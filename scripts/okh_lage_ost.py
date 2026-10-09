"""Download the OKH "Lage Ost" situation maps of 1942 (first of each month) from germandocsinrussia.org.

Source: Central Archive of the Russian Ministry of Defence (ЦАМО / CAMO), Fond 500, Findbuch (opis) 12457,
"Karten zur Lage Ost": maps of the Operationsabteilung IIIb of the Generalstab des Heeres in the OKH, one file
(Akte) per day, each with two sheets (Blatt Nord and Blatt Süd of the 1:1,000,000 "Operationskarte Osten").
Digitised by the Russian-German project for the digitisation of German documents in Russian archives
(https://germandocsinrussia.org).

The site offers the sheets at up to 1966 px wide; the full scan is only served as 256 px map tiles
(OpenLayers XYZ on the default EPSG:4326 grid: zoom z is 2^z x 2^(z-1) tiles; the scan is scaled to the full
height and centred). This script stitches the tiles of one zoom level and crops them to the scan.

    python3 scripts/okh_lage_ost.py              # zoom 5 (4096 px high), into okh_lage_ost_1942/
    python3 scripts/okh_lage_ost.py --zoom 6     # near the scan resolution (8192 px high)

Writes <date>_<sheet>.jpg and catalog.csv (date asked, date of the map, Akte, sheet, URLs).
"""
import argparse
import concurrent.futures as cf
import csv
import io
import re
import time
from pathlib import Path

import requests
from PIL import Image

from common import ROOT

SITE = "https://wwii.germandocsinrussia.org"

# 1 Jun and 1 Jul 1942 are missing from the Findbuch (Akte 345 is 31.5., 346 is 2.6.; 374 is 30.6., 375 is 2.7.).
# The maps are "Stand ... abends", so the map of the evening before is the situation on the morning of the 1st.
FILES = [  # (date asked, map date, Akte, node id)
    ("1942-01-01", "1942-01-01", 195, 20601),
    ("1942-02-01", "1942-02-01", 226, 20632),
    ("1942-03-01", "1942-03-01", 254, 20660),
    ("1942-04-01", "1942-04-01", 285, 20691),
    ("1942-05-01", "1942-05-01", 315, 20721),
    ("1942-06-01", "1942-05-31", 345, 20751),
    ("1942-07-01", "1942-06-30", 374, 20780),
    ("1942-08-01", "1942-08-01", 405, 20811),
    ("1942-09-01", "1942-09-01", 436, 20842),
    ("1942-10-01", "1942-10-01", 466, 20872),
    ("1942-11-01", "1942-11-01", 497, 20903),
    ("1942-12-01", "1942-12-01", 527, 20933),
]

session = requests.Session()
session.headers["User-Agent"] = "World_Map_History research script"


def get(url, tries=6):
    for i in range(tries):
        try:
            r = session.get(url, timeout=60)
            if r.status_code in (200, 404):
                return r
        except requests.RequestException:
            pass
        time.sleep(2 ** i)
    raise RuntimeError(f"failed: {url}")


def sheets(node):
    """Page ids, scan sizes and tile paths of one Akte."""
    html = get(f"{SITE}/de/nodes/{node}").text
    pages = re.search(r"pages: (\[.*?\]),\n", html).group(1)
    out = []
    for pid, w, h in re.findall(r'"id":(\d+),"w":(\d+),"h":(\d+)', pages):
        m = get(f"{SITE}/pages/{pid}/map").text
        path = re.search(r"create_map\('map', '([^']+)'\)", m).group(1)
        out.append((int(pid), int(w), int(h), path))
    return out


def stitch(path, w, h, zoom, workers=4):
    """The scan is scaled to the height of the grid (2^(z-1) tiles) and centred on the grid's middle column."""
    rows = 1 << (zoom - 1)
    H = rows * 256
    W = round(H * w / h)
    left = rows * 256 - W // 2                 # pixel x of the scan's left edge (grid is 2*rows tiles wide)
    cols = range(left // 256, (left + W - 1) // 256 + 1)
    jobs = [(x, y) for x in cols for y in range(rows)]

    def tile(xy):
        x, y = xy
        r = get(f"{SITE}{path}/{zoom}/{x}_{y}.jpg")
        return xy, (r.content if r.status_code == 200 else None)

    canvas = Image.new("RGB", (len(cols) * 256, H), (0, 0, 0))
    with cf.ThreadPoolExecutor(workers) as ex:
        for (x, y), data in ex.map(tile, jobs):
            if data:
                canvas.paste(Image.open(io.BytesIO(data)).convert("RGB"), ((x - cols[0]) * 256, y * 256))
    off = left - cols[0] * 256
    return canvas.crop((off, 0, off + W, H))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zoom", type=int, default=5)
    ap.add_argument("--out", type=Path, default=ROOT / "okh_lage_ost_1942")
    ap.add_argument("--only", nargs="*", help="dates asked, e.g. 1942-01-01")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for asked, date, akte, node in FILES:
        if args.only and asked not in args.only:
            continue
        for i, (pid, w, h, path) in enumerate(sheets(node), 1):
            name = f"{asked}_blatt{i}.jpg"
            dest = args.out / name
            if not dest.exists():
                img = stitch(path, w, h, args.zoom)
                img.save(dest, quality=88, optimize=True)
                print(name, img.size, flush=True)
            rows.append(dict(date_asked=asked, map_date=date, archive_ref=f"CAMO 500/12457/{akte}, sheet {i}",
                             file=name, page_url=f"{SITE}/de/nodes/{node}", sheet_view=f"{SITE}/pages/{pid}/map",
                             scan_px=f"{w}x{h}"))
    with open(args.out / "catalog.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)


if __name__ == "__main__":
    main()
