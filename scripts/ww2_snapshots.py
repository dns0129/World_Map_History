"""Political situation of the historical administrative units on six WWII dates.

For each snapshot date, every unit in force (work/ww2/hist_units, see ww2_histunits.py):
  * de jure political unit and sovereign (CShapes 2.0 on that exact date); a unit lying in
    two political units is cut along their border
  * de facto controller, from, in order:
      CShapes owner -> whole-unit control events (curated/control_events.csv)
      -> East Asia occupation layers traced by K. Lawson (Manchukuo, Kwantung, Mengjiang,
         Japanese-occupied China 1942, CCP base areas 1941-42, Indochina provinces ceded
         to Thailand 1941)
      -> curated region rules (curated/ww2_region_control.csv)
    The rules name present-day regions, so they are evaluated on the reference units
    (ww2_reference.py) inside each historical unit; the unit is cut only where the
    controller differs between them.
  * alliance bloc (simplified)
  * population estimate: GHS-POP 1975 at 30 arc-seconds summed per piece, scaled so the
    pieces of each political unit add up to that unit's population in the main database
    (US: to each state's census estimate)
Outputs in work/ww2/: snapshot_<date>.csv and split_<date>.wkb (pieces whose shape
differs from their unit).
"""
import json
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window
from shapely import STRtree
from shapely.geometry import Point, Polygon, box, mapping, shape
from shapely.ops import unary_union

import topo
from build_database import Namer
import controllers
from common import RAW, WORK, ROOT
from controllers import MANCHU_ROC, UNIT_FIX
from ww2_territories import ALL_ISLANDS, island_unit
from ww2_common import REF_WORK, RULES, SET, SNAPSHOTS, UNCOVERED, UNCOVERED_BOX, WW2_RAW, WW2_WORK
from ww2_geo import diff, eq_area_km2, inter, opening, polys, read_geojson, read_outlines, union, write_outlines

LAW = WW2_RAW / "lawson"
SPLIT_MIN_SHARE = 0.03
RU1897_SPLIT_KM2 = 300  # parts of an 1897 province this large in another unit are cut off, whatever their share
GHS = RAW / "ghs_pop" / "GHS_POP_E1975_30ss.tif"

def names_on(snap):
    return controllers.names_on(SET, snap)


def bloc(gw, snap, detail):
    return controllers.bloc_on(SET, gw, snap, detail)



def load_units():
    arcs, geoms = topo.load(RAW / "cshapes_2_gw.topojson")
    out = []
    for g in geoms:
        p = dict(g["properties"])
        p["geom"] = topo.to_shape(arcs, g)
        out.append(p)
    return out


def overlays():
    occ = [g for _, g in read_geojson(LAW / "occupied-zone-1942.geojson")]
    occ = polys(__import__("shapely.ops", fromlist=["unary_union"]).unary_union(occ))
    meng = polys(shape(json.load(open(LAW / "mengjiang-control-1942.geojson"))["features"][0]["geometry"]))
    ccp = [g for _, g in read_geojson(LAW / "ccp-resistance-areas-1941-1942-p199-v2.geojson")]
    ccp = polys(__import__("shapely.ops", fromlist=["unary_union"]).unary_union(ccp))
    ic = read_geojson(LAW / "french-indochina-admin.geojson")
    ceded = polys(__import__("shapely.ops", fromlist=["unary_union"]).unary_union([g for p, g in ic if p.get("ceded")]))
    return occ, meng, ccp, ceded




def control_overlay(snap, county, pt, occ, meng, ccp, ceded):
    """East Asia occupation layers (controllers.OVERLAY_RULES); returns (gw, detail_en, detail_zh, type, source,
    confidence) or None."""
    layers = dict(occ=occ, meng=meng, ccp=ccp, ceded=ceded)
    return controllers.overlay_control(snap, county, lambda k: layers[k] is not None and layers[k].contains(pt))


def geo_shapes(match):
    """Shapes of a "geo" rule: box:W,S,E,N | circle:LON,LAT,KM | poly:LON LAT;LON LAT;... joined by "|"."""
    out = []
    for part in match.split("|"):
        kind, _, arg = part.strip().partition(":")
        if kind == "box":
            w, s_, e, n = map(float, arg.split(","))
            out.append(box(w, s_, e, n))
        elif kind == "circle":
            x, y, km = map(float, arg.split(","))
            out.append(Point(x, y).buffer(km / 111.32 / max(np.cos(np.radians(y)), 0.2), 32))
        elif kind == "poly":
            out.append(Polygon([tuple(map(float, xy.split())) for xy in arg.split(";")]))
        else:
            raise ValueError(part)
    return unary_union(out)


_GEO = {}


def rule_match(rule, c):
    if rule["iso3"] != "*" and c["iso3"] not in rule["iso3"].split("|"):
        return False
    if rule["field"] == "*":
        return True
    if rule["field"] == "geo":  # the reference unit's label point lies in the drawn area
        if rule["match"] not in _GEO:
            _GEO[rule["match"]] = geo_shapes(rule["match"])
        return _GEO[rule["match"]].contains(Point(c["label_lon"], c["label_lat"]))
    if rule["field"] == "unit":
        return any(m in (c["unit"], c["unit_cs"]) for m in rule["match"].split("|"))
    if rule["field"] == "hist":  # the historical unit itself, or the province it belongs to
        return bool(set(rule["match"].split("|")) & set(c.get("hist_names") or ()))
    v = c.get(rule["field"])
    if not isinstance(v, str):
        return False
    v = v.replace("\xa0", "").strip()
    return any(v == m or (m.endswith("*") and v.startswith(m[:-1])) for m in rule["match"].split("|"))


def ghs_zonal(pieces):
    """pieces: list of (key, geom). Returns dict key -> GHS-1975 people (30 arc-second grid)."""
    out = defaultdict(float)
    with rasterio.open(GHS) as src:
        tr = src.transform
        tree = STRtree([g for _, g in pieces])
        T = 2400
        for r0 in range(0, src.height, T):
            for c0 in range(0, src.width, T):
                w = Window(c0, r0, min(T, src.width - c0), min(T, src.height - r0))
                wt = src.window_transform(w)
                west, north = wt.c, wt.f
                east, south = west + w.width * wt.a, north + w.height * wt.e
                idx = tree.query(box(west, south, east, north))
                if len(idx) == 0:
                    continue
                order = sorted(idx, key=lambda i: -pieces[i][1].area)
                ids = rasterize(((mapping(pieces[i][1]), int(i) + 1) for i in order), out_shape=(w.height, w.width),
                                transform=wt, fill=0, dtype="int32")
                a = src.read(1, window=w)
                a = np.where(a > 0, a, 0.0)
                s = np.bincount(ids.ravel(), weights=a.ravel(), minlength=len(pieces) + 1)
                for i in np.flatnonzero(s[1:]) :
                    out[pieces[i][0]] += float(s[i + 1])
        # pieces smaller than a pixel: take the pixel under the representative point, scaled by area
        px_km2 = (abs(tr.a) * 111.32) ** 2
        for k, g in pieces:
            if out.get(k, 0) == 0:
                p = g.representative_point()
                row, col = src.index(p.x, p.y)
                if 0 <= row < src.height and 0 <= col < src.width:
                    v = float(src.read(1, window=Window(col, row, 1, 1))[0, 0])
                    out[k] = max(v, 0) * min(1.0, eq_area_km2(g) / (px_km2 * np.cos(np.radians(p.y)) + 1e-9))
    return out


def control_for(c, u, uen, uzh, status, sov_gw, sov_en, sov_zh, snap, pt, whole, rules, ov_layers, state_name):
    """De facto controller of one place: CShapes owner, then whole-unit events, East Asian
    occupation layers and the curated rules (last match wins)."""
    ST = names_on(snap)
    ctrl = dict(gw=sov_gw, en=sov_en, zh=sov_zh, detail=None, detail_zh=None, type=status, source="cshapes", conf="whole")
    e = whole.get((u["country_name"], u["gwcode"]))
    if e is not None:
        gw = int(e.controller_gwcode)
        ctrl.update(gw=gw, en=ST.get(gw, (e.controller_name,))[0], zh=ST.get(gw, (None, e.controller_name_zh))[1],
                    detail=e.controller_name, detail_zh=e.controller_name_zh, type=e.control_type,
                    source=f"event:{e.event_id}")
    ov = control_overlay(snap, c, pt, *ov_layers)
    if ov:
        gw, den, dzh, typ, src, conf = ov
        ctrl.update(gw=gw, en=ST.get(gw, (den,))[0], zh=ST.get(gw, (None, dzh))[1], detail=den, detail_zh=dzh,
                    type=typ, source=src, conf=conf)
    cu = dict(c, unit=uen, unit_cs=u["country_name"])
    for k, r in enumerate(rules):
        if r["field"] in ("*", "unit") and ctrl["source"].startswith("overlay:"):
            continue  # whole-unit rules do not override the East Asian occupation layers
        if snap in r["snapshots"].split("|") and rule_match(r, cu):
            gw = int(r["controller_gwcode"])
            ctrl.update(gw=gw, en=ST.get(gw, (r["controller_name"],))[0],
                        zh=ST.get(gw, (None, r["controller_name_zh"]))[1], detail=r["controller_name"],
                        detail_zh=r["controller_name_zh"], type=r["control_type"], source=f"rule:{k + 2}",
                        conf=r["confidence"])
    if ctrl["en"] is None:
        ctrl["en"], ctrl["zh"] = state_name.get(str(ctrl["gw"]), (str(ctrl["gw"]), None))
    return ctrl


CTRL_KEYS = ("gw", "en", "zh", "detail", "detail_zh", "type", "source", "conf")
CONTROL_MIN_SHARE = 0.08   # a different controller must hold this share of a unit ...
CONTROL_MIN_KM2 = 1500     # ... or this much land to be cut out as its own piece


def control_pieces(g, refs_here, ctrl_of):
    """Cut one unit (or its part inside one CShapes unit) where the controller changes.
    refs_here: reference units intersecting g. Returns [(ctrl, geometry or None if whole)]."""
    if not refs_here:
        return [(None, None)]
    groups = defaultdict(list)
    for r in refs_here:
        groups[tuple(ctrl_of(r)[k] for k in CTRL_KEYS)].append(r)
    if len(groups) == 1:
        return [(next(iter(groups)), None)]
    total = eq_area_km2(g)
    parts = []
    for key, rs in groups.items():
        gg = opening(polys(inter(g, union([r["geom"] for r in rs]))), 0.02)
        km2 = eq_area_km2(gg) if gg is not None else 0
        parts.append([key, gg, km2])
    parts.sort(key=lambda p: -p[2])
    kept = [p for p in parts[1:] if p[1] is not None and (p[2] >= CONTROL_MIN_SHARE * total or p[2] >= CONTROL_MIN_KM2)]
    if not kept:
        return [(parts[0][0], None)]
    major = polys(diff(g, union([p[1] for p in kept])))
    return [(parts[0][0], major)] + [(p[0], p[1]) for p in kept]


def blank_land(g, units, refs, rtree, snap):
    """The land of g (reference outlines, not the sea) inside UNCOVERED_BOX that none of the CShapes units
    covers, in parts too wide and large to be a seam between two outlines; None when under SPLIT_MIN_SHARE of g."""
    land = union([refs[k]["geom"] for k in rtree.query(g, predicate="intersects")])
    if land is None:
        return None
    land = inter(land, box(*UNCOVERED_BOX[snap]))
    cover = union(units)
    rest = opening(polys(diff(inter(g, land), cover) if cover is not None else inter(g, land)), 0.05)
    parts = [p for p in getattr(rest, "geoms", [rest]) if rest is not None and eq_area_km2(p) >= 300]
    rest = polys(union(parts)) if parts else None
    return rest if rest is not None and rest.area >= SPLIT_MIN_SHARE * g.area else None


def main(only=None):
    hist = pd.read_csv(WW2_WORK / "hist_units.csv", low_memory=False)
    dates = [s[0] for s in SNAPSHOTS if not only or s[0] in only]
    used = set(hist[hist.snapshots.apply(lambda x: any(d in x for d in dates))].unit_id)
    hgeom = read_outlines(WW2_WORK / "hist_units.geojson", "unit_id", only=used)  # the dates' units only
    refs = pd.read_csv(REF_WORK / "ref_units.csv", low_memory=False).to_dict("records")
    rgeom = read_outlines(REF_WORK / "ref_units.geojson", "ref_id")
    for r in refs:
        r["geom"] = rgeom[r["ref_id"]]
        r["pt"] = Point(r["label_lon"], r["label_lat"])
    rtree = STRtree([r["geom"] for r in refs])
    island_by_id = ALL_ISLANDS
    units = load_units()
    namer = Namer()
    events = pd.read_csv(ROOT / "curated" / "control_events.csv")
    rules = pd.read_csv(RULES, dtype=str).fillna("").to_dict("records")
    ov_layers = overlays()
    uy = pd.read_csv(WORK / "unit_year.csv")
    targets = pd.read_csv(WORK / "admin1_targets.csv")
    years = pd.read_csv(WORK / "years.csv").set_index("year")

    piece_geom = {}
    rows = []
    for snap, title_zh, title_en in SNAPSHOTS:
        if only and snap not in only:
            continue
        year = int(snap[:4])
        act = [u for u in units if u["start"] <= snap <= u["end"]]
        fid_index = {u["fid"]: i for i, u in enumerate(act)}
        ug = [u["geom"] for u in act]
        tree = STRtree(ug)
        state_name = {}
        for u in act:
            if u["status"] == "independent":
                state_name[str(u["gwcode"])] = namer(u["country_name"], "independent", year)
        ev = events[(events.start_date <= snap) & (events.end_date >= snap) & (events.scope == "whole")]
        whole = {(e.unit_name, e.unit_gwcode): e for e in ev.itertuples()}
        partial = defaultdict(list)
        for e in events[(events.start_date <= snap) & (events.end_date >= snap) & (events.scope == "partial")].itertuples():
            partial[(e.unit_name, e.unit_gwcode)].append(e.event_id)
        hs = hist[hist.snapshots.str.contains(snap, regex=False)].to_dict("records")
        cache = {}
        n_split = 0
        for h in hs:
            hid = h["unit_id"]
            g = hgeom[hid]
            pt = g.representative_point()
            # which political unit(s) of the date the historical unit lies in
            if h["tier"] == 6:
                iu = island_by_id[int(hid[3:].split("#")[0])]
                parts = [(("island", iu), None)]
            elif h["tier"] == 5 and h["cshapes_fid"] == h["cshapes_fid"] and int(h["cshapes_fid"]) in fid_index:
                parts = [(("cs", fid_index[int(h["cshapes_fid"])]), None)]
            else:
                cand = list(tree.query(g, predicate="intersects"))
                shares = [(i, inter(g, ug[i]).area / max(g.area, 1e-12)) for i in cand]
                blank = 1 - sum(s_ for _, s_ in shares)  # share on land CShapes leaves blank on this date
                min_share = SPLIT_MIN_SHARE
                if hid.startswith("RU1897"):  # the 1897 provinces are cut at every later border (Finland in 1918)
                    min_share = min(SPLIT_MIN_SHARE, RU1897_SPLIT_KM2 / max(eq_area_km2(g), 1.0))
                shares = [(i, s_) for i, s_ in shares if s_ >= min_share]
                fb = [i for i, u in enumerate(act) if u["country_name"] == UNCOVERED.get(snap)]
                isl = None
                if not shares and SET != "ww2":  # land CShapes does not draw: a known territory (Greenland)?
                    isl = next((iu for k in rtree.query(pt) if refs[k]["geom"].contains(pt)
                                for iu in [island_unit(refs[k], snap)] if iu), None)
                if isl:
                    parts = [(("island", isl), None)]
                elif fb and sum(s_ for _, s_ in shares) < 0.5 and ug[fb[0]].distance(g) < 0.5:
                    parts = [(("cs", fb[0]), None)]  # land CShapes leaves blank on this date
                elif fb and blank >= SPLIT_MIN_SHARE and ug[fb[0]].distance(g) < 0.5 and \
                        (rest := blank_land(g, [ug[i] for i in cand], refs, rtree, snap)) is not None:
                    # partly on that blank land (Livonia and Courland of 1897 on 11 November 1918): the
                    # blank part counts as that unit, the rest goes to the units it lies in
                    cut = {i: polys(inter(g, ug[i])) for i, _ in shares}
                    cut[fb[0]] = polys(union([cut.get(fb[0]), rest]))
                    parts = [(("cs", i), p) for i, p in cut.items() if p is not None]
                elif len(shares) <= 1 or max(s_ for _, s_ in shares) >= 1 - min_share:
                    hit = [i for i in cand if ug[i].contains(pt)] or [max(shares, key=lambda t: t[1])[0]] if shares else \
                        ([i for i in cand if ug[i].contains(pt)] or cand or [tree.nearest(pt)])
                    parts = [(("cs", hit[0]), None)]
                else:
                    parts = [(("cs", i), polys(inter(g, ug[i]))) for i, _ in shares]
                    parts = [(k, p) for k, p in parts if p is not None]
            kind_flag = "manchukuo" if h["kind"] == "省 (Manchukuo)" else "kwantung" if hid.startswith("KW") else \
                "manchu_roc" if hid.startswith("ROC-") and h["name"] in MANCHU_ROC else ""
            for (ptype, ref_u), gp in parts:
                gpart = gp if gp is not None else g
                if ptype == "island":
                    iu = ref_u
                    u = {"fid": iu[0], "gwcode": None, "country_name": iu[1], "status": iu[3]}
                    status, uen, uzh, sov_gw = iu[3], iu[1], iu[2], iu[4]
                    if sov_gw is None:  # an island state that became independent: its own sovereign
                        sov_gw = iu[0]
                else:
                    u = act[ref_u]
                    status = u["status"]
                    uen, uzh = namer(u["country_name"], status, year)
                    sov_gw = u["gwcode"] if status == "independent" else int(u["owner"])
                    fix = UNIT_FIX.get((snap, u["country_name"]))
                    if fix:
                        status, sov_gw, uen, uzh = fix
                sov_en, sov_zh = names_on(snap).get(sov_gw) or state_name.get(str(sov_gw)) or \
                    ((uen, uzh) if ptype == "island" and sov_gw == ref_u[0] else (None, None))

                def ctrl_of(r, u=u, uen=uen, uzh=uzh, status=status, sov_gw=sov_gw, sov_en=sov_en, sov_zh=sov_zh,
                            gpart=gpart):
                    key = (r["ref_id"], u["fid"], hid if SET != "ww2" else (kind_flag and hid))
                    if key not in cache:
                        c = dict(r, defacto_parent_kind={"manchukuo": "省 (Manchukuo)", "kwantung": "leased territory",
                                                         "manchu_roc": "ROC Manchuria"}.get(kind_flag),
                                 defacto_parent=h["name"], defacto_parent_zh=h["name_zh"],
                                 hist_names=[h["name"], h.get("parent"), h.get("grandparent")])
                        p = r["pt"] if gpart.contains(r["pt"]) else inter(r["geom"], gpart).representative_point()
                        cache[key] = control_for(c, u, uen, uzh, status, sov_gw, sov_en, sov_zh, snap, p, whole, rules,
                                                 ov_layers, state_name)
                    return cache[key]
                refs_here = [refs[k] for k in rtree.query(gpart, predicate="intersects")]
                if not refs_here:
                    refs_here = [refs[rtree.nearest(gpart.representative_point())]]
                cps = control_pieces(gpart, refs_here, ctrl_of)
                if len(cps) == 1 and cps[0][0] is not None and cps[0][1] is None:
                    ctrl = dict(zip(CTRL_KEYS, cps[0][0]))
                    cps = [(ctrl, None)]
                else:
                    cps = [(dict(zip(CTRL_KEYS, key)) if key else ctrl_of(refs_here[0]), pg) for key, pg in cps]
                    n_split += len(cps) > 1
                for k, (ctrl, pg) in enumerate(cps):
                    pid = hid + (f"@{u['fid']}" if gp is not None else "") + (f"~{k}" if len(cps) > 1 else "")
                    geom = pg if pg is not None else gpart
                    if pid != hid:
                        piece_geom[pid] = geom
                    rows.append(dict(
                        snapshot=snap, piece_id=pid, admin_id=hid, unit_id=u["fid"], unit_gwcode=u["gwcode"],
                        unit_name_en=uen, unit_name_zh=uzh, unit_status=status, sovereign_gwcode=sov_gw,
                        sovereign_name_en=sov_en, sovereign_name_zh=sov_zh, controller_gwcode=ctrl["gw"],
                        controller_name_en=ctrl["en"], controller_name_zh=ctrl["zh"], controller_detail_en=ctrl["detail"],
                        controller_detail_zh=ctrl["detail_zh"], control_type=ctrl["type"],
                        control_source=ctrl["source"], control_confidence=ctrl["conf"],
                        bloc=bloc(ctrl["gw"], snap, ctrl["detail"]), control_split=int(len(cps) > 1),
                        partial_control_events=";".join(partial.get((u["country_name"], u["gwcode"]), [])),
                        area_km2=round(eq_area_km2(geom), 2), _geom=geom, _parent=h.get("parent")))
        cur = [r for r in rows if r["snapshot"] == snap]
        print(snap, "admin units:", len(hs), "pieces:", len(cur), "split by control:", n_split, flush=True)

        # ---- population estimate
        base = ghs_zonal([(r["piece_id"], r["_geom"]) for r in cur])
        upop = uy[uy.year == year].set_index("unit_id").population.to_dict()
        ugw = uy[uy.year == year].groupby("gwcode").population.sum().to_dict()
        if SET == "postwar":
            # the yearly table describes 1 July: a unit created later in the year (India and Pakistan on 15 August
            # 1947, the states that left the Soviet Union in 1991) takes its population of the next year
            nxt = uy[uy.year == year + 1].set_index("unit_id").population.to_dict()
            upop = {**{u: v for u, v in nxt.items() if u not in upop}, **upop}
        world_ratio = years.loc[year, "world_population"] / 4.069e9
        by_unit = defaultdict(float)
        for r in cur:
            r["pop_base_1975"] = base.get(r["piece_id"], 0.0)
            by_unit[r["unit_id"]] += r["pop_base_1975"]
        st = targets[targets.year == year].set_index("iso_3166_2").population.to_dict()
        state_code = {n: k for k, n in zip(*_us_states())}
        us_state_base = defaultdict(float)
        for r in cur:
            if r["admin_id"].startswith("AHCB-") and r["_parent"] in state_code:
                us_state_base[r["_parent"]] += r["pop_base_1975"]
        island_pop = {v[0]: v[5] for v in ALL_ISLANDS.values()}
        for r in cur:
            stc = state_code.get(r["_parent"]) if r["admin_id"].startswith("AHCB-") else None
            if stc in st and us_state_base[r["_parent"]] > 0:
                f = st[stc] / us_state_base[r["_parent"]]
                r["pop_method"] = "GHS-1975 pattern scaled to state census estimate"
            elif r["unit_id"] in island_pop and by_unit[r["unit_id"]] > 0:
                f = island_pop[r["unit_id"]] / by_unit[r["unit_id"]]
                r["pop_method"] = "GHS-1975 pattern scaled to an approximate territory population " + \
                    ("on the date" if SET == "postwar" else "c. 1940")
            elif by_unit[r["unit_id"]] > 0 and (r["unit_id"] in upop):
                f = upop[r["unit_id"]] / by_unit[r["unit_id"]]
                r["pop_method"] = "GHS-1975 pattern scaled to unit population"
            elif by_unit[r["unit_id"]] > 0 and r["unit_gwcode"] in ugw:
                f = ugw[r["unit_gwcode"]] / by_unit[r["unit_id"]]
                r["pop_method"] = "GHS-1975 pattern scaled to unit population (matched by GW code)"
            else:
                f = world_ratio
                r["pop_method"] = "GHS-1975 pattern scaled by world growth"
            r["population_est"] = round(r["pop_base_1975"] * f)
        print(snap, "population", f"{sum(r['population_est'] for r in cur) / 1e9:.3f} bn", flush=True)

    out = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])
    for snap, d in out.groupby("snapshot"):
        d.to_csv(WW2_WORK / f"snapshot_{snap}.csv", index=False)
        keep = set(d.piece_id)
        write_outlines(WW2_WORK / f"split_{snap}.geojson", ((k, g) for k, g in piece_geom.items() if k in keep))
    print(out.groupby("snapshot").agg(pieces=("piece_id", "count"), pop=("population_est", "sum")))
    print(out.groupby(["snapshot", "bloc"]).population_est.sum().unstack())


def _us_states():
    codes = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA",
             "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
             "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]
    names = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
             "District of Columbia", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas",
             "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
             "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
             "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
             "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
             "West Virginia", "Wisconsin", "Wyoming"]
    return ["US-" + c for c in codes], names


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
