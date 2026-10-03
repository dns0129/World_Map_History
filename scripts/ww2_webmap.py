"""Data files for the interactive 1939-1945 county maps (ww2/maps/).

  geo.bin           all pieces of the six snapshots (administrative units, cut where the
                    controller changes), simplified; zigzag-varint
                    deltas of 1/1000 degree, per feature: parts, rings, points
  geo-units.bin     CShapes units valid on any snapshot date (same encoding)
  geo-admin.bin     outlines of the historical administrative units (same encoding)
  admin.json        static attributes of the administrative units (columnar)
  snap-<date>.json  per-snapshot rows: which pieces exist and who controls them
  terrain.png       land hillshade in Web Mercator (alpha = shade)
  hydro.json        main rivers and lakes
"""
import json

import numpy as np
import pandas as pd
from PIL import Image
from rasterio.transform import from_origin, from_bounds
from rasterio.warp import reproject, Resampling
from shapely.geometry import shape, MultiPolygon

import topo
from common import RAW, WORK, ROOT, HYDE_RES
from ww2_common import SNAPSHOTS, WW2_WORK, WW2_OUT

OUT = WW2_OUT / "maps" / "data"
Q = 1000  # coordinate units per degree
TOL_COUNTY = 0.008
TOL_UNIT = 0.02
BLOCS = ["allied", "axis", "neutral", "contested"]
TIER_ZH = {1: "县级", 2: "地区级", 3: "省级", 4: "大区级", 5: "整个政治单元", 6: "岛屿属地"}
CONF = ["whole", "approximate"]


def varint(n, out):
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def zz(n):
    return (n << 1) ^ (n >> 63)


def encode(geoms, tol):
    buf = bytearray()
    for g in geoms:
        s = g.simplify(tol, preserve_topology=True)
        ps = [p for p in getattr(s, "geoms", [s]) if p.geom_type == "Polygon" and not p.is_empty]
        ps = [p for p in ps if p.area > (tol * tol) / 4] or ps[:1]
        polys = []
        for p in ps:
            rings = []
            for r in [p.exterior, *p.interiors]:
                c = np.round(np.asarray(r.coords)[:-1] * Q).astype(np.int64)
                c = c[np.r_[True, np.any(np.diff(c, axis=0) != 0, axis=1)]]
                if len(c) > 1 and (c[0] == c[-1]).all():
                    c = c[:-1]
                if len(c) >= 3:
                    rings.append(c)
                elif not rings:
                    break  # exterior collapsed: drop the polygon
            if rings:
                polys.append(rings)
        if not polys:  # keep tiny units clickable: a small triangle at the label point
            pt = g.representative_point()
            x, y = round(pt.x * Q), round(pt.y * Q)
            polys = [[np.array([[x - 2, y - 2], [x + 2, y - 2], [x, y + 2]], dtype=np.int64)]]
        varint(len(polys), buf)
        px = py = 0
        for rings in polys:
            varint(len(rings), buf)
            for c in rings:
                varint(len(c), buf)
                for x, y in c:
                    varint(zz(int(x - px)), buf)
                    varint(zz(int(y - py)), buf)
                    px, py = int(x), int(y)
    return bytes(buf)


def table(values):
    """Deduplicate strings into a lookup list and index array."""
    lut, idx = [], {}
    out = []
    for v in values:
        v = None if (isinstance(v, float) and np.isnan(v)) else v
        if v not in idx:
            idx[v] = len(lut)
            lut.append(v)
        out.append(idx[v])
    return lut, out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hist = pd.read_csv(WW2_WORK / "hist_units.csv", low_memory=False)
    snaps = {s[0]: pd.read_csv(WW2_WORK / f"snapshot_{s[0]}.csv", low_memory=False) for s in SNAPSHOTS}
    hgeom = {f["properties"]["unit_id"]: shape(f["geometry"])
             for f in json.load(open(WW2_WORK / "hist_units.geojson"))["features"]}
    pgeom = {}
    for s in SNAPSHOTS:
        for f in json.load(open(WW2_WORK / f"split_{s[0]}.geojson"))["features"]:
            pgeom[f["properties"]["piece_id"]] = shape(f["geometry"])

    used = sorted(set().union(*[set(d.piece_id) for d in snaps.values()]))
    fidx = {p: i for i, p in enumerate(used)}
    padmin = {}
    for d in snaps.values():
        padmin.update(zip(d.piece_id, d.admin_id))
    aids = sorted(set(padmin.values()))
    aidx = {a: i for i, a in enumerate(aids)}
    (OUT / "geo.bin").write_bytes(encode([pgeom.get(p) or hgeom[padmin[p]] for p in used], TOL_COUNTY))
    (OUT / "geo-admin.bin").write_bytes(encode([hgeom[a] for a in aids], TOL_COUNTY))

    arow = hist.set_index("unit_id").loc[aids]
    cols = {}
    for col in ("name", "name_zh", "name_en", "kind", "basis", "source", "parent", "parent_zh", "grandparent", "note",
                "start", "end"):
        lut, idx = table(arow[col].tolist())
        cols[col] = {"lut": lut, "idx": idx}
    static = {
        "n": len(aids), "admin_id": aids, "cols": cols,
        "tier": [int(t) for t in arow.tier], "tier_zh": TIER_ZH,
        "partial": [int(bool(x)) for x in arow.partial],
        "area": [round(float(a), 1) for a in arow.area_km2],
        "label": [[round(float(x), 3), round(float(y), 3)] for x, y in zip(arow.label_lon, arow.label_lat)],
        "feature_admin": [aidx[padmin[p]] for p in used],
    }
    (OUT / "admin.json").write_text(json.dumps(static, ensure_ascii=False, separators=(",", ":")))

    # political units (CShapes) for borders and labels
    arcs, gs = topo.load(RAW / "cshapes_2_gw.topojson")
    unit_ids = sorted(set().union(*[set(d.unit_id) for d in snaps.values()]))
    ug = {g["properties"]["fid"]: topo.to_shape(arcs, g) for g in gs if g["properties"]["fid"] in unit_ids}
    unit_ids = [u for u in unit_ids if u in ug]  # territories CShapes does not draw have no outline
    (OUT / "geo-units.bin").write_bytes(encode([ug[u] for u in unit_ids], TOL_UNIT))
    uidx = {u: i for i, u in enumerate(unit_ids)}

    summary = []
    for snap, tzh, ten in SNAPSHOTS:
        d = snaps[snap].drop_duplicates("piece_id")
        luts = {}
        rows = {}
        for col in ("unit_name_zh", "unit_name_en", "unit_status", "sovereign_name_zh", "controller_name_zh",
                    "controller_name_en", "controller_detail_zh", "controller_detail_en", "control_type", "control_source",
                    "partial_control_events"):
            luts[col], rows[col] = table(d[col].tolist())
        units = d.groupby("unit_id").agg(name_zh=("unit_name_zh", "first"), name_en=("unit_name_en", "first"),
                                         pop=("population_est", "sum")).reset_index()
        lab = {}
        for u in units.itertuples():
            if u.unit_id not in ug:
                continue
            p = ug[u.unit_id].representative_point()
            lab[uidx[u.unit_id]] = [u.name_zh or u.name_en, round(p.x, 2), round(p.y, 2), int(u.pop), round(ug[u.unit_id].area, 2)]
        ctrl_pop = d.groupby(["controller_gwcode", "controller_name_zh", "bloc"]).population_est.sum().reset_index() \
            .sort_values("population_est", ascending=False)
        doc = {
            "snapshot": snap, "title_zh": tzh, "title_en": ten,
            "feature": [fidx[p] for p in d.piece_id], "unit": [uidx.get(u, -1) for u in d.unit_id],
            "bloc": [BLOCS.index(b) for b in d.bloc], "conf": [CONF.index(c) if c in CONF else 0 for c in d.control_confidence],
            "ctrl_gw": [int(x) for x in d.controller_gwcode], "split": [int(x) for x in d.control_split],
            "area": [round(float(a), 1) for a in d.area_km2],
            "pop": [int(x) for x in d.population_est], "luts": luts, "rows": rows,
            "units_active": sorted(set(uidx[u] for u in d.unit_id if u in uidx)),
            "admin_active": sorted(set(aidx[a] for a in d.admin_id)), "unit_labels": lab,
            "controllers": [[int(r.controller_gwcode), r.controller_name_zh, r.bloc, int(r.population_est)]
                            for r in ctrl_pop.head(40).itertuples()],
            "bloc_pop": {b: int(d[d.bloc == b].population_est.sum()) for b in BLOCS},
            "tier_count": {str(t): int(n) for t, n in hist.set_index("unit_id").loc[sorted(set(d.admin_id))]
                           .tier.value_counts().sort_index().items()},
        }
        (OUT / f"snap-{snap}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
        summary.append({"snapshot": snap, "title_zh": tzh, "title_en": ten, "pieces": len(d),
                        "admin_units": int(d.admin_id.nunique()), "population": int(d.population_est.sum()),
                        "bloc_pop": doc["bloc_pop"], "tier_count": doc["tier_count"]})
    (OUT / "index.json").write_text(json.dumps({"snapshots": summary, "blocs": BLOCS, "tiers": TIER_ZH,
                                                "quantum": Q}, ensure_ascii=False, indent=1))

    # terrain in Web Mercator (alpha from the land hillshade)
    hs = np.asarray(Image.open(WORK / "physical" / "hillshade_5m.png"), dtype=np.float32)
    m = 20037508.342789244
    n = 2048
    dst = np.full((n, n), 255, dtype=np.float32)
    reproject(hs, dst, src_transform=from_origin(-180, 90, HYDE_RES, HYDE_RES), src_crs="EPSG:4326",
              dst_transform=from_bounds(-m, -m, m, m, n, n), dst_crs="EPSG:3857", resampling=Resampling.bilinear,
              dst_nodata=255)
    a = np.clip((255 - dst) * 1.4, 0, 255).astype(np.uint8)
    rgba = np.zeros((n, n, 4), np.uint8)
    rgba[..., 3] = a
    Image.fromarray(rgba, "RGBA").save(OUT / "terrain.png", optimize=True)

    feats = []
    for layer, maxrank, tol in (("rivers", 5, 0.02), ("lakes", 4, 0.02)):
        for f in json.load(open(WORK / "physical" / f"{layer}.geojson"))["features"]:
            p = f["properties"]
            if (p.get("scalerank") or 9) > maxrank:
                continue
            if layer == "lakes" and p.get("valid_to") is not None:
                continue
            g = shape(f["geometry"]).simplify(tol)
            if g.is_empty:
                continue
            gm = json.loads(json.dumps(g.__geo_interface__), parse_float=lambda s: round(float(s), 3))
            feats.append({"type": "Feature", "properties": {"k": layer[0], "r": p.get("scalerank"),
                                                            "n": p.get("name_zh") or p.get("name")}, "geometry": gm})
    (OUT / "hydro.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False,
                                               separators=(",", ":")))
    for p in sorted(OUT.iterdir()):
        print(p.name, f"{p.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
