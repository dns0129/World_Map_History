"""Present-day reference units for the 1939-1945 build (internal, never shown as divisions).

The control rules in curated/ww2_region_control.csv are written against present-day
regions (for example "Kursk Oblast", French arrondissements, Croatia). This layer
carries those names: each historical unit is cut along it only where the rules give
different controllers, and only its names are used, never its outlines as divisions.

Level per country: the geoBoundaries level whose median area is closest to a typical
county (about 1,500 km2), with first-level areas added where that level leaves holes.

Output: work/ww2/ref_units.geojson, ref_units.csv, ref_levels.csv
"""
import json
import math
from collections import defaultdict

import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import mapping
from shapely.ops import unary_union

from ww2_common import GB, REF_WORK as WW2_WORK, TYPICAL_COUNTY_KM2
from ww2_geo import eq_area_km2, gb_path, polys, read_geojson


def choose_levels():
    isos = sorted({p.name[:3] for p in GB.glob("*_simplified.geojson")})
    choice = {}
    for iso in isos:
        cands = {}
        for lv in ("ADM2", "ADM3"):
            if gb_path(iso, lv).exists():
                areas = [eq_area_km2(g) for _, g in read_geojson(gb_path(iso, lv)) if g is not None]
                if areas:
                    cands[lv] = (float(np.median(areas)), len(areas))
        if cands:
            lv = min(cands, key=lambda k: abs(math.log(max(cands[k][0], 1) / TYPICAL_COUNTY_KM2)))
            choice[iso] = (lv, *cands[lv])
            # communes are far finer than a county: use the first level instead
            if cands[lv][0] < 100 and cands[lv][1] >= 100 and gb_path(iso, "ADM1").exists():
                a1 = [eq_area_km2(g) for _, g in read_geojson(gb_path(iso, "ADM1")) if g is not None]
                if len(a1) >= 8 and np.median(a1) <= 20000:
                    choice[iso] = ("ADM1", float(np.median(a1)), len(a1))
        elif gb_path(iso, "ADM1").exists():
            choice[iso] = ("ADM1", None, None)
    return choice


def load_base(choice):
    rows = []
    for iso, (lv, _, _) in sorted(choice.items()):
        adm1 = read_geojson(gb_path(iso, "ADM1")) if gb_path(iso, "ADM1").exists() and lv != "ADM1" else []
        a1 = [g for _, g in adm1 if g is not None]
        a1n = [p.get("shapeName") for p, g in adm1 if g is not None]
        tree = STRtree(a1) if a1 else None
        adm2 = read_geojson(gb_path(iso, "ADM2")) if lv == "ADM3" and gb_path(iso, "ADM2").exists() else []
        a2 = [g for _, g in adm2 if g is not None]
        a2n = [p.get("shapeName") for p, g in adm2 if g is not None]
        tree2 = STRtree(a2) if a2 else None
        for p, g in read_geojson(gb_path(iso, lv)):
            if g is None:
                continue
            rp = g.representative_point()
            parent = None
            if tree is not None:
                hit = tree.query(rp, predicate="within")
                parent = a1n[hit[0] if len(hit) else tree.nearest(rp)]
            elif lv == "ADM1":
                parent = p.get("shapeName")
            parent2 = None
            if tree2 is not None:
                hit = tree2.query(rp, predicate="within")
                parent2 = a2n[hit[0] if len(hit) else tree2.nearest(rp)]
            rows.append(dict(ref_id=f"{iso}-{lv}-{p.get('shapeID')}", name=p.get("shapeName"), iso3=iso, gb_level=lv,
                             adm1_modern=parent, adm2_modern=parent2, geom=g))
    return rows


def fill_gaps(rows, choice):
    """First-level areas the chosen level leaves uncovered (geoBoundaries has no districts
    for Moscow or St Petersburg, for example)."""
    by_iso = defaultdict(list)
    for r in rows:
        by_iso[r["iso3"]].append(r["geom"])
    added = []
    for iso, (lv, _, _) in choice.items():
        if lv == "ADM1" or not gb_path(iso, "ADM1").exists() or iso not in by_iso:
            continue
        tree = STRtree(by_iso[iso])
        for p, g in read_geojson(gb_path(iso, "ADM1")):
            # Taiwan has its own file; China's copy would make it Chinese territory here
            if g is None or (iso == "CHN" and "Taiwan" in (p.get("shapeName") or "")):
                continue
            near = [by_iso[iso][i] for i in tree.query(g, predicate="intersects")]
            covered = unary_union(near).intersection(g).area if near else 0
            if covered < 0.8 * g.area:
                rest = polys(g.difference(unary_union(near)) if near else g)
                if rest is None or rest.area < 0.2 * g.area:
                    continue
                added.append(dict(ref_id=f"{iso}-ADM1fill-{p.get('shapeID')}", name=p.get("shapeName"), iso3=iso,
                                  gb_level="ADM1 (gap fill)", adm1_modern=p.get("shapeName"), adm2_modern=None,
                                  geom=rest))
    print("gap-filled first-level areas:", len(added), flush=True)
    return rows + added


def drop_overlaps(rows):
    """Disputed areas appear in several country files; keep the first."""
    geoms = [r["geom"] for r in rows]
    tree = STRtree(geoms)
    area = np.array([g.area for g in geoms])
    keep = np.ones(len(rows), bool)
    for i, g in enumerate(geoms):
        if not keep[i]:
            continue
        for j in tree.query(g, predicate="intersects"):
            if j <= i or not keep[j] or rows[j]["iso3"] == rows[i]["iso3"]:
                continue
            if g.intersection(geoms[j]).area > 0.5 * area[j]:
                keep[j] = False
    print("dropped overlapping units:", int((~keep).sum()), flush=True)
    return [r for r, k in zip(rows, keep) if k]


def main():
    choice = choose_levels()
    pd.DataFrame([(k, *v) for k, v in choice.items()], columns=["iso3", "level", "median_km2", "n"]) \
        .to_csv(WW2_WORK / "ref_levels.csv", index=False)
    rows = drop_overlaps(fill_gaps(load_base(choice), choice))
    for r in rows:
        rp = r["geom"].representative_point()
        r["label_lon"], r["label_lat"] = round(rp.x, 4), round(rp.y, 4)
    pd.DataFrame([{k: v for k, v in r.items() if k != "geom"} for r in rows]).to_csv(WW2_WORK / "ref_units.csv",
                                                                                   index=False)
    with open(WW2_WORK / "ref_units.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"ref_id": r["ref_id"]}, "geometry": mapping(r["geom"])} for r in rows]}, f)
    print("reference units:", len(rows))


if __name__ == "__main__":
    main()
