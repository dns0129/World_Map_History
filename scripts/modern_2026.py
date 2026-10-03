"""The world in 2026, in the same form as the 1939-1945 snapshots, for the map's 2026 tab.

  provinces   Natural Earth 1:10m admin-1 states and provinces. Where Natural Earth draws a
              second-level unit, it is merged into the first-level one (French regions,
              Italian regions, Spanish autonomous communities, the four countries of the
              United Kingdom, Philippine regions, Slovenian and Latvian regions, Maltese
              regions; North Macedonian and Kosovan municipalities join their statistical region or district,
              Burkinabe provinces and Guinean prefectures their region; Hungarian cities with county
              rights and Irish cities join their county)
  de jure     Natural Earth admin-0 countries, except where the United Nations General
              Assembly does not recognise a change: Crimea and Sevastopol stay with Ukraine,
              Northern Cyprus with Cyprus, Somaliland with Somalia, the Golan Heights with Syria
  de facto    the sovereign, with the following exceptions (province-level approximations):
              Russia holds Crimea, Sevastopol and Luhansk; the front runs through Donetsk,
              Zaporizhzhia and Kherson oblasts; Transnistria, Abkhazia, South Ossetia,
              Northern Cyprus and Somaliland are run by unrecognised governments; Israel holds
              the Golan Heights; Morocco most of Western Sahara; Russia leases Baikonur and the
              United States Guantanamo Bay. Wars inside one country (Sudan, Myanmar, Yemen,
              Syria, Libya, Sahel) are not drawn.
  blocs       NATO members, members of the Collective Security Treaty Organization, others,
              and the front line
  population  GHS-POP 2025 (R2023A, 30 arc-seconds) summed per piece and scaled to a world
              population of 8.30 billion for mid-2026 (UN World Population Prospects 2024)

Output in work/modern/: prov_units_2026.csv/.geojson, prov_snapshot_2026.csv,
prov_split_2026.geojson and units_2026.geojson.
"""
import json
import re
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import rasterio
import shapely
import shapely.ops
from rasterio.features import rasterize
from rasterio.windows import Window
from shapely import STRtree
from shapely.geometry import box, mapping, shape

from common import RAW, WORK
from fetch_sources import GHS_URL, NE_BASE, fetch
from ww2_geo import eq_area_km2, polys, union

NE = RAW / "naturalearth"
OUT = WORK / "modern"
GHS = RAW / "ghs_pop" / "GHS_POP_E2025_30ss.tif"
SNAP = "2026"
WORLD_POP = 8.30e9
UNIT_BASE = 900000

DISSOLVE = {"GBR": "geonunit", "SVN": "region", "LVA": "region", "ITA": "region", "FRA": "region", "MLT": "region",
            "ESP": "region", "PHL": "region", "MKD": "region", "KOS": "region", "BFA": "region", "GIN": "region"}
REGION_ALIAS = {("MKD", "Greater Skopje"): "Skopje"}
CITY_INTO_COUNTY = {"HUN": "Urban county", "IRL": "City"}
REGION_ZH = {
    "England": "英格兰", "Scotland": "苏格兰", "Wales": "威尔士", "Northern Ireland": "北爱尔兰",
    "Île-de-France": "法兰西岛", "Hauts-de-France": "上法兰西", "Grand Est": "大东部", "Normandie": "诺曼底",
    "Bretagne": "布列塔尼", "Pays de la Loire": "卢瓦尔河地区", "Centre-Val de Loire": "中央-卢瓦尔河谷",
    "Bourgogne-Franche-Comté": "勃艮第-弗朗什-孔泰", "Auvergne-Rhône-Alpes": "奥弗涅-罗讷-阿尔卑斯",
    "Nouvelle-Aquitaine": "新阿基坦", "Occitanie": "奥克西塔尼", "Provence-Alpes-Côte-d'Azur": "普罗旺斯-阿尔卑斯-蓝色海岸",
    "Corse": "科西嘉", "Guadeloupe": "瓜德罗普", "Martinique": "马提尼克", "Guyane française": "法属圭亚那",
    "La Réunion": "留尼汪", "Mayotte": "马约特",
    "Piemonte": "皮埃蒙特", "Valle d'Aosta": "瓦莱达奥斯塔", "Lombardia": "伦巴第", "Trentino-Alto Adige": "特伦蒂诺-上阿迪杰",
    "Veneto": "威尼托", "Friuli-Venezia Giulia": "弗留利-威尼斯朱利亚", "Liguria": "利古里亚", "Emilia-Romagna": "艾米利亚-罗马涅",
    "Toscana": "托斯卡纳", "Umbria": "翁布里亚", "Marche": "马尔凯", "Lazio": "拉齐奥", "Abruzzo": "阿布鲁佐",
    "Molise": "莫利塞", "Campania": "坎帕尼亚", "Apulia": "普利亚", "Puglia": "普利亚", "Basilicata": "巴西利卡塔",
    "Calabria": "卡拉布里亚", "Sicily": "西西里", "Sardegna": "撒丁",
    "Andalucía": "安达卢西亚", "Aragón": "阿拉贡", "Asturias": "阿斯图里亚斯", "Islas Baleares": "巴利阿里群岛",
    "Canary Is.": "加那利群岛", "Canarias": "加那利群岛", "Cantabria": "坎塔布里亚", "Castilla y León": "卡斯蒂利亚-莱昂",
    "Castilla-La Mancha": "卡斯蒂利亚-拉曼恰", "Cataluña": "加泰罗尼亚", "Valenciana": "巴伦西亚",
    "Extremadura": "埃斯特雷马杜拉", "Galicia": "加利西亚", "La Rioja": "拉里奥哈", "Madrid": "马德里",
    "Murcia": "穆尔西亚", "Foral de Navarra": "纳瓦拉", "País Vasco": "巴斯克", "Ceuta": "休达", "Melilla": "梅利利亚",
}
REGION_ZH_OF = {  # generic region names, per country
    "MKD": {"Skopje": "斯科普里地区", "Pelagonia": "佩拉戈尼亚地区", "Polog": "波洛格地区", "Vardar": "瓦尔达尔地区",
            "Eastern": "东部地区", "Northeastern": "东北地区", "Southeastern": "东南地区", "Southwestern": "西南地区"},
    "KOS": {"Pristina": "普里什蒂纳区", "Prizren": "普里兹伦区", "Peć": "佩奇区", "Đakovica": "贾科维察区",
            "Kosovska Mitrovica": "米特罗维察区", "Gnjilane": "吉兰区", "Uroševac": "费里扎伊区"},
    "BFA": {"Boucle du Mouhoun": "穆洪河湾大区", "Cascades": "瀑布大区", "Centre": "中部大区", "Centre-Est": "中东部大区",
            "Centre-Nord": "中北部大区", "Centre-Ouest": "中西部大区", "Centre-Sud": "中南部大区", "Est": "东部大区",
            "Hauts-Bassins": "上盆地大区", "Nord": "北部大区", "Plateau-Central": "中部高原大区", "Sahel": "萨赫勒大区",
            "Sud-Ouest": "西南大区"},
    "GIN": {"Boke": "博凯区", "Kindia": "金迪亚区", "Mamou": "马木区", "Labé": "拉贝区", "Faranah": "法拉纳区",
            "Kankan": "康康区", "Nzérékoré": "恩泽雷科雷区", "Conakry": "科纳克里"},
}
NAME_ZH = {"CHN": "中国", "TWN": "台湾", "KOR": "韩国", "PRK": "朝鲜", "MNG": "蒙古", "CYN": "北塞浦路斯",
           "ARE": "阿联酋", "BIH": "波黑", "SWZ": "埃斯瓦蒂尼", "PGA": "南沙群岛", "SPI": "南巴塔哥尼亚冰原",
           "CNM": "塞浦路斯缓冲区", "USG": "关塔那摩湾", "KAB": "拜科努尔"}
NATO = {"ALB", "BEL", "BGR", "CAN", "HRV", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC", "HUN", "ISL", "ITA", "LVA",
        "LTU", "LUX", "MNE", "NLD", "MKD", "NOR", "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE", "TUR", "GBR", "USA"}
CSTO = {"RUS", "BLR", "KAZ", "KGZ", "TJK", "ARM"}  # Armenia froze its participation in 2024
BLOC_NAMES = {"allied": "北约成员国", "axis": "集体安全条约组织成员国", "neutral": "其他国家", "contested": "交战前线"}
# de jure sovereign where the UN does not recognise the de facto one
DEJURE = {"CYN": "CYP", "SOL": "SOM", "USG": "CUB", "KAB": "KAZ"}
# de facto controllers that are not the de jure state: key -> (zh, en, colour, type, detail)
SPECIAL = {
    "FRONT": ("交战前线", "Front line", "#b9b6aa", "front_line", "俄乌战争前线：州内部分地区被俄罗斯占领（按整州近似）"),
    "TRANSN": ("德涅斯特河沿岸", "Transnistria", "#c4a484", "de_facto_state", "未获承认的政权，俄军驻扎"),
    "ABK": ("阿布哈兹", "Abkhazia", "#a99bbf", "de_facto_state", "未获普遍承认的政权，俄罗斯支持"),
    "SOS": ("南奥塞梯", "South Ossetia", "#9fb7a8", "de_facto_state", "未获普遍承认的政权，俄罗斯支持"),
    "CYN": ("北塞浦路斯", "Northern Cyprus", "#d4a373", "de_facto_state", "仅土耳其承认的政权"),
    "SOL": ("索马里兰", "Somaliland", "#b5c99a", "de_facto_state", "自 1991 年起自治、未获普遍承认"),
}
PALETTE = ["#d9776f", "#5f9fd0", "#7fb07a", "#e3c25a", "#a67fb5", "#6fbfb3", "#e39a6c", "#c97f8f", "#9eb36a",
           "#7d8fc9", "#c9a46e", "#86c49b"]
FIXED = {"RUS": "#c9746b", "CHN": "#e3c25a", "USA": "#5f9fd0", "IND": "#e39a6c", "BRA": "#7fb07a", "CAN": "#c97f8f",
         "AUS": "#c9a46e", "UKR": "#7d8fc9", "DEU": "#9a9fa6", "FRA": "#6f8fd0", "GBR": "#d9776f", "JPN": "#e6b0a8"}


def lighten(hexcolor, t):
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(v + (255 - v) * t) for v in (r, g, b))


def load(name):
    return json.load(open(NE / f"{name}.geojson"))["features"]


def zonal(pieces):
    """GHS-POP 2025 people per piece (key, geometry)."""
    out = defaultdict(float)
    with rasterio.open(GHS) as src:
        tree = STRtree([g for _, g in pieces])
        T = 2400
        for r0 in range(0, src.height, T):
            for c0 in range(0, src.width, T):
                w = Window(c0, r0, min(T, src.width - c0), min(T, src.height - r0))
                wt = src.window_transform(w)
                west, north = wt.c, wt.f
                idx = tree.query(box(west, north + w.height * wt.e, west + w.width * wt.a, north))
                if len(idx) == 0:
                    continue
                order = sorted(idx, key=lambda i: -pieces[i][1].area)
                ids = rasterize(((mapping(pieces[i][1]), int(i) + 1) for i in order), out_shape=(w.height, w.width),
                                transform=wt, fill=0, dtype="int32")
                a = src.read(1, window=w)
                a = np.where(a > 0, a, 0.0)
                s = np.bincount(ids.ravel(), weights=a.ravel(), minlength=len(pieces) + 1)
                for i in np.flatnonzero(s[1:]):
                    out[pieces[i][0]] += float(s[i + 1])
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fetch(GHS_URL.format(y=2025), GHS, 100_000_000)
    for layer in ("ne_10m_admin_1_states_provinces", "ne_10m_admin_0_countries", "ne_10m_admin_0_disputed_areas",
                  "ne_10m_populated_places"):
        fetch(NE_BASE + layer + ".geojson", NE / f"{layer}.geojson", 1000)
    a0 = {f["properties"]["ADM0_A3"]: f["properties"] for f in load("ne_10m_admin_0_countries")}
    by_admin = {p["ADMIN"]: a for a, p in a0.items()}

    def sovereign(a3):
        p = a0.get(a3)
        if p is None:
            return a3
        s = by_admin.get(p["SOVEREIGNT"], a3)
        return s if s in a0 else a3

    def zh(a3):
        return NAME_ZH.get(a3) or (a0[a3]["NAME_ZH"] if a3 in a0 else a3)

    def status(a3):
        t = a0.get(a3, {}).get("TYPE")
        if a3 in ("HKG", "MAC", "ALD"):
            return "part"
        if t in ("Sovereign country", "Country", "Sovereignty") and sovereign(a3) == a3:
            return "independent"
        if t in ("Dependency", "Country", "Lease"):
            return "dependency"
        return "disputed"

    # ---- provinces
    feats = [f for f in load("ne_10m_admin_1_states_provinces") if f["properties"]["adm0_a3"] != "ATA"]
    rows = []
    for f in feats:
        p = f["properties"]
        g = polys(shape(f["geometry"]))
        if g is None:
            continue
        a3 = p["adm0_a3"]
        if a3 == "RUS" and p["name"] in ("Crimea", "Sevastopol"):
            a3 = "UKR"  # annexed in 2014; UN General Assembly resolution 68/262
        rows.append(dict(a3=a3, ne_a3=p["adm0_a3"], name=p["name"], name_zh=p.get("name_zh"), name_en=p.get("name_en") or p["name"],
                         kind=p.get("type_en") or p.get("type"), region=p.get("region"), geonunit=p.get("geonunit"),
                         code=p["adm1_code"], geom=g))
    for r in rows:
        r["region"] = REGION_ALIAS.get((r["ne_a3"], r["region"]), r["region"])
    # units without a region join the neighbouring region they share the longest border with
    for a3, field in DISSOLVE.items():
        todo = [r for r in rows if r["ne_a3"] == a3 and not r[field]]
        while todo:
            done = []
            for r in todo:
                b = r["geom"].boundary.buffer(0.005)
                nb = [(o["geom"].intersection(b).area, o[field]) for o in rows
                      if o["ne_a3"] == a3 and o[field] and o["geom"].intersects(b)]
                if nb:
                    r[field] = max(nb, key=lambda t: t[0])[1]
                    done.append(r)
            if not done:
                break
            todo = [r for r in todo if r not in done]
    groups = defaultdict(list)
    for r in rows:
        field = DISSOLVE.get(r["ne_a3"])
        key = (r["a3"], r[field]) if field and r[field] else (r["a3"], r["code"])
        groups[key].append(r)
    provs = []
    for (a3, k), rs in groups.items():
        if len(rs) == 1:
            r = rs[0]
            provs.append(dict(r, merged=0))
        else:
            g = polys(union([r["geom"] for r in rs]))
            provs.append(dict(a3=a3, name=k, name_zh=REGION_ZH_OF.get(a3, {}).get(k) or REGION_ZH.get(k), name_en=k,
                              kind="region", code=f"{a3}-{k}",
                              geom=g, merged=len(rs)))
    # cities with county rights join the county they lie in
    for a3, kind in CITY_INTO_COUNTY.items():
        cities = [p for p in provs if p["a3"] == a3 and p["kind"] == kind]
        others = [p for p in provs if p["a3"] == a3 and p["kind"] != kind]
        for c in cities:
            b = c["geom"].buffer(0.01)
            host = max(others, key=lambda o: o["geom"].intersection(b).area)
            host["geom"] = polys(union([host["geom"], c["geom"]]))
            host["merged"] = host.get("merged", 0) + 1
            provs.remove(c)
    print("provinces:", len(provs))

    # ---- carve the breakaway areas, the Golan Heights and the de facto states out of their provinces
    disputed = load("ne_10m_admin_0_disputed_areas")
    carve = {}
    for f in disputed:
        p = f["properties"]
        names = {p.get("BRK_NAME"), p.get("NAME")}
        if names & {"South Ossetia", "Transnistria"}:
            carve["SOS" if "South Ossetia" in names else "TRANSN"] = polys(shape(f["geometry"]))
        if "Golan Heights" in names:
            carve["GOLAN"] = polys(shape(f["geometry"]))
    pieces = []  # (province index, geometry or None, controller key, detail, type, confidence)
    for i, pv in enumerate(provs):
        g = pv["geom"]
        rest = g
        cut = []
        for key in ("SOS", "TRANSN", "GOLAN"):
            c = carve.get(key)
            if c is None or not g.intersects(c):
                continue
            part = polys(g.intersection(c))
            if part is not None and eq_area_km2(part) > 20:
                cut.append((key, part))
                rest = polys(rest.difference(c))
        if cut:
            for key, part in cut:
                pieces.append((i, part, key))
            if rest is not None and eq_area_km2(rest) > 20:
                pieces.append((i, rest, None))
        else:
            pieces.append((i, None, None))

    # ---- de jure units
    units = defaultdict(list)
    for i, pv in enumerate(provs):
        a3 = DEJURE.get(pv["a3"], pv["a3"])
        if status(a3) == "part":
            a3 = sovereign(a3)
        pv["unit"] = a3
        units[a3].append(pv["geom"])
    golan = carve.get("GOLAN")
    unit_geom = {a3: polys(union(gs)) for a3, gs in units.items()}
    if golan is not None and "SYR" in unit_geom:  # UN Security Council resolution 497
        unit_geom["SYR"] = polys(union([unit_geom["SYR"], golan]))
        unit_geom["ISR"] = polys(unit_geom["ISR"].difference(golan)) or unit_geom["ISR"]
    uids = {a3: UNIT_BASE + k for k, a3 in enumerate(sorted(unit_geom))}

    # colours: neighbours differ; dependencies in a lighter shade of their sovereign's colour
    indep = [a3 for a3 in unit_geom if status(a3) in ("independent", "disputed")]
    tree = STRtree([unit_geom[a] for a in indep])
    colour = dict(FIXED)
    for a3 in sorted(indep, key=lambda a: -unit_geom[a].area):
        if a3 in colour:
            continue
        near = {colour.get(indep[j]) for j in tree.query(unit_geom[a3].buffer(0.1), predicate="intersects")}
        free = [c for c in PALETTE if c not in near]
        colour[a3] = (free or PALETTE)[(len(colour) * 7) % len(free or PALETTE)]
    for a3 in unit_geom:
        if a3 not in colour:
            colour[a3] = lighten(colour.get(sovereign(a3), "#c9c4b8"), 0.42)

    # ---- pieces with control
    def control(pv, key):
        a3 = pv["unit"]
        name = pv["name"]
        if key in ("SOS", "TRANSN"):
            return key, "whole"
        if key == "GOLAN":
            return "ISR", "whole"
        if pv["a3"] == "UKR" and pv.get("ne_a3") == "RUS":
            return "RUS", "whole"  # Crimea, Sevastopol
        if a3 == "UKR" and name in ("Luhans'k",):
            return "RUS", "approximate"
        if a3 == "UKR" and name in ("Donets'k", "Zaporizhzhya", "Kherson"):
            return "FRONT", "approximate"
        if a3 == "GEO" and name == "Abkhazia":
            return "ABK", "whole"
        if pv["a3"] in ("CYN", "SOL"):
            return pv["a3"], "whole"
        if pv["a3"] == "USG":
            return "USA", "whole"
        if pv["a3"] == "KAB":
            return "RUS", "whole"
        if a3 == "SAH":
            return "MAR", "approximate"  # Morocco holds the land west of the berm
        st = status(a3)
        return (sovereign(a3) if st in ("dependency", "part") else a3), "whole"

    zh_unit = {a3: zh(a3) for a3 in unit_geom}
    prov_rows, snap_rows, split_geoms = [], [], {}
    count = Counter(i for i, _, _ in pieces)
    seen = Counter()
    for i, g, key in pieces:
        pv = provs[i]
        pid = f"M26-{re.sub(r'[^A-Za-z0-9]+', '-', pv['code']).strip('-')}"
        pv["pid"] = pid
        ctrl, conf = control(pv, key)
        unit = "SYR" if key == "GOLAN" else pv["unit"]  # the Golan Heights stay Syrian de jure
        piece = pid if count[i] == 1 else f"{pid}~{seen[i]}"
        seen[i] += 1
        geom = g if g is not None else pv["geom"]
        if count[i] > 1:
            split_geoms[piece] = geom
        if ctrl in SPECIAL:
            czh, cen, ccol, ctype, cdet = SPECIAL[ctrl]
        else:
            czh, cen, ccol = zh(ctrl), a0.get(ctrl, {}).get("NAME", ctrl), colour.get(ctrl, "#c9c4b8")
            ctype = "independent" if ctrl == unit else "dependency" if status(unit) == "dependency" else "control"
            cdet = None
            if unit == "UKR" and ctrl == "RUS":
                ctype, cdet = "military_occupation", ("2014 年被俄罗斯吞并（联合国大会第 68/262 号决议不予承认）"
                                                      if conf == "whole" else "2022 年起几乎全境被俄罗斯占领（按整州近似）")
            if ctrl == "ISR" and unit != "ISR":
                ctype, cdet = "military_occupation", "1967 年起由以色列控制（联合国安理会第 497 号决议不承认其吞并）"
            if ctrl == "MAR" and unit == "SAH":
                ctype, cdet = "control", "摩洛哥控制沙墙以西大部分地区，以东由西撒哈拉人民解放阵线控制（按整区近似）"
            if unit == "PSX":
                cdet = "约旦河西岸 C 区及加沙部分地区由以色列军队控制（未分块表示）"
                conf = "approximate"
        base = ctrl if ctrl not in SPECIAL else None
        bloc = "contested" if ctrl == "FRONT" else "allied" if base in NATO else "axis" if base in CSTO else "neutral"
        st = status(unit)
        snap_rows.append(dict(
            snapshot=SNAP, piece_id=piece, admin_id=pid, unit_id=uids[unit], unit_gwcode=None,
            unit_name_en=a0.get(unit, {}).get("NAME", unit), unit_name_zh=zh_unit[unit],
            unit_status=st,
            sovereign_gwcode=None, sovereign_name_en=a0.get(sovereign(unit), {}).get("NAME"),
            sovereign_name_zh=zh(sovereign(unit)), controller_gwcode=0, controller_name_en=cen, controller_name_zh=czh,
            controller_detail_en=None, controller_detail_zh=cdet, control_type=ctype, control_source="modern",
            control_confidence=conf, bloc=bloc, control_split=int(count[i] > 1), partial_control_events=None,
            area_km2=round(eq_area_km2(geom), 2), pop_method="GHS-POP 2025 scaled to the UN 2026 world total",
            country_key=f"M:{ctrl}", country_zh=czh, country_en=cen, country_color=ccol, nation_color=colour[unit],
            _geom=geom))

    # ---- population
    base = zonal([(r["piece_id"], r["_geom"]) for r in snap_rows])
    total = sum(base.values())
    for r in snap_rows:
        r["population_est"] = int(round(base.get(r["piece_id"], 0) * WORLD_POP / total))
    print(f"GHS 2025 total {total / 1e9:.3f} bn -> {WORLD_POP / 1e9:.2f} bn")

    # ---- write
    for pv in provs:
        lp = shapely.ops.polylabel(max(getattr(pv["geom"], "geoms", [pv["geom"]]), key=lambda q: q.area), tolerance=0.02)
        prov_rows.append(dict(unit_id=pv["pid"], name=pv["name"], name_zh=pv.get("name_zh"), name_en=pv.get("name_en"),
                              tier=3, tier_zh="省级", tier_en="province", kind=pv.get("kind"), basis="present_day_admin1",
                              source="Natural Earth 1:10m admin-1 states and provinces (public domain)"
                                     + (f"; merged from {pv['merged']} units" if pv.get("merged") else ""),
                              note=None, start=None, end=None, partial=0, parent=None, parent_zh=None, grandparent=None,
                              ohm_level=None, wikidata=None, cshapes_fid=None, merged_units=pv.get("merged", 0),
                              snapshots=SNAP, area_km2=round(eq_area_km2(pv["geom"]), 2), label_lon=round(lp.x, 4),
                              label_lat=round(lp.y, 4), _geom=pv["geom"]))
    pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in prov_rows]).to_csv(
        OUT / "prov_units_2026.csv", index=False)
    json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"unit_id": r["unit_id"]},
                                                          "geometry": mapping(r["_geom"])} for r in prov_rows]},
              open(OUT / "prov_units_2026.geojson", "w"))
    pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in snap_rows]).to_csv(
        OUT / "prov_snapshot_2026.csv", index=False)
    json.dump({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"piece_id": k},
                                                          "geometry": mapping(g)} for k, g in split_geoms.items()]},
              open(OUT / "prov_split_2026.geojson", "w"))
    json.dump({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"unit_id": uids[a3], "a3": a3, "name_zh": zh_unit[a3]}, "geometry": mapping(g)}
        for a3, g in unit_geom.items()]}, open(OUT / "units_2026.geojson", "w"))
    json.dump({"bloc_names": BLOC_NAMES}, open(OUT / "meta_2026.json", "w"), ensure_ascii=False)
    d = pd.DataFrame(snap_rows)
    print("pieces", len(d), "units", len(unit_geom), "population", f"{d.population_est.sum() / 1e9:.2f} bn")
    print(d.groupby("bloc").population_est.sum())


if __name__ == "__main__":
    main()
