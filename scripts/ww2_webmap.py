"""Data files for the interactive 1939-1945 province maps (ww2/maps/).

  geo.bin           all pieces of the six snapshots (provinces, cut where a border or the
                    controller runs through them), simplified; zigzag-varint deltas of
                    1/1000 degree, per feature: parts, rings, points
  geo-units.bin     CShapes units valid on any snapshot date (same encoding)
  geo-admin.bin     outlines of the province-level units (same encoding)
  geo-ctrl.bin      the area each country actually controls on each date, dissolved (same encoding)
  admin.json        static attributes of the province-level units (columnar)
  snap-<date>.json  per-snapshot rows: which pieces exist, who controls them, the countries
                    of the control view with their colours and where their names sit
  relief/           shaded relief sheets, written by ww2_relief.py
  hydro.json        rivers and lakes as they were in 1939-45 (Natural Earth 10m)
  hydro-detail.json the denser European and North American river and lake layers
"""
import colorsys
import hashlib
import json
import math
import unicodedata
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import shapefile
import shapely
import shapely.ops
from shapely.geometry import MultiPolygon, Polygon, shape

import topo
from common import RAW
from ww2_common import SNAPSHOTS, WW2_WORK, WW2_OUT
from ww2_geo import polys, union

OUT = WW2_OUT / "maps" / "data"
NE = RAW / "naturalearth"
Q = 1000  # coordinate units per degree
TOL_PROV = 0.008
TOL_UNIT = 0.02
TOL_CTRL = 0.012
BLOCS = ["allied", "axis", "neutral", "contested"]
TIER_ZH = {3: "省级", 4: "大区级", 5: "整个政治单元", 6: "岛屿属地"}
CONF = ["whole", "approximate"]
LABEL_MIN_KM2 = 2500      # smaller pieces of a country's territory get no country label

# ---------------------------------------------------------------- countries of the control view
# A country is whoever actually governs the land on the date. Occupied land belongs to the
# occupier; client states with a government of their own (Manchukuo, Mengjiang, Vichy France,
# the Italian Social Republic) are countries of their own, as on strategy-game maps.
SPECIAL = {
    "MAN": ("满洲国", "Manchukuo"), "MEN": ("蒙疆", "Mengjiang"), "VICHY": ("维希法国", "Vichy France"),
    "RSI": ("意大利社会共和国", "Italian Social Republic"), "ITK": ("意大利王国", "Kingdom of Italy (Allied-held)"),
    "-1": ("同盟国联军", "Allied forces"), "-10": ("德意联军", "German-Italian forces"),
    "-20": ("前线争夺区", "Contested front"), "-2": ("中国共产党", "Chinese Communist Party"),
}
# Flat colours in the manner of grand-strategy maps; the rest are spread around the hue circle.
COLOR = {
    "255": "#7f858c", "325": "#4f9a58", "740": "#ecdfa6", "365": "#a33a32", "200": "#d9625f", "220": "#3d5ab0",
    "VICHY": "#8d89b9", "-4": "#5d86d8", "2": "#4c94c9", "710": "#d49a3c", "-2": "#c4473d", "MAN": "#8f72b0",
    "MEN": "#b78d5d", "RSI": "#9b9161", "ITK": "#5fae6a", "20": "#c27d6c", "900": "#4aa395", "920": "#73b37a",
    "560": "#c39448", "140": "#59ad62", "160": "#8ec4e3", "155": "#b9667f", "135": "#cba2d4", "230": "#e1bb45",
    "235": "#3e7d4b", "380": "#5e8bcb", "385": "#c98b7b", "375": "#e3e8ec", "390": "#c4605e", "640": "#a9b26f",
    "630": "#6ea56f", "645": "#bfa76a", "670": "#a7c47f", "651": "#d8c47c", "530": "#86a95b", "310": "#b07d56",
    "360": "#d9c24c", "355": "#6d9e5d", "317": "#6290c1", "-12": "#c56e90", "345": "#9070a8", "350": "#79aadb",
    "339": "#94443f", "290": "#d06f8d", "800": "#5383c2", "711": "#cba57c", "712": "#80af90", "-30": "#b7d48c",
    "210": "#e38c3d", "211": "#d6bf54", "212": "#7aa3c4", "225": "#c95a5a", "205": "#71bf7c", "70": "#4fa58d",
    "700": "#9e8a6a", "790": "#b9798c", "-1": "#8eb2d1", "-10": "#8f8e7e", "-20": "#b9b6aa",
    "305": "#c89a8e", "315": "#6fae9c", "366": "#6f9fd8", "367": "#a67fb5", "368": "#d9ad62", "395": "#94bdd3",
    "100": "#dcbd57", "101": "#c97c5d", "130": "#7fb07a", "145": "#d9a65b", "150": "#88a7d4", "165": "#a3c4e0",
    "40": "#d9776f", "41": "#8f7fbf", "42": "#6fb59a", "90": "#7aa86b", "91": "#b9a0d0", "92": "#5f9fd0",
    "93": "#d8b86a", "94": "#c97f8f", "95": "#8fc49b", "450": "#c58fb0", "678": "#b9875f", "698": "#c7a7a0",
    "850": "#d0855f", "660": "#8fb6c9", "652": "#c6b36b",
}


def country_key(r):
    gw, det = int(r["controller_gwcode"]), str(r["controller_detail_en"] or "")
    if gw == 740 and det.startswith("Manchukuo"):
        return "MAN"
    if gw == 740 and det.startswith("Mengjiang"):
        return "MEN"
    if gw == 255 and "Italian Social Republic" in det:
        return "RSI"
    if gw == -1 and "Kingdom of Italy" in det:
        return "ITK"
    if gw == 220 and r["bloc"] == "neutral" and r["snapshot"] in ("1940-07-01", "1941-12-07", "1942-11-01"):
        return "VICHY"
    return str(gw)


def lighten(hexcolor, t):
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(v + (255 - v) * t) for v in (r, g, b))


def nation_of(r):
    """Colour of the 'nation' view: each state's de jure territory in its own colour; colonies,
    protectorates and mandates in a lighter shade of their sovereign's."""
    gw = r["unit_gwcode"] if r["unit_gwcode"] == r["unit_gwcode"] else r["sovereign_gwcode"]
    if r["unit_status"] in ("colony", "protectorate", "mandate"):
        return lighten(color_of(str(int(r["sovereign_gwcode"]))), 0.42)
    return color_of(str(int(gw))) if gw == gw else "#c9c4b8"


def color_of(key):
    if key in COLOR:
        return COLOR[key]
    h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360, 0.55 + ((h >> 9) % 12) / 100, 0.35 + ((h >> 13) % 20) / 100)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


# ---------------------------------------------------------------- encoding

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
        polys_ = []
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
                polys_.append(rings)
        if not polys_:  # keep tiny units clickable: a small triangle at the label point
            pt = g.representative_point()
            x, y = round(pt.x * Q), round(pt.y * Q)
            polys_ = [[np.array([[x - 2, y - 2], [x + 2, y - 2], [x, y + 2]], dtype=np.int64)]]
        varint(len(polys_), buf)
        px = py = 0
        for rings in polys_:
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


# ---------------------------------------------------------------- country outlines and labels

def dissolve(gs, eps=0.004):
    g = polys(union(gs))
    if g is None:
        return None
    c = polys(g.buffer(eps, join_style="mitre", mitre_limit=3).buffer(-eps, join_style="mitre", mitre_limit=3)) or g
    out = []
    for p in getattr(c, "geoms", [c]):
        out.append(Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area > 0.003]))
    return out[0] if len(out) == 1 else MultiPolygon(out)


def merc(lon, lat):
    lat = np.clip(lat, -85, 85)
    return (lon + 180) / 360, (1 - np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) / np.pi) / 2


def unmerc(x, y):
    return x * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))


def _chord(P, c, u, reach):
    """Distances from c to the territory's edge along +u and -u."""
    line = shapely.LineString([c - reach * u, c + reach * u])
    part = P.intersection(line)
    best = None
    for seg in getattr(part, "geoms", [part]):
        if seg.geom_type == "LineString" and seg.distance(shapely.Point(c)) < 1e-9:
            best = seg
    if best is None:
        return 0.0, 0.0
    xy = np.asarray(best.coords)
    t = (xy - c) @ u
    return float(t.max()), float(-t.min())


def label_anchor(poly):
    """Where a country's name sits on one piece of its territory: the point deepest inside the
    main body (pole of inaccessibility), and the horizontal and vertical room the name has
    there, in Web Mercator world units (0-1), so the page shows the name only at zooms where
    it fits inside the land. Returns [lon, lat, width, height] or None."""
    xy = np.asarray(poly.exterior.coords)
    P = Polygon(np.column_stack(merc(xy[:, 0], xy[:, 1])),
                [np.column_stack(merc(*np.asarray(r.coords).T)) for r in poly.interiors])
    if not P.is_valid:
        P = polys(shapely.make_valid(P))
        if P is None:
            return None
        P = max(getattr(P, "geoms", [P]), key=lambda p: p.area)
    # the main body: shrink, keep the largest part, grow back, so necks and peninsulas do not count
    try:
        c0 = shapely.ops.polylabel(P, tolerance=max(P.length, 1e-9) / 2000)
    except Exception:
        c0 = P.representative_point()
    r = c0.distance(P.exterior)
    body = P
    er = P.buffer(-0.5 * r)
    if not er.is_empty:
        er = max(getattr(er, "geoms", [er]), key=lambda q: q.area)
        body = polys(er.buffer(0.5 * r).intersection(P)) or P
        body = max(getattr(body, "geoms", [body]), key=lambda q: q.area)
    try:
        c = np.asarray(shapely.ops.polylabel(body, tolerance=max(body.length, 1e-9) / 2000).coords[0])
    except Exception:
        c = np.asarray(body.representative_point().coords[0])
    x0, y0, x1, y1 = body.bounds
    reach = max(x1 - x0, y1 - y0) + 1e-6
    f, b = _chord(P, c, np.array([1.0, 0.0]), reach)
    up, down = _chord(P, c, np.array([0.0, 1.0]), reach)
    length, height = 2 * min(f, b), 2 * min(up, down)
    if length <= 0 or height <= 0:
        return None
    lon, lat = unmerc(*c)
    return [round(lon, 3), round(lat, 3), round(length, 7), round(height, 7)]


# ---------------------------------------------------------------- rivers and lakes

HISTORIC_LAKES = {"Aral Sea", "Lake Chad", "Lop Nur"}  # drawn as they were before the 1960s


def rnd(gm):
    return json.loads(json.dumps(gm), parse_float=lambda s: round(float(s), 3))


def cjk(name):
    """A river name the map can letter along the river: Chinese characters only (the map draws
    them itself; other scripts would need glyph files)."""
    name = (name or "").strip()
    ok = name and all(unicodedata.name(ch, "").startswith("CJK UNIFIED IDEOGRAPH") for ch in name)
    return name if ok else None


def river_features(path, tol, min_rank=0):
    r = shapefile.Reader(str(path), encoding="utf-8")
    out = []
    for sr in r.iterShapeRecords():
        p = sr.record.as_dict()
        rank = int(p.get("scalerank") or 9)
        if rank < min_rank or sr.shape.shapeType == shapefile.NULL:
            continue
        g = shape(sr.shape.__geo_interface__).simplify(tol)
        if g.is_empty:
            continue
        out.append({"type": "Feature", "properties": {
            "k": "r", "r": rank, "n": cjk(p.get("name_zh")),
            "c": 1 if "Lake" in (p.get("featurecla") or "") else 0}, "geometry": rnd(g.__geo_interface__)})
    return out


def lake_features(path, tol, historic=False):
    out = []
    for f in json.load(open(path))["features"]:
        p = f["properties"]
        name = p.get("name")
        if (name in HISTORIC_LAKES) != historic:
            continue
        if p.get("featurecla") == "Reservoir" and (p.get("year") or 0) > 1945:
            continue  # reservoirs filled after the war
        g = shape(f["geometry"]).simplify(tol, preserve_topology=True)
        if g.is_empty:
            continue
        out.append({"type": "Feature", "properties": {"k": "l", "r": int(p.get("scalerank") or 9),
                                                      "n": p.get("name_zh") or name},
                    "geometry": rnd(g.__geo_interface__)})
    return out


def name_lines(feats):
    """Lines the river names are lettered along: Natural Earth cuts each river into many short
    pieces, so join the pieces of each named river and smooth them (k = "n", not drawn)."""
    by = defaultdict(list)
    rank = {}
    for f in feats:
        p = f["properties"]
        if p["k"] != "r" or not p.get("n") or p.get("c"):
            continue
        by[p["n"]].append(shape(f["geometry"]))
        rank[p["n"]] = min(rank.get(p["n"], 99), p["r"])
    out = []
    for name, gs in by.items():
        u = shapely.ops.unary_union(gs)
        merged = shapely.ops.linemerge(u) if u.geom_type == "MultiLineString" else u
        for part in getattr(merged, "geoms", [merged]):
            if part.length < 0.6:
                continue
            g = part.simplify(0.04)
            out.append({"type": "Feature", "properties": {"k": "n", "r": rank[name], "n": name},
                        "geometry": rnd(g.__geo_interface__)})
    return out


def hydro():
    if not (NE / "shp" / "ne_10m_rivers_lake_centerlines.shp").exists():
        print("Natural Earth rivers not downloaded; keeping the existing hydro files")
        return
    main = river_features(NE / "shp" / "ne_10m_rivers_lake_centerlines.shp", 0.006)
    main += lake_features(NE / "ne_10m_lakes.geojson", 0.006)
    main += lake_features(NE / "ne_10m_lakes_historic.geojson", 0.006, historic=True)
    detail = []
    for layer in ("ne_10m_rivers_europe", "ne_10m_rivers_north_america"):
        if (NE / "shp" / f"{layer}.shp").exists():
            detail += river_features(NE / "shp" / f"{layer}.shp", 0.008)
    main += name_lines(main + detail)
    (OUT / "hydro.json").write_text(json.dumps({"type": "FeatureCollection", "features": main}, ensure_ascii=False,
                                               separators=(",", ":")))
    for layer in ("ne_10m_lakes_europe", "ne_10m_lakes_north_america"):
        if (NE / f"{layer}.geojson").exists():
            detail += lake_features(NE / f"{layer}.geojson", 0.006)
    (OUT / "hydro-detail.json").write_text(json.dumps({"type": "FeatureCollection", "features": detail},
                                                      ensure_ascii=False, separators=(",", ":")))


# ---------------------------------------------------------------- main

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hist = pd.read_csv(WW2_WORK / "prov_units.csv", low_memory=False)
    snaps = {s[0]: pd.read_csv(WW2_WORK / f"prov_snapshot_{s[0]}.csv", low_memory=False) for s in SNAPSHOTS}
    hgeom = {f["properties"]["unit_id"]: shape(f["geometry"])
             for f in json.load(open(WW2_WORK / "prov_units.geojson"))["features"]}
    pgeom = {}
    for s in SNAPSHOTS:
        for f in json.load(open(WW2_WORK / f"prov_split_{s[0]}.geojson"))["features"]:
            pgeom[f["properties"]["piece_id"]] = shape(f["geometry"])

    used = sorted(set().union(*[set(d.piece_id) for d in snaps.values()]))
    fidx = {p: i for i, p in enumerate(used)}
    padmin = {}
    for d in snaps.values():
        padmin.update(zip(d.piece_id, d.admin_id))
    aids = sorted(set(padmin.values()))
    aidx = {a: i for i, a in enumerate(aids)}
    geom_of = lambda p: pgeom.get(p) or hgeom[padmin[p]]
    (OUT / "geo.bin").write_bytes(encode([geom_of(p) for p in used], TOL_PROV))
    (OUT / "geo-admin.bin").write_bytes(encode([hgeom[a] for a in aids], TOL_PROV))

    arow = hist.set_index("unit_id").loc[aids]
    cols = {}
    for col in ("name", "name_zh", "name_en", "kind", "basis", "source", "parent", "parent_zh", "note", "start", "end"):
        lut, idx = table(arow[col].tolist())
        cols[col] = {"lut": lut, "idx": idx}
    static = {
        "n": len(aids), "admin_id": aids, "cols": cols,
        "tier": [int(t) for t in arow.tier], "tier_zh": TIER_ZH,
        "partial": [int(bool(x)) for x in arow.partial.fillna(0)],
        "merged": [int(x) for x in arow.merged_units.fillna(0)],
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

    ctrl_geoms = []
    summary = []
    for snap, tzh, ten in SNAPSHOTS:
        d = snaps[snap].drop_duplicates("piece_id").reset_index(drop=True)
        d["country"] = [country_key(r) for r in d.to_dict("records")]
        luts = {}
        rows = {}
        for col in ("unit_name_zh", "unit_name_en", "unit_status", "sovereign_name_zh", "controller_name_zh",
                    "controller_name_en", "controller_detail_zh", "controller_detail_en", "control_type", "control_source",
                    "partial_control_events"):
            luts[col], rows[col] = table(d[col].tolist())
        units = d.groupby("unit_id").agg(name_zh=("unit_name_zh", "first"), name_en=("unit_name_en", "first"),
                                         pop=("population_est", "sum")).reset_index()
        lab = []
        for u in units.itertuples():
            if u.unit_id not in ug:
                continue
            g = ug[u.unit_id]
            big = max(getattr(g, "geoms", [g]), key=lambda q: q.area)
            anchor = label_anchor(big)
            if anchor:
                km2 = big.area * (111.32 ** 2) * math.cos(math.radians(big.centroid.y))
                lab.append([uidx[u.unit_id], u.name_zh or u.name_en] + anchor + [round(km2)])
        # nations: the de jure political units, coloured by state
        nat = d.groupby("unit_id", sort=False).agg(zh=("unit_name_zh", "first"), en=("unit_name_en", "first"),
                                                   status=("unit_status", "first"), sov=("sovereign_name_zh", "first"),
                                                   pop=("population_est", "sum"), km2=("area_km2", "sum"))
        nat_color = {u: nation_of(r) for u, r in d.drop_duplicates("unit_id").set_index("unit_id", drop=False).iterrows()}
        nat = nat.sort_values("pop", ascending=False)
        nidx = {u: i for i, u in enumerate(nat.index)}
        nations = [[int(u), r.zh or r.en, r.en, nat_color[u], r.status, r.sov, int(r["pop"]), round(float(r.km2))]
                   for u, r in nat.iterrows()]

        # countries of the control view: dissolved territory, colour, curved name lines
        countries, clabels = [], []
        cindex = {}
        for key, g in sorted(d.groupby("country"), key=lambda kv: -kv[1].population_est.sum()):
            first = g.sort_values("area_km2").iloc[-1]
            zh, en = SPECIAL.get(key, (first.controller_name_zh or first.controller_name_en, first.controller_name_en))
            geom = dissolve([geom_of(p) for p in g.piece_id]) or polys(union([geom_of(p) for p in g.piece_id]))
            ci = len(countries)
            cindex[key] = ci
            comp = g.groupby("unit_name_zh", dropna=False).agg(pop=("population_est", "sum"),
                                                               km2=("area_km2", "sum")).sort_values("km2", ascending=False)
            countries.append([key, zh, en, color_of(key), BLOCS.index(Counter(g.bloc).most_common(1)[0][0]),
                              int(g.population_est.sum()), round(float(g.area_km2.sum())), int(g.admin_id.nunique()),
                              len(ctrl_geoms), [[n if isinstance(n, str) else "—", int(r["pop"]), round(float(r["km2"]))]
                                                for n, r in comp.head(12).iterrows()]])
            ctrl_geoms.append(geom)
            if key == "-20" or geom is None:
                continue
            for part in getattr(geom, "geoms", [geom]):
                km2 = part.area * (111.32 ** 2) * math.cos(math.radians(part.centroid.y))
                if km2 < LABEL_MIN_KM2:
                    continue
                anchor = label_anchor(part)
                if anchor:
                    clabels.append([ci] + anchor + [round(km2)])
        doc = {
            "snapshot": snap, "title_zh": tzh, "title_en": ten,
            "feature": [fidx[p] for p in d.piece_id], "unit": [uidx.get(u, -1) for u in d.unit_id],
            "country": [cindex[k] for k in d.country], "nation": [nidx[u] for u in d.unit_id], "nations": nations,
            "bloc": [BLOCS.index(b) for b in d.bloc], "conf": [CONF.index(c) if c in CONF else 0 for c in d.control_confidence],
            "ctrl_gw": [int(x) for x in d.controller_gwcode], "split": [int(x) for x in d.control_split],
            "area": [round(float(a), 1) for a in d.area_km2],
            "pop": [int(x) for x in d.population_est], "luts": luts, "rows": rows,
            "units_active": sorted(set(uidx[u] for u in d.unit_id if u in uidx)),
            "admin_active": sorted(set(aidx[a] for a in d.admin_id)), "unit_labels": lab,
            "countries": countries, "country_labels": clabels,
            "bloc_pop": {b: int(d[d.bloc == b].population_est.sum()) for b in BLOCS},
            "tier_count": {str(t): int(n) for t, n in hist.set_index("unit_id").loc[sorted(set(d.admin_id))]
                           .tier.value_counts().sort_index().items()},
        }
        (OUT / f"snap-{snap}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
        summary.append({"snapshot": snap, "title_zh": tzh, "title_en": ten, "pieces": len(d),
                        "admin_units": int(d.admin_id.nunique()), "countries": len(countries),
                        "population": int(d.population_est.sum()), "bloc_pop": doc["bloc_pop"],
                        "tier_count": doc["tier_count"]})
        print(snap, "pieces", len(d), "provinces", d.admin_id.nunique(), "countries", len(countries),
              "labels", len(clabels), flush=True)
    (OUT / "geo-ctrl.bin").write_bytes(encode(ctrl_geoms, TOL_CTRL))
    (OUT / "index.json").write_text(json.dumps({"snapshots": summary, "blocs": BLOCS, "tiers": TIER_ZH,
                                                "quantum": Q}, ensure_ascii=False, indent=1))
    hydro()
    for p in sorted(OUT.iterdir()):
        print(p.name, f"{p.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
