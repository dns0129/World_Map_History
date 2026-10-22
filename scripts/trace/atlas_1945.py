"""Trace the 1945 pages of the War Department's atlas into curated/atlas_1945.json (the input of atlas_fronts.py).

  python3 scripts/trace/atlas_1945.py            download the atlas (sources.json "files"), trace, write the json
  python3 scripts/trace/atlas_1945.py --check    trace and compare with the json in the repository (no write)

Steps (each date one "War against Germany" page; the hand-made parts of the json, `divider`, `extra_soviet` and
the per-date `corrections`, are kept as they are):
  1. pages     the scans embedded in the PDF, extracted unchanged (pdfimages -j, poppler-utils)
  2. gcps      the city circles of curated/trace/atlas_1945_cities.json, read on page 82, each moved to the centre
               of the nearest circle found by a Hough transform (within 9 px); points with a residual over 30 km of
               the second-order polynomial are dropped and the fit repeated. The other pages are prints of the same
               base map: their control points are those of page 82 carried over by a homography fitted (RANSAC) to
               SIFT feature matches between the two pages (median error about 0.5 px)
  3. allied    Allied-held ground is pink, that taken in the phase dark red: pixels with r-g > 12 and r-b > 14
               inside the map (rows 150-1380), opened and closed twice, holes under 400 px filled (lakes, labels;
               the larger holes are German pockets), parts under 150 px dropped; then grown over the sea by up to
               12 px (a geodesic dilation through pixels that are not grey land, kept 5 px clear of it: German land
               is light grey, neutral countries darker grey), so that the area reaches the coastline of the
               provinces; outlines simplified to 1 px (Douglas-Peucker)
  4. sheet     the map's frame on the page: below the title band (the first row whose brightness jumps, + 10 px),
               12 px inside the left edge, 15 px inside the right, 8 px above row 1380 (the text below)
"""
import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import RAW, ROOT  # noqa: E402
from lagekarten import Georef  # noqa: E402
from sources import load  # noqa: E402

JSON = ROOT / "curated" / "atlas_1945.json"
CITIES = ROOT / "curated" / "trace" / "atlas_1945_cities.json"
PAGES = {"1945-01-01": 82, "1945-02-01": 86, "1945-03-01": 90, "1945-04-01": 94, "1945-05-01": 98}
TOP, BOTTOM = 150, 1380          # map rows: below the title band, above the text
SEA_PX, LAND_CLEAR = 12, 5


def pdf():
    f = load()["files"]["atlas_1945"]
    path = RAW / f["dest"]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(f["url"], headers={"User-Agent": "World_Map_History build (trace/atlas_1945.py)"})
        with urllib.request.urlopen(req, timeout=300) as r:
            path.write_bytes(r.read())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != f["sha256"]:
        raise SystemExit(f"{path}: sha256 {digest} is not the one sources.json pins")
    return path


def page(n):
    out = pdf().parent / f"pg{n}-000.jpg"
    if not out.exists():
        subprocess.run(["pdfimages", "-f", str(n), "-l", str(n), "-j", str(pdf()), str(out.parent / f"pg{n}")], check=True)
    return out


def gcps_82():
    im = cv2.imread(str(page(82)), 0)
    circles = cv2.HoughCircles(cv2.GaussianBlur(im, (3, 3), 0), cv2.HOUGH_GRADIENT, dp=1, minDist=8, param1=80,
                               param2=10, minRadius=3, maxRadius=8)[0]
    pts = []
    for c in json.loads(CITIES.read_text())["cities"]:
        d, cx, cy = min((float(np.hypot(x - c["x"], y - c["y"])), float(x), float(y)) for x, y, _ in circles)
        x, y = (round(cx), round(cy)) if d <= 9 else (c["x"], c["y"])
        pts.append(dict(name=c["name"], x=x, y=y, lon=c["lon"], lat=c["lat"]))
    while True:
        g = Georef(pts)
        bad = [k for k, v in g.residuals.items() if v > 30]
        if not bad:
            print(f"page 82: {len(pts)} control points, residuals median {statistics.median(g.residuals.values()):.1f} km")
            return pts
        pts = [p for p in pts if p["name"] not in bad]


def carry(gcps, n):
    """The control points of page 82 on page n: a homography fitted to SIFT matches between the two prints."""
    cv2.setRNGSeed(0)
    sift = cv2.SIFT_create(15000)

    def features(path):
        im = cv2.imread(str(path), 0)
        mask = np.zeros_like(im)
        mask[TOP:BOTTOM, :] = 255
        return sift.detectAndCompute(im, mask)

    ka, da = features(page(82))
    kb, db = features(page(n))
    good = [x for x, y in cv2.BFMatcher().knnMatch(da, db, k=2) if x.distance < 0.7 * y.distance]
    src = np.float32([ka[m.queryIdx].pt for m in good])
    dst = np.float32([kb[m.trainIdx].pt for m in good])
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    err = np.linalg.norm(cv2.perspectiveTransform(src[inl.ravel() == 1][None], H)[0] - dst[inl.ravel() == 1], axis=1)
    print(f"page {n}: {int(inl.sum())} of {len(good)} matches, median error {float(np.median(err)):.2f} px")
    q = cv2.perspectiveTransform(np.float32([[g["x"], g["y"]] for g in gcps])[None], H)[0]
    return [dict(g, x=round(float(x), 1), y=round(float(y), 1)) for g, (x, y) in zip(gcps, q)]


def rings_of(mask, holes=True):
    cs, hier = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP if holes else cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for i, c in enumerate(cs):
        c = cv2.approxPolyDP(c, 1.0, True)
        if len(c) >= 3:
            out.append(dict(hole=bool(holes and hier[0][i][3] != -1), pts=[[int(q[0][0]), int(q[0][1])] for q in c]))
    return out


def allied(n):
    bgr = cv2.imread(str(page(n)))
    im = bgr[..., ::-1].astype(int)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    m = (r - g > 12) & (r - b > 14)
    frame = np.zeros(m.shape, bool)
    frame[TOP:BOTTOM, :] = True
    m &= frame
    m = ndi.binary_opening(m, iterations=2)
    m = ndi.binary_closing(m, iterations=2)
    holes = ndi.binary_fill_holes(m) & ~m
    hl, hn = ndi.label(holes)
    m |= np.isin(hl, 1 + np.where(ndi.sum(holes, hl, range(1, hn + 1)) < 400)[0])
    lab, k = ndi.label(m)
    m = np.isin(lab, 1 + np.where(ndi.sum(m, lab, range(1, k + 1)) >= 150)[0])
    traced = rings_of(m)
    pockets = [r for r in traced if r["hole"]]
    # over the sea: never into grey (German, neutral) land
    hsv = cv2.cvtColor(cv2.GaussianBlur(bgr, (5, 5), 0), cv2.COLOR_BGR2HSV)
    land = ((hsv[..., 1] <= 9) & (hsv[..., 0] < 42) & (hsv[..., 2] >= 150)).astype(np.uint8)
    land = cv2.morphologyEx(land, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    allowed = cv2.dilate(land, np.ones((2 * LAND_CLEAR + 1,) * 2, np.uint8)) == 0
    grown = np.zeros(m.shape, np.uint8)   # grown from the simplified outer outlines, as they were traced
    for r in traced:
        if not r["hole"]:
            cv2.fillPoly(grown, [np.array(r["pts"], np.int32)], 1)
    for _ in range(SEA_PX):
        grown = np.maximum(grown, (cv2.dilate(grown, np.ones((3, 3), np.uint8)) > 0) & allowed).astype(np.uint8)
    cs, _ = cv2.findContours(grown, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outer = []
    for c in cs:
        if cv2.contourArea(c) >= 30:
            ap = cv2.approxPolyDP(c, 1.0, True).reshape(-1, 2)
            if len(ap) >= 3:
                outer.append(dict(hole=False, pts=ap.tolist()))
    return outer + pockets


def sheet(n):
    im = cv2.imread(str(page(n)), 0).astype(float)
    rows = im[100:260, 300:1000].mean(1)
    top = 100 + int(np.argmax(np.diff(rows))) + 1
    return [12, top + 10, im.shape[1] - 15, BOTTOM - 8]


def trace():
    data = json.loads(JSON.read_text())
    g82 = gcps_82()
    for date, n in PAGES.items():
        d = data["dates"][date]
        d["page"] = str(n)
        d["gcps"] = g82 if n == 82 else carry(g82, n)
        d["allied"] = allied(n)
        d["sheet"] = sheet(n)
        print(date, f"page {n}: {len(d['allied'])} rings, sheet {d['sheet']}")
    return data


def compare(new, old):
    """Largest differences between a fresh trace and the json in the repository."""
    for date in PAGES:
        a, b = new["dates"][date], old["dates"][date]
        dg = max(abs(p["x"] - q["x"]) + abs(p["y"] - q["y"]) for p, q in zip(a["gcps"], b["gcps"])) \
            if len(a["gcps"]) == len(b["gcps"]) else float("inf")
        area = lambda d: sum((-1 if r["hole"] else 1) * cv2.contourArea(np.array(r["pts"], np.int32)) for r in d["allied"])
        print(f"{date}: control points {len(a['gcps'])}/{len(b['gcps'])}, largest move {dg:.1f} px; Allied area "
              f"{area(a):.0f}/{area(b):.0f} px; sheet {a['sheet']}/{b['sheet']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    new = trace()
    if args.check:
        compare(new, json.loads(JSON.read_text()))
    else:
        JSON.write_text(json.dumps(new, separators=(",", ":")))
        print("wrote", JSON.relative_to(ROOT), "- then python3 scripts/atlas_fronts.py")


if __name__ == "__main__":
    main()
