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
from common import RAW, WORK, ROOT
from ww2_territories import ALL_ISLANDS, island_unit
from ww2_common import REF_WORK, RULES, SET, SNAPSHOTS, UNCOVERED, UNCOVERED_BOX, WW2_RAW, WW2_WORK
from ww2_geo import diff, eq_area_km2, inter, opening, polys, read_geojson, read_outlines, union, write_outlines

LAW = WW2_RAW / "lawson"
SPLIT_MIN_SHARE = 0.03
RU1897_SPLIT_KM2 = 300  # parts of an 1897 province this large in another unit are cut off, whatever their share
GHS = RAW / "ghs_pop" / "GHS_POP_E1975_30ss.tif"

# Short WWII names for states that appear as controllers
STATE = {255: ("Germany", "德国"), 325: ("Italy", "意大利"), 740: ("Japan", "日本"), 365: ("Soviet Union", "苏联"),
         200: ("United Kingdom", "英国"), 2: ("United States", "美国"), 220: ("France", "法国"),
         710: ("Republic of China", "中华民国"), 310: ("Hungary", "匈牙利"), 360: ("Romania", "罗马尼亚"),
         355: ("Bulgaria", "保加利亚"), 375: ("Finland", "芬兰"), 800: ("Thailand", "泰国"),
         317: ("Slovakia", "斯洛伐克"), 210: ("Netherlands", "荷兰"), 211: ("Belgium", "比利时"),
         235: ("Portugal", "葡萄牙"), 230: ("Spain", "西班牙"), 900: ("Australia", "澳大利亚"),
         339: ("Albania", "阿尔巴尼亚"), 290: ("Poland", "波兰"), 345: ("Yugoslavia", "南斯拉夫"),
         350: ("Greece", "希腊"), 560: ("South Africa", "南非"), 20: ("Canada", "加拿大"), 920: ("New Zealand", "新西兰"),
         -1: ("Allied powers", "同盟国"), -10: ("Axis powers", "轴心国"), -12: ("Independent State of Croatia", "克罗地亚独立国"),
         -20: ("Front line (contested)", "前线（双方争夺）"), -2: ("Chinese Communist Party", "中国共产党"),
         -30: ("Tuvan People's Republic", "图瓦人民共和国"), -3: ("United Nations", "联合国"),
         -4: ("Free France", "自由法国")}

# Alliance bloc of each controller by snapshot (simplified; neutral otherwise)
S = [s[0] for s in SNAPSHOTS] if SET == "ww2" else [""] * 6
AXIS = {255: S, 325: S[:4] + [], 740: S, 317: S[:5], -12: S[1:5], -10: S,
        310: S[2:5], 360: S[2:5], 355: S[2:5], 375: S[2:5], 800: S[3:5]}
ALLIED = {200: S, 710: S, -2: S, -1: S, -4: S, 900: S, 20: S, 920: S, 560: S, 750: S, 290: S, 210: S, 211: S, 385: S, 212: S,
          390: S[5:], 350: S[2:], 345: S[2:], 365: S[2:], 2: S[2:], 220: [S[0], S[4], S[5]],
          140: S[3:], 70: S[3:], 40: S[3:], 42: S[3:], 41: S[3:], 90: S[3:], 91: S[3:], 92: S[3:], 93: S[3:],
          94: S[3:], 95: S[3:], 530: S[3:], 645: S[3:], 630: S[4:], 100: S[4:], 145: S[4:], 450: S[4:],
          640: S[5:], 651: S[5:], 160: S[5:], 155: S[5:], 135: S[5:], 101: S[5:], 130: S[5:], 150: S[5:], 165: S[5:],
          670: S[5:], 660: S[5:], 652: S[5:], 663: S[5:], 712: S[5:], 360: S[5:], 355: S[5:], 310: [], 375: []}
CONTESTED = {-20}

# ---- 1900-1934 (WW2_SET=early). Controllers without a state of their own on the date:
EARLY_STATE = {
    -1: ("Allied forces", "协约国联军"), -20: ("Contested (fighting)", "交战区（双方争夺）"),
    -30: ("Tuvan People's Republic", "图瓦人民共和国"), -40: ("League of Nations", "国际联盟"),
    -41: ("Free City of Danzig", "但泽自由市"), -50: ("Eight-Nation Alliance", "八国联军"),
    -60: ("Anti-Bolshevik (White) governments", "反布尔什维克政权（白军）"),
    -62: ("Allied intervention forces", "协约国干涉军"), -63: ("Democratic Republic of Georgia", "格鲁吉亚民主共和国"),
    -64: ("Republic of Armenia", "亚美尼亚共和国"), -65: ("Azerbaijan Democratic Republic", "阿塞拜疆民主共和国"),
    -66: ("Ukrainian State (Hetmanate)", "乌克兰国（盖特曼国）"),
    -67: ("State of Slovenes, Croats and Serbs", "斯洛文尼亚人、克罗地亚人和塞尔维亚人国"),
    -68: ("West Ukrainian People's Republic", "西乌克兰人民共和国"),
    -69: ("Arab Government in Damascus", "大马士革阿拉伯政府"), -70: ("Kingdom of Hejaz", "汉志王国"),
    -71: ("Emirate of Nejd and Hasa", "内志和哈萨酋长国"), -72: ("Constitutional Protection Government (Guangzhou)",
                                                           "护法军政府（广州）"),
    -73: ("Outer Mongolia (Bogd Khanate)", "外蒙古（博克多汗国）"), -74: ("Emirate of Bukhara", "布哈拉酋长国"),
    -75: ("Khanate of Khiva", "希瓦汗国"), -80: ("Chinese Soviet Republic", "中华苏维埃共和国"),
}
# States that CShapes does not count as independent on the date but that hold or own land in it
EARLY_STATE_ON = {"1918-11-11": {300: ("Austria-Hungary", "奥匈帝国"), 345: ("Serbia", "塞尔维亚"),
                                 341: ("Montenegro", "黑山")}}


def names_on(snap):
    """Controller names for one date: the special codes, then states named for that date only."""
    if SET == "postwar":
        return {**STATE, **POSTWAR_STATE_ON.get(snap, {})}
    return {**STATE, **EARLY_STATE_ON.get(snap, {})} if SET == "early" else STATE
# Bloc of each controller on each date; colonies follow their sovereign (the controller).
#   1900  the Eight-Nation Alliance against the Qing court; the provinces of the Southeast Mutual
#         Protection kept out of the war (their detail names it)
#   1914  the states at war on 4 August 1914
#   1918  the Allied and Associated Powers and the Central Powers as they ended the war
#   1934  members of the League of Nations; Japan and Germany had given notice of withdrawal (1933)
EARLY_BLOCS = {
    "1900-08-14": dict(allied={200, 2, 220, 255, 325, 365, 740, 300, -50}, axis={710}),
    "1914-08-04": dict(allied={200, 220, 365, 345, 211, 20, 900, 920, 560}, axis={255, 300}),
    "1918-11-11": dict(allied={200, 220, 2, 325, 740, 211, 345, 341, 360, 350, 235, 140, 710, 800, 450, 40, 95, 90, 93,
                               91, 94, 41, 20, 900, 920, 560, 315, 290, -1, -60, -62, -67, -69, -70, -72},
                       axis={255, 305, 310, 300, 355, 640, -66}),
    "1934-10-16": dict(allied={700, 339, 160, 900, 305, 211, 145, 355, 20, 155, 710, 100, 40, 315, 390, 42, 130, 92,
                               366, 530, 375, 220, 350, 90, 41, 91, 310, 630, 645, 205, 325, 367, 450, 368, 212, 70,
                               210, 920, 93, 385, 95, 150, 135, 290, 235, 360, 365, 560, 230, 380, 225, 800, 640, 200,
                               165, 101, 345, -40, -41},
                       axis={740, 255}),
}


# ---- 1946-1991 (WW2_SET=postwar). Controllers without a state of their own on the date, and
# states CShapes does not yet (or no longer) list on the date
POSTWAR_STATE = {
    -1: ("Allied powers (four-power administration)", "盟国（四国共管）"), -20: ("Contested (fighting)", "交战区（双方争夺）"),
    -2: ("Chinese Communist Party", "中国共产党"), -3: ("United Nations", "联合国"),
    -100: ("Azerbaijan People's Government", "阿塞拜疆人民政府"), -101: ("Republic of Mahabad", "马哈巴德共和国"),
    -102: ("East Turkestan Republic (Three Districts)", "东突厥斯坦共和国（三区）"),
    -104: ("Hyderabad State", "海得拉巴土邦"), -105: ("Jammu and Kashmir (princely state)", "查谟和克什米尔土邦"),
    -106: ("Junagadh State", "朱纳格特土邦"), -107: ("Khanate of Kalat", "卡拉特汗国"),
    -110: ("Allied Military Government (UK/US)", "英美军政府"),
    -113: ("Republic of Serbian Krajina", "塞尔维亚克拉伊纳共和国"),
    -114: ("Pridnestrovian Moldavian Republic", "德涅斯特河沿岸摩尔达维亚共和国"),
    -116: ("Chechen Republic of Ichkeria", "车臣伊奇克里亚共和国"),
    -118: ("Turkish Republic of Northern Cyprus", "北塞浦路斯土耳其共和国"),
    -122: ("Provisional Government of Eritrea (EPLF)", "厄立特里亚临时政府（厄人阵）"),
    -123: ("Kurdistan Region (Kurdistan Front)", "库尔德斯坦地区（库尔德斯坦阵线）"),
    -126: ("Liberation Tigers of Tamil Eelam", "泰米尔伊拉姆猛虎解放组织"),
    -129: ("Sikkim (protectorate)", "锡金（保护国）"),
}
_VIET_MINH = {816: ("Democratic Republic of Vietnam (Viet Minh)", "越南民主共和国（越盟）"), 812: ("Pathet Lao", "巴特寮")}
# States named for one date only: the People's Republic proclaimed in the CCP-held land on 1 October 1949;
# Russia, Croatia and Slovenia at the end of 1991
POSTWAR_STATE_ON = {
    "1946-06-26": _VIET_MINH, "1947-08-15": _VIET_MINH, "1948-09-12": _VIET_MINH,
    "1949-10-01": {**_VIET_MINH, -2: ("People's Republic of China", "中华人民共和国")},
    "1953-07-27": _VIET_MINH,
    "1991-12-26": {365: ("Russia", "俄罗斯"), 344: ("Croatia", "克罗地亚"), 349: ("Slovenia", "斯洛文尼亚"),
                   345: ("Yugoslavia", "南斯拉夫"), 260: ("Germany", "德国")},
}
# Bloc of each controller on each date; colonies follow their sovereign (the controller).
#   1946  the Western Allies and the Soviet sphere of the "iron curtain" speech (March 1946)
#   1947  the Truman Doctrine and the Marshall Plan against the Soviet bloc
#   1948  after the Brussels Treaty, the Prague coup and Yugoslavia's expulsion from the Cominform
#   1949  NATO (April 1949) and the US allies in Asia; the Soviet bloc with the new PRC
#   1953  NATO, ANZUS and the US allies in Asia; the Soviet bloc, the PRC and North Korea
#   1991  NATO; the Commonwealth of Independent States (Alma-Ata, 21 December 1991)
_WEST = {2, 200, 220, 20, 900, 920, 560, 210, 211, 212, 385, 390, 395, 350, 710}
_EAST = {365, 712, 290, 345, 339, 355, 360, 310, 315, -2, -100, -101, -102}
_NATO49 = {2, 200, 220, 20, 210, 211, 212, 390, 395, 325, 385, 235}
POSTWAR_BLOCS = {
    "1946-06-26": dict(allied=_WEST | {640, -110}, axis=_EAST),
    "1947-08-15": dict(allied=_WEST | {640, 325, -110}, axis=_EAST),
    "1948-09-12": dict(allied=_WEST | {640, 325, 732, -110}, axis=(_EAST - {345}) | {731}),
    "1949-10-01": dict(allied=_NATO49 | {350, 640, 900, 920, 710, 732, 840, -110}, axis=(_EAST - {345}) | {731, 816}),
    "1953-07-27": dict(allied=_NATO49 | {350, 640, 260, 900, 920, 732, 713, 840, 740, -110}, axis=(_EAST - {345, -2}) | {731, 816, 710, 265}),
    "1991-12-26": dict(allied=_NATO49 | {350, 640, 260, 230},
                       axis={365, 369, 370, 359, 371, 373, 705, 703, 702, 701, 704}),
}


if SET == "early":
    STATE = EARLY_STATE  # other states take the name the period used (build_database.Namer)
elif SET == "postwar":
    STATE = POSTWAR_STATE


def early_bloc(gw, snap, detail):
    if gw in CONTESTED:
        return "contested"
    b = EARLY_BLOCS[snap]
    if snap == "1900-08-14" and gw == 710 and detail and "Mutual Protection" in detail:
        return "neutral"
    if gw == 740 and detail and detail.startswith("Manchukuo"):
        return "axis"
    return "allied" if gw in b["allied"] else "axis" if gw in b["axis"] else "neutral"


def postwar_bloc(gw, snap, detail):
    if gw in CONTESTED:
        return "contested"
    b = POSTWAR_BLOCS[snap]
    if gw == 365 and detail and "Soviet" not in detail and snap == "1991-12-26":
        return "axis"
    return "allied" if gw in b["allied"] else "axis" if gw in b["axis"] else "neutral"


def bloc(gw, snap, detail):
    if SET == "early":
        return early_bloc(gw, snap, detail)
    if SET == "postwar":
        return postwar_bloc(gw, snap, detail)
    if gw in CONTESTED:
        return "contested"
    if detail and "Vichy" in detail:
        return "neutral"
    if snap in AXIS.get(gw, ()):
        return "axis"
    if snap in ALLIED.get(gw, ()):
        return "allied"
    if gw == 325 and snap == S[4]:
        return "axis"
    return "neutral"


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


# Before Manchukuo's own provinces (1934-41) are known, its territory is that of these 1928-45 provinces
MANCHU_ROC = {"Liaoning": ("Fengtian", "奉天"), "Jilin": ("Jilin", "吉林"), "Heilongjiang": ("Heilongjiang", "黑龙江"),
              "Jehol": ("Rehe", "热河")}
# Political units whose CShapes status on the date misdescribes them: (date, CShapes name) ->
# (status, sovereign gw, name en, name zh). Serbia and Montenegro had been freed by 11 November 1918.
UNIT_FIX = {("1918-11-11", "Serbia"): ("independent", 345, "Serbia", "塞尔维亚"),
            ("1918-11-11", "Montenegro"): ("independent", 341, "Montenegro", "黑山"),
            ("1991-12-26", "Russia (Soviet Union)"): ("independent", 365, "Russia", "俄罗斯"),
            ("1991-12-26", "German Federal Republic"): ("independent", 260, "Germany", "德国")}


def control_overlay(snap, county, pt, occ, meng, ccp, ceded):
    """East Asia occupation layers; returns (gw, detail_en, detail_zh, type, source, confidence) or None."""
    year = int(snap[:4])
    if snap > "1945-09-02":
        # after the war only two layers still mean something: the Indochinese land Thailand kept until
        # the Washington agreement of November 1946, and the Kwantung territory (Port Arthur and Dalny),
        # held by the Soviet Union under the treaty of August 1945
        if ceded is not None and county["iso3"] in ("KHM", "LAO") and snap <= "1946-11-17" and ceded.contains(pt):
            return (800, "Thailand (territory ceded by French Indochina in 1941, returned in November 1946)",
                    "泰国（1941 年法属印度支那割让地，1946 年 11 月归还）", "annexation", "overlay:indochina_ceded", "whole")
        if county.get("defacto_parent_kind") == "leased territory" and snap < "1949-10-01":
            return (365, "Soviet Union (Port Arthur naval base and Dalny, treaty of 14 August 1945)",
                    "苏联（旅顺海军基地与大连，1945 年 8 月 14 日条约）", "leased_territory", "overlay:kwantung", "whole")
        return None
    if snap < "1937-07-07":
        if county.get("defacto_parent_kind") == "ROC Manchuria" and snap >= "1932-03-01":
            name = county.get("defacto_parent")
            if name == "Jehol" and snap < "1933-03-04":
                return None
            en, zh = MANCHU_ROC[name]
            return (740, f"Manchukuo ({en} Province)", f"伪满洲国（{zh}省）", "client_state", "overlay:manchukuo_roc", "whole")
        if county.get("defacto_parent_kind") != "leased territory":
            return None
        if snap < "1905-09-05":
            return (365, "Kwantung Leased Territory (Russia, Port Arthur and Dalny)", "关东州（俄国租借地，旅顺、大连）",
                    "leased_territory", "overlay:kwantung", "whole")
        return (740, "Kwantung Leased Territory (Japan)", "关东州（日本租借地）", "leased_territory", "overlay:kwantung",
                "whole")
    if county.get("defacto_parent_kind") == "省 (Manchukuo)" or county.get("defacto_parent_kind") == "leased territory":
        lt = county.get("defacto_parent_kind") == "leased territory"
        if snap == "1945-09-02":
            return (365, "Soviet military occupation of Manchuria", "苏军占领东北", "military_occupation",
                    "overlay:manchukuo", "whole")
        if lt:
            return (740, "Kwantung Leased Territory (Japan)", "关东州（日本租借地）", "leased_territory", "overlay:kwantung", "whole")
        return (740, f"Manchukuo ({county.get('defacto_parent')} Province)", f"伪满洲国（{county.get('defacto_parent_zh') or ''}省）",
                "client_state", "overlay:manchukuo", "whole")
    if county["iso3"] not in ("CHN",):
        if ceded is not None and county["iso3"] in ("KHM", "LAO") and snap >= "1941-05-09" and ceded.contains(pt):
            return (800, "Thailand (territory ceded by French Indochina, 1941)", "泰国（1941年法属印度支那割让地）",
                    "annexation", "overlay:indochina_ceded", "whole")
        return None
    if snap in ("1941-12-07", "1942-11-01") and ccp.contains(pt):
        return (-2, "CCP base area / guerrilla zone (1941-42)", "中共抗日根据地 / 游击区（1941-42）", "resistance_base",
                "overlay:ccp_bases_1941_42", "approximate")
    if meng is not None and meng.contains(pt) and snap != "1945-09-02":
        return (740, "Mengjiang (Japanese client state)", "蒙疆（日本扶植政权）", "client_state", "overlay:mengjiang",
                "approximate" if snap == "1939-09-01" else "whole")
    if occ is not None and occ.contains(pt):
        if snap == "1945-09-02":
            return (740, "Japanese forces pending surrender (occupied zone of 1942)", "待投降日军（1942年占领区范围）",
                    "surrendering_forces", "overlay:occupied_zone_1942", "approximate")
        conf = "approximate" if snap in ("1939-09-01", "1940-07-01", "1944-06-06") else "whole"
        return (740, "Japanese-occupied China (incl. Wang Jingwei regime)", "日占区（含汪精卫政权）", "military_occupation",
                "overlay:occupied_zone_1942", conf)
    return None


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
