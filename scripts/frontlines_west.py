"""Front lines of the Western Front in 1944 from the daily situation maps of the US Twelfth Army Group.

Source: "HQ Twelfth Army Group situation map", one sheet per day from 6 June 1944 to July 1945, Library of Congress,
Geography and Map Division, World War II Military Situation Maps (www.loc.gov/collections/world-war-ii-maps-military-
situation-maps-from-1944-to-1945; US government work, no known copyright restrictions). curated/loc_west_<year>.json
holds, per date, the sheet used (its LOC item and image id; pixels are those of the IIIF image at pct:50) and:
  gcps   control points with their lon/lat: graticule intersections (the 1:500,000 sheets of the Normandy period) or
         towns read on the sheet (the 1:1,000,000 outline maps of the autumn)
  ticks  border ticks of a sheet whose edges are not graticule lines: a "lon" tick on the bottom edge fixes only the
         longitude at its pixel, a "lat" tick on the right edge only the latitude
  front  the front line ("front line" symbol, a heavy line with ticks on the enemy side) read along the sheet
A stretch may instead be {"lonlat": [...], "note": ...}: written as lon/lat after the map where no front line is drawn
(the sheets of the pursuit in September and of 1 October show unit positions only; the line then runs between the
Allied and German unit symbols, along the features named in the note) or where the line leaves the sheet.
The sheets are drawn on a conical orthomorphic (Lambert conformal conic) projection ("Projection Europe (Air)
Conical Orthomorphic"): a Lambert conformal conic of cone constant n with a similarity transform (scale, rotation,
offset) is fitted to the control points (least squares, n by search), each tick contributing the point on its edge
whose other coordinate the model gives (repeated until stable); residuals are written out with the result.
Per date `head` and `tail` take the line's ends out to sea or to a neutral border, `close` returns from the tail to
the head round the Allied side, `adjustments` records any point moved and why, and `pockets` are lon/lat polygons the line cannot express (German pockets behind the
Allied front: Dunkirk, the Atlantic ports; side "allied" for Allied areas beyond a German corridor, as southern
France on 1 September). A pocket drawn on the sheet is given in pixels and closed along the coast by lon/lat points.

Writes curated/frontlines_west_<year>/<date>.geojson (python3 scripts/frontlines_west.py [year ...]):
  front         the front line
  allied        the Allied side (head + line + tail + close)
  axis          the rest of the box the Western Front lies in
  axis_pocket   German pockets behind the Allied front
  allied_pocket Allied areas the line does not reach
"""
import json
import math
import sys
from pathlib import Path

from shapely.geometry import LineString, Polygon, box, mapping

from georef import LambertSheet, line_lonlat

ROOT = Path(__file__).resolve().parent.parent
YEARS = ("1944",)
WEST = box(-30, 30, 30, 62)


def main(year):
    data = json.loads((ROOT / "curated" / f"loc_west_{year}.json").read_text())
    out = ROOT / "curated" / f"frontlines_west_{year}"
    out.mkdir(exist_ok=True)
    for date, d in sorted(data["dates"].items()):
        sheet = LambertSheet(d["gcps"], d.get("ticks", []))
        line = [tuple(p) for p in d.get("head", [])]
        for part in d["front"]:
            if "lonlat" in part:
                line += [tuple(p) for p in part["lonlat"]]
            else:
                line += line_lonlat(sheet, part["pixels"])
        line += [tuple(p) for p in d.get("tail", [])]
        allied = Polygon(line + [tuple(p) for p in d["close"]]).buffer(0)
        feats = [dict(type="Feature", properties=dict(side="front"), geometry=mapping(LineString(line))),
                 dict(type="Feature", properties=dict(side="allied"), geometry=mapping(allied)),
                 dict(type="Feature", properties=dict(side="axis"), geometry=mapping(WEST.difference(allied)))]
        for p in d.get("pockets", []):
            ring = [tuple(q) for q in p.get("lonlat", [])]
            if "pixels" in p:  # a pocket drawn on the sheet, closed along the coast by lon/lat points
                ring = line_lonlat(sheet, p["pixels"]) + [tuple(q) for q in p["lonlat_close"]]
            feats.append(dict(type="Feature", properties=dict(side=p["side"] + "_pocket", name=p["name"], note=p["note"]),
                              geometry=mapping(Polygon(ring).buffer(0))))
        src = dict(archive="Library of Congress, Geography and Map Division, " + d["title"], map_time=d["map_time"],
                   url=d["url"], image=d["image"], cone_constant=round(float(sheet.n), 3),
                   residuals_km=sheet.residuals)
        (out / f"{date}.geojson").write_text(json.dumps(dict(type="FeatureCollection", source=src, features=feats),
                                                        ensure_ascii=False, separators=(",", ":")))
        print(date, len(line), "points; control point residuals up to", max(sheet.residuals.values()), "km")


if __name__ == "__main__":
    for y in sys.argv[1:] or YEARS:
        main(y)
