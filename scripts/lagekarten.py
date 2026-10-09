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
point moved, and why), `north` (lon/lat points from the line's north end to the top edge of the world that close
the Soviet side; along the Gulf of Finland for a line beginning at Leningrad, so that the Karelian Isthmus is not
cut) and the pockets that a single line cannot express (encircled forces, bridgeheads), as lon/lat
polygons drawn after the map. A second-order polynomial fitted to the control points (least squares) turns
pixels into lon/lat; its residuals are written out with the result.

Writes curated/frontlines_<year>/<date>.geojson (python3 scripts/lagekarten.py [year ...], both years by default) with the front line and the polygons the control rules use:
  soviet   east of the line (open to the east and south; `north` closes it from the line's north end)
  axis     west of the line
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
# The two sides are open polygons: nothing inside the Soviet Union may be cut by an edge of them other than the line
# itself (fixed edges at 40N, 60N or 60E cut whole provinces along straight lines). Behind the line everything is
# taken as German; the control rules hand the Romanian and Finnish zones of the base date back afterwards.
WORLD = box(-30, 0, 180, 90)


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


def sides(line, north):
    """The Soviet side: east of the line, closed through the south, the east and the top of the world, and back to
    the line's north end by `north` (points from the line's north end up to the top edge; by default straight
    north). The axis side: the rest of the world west of it."""
    lon_s = line[-1][0]
    ring = list(line) + [(lon_s, 0), (180, 0), (180, 90)] + [tuple(p) for p in reversed(north)]
    soviet = Polygon(ring).buffer(0)
    return soviet, WORLD.difference(soviet)


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
        soviet, axis = sides(line, d.get("north", [(line[0][0], 90)]))
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
