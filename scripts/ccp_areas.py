"""Areas held by the Chinese Communist Party behind the Japanese lines, from the Japanese Army's maps.

Sources (National Institute for Defense Studies, Japan, Senshi Sōsho appendices; curated/ccp_areas.json):
  050_332  北支那方面軍占據地域内治安概況 (September 1942, vol. 50 appendix 5): the North China Area Army's
           classification of its area into pacified (blue), semi-pacified (white) and unpacified (red) ground;
           the red areas, taken from the map by colour, are the Communist base areas and guerrilla zones
  050_331  北支那方面敵情要図 (end of September 1942, vol. 50 appendix 4): the boundary of the Shaan-Gan-Ning
           Border Region (red dash-dot line); its control points are those of 050_332 carried over by a homography
           fitted to feature matches between the two prints of the same base map
  018_323  北支那方面共産軍概況要図 (mid-November 1939, vol. 18 appendix 3): the Jin-Cha-Ji Border Region with
           Central Hebei in November 1939 (blue line) and its sphere at its founding in January 1938 (red dashed line)
An area's `minus` takes lon/lat corridors out of it (railways and towns the Japanese held inside an outline).
Each sheet holds its control points (towns read on the image, full-resolution pixels; a second-order polynomial,
georef.py) and its areas in pixels, densified before they are transformed (georef.line_lonlat).

Writes curated/ccp_areas/<area>.geojson (north_china_1942_09, shaan_gan_ning_1942_09, jin_cha_ji_1939_11,
jin_cha_ji_1938_01) (python3 scripts/ccp_areas.py), each with side "ccp" (the area) and
"cover" (the part of China the sheet's classification covers: North China north of the Longhai railway for
050_332, where the red areas replace any other reading of the Communist areas) and, for 050_332, "jinsui" (north-western
Shanxi beyond the Japanese line, where the red area is the Jin-Sui base: the red areas outside the occupied area of
March 1942 that reach into a box around it, whole).
"""
import json
from pathlib import Path

from shapely.geometry import LineString, Polygon, box, mapping, shape
from shapely.ops import unary_union

from georef import Georef, line_lonlat

ROOT = Path(__file__).resolve().parent.parent
COVER = {"north_china_1942_09": box(105, 34.4, 125, 43)}   # 050_332: the North China Area Army's area, north of the Longhai railway
# 050_332: north-western Shanxi, the Jin-Sui base: the red areas beyond the Japanese line (the occupied area of
# March 1942, curated/frontlines_china_1942) that reach into this box, taken whole, so that the side follows the red
# areas and the Japanese line and no edge of the box runs through a province
JINSUI = {"north_china_1942_09": box(110.3, 37.8, 112.5, 39.6)}
JAPANESE_LINE = ROOT / "curated" / "frontlines_china_1942" / "1942-03-01.geojson"


def main():
    data = json.loads((ROOT / "curated" / "ccp_areas.json").read_text())
    out = ROOT / "curated" / "ccp_areas"
    out.mkdir(exist_ok=True)
    for sheet, sh in data["sheets"].items():
        g = Georef(sh["gcps"])
        for name, a in sh["areas"].items():
            polys = []
            for ring in a["rings"]:
                polys.append(Polygon(line_lonlat(g, ring, closed=True)).buffer(0))
            area = unary_union(polys)
            for m in a.get("minus", []):  # lon/lat corridors the Japanese held inside an outline (its note says which)
                area = area.difference(unary_union([LineString(l).buffer(m["width"]) for l in m["lines"]]))
            feats = [dict(type="Feature", properties=dict(side="ccp"), geometry=mapping(area))]
            if name in COVER:
                feats.append(dict(type="Feature", properties=dict(side="cover"), geometry=mapping(COVER[name])))
            if name in JINSUI:
                occupied = unary_union([shape(f["geometry"]).buffer(0) for f in json.loads(JAPANESE_LINE.read_text())["features"]
                                        if f["properties"]["side"] == "japanese"])
                beyond = area.difference(occupied)
                jinsui = unary_union([p for p in getattr(beyond, "geoms", [beyond]) if p.intersects(JINSUI[name])])
                feats.append(dict(type="Feature", properties=dict(side="jinsui"), geometry=mapping(jinsui)))
            src = dict(map=sh["title"], map_date=sh["map_date"], source=sh["source"], url=sh["url"], note=a["note"],
                       residuals_km=g.residuals)
            fname = name
            (out / f"{fname}.geojson").write_text(json.dumps(dict(type="FeatureCollection", source=src, features=feats),
                                                             ensure_ascii=False, separators=(",", ":")))
            print(fname, len(polys), "areas,", round(area.area, 2), "sq deg; residuals up to",
                  max(g.residuals.values()), "km")


if __name__ == "__main__":
    main()
