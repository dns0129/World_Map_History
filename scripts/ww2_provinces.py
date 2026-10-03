"""Province-level partition of the six 1939-1945 snapshots.

ww2_histunits.py lays down the finest historical division known for each place
(county, district, province, region, whole country). This step dissolves every
county-level (tier 1) and district-level (tier 2) unit into the province-level
unit above it, so that only province-level divisions remain:

  * the province of a county or district is its nearest ancestor of tier 3, read
    from the parent / grandparent recorded by ww2_histunits (a tier-4 region when
    no province lies in between); source-specific rules cover the layers whose
    provinces are known from the source itself (Korean provinces in the unit id,
    US states, Burma 1931 divisions, French Indochina, Dutch East Indies);
  * a county or district with no ancestor is itself a first-level division (Irish
    counties, Italian provinces of 1940, Hungarian varmegye, Romanian judete) and
    stays as a province; very small ones (city districts, towns) join the
    neighbouring unit of the same political unit;
  * the province outline is the union of the outlines it absorbs. The remaining part
    of a tier-3 unit that finer units had cut away is merged back with them.

Borders still cut provinces: wherever a province lies in two political units
(CShapes, that date) or the de facto controller changes inside it (front lines,
annexations, occupation zones), it is split into pieces along the finer units the
controller was decided on, so the border keeps that resolution.

Input: work/ww2/hist_units.* and snapshot_<date>.csv / split_<date>.geojson, or,
when those are missing, a county-level release of the database (--county-db PATH;
the 2026-10-03 release is in git history as db/ww2_divisions_1939_1945.sqlite).
Output in work/ww2/: prov_units.csv / prov_units.geojson, prov_snapshot_<date>.csv
and prov_split_<date>.geojson (same columns as the county-level files).
"""
import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import shapely
import shapely.ops
from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon, mapping, shape

from common import ROOT
from ww2_common import SNAPSHOTS, WW2_RAW, WW2_WORK
from ww2_geo import eq_area_km2, polys, union

DATES = [s[0] for s in SNAPSHOTS]
TIER_ZH = {3: "省级", 4: "大区级", 5: "整个政治单元", 6: "岛屿属地"}
TIER_EN = {3: "province", 4: "region", 5: "whole unit", 6: "territory"}
CLUSTER_DEG = 1.5        # units naming the same province farther apart than this are different provinces
CLOSE_DEG = 0.002        # closes the hairline gaps left between independently simplified outlines
ORPHAN_KM2 = 300         # first-level units smaller than this (towns, city districts) join a neighbour
ORPHAN_SHARE = 0.10      # ... as do a political unit's only subdivisions when they cover less than this share
REMNANT_KM2 = 5000       # leftover land of a country beside its provinces joins the nearest province ...
REMNANT_SHARE = 0.03     # ... when it is this small, absolutely and as a share of the political unit
REMNANT_DEG = 2.0        # ... and lies this close to it
PIECE_MIN_KM2 = 5        # control pieces smaller than this inside a province join its largest piece
TIER2_NAME = re.compile(r"^(Regierungsbezirk|Bezirk |Kreishauptmannschaft|Landeskommiss|Oberlandrat)")

# Names of one province spelled differently by two sources
ALIAS = {"Tonkin": "Protectorat du Tonkin", "Annam": "Protectorat d'Annam", "Cochinchina": "Colonie de Cochinchine"}
# Chinese names of provinces that only exist here as the union of their subdivisions
ZH = {
    "Protectorat du Tonkin": "东京（法国保护国）", "Protectorat d'Annam": "安南（法国保护国）",
    "Colonie de Cochinchine": "交趾支那（法国殖民地）", "Cambodia": "柬埔寨", "Laos": "老挝",
    "West-Java": "西爪哇省", "Midden-Java": "中爪哇省", "Oost-Java": "东爪哇省", "Gouvernement Borneo": "婆罗洲省",
    "Gouvernement der Molukken": "摩鹿加省", "Gouvernement Groote Oost": "大东省", "Soerakarta": "梭罗（苏拉卡尔塔）",
    "Jogjakarta": "日惹",
    "Arakan Division": "若开专区", "Pegu Division": "勃固专区", "Irrawaddy Division": "伊洛瓦底专区",
    "Tenasserim Division": "丹那沙林专区", "Magwe Division": "马圭专区", "Mandalay Division": "曼德勒专区",
    "Sagaing Division": "实皆专区", "Federated Shan States": "掸邦联邦", "Karenni States": "克伦尼诸邦",
    "Alabama": "亚拉巴马州", "Alaska Territory": "阿拉斯加领地", "Arizona": "亚利桑那州", "Arkansas": "阿肯色州",
    "California": "加利福尼亚州", "Colorado": "科罗拉多州", "Connecticut": "康涅狄格州", "Delaware": "特拉华州",
    "District of Columbia": "哥伦比亚特区", "Florida": "佛罗里达州", "Georgia": "佐治亚州", "Hawaii Territory": "夏威夷领地",
    "Idaho": "爱达荷州", "Illinois": "伊利诺伊州", "Indiana": "印第安纳州", "Iowa": "艾奥瓦州", "Kansas": "堪萨斯州",
    "Kentucky": "肯塔基州", "Louisiana": "路易斯安那州", "Maine": "缅因州", "Maryland": "马里兰州",
    "Massachusetts": "马萨诸塞州", "Michigan": "密歇根州", "Minnesota": "明尼苏达州", "Mississippi": "密西西比州",
    "Missouri": "密苏里州", "Montana": "蒙大拿州", "Nebraska": "内布拉斯加州", "Nevada": "内华达州",
    "New Hampshire": "新罕布什尔州", "New Jersey": "新泽西州", "New Mexico": "新墨西哥州", "New York": "纽约州",
    "North Carolina": "北卡罗来纳州", "North Dakota": "北达科他州", "Ohio": "俄亥俄州", "Oklahoma": "俄克拉何马州",
    "Oregon": "俄勒冈州", "Pennsylvania": "宾夕法尼亚州", "Rhode Island": "罗得岛州", "South Carolina": "南卡罗来纳州",
    "South Dakota": "南达科他州", "Tennessee": "田纳西州", "Texas": "得克萨斯州", "Utah": "犹他州", "Vermont": "佛蒙特州",
    "Virginia": "弗吉尼亚州", "Washington": "华盛顿州", "West Virginia": "西弗吉尼亚州", "Wisconsin": "威斯康星州",
    "Wyoming": "怀俄明州",
}
# Layers that divide their whole country into provinces: a stray OpenHistoricalMap unit with no
# ancestor inside such a country is one of their counties, not a province of its own
COMPLETE = {"AHCB", "KR1914", "TW1930", "MM1931"}
KIND = {"AHCB": "state / territory", "KR1914": "道", "TW1930": "州/庁", "MM1931": "division / states",
        "FIC": "protectorate / colony", "DEI": "gouvernement"}

UNIT_COLS = ["unit_id", "name", "name_zh", "name_en", "tier", "tier_zh", "tier_en", "kind", "basis", "source", "note",
             "start", "end", "partial", "parent", "parent_zh", "grandparent", "ohm_level", "wikidata", "cshapes_fid",
             "merged_units", "snapshots", "area_km2", "label_lon", "label_lat"]

SNAP_COLS = ["snapshot", "piece_id", "admin_id", "unit_id", "unit_gwcode", "unit_name_en", "unit_name_zh", "unit_status",
             "sovereign_gwcode", "sovereign_name_en", "sovereign_name_zh", "controller_gwcode", "controller_name_en",
             "controller_name_zh", "controller_detail_en", "controller_detail_zh", "control_type", "control_source",
             "control_confidence", "bloc", "control_split", "partial_control_events", "area_km2", "pop_method",
             "population_est"]


def nn(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else x


def base_id(uid):
    return uid.split("#")[0]


def src_of(uid):
    return re.match(r"^([A-Z]+[0-9]*)", uid).group(1)


# ---------------------------------------------------------------- input

def load_work():
    hist = pd.read_csv(WW2_WORK / "hist_units.csv", low_memory=False)
    ugeom = {f["properties"]["unit_id"]: shape(f["geometry"])
             for f in json.load(open(WW2_WORK / "hist_units.geojson"))["features"]}
    snaps, pgeom = {}, {}
    for d in DATES:
        snaps[d] = pd.read_csv(WW2_WORK / f"snapshot_{d}.csv", low_memory=False)
        for f in json.load(open(WW2_WORK / f"split_{d}.geojson"))["features"]:
            pgeom[f["properties"]["piece_id"]] = shape(f["geometry"])
    return hist, ugeom, snaps, pgeom


def _shape(gj):
    g = shape(json.loads(gj))
    if g.geom_type == "GeometryCollection":
        g = MultiPolygon([q for x in g.geoms for q in getattr(x, "geoms", [x]) if q.geom_type == "Polygon"])
    try:
        return polys(g)
    except shapely.errors.GEOSException:
        return polys(shapely.make_valid(g, method="structure"))


def load_db(path):
    con = sqlite3.connect(path)
    hist = pd.read_sql("SELECT admin_id AS unit_id, name, name_zh, name_en, tier, kind, basis, source, note, "
                       "start_date AS start, end_date AS end, partial, parent, parent_zh, grandparent, ohm_level, "
                       "wikidata, snapshots, area_km2, label_lon, label_lat, geometry FROM admin_units", con)
    ugeom = {u: _shape(g) for u, g in zip(hist.unit_id, hist.geometry)}
    hist = hist.drop(columns="geometry")
    hist["cshapes_fid"] = None
    pgeom = {p: _shape(g) for p, g in
             con.execute("SELECT piece_id, geometry FROM pieces WHERE geometry IS NOT NULL")}
    full = pd.read_sql("SELECT * FROM snapshot_full", con)
    con.close()
    return hist, ugeom, {d: full[full.snapshot == d].reset_index(drop=True) for d in DATES}, pgeom


def burma_groups():
    """Burma 1931 district -> division (the source's group field)."""
    p = WW2_RAW / "lawson" / "burma-1931-admin-units.geojson"
    if not p.exists():
        return {}
    out = {}
    for k, f in enumerate(json.load(open(p))["features"]):
        q = f["properties"]
        name = q.get("name") or f"{q.get('group') or 'Burma'} (unit {k})"
        if q.get("group"):
            out[f"MM1931-{k:03d}"] = q["group"]
            out[name] = q["group"]
    return out


# ---------------------------------------------------------------- which province

class Resolver:
    def __init__(self, hist):
        self.tiers = defaultdict(set)
        for n, t in zip(hist.name, hist.tier):
            if t >= 2:
                self.tiers[n].add(int(t))
        self.korea = pd.read_csv(ROOT / "curated" / "east_asia" / "korea.csv").set_index("key")
        ALIAS.update({ko.split(" (")[0]: en for ko, en in zip(self.korea.ko, self.korea.en)})
        self.us = set(hist[hist.unit_id.str.startswith("AHCB")].parent.dropna())
        self.burma = burma_groups()

    def tier_of(self, name, row=None, which="parent"):
        if row is not None and which + "_tier" in row and nn(row[which + "_tier"]) is not None:
            return int(row[which + "_tier"])  # recorded by ww2_histunits (builds after this release)
        t = self.tiers.get(name, set())
        if 3 in t:
            return 3
        if 2 in t or TIER2_NAME.match(name):
            return 2
        if 4 in t:
            return 4
        return None

    def __call__(self, h):
        """(province name, province zh) of a tier-1/2 unit, or (None, None) when it has no ancestor."""
        uid, tier = h["unit_id"], int(h["tier"])
        p, pzh, g = nn(h["parent"]), nn(h["parent_zh"]), nn(h["grandparent"])
        if p == h["name"] and tier == 2:
            p, pzh = g, None  # matched itself in another source
        src = src_of(uid)
        if src == "KR1914":
            key = uid.split("-")[1]
            return self.korea.en[key], self.korea.zh[key]
        if src == "AHCB":
            for x in (p, g):
                if x in self.us:
                    return x, None
        if src == "MM1931":
            grp = self.burma.get(base_id(uid)) or self.burma.get(h["name"])
            if grp:
                return grp, None
        if p is None:
            return None, None
        tp = self.tier_of(p, h, "parent")
        if tp == 2 and g is not None:
            return g, None
        if tp is None and g is not None:
            tg = self.tier_of(g, h, "grandparent")
            if tg == 3:
                return g, None  # the parent sits between the unit and a province: a district
        return p, pzh


# ---------------------------------------------------------------- geometry

def close(g, eps=CLOSE_DEG):
    """Union whose hairline gaps (left by simplifying neighbours independently) are closed."""
    if g is None or g.is_empty:
        return g
    c = g.buffer(eps, join_style="mitre", mitre_limit=3).buffer(-eps, join_style="mitre", mitre_limit=3)
    c = polys(c)
    if c is None:
        return g
    out = []
    for p in getattr(c, "geoms", [c]):
        holes = [r for r in p.interiors if Polygon(r).area > 5e-5]  # drop sliver holes under ~0.5 km2
        out.append(Polygon(p.exterior, holes))
    return out[0] if len(out) == 1 else MultiPolygon(out)


def merged(gs):
    gs = [g for g in gs if g is not None and not g.is_empty]
    if len(gs) == 1:
        return gs[0]
    return close(polys(union(gs)))


def label_point(g):
    big = max(getattr(g, "geoms", [g]), key=lambda p: p.area)
    try:
        return shapely.ops.polylabel(big, tolerance=0.02)
    except Exception:
        return big.representative_point()


# ---------------------------------------------------------------- one snapshot

def groups_for(date, hist, ugeom, rows, resolve):
    """Province groups of one date: list of dict(anchor, members, name, name_zh, self)."""
    act = hist[hist.unit_id.isin(set(rows.admin_id))].to_dict("records")
    unit_of = rows.sort_values("area_km2").drop_duplicates("admin_id", keep="last").set_index("admin_id").unit_id
    groups = []
    items = defaultdict(list)  # canonical province name -> [(group index, None) | (None, (unit, zh, is_self))]
    for h in act:
        if h["tier"] >= 3:
            gi = len(groups)
            groups.append(dict(anchor=h, members=[h["unit_id"]], name=h["name"], name_zh=nn(h["name_zh"]), self=False))
            if h["tier"] <= 4:
                items[ALIAS.get(h["name"], h["name"])].append((gi, None))
            continue
        name, zh = resolve(h)
        if name is None:
            name, zh, self_ = h["name"], nn(h["name_zh"]), True
        else:
            self_ = False
        items[ALIAS.get(name, name)].append((None, (h, zh, self_)))
    dead = set()
    for name, its in items.items():
        if len(its) == 1 and its[0][0] is not None:
            continue
        geo = [ugeom[groups[gi]["anchor"]["unit_id"]] if gi is not None else ugeom[k[0]["unit_id"]] for gi, k in its]
        pu = [unit_of[groups[gi]["anchor"]["unit_id"]] if gi is not None else None for gi, _ in its]
        # single linkage over everything that names this province, nearest pairs first; two units of
        # that name in different political units (Limburg, Amazonas) are never joined
        tree = STRtree([g.envelope for g in geo])
        pairs = []
        for i, g in enumerate(geo):
            for j in tree.query(g.envelope.buffer(CLUSTER_DEG)):
                j = int(j)
                if j > i:
                    dist = g.distance(geo[j])
                    if dist <= CLUSTER_DEG:
                        pairs.append((dist, i, j))
        par = list(range(len(its)))
        pus = [{p} if p is not None else set() for p in pu]

        def find(i):
            while par[i] != i:
                par[i] = par[par[i]]
                i = par[i]
            return i
        for _, i, j in sorted(pairs):
            a, b = find(i), find(j)
            if a == b or (pus[a] and pus[b] and not pus[a] & pus[b]):
                continue
            par[b] = a
            pus[a] |= pus[b]
        cl = defaultdict(list)
        for i in range(len(its)):
            cl[find(i)].append(its[i])
        for members in cl.values():
            anchors = [gi for gi, _ in members if gi is not None]
            kids = [k for gi, k in members if gi is None]
            if anchors:
                main = max(anchors, key=lambda gi: (groups[gi]["name"] == name, ugeom[groups[gi]["anchor"]["unit_id"]].area))
                for gi in anchors:
                    if gi != main:
                        groups[main]["members"] += groups[gi]["members"]
                        dead.add(gi)
                groups[main]["members"] += [h["unit_id"] for h, _, _ in kids]
                continue
            zhs = Counter(z for _, z, _ in kids if z)
            only_self = len(kids) == 1 and kids[0][2]
            groups.append(dict(anchor=kids[0][0] if only_self else None, members=[h["unit_id"] for h, _, _ in kids],
                               name=name, name_zh=ZH.get(name) or (zhs.most_common(1)[0][0] if zhs else None),
                               self=only_self, src=Counter(src_of(h["unit_id"]) for h, _, _ in kids).most_common(1)[0][0]))
    return [g for i, g in enumerate(groups) if i not in dead]


def absorb_orphans(groups, ugeom, rows, hist_tier):
    """First-level units that are really towns or city districts, and slivers of a country left over
    beside its provinces, join the neighbouring unit of the same political unit."""
    area = rows.groupby("admin_id").area_km2.sum()
    unit_of = rows.sort_values("area_km2").drop_duplicates("admin_id", keep="last").set_index("admin_id").unit_id
    gunit = [Counter(unit_of[m] for m in g["members"]).most_common(1)[0][0] for g in groups]
    garea = [float(sum(area[m] for m in g["members"])) for g in groups]
    gtier = [hist_tier[g["members"][0]] if g["anchor"] is not None else 3 for g in groups]
    gsrc = [Counter(src_of(m) for m in g["members"]).most_common(1)[0][0] for g in groups]
    unit_total = defaultdict(float)
    unit_sub = defaultdict(float)
    for i, g in enumerate(groups):
        unit_total[gunit[i]] += garea[i]
        if gtier[i] <= 4:
            unit_sub[gunit[i]] += garea[i]
    geoms = [merged([ugeom[m] for m in g["members"]]) for g in groups]
    tree = STRtree(geoms)
    alive = [True] * len(groups)
    for i in sorted(range(len(groups)), key=lambda i: garea[i]):
        g = groups[i]
        sparse = unit_sub[gunit[i]] < ORPHAN_SHARE * unit_total[gunit[i]]
        b = geoms[i].buffer(0.02)
        if g["self"]:
            near = [int(j) for j in tree.query(b) if int(j) != i and alive[int(j)] and gunit[int(j)] == gunit[i]]
            top = max(near, key=lambda j: b.intersection(geoms[j]).area, default=None)
            stray = top is not None and gsrc[top] in COMPLETE and gsrc[i] == "OHM"
            if garea[i] >= ORPHAN_KM2 and not sparse and not stray:
                continue
        elif gtier[i] == 5:
            if garea[i] >= REMNANT_KM2 or garea[i] >= REMNANT_SHARE * unit_total[gunit[i]]:
                continue
        else:
            continue
        touch = [int(j) for j in tree.query(b) if int(j) != i and alive[int(j)]]
        near = [j for j in touch if gunit[j] == gunit[i]] or (touch if garea[i] < ORPHAN_KM2 else [])
        if near:
            j = max(near, key=lambda j: (gtier[j] == 5 and sparse, b.intersection(geoms[j]).area))
        else:
            near = [int(j) for j in tree.query(geoms[i].buffer(REMNANT_DEG)) if int(j) != i and alive[int(j)]
                    and gunit[int(j)] == gunit[i]]
            if not near:
                continue
            j = min(near, key=lambda j: geoms[i].distance(geoms[j]))
        groups[j]["members"] += g["members"]
        geoms[j] = merged([geoms[j], geoms[i]])
        garea[j] += garea[i]
        alive[i] = False
    return [g for g, a in zip(groups, alive) if a]


def pieces_for(g, rows, ugeom, pgeom):
    """Cut one province where the political unit or the controller changes."""
    sub = rows[rows.admin_id.isin(g["members"])]
    key = ["unit_id", "controller_gwcode", "controller_detail_en", "control_type", "bloc"]
    parts = []
    for _, d in sub.fillna({"controller_detail_en": ""}).groupby(key, sort=False, dropna=False):
        parts.append(d)
    parts.sort(key=lambda d: -d.area_km2.sum())
    if len(parts) > 1:
        big, small = [parts[0]], []
        for d in parts[1:]:
            (small if d.area_km2.sum() < PIECE_MIN_KM2 else big).append(d)
        if small:
            big[0] = pd.concat([big[0]] + small)
        parts = big
    out = []
    for d in parts:
        top = d.sort_values("area_km2").iloc[-1].to_dict()
        conf = d.groupby("control_confidence").area_km2.sum().idxmax()
        src = d.groupby("control_source").area_km2.sum().idxmax()
        meth = d.groupby("pop_method").population_est.sum().idxmax() if d.population_est.sum() > 0 else top["pop_method"]
        ev = sorted({e for x in d.partial_control_events.dropna() for e in str(x).split(";") if e})
        top.update(control_confidence=conf, control_source=src, pop_method=meth, area_km2=round(float(d.area_km2.sum()), 2),
                   population_est=int(d.population_est.sum()), partial_control_events=";".join(ev) or None)
        if top["controller_detail_en"] == "":
            top["controller_detail_en"] = None
        geom = None
        if len(parts) > 1:
            geom = merged([pgeom.get(p) or ugeom[a] for p, a in zip(d.piece_id, d.admin_id)])
        out.append((top, geom))
    return out


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--county-db", help="county-level database to read when work/ww2 has no county-level files")
    args = ap.parse_args()
    if (WW2_WORK / "hist_units.csv").exists() and not args.county_db:
        hist, ugeom, snaps, pgeom = load_work()
    else:
        path = args.county_db or (WW2_WORK / "county_level_1939_1945.sqlite")
        hist, ugeom, snaps, pgeom = load_db(path)
    hist = hist.copy()
    hist["tier"] = hist.tier.astype(int)
    hrow = {r["unit_id"]: r for r in hist.to_dict("records")}
    hist_tier = dict(zip(hist.unit_id, hist.tier))
    resolve = Resolver(hist)

    final = {}       # (prov_id, geom hash) -> unit record
    piece_rows = []  # (date, prov key, row, geom)
    for date in DATES:
        rows = snaps[date]
        groups = groups_for(date, hist, ugeom, rows, resolve)
        groups = absorb_orphans(groups, ugeom, rows, hist_tier)
        ids = Counter()
        for g in sorted(groups, key=lambda g: (g["name"], ugeom[g["members"][0]].centroid.x)):
            a = g["anchor"]
            if a is not None:
                pid = base_id(a["unit_id"])
            else:
                slug = re.sub(r"[^a-z0-9]+", "-", (g["name"] or "").lower()).strip("-") or \
                    hashlib.md5(g["name"].encode()).hexdigest()[:8]
                pid = f"PROV-{slug}"
            ids[pid] += 1
            if ids[pid] > 1:
                pid += f"-{ids[pid]}"
            kids = [m for m in g["members"] if a is None or m != a["unit_id"]]
            geom = merged([ugeom[m] for m in g["members"]]) if kids else ugeom[g["members"][0]]
            if a is not None:
                rec = {c: nn(a.get(c)) for c in UNIT_COLS if c in a}
                if pid.startswith("PH1939"):
                    rec["name"] = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", rec["name"])
                if kids:
                    rec.update(partial=0)
            else:
                first = hrow[g["members"][0]]
                rec = dict(name=g["name"], name_zh=g["name_zh"], name_en=g["name"] if g.get("src") == "AHCB" else None,
                           tier=3, kind=KIND.get(g.get("src")) or nn(first.get("kind")), start=None, end=None, partial=0,
                           parent=None, parent_zh=None, grandparent=None, ohm_level=None, wikidata=None, cshapes_fid=None,
                           note=None)
            if kids and rec["tier"] >= 5:
                rec.update(merged_units=len(kids))  # a whole country or territory that took in a few towns
            elif kids:
                srcs = Counter(hrow[m]["source"] for m in g["members"])
                rec.update(basis="merged_subunits", merged_units=len(kids),
                           source=f"Union of {len(kids)} subdivisions in force on the date; outlines from: "
                                  + "; ".join(s for s, _ in srcs.most_common(3)))
            else:
                rec.update(merged_units=0)
            if rec["tier"] in (1, 2):
                rec["tier"] = 3
            h = hashlib.md5(shapely.to_wkb(geom)).hexdigest()[:8]
            k = (pid, h)
            if k in final:
                final[k]["dates"].append(date)
            else:
                final[k] = dict(rec, uid=pid, geom=geom, dates=[date])
            for top, pg in pieces_for(g, rows, ugeom, pgeom):
                piece_rows.append((date, k, top, pg))
        n = Counter(int(final[k]["tier"]) for k in {pr[1] for pr in piece_rows if pr[0] == date})
        print(date, "provinces:", sum(n.values()), dict(sorted(n.items())), flush=True)

    # one id per distinct unit; versions that differ between dates get a suffix
    versions = defaultdict(list)
    for k, u in final.items():
        versions[u["uid"]].append(k)
    uid_of = {}
    for uid, ks in versions.items():
        for i, k in enumerate(sorted(ks, key=lambda k: DATES.index(final[k]["dates"][0]))):
            uid_of[k] = uid if len(ks) == 1 else f"{uid}#{i + 1}"
    out_units = []
    for k, u in final.items():
        lp = label_point(u["geom"])
        t = int(u["tier"])
        out_units.append(dict({c: u.get(c) for c in UNIT_COLS}, unit_id=uid_of[k], tier=t, tier_zh=TIER_ZH[t],
                              tier_en=TIER_EN[t], snapshots="|".join(u["dates"]),
                              area_km2=round(eq_area_km2(u["geom"]), 2), label_lon=round(lp.x, 4),
                              label_lat=round(lp.y, 4), geom=u["geom"]))
    df = pd.DataFrame([{c: r.get(c) for c in UNIT_COLS} for r in out_units])
    df.to_csv(WW2_WORK / "prov_units.csv", index=False)
    with open(WW2_WORK / "prov_units.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"unit_id": r["unit_id"]}, "geometry": mapping(r["geom"])}
            for r in out_units]}, f)

    by_date = defaultdict(list)
    for date, k, top, pg in piece_rows:
        by_date[date].append((uid_of[k], top, pg))
    for date in DATES:
        rows, geoms = [], {}
        count = Counter(u for u, _, _ in by_date[date])
        seen = Counter()
        for u, top, pg in by_date[date]:
            pid = u if count[u] == 1 else f"{u}~{seen[u]}"
            seen[u] += 1
            r = dict(top, snapshot=date, piece_id=pid, admin_id=u, control_split=int(count[u] > 1))
            rows.append(r)
            if pg is not None:
                geoms[pid] = pg
        pd.DataFrame(rows)[SNAP_COLS].to_csv(WW2_WORK / f"prov_snapshot_{date}.csv", index=False)
        with open(WW2_WORK / f"prov_split_{date}.geojson", "w") as f:
            json.dump({"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"piece_id": k}, "geometry": mapping(g)} for k, g in geoms.items()]}, f)
        d = pd.DataFrame(rows)
        print(date, "pieces:", len(d), "split provinces:", int((d.control_split == 1).sum()),
              f"population {d.population_est.sum() / 1e9:.3f} bn", flush=True)
    print("distinct province-level units:", len(df))
    print(df.groupby("tier_en").size())


if __name__ == "__main__":
    main()
