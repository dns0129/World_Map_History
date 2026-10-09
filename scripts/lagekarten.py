"""Front lines of the Eastern Front in 1941 and 1942 from the German Army High Command's situation maps ("Lage Ost").

Source: the daily maps of the Operations Branch (Operationsabteilung IIIb) of the General Staff of the Army,
Central Archive of the Russian Ministry of Defence (CAMO), Bestand 500, Findbuch 12457, published by the
German-Russian digitisation project (wwii.germandocsinrussia.org, use for research only, as its user agreement
says). For each date one map (one to three sheets) is used; curated/lagekarten_<year>.json holds, per sheet:
  gcps   control points: towns and coast features whose position on the sheet was read from the scan
         (pixels of the site's preview, 1966 pixels wide) with their present-day coordinates
  front  the German main line of resistance (blue) read along the sheet, north to south, in the same pixels
         (empty where the line is written as lon/lat and the sheet serves to check it by overlay)
A sheet entry may instead be {"lonlat": [...], "note": ...}: a stretch of the line written as lon/lat after the
map where pixels could not be read along it (a complicated salient, a fold of the paper, a gauze strip, Army Group
A shown by its units only), or taken over unchanged from the month before after an overlay check. The same page may
appear in several entries, each fitted to its own control points (a large sheet fitted in parts). Per date `head` and `tail`
(lon/lat points taking the line's ends into the sea, so that the far shore falls on the right side), `adjustments` (any
point moved, and why) and the pockets that a single line cannot express (encircled forces, bridgeheads), as lon/lat
polygons drawn after the map. A second-order polynomial fitted to the control points (least squares) turns
pixels into lon/lat; its residuals are written out with the result.

Writes curated/frontlines_<year>/<date>.geojson (python3 scripts/lagekarten.py [year ...], both years by default) with the front line and the polygons the control rules use:
  soviet   east of the line (closed far to the east and south, and north along the Leningrad front)
  axis     west of the line, up to AXIS_DEG behind it
  soviet_pocket, axis_pocket   the pockets
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Polygon, box, mapping

ROOT = Path(__file__).resolve().parent.parent
YEARS = ("1941", "1942")
AXIS_DEG = 2.5          # the axis side reaches this far behind the line (degrees), not to the rear areas
EAST, SOUTH = 60.0, 40.0
NORTH_WEST = 60.0       # north edge west of Lake Ladoga: the Karelian Isthmus beyond belongs to the Finnish front
NORTH_EAST = 60.6       # north edge east of the lake (Svir front)


def terms(u, v):
    u, v = np.asarray(u, float), np.asarray(v, float)
    return np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], -1)


class Georef:
    """Preview pixels -> lon/lat by a second-order polynomial fitted to the control points."""

    def __init__(self, gcps):
        P = np.array([[g["x"], g["y"]] for g in gcps], float)
        L = np.array([[g["lon"], g["lat"]] for g in gcps], float)
        self.mean = L.mean(0)
        self.coef = np.linalg.lstsq(terms(P[:, 0] / 1000, P[:, 1] / 1000), L - self.mean, rcond=None)[0]
        self.residuals = {g["name"]: round(self.km(*self.lonlat(g["x"], g["y"]), g["lon"], g["lat"]), 1) for g in gcps}

    def lonlat(self, x, y):
        r = terms(np.asarray(x) / 1000, np.asarray(y) / 1000) @ self.coef + self.mean
        return r[..., 0], r[..., 1]

    @staticmethod
    def km(lon1, lat1, lon2, lat2):
        return math.hypot((lon1 - lon2) * 111.32 * math.cos(math.radians(lat2)), (lat1 - lat2) * 110.57)


def sides(line):
    """The Soviet side (east of the line, closed far to the east and south and north around Leningrad) and the
    axis side (the rest of the front zone up to AXIS_DEG west of the line)."""
    lon_n, lon_s = line[0][0], line[-1][0]
    ring = list(line) + [(lon_s, SOUTH), (EAST, SOUTH), (EAST, NORTH_EAST), (33.0, NORTH_EAST), (32.6, NORTH_WEST),
                         (lon_n, NORTH_WEST)]
    soviet = Polygon(ring).buffer(0)
    zone = LineString(line).buffer(AXIS_DEG)
    axis = zone.intersection(box(20, SOUTH, EAST, NORTH_WEST)).difference(soviet)
    return soviet, axis


def main(year):
    data = json.loads((ROOT / "curated" / f"lagekarten_{year}.json").read_text())
    out = ROOT / "curated" / f"frontlines_{year}"
    out.mkdir(exist_ok=True)
    for date, d in sorted(data["dates"].items()):
        line, report = [tuple(p) for p in d.get("head", [])], {}  # the line's north end taken out to sea, lon/lat
        for sheet in d["sheets"]:
            if "lonlat" in sheet:  # a stretch written as lon/lat after the map (see its note)
                line += [tuple(p) for p in sheet["lonlat"]]
                continue
            g = Georef(sheet["gcps"])
            report[str(sheet["page"])] = g.residuals
            if not sheet.get("front"):  # a sheet georeferenced only to check the lon/lat stretches against it
                continue
            lon, lat = g.lonlat([p[0] for p in sheet["front"]], [p[1] for p in sheet["front"]])
            line += [(round(float(a), 4), round(float(b), 4)) for a, b in zip(lon, lat)]
        line += [tuple(p) for p in d.get("tail", [])]  # the line taken on to the coast, lon/lat
        soviet, axis = sides(line)
        feats = [dict(type="Feature", properties=dict(side="front"), geometry=mapping(LineString(line))),
                 dict(type="Feature", properties=dict(side="soviet"), geometry=mapping(soviet)),
                 dict(type="Feature", properties=dict(side="axis"), geometry=mapping(axis))]
        for p in d.get("pockets", []):
            feats.append(dict(type="Feature", properties=dict(side=p["side"] + "_pocket", name=p["name"], note=p["note"]),
                              geometry=mapping(Polygon(p["lonlat"]))))
        src = dict(archive="CAMO, Bestand 500, Findbuch 12457, Akte " + d["akte"], map_date=d["map_date"],
                   url=d["url"], residuals_km=report)
        (out / f"{date}.geojson").write_text(json.dumps(dict(type="FeatureCollection", source=src, features=feats),
                                                        ensure_ascii=False, separators=(",", ":")))
        worst = max((v for r in report.values() for v in r.values()), default=0)
        print(date, len(line), "points; control point residuals up to", worst, "km")


if __name__ == "__main__":
    for y in sys.argv[1:] or YEARS:
        main(y)
