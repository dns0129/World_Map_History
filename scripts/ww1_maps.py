"""Add the 1915-1917 event-day maps to the early SQLite database and the map data.

Run as the ww1 job of pipeline.py (after the early database and ww2_webmap.py), or python3 scripts/ww1_maps.py
from a checkout. No raw downloads are required. Dated CShapes geometry and annual population come from
world_history_1900_2000.sqlite; historical divisions and their population pattern come from
divisions_1900_1934.sqlite. Modern reference regions are used only as explicitly approximate control masks,
never as the displayed historical administrative divisions.

Each date gets its own snap-<date>.json and geo-<date>.bin, in the layout ww2_webmap.py writes; the divisions
and pieces they add are appended to admin.bin, after those of the other dates. ww1-build.json records where
the appended part begins, so that a repeat run replaces it instead of adding it again. Database changes are
made in a transaction.
"""
import csv
import fnmatch
import gzip
import hashlib
import json
import math
import sqlite3
from collections import Counter
from itertools import count

import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon, shape

import cities
from build_database import Namer
from common import DB_DIR, ROOT
from ww2_common import SNAPSHOTS_WWI, WW2_OUT
from ww2_database import gj
from ww2_geo import diff, eq_area_km2, inter, polys, union
from ww2_webmap import (BLOCS, CONF, LABEL_MIN_KM2, TOL_CTRL, TOL_PROV, TOL_UNIT,
                        color_of, dissolve, encode, label_anchor, nation_of, packed, table)

DATES = {d for d, _, _ in SNAPSHOTS_WWI}
DATA = WW2_OUT / "maps" / "data"
DATABASE = DB_DIR / "divisions_1900_1934.sqlite"
RULES = ROOT / "curated" / "ww1_region_control.csv"
MARKER = DATA / "ww1-build.json"
BASE_DATE = "1914-08-04"
POP_METHOD = ("1914 historical province population density (original GHS-POP-derived estimates), "
              "or the existing 1918 estimate where no 1914 province exists; "
              "area-adjusted for new pieces and scaled to the same political unit's annual "
              "population in world_history_1900_2000.sqlite; rounded with conserved unit totals")
ALLIED_1915 = {200, 220, 365, 340, 345, 341, 211, 20, 900, 920, 560, 740, 325, -1}
ALLIED = {"1915-05-23": ALLIED_1915,
          "1916-08-27": ALLIED_1915 | {235, 360, -70},
          "1917-04-06": ALLIED_1915 | {235, 360, 2, -70, -76}}
AXIS = {"1915-05-23": {255, 300, 640},
        "1916-08-27": {255, 300, 640, 355},
        "1917-04-06": {255, 300, 640, 355}}
NOTES = {
    "1915-05-23": "意大利当日对奥匈宣战（战争状态次日生效），尚未对德国宣战；日本、黑山和奥斯曼已经参战，保加利亚、罗马尼亚、葡萄牙、美国、中国、希腊仍中立。东线在戈尔利采攻势期间，不能套用 1915 年秋的占领范围。",
    "1916-08-27": "罗马尼亚当日对奥匈宣战；意大利当日另对德国宣战。葡萄牙已于 3 月参战，保加利亚属同盟国。美国、中国、希腊仍未正式参战。罗马尼亚尚未遭到同盟国的冬季占领。",
    "1917-04-06": "美国当日对德国宣战（对奥匈宣战在 12 月）；俄国临时政府继续参加协约国战争。中国、巴西、暹罗尚未对德宣战，希腊尚未统一参战；萨洛尼卡临时政府及协约国驻军另作近似处理。俄国此时尚未发生十月革命，也未签订布列斯特和约。",
}
CONTROL_NOTE = ("控制区沿用原地图的省级近似方法。西线、加利西亚、非洲战场等没有精确战线资料的省份标为交战区；"
                "部分占领范围借用同一数据库的现代地区轮廓作近似裁切，并加斜线，不代表精确战线。"
                "人口为该年估计，并非事件日普查。历史区划缺失处保留整个政治单元。")


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def unpack(path):
    """A data file as bytes, gunzipped when it is gzip-compressed."""
    raw = path.read_bytes()
    return gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw


def decode_geo(raw):
    """Outlines of a geo-<date>.bin (unpacked), with the byte offset where each ends."""
    pos = 0
    boundaries = [0]
    geoms = []

    def varint():
        nonlocal pos
        value = shift = 0
        while True:
            if pos >= len(raw):
                raise ValueError("Truncated map geometry")
            b = raw[pos]
            pos += 1
            value |= (b & 127) << shift
            if not b & 128:
                return value
            shift += 7
            if shift > 63:
                raise ValueError("Invalid map geometry varint")

    while pos < len(raw):
        parts = []
        x = y = 0
        for _ in range(varint()):
            rings = []
            for _ in range(varint()):
                points = []
                for _ in range(varint()):
                    dx, dy = varint(), varint()
                    x += (dx >> 1) ^ -(dx & 1)
                    y += (dy >> 1) ^ -(dy & 1)
                    points.append((x / 1000, y / 1000))
                rings.append(points)
            parts.append(Polygon(rings[0], rings[1:]))
        geoms.append(MultiPolygon(parts) if len(parts) > 1 else parts[0])
        boundaries.append(pos)
    return geoms, boundaries


def matches(pattern, value):
    return any(fnmatch.fnmatchcase(str(value or ""), p) for p in pattern.split("|"))


def bloc(gw, snap):
    if gw == -20:
        return "contested"
    return "allied" if gw in ALLIED[snap] else "axis" if gw in AXIS[snap] else "neutral"


def names(units, snap):
    namer = Namer()
    out = {-1: ("Allied forces", "协约国联军"), -20: ("Contested front", "交战区（双方争夺）"),
           -70: ("Kingdom of Hejaz", "汉志王国"), -73: ("Outer Mongolia (Bogd Khanate)", "外蒙古（博克多汗国）"),
           -76: ("Greek Provisional Government of National Defence", "希腊国民防卫临时政府")}
    for u in units:
        if u["status"] == "independent":
            out[u["gwcode"]] = namer(u["cshapes_name"], "independent", int(snap[:4]))
    if snap == "1917-04-06":
        out[365] = ("Russia (Provisional Government)", "俄国（临时政府）")
    return out


def controller(gw, state_names, typ="independent", source="cshapes", confidence="whole", detail=None, detail_zh=None):
    en, zh = state_names.get(gw, (str(gw), str(gw)))
    return dict(controller_gwcode=gw, controller_name_en=en, controller_name_zh=zh,
                controller_detail_en=detail, controller_detail_zh=detail_zh,
                control_type=typ, control_source=source, control_confidence=confidence)


def load_rules(world):
    rules = list(csv.DictReader(RULES.open()))
    references = [dict(r) for r in world.execute("SELECT iso_3166_2, modern_country, geometry FROM admin1_pieces")]
    mask_cache = {}
    for row, rule in enumerate(rules, 2):
        rule["row"] = row
        pattern = rule["reference"]
        if pattern and pattern not in mask_cache:
            selected = [shape(json.loads(r["geometry"])) for r in references
                        if matches(pattern, r["iso_3166_2"]) or matches(pattern, r["modern_country"])]
            if not selected:
                raise ValueError(f"Control rule {row} has no reference geometry: {pattern}")
            mask_cache[pattern] = polys(union(selected))
        rule["mask"] = mask_cache.get(pattern)
    return rules


def control_parts(geom, admin, unit, snap, base, rules, state_names, rule_hits):
    parts = [(geom, base)]
    for rule in rules:
        if snap not in rule["snapshots"].split("|"):
            continue
        if not matches(rule["unit_match"], unit["cshapes_name"]):
            continue
        if not matches(rule["admin_match"], admin["admin_id"]):
            continue
        if rule["mask"] is not None and not geom.intersects(rule["mask"]):
            continue
        ctrl = controller(int(rule["controller_gwcode"]), state_names, rule["control_type"],
                          rule.get("source", f"ww1_rule:{rule['row']}"), rule["confidence"], rule["controller_name"], rule["controller_name_zh"])
        new_parts = []
        for g, previous in parts:
            inside = polys(inter(g, rule["mask"])) if rule["mask"] is not None else g
            if inside is None or eq_area_km2(inside) < 0.1:
                new_parts.append((g, previous))
                continue
            rule_hits.add((snap, rule["row"]))
            if rule["mask"] is not None:
                outside = polys(diff(g, rule["mask"]))
                if outside is not None:
                    new_parts.append((outside, previous))
            new_parts.append((inside, ctrl))
        parts = new_parts
    return parts


def population_target(world, unit, year):
    row = world.execute("SELECT population FROM unit_year WHERE year=? AND unit_id=?", (year, unit["unit_id"])).fetchone()
    if row is not None:
        return round(row[0])
    rows = world.execute("SELECT population, area_km2 FROM unit_year WHERE year=? AND cshapes_name=?",
                         (year, unit["cshapes_name"])).fetchall()
    if rows:
        return round(sum(r[0] for r in rows) * unit["area_km2"] / max(sum(r[1] for r in rows), 1))
    row = world.execute("SELECT population FROM unit_year WHERE unit_id=? ORDER BY ABS(year-?) LIMIT 1",
                        (unit["unit_id"], year)).fetchone()
    if row is None:
        raise ValueError(f"No population estimate for {unit['cshapes_name']} on {year}")
    return round(row[0])


def allocate_population(rows, total):
    weights = np.array([r.pop("weight") for r in rows], dtype=float)
    if weights.sum() <= 0:
        weights = np.array([r["area_km2"] for r in rows])
    values = weights / weights.sum() * total
    rounded = np.floor(values).astype(np.int64)
    remainder = total - int(rounded.sum())
    rounded[np.argsort(-(values - rounded), kind="stable")[:remainder]] += 1
    for r, pop in zip(rows, rounded):
        r["population_est"] = int(pop)


def new_admin(unit, geom, snap):
    pt = geom.representative_point()
    return dict(admin_id=f"WW1-CSH-{unit['unit_id']}", name=unit["unit_name_en"], name_zh=unit["unit_name_zh"],
                name_en=unit["unit_name_en"], tier=5, tier_zh="整个政治单元", tier_en="whole political unit",
                kind="historical political unit (remainder)", basis="historical_unit", source="CShapes 2.0",
                note="历史省级资料缺失的剩余区域；采用当日政治单元边界，不表示省级区划。", start_date=unit["start_date"],
                end_date=unit["end_date"], partial=1, parent=None, parent_zh=None, grandparent=None, ohm_level=None,
                wikidata=None, merged_units=0, snapshots=snap, area_km2=eq_area_km2(geom), label_lon=pt.x,
                label_lat=pt.y, geometry=gj(geom))


def build_snapshot(con, world, snap, rules, rule_hits):
    year = int(snap[:4])
    active = [dict(r) for r in world.execute("SELECT * FROM units WHERE start_date<=? AND end_date>=? ORDER BY unit_id", (snap, snap))]
    state_names = names(active, snap)
    namer = Namer()
    admins = [dict(r) for r in con.execute("SELECT * FROM admin_units WHERE snapshots LIKE '%1914-08-04%' ORDER BY tier, admin_id")
              if (not r["start_date"] or r["start_date"] <= snap) and (not r["end_date"] or r["end_date"] >= snap)]
    # Only explicitly dated replacements can add divisions absent in the 1914 reference.
    replacements = [dict(r) for r in con.execute("SELECT * FROM admin_units WHERE tier<=4 AND "
                                               "((start_date>? AND start_date<=?) OR basis='historical_1897') "
                                               "AND (end_date IS NULL OR end_date>=?) AND admin_id NOT LIKE 'WW1-%' ORDER BY admin_id",
                                               (BASE_DATE, snap, snap))]
    candidate_ids = {a["admin_id"] for a in admins}
    admins = [a for a in replacements if a["admin_id"] not in candidate_ids and a["basis"] != 'historical_1897'] + admins + [
        a for a in replacements if a["admin_id"] not in candidate_ids and a["basis"] == 'historical_1897']
    geoms = [polys(shape(json.loads(a["geometry"]))) for a in admins]
    tree = STRtree(geoms)
    density = {r[0]: r[1] / max(r[2], 1) for r in con.execute(
        "SELECT admin_id,SUM(population_est),SUM(area_km2) FROM snapshot_full WHERE snapshot='1918-11-11' GROUP BY admin_id")}
    density.update({r[0]: r[1] / max(r[2], 1) for r in con.execute(
        "SELECT admin_id,SUM(population_est),SUM(area_km2) FROM snapshot_full WHERE snapshot=? GROUP BY admin_id", (BASE_DATE,))})
    base_controls = {r["admin_id"]: dict(r) for r in con.execute(
        "SELECT * FROM snapshot_full WHERE snapshot=? AND control_source LIKE 'overlay:%'", (BASE_DATE,))}
    events = [dict(r) for r in con.execute("SELECT * FROM control_events WHERE start_date<=? AND end_date>=?", (snap, snap))]
    output, used_admins, unit_geoms = [], {}, {}
    for u in active:
        ug = polys(shape(json.loads(u["geometry"])))
        if ug is None:
            continue
        uid = u["unit_id"]
        unit_geoms[uid] = ug
        u["unit_name_en"], u["unit_name_zh"] = namer(u["cshapes_name"], u["status"], year)
        if u["gwcode"] == 365 and snap == "1917-04-06":
            u["unit_name_en"], u["unit_name_zh"] = state_names[365]
        owner = int(str(u["owner_gwcode"]).split(";")[0])
        sov_en, sov_zh = state_names.get(owner, (str(owner), str(owner)))
        unit_fields = dict(snapshot=snap, unit_id=uid, unit_gwcode=u["gwcode"], unit_name_en=u["unit_name_en"],
                           unit_name_zh=u["unit_name_zh"], unit_status=u["status"], sovereign_gwcode=owner,
                           sovereign_name_en=sov_en, sovereign_name_zh=sov_zh,
                           partial_control_events="|".join(e["event_id"] for e in events if e["scope"] == "partial"
                               and (e["unit_name"] == u["cshapes_name"] or e["unit_gwcode"] == u["gwcode"])) or None)
        base = controller(owner, state_names, u["status"])
        for e in events:
            if e["scope"] == "whole" and (e["unit_name"] == u["cshapes_name"] or e["unit_gwcode"] == u["gwcode"]):
                base = controller(e["controller_gwcode"], state_names, e["control_type"], f"event:{e['event_id']}",
                                  detail=e["controller_name"], detail_zh=e["controller_name_zh"])
        remaining = ug
        unit_rows = []

        def add(a, g):
            used_admins[a["admin_id"]] = a
            ctrl = base
            inherited = base_controls.get(a["admin_id"])
            if inherited and inherited["control_source"] == "overlay:kwantung":
                ctrl = {k: inherited[k] for k in base}
            for part, control in control_parts(g, a, u, snap, ctrl, rules, state_names, rule_hits):
                area = eq_area_km2(part)
                if area < 0.01:
                    continue
                row = dict(unit_fields, admin_id=a["admin_id"], area_km2=area, geom=part, **control)
                row["bloc"] = bloc(control["controller_gwcode"], snap)
                row["weight"] = area * density.get(a["admin_id"], 1)
                row["control_split"] = int(control != base)
                row["piece_id"] = f"WW1:{snap}:{uid}:{a['admin_id']}:{len(unit_rows)}"
                unit_rows.append(row)

        for i in sorted(tree.query(ug, predicate="intersects")):
            if remaining is None:
                break
            a = admins[i]
            cut = polys(inter(remaining, geoms[i]))
            if cut is None or eq_area_km2(cut) < 0.1:
                continue
            add(a, cut)
            remaining = polys(diff(remaining, geoms[i]))
        if remaining is not None and eq_area_km2(remaining) >= 0.01:
            aid = f"WW1-CSH-{uid}"
            existing = con.execute("SELECT * FROM admin_units WHERE admin_id=?", (aid,)).fetchone()
            a = dict(existing) if existing else new_admin(u, remaining, snap)
            add(a, remaining)
        if not unit_rows:
            raise ValueError(f"Empty political unit: {uid}")
        allocate_population(unit_rows, population_target(world, u, year))
        output.extend(unit_rows)
    # Small island territories absent from CShapes retain the original database's records.
    for r in con.execute("SELECT s.*,p.geometry AS piece_geometry,a.geometry AS admin_geometry FROM snapshot_full s "
                         "JOIN pieces p USING(piece_id) JOIN admin_units a USING(admin_id) WHERE s.snapshot=? AND s.unit_id<0", (BASE_DATE,)):
        row = dict(r)
        a = dict(con.execute("SELECT * FROM admin_units WHERE admin_id=?", (row["admin_id"],)).fetchone())
        if (a["start_date"] and a["start_date"] > snap) or (a["end_date"] and a["end_date"] < snap):
            continue
        used_admins[a["admin_id"]] = a
        row.update(snapshot=snap, piece_id=f"WW1:{snap}:{row['piece_id']}",
                   geom=polys(shape(json.loads(row["piece_geometry"] or row["admin_geometry"]))),
                   bloc=bloc(row["controller_gwcode"], snap))
        output.append(row)
    piece_counts = Counter(r["admin_id"] for r in output)
    for r in output:
        r["control_split"] = int(piece_counts[r["admin_id"]] > 1)
    return output, used_admins, unit_geoms


def store_snapshot(con, rows, admins, snapshot):
    snap, zh, en = snapshot
    for aid, a in admins.items():
        existing = con.execute("SELECT admin_key,snapshots FROM admin_units WHERE admin_id=?", (aid,)).fetchone()
        if existing:
            memberships = sorted(set((existing["snapshots"] or "").split("|")) | {snap})
            con.execute("UPDATE admin_units SET snapshots=? WHERE admin_key=?", ("|".join(memberships), existing["admin_key"]))
        else:
            columns = [r[1] for r in con.execute("PRAGMA table_info(admin_units)") if r[1] != "admin_key"]
            con.execute(f"INSERT INTO admin_units ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                        [a.get(k) for k in columns])
    admin_keys = dict(con.execute("SELECT admin_id,admin_key FROM admin_units"))
    ccols = [r[1] for r in con.execute("PRAGMA table_info(controls)") if r[1] != "control_id"]
    controls = {tuple(r[k] for k in ccols): r["control_id"] for r in con.execute("SELECT * FROM controls")}
    con.execute("INSERT OR IGNORE INTO pop_methods(pop_method) SELECT ? WHERE NOT EXISTS "
                "(SELECT 1 FROM pop_methods WHERE pop_method=?)", (POP_METHOD, POP_METHOD))
    method = con.execute("SELECT pop_method_id FROM pop_methods WHERE pop_method=?", (POP_METHOD,)).fetchone()[0]
    unit_seen = set()
    for r in rows:
        if r["unit_id"] not in unit_seen:
            columns = [v[1] for v in con.execute("PRAGMA table_info(unit_snapshot)")]
            con.execute(f"INSERT INTO unit_snapshot VALUES ({','.join('?' for _ in columns)})", [r[k] for k in columns])
            unit_seen.add(r["unit_id"])
        key = tuple(r[k] for k in ccols)
        if key not in controls:
            cur = con.execute(f"INSERT INTO controls({','.join(ccols)}) VALUES ({','.join('?' for _ in ccols)})", key)
            controls[key] = cur.lastrowid
        cur = con.execute("INSERT INTO pieces(piece_id,admin_key,area_km2,geometry) VALUES (?,?,?,?)",
                          (r["piece_id"], admin_keys[r["admin_id"]], r["area_km2"], gj(r["geom"])))
        con.execute("INSERT INTO piece_snapshot VALUES (?,?,?,?,?,?,?,?)", (snap, cur.lastrowid, r["unit_id"],
                    controls[key], r["control_split"], r["area_km2"], r["population_est"], method))
    pops = Counter()
    for r in rows:
        pops[r["bloc"]] += r["population_est"]
    con.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)", (snap, zh, en, len(admins), sum(pops.values()),
                *[pops[b] for b in BLOCS]))


def static_hash(static):
    return hashlib.sha256(json.dumps(static, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def base_assets():
    """admin.bin and index.json as ww2_webmap.py wrote them. When this script has run on them before, what it
    appended (divisions, pieces, look-up values, the three dates) is taken off again, back to the lengths
    ww1-build.json recorded; the checksum there makes sure nothing else changed since."""
    static, index = json.loads(unpack(DATA / "admin.bin")), read_json(DATA / "index.json")
    if any(s["snapshot"] in DATES for s in index["snapshots"]):
        old = read_json(MARKER)
        n = static["n"] = old["admins"]
        for col in ("admin_id", "tier", "partial", "merged", "area", "label"):
            static[col] = static[col][:n]
        for key, col in static["cols"].items():
            col["idx"] = col["idx"][:n]
            col["lut"] = col["lut"][:old["luts"][key]]
        static["feature_admin"] = static["feature_admin"][:old["features"]]
        if static_hash(static) != old["sha256"]:
            raise ValueError("admin.bin changed since ww1_maps.py last ran; run ww2_webmap.py before ww1_maps.py")
        index["snapshots"] = [s for s in index["snapshots"] if s["snapshot"] not in DATES]
    marker = {"admins": static["n"], "features": len(static["feature_admin"]),
              "luts": {k: len(c["lut"]) for k, c in static["cols"].items()}, "sha256": static_hash(static)}
    return static, index, marker


def append_admin(static, a):
    aid = "E:" + a["admin_id"]
    if aid in static["admin_id"]:
        return static["admin_id"].index(aid)
    i = static["n"]
    static["n"] += 1
    static["admin_id"].append(aid)
    for key, value in dict(tier=a["tier"], partial=a["partial"] or 0, merged=a["merged_units"] or 0,
                           area=round(a["area_km2"], 1), label=[round(a["label_lon"], 3), round(a["label_lat"], 3)]).items():
        static[key].append(value)
    for key, col in static["cols"].items():
        value = a.get({"start": "start_date", "end": "end_date"}.get(key, key))
        if value not in col["lut"]:
            col["lut"].append(value)
        col["idx"].append(col["lut"].index(value))
    return i


def anchors(g):
    for p in getattr(g, "geoms", [g]):
        km2 = p.area * 111.32 ** 2 * math.cos(math.radians(p.centroid.y))
        if km2 >= LABEL_MIN_KM2:
            a = label_anchor(p)
            if a:
                yield a + [round(km2)]


def export_snapshot(rows, admins, ug, snapshot, static, unit_indices, new_unit):
    """The date's snap-<date>.json and its summary for index.json; writes its geo-<date>.bin."""
    snap, zh, en = snapshot
    d = pd.DataFrame(rows)
    features, admin_indices, admin_rec, piece_rec = [], {}, {}, {}
    for r in rows:
        a = admins[r["admin_id"]]
        if r["admin_id"] not in admin_indices:
            ai = admin_indices[r["admin_id"]] = append_admin(static, a)
            admin_rec[ai] = encode([shape(json.loads(a["geometry"]))], TOL_PROV)
        fi = len(static["feature_admin"])
        static["feature_admin"].append(admin_indices[r["admin_id"]])
        features.append(fi)
        if r["area_km2"] < 0.999 * a["area_km2"]:  # cut from its division: an outline of its own
            piece_rec[fi] = encode([r["geom"]], TOL_PROV)
    # the date's units with an outline (territories CShapes does not draw have none), in index order
    for uid in ug:
        if uid not in unit_indices:
            unit_indices[uid] = next(new_unit)
    unit_list = sorted({r["unit_id"] for r in rows if r["unit_id"] in ug}, key=unit_indices.get)
    luts, lut_rows = {}, {}
    for col in ("unit_name_zh", "unit_name_en", "unit_status", "sovereign_name_zh", "controller_name_zh",
                "controller_name_en", "controller_detail_zh", "controller_detail_en", "control_type",
                "control_source", "partial_control_events"):
        luts[col], lut_rows[col] = table(d[col].tolist())
    nations, nation_indices, unit_labels = [], {}, []
    for uid, group in sorted(d.groupby("unit_id"), key=lambda kv: -kv[1].population_est.sum()):
        first = group.iloc[0].to_dict()
        nation_indices[uid] = len(nations)
        nations.append([int(uid), first["unit_name_zh"] or first["unit_name_en"], first["unit_name_en"], nation_of(first),
                        first["unit_status"], first["sovereign_name_zh"], int(group.population_est.sum()), round(group.area_km2.sum())])
        if uid in ug:
            big = max(getattr(ug[uid], "geoms", [ug[uid]]), key=lambda g: g.area)
            a = label_anchor(big)
            if a:
                unit_labels.append([unit_indices[uid], first["unit_name_zh"] or first["unit_name_en"]] + a + [round(eq_area_km2(big))])
    countries, country_indices, country_labels, ctrl_geoms = [], {}, [], []
    for gw, group in sorted(d.groupby("controller_gwcode"), key=lambda kv: -kv[1].population_est.sum()):
        home = group[group.unit_gwcode == gw]
        first = (home if len(home) else group).sort_values("area_km2").iloc[-1]
        ci = len(countries)
        country_indices[gw] = ci
        geom = dissolve(group.geom.tolist()) or polys(union(group.geom.tolist()))
        comp = group.groupby("unit_name_zh", dropna=False).agg(pop=("population_est", "sum"), km2=("area_km2", "sum"))
        countries.append([str(int(gw)), first.controller_name_zh or first.controller_name_en, first.controller_name_en,
                          color_of(str(int(gw))), BLOCS.index(first.bloc), int(group.population_est.sum()),
                          round(group.area_km2.sum()), int(group.admin_id.nunique()), len(ctrl_geoms),
                          [[n if isinstance(n, str) else "—", int(r["pop"]), round(r.km2)]
                           for n, r in comp.sort_values("km2", ascending=False).head(12).iterrows()]])
        ctrl_geoms.append(geom)
        if gw != -20:
            country_labels.extend([ci] + a for a in anchors(geom))
    doc = dict(snapshot=snap, title_zh=zh, title_en=en, feature=features,
               unit=[unit_indices[r["unit_id"]] if r["unit_id"] in ug else -1 for r in rows], country=[country_indices[r["controller_gwcode"]] for r in rows],
               nation=[nation_indices[r["unit_id"]] for r in rows], nations=nations, bloc=[BLOCS.index(r["bloc"]) for r in rows],
               conf=[CONF.index(r["control_confidence"]) for r in rows], ctrl_gw=[r["controller_gwcode"] for r in rows],
               split=[r["control_split"] for r in rows], area=[round(r["area_km2"], 1) for r in rows],
               pop=[r["population_est"] for r in rows], luts=luts, rows=lut_rows,
               units_active=[unit_indices[u] for u in unit_list],
               admin_active=sorted(admin_indices.values()), unit_labels=unit_labels, geo_feature=sorted(piece_rec),
               countries=countries,
               country_labels=country_labels, cities=cities.ww2(snap, use_curated_coordinates=True),
               bloc_names={"allied": "协约国及其盟国（已参战）", "axis": "同盟国（已参战）", "neutral": "中立国 / 尚未参战", "contested": "交战区"},
               notes=dict(bloc_title="参战国 · 人口", bloc=NOTES[snap], control=CONTROL_NOTE),
               bloc_pop={b: sum(r["population_est"] for r in rows if r["bloc"] == b) for b in BLOCS},
               tier_count={str(t): n for t, n in sorted(Counter(a["tier"] for a in admins.values()).items())})
    summary = dict(snapshot=snap, title_zh=zh, title_en=en, pieces=len(rows), admin_units=len(admins), countries=len(countries),
                   population=sum(doc["pop"]), bloc_pop=doc["bloc_pop"], tier_count=doc["tier_count"])
    # in the order the page reads them: divisions, cut pieces, units, control areas (see ww2_webmap.py)
    packed(DATA / f"geo-{snap}.bin", b"".join([admin_rec[a] for a in doc["admin_active"]]
                                              + [piece_rec[f] for f in doc["geo_feature"]]
                                              + [encode([ug[u]], TOL_UNIT) for u in unit_list])
           + encode(ctrl_geoms, TOL_CTRL))
    return doc, summary


def coverage(con):
    d = pd.read_sql_query("SELECT * FROM snapshot_full", con)
    rows, units = [], []
    for snap, group in d.groupby("snapshot"):
        for tier, part in group.groupby("tier"):
            rows.append(dict(snapshot=snap, tier=int(tier), tier_zh=part.tier_zh.iloc[0], admin_units=int(part.admin_id.nunique()),
                             area_km2=round(part.area_km2.sum()), population_est=int(part.population_est.sum()),
                             area_share=round(part.area_km2.sum() / group.area_km2.sum(), 4),
                             pop_share=round(part.population_est.sum() / group.population_est.sum(), 4)))
        for (_, _), part in group.groupby(["unit_name_zh", "unit_name_en"]):
            total = max(part.population_est.sum(), 1)
            units.append(dict(snapshot=snap, unit_name_zh=part.unit_name_zh.iloc[0], unit_name_en=part.unit_name_en.iloc[0],
                              population_est=int(part.population_est.sum()), provinces=int(part[part.tier == 3].admin_id.nunique()),
                              finest_tier=int(part.tier.min()), pop_share_province=round(part[part.tier == 3].population_est.sum()/total, 3),
                              pop_share_region_or_finer=round(part[part.tier <= 4].population_est.sum()/total, 3)))
    return pd.DataFrame(rows), pd.DataFrame(units)


def main():
    static, index, marker = base_assets()
    # Existing unit indices are recoverable from each snapshot's parallel nation/unit arrays; new units are
    # numbered after all of them
    unit_indices, top = {}, -1
    for s in index["snapshots"]:
        doc = read_json(DATA / f"snap-{s['snapshot']}.json")
        top = max([top] + doc["units_active"])
        for ui, ni in zip(doc["unit"], doc["nation"]):
            if ui >= 0:
                uid = doc["nations"][ni][0]
                # 2026 has a separate id space; it must not alias historical CShapes ids.
                if s["snapshot"] != "2026":
                    unit_indices[uid] = ui
    new_unit = count(top + 1)
    con = sqlite3.connect(DATABASE)
    con.row_factory = sqlite3.Row
    world = sqlite3.connect(f"file:{DB_DIR / 'world_history_1900_2000.sqlite'}?mode=ro", uri=True)
    world.row_factory = sqlite3.Row
    rules = load_rules(world)
    # Retain dated enclaves already curated in the original 1914 map. Use each
    # original piece as a mask rather than assigning its whole parent province.
    inherited_rules = []
    for r in con.execute("SELECT s.*,p.geometry AS pg,a.geometry AS ag FROM snapshot_full s JOIN pieces p USING(piece_id) "
                         "JOIN admin_units a USING(admin_id) WHERE s.snapshot=? AND s.control_source IN ('rule:8','rule:9','rule:69','overlay:kwantung')", (BASE_DATE,)):
        inherited_rules.append(dict(snapshots="|".join(sorted(DATES)), unit_match="*", admin_match="*", row=-len(inherited_rules)-1,
                                    controller_gwcode=r["controller_gwcode"], controller_name=r["controller_detail_en"] or r["controller_name_en"],
                                    controller_name_zh=r["controller_detail_zh"] or r["controller_name_zh"], control_type=r["control_type"],
                                    confidence=r["control_confidence"], source=f"baseline:{BASE_DATE}:{r['control_source']}",
                                    mask=polys(shape(json.loads(r["pg"] or r["ag"])))))
    documents, rule_hits = {}, set()
    with con:
        for snap in DATES:
            con.execute("DELETE FROM piece_snapshot WHERE snapshot=?", (snap,))
            con.execute("DELETE FROM unit_snapshot WHERE snapshot=?", (snap,))
            con.execute("DELETE FROM snapshots WHERE snapshot=?", (snap,))
        con.execute("DELETE FROM pieces WHERE piece_id LIKE 'WW1:%'")
        for snapshot in SNAPSHOTS_WWI:
            rows, admins, ug = build_snapshot(con, world, snapshot[0], inherited_rules + rules, rule_hits)
            store_snapshot(con, rows, admins, snapshot)
            doc, summary = export_snapshot(rows, admins, ug, snapshot, static, unit_indices, new_unit)
            documents[snapshot[0]] = doc
            index["snapshots"].append(summary)
            print(snapshot[0], len(rows), "pieces;", len(admins), "historical divisions;", len(doc["countries"]), "controllers", flush=True)
        missing = [(snap, r["row"]) for r in rules for snap in r["snapshots"].split("|") if (snap, r["row"]) not in rule_hits]
        if missing:
            raise ValueError(f"Unmatched control rules: {missing}")
        con.execute("DELETE FROM control_rules WHERE field LIKE 'ww1:%'")
        next_row = con.execute("SELECT COALESCE(MAX(row),1)+1 FROM control_rules").fetchone()[0]
        for offset, rule in enumerate(rules):
            con.execute("INSERT INTO control_rules VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (next_row+offset, rule["snapshots"], "*", f"ww1:{rule['row']}",
                         f"unit={rule['unit_match']};admin={rule['admin_match']};reference={rule['reference']}",
                         rule["controller_name"], rule["controller_name_zh"], int(rule["controller_gwcode"]),
                         rule["control_type"], rule["confidence"], rule["note"] + " Source: " + rule["source_url"]))
        meta = dict(snapshots=";".join(r[0] for r in con.execute("SELECT snapshot FROM snapshots ORDER BY snapshot")),
                    wwi_method=POP_METHOD, wwi_control="curated/ww1_region_control.csv; approximate reference masks flagged in controls")
        con.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", meta.items())
        for i, url in enumerate(sorted({r["source_url"] for r in rules}), 1):
            con.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?)", (f"ww1-control-{i}", "WWI control reference",
                         "Historical facts underlying curated/ww1_region_control.csv; see each rule's note", url,
                         "Reference text: respective publisher; curated rules: CC0", "1915-1917 event-day control facts; no source text or source map reproduced"))
        cov, cov_units = coverage(con)
    con.execute("VACUUM")
    con.close()
    world.close()
    for snap, doc in documents.items():
        write_json(DATA / f"snap-{snap}.json", doc)
    index["snapshots"].sort(key=lambda s: s["snapshot"])
    packed(DATA / "admin.bin", json.dumps(static, ensure_ascii=False, separators=(",", ":")).encode())
    write_json(DATA / "index.json", index)
    write_json(MARKER, marker)
    cov.to_csv(WW2_OUT / "coverage_1900_1934.csv", index=False)
    cov_units.to_csv(WW2_OUT / "coverage_by_unit_1900_1934.csv", index=False)
    print("Updated", DATABASE, "and", DATA)


if __name__ == "__main__":
    main()
