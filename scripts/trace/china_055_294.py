"""Trace the Japanese-held area of the general situation map of late August 1941 into curated/china_front_1942.json.

  python3 scripts/trace/china_055_294.py           snap the waypoints to the blue line, write the sheet's pixels
  python3 scripts/trace/china_055_294.py --check   compare with the json in the repository (no write)

Map: 中國軍全般図（昭和十六年八月下旬における）, Senshi Sosho vol. 55, appendix 2 (NIDS 055_294, nids.py), whose
blue line marks the area the Japanese army held. The corners of the line were read by eye
(curated/trace/china_055_294_waypoints.json); between consecutive corners the line is found on the map:
  1. blue pixels: b > r + 40, b > g + 5, b > 120; dilated 5 x 5 and pooled 2 x 2 (max) so the thin line survives
  2. the cheapest path between two corners on that grid (Dijkstra, 8 neighbours): cost 1 on blue, 12 elsewhere, so
     gaps where red or black lines cross the blue one are bridged straight but the line itself is followed
  3. simplified to 3 px (Douglas-Peucker); a closed ring ends at its first corner
The control points, the closures at sea, the `fix` and the dates of china_front_1942.json are kept as they are.
Afterwards: python3 scripts/frontlines_china.py.
"""
import argparse
import heapq
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import ROOT  # noqa: E402
from nids import fetch  # noqa: E402

JSON = ROOT / "curated" / "china_front_1942.json"
WAYPOINTS = ROOT / "curated" / "trace" / "china_055_294_waypoints.json"
OFF, MARGIN = 12.0, 60
STEPS = [(-1, -1, 1.414), (-1, 0, 1), (-1, 1, 1.414), (0, -1, 1), (0, 1, 1), (1, -1, 1.414), (1, 0, 1), (1, 1, 1.414)]


def blue_grid():
    Image.MAX_IMAGE_PIXELS = None
    im = np.asarray(Image.open(fetch("055_294")).convert("RGB")).astype(int)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    blue = ((b > r + 40) & (b > g + 5) & (b > 120)).astype(np.uint8)
    blue = cv2.dilate(blue, np.ones((5, 5), np.uint8))
    h, w = blue.shape
    return blue[:h // 2 * 2, :w // 2 * 2].reshape(h // 2, 2, w // 2, 2).max(axis=(1, 3)) > 0


def segment(grid, a, b):
    """The cheapest path from corner a to corner b (full-resolution pixels) along the blue grid."""
    a, b = (a[0] // 2, a[1] // 2), (b[0] // 2, b[1] // 2)
    x0, x1 = max(0, min(a[0], b[0]) - MARGIN), min(grid.shape[1] - 1, max(a[0], b[0]) + MARGIN)
    y0, y1 = max(0, min(a[1], b[1]) - MARGIN), min(grid.shape[0] - 1, max(a[1], b[1]) + MARGIN)
    sub = grid[y0:y1 + 1, x0:x1 + 1]
    h, w = sub.shape
    cost = np.where(sub, 1.0, OFF)
    dist = np.full((h, w), np.inf)
    prev = {}
    s, t = (a[1] - y0, a[0] - x0), (b[1] - y0, b[0] - x0)
    dist[s] = 0
    queue = [(0, s)]
    while queue:
        d, u = heapq.heappop(queue)
        if u == t:
            break
        if d > dist[u]:
            continue
        for dy, dx, step in STEPS:
            v = (u[0] + dy, u[1] + dx)
            if 0 <= v[0] < h and 0 <= v[1] < w:
                nd = d + step * cost[v]
                if nd < dist[v]:
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(queue, (nd, v))
    path = [t]
    while path[-1] != s:
        path.append(prev[path[-1]])
    path.reverse()
    pts = [((x + x0) * 2, (y + y0) * 2) for y, x in path]
    return cv2.approxPolyDP(np.array(pts, np.int32).reshape(-1, 1, 2), 3.0, False).reshape(-1, 2).tolist()


def snap(grid, corners):
    out = []
    for a, b in zip(corners, corners[1:]):
        seg = segment(grid, a, b)
        out += seg if not out else seg[1:]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    grid = blue_grid()
    wp = json.loads(WAYPOINTS.read_text())
    data = json.loads(JSON.read_text())
    sheet = data["sheets"]["055_294"]
    new_main = snap(grid, [tuple(p) for p in wp["main"]])
    new_lines = {}
    for name, v in wp["lines"].items():
        corners = [tuple(p) for p in v["pts"]] + ([tuple(v["pts"][0])] if v["closed"] else [])
        new_lines[name] = snap(grid, corners)
        print(f"{name}: {len(new_lines[name])} points")
    if args.check:
        same = new_main == sheet["main"]["pixels"] and all(new_lines[k] == sheet["lines"][k]["pixels"] for k in new_lines)
        print("main line and", len(new_lines), "lines:", "identical" if same else "DIFFERENT")
        sys.exit(0 if same else 1)
    sheet["main"]["pixels"] = new_main
    for name, pixels in new_lines.items():
        sheet["lines"].setdefault(name, {})["side"] = wp["lines"][name]["side"]
        sheet["lines"][name]["pixels"] = pixels
    JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print("wrote", JSON.relative_to(ROOT), "- then python3 scripts/frontlines_china.py")


if __name__ == "__main__":
    main()
