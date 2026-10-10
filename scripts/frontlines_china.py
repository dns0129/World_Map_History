"""The Japanese-occupied area of China in 1942 from the Japanese Army's situation maps.

Source: the general situation map of the Chinese army in late August 1941 (中國軍全般図 昭和十六年八月下旬における),
appendix 2 of the official war history Senshi Sōsho vol. 55 (「昭和十七、八年の支那派遣軍」, National Institute for
Defense Studies, Japan), redrawn from the China Expeditionary Army's map of 16 September 1941 (JACAR Ref.
C11110508500); its blue line bounds the area the Japanese army held (我軍占據地域). curated/china_front_<year>.json holds:
  sheets   per map: its control points (towns read on the image, full-resolution pixels, with their present-day
           coordinates; a second-order polynomial fitted to them, as in lagekarten.py), the main line (from the
           Mengjiang border down western Shanxi, the Yellow River, the 1938 flood zone, round the Dabie mountains
           to Yichang and back along the south bank of the Yangtze to the coast at Ningbo) and the other lines, in
           pixels. The lines were taken from the image by colour (the blue ink only) and followed between waypoints
           read by eye; `head`, `tail` and `close` (lon/lat) take the main line out to the Mengjiang border and to
           sea round the occupied side, `closure` does the same for a line that ends on the coast.
  dates    per date the sheet it starts from and `add` / `cut`: lon/lat areas the date's events add to the occupied
           area or take from it (the 1942 Zhejiang-Jiangxi campaign after the operation maps of the same volume,
           western Yunnan from May 1942, the third battle of Changsha), each with its note; `whole` marks an addition
           that is not an approximation of the date's events (the whole of Hainan, held since 1939).
A line's side: "chinese" lines enclose Chinese-held pockets behind the line (Nationalist armies; the Communist base
areas are a layer of their own on the base date), "japanese" lines enclose Japanese-held enclaves (Canton,
Shantou, northern Hainan).

Writes curated/frontlines_china_<year>/<date>.geojson (python3 scripts/frontlines_china.py [year ...]):
  front      the main line
  japanese   the occupied area
  chinese    the rest of the box China lies in
  added      the part of the occupied area the date's `add` entries contribute (not those marked `whole`)
"""
import json
import sys
from pathlib import Path

from shapely.geometry import LineString, Polygon, box, mapping
from shapely.ops import unary_union

from lagekarten import Georef

ROOT = Path(__file__).resolve().parent.parent
YEARS = ("1942",)
CHINA = box(70, 15, 140, 56)


def lonlat(georef, pixels):
    lon, lat = georef.lonlat([p[0] for p in pixels], [p[1] for p in pixels])
    return [(round(float(a), 4), round(float(b), 4)) for a, b in zip(lon, lat)]


def main(year):
    data = json.loads((ROOT / "curated" / f"china_front_{year}.json").read_text())
    out = ROOT / "curated" / f"frontlines_china_{year}"
    out.mkdir(exist_ok=True)
    sheets = {}
    for name, sh in data["sheets"].items():
        g = Georef(sh["gcps"])
        m = sh["main"]
        line = [tuple(p) for p in m["head"]] + lonlat(g, m["pixels"]) + [tuple(p) for p in m["tail"]]
        occupied = Polygon(line + [tuple(p) for p in m["close"]]).buffer(0)
        chinese, japanese = [], []
        for pname, p in sh["lines"].items():
            ring = lonlat(g, p["pixels"]) + [tuple(q) for q in p.get("closure", [])]
            (chinese if p["side"] == "chinese" else japanese).append(Polygon(ring).buffer(0))
        occupied = occupied.difference(unary_union(chinese)).union(unary_union(japanese))
        sheets[name] = (line, occupied, g.residuals)
    for date, d in sorted(data["dates"].items()):
        line, occupied, residuals = sheets[d["sheet"]]
        added = unary_union([Polygon(a["lonlat"]).buffer(0) for a in d.get("add", []) if not a.get("whole")])
        for a in d.get("add", []):
            occupied = occupied.union(Polygon(a["lonlat"]).buffer(0))
        for c in d.get("cut", []):
            occupied = occupied.difference(Polygon(c["lonlat"]).buffer(0))
        feats = [dict(type="Feature", properties=dict(side="front"), geometry=mapping(LineString(line))),
                 dict(type="Feature", properties=dict(side="japanese"), geometry=mapping(occupied)),
                 dict(type="Feature", properties=dict(side="chinese"), geometry=mapping(CHINA.difference(occupied)))]
        if not added.is_empty:  # what the date's events add, written after the histories (approximate)
            feats.append(dict(type="Feature", properties=dict(side="added"), geometry=mapping(added.intersection(occupied))))
        sh = data["sheets"][d["sheet"]]
        src = dict(map=sh["title"], map_date=sh["map_date"], url=sh["url"], original=sh.get("original"),
                   residuals_km=residuals, changes=[a["note"] for a in d.get("add", []) + d.get("cut", [])])
        (out / f"{date}.geojson").write_text(json.dumps(dict(type="FeatureCollection", source=src, features=feats),
                                                        ensure_ascii=False, separators=(",", ":")))
        print(date, len(line), "points;", len(d.get("add", [])), "added,", len(d.get("cut", [])), "cut; residuals up to",
              max(residuals.values()), "km")


if __name__ == "__main__":
    for y in sys.argv[1:] or YEARS:
        main(y)
