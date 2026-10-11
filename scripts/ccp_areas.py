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
Each sheet holds its control points (towns read on the image, full-resolution pixels; a second-order polynomial
as in lagekarten.py) and its areas in pixels.

Writes curated/ccp_areas/<area>.geojson (north_china_1942_09, shaan_gan_ning_1942_09, jin_cha_ji_1939_11,
jin_cha_ji_1938_01) (python3 scripts/ccp_areas.py), each with side "ccp" (the area) and
"cover" (the part of China the sheet's classification covers: North China north of the Longhai railway for
050_332, where the red areas replace any other reading of the Communist areas).
"""
import json
from pathlib import Path

from shapely.geometry import Polygon, box, mapping
from shapely.ops import unary_union

from lagekarten import Georef

ROOT = Path(__file__).resolve().parent.parent
COVER = {"north_china_1942_09": box(105, 34.4, 125, 43)}   # 050_332: the North China Area Army's area, north of the Longhai railway


def main():
    data = json.loads((ROOT / "curated" / "ccp_areas.json").read_text())
    out = ROOT / "curated" / "ccp_areas"
    out.mkdir(exist_ok=True)
    for sheet, sh in data["sheets"].items():
        g = Georef(sh["gcps"])
        for name, a in sh["areas"].items():
            polys = []
            for ring in a["rings"]:
                lon, lat = g.lonlat([p[0] for p in ring], [p[1] for p in ring])
                polys.append(Polygon([(round(float(x), 4), round(float(y), 4)) for x, y in zip(lon, lat)]).buffer(0))
            area = unary_union(polys)
            feats = [dict(type="Feature", properties=dict(side="ccp"), geometry=mapping(area))]
            if name in COVER:
                feats.append(dict(type="Feature", properties=dict(side="cover"), geometry=mapping(COVER[name])))
            src = dict(map=sh["title"], map_date=sh["map_date"], source=sh["source"], url=sh["url"], note=a["note"],
                       residuals_km=g.residuals)
            fname = name
            (out / f"{fname}.geojson").write_text(json.dumps(dict(type="FeatureCollection", source=src, features=feats),
                                                             ensure_ascii=False, separators=(",", ":")))
            print(fname, len(polys), "areas,", round(area.area, 2), "sq deg; residuals up to",
                  max(g.residuals.values()), "km")


if __name__ == "__main__":
    main()
