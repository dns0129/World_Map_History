"""Data files for the interactive province maps (ww2/maps/): 1900-1934, 1939-1945, 1946-1991 and 2026.

  geo-<date>.bin    the outlines one snapshot needs, gzip-compressed, so that the page loads only the
                    date shown: its provinces, the pieces of the provinces a border or front cuts
                    (a piece that is a whole province is drawn with the province's outline), its
                    CShapes units and the area each country actually controls, dissolved. Each
                    outline is simplified and written as zigzag-varint deltas of 1/1000 degree
                    (per feature: parts, rings, points); snap-<date>.json says which is which
  admin.bin         static attributes of the province-level units (columnar JSON, gzip-compressed)
  snap-<date>.json  per-snapshot rows: which pieces exist, who controls them, the countries
                    of the control view with their colours and where their names sit
  relief/           shaded relief sheets, written by ww2_relief.py
  hydro.bin         rivers and lakes as they were in 1939-45 (Natural Earth 10m; gzip-compressed GeoJSON)
  hydro-detail.bin  the denser European and North American river and lake layers (the same)
"""
import colorsys
import gzip
import hashlib
import json
import math
import multiprocessing
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
import shapefile
import shapely
import shapely.ops
from shapely.geometry import MultiPolygon, Polygon, shape

import topo
from common import RAW, WORK
import cities
from ww2_common import SNAPSHOTS, SNAPSHOTS_EARLY, SNAPSHOTS_POSTWAR, WW2_WORK, WW2_OUT, workers
from ww2_geo import polys, read_outlines, union

OUT = WW2_OUT / "maps" / "data"
MODERN = WORK / "modern"
EARLY = WORK / "early"          # the 1900-1934 snapshots (WW2_SET=early)
EARLY_DATES = {s[0] for s in SNAPSHOTS_EARLY}
POSTWAR = WORK / "postwar"      # the 1946-1991 snapshots (WW2_SET=postwar)
POSTWAR_DATES = {s[0] for s in SNAPSHOTS_POSTWAR}
# Blocs and legend notes of the 1900-1934 dates (ww2_snapshots.EARLY_BLOCS says who is in which)
EARLY_META = {
    "1900-08-14": dict(
        bloc_names={"allied": "八国联军各国（及其属地）", "axis": "清廷（对列强宣战）", "neutral": "东南互保各省与其他国家",
                    "contested": "交战区"},
        notes={"bloc_title": "庚子年的阵营 · 人口",
               "bloc": "八国联军为英、美、法、德、意、俄、日、奥匈八国，属地随宗主国。1900 年 6 月清廷对各国宣战；两江、湖广、"
                       "两广、闽浙、山东、四川督抚与列强约定互保，不参与战事（灰色）。天津、北京为联军占领；黑龙江为俄军入侵的"
                       "交战区；奥兰治自由邦已被英军占领，德兰士瓦为布尔战争交战区（按整区近似，斜线）。",
               "control": "京津地区为八国联军占领；关东州为俄国租借地；奥兰治自由邦为英军占领。"}),
    "1914-08-04": dict(
        bloc_names={"allied": "协约国（已参战）", "axis": "同盟国（已参战）", "neutral": "中立国 / 尚未参战", "contested": "交战区"},
        notes={"bloc_title": "参战国 · 人口",
               "bloc": "8 月 4 日已处于战争状态的国家：协约国为塞尔维亚、俄国、法国、比利时、英国及其自治领和殖民地；同盟国为"
                       "奥匈帝国和德国。黑山（8 月 5 日）、日本（8 月 23 日）、奥斯曼帝国（11 月）、意大利（1915 年）此时尚未参战。",
               "control": "德国 8 月 2 日占领卢森堡；外蒙古（博克多汗国）1911 年起自治；乌梁海 1914 年 4 月成为俄国保护地。"}),
    "1918-11-11": dict(
        bloc_names={"allied": "协约国及其盟国", "axis": "同盟国", "neutral": "中立国 / 退出大战", "contested": "交战区（俄国内战等）"},
        notes={"bloc_title": "大战结束时的阵营 · 人口",
               "bloc": "协约国及其盟国含美、日、中、暹罗、巴西等对德宣战的国家，以及捷克斯洛伐克、波兰和俄国白军；同盟国为德国、"
                       "奥匈（已分解为奥地利、匈牙利等）、奥斯曼帝国、保加利亚，四国均已停战。苏维埃俄国 1918 年 3 月退出大战，"
                       "计为中立。俄国内战前线与利沃夫为交战区（按整州近似，斜线）。",
               "control": "停战当日的实际控制：德军仍占领比利时大部、卢森堡、法国阿登，以及布列斯特和约后的波罗的海、白俄罗斯和乌克兰"
                          "（盖特曼国）；协约国占领奥斯曼的阿拉伯省份；俄国内战各方、高加索三国、斯洛文尼亚人、克罗地亚人和塞尔维亚人"
                          "国单列。均为按整州、整区的近似。"}),
    "1934-10-16": dict(
        bloc_names={"allied": "国际联盟成员国", "axis": "已宣布退出国联（日、德）及满洲国", "neutral": "非国联成员",
                    "contested": "交战区"},
        notes={"bloc_title": "国际联盟成员 · 人口",
               "bloc": "国际联盟成员国（1934 年 9 月苏联、阿富汗、厄瓜多尔加入），属地随宗主国。日本（1933 年 3 月）与德国（1933 年"
                       " 10 月）已宣布退出，满洲国随日本；美国、巴西、埃及、沙特阿拉伯等不是成员。查科战争前线与阿斯图里亚斯起义为"
                       "交战区（斜线）。",
               "control": "东北四省为伪满洲国（按 1928–45 年省界近似）；中华苏维埃共和国的中央苏区与川陕苏区按县近似；萨尔盆地由"
                          "国际联盟管理。"}),
}
# Blocs and legend notes of the 1946-1991 dates (ww2_snapshots.POSTWAR_BLOCS says who is in which)
POSTWAR_META = {
    "1946-06-26": dict(
        bloc_names={"allied": "西方盟国（美英法等）及其属地", "axis": "苏联势力范围（含中共控制区）", "neutral": "其他国家",
                    "contested": "交战区"},
        notes={"bloc_title": "铁幕初落 · 人口",
               "bloc": "按丘吉尔 1946 年 3 月“铁幕”演说划分：苏联及东欧各国、外蒙古、德奥的苏占区、朝鲜三八线以北，以及中共、"
                       "伊朗阿塞拜疆与马哈巴德、新疆三区等苏联支持的政权为一方；美英法及其属地、比荷卢、北欧、希腊、土耳其、"
                       "中华民国为另一方。中原突围地区为交战区。中共控制区按县近似（斜线）。",
               "control": "德国、奥地利分为美英法苏四个占领区，柏林、维也纳四国共管；日本由美国主导的盟军占领，冲绳、奄美归美军；"
                          "朝鲜以三八线分美苏占领区；关东州（旅大）由苏军驻守。国共双方控制区按县近似。"}),
    "1947-08-15": dict(
        bloc_names={"allied": "西方阵营（杜鲁门主义、马歇尔计划）", "axis": "苏联阵营（含中共控制区）", "neutral": "其他国家",
                    "contested": "交战区"},
        notes={"bloc_title": "冷战开始 · 人口",
               "bloc": "1947 年 3 月杜鲁门主义援助希腊、土耳其，6 月提出马歇尔计划。印度、巴基斯坦当日独立，计入其他国家；"
                       "海得拉巴、克什米尔、朱纳格特尚未加入印巴，卡拉特宣布独立。希腊内战山区、陕北与豫东、越南红河三角洲为交战区。",
               "control": "印巴分治；国民政府攻占延安后中共主力转入外线，东北中共控制乡村；荷兰“警察行动”占领爪哇、苏门答腊要地；"
                          "法越战争中越盟控制越北山区与中部。均为按整区、整县的近似。"}),
    "1948-09-12": dict(
        bloc_names={"allied": "西方阵营", "axis": "苏联阵营（含中共控制区）", "neutral": "其他国家（含南斯拉夫）",
                    "contested": "交战区"},
        notes={"bloc_title": "柏林封锁与辽沈战役前夕 · 人口",
               "bloc": "1948 年 2 月捷克斯洛伐克政变，6 月南斯拉夫被开除出情报局（计入其他国家），苏联封锁西柏林。朝鲜半岛 8 月、"
                       "9 月先后成立大韩民国和朝鲜民主主义人民共和国。以色列 5 月建国，第一次中东战争处于第二次停火中，内盖夫为交战区。",
               "control": "东北除长春、沈阳、锦州走廊外均为中共控制，华北、山东、中原大部亦然（国民政府守大城市）；海得拉巴仍未加入印度"
                          "（9 月 13 日印军进攻）；伊拉克军队据守撒马利亚北部。均为近似。"}),
    "1949-10-01": dict(
        bloc_names={"allied": "北约与美国的盟友", "axis": "苏联阵营（含中华人民共和国）", "neutral": "其他国家",
                    "contested": "交战区"},
        notes={"bloc_title": "北约成立与新中国 · 人口",
               "bloc": "北约 1949 年 4 月成立，12 个创始国；希腊、土耳其、中华民国、韩国、菲律宾、澳新计入美国一方。中华人民共和国"
                       "当日成立；德国西部已成立联邦德国（9 月），东部为苏占区（10 月 7 日成立民主德国）。",
               "control": "中华人民共和国控制北方、西北、华东和长江中游；国民政府仍据两广、西南、海南、台湾和舟山。柏林分治。"
                          "印度尼西亚为荷兰与共和国停火后的分治局面（近似）。"}),
    "1953-07-27": dict(
        bloc_names={"allied": "北约、澳新美与美国在亚洲的盟友", "axis": "苏联阵营、中华人民共和国、朝鲜", "neutral": "其他国家",
                    "contested": "交战区"},
        notes={"bloc_title": "朝鲜停战 · 人口",
               "bloc": "北约 14 国（1952 年希腊、土耳其加入）、联邦德国、澳新美同盟，以及日本、韩国、菲律宾、台湾的中华民国为一方；"
                       "苏联、东欧各国、民主德国、蒙古、中华人民共和国、朝鲜、越盟为另一方。越南红河三角洲边缘为交战区。",
               "control": "朝鲜半岛以停战线分南北；越盟控制越北山区与中部，巴特寮占据老挝桑怒、丰沙里；萨尔为法国保护地，"
                          "的里雅斯特 A 区由英美管理；冲绳、奄美仍归美国。"}),
    "1991-12-26": dict(
        bloc_names={"allied": "北约成员国", "axis": "独联体国家（原苏联）", "neutral": "其他国家", "contested": "交战区"},
        notes={"bloc_title": "苏联解体 · 人口",
               "bloc": "北约 16 国；独立国家联合体 11 国（1991 年 12 月 21 日阿拉木图宣言）。波罗的海三国 9 月独立，格鲁吉亚未加入独联体。"
                       "克罗地亚、纳戈尔诺-卡拉巴赫、南奥塞梯与索马里为交战区（斜线）。",
               "control": "苏联 12 月 26 日解体，各加盟共和国独立；南斯拉夫解体中，斯洛文尼亚、克罗地亚已实际独立，塞尔维亚克拉伊纳"
                          "共和国单列；车臣、德涅斯特河沿岸、北塞浦路斯、索马里兰、伊拉克库尔德地区、厄立特里亚为实际自立的政权。"}),
}
META = {**EARLY_META, **POSTWAR_META}
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
    # 1900-1934
    "300": "#e0cf8a", "341": "#8c9fc9", "730": "#9cc29a", "563": "#d9a86a", "564": "#c98f5f",
    "-50": "#8eb2d1", "-60": "#e4dcc0", "-62": "#9fb8cf", "-63": "#c9a0a0", "-64": "#d9a86a", "-65": "#7fb3a8",
    "-66": "#e3c95d", "-67": "#8f80b8", "-68": "#d8c65f", "-69": "#86a95b", "-70": "#9fbf6f", "-71": "#c2a36a",
    "-72": "#5f9e8f", "-73": "#a7b884", "-74": "#b98c6f", "-75": "#c4a07f", "-80": "#c4473d", "-40": "#7fa7c9",
    "-41": "#c8b27a",
    # 1946-1991
    "PRC": "#c4473d", "713": "#d49a3c", "260": "#5d86d8", "265": "#b5584f", "731": "#a65d57", "732": "#5b8fc9",
    "750": "#e0a24c", "770": "#5f9e6e", "771": "#79b38a", "666": "#6f8fd0", "663": "#c9a467", "816": "#c96a4f",
    "-100": "#c98b7b", "-101": "#b4a05f", "-102": "#9d6aa8", "-104": "#c7a3d6", "-105": "#a8c48a", "-106": "#d3b47b",
    "-107": "#b88f6a", "-110": "#7aa3c4", "-113": "#9b6f8d", "-114": "#b07d56", "-116": "#7b9e6a", "-118": "#c96c6c",
    "-122": "#6fae9c", "-123": "#d0a65e", "-126": "#a77c5b", "-129": "#b9cf8f", "-130": "#93a8c9", "-131": "#8a5c4f",
    "369": "#e3c95d", "370": "#9fbf6f", "705": "#69a6c9", "704": "#7fb3a8", "701": "#c2a36a", "702": "#b98c6f",
    "703": "#c4a07f", "371": "#d9a86a", "372": "#c9a0a0", "373": "#7fb3a8", "359": "#d8c65f", "344": "#7b8fc7",
    "349": "#8fc49b", "343": "#c58fb0",
}


def country_key(r):
    gw, det = int(r["controller_gwcode"]), str(r["controller_detail_en"] or "")
    if r["snapshot"] in POSTWAR_DATES:
        if gw == 710 and r["snapshot"] >= "1950":
            return "PRC"
        if gw == -2 and r["snapshot"] == "1949-10-01":
            return "PRC"
        return str(gw)
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


def packed(path, data):
    """gzip-compressed file (mtime 0, so that the same data gives the same bytes); the page inflates it."""
    path.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))


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
    packed(OUT / "hydro.bin", json.dumps({"type": "FeatureCollection", "features": main}, ensure_ascii=False,
                                         separators=(",", ":")).encode())
    for layer in ("ne_10m_lakes_europe", "ne_10m_lakes_north_america"):
        if (NE / f"{layer}.geojson").exists():
            detail += lake_features(NE / f"{layer}.geojson", 0.006)
    packed(OUT / "hydro-detail.bin", json.dumps({"type": "FeatureCollection", "features": detail},
                                                ensure_ascii=False, separators=(",", ":")).encode())
    for old in ("hydro.json", "hydro-detail.json"):
        (OUT / old).unlink(missing_ok=True)  # the uncompressed files of earlier builds


# ---------------------------------------------------------------- main

G = {}  # set in main() before the worker processes fork


def _one_snapshot(k):
    return G["one"](k)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hist = pd.read_csv(WW2_WORK / "prov_units.csv", low_memory=False)
    snaps = {s[0]: pd.read_csv(WW2_WORK / f"prov_snapshot_{s[0]}.csv", low_memory=False) for s in SNAPSHOTS}
    hgeom = read_outlines(WW2_WORK / "prov_units.geojson", "unit_id")
    pgeom = {}
    for s in SNAPSHOTS:
        pgeom.update(read_outlines(WW2_WORK / f"prov_split_{s[0]}.geojson", "piece_id"))
    # the 1900-1934 snapshots, built the same way in work/early; their ids get a prefix
    early = []
    if (EARLY / "prov_units.csv").exists():
        eh = pd.read_csv(EARLY / "prov_units.csv", low_memory=False)
        eh["unit_id"] = "E:" + eh.unit_id
        hist = pd.concat([eh, hist], ignore_index=True)
        hgeom.update({"E:" + k: g for k, g in read_outlines(EARLY / "prov_units.geojson", "unit_id").items()})
        for d, _, _ in SNAPSHOTS_EARLY:
            df = pd.read_csv(EARLY / f"prov_snapshot_{d}.csv", low_memory=False)
            df["piece_id"] = "E:" + df.piece_id
            df["admin_id"] = "E:" + df.admin_id
            snaps[d] = df
            pgeom.update({"E:" + k: g for k, g in read_outlines(EARLY / f"prov_split_{d}.geojson", "piece_id").items()})
        early = list(SNAPSHOTS_EARLY)
    # the 1946-1991 snapshots, built the same way in work/postwar; their ids get the prefix P:
    postwar = []
    if (POSTWAR / "prov_units.csv").exists():
        ph = pd.read_csv(POSTWAR / "prov_units.csv", low_memory=False)
        ph["unit_id"] = "P:" + ph.unit_id
        hist = pd.concat([hist, ph], ignore_index=True)
        hgeom.update({"P:" + k: g for k, g in read_outlines(POSTWAR / "prov_units.geojson", "unit_id").items()})
        for d, _, _ in SNAPSHOTS_POSTWAR:
            df = pd.read_csv(POSTWAR / f"prov_snapshot_{d}.csv", low_memory=False)
            df["piece_id"] = "P:" + df.piece_id
            df["admin_id"] = "P:" + df.admin_id
            snaps[d] = df
            pgeom.update({"P:" + k: g for k, g in read_outlines(POSTWAR / f"prov_split_{d}.geojson", "piece_id").items()})
        postwar = list(SNAPSHOTS_POSTWAR)
    # the present-day map (modern_2026.py) rides along as the last tab
    snapshots = early + list(SNAPSHOTS) + postwar
    modern_ug, modern_meta = {}, {}
    if (MODERN / "prov_snapshot_2026.csv").exists():
        snapshots.append(("2026", "2026 年：当今世界", "The world in 2026"))
        hist = pd.concat([hist, pd.read_csv(MODERN / "prov_units_2026.csv", low_memory=False)], ignore_index=True)
        snaps["2026"] = pd.read_csv(MODERN / "prov_snapshot_2026.csv", low_memory=False)
        hgeom.update(read_outlines(MODERN / "prov_units_2026.geojson", "unit_id"))
        pgeom.update(read_outlines(MODERN / "prov_split_2026.geojson", "piece_id"))
        units26 = json.load(open(MODERN / "units_2026.geojson"))["features"]
        modern_ug = {f["properties"]["unit_id"]: shape(f["geometry"]) for f in units26}
        modern_zh = {f["properties"]["a3"]: f["properties"]["name_zh"] for f in units26}
        modern_meta = json.load(open(MODERN / "meta_2026.json"))

    used = sorted(set().union(*[set(d.piece_id) for d in snaps.values()]))
    fidx = {p: i for i, p in enumerate(used)}
    padmin = {}
    for d in snaps.values():
        padmin.update(zip(d.piece_id, d.admin_id))
    aids = sorted(set(padmin.values()))
    aidx = {a: i for i, a in enumerate(aids)}
    geom_of = lambda p: pgeom.get(p) or hgeom[padmin[p]]
    # each outline encoded once; the per-snapshot files are put together from these
    admin_rec = [encode([hgeom[a]], TOL_PROV) for a in aids]
    feat_rec = {fidx[p]: encode([pgeom[p]], TOL_PROV) for p in used if p in pgeom}  # pieces cut from a province

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
    packed(OUT / "admin.bin", json.dumps(static, ensure_ascii=False, separators=(",", ":")).encode())

    # political units (CShapes) for borders and labels
    arcs, gs = topo.load(RAW / "cshapes_2_gw.topojson")
    unit_ids = sorted(set().union(*[set(d.unit_id) for d in snaps.values()]))
    ug = {g["properties"]["fid"]: topo.to_shape(arcs, g) for g in gs if g["properties"]["fid"] in unit_ids}
    ug.update({u: g for u, g in modern_ug.items() if u in unit_ids})
    unit_ids = [u for u in unit_ids if u in ug]  # territories CShapes does not draw have no outline
    unit_rec = [encode([ug[u]], TOL_UNIT) for u in unit_ids]
    uidx = {u: i for i, u in enumerate(unit_ids)}

    def one_snapshot(k):
        """The data file of one snapshot, its summary and the control-view outlines it adds (numbered from 0
        here; shifted when the snapshots are put together)."""
        snap, tzh, ten = snapshots[k]
        ctrl_geoms = []
        d = snaps[snap].drop_duplicates("piece_id").reset_index(drop=True)
        modern = "country_key" in d.columns
        d["country"] = d.country_key if modern else [country_key(r) for r in d.to_dict("records")]
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
        nat_color = {u: (r["nation_color"] if modern else nation_of(r))
                     for u, r in d.drop_duplicates("unit_id").set_index("unit_id", drop=False).iterrows()}
        nat = nat.sort_values("pop", ascending=False)
        nidx = {u: i for i, u in enumerate(nat.index)}
        nations = [[int(u), r.zh or r.en, r.en, nat_color[u], r.status, r.sov if isinstance(r.sov, str) else None,
                    int(r["pop"]), round(float(r.km2))]
                   for u, r in nat.iterrows()]

        # countries of the control view: dissolved territory, colour, curved name lines
        countries, clabels = [], []
        cindex = {}
        for key, g in sorted(d.groupby("country"), key=lambda kv: -kv[1].population_est.sum()):
            first = g.sort_values("area_km2").iloc[-1]
            if modern:
                zh, en = first.country_zh, first.country_en
            elif (snap in EARLY_DATES or snap in POSTWAR_DATES) and key != "MAN":  # WWII names such as "-1" Allied
                # forces mean other things here
                home = g[g.unit_gwcode == g.controller_gwcode]  # a state is named after its own territory
                nm = home.sort_values("area_km2").iloc[-1] if len(home) else first
                zh, en = nm.controller_name_zh or nm.controller_name_en, nm.controller_name_en
            else:
                zh, en = SPECIAL.get(key, (first.controller_name_zh or first.controller_name_en, first.controller_name_en))
            geom = dissolve([geom_of(p) for p in g.piece_id]) or polys(union([geom_of(p) for p in g.piece_id]))
            ci = len(countries)
            cindex[key] = ci
            comp = g.groupby("unit_name_zh", dropna=False).agg(pop=("population_est", "sum"),
                                                               km2=("area_km2", "sum")).sort_values("km2", ascending=False)
            countries.append([key, zh, en, first.country_color if modern else color_of(key), BLOCS.index(Counter(g.bloc).most_common(1)[0][0]),
                              int(g.population_est.sum()), round(float(g.area_km2.sum())), int(g.admin_id.nunique()),
                              len(ctrl_geoms), [[n if isinstance(n, str) else "—", int(r["pop"]), round(float(r["km2"]))]
                                                for n, r in comp.head(12).iterrows()]])
            ctrl_geoms.append(geom)
            if key in ("-20", "M:FRONT") or geom is None:
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
            "geo_feature": sorted(set(fidx[p] for p in d.piece_id) & feat_rec.keys()),
            "countries": countries, "country_labels": clabels,
            "cities": cities.y2026(modern_zh) if modern else cities.ww2(snap),
            "bloc_names": modern_meta.get("bloc_names") if modern else META.get(snap, {}).get("bloc_names"),
            "notes": META.get(snap, {}).get("notes"),
            "bloc_pop": {b: int(d[d.bloc == b].population_est.sum()) for b in BLOCS},
            "tier_count": {str(t): int(n) for t, n in hist.set_index("unit_id").loc[sorted(set(d.admin_id))]
                           .tier.value_counts().sort_index().items()},
        }
        summary = {"snapshot": snap, "title_zh": tzh, "title_en": ten, "pieces": len(d),
                   "admin_units": int(d.admin_id.nunique()), "countries": len(countries),
                   "population": int(d.population_est.sum()), "bloc_pop": doc["bloc_pop"],
                   "tier_count": doc["tier_count"]}
        print(snap, "pieces", len(d), "provinces", d.admin_id.nunique(), "countries", len(countries),
              "labels", len(clabels), flush=True)
        # the snapshot's outlines, in the order the page reads them: provinces (admin_active), cut pieces
        # (geo_feature), units (units_active), then the control areas (countries[i][8] counts from 0)
        packed(OUT / f"geo-{snap}.bin", b"".join([admin_rec[a] for a in doc["admin_active"]]
                                                 + [feat_rec[f] for f in doc["geo_feature"]]
                                                 + [unit_rec[u] for u in doc["units_active"]])
               + encode(ctrl_geoms, TOL_CTRL))
        return doc, summary

    # the snapshots are independent: one worker process each, as many as fit in memory (forked, so they
    # share everything loaded above)
    G["one"] = one_snapshot
    # a worker killed for memory stops the run (BrokenProcessPool) instead of leaving it waiting
    with ProcessPoolExecutor(workers(len(snapshots), 2.5), mp_context=multiprocessing.get_context("fork")) as pool:
        results = list(pool.map(_one_snapshot, range(len(snapshots))))
    summary = []
    for doc, row in results:
        (OUT / f"snap-{doc['snapshot']}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
        summary.append(row)
    for old in ("geo.bin", "geo-admin.bin", "geo-units.bin", "geo-ctrl.bin", "admin.json"):
        (OUT / old).unlink(missing_ok=True)  # the layout before the per-snapshot files
    (OUT / "index.json").write_text(json.dumps({"snapshots": summary, "blocs": BLOCS, "tiers": TIER_ZH,
                                                "quantum": Q}, ensure_ascii=False, indent=1))
    hydro()
    for p in sorted(OUT.iterdir()):
        print(p.name, f"{p.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
