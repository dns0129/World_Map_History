"""Add dates to a set's SQLite database and to the map data, without rebuilding the set.

The dates, and everything particular to them, are in added_dates.py: groups of dates, each added to the
database of one set (ww2 1939-45, early 1900-34, postwar 1946-91) from the divisions of one of its dates (the
base date). Run as the `added` job of pipeline.py (after the sets' databases and ww2_webmap.py), or
python3 scripts/add_snapshots.py from a checkout. No raw downloads are required. Dated CShapes geometry and
annual population come from world_history_1900_2000.sqlite; historical divisions and their population pattern
come from the set's database. Modern reference regions are used only as explicitly approximate control masks,
never as the displayed historical administrative divisions.

Each date gets its own snap-<date>.json and geo-<date>.bin, in the layout ww2_webmap.py writes; the divisions
and pieces they add are appended to admin.bin, after those of the other dates. added-build.json records where
the appended part begins, so that a repeat run replaces it instead of adding it again. Database changes are
made in a transaction, one per database.

Control rules (curated/<group.rules>), applied in file order, a later match overriding an earlier one:
  snapshots       dates the rule applies to, "|"-separated
  unit_match      CShapes name of the political unit ("*" wildcards, "|"-separated)
  admin_match     admin_id of the historical division ("*" wildcards, "|"-separated)
  reference       optional: ISO 3166-2 codes or present-day country names of reference regions (admin1_pieces of
                  the yearly database), or base:<source>|<source> for the pieces those control sources (rule:35,
                  overlay:mengjiang, ...) held on the base date, or file:<path under curated/>#<side>|<side> for the
                  polygons of a GeoJSON file with those `side` properties, or several of these joined by "&" for
                  the part of the first inside all the others; only the part of a division inside them is
                  assigned (a mask, never shown as a division)
  controller_name, controller_name_zh, controller_gwcode, control_type, confidence (whole / approximate), note,
  source_url
A rule that matches nothing on one of its dates stops the build.
"""
import csv
import fnmatch
import gzip
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from itertools import count

import numpy as np
import pandas as pd
from shapely import STRtree, make_valid, prepare
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon, box, shape

import cities
from added_dates import GROUPS
from build_database import Namer
from common import DB_DIR, ROOT
from ww2_common import COVERAGE_SUFFIX, DATABASES, SNAPSHOTS_EARLY, SNAPSHOTS_POSTWAR, SNAPSHOTS_WW2, WW2_OUT
from ww2_database import gj
from ww2_geo import diff, eq_area_km2, inter, polys, union
from ww2_webmap import (BLOCS, CONF, LABEL_MIN_KM2, SPECIAL, TOL_CTRL, TOL_PROV, TOL_UNIT,
                        color_of, dissolve, encode, label_anchor, nation_of, packed, table)

DATES = {s.date for g in GROUPS for s in g.snapshots}
DATA = WW2_OUT / "maps" / "data"
MARKER = DATA / "added-build.json"
# the dates ww2_webmap.py writes; any other date in index.json was added here
WEBMAP_DATES = {d for d, _, _ in SNAPSHOTS_EARLY + SNAPSHOTS_WW2 + SNAPSHOTS_POSTWAR} | {"2026"}
# how ww2_webmap.py prefixes the ids of each set's divisions in admin.bin
PREFIX = {"ww2": "", "early": "E:", "postwar": "P:"}


TILE_DEG = 10  # land without provinces is divided into tiles of this size (degrees)
SHARED = "ADD"  # piece_id prefix of the pieces the added dates store (one outline per division and cut)


def own_outline(r, a):
    """Whether a row's piece keeps an outline of its own: cut from its division, or the land without provinces of
    a group (KEY-CSH-<unit>-<tile>) where it differs from the outline its division was built with on its first date by more
    than 1% of its area (the divisions around it end and begin)."""
    if r["control_split"]:
        return True
    if re.fullmatch(r"[A-Z0-9]+-CSH-\d+-\d+_\d+", r["admin_id"]) is None:
        return False
    # slivers under min_piece_km2 merged into it are left out (they would store the whole outline again)
    return abs(r["area_km2"] - (a.get("area_km2") or 0)) > 0.01 * max(r["area_km2"], 1)


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


def outline(text):
    """A GeoJSON outline from the database as Polygon/MultiPolygon. A few rings that touch themselves defeat
    the default repair (Tierra del Fuego in 1914: "Overlay input is mixed-dimension"); the structural one
    keeps the same area."""
    g = shape(json.loads(text))
    try:
        return polys(g)
    except GEOSException:
        return polys(make_valid(g, method="structure"))


def matches(pattern, value):
    return any(fnmatch.fnmatchcase(str(value or ""), p) for p in pattern.split("|"))


def bloc(gw, s):
    if gw == -20:
        return "contested"
    return "allied" if gw in s.allied else "axis" if gw in s.axis else "neutral"


def names(units, group, s):
    """Controller names on the date: the independent states as the period called them (unit_names.csv), then the
    group's names (its own codes, or short names it prefers), then the date's own names."""
    namer = Namer()
    out = {}
    for u in units:
        if u["status"] == "independent":
            out[u["gwcode"]] = namer(u["cshapes_name"], "independent", int(s.date[:4]))
    out.update(group.names)
    out.update(s.names)
    return out


def absorb(rows, min_km2):
    """Merge the pieces of one political unit smaller than min_km2 (slivers between outlines from different
    sources) into the largest piece of the same division, else into the largest piece they touch."""
    for r in sorted((r for r in rows if r["area_km2"] < min_km2), key=lambda r: r["area_km2"]):
        others = [o for o in rows if o is not r]
        same = [o for o in others if o["admin_id"] == r["admin_id"]]
        near = r["geom"].buffer(0.01)
        touching = [o for o in others if o["geom"].intersects(near)]
        target = max(same or touching, key=lambda o: o["area_km2"], default=None)
        if target is None:
            continue
        target["geom"] = polys(union([target["geom"], r["geom"]]))
        target["area_km2"] += r["area_km2"]
        target["weight"] += r["weight"]
        rows.remove(r)


def controller(gw, state_names, typ="independent", source="cshapes", confidence="whole", detail=None, detail_zh=None):
    en, zh = state_names.get(gw, (str(gw), str(gw)))
    return dict(controller_gwcode=gw, controller_name_en=en, controller_name_zh=zh,
                controller_detail_en=detail, controller_detail_zh=detail_zh,
                control_type=typ, control_source=source, control_confidence=confidence)


def mask(con, group, pattern, references, land, row):
    """The reference geometry of one pattern (see the module docstring)."""
    def regions(p):
        return [r["shape"] for r in references if matches(p, r["iso_3166_2"]) or matches(p, r["modern_country"])]
    if pattern.startswith("file:"):  # polygons of a GeoJSON file under curated/ whose `side` is listed
        path, _, wanted = pattern[5:].partition("#")
        feats = json.loads((ROOT / "curated" / path).read_text())["features"]
        selected = [shape(f["geometry"]) for f in feats
                    if not wanted or f["properties"].get("side") in wanted.split("|")]
    elif pattern.startswith("base:"):  # the pieces these control sources held on the base date, or of those
        sources, _, within = pattern[5:].partition("@")  # the ones lying in these regions
        sources = sources.split("|")
        selected = [outline(r[0] or r[1]) for r in con.execute(
            "SELECT p.geometry,a.geometry FROM snapshot_full s JOIN pieces p USING(piece_id) JOIN admin_units a "
            f"USING(admin_id) WHERE s.snapshot=? AND s.control_source IN ({','.join('?' * len(sources))})",
            (group.base, *sources))]
        if within:
            area = polys(union(regions(within)))
            selected = [g for g in selected if area.covers(g.representative_point())]
    else:
        selected = regions(pattern)
        if selected and group.coast_deg:  # out to sea, not into other regions: coasts drawn further out
            grown = union(selected).buffer(group.coast_deg)
            others = [references[i]["shape"] for i in land.query(grown, predicate="intersects")
                      if not any(references[i]["shape"] is g for g in selected)]
            sea = polys(diff(grown, union(others))) if others else grown
            if sea is not None:
                selected = selected + [sea]
    if not selected:
        raise ValueError(f"Control rule {row} has no reference geometry: {pattern}")
    return polys(union(selected))


def load_rules(con, world, group):
    rules = list(csv.DictReader((ROOT / "curated" / group.rules).open()))
    references = [dict(r) for r in world.execute("SELECT iso_3166_2, modern_country, geometry FROM admin1_pieces")]
    for r in references:
        r["shape"] = shape(json.loads(r["geometry"]))
    land = STRtree([r["shape"] for r in references])
    mask_cache = {}
    for row, rule in enumerate(rules, 2):
        rule["row"] = row
        rule["source"] = f"{group.key}_rule:{row}"
        pattern = rule["reference"]
        if pattern and pattern not in mask_cache:
            parts = [mask(con, group, part, references, land, row) for part in pattern.split("&")]
            m = parts[0]
            for other in parts[1:]:  # "a&b": the part of a inside b
                m = polys(m.intersection(other))
            if m is None or m.is_empty:
                raise ValueError(f"Control rule {row} has no reference geometry: {pattern}")
            mask_cache[pattern] = m
            prepare(mask_cache[pattern])
        rule["mask"] = mask_cache.get(pattern)
        rule["bounds"] = rule["mask"].bounds if rule["mask"] is not None else None
    return rules


def overlaps(a, b):
    """Whether two bounding boxes (minx, miny, maxx, maxy) meet."""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def control_parts(geom, admin, unit, snap, base, rules, state_names, rule_hits):
    parts = [(geom, base)]
    for rule in rules:
        if snap not in rule["snapshots"].split("|"):
            continue
        if not matches(rule["unit_match"], unit["cshapes_name"]):
            continue
        if not matches(rule["admin_match"], admin["admin_id"]):
            continue
        if rule["mask"] is not None and (not overlaps(geom.bounds, rule["bounds"]) or not geom.intersects(rule["mask"])):
            continue
        ctrl = controller(int(rule["controller_gwcode"]), state_names, rule["control_type"],
                          rule["source"], rule["confidence"], rule["controller_name"], rule["controller_name_zh"])
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


def new_admin(unit, geom, snap, group, aid):
    pt = geom.representative_point()
    return dict(admin_id=aid, name=unit["unit_name_en"], name_zh=unit["unit_name_zh"],
                name_en=unit["unit_name_en"], tier=5, tier_zh="整个政治单元", tier_en="whole political unit",
                kind="historical political unit (remainder)", basis="historical_unit", source="CShapes 2.0",
                note="历史省级资料缺失的剩余区域；采用当日政治单元边界，不表示省级区划。", start_date=unit["start_date"],
                end_date=unit["end_date"], partial=1, parent=None, parent_zh=None, grandparent=None, ohm_level=None,
                wikidata=None, merged_units=0, snapshots=snap, area_km2=eq_area_km2(geom), label_lon=pt.x,
                label_lat=pt.y, geometry=gj(geom))


def build_snapshot(con, world, group, s, rules, rule_hits):
    snap, base_date = s.date, group.base
    year = int(snap[:4])
    active = [dict(r) for r in world.execute("SELECT * FROM units WHERE start_date<=? AND end_date>=? ORDER BY unit_id", (snap, snap))]
    state_names = names(active, group, s)
    namer = Namer()
    admins = [dict(r) for r in con.execute("SELECT * FROM admin_units WHERE snapshots LIKE ? ORDER BY tier, admin_id",
                                           (f"%{base_date}%",))
              if (not r["start_date"] or r["start_date"] <= snap) and (not r["end_date"] or r["end_date"] >= snap)]
    # Only explicitly dated replacements can add divisions absent on the base date: those set up between the
    # base date and this date (or, for a date before the base date, those that ended between them), and the
    # 1897 Russian provinces, which fill the gaps last
    between = "(start_date>? AND start_date<=?)" if snap >= base_date else "(end_date>=? AND end_date<?)"
    bounds = (base_date, snap) if snap >= base_date else (snap, base_date)
    replacements = [dict(r) for r in con.execute(f"SELECT * FROM admin_units WHERE tier<=4 AND "
                                                 f"({between} OR basis='historical_1897') "
                                                 "AND (end_date IS NULL OR end_date>=?) AND (start_date IS NULL OR start_date<=?) "
                                                 "AND admin_id NOT LIKE ? ORDER BY admin_id",
                                                 (*bounds, snap, snap, f"{group.key.upper()}-%"))]
    candidate_ids = {a["admin_id"] for a in admins}
    admins = [a for a in replacements if a["admin_id"] not in candidate_ids and a["basis"] != 'historical_1897'] + admins + [
        a for a in replacements if a["admin_id"] not in candidate_ids and a["basis"] == 'historical_1897']
    geoms = [outline(a["geometry"]) for a in admins]
    tree = STRtree(geoms)
    # people per km² of each division: on the base date, else on the first of density_from that has it
    density = {}
    for d in (*reversed(group.density_from), base_date):
        density.update({r[0]: r[1] / max(r[2], 1) for r in con.execute(
            "SELECT admin_id,SUM(population_est),SUM(area_km2) FROM snapshot_full WHERE snapshot=? GROUP BY admin_id", (d,))})
    base_controls = {r["admin_id"]: dict(r) for r in con.execute(
        f"SELECT * FROM snapshot_full WHERE snapshot=? AND control_source IN ({','.join('?' * len(group.keep_whole))})",
        (base_date, *group.keep_whole))} if group.keep_whole else {}
    events = [dict(r) for r in con.execute("SELECT * FROM control_events WHERE start_date<=? AND end_date>=?", (snap, snap))]
    output, used_admins, unit_geoms = [], {}, {}
    for u in active:
        ug = outline(u["geometry"])
        if ug is None:
            continue
        uid = u["unit_id"]
        unit_geoms[uid] = ug
        u["unit_name_en"], u["unit_name_zh"] = namer(u["cshapes_name"], u["status"], year)
        if u["gwcode"] in s.names:
            u["unit_name_en"], u["unit_name_zh"] = state_names[u["gwcode"]]
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
            if inherited:
                ctrl = {k: inherited[k] for k in base}
            for part, control in control_parts(g, a, u, snap, ctrl, rules, state_names, rule_hits):
                area = eq_area_km2(part)
                if area < 0.01:
                    continue
                row = dict(unit_fields, admin_id=a["admin_id"], area_km2=area, geom=part, **control)
                row["bloc"] = bloc(control["controller_gwcode"], s)
                row["weight"] = area * density.get(a["admin_id"], 1)
                row["control_split"] = int(control != base)
                row["piece_id"] = f"{group.key.upper()}:{snap}:{uid}:{a['admin_id']}:{len(unit_rows)}"
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
            # land without provinces (islands, lakes, slivers between divisions all over the unit) in tiles of
            # TILE_DEG degrees, each a division of its own: a front cuts only the tiles it crosses
            x0, y0, x1, y1 = remaining.bounds
            for ix in range(math.floor(x0 / TILE_DEG), math.floor(x1 / TILE_DEG) + 1):
                for iy in range(math.floor(y0 / TILE_DEG), math.floor(y1 / TILE_DEG) + 1):
                    tile = polys(inter(remaining, box(ix * TILE_DEG, iy * TILE_DEG, (ix + 1) * TILE_DEG,
                                                      (iy + 1) * TILE_DEG)))
                    if tile is None or eq_area_km2(tile) < 0.01:
                        continue
                    aid = f"{group.key.upper()}-CSH-{uid}-{ix + 180 // TILE_DEG}_{iy + 90 // TILE_DEG}"  # >= 0
                    existing = con.execute("SELECT * FROM admin_units WHERE admin_id=?", (aid,)).fetchone()
                    add(dict(existing) if existing else new_admin(u, tile, snap, group, aid), tile)
        if not unit_rows:
            raise ValueError(f"Empty political unit: {uid}")
        if group.min_piece_km2:
            absorb(unit_rows, group.min_piece_km2)
        allocate_population(unit_rows, population_target(world, u, year))
        output.extend(unit_rows)
    # Small island territories absent from CShapes retain the original database's records.
    for r in con.execute("SELECT s.*,p.geometry AS piece_geometry,a.geometry AS admin_geometry FROM snapshot_full s "
                         "JOIN pieces p USING(piece_id) JOIN admin_units a USING(admin_id) WHERE s.snapshot=? AND s.unit_id<0", (base_date,)):
        row = dict(r)
        a = dict(con.execute("SELECT * FROM admin_units WHERE admin_id=?", (row["admin_id"],)).fetchone())
        if (a["start_date"] and a["start_date"] > snap) or (a["end_date"] and a["end_date"] < snap):
            continue
        used_admins[a["admin_id"]] = a
        row.update(snapshot=snap, piece_id=f"{group.key.upper()}:{snap}:{row['piece_id']}",
                   geom=outline(row["piece_geometry"] or row["admin_geometry"]))
        # the group's own rules (not the inherited ones) may name a territory by its unit name; the last one
        # that applies takes the whole territory
        for rule in rules:
            if rule["row"] > 0 and snap in rule["snapshots"].split("|") \
                    and matches(rule["unit_match"], row["unit_name_en"]) and matches(rule["admin_match"], row["admin_id"]) \
                    and (rule["mask"] is None or row["geom"].intersects(rule["mask"])):
                row.update(controller(int(rule["controller_gwcode"]), state_names, rule["control_type"], rule["source"],
                                      rule["confidence"], rule["controller_name"], rule["controller_name_zh"]))
                rule_hits.add((snap, rule["row"]))
        row["bloc"] = bloc(row["controller_gwcode"], s)
        output.append(row)
    piece_counts = Counter(r["admin_id"] for r in output)
    for r in output:
        r["control_split"] = int(piece_counts[r["admin_id"]] > 1)
    return output, used_admins, unit_geoms


def store_snapshot(con, rows, admins, s, pop_method, group, stored):
    """The date's rows in the database. A piece that is its whole division keeps no outline of its own (as in the
    sets' databases); one cut from it does, and is stored once for all the group's dates it is the same on
    (stored: (division, outline) -> piece key), and by the dates of the other groups too (piece_id SHARED:...)."""
    snap, zh, en = s.date, s.title_zh, s.title_en
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
                "(SELECT 1 FROM pop_methods WHERE pop_method=?)", (pop_method, pop_method))
    method = con.execute("SELECT pop_method_id FROM pop_methods WHERE pop_method=?", (pop_method,)).fetchone()[0]
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
        geometry = gj(r["geom"]) if own_outline(r, admins[r["admin_id"]]) else None
        piece = (r["admin_id"], geometry)
        if piece not in stored:  # shared by all the added dates (of every group) it is the same on
            digest = hashlib.md5((geometry or "").encode()).hexdigest()[:12]
            piece_id = f"{SHARED}:{r['admin_id']}" + (f"~{digest}" if geometry else "")
            found = con.execute("SELECT piece_key FROM pieces WHERE piece_id=?", (piece_id,)).fetchone()
            stored[piece] = found[0] if found else con.execute(
                "INSERT INTO pieces(piece_id,admin_key,area_km2,geometry) VALUES (?,?,?,?)",
                (piece_id, admin_keys[r["admin_id"]], r["area_km2"], geometry)).lastrowid
        con.execute("INSERT INTO piece_snapshot VALUES (?,?,?,?,?,?,?,?)", (snap, stored[piece], r["unit_id"],
                    controls[key], r["control_split"], r["area_km2"], r["population_est"], method))
    pops = Counter()
    for r in rows:
        pops[r["bloc"]] += r["population_est"]
    con.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)", (snap, zh, en, len(admins), sum(pops.values()),
                *[pops[b] for b in BLOCS]))


def static_hash(static):
    return hashlib.sha256(json.dumps(static, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def base_assets():
    """admin.bin and index.json as ww2_webmap.py wrote them. When this script has run on them before (index.json
    has dates ww2_webmap.py does not write), what it appended (divisions, pieces, look-up values, the dates) is
    taken off again, back to the lengths added-build.json recorded; the checksum there makes sure nothing else
    changed since."""
    static, index = json.loads(unpack(DATA / "admin.bin")), read_json(DATA / "index.json")
    if any(s["snapshot"] not in WEBMAP_DATES for s in index["snapshots"]):
        old = read_json(MARKER)
        n = static["n"] = old["admins"]
        for col in ("admin_id", "tier", "partial", "merged", "area", "label"):
            static[col] = static[col][:n]
        for key, col in static["cols"].items():
            col["idx"] = col["idx"][:n]
            col["lut"] = col["lut"][:old["luts"][key]]
        static["feature_admin"] = static["feature_admin"][:old["features"]]
        if static_hash(static) != old["sha256"]:
            raise ValueError("admin.bin changed since add_snapshots.py last ran; run ww2_webmap.py before add_snapshots.py")
        index["snapshots"] = [s for s in index["snapshots"] if s["snapshot"] in WEBMAP_DATES]
    marker = {"admins": static["n"], "features": len(static["feature_admin"]),
              "luts": {k: len(c["lut"]) for k, c in static["cols"].items()}, "sha256": static_hash(static)}
    return static, index, marker


def append_admin(static, a, prefix):
    """The index of a division in admin.bin (prefix: its set's, as ww2_webmap.py writes the ids), appended when
    it is not there yet."""
    aid = prefix + a["admin_id"]
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


def country_of(r, group):
    """Key of the controller's country in the control view: its code; with group.client_states, client states
    and Vichy France have keys of their own, as ww2_webmap.country_key gives them on the 1939-45 dates."""
    gw = r["controller_gwcode"]
    if not group.client_states:
        return gw
    det = str(r["controller_detail_en"] or "")
    if gw == 740 and det.startswith("Manchukuo"):
        return "MAN"
    if gw == 740 and det.startswith("Mengjiang"):
        return "MEN"
    if gw == 255 and "Italian Social Republic" in det:
        return "RSI"
    if gw == -1 and "Kingdom of Italy" in det:
        return "ITK"
    if gw == 220 and r["bloc"] == "neutral":
        return "VICHY"
    return str(int(gw))


_BASE_ADMINS = {}


def base_admins(base):
    """The divisions whose outlines a base date's geo file carries (its snapshot's admin_active)."""
    if base not in _BASE_ADMINS:
        _BASE_ADMINS[base] = set(read_json(DATA / f"snap-{base}.json")["admin_active"])
    return _BASE_ADMINS[base]


def export_snapshot(rows, admins, ug, group, s, static, unit_indices, new_unit):
    """The date's snap-<date>.json and its summary for index.json; writes its geo-<date>.bin."""
    snap, zh, en = s.date, s.title_zh, s.title_en
    d = pd.DataFrame(rows)
    features, admin_indices, admin_rec, piece_rec = [], {}, {}, {}
    for r in rows:
        a = admins[r["admin_id"]]
        if r["admin_id"] not in admin_indices:
            ai = admin_indices[r["admin_id"]] = append_admin(static, a, PREFIX[group.set])
            admin_rec[ai] = encode([shape(json.loads(a["geometry"]))], TOL_PROV)
        fi = len(static["feature_admin"])
        static["feature_admin"].append(admin_indices[r["admin_id"]])
        features.append(fi)
        if own_outline(r, a):  # cut from its division, or land without provinces: an outline of its own
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
    for uid, part in sorted(d.groupby("unit_id"), key=lambda kv: -kv[1].population_est.sum()):
        first = part.iloc[0].to_dict()
        nation_indices[uid] = len(nations)
        nations.append([int(uid), first["unit_name_zh"] or first["unit_name_en"], first["unit_name_en"], nation_of(first),
                        first["unit_status"], first["sovereign_name_zh"], int(part.population_est.sum()), round(part.area_km2.sum())])
        if uid in ug:
            big = max(getattr(ug[uid], "geoms", [ug[uid]]), key=lambda g: g.area)
            a = label_anchor(big)
            if a:
                unit_labels.append([unit_indices[uid], first["unit_name_zh"] or first["unit_name_en"]] + a + [round(eq_area_km2(big))])
    countries, country_indices, country_labels, ctrl_geoms = [], {}, [], []
    d["country"] = [country_of(r, group) for r in rows]
    for ckey, part in sorted(d.groupby("country"), key=lambda kv: -kv[1].population_est.sum()):
        gw = int(part.controller_gwcode.iloc[0])
        key = ckey if isinstance(ckey, str) else str(int(ckey))
        home = part[part.unit_gwcode == gw]
        first = (home if len(home) else part).sort_values("area_km2").iloc[-1]
        ci = len(countries)
        country_indices[ckey] = ci
        geom = dissolve(part.geom.tolist()) or polys(union(part.geom.tolist()))
        comp = part.groupby("unit_name_zh", dropna=False).agg(pop=("population_est", "sum"), km2=("area_km2", "sum"))
        name_zh, name_en = SPECIAL[key] if key in SPECIAL and not key.lstrip("-").isdigit() else \
            (first.controller_name_zh or first.controller_name_en, first.controller_name_en)
        countries.append([key, name_zh, name_en, color_of(key), BLOCS.index(first.bloc), int(part.population_est.sum()),
                          round(part.area_km2.sum()), int(part.admin_id.nunique()), len(ctrl_geoms),
                          [[n if isinstance(n, str) else "—", int(r["pop"]), round(r.km2)]
                           for n, r in comp.sort_values("km2", ascending=False).head(12).iterrows()]])
        ctrl_geoms.append(geom)
        if gw != -20:
            country_labels.extend([ci] + a for a in anchors(geom))
    doc = dict(snapshot=snap, title_zh=zh, title_en=en, feature=features,
               unit=[unit_indices[r["unit_id"]] if r["unit_id"] in ug else -1 for r in rows], country=[country_indices[k] for k in d.country],
               nation=[nation_indices[r["unit_id"]] for r in rows], nations=nations, bloc=[BLOCS.index(r["bloc"]) for r in rows],
               conf=[CONF.index(r["control_confidence"]) for r in rows], ctrl_gw=[r["controller_gwcode"] for r in rows],
               split=[r["control_split"] for r in rows], area=[round(r["area_km2"], 1) for r in rows],
               pop=[r["population_est"] for r in rows], luts=luts, rows=lut_rows,
               units_active=[unit_indices[u] for u in unit_list],
               admin_active=sorted(admin_indices.values()), unit_labels=unit_labels, geo_feature=sorted(piece_rec),
               # outlines of divisions the base date's file already carries are not repeated: the page loads the base
               # date first (admin_base) and reads from this file only the outlines listed in admin_geo
               admin_base=group.base, admin_geo=sorted(set(admin_indices.values()) - base_admins(group.base)),
               countries=countries,
               country_labels=country_labels,
               cities=cities.ww2(snap, use_curated_coordinates=True, table=group.cities, code=s.city_code),
               bloc_names=s.bloc_names or group.bloc_names,
               notes=dict(bloc_title=s.bloc_title or group.bloc_title, bloc=s.bloc_note,
                          control=s.control_note or group.control_note),
               bloc_pop={b: sum(r["population_est"] for r in rows if r["bloc"] == b) for b in BLOCS},
               tier_count={str(t): n for t, n in sorted(Counter(a["tier"] for a in admins.values()).items())})
    summary = dict(snapshot=snap, title_zh=zh, title_en=en, pieces=len(rows), admin_units=len(admins), countries=len(countries),
                   population=sum(doc["pop"]), bloc_pop=doc["bloc_pop"], tier_count=doc["tier_count"])
    # in the order the page reads them: divisions, cut pieces, units, control areas (see ww2_webmap.py)
    packed(DATA / f"geo-{snap}.bin", b"".join([admin_rec[a] for a in doc["admin_geo"]]
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


def inherited_rules(con, group):
    """Control of the base date carried over to the group's dates piece by piece (group.inherit): each piece
    with one of those sources becomes a rule whose mask is the piece."""
    if not group.inherit:
        return []
    out = []
    for r in con.execute("SELECT s.*,p.geometry AS pg,a.geometry AS ag FROM snapshot_full s JOIN pieces p USING(piece_id) "
                         f"JOIN admin_units a USING(admin_id) WHERE s.snapshot=? AND s.control_source IN "
                         f"({','.join('?' * len(group.inherit))})", (group.base, *group.inherit)):
        out.append(dict(snapshots="|".join(sorted(s.date for s in group.snapshots)), unit_match="*", admin_match="*",
                        row=-len(out)-1, controller_gwcode=r["controller_gwcode"],
                        controller_name=r["controller_detail_en"] or r["controller_name_en"],
                        controller_name_zh=r["controller_detail_zh"] or r["controller_name_zh"],
                        control_type=r["control_type"], confidence=r["control_confidence"],
                        source=f"baseline:{group.base}:{r['control_source']}", mask=outline(r["pg"] or r["ag"])))
    for rule in out:
        prepare(rule["mask"])
        rule["bounds"] = rule["mask"].bounds
    return out


def add_group(con, world, group, static, index, unit_indices, new_unit, documents):
    """Build the group's dates into its set's database (an open transaction) and into the map data."""
    key, dates = group.key, [s.date for s in group.snapshots]
    rules = load_rules(con, world, group)
    rule_hits = set()
    for snap in dates:
        con.execute("DELETE FROM piece_snapshot WHERE snapshot=?", (snap,))
        con.execute("DELETE FROM unit_snapshot WHERE snapshot=?", (snap,))
        con.execute("DELETE FROM snapshots WHERE snapshot=?", (snap,))
    inherited = inherited_rules(con, group)
    stored = {}
    for s in group.snapshots:
        rows, admins, ug = build_snapshot(con, world, group, s, inherited + rules, rule_hits)
        store_snapshot(con, rows, admins, s, group.pop_method, group, stored)
        doc, summary = export_snapshot(rows, admins, ug, group, s, static, unit_indices, new_unit)
        documents[s.date] = doc
        index["snapshots"].append(summary)
        print(s.date, len(rows), "pieces;", len(admins), "historical divisions;", len(doc["countries"]), "controllers",
              flush=True)
    missing = [(snap, r["row"]) for r in rules for snap in r["snapshots"].split("|") if (snap, r["row"]) not in rule_hits]
    if missing:
        raise ValueError(f"Unmatched control rules in {group.rules} (date, row): {missing}")
    con.execute("DELETE FROM control_rules WHERE field LIKE ?", (f"{key}:%",))
    next_row = con.execute("SELECT COALESCE(MAX(row),1)+1 FROM control_rules").fetchone()[0]
    for offset, rule in enumerate(rules):
        con.execute("INSERT INTO control_rules VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (next_row+offset, rule["snapshots"], "*", f"{key}:{rule['row']}",
                     f"unit={rule['unit_match']};admin={rule['admin_match']};reference={rule['reference']}",
                     rule["controller_name"], rule["controller_name_zh"], int(rule["controller_gwcode"]),
                     rule["control_type"], rule["confidence"], rule["note"] + " Source: " + rule["source_url"]))
    mk = group.meta_key or key
    con.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)",
                    [(f"{mk}_method", group.pop_method),
                     (f"{mk}_control", f"curated/{group.rules}; approximate reference masks flagged in controls")])
    for i, url in enumerate(sorted({r["source_url"] for r in rules}), 1):
        con.execute("INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?)", (f"{key}-control-{i}", f"{group.label or key} control reference",
                     f"Historical facts underlying curated/{group.rules}; see each rule's note", url,
                     "Reference text: respective publisher; curated rules: CC0",
                     f"{group.period} event-day control facts; no source text or source map reproduced".strip()))


def main():
    dates = [s.date for g in GROUPS for s in g.snapshots]
    if len(set(dates)) != len(dates) or DATES & WEBMAP_DATES:
        raise ValueError("A date is in two groups of added_dates.py, or is built by a set already")
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
    world = sqlite3.connect(f"file:{DB_DIR / 'world_history_1900_2000.sqlite'}?mode=ro", uri=True)
    world.row_factory = sqlite3.Row
    documents = {}
    for set_name in dict.fromkeys(g.set for g in GROUPS):  # each database once, in the order of the groups
        con = sqlite3.connect(DATABASES[set_name])
        con.row_factory = sqlite3.Row
        with con:
            for group in GROUPS:
                if group.set == set_name:
                    add_group(con, world, group, static, index, unit_indices, new_unit, documents)
            # pieces no date uses any more (of an earlier build, or with the group prefix of older builds)
            prefixes = [SHARED] + [g.key.upper() for g in GROUPS]
            con.execute("DELETE FROM pieces WHERE (" + " OR ".join("piece_id LIKE ?" for _ in prefixes) + ") "
                        "AND piece_key NOT IN (SELECT piece_key FROM piece_snapshot)", [p + ":%" for p in prefixes])
            con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", ("snapshots", ";".join(
                r[0] for r in con.execute("SELECT snapshot FROM snapshots ORDER BY snapshot"))))
            cov, cov_units = coverage(con)
        con.execute("VACUUM")
        con.close()
        cov.to_csv(WW2_OUT / f"coverage{COVERAGE_SUFFIX[set_name]}.csv", index=False)
        cov_units.to_csv(WW2_OUT / f"coverage_by_unit{COVERAGE_SUFFIX[set_name]}.csv", index=False)
        print("Updated", DATABASES[set_name])
    world.close()
    for snap, doc in documents.items():
        write_json(DATA / f"snap-{snap}.json", doc)
    index["snapshots"].sort(key=lambda s: s["snapshot"])
    packed(DATA / "admin.bin", json.dumps(static, ensure_ascii=False, separators=(",", ":")).encode())
    write_json(DATA / "index.json", index)
    write_json(MARKER, marker)
    print("Updated", DATA)


if __name__ == "__main__":
    main()
