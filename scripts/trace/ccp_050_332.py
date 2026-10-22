"""Trace the red (unpacified) areas of the North China Area Army's map of September 1942 into curated/ccp_areas.json.

  python3 scripts/trace/ccp_050_332.py           trace and write the rings of north_china_1942_09
  python3 scripts/trace/ccp_050_332.py --check   trace and compare with the json in the repository (no write)

Map: 北支那方面軍占據地域内治安概況 (Senshi Sosho vol. 50, appendix 5; NIDS 050_332, downloaded by nids.py), whose
unpacified areas are a red stipple. The control points, the other sheets of ccp_areas.json and the `minus` corridors
are read by eye and kept as they are; only the rings of the red areas come from here:
  1. red pixels: r > g + 45 and r > b + 45
  2. their density in 8 x 8 px cells, smoothed over 5 x 5 cells; cells over 0.08 (the stipple, not stray red ink)
  3. closed and opened twice, holes filled, parts under 60 cells dropped; the four text blocks of the map cleared
  4. outer outlines over 40 cells, simplified to 1.2 cells, in full-resolution pixels (cell centres)
Afterwards: python3 scripts/ccp_areas.py.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import ROOT  # noqa: E402
from nids import fetch  # noqa: E402

JSON = ROOT / "curated" / "ccp_areas.json"
CELL = 8
TEXT = [(1580, 1555, 2490, 3840), (7210, 780, 8225, 2520), (7290, 4410, 8250, 5350), (830, 5400, 1115, 6435)]  # px


def trace():
    Image.MAX_IMAGE_PIXELS = None
    im = np.asarray(Image.open(fetch("050_332")).convert("RGB")).astype(np.int16)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    red = (r > g + 45) & (r > b + 45)
    h, w = red.shape[0] // CELL * CELL, red.shape[1] // CELL * CELL
    dens = red[:h, :w].reshape(h // CELL, CELL, w // CELL, CELL).mean((1, 3))
    m = ndi.uniform_filter(dens, 5) > 0.08
    m = ndi.binary_closing(m, iterations=2)
    m = ndi.binary_fill_holes(m)
    m = ndi.binary_opening(m, iterations=2)
    lab, n = ndi.label(m)
    m = np.isin(lab, 1 + np.where(ndi.sum(m, lab, range(1, n + 1)) >= 60)[0]).astype(np.uint8)
    for x0, y0, x1, y1 in TEXT:
        m[y0 // CELL:y1 // CELL + 1, x0 // CELL:x1 // CELL + 1] = 0
    cs, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    rings = []
    for i, c in enumerate(cs):
        if hier[0][i][3] != -1 or cv2.contourArea(c) < 40:
            continue
        c = cv2.approxPolyDP(c, 1.2, True)
        if len(c) >= 3:
            rings.append([[int(p[0][0] * CELL + CELL // 2), int(p[0][1] * CELL + CELL // 2)] for p in c])
    return rings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    data = json.loads(JSON.read_text())
    area = data["sheets"]["050_332"]["areas"]["north_china_1942_09"]
    rings = trace()
    if args.check:
        same = rings == area["rings"]
        print(f"{len(rings)} rings traced, {len(area['rings'])} in the repository: {'identical' if same else 'DIFFERENT'}")
        sys.exit(0 if same else 1)
    area["rings"] = rings
    JSON.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {len(rings)} rings - then python3 scripts/ccp_areas.py")


if __name__ == "__main__":
    main()
