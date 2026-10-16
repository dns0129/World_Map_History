"""Fronts of the war against Germany in 1945 from the War Department's atlas of the world battle fronts.

Source: "Atlas of the World Battle Fronts in Semimonthly Phases to August 15, 1945" (United States War Department,
General Staff, 1945; public domain; Combined Arms Research Library digital library), the "War against Germany" map of
each phase: Allied-held ground pink (that taken in the phase dark red), German-held ground light grey, neutral countries
darker grey. curated/atlas_1945.json holds per date the page used, its control points (city circles read on the 1
January 1945 page, located by circle detection, carried to the other pages by a homography fitted to feature matches
between the prints of the same base map; second-order polynomial as in lagekarten.py), `sheet` (the map's pixel frame
on that page, whose width differs from page to page) and the Allied area taken from
the page by colour (pink and red, small holes such as lakes filled, German pockets kept), in pixels, extended over
the sea by up to 12 px (never over German or neutral grey land, kept 5 px clear of it) so that it reaches the
coastline of the provinces; `divider` (lon/lat)
splits the Allied area into the Soviet side (east) and the Western Allied side (west), which met only on the Elbe on
25 April 1945; `extra_soviet` adds ground liberated in the east beyond the edge of the sheet, and ground beyond the
edges of the sheet otherwise falls to the side of the divider it lies on (the Soviet Union east of the sheet, southern
Italy south of it). Per date `corrections` (each with its note and source) add Soviet-held or Western Allied ground (sides "soviet", "allied") or
take German fortress pockets out of the Allied area (side "axis"), where the atlas, drawn at about 1:7,000,000, misses
them or where the OKH map Lage Ost of the end of March 1945 (German-Russian digitisation project) places the front
otherwise for 1 April.

Writes curated/frontlines_1945/<date>.geojson (python3 scripts/atlas_fronts.py):
  allied    the Allied area of the phase
  axis_pocket   German fortress pockets of the corrections
  soviet    its part east of the divider (with extra_soviet)
  western   its part west of the divider (the army group zones in Germany are given by whole provinces in the
            control rules, not here, so that no straight line runs through a province)
"""
import json
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, box, mapping
from shapely.ops import split, unary_union

from lagekarten import Georef

ROOT = Path(__file__).resolve().parent.parent
EUROPE = box(-12, 34, 40, 72)


def main():
    data = json.loads((ROOT / "curated" / "atlas_1945.json").read_text())
    out = ROOT / "curated" / "frontlines_1945"
    out.mkdir(exist_ok=True)
    east, west = split(EUROPE, LineString([(data["divider"][0][0], 72)] + data["divider"] + [(data["divider"][-1][0], 34)])).geoms
    if east.centroid.x < west.centroid.x:
        east, west = west, east
    extra = unary_union([Polygon(e["lonlat"]) for e in data["extra_soviet"]])
    for date, d in sorted(data["dates"].items()):
        g = Georef(d["gcps"])
        outer, holes = [], []
        for r in d["allied"]:
            ring = LineString(r["pts"] + r["pts"][:1]).segmentize(10).coords   # densified: the polynomial bends long straight edges
            lon, lat = g.lonlat([p[0] for p in ring], [p[1] for p in ring])
            poly = Polygon([(round(float(x), 4), round(float(y), 4)) for x, y in zip(lon, lat)]).buffer(0)
            (holes if r["hole"] else outer).append(poly)
        allied = unary_union(outer).difference(unary_union(holes)) if holes else unary_union(outer)
        x0, y0, x1, y1 = d["sheet"]   # the map on the page: below the title band, above the text, a few pixels inside the
        # page edges so that the ground beyond it overlaps the area traced to them; a point every 10 px, since the
        # polynomial bends the edges and a chord between corners would leave a sliver along the traced area
        xs, ys = list(range(x0, x1, 10)), list(range(y0, y1, 10))
        px = xs + [x1] * len(ys) + [x1 + x0 - x for x in xs] + [x0] * len(ys)
        py = [y0] * len(xs) + ys + [y1] * len(xs) + [y1 + y0 - y for y in ys]
        lon, lat = g.lonlat(px, py)
        sheet = Polygon(list(zip(lon, lat)))
        beyond = EUROPE.difference(sheet)
        corr = {"soviet": [], "axis": [], "allied": []}
        for c in d.get("corrections", []):
            shape_ = Point(c["circle"][:2]).buffer(c["circle"][2]) if "circle" in c else Polygon(c["lonlat"])
            corr[c["side"]].append(shape_)
        pockets = unary_union(corr["axis"])
        allied = allied.union(beyond).union(unary_union(corr["soviet"] + corr["allied"])).difference(pockets)
        soviet = allied.intersection(east).union(extra).difference(pockets)
        western = allied.intersection(west)
        sides = dict(allied=allied.union(extra), axis_pocket=pockets, soviet=soviet, western=western)
        feats = [dict(type="Feature", properties=dict(side=k), geometry=mapping(v)) for k, v in sides.items() if not v.is_empty]
        src = dict(data["source"], page=int(d["page"]), map_date=date, residuals_km=g.residuals,
                   corrections=[f"{c['name']}: {c['note']} ({c['source']})" for c in d.get("corrections", [])])
        (out / f"{date}.geojson").write_text(json.dumps(dict(type="FeatureCollection", source=src, features=feats),
                                                        ensure_ascii=False, separators=(",", ":")))
        print(date, "page", d["page"], len(outer), "areas,", len(holes), "pockets; residuals up to", max(g.residuals.values()), "km")


if __name__ == "__main__":
    main()
