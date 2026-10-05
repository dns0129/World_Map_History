"""Historical administrative units in force on each snapshot date, 1939-1945.

Only divisions that existed at the time are used. For every date the layers below
are laid down from the finest tier to the coarsest; each unit keeps the area no
finer unit covers, so the result is one partition of the land per date.

  tier 1  county level    US counties (Newberry AHCB, dated); Taiwan 1930 gun/shi; Korea gun/bu
                          (reconstructed from 1914-1926 records); Burma 1931 districts;
                          OpenHistoricalMap admin_level 6 (dated)
  tier 2  district level  OpenHistoricalMap admin_level 5; Kwantung; Dutch East Indies residencies
                          (1941); French Indochina provinces
  tier 3  province level  Mengjiang and Manchukuo provinces; Republican China provinces (1928-45);
                          Korean and Taiwanese provinces; Philippine provinces (1939); Japanese
                          prefectures and French departements of 1939 (present-day outlines of the
                          same units, see FRANCE_1939); OpenHistoricalMap admin_level 4; Indian
                          princely states (1931); provinces of the 1897 Russian census (up to 1918)
  tier 4  region level    OpenHistoricalMap admin_level 3
  tier 5  whole unit      where no subdivision is known: the country, colony or protectorate as
                          drawn by CShapes 2.0 on that date
  tier 6  territory       islands and protectorates CShapes does not draw (ww2_territories)

Land outlines come from present-day data (the reference units); historical units
are extended to that coastline where small slivers of land were left over.

Output: work/ww2/hist_units.geojson (one feature per distinct unit, with the dates it
is in force) and hist_units.csv.
"""
import hashlib
import json
import pickle
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import shapefile
from pyproj import Transformer
from shapely import STRtree, voronoi_polygons, wkb
from shapely import transform as shp_transform
from shapely.affinity import translate
from shapely.geometry import MultiPoint, Point, box, mapping, shape
from shapely.ops import unary_union

import topo
from build_database import Namer
from common import RAW, ROOT
from ww2_common import REF_WORK, SNAPSHOTS, UNCOVERED, WW2_RAW, WW2_WORK
from ww2_geo import (clip_to, diff, eq_area_km2, fix_rings, gb_path, inter, norm, opening, polys, read_geojson,
                     read_projected, union)
from ww2_territories import island_unit

LAW = WW2_RAW / "lawson"
EA = ROOT / "curated" / "east_asia"
OHM = RAW / "ohm" / "areas_1900_45.jsonl"
DATES = [s[0] for s in SNAPSHOTS]
TIER_ZH = {1: "县级", 2: "地区级", 3: "省级", 4: "大区级", 5: "整个政治单元", 6: "岛屿属地"}
TIER_EN = {1: "county", 2: "district", 3: "province", 4: "region", 5: "whole unit", 6: "territory"}
MIN_KEEP_KM2 = 300      # smaller remnants of a carved unit are given to their neighbours
SNAP_KM2 = 800          # leftover land up to this size joins the adjacent historical unit
FILL_REGION_SHARE = 0.25  # a region the fill-in provinces cover all but this share of gives them the rest


def cand(uid, name, tier, prio, geom, source, basis, kind, name_zh=None, name_en=None, start=None, end=None, **kw):
    return dict(uid=uid, name=name, name_zh=name_zh, name_en=name_en, tier=tier, prio=prio, geom=geom,
                source=source, basis=basis, kind=kind, start=start, end=end, **kw)


def active(c, date):
    return (c["start"] is None or c["start"] <= date) and (c["end"] is None or c["end"] >= date)


def ohm_date(d, end=False):
    if not d:
        return None
    m = re.match(r"^~?(-?\d{1,4})(?:-(\d{2}))?(?:-(\d{2}))?", d.strip())
    if not m:
        return None
    y, mo, da = int(m.group(1)), m.group(2), m.group(3)
    return f"{y:04d}-{mo or ('12' if end else '01')}-{da or ('31' if end else '01')}"


# ---------------------------------------------------------------- county-level layers

def us_counties():
    out = []
    for p, g in read_geojson(WW2_RAW / "us_histcounties.geojson"):
        if g is None or p["END_N"] < int(DATES[0].replace("-", "")) or p["START_N"] > int(DATES[-1].replace("-", "")):
            continue
        s, e = str(p["START_N"]), str(p["END_N"])
        out.append(cand(f"AHCB-{p['ID']}-v{p['VERSION']}", p["NAME"].title(), 1, 0, g,
                        "Newberry Library, Atlas of Historical County Boundaries (CC0), via USAboundariesData",
                        "historical_dated", p.get("CNTY_TYPE") or "county", start=f"{s[:4]}-{s[4:6]}-{s[6:]}",
                        end=f"{e[:4]}-{e[4:6]}-{e[6:]}", parent_hint=p["STATE_TERR"]))
    return out


def taiwan():
    out = []
    for p, g in read_projected(LAW / "taiwan_1930.geojson", 3826):
        out.append(cand(f"TW1930-{p['ID']}", p["NAME"], 1, 1, g,
                        "Academia Sinica, Taiwan 1930 gun/shi boundaries (CC BY-NC-SA 4.0), via K. Lawson",
                        "historical_1930", "郡/市", name_zh=p["NAMEC"], start="1920-10-01"))
    return out


VARIANT = str.maketrans({"淸": "清", "尙": "尚", "黃": "黄"})


def korea_provinces():
    kcsv = pd.read_csv(EA / "korea.csv")
    out = []
    for p, g in read_geojson(LAW / "korea_13_provinces_fine.json"):
        row = kcsv[kcsv.key == p["shapeName"]].iloc[0]
        out.append((row.key, row.zh, row.en, g))
    return out


def korea():
    prov = {zh.translate(VARIANT): (key, zh, en, g) for key, zh, en, g in korea_provinces()}
    r = shapefile.Reader(str(LAW / "place_modern_open.shp"), encoding="utf-8")
    pts = defaultdict(list)
    for rec in r.records():
        lv1 = (rec["adm_lv1"] or "").translate(VARIANT)
        lv2 = (rec["adm_lv2"] or "").strip()
        if lv1 in prov and re.search(r"(郡|府|島)$", lv2):
            pts[lv1].append((float(rec["long"]), float(rec["lat"]), lv2.translate(VARIANT)))
    tr = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    inv = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    to_m = lambda g: shp_transform(g, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))
    to_ll = lambda g: shp_transform(g, lambda c: np.column_stack(inv.transform(c[:, 0], c[:, 1])))
    out = []
    for lv1, (key, zh, en, pg) in prov.items():
        uniq = {}
        for x, y, n in pts.get(lv1, []):
            uniq.setdefault((round(x, 5), round(y, 5)), n)
        xy = np.array([tr.transform(x, y) for (x, y) in uniq])
        names = list(uniq.values())
        pm = to_m(pg)
        cells = voronoi_polygons(MultiPoint(xy), extend_to=pm.envelope.buffer(50000))
        cell_tree = STRtree(list(cells.geoms))
        groups = defaultdict(list)
        for k, (x, y) in enumerate(xy):
            hit = cell_tree.query(Point(x, y), predicate="intersects")
            if len(hit):
                groups[names[k]].append(cells.geoms[hit[0]])
        for gun, cs in groups.items():
            g = polys(to_ll(unary_union(cs).intersection(pm)))
            if g is not None:
                out.append(cand(f"KR1914-{key}-{gun}", gun, 1, 2, g,
                                "Reconstructed (Voronoi of township and facility points) from NIKH Modern Geographic "
                                "Information DB 1914-1926, clipped to K. Lawson's 13 provinces",
                                "reconstructed_1914_1926", "郡/府", name_zh=gun, start="1914-04-01"))
    return out


def burma():
    out = []
    for k, (p, g) in enumerate(read_geojson(LAW / "burma-1931-admin-units.geojson")):
        name = p.get("name") or f"{p.get('group') or 'Burma'} (unit {k})"
        out.append(cand(f"MM1931-{k:03d}", name, 1, 3, g, "Burma 1931 census districts and states, traced by "
                        "K. Lawson (CC0)", "historical_1931", "district / state", parent_hint=p.get("group") or None,
                        start="1897-05-01"))
    return out


# ---------------------------------------------------------------- OpenHistoricalMap

OHM_TIER = {"6": (1, 10), "5": (2, 10), "4": (3, 20), "3": (4, 10)}
# Wrappers that would hide the real first-level units under them: before 1918 OpenHistoricalMap
# draws the whole Kingdom of Hungary at level 4 above its counties (vármegye)
OHM_SKIP = {"Magyar Királyság", "Transleithania"}
OHM_NAME = {"达里尼 Квантунская Область": ("Kwantung Leased Territory", "关东州")}
# Drawn at level 4 but above the provinces: the Turkestan governorate-general and the Alash autonomy (1917-20)
# span several oblasts, which are the first-level divisions (provinces of the 1897 census where
# OpenHistoricalMap has none)
OHM_REGION = {"Русский Туркестан", "Алашская автономия"}


def ohm():
    out = []
    for line in open(OHM):
        o = json.loads(line)
        t = o["tags"]
        lv = t.get("admin_level")
        if lv not in OHM_TIER or t.get("name") in OHM_SKIP:
            continue
        g = polys(fix_rings(wkb.loads(o["wkb"], hex=True)))
        if g is None:
            continue
        tier, prio = OHM_TIER[lv]
        name = t.get("name") or t.get("name:en") or f"OHM relation {o['id']}"
        zh = t.get("name:zh") or t.get("name:zh-Hans") or t.get("name:zh-CN")
        name, zh = OHM_NAME.get(name, (name, zh))
        if name in OHM_REGION:
            tier = 4
        out.append(cand(f"OHM-r{o['id']}", name, tier, prio, g,
                        f"OpenHistoricalMap relation {o['id']} (CC0), planet 2026-10-03", "ohm_dated",
                        t.get("border_type") or f"admin_level {lv}", name_zh=zh, name_en=t.get("name:en"),
                        start=ohm_date(t.get("start_date")), end=ohm_date(t.get("end_date"), True),
                        ohm_level=int(lv), wikidata=t.get("wikidata")))
    return out


# ---------------------------------------------------------------- China before 1928, from the 1928-45 outlines

# The counties of Garze prefecture, roughly the Xikang (Chuanbian) special region before 1939
GARZE = {"Kangdingxian", "Ludingxian", "Danbaxian", "Jiulongxian", "Yajiangxian", "Daofuxian", "Luhuoxian", "Ganzixian",
         "Xinlongxian", "Degexian", "Baiyuxian", "Shiquxian", "Sedaxian", "Litangxian", "Batangxian", "Xiangchengxian",
         "Daochengxian", "Derongxian"}
RECON = "reconstructed_from_1928_outlines"
RECON_NOTE = ("outline of the province of 1928-45 (ENP-China, K. Lawson), merged or split to the units of this "
              "period; the boundaries between provinces moved little, those with Mongolia and Tibet more")
QING = ("1885-01-01", "1911-10-09")      # after Xinjiang became a province; until the Wuchang uprising
BEIYANG = ("1914-06-01", "1928-10-16")   # the special regions of 1914; until the provinces of 1928
ROC_EARLY = ("1928-10-17", "1938-12-31")


def early_china(roc):
    """Provinces of the Qing (1900) and the Beiyang government (1914-1928), and Sichuan and Xikang
    before 1939, put together from the 1928-45 provinces and present-day outlines."""
    gb = lambda iso, lv: [(p, g) for p, g in read_geojson(gb_path(iso, lv)) if g is not None]
    chn1 = {p["shapeName"]: g for p, g in gb("CHN", "ADM1")}
    kham = union([g for p, g in gb("CHN", "ADM2") if p["shapeName"] in GARZE] + [chn1["Tibet Autonomous Region"]])
    xik_small = polys(inter(roc["Xikang"], kham.buffer(0.02)))
    sich_big = polys(union([roc["Sichuan"], diff(roc["Xikang"], xik_small)]))
    gansu = polys(union([roc["Gansu"], roc["Ningxia"]]))
    beijing = polys(inter(roc["Hebei"], chn1["Beijing Municipality"]))
    mongolia = polys(union([g for _, g in gb("MNG", "ADM1")]))
    tuva = polys(union([g for p, g in gb("RUS", "ADM1") if p["shapeName"] == "Tuva"]))
    src = "Reconstructed from the Republican China provinces of 1928-45 (ENP-China, K. Lawson)"
    out = [cand("ROC1928-xikang", "Xikang Special Administrative Region", 3, 2, xik_small, src, RECON, "特别区",
                name_zh="西康特别区", start=ROC_EARLY[0], end=ROC_EARLY[1],
                note="the province of 1939 less the Ya'an and Xichang areas, which belonged to Sichuan until then"),
           cand("ROC1928-sichuan", "Sichuan", 3, 2, sich_big, src, RECON, "省 (ROC)", name_zh="四川",
                start=ROC_EARLY[0], end=ROC_EARLY[1], note="with the Ya'an and Xichang areas, given to Xikang in 1939")]
    beiyang = {
        "Hebei": ("Zhili", "直隶", diff(roc["Hebei"], beijing)), "Liaoning": ("Fengtian", "奉天", None),
        "Jehol": ("Rehe Special Region", "热河特别区", None), "Chahaer": ("Chahar Special Region", "察哈尔特别区", None),
        "Suiyuan": ("Suiyuan Special Region", "绥远特别区", None), "Gansu": ("Gansu", "甘肃", gansu),
        "Qinghai": ("Qinghai (Kokonor)", "青海", None), "Xikang": ("Chuanbian Special Region", "川边特别区", xik_small),
        "Sichuan": ("Sichuan", "四川", sich_big), "Xizang": ("Tibet", "西藏", None),
    }
    qing = {
        "Hebei": ("Zhili", "直隶", None), "Liaoning": ("Shengjing (Mukden general)", "盛京将军辖区（奉天）", None),
        "Jilin": ("Jilin (Jilin general)", "吉林将军辖区", None),
        "Heilongjiang": ("Heilongjiang (Heilongjiang general)", "黑龙江将军辖区", None),
        "Jehol": ("Rehe (Chengde prefecture, Josotu and Juu Uda leagues)", "热河（承德府及卓索图、昭乌达二盟）", None),
        "Chahaer": ("Chahar (Eight Banners and the three Kouwai subprefectures)", "察哈尔（八旗及口北三厅）", None),
        "Suiyuan": ("Suiyuan (Guihua Tumed, Ulanqab and Yekejuu leagues)", "绥远（归化城土默特及乌兰察布、伊克昭二盟）", None),
        "Gansu": ("Gansu", "甘肃", gansu), "Qinghai": ("Qinghai (Xining amban)", "青海（西宁办事大臣辖区）", None),
        "Sichuan": ("Sichuan", "四川", polys(union([roc["Sichuan"], roc["Xikang"]]))),
        "Xizang": ("Tibet (Lhasa ambans)", "西藏（驻藏大臣辖区）", None),
    }
    china = pd.read_csv(EA / "china.csv").set_index("key")
    simp = str.maketrans("廣東甘肅貴雲陝蘇寧熱綏遼黑龍藏", "广东甘肃贵云陕苏宁热绥辽黑龙藏")
    for era, (start, end), table in (("BY", BEIYANG, beiyang), ("QING", QING, qing)):
        for n, g in roc.items():
            if n in ("Ningxia", "Xikang") and n not in table:
                continue  # part of Gansu / Sichuan in this period
            en, z, geom = table.get(n, (n, china["zh"].get(n, n).translate(simp), None))
            geom = polys(geom) if geom is not None else g
            out.append(cand(f"{era}-{norm(n)}", en, 3, 2, geom, src, RECON,
                            "省 (Qing)" if era == "QING" else "省 (Beiyang)", name_zh=z, start=start, end=end,
                            note=RECON_NOTE))
    out.append(cand("BY-jingzhao", "Jingzhao (metropolitan district of Beijing)", 3, 2, beijing, src + "; present-day "
                    "Beijing municipality inside 1928-45 Hebei", RECON, "特别区", name_zh="京兆地方", start=BEIYANG[0],
                    end=BEIYANG[1], note="approximated by present-day Beijing municipality"))
    gsrc = "Present-day outline (geoBoundaries) of the same territory"
    out.append(cand("QING-outer-mongolia", "Outer Mongolia (Uliastai general, Urga and Khovd ambans)", 3, 2, mongolia,
                    gsrc, "present_day_outline_same_unit", "将军辖区 (Qing)", name_zh="外蒙古（乌里雅苏台将军辖区）",
                    start=QING[0], end=QING[1]))
    out.append(cand("BY-outer-mongolia", "Outer Mongolia (autonomous, Bogd Khanate)", 3, 2, mongolia, gsrc,
                    "present_day_outline_same_unit", "自治外蒙古", name_zh="外蒙古（博克多汗国，自治）",
                    start="1911-12-01", end="1921-07-10"))
    out.append(cand("QING-tannu-uriankhai", "Tannu Uriankhai", 3, 2, tuva, gsrc, "present_day_outline_same_unit",
                    "乌梁海 (Qing)", name_zh="唐努乌梁海", start=QING[0], end=QING[1]))
    out.append(cand("RU-uryankhay", "Uryankhay Krai", 3, 2, tuva, gsrc, "present_day_outline_same_unit",
                    "边区 (Russian protectorate)", name_zh="乌梁海边区", start="1914-04-17", end="1921-08-13"))
    out.append(cand("TUV-1921", "Tuvan People's Republic", 3, 2, tuva, gsrc, "present_day_outline_same_unit",
                    "人民共和国", name_zh="图瓦人民共和国", start="1921-08-14", end="1944-10-10"))
    return out


# ---------------------------------------------------------------- province-level traced layers (East Asia)

def east_asia():
    out = []
    china = pd.read_csv(EA / "china.csv").set_index("key")
    zh = lambda n: china["zh"].get(n) if n in china.index else None
    # Mengjiang 1940: three governments of the federation
    names = [((114.88, 40.82), "South Chahar Autonomous Government", "察南自治政府"),
             ((113.30, 40.08), "North Shanxi Autonomous Government", "晋北自治政府")]
    for k, (p, g) in enumerate(read_geojson(LAW / "mengjiang-1940.geojson")):
        n_en, n_zh = "Mongolian Leagues (Mongol United Autonomous Government)", "蒙古联盟自治政府（各盟）"
        for (x, y), en, z in names:
            if g.contains(Point(x, y)):
                n_en, n_zh = en, z
        out.append(cand(f"MJ1940-{k}", n_en, 3, 0, g, "Mengjiang 1940, traced by K. Lawson", "historical_1940",
                        "政厅 (Mengjiang)", name_zh=n_zh, start="1937-10-28"))
    for p, g in read_geojson(LAW / "manchukuo-provinces-v2.geojson"):
        out.append(cand(f"MK-{p['fid']}", p["Name"], 3, 1, g, "Manchukuo provinces c. 1941, traced by K. Lawson",
                        "historical_1941", "省 (Manchukuo)", name_zh=p.get("Name_zh"), start="1939-06-01"))
    kw = polys(unary_union([g for _, g in read_geojson(LAW / "kwantung-1935.geojson")]))
    out.append(cand("KW1935", "Kwantung Leased Territory", 2, 0, kw, "Kwantung 1935, traced by K. Lawson",
                    "historical_1935", "租借地", name_zh="关东州", start="1898-03-27"))
    alias = {"Tibet": "Xizang", "Rehe": "Jehol", "Chahar": "Chahaer"}
    roc = {}
    for p, g in read_geojson(LAW / "republican-china-provinces-v5.geojson"):
        n = alias.get(p["name"].strip(), p["name"].strip())
        roc[n] = g
        # Xikang became a province in 1939, taking the Ya'an and Xichang areas from Sichuan
        start = "1939-01-01" if n in ("Xikang", "Sichuan") else "1928-10-17"
        out.append(cand(f"ROC-{norm(n)}", n, 3, 2, g, "Republican China provinces 1928-1945 (ENP-China, adjusted by "
                        "K. Lawson)", "historical_1928_1945", "省 (ROC)", name_zh=zh(n), start=start))
    out += early_china(roc)
    for key, z, en, g in korea_provinces():
        out.append(cand(f"KR-{key}", en, 3, 3, g, "Korea, 13 provinces, traced by K. Lawson", "historical_1941",
                        "道", name_zh=z, start="1896-08-04"))
    for p, g in read_projected(LAW / "taiwan_1930_shu.geojson", 3826):
        out.append(cand(f"TWS-{norm(p['NAME'])}", p["NAME"], 3, 4, g, "Academia Sinica, Taiwan 1930 prefectures, "
                        "via K. Lawson", "historical_1930", p.get("TYPE") or "州/庁", name_zh=p["NAME"],
                        start="1920-10-01"))
    for p, g in read_geojson(LAW / "dei-1941-admin.geojson"):
        out.append(cand(f"DEI-{p['fid']}", p["name"], 2, 1, g, "Dutch East Indies 1941 residencies, traced by "
                        "K. Lawson", "historical_1941", "residentie", parent_hint=p.get("gouvernement"),
                        start="1938-01-01"))
        # before the Borneo governorate (1938) its residencies answered to Batavia directly
        gov = p.get("gouvernement")
        out.append(cand(f"DEI26-{p['fid']}", p["name"], 2, 1, g, "Dutch East Indies residencies, 1941 outlines traced "
                        "by K. Lawson, grouped as before the 1938 governorates", "historical_1941_outline", "residentie",
                        parent_hint=None if gov and "Borneo" in gov else gov, start="1926-01-01", end="1937-12-31",
                        note="residency outlines of 1941; boundaries of the 1930s may differ slightly"))
    for k, (p, g) in enumerate(read_geojson(LAW / "french-indochina-admin.geojson")):
        n = p["name"] + (f" ({p['name_french']})" if p.get("name_french") and p["name_french"] != p["name"] else "")
        out.append(cand(f"FIC-{k:03d}", n, 2, 2, g, "French Indochina provinces, traced by K. Lawson",
                        "historical_1941", "province", parent_hint=p.get("protectorate"),
                        start="1907-03-23" if p.get("ceded") else None))  # ceded by Siam in 1904 and 1907
    for k, (p, g) in enumerate(read_geojson(LAW / "adm2_PHL_1939.json")):
        out.append(cand(f"PH1939-{k:02d}", p["shapeName"], 3, 5, g, "Philippine provinces 1939, via K. Lawson",
                        "historical_1939", "province", start="1917-01-01"))
    for p, g in read_geojson(LAW / "princely-states-india-1931-v1.2026.8.11.geojson"):
        if p.get("name"):
            out.append(cand(f"IPS-{p['fid']}", p["name"], 3, 30, g, "Indian princely states 1931, traced by "
                            "K. Lawson", "historical_1931", "princely state"))
    return out


# ---------------------------------------------------------------- Russian Empire, provinces of the 1897 census

RU1897 = WW2_RAW / "russia1897" / "1897RussianEmpire.shp"
RU1897_END = "1918-12-31"  # used up to the end of 1918; the Soviet reorganisation begins after that
RU1897_SRC = ("Provinces of the 1897 Russian census, outlines traced from A. Ilyin's school atlas of c. 1914 "
              "(Sablin et al. 2015, Transcultural Empire GIS, heiDATA doi:10.11588/data/10064, CC BY 4.0); used up "
              "to 1918 where OpenHistoricalMap has no province, so later boundary changes are not shown")


def russia_1897(cshapes):
    """Governorates and oblasts of the 1897 census, and the provinces of Finland the same GIS draws. They come
    after OpenHistoricalMap at the province level, so they fill the provinces it lacks, and where it has the
    province the 1897 outline only adds the land it leaves out (see carve). Bukhara and Khiva, drawn whole,
    are left out: they are protectorates with CShapes units of their own."""
    names = pd.read_csv(ROOT / "curated" / "russia_1897.csv", dtype=str).fillna("")
    rows = defaultdict(list)
    for r in names.itertuples():
        rows[r.src].append(r)
    # the atlas borders run a few kilometres off CShapes: keep each province inside the empire
    empire = union([u["geom"] for u in cshapes if u["gwcode"] == 365 and u["start"] <= RU1897_END
                    and u["end"] >= "1897-01-28"])
    # where a region's leftover may be handed to these provinces (see carve): the empire and its coastal waters,
    # less the land of the other units of the empire's time, before the states that broke away from it
    # (Khiva, Bukhara, Austria, Sweden)
    others = [u["geom"] for u in cshapes if u["gwcode"] != 365 and u["start"] <= "1914-08-04"
              and u["end"] >= "1897-01-28"]
    reach = empire.simplify(0.01).buffer(0.5)
    zone = polys(diff(reach, union([o for o in others if o.intersects(reach)])))
    # the atlas draws Sakhalin without the south, Japanese from 1905; until then the 1897 unit is the whole island
    south_sakhalin = union([u["geom"] for u in cshapes if u["country_name"] == "Southern Sakhalin Island"])
    west, east = box(-180, -90, 180, 90), box(180, -90, 540, 90)
    out = []
    shp = shapefile.Reader(str(RU1897), encoding="utf-8")
    for s, rec in zip(shp.shapes(), shp.records()):
        if rec["NAMERUS"] not in rows:
            continue
        g = polys(fix_rings(shape(s.__geo_interface__)))
        g = union([inter(g, west), translate(inter(g, east), -360)])  # Chukotka runs past 180 degrees
        g = polys(inter(g, empire))
        for r in rows[rec["NAMERUS"]]:
            geom = polys(union([g, south_sakhalin])) if r.key == "sakhalin" else g
            out.append(cand(f"RU1897-{r.key}", r.name, 3, 30, geom, RU1897_SRC, "historical_1897", r.kind,
                            name_zh=r.zh, name_en=r.en, start=r.start or None, end=r.end or RU1897_END,
                            note=r.note or None, fill_rest=True, fill_within=zone))
    return out


# ---------------------------------------------------------------- 1939 units drawn with present-day outlines

JAPAN_NOTE = "prefecture boundaries essentially unchanged since 1888 (Okinawa 1879)"
FRANCE_1939 = {  # 1939 departement <- present-day departements (most are one-to-one)
    "Seine": ["Paris", "Hauts-de-Seine", "Seine-Saint-Denis", "Val-de-Marne"],
    "Seine-et-Oise": ["Yvelines", "Essonne", "Val-d'Oise"],
    "Corse": ["Corse-du-Sud", "Haute-Corse"],
    "Seine-Inférieure": ["Seine-Maritime"], "Loire-Inférieure": ["Loire-Atlantique"],
    "Basses-Pyrénées": ["Pyrénées-Atlantiques"], "Basses-Alpes": ["Alpes-de-Haute-Provence"],
    "Charente-Inférieure": ["Charente-Maritime"], "Côtes-du-Nord": ["Côtes d'Armor"],
}
ALSACE = ("Bas-Rhin", "Haut-Rhin", "Moselle")
ALSACE_DE_END, ALSACE_FR = "1918-11-21", "1918-11-22"   # French troops entered Strasbourg on 22 November 1918
FRANCE_APPROX = {"Seine": "the 1968 reform moved 43 communes from Seine-et-Oise into the three new departements "
                          "around Paris, so this outline is larger than the 1939 Seine",
                 "Seine-et-Oise": "outline lacks the 43 communes later moved to the departements around Paris",
                 "Alpes-Maritimes": "includes Tende and La Brigue, Italian until 1947"}


def from_present_day():
    out = []
    jp = pd.read_csv(EA / "japan.csv")
    jmap = {norm(k): (row.en, row.zh) for k, row in zip(jp.key, jp.itertuples())}
    for p, g in read_geojson(gb_path("JPN", "ADM1")):
        k = norm(re.sub(r"\s*Prefecture$", "", p["shapeName"]))
        en, z = jmap.get(k, (p["shapeName"], None))
        out.append(cand(f"JP1940-{k}", en, 3, 6, g, "Japanese prefectures of 1940 (" + JAPAN_NOTE + "); outline from "
                        "geoBoundaries", "present_day_outline_same_unit", "府/県/庁", name_zh=z))
    present = {p["shapeName"].replace("\xa0", "").strip(): g for p, g in read_geojson(gb_path("FRA", "ADM2"))}
    used = set()
    for dep, parts in FRANCE_1939.items():
        g = polys(unary_union([present[x] for x in parts]))
        used.update(parts)
        out.append(cand(f"FR1939-{norm(dep)}", dep, 3, 7, g, "French departements of 1939, outline merged from "
                        "present-day departements (geoBoundaries)", "present_day_outline_same_unit", "département",
                        note=FRANCE_APPROX.get(dep)))
    for name, g in present.items():
        if name not in used:
            out.append(cand(f"FR1939-{norm(name)}", name, 3, 7, g, "French departements of 1939, outline from "
                            "present-day data (unchanged unit)", "present_day_outline_same_unit", "département",
                            note=FRANCE_APPROX.get(name), start=ALSACE_FR if name in ALSACE else None))
    # 1871-1918: the three departements were the German Reichsland of Alsace-Lorraine
    out.append(cand("DE1871-elsass-lothringen", "Reichsland Elsaß-Lothringen", 3, 7,
                    polys(unary_union([present[x] for x in ALSACE])), "Union of the present-day departements Bas-Rhin, "
                    "Haut-Rhin and Moselle (geoBoundaries), the territory annexed by Germany in 1871",
                    "present_day_outline_same_unit", "Reichsland", name_zh="阿尔萨斯-洛林帝国直辖领地",
                    start="1871-05-10", end=ALSACE_DE_END))
    return out


# ---------------------------------------------------------------- partition per date

def carve_order(c):
    return c["prio"], -(int(c["start"][:4]) if c["start"] else -9999), c["area"]


def share_out(g, targets, step=0.1):
    """Split g among the target outlines: each cell of a 0.1-degree grid goes to the nearest target."""
    tree = STRtree(targets)
    parts = defaultdict(list)
    x0, y0, x1, y1 = g.bounds
    for y in np.arange(y0, y1, step):
        row = polys(inter(g, box(x0, y, x1, y + step)))  # robust: clip_by_rect can fail on degenerate rings
        if row is None:
            continue
        for x in np.arange(x0, x1, step):
            cell = polys(inter(row, box(x, y, x + step, y + step)))
            if cell is not None:
                parts[int(tree.nearest(cell.representative_point()))].append(cell)
    return {k: union(v) for k, v in parts.items()}


def carve(cands, date):
    """Lay the candidate units down from tier 1 to tier 4; each keeps what finer tiers left."""
    accepted = []
    for tier in (1, 2, 3, 4):
        cs = [c for c in cands if c["tier"] == tier and active(c, date)]
        # same tier: preferred source first, then the most recently created unit, then the smaller
        cs.sort(key=carve_order)
        finer = [a["geom"] for a in accepted]
        ftree = STRtree(finer) if finer else None
        ctree = STRtree([c["geom"] for c in cs])
        kept = {}
        for i, c in enumerate(cs):
            g = c["geom"]
            hits = [int(j) for j in ctree.query(g, predicate="intersects") if j in kept]
            same = clip_to([kept[j] for j in hits], g.bounds)
            carved = False
            if same:
                ov = sum(inter(g, s).area for s in same)
                if ov > 0.5 * g.area:
                    if not c.get("fill_rest"):
                        continue  # another version of the same unit, or an overlapping duplicate
                    # a source that only fills in (the 1897 Russian provinces): what the other outline
                    # leaves of this province stays, under that unit's name when both draw one province
                    # (similar areas), so that the two parts become one province
                    dup = cs[max(hits, key=lambda j: inter(g, kept[j]).area)]
                    if 2 / 3 <= dup["area_km2"] / c["area_km2"] <= 1.5:
                        c = dict(c, uid=c["uid"] + "-rest", name=dup["name"], name_zh=dup.get("name_zh"),
                                 name_en=dup.get("name_en"), note=f"land the outline of {c['name']} in the 1897 "
                                 f"census GIS adds to {dup['name']} ({dup['source']})")
                g = diff(g, union(same))
                carved = True
            if ftree is not None:
                near = clip_to([finer[k] for k in ftree.query(g, predicate="intersects")], g.bounds)
                if near:
                    g = diff(g, union(near))
                    carved = True
            g = opening(polys(g)) if carved else g
            if g is None:
                continue
            km2 = eq_area_km2(g)
            if km2 < MIN_KEEP_KM2 and km2 < 0.5 * c["area_km2"]:
                continue
            if tier == 4 and ftree is not None and km2 < FILL_REGION_SHARE * c["area_km2"]:
                # what a region keeps beside fill-in provinces (the coast and islands of Finland, which the 1897
                # outlines draw short, the seams between the Turkestan oblasts) goes to the nearest of them, as
                # far as it lies in the empire or its waters (not Khiva, Bukhara, Austria or Sweden)
                fill = [int(k) for k in ftree.query(g.buffer(0.05)) if accepted[int(k)].get("fill_rest")]
                share = polys(inter(g, accepted[fill[0]]["fill_within"])) if fill else None
                if share is not None:
                    for k, part in share_out(share, [accepted[k]["geom"] for k in fill]).items():
                        a = accepted[fill[k]]
                        a["geom"] = polys(union([a["geom"], part]))
                    rest = opening(polys(diff(g, share)))
                    if rest is None or eq_area_km2(rest) < MIN_KEEP_KM2:
                        kept[i] = g  # still carved out of the regions laid down after it
                        continue
                    kept[i] = g
                    accepted.append(dict(c, geom=rest, partial=True))
                    continue
            kept[i] = g
            accepted.append(dict(c, geom=g, partial=km2 < 0.97 * c["area_km2"]))
    return accepted


def remainder(accepted, refs, units, date, namer):
    """Land no historical unit covers: small slivers join the adjacent unit; the rest becomes
    the whole CShapes unit of that date, or a territory CShapes does not draw."""
    year = int(date[:4])
    acc_tree = STRtree([a["geom"] for a in accepted])
    ug = [u["geom"] for u in units]
    utree = STRtree(ug)
    snap = defaultdict(list)
    by_unit = defaultdict(list)
    by_island = defaultdict(list)
    for r in refs:
        near = clip_to([accepted[k]["geom"] for k in acc_tree.query(r["geom"], predicate="intersects")], r["geom"].bounds)
        if near:
            left = opening(polys(diff(r["geom"], union(near))))
        else:
            left = r["geom"]
        if left is None:
            continue
        iu = island_unit(r, date)
        for part in getattr(left, "geoms", [left]):
            if iu:
                by_island[iu].append(part)
                continue
            km2 = eq_area_km2(part)
            if km2 <= SNAP_KM2:
                close = acc_tree.query(part.buffer(0.02), predicate="intersects")
                if len(close):
                    best = max(close, key=lambda k: inter(accepted[k]["geom"], part.buffer(0.02)).area)
                    snap[best].append(part)
                    continue
            hits = utree.query(part, predicate="intersects")
            pieces = [(i, polys(inter(part, ug[i]))) for i in hits]
            pieces = [(i, p) for i, p in pieces if p is not None]
            rest = polys(diff(part, union([ug[i] for i, _ in pieces]))) if pieces else part
            for i, p in pieces:
                by_unit[i].append(p)
            if rest is not None and rest.area > 1e-6:
                fb = [i for i, u in enumerate(units) if u["country_name"] == UNCOVERED.get(date)
                      and u["geom"].distance(rest) < 0.5]  # only land next to that unit (not Arabia)
                by_unit[fb[0] if fb else utree.nearest(rest.representative_point())].append(rest)
    for k, parts in snap.items():
        accepted[k] = dict(accepted[k], geom=polys(union([accepted[k]["geom"]] + parts)))
    out = []
    for i, parts in by_unit.items():
        g = opening(polys(union(parts)))
        if g is None or eq_area_km2(g) < 50:
            continue
        u = units[i]
        en, z = namer(u["country_name"], u["status"], year)
        out.append(dict(uid=f"CSH-{u['fid']}", name=en or u["country_name"], name_zh=z, name_en=en, tier=5, prio=0,
                        geom=g, source="CShapes 2.0 outline of the whole country or colony on this date (no "
                        "subdivision layer available)", basis="historical_unit", kind=u["status"], start=u["start"],
                        end=u["end"], partial=False, cshapes_fid=u["fid"]))
    for iu, parts in by_island.items():
        g = polys(union(parts))
        out.append(dict(uid=f"ISL{iu[0]}", name=iu[1], name_zh=iu[2], name_en=iu[1], tier=6, prio=0, geom=g,
                        source="Territory not drawn by CShapes 2.0; land outline from geoBoundaries",
                        basis="historical_unit", kind=iu[3], start=None, end=None, partial=False))
    return accepted + out


def parents(units, cands, date):
    """Nearest coarser historical unit containing each unit's label point."""
    by_tier = {t: [c for c in cands if c["tier"] == t and active(c, date)] for t in (2, 3, 4)}
    trees = {t: STRtree([c["geom"] for c in cs]) for t, cs in by_tier.items() if cs}
    for u in units:
        u["parent"] = u["parent_zh"] = u["grandparent"] = u["parent_tier"] = u["grandparent_tier"] = None
        if u["tier"] >= 4:
            continue
        rp = u["geom"].representative_point()
        found = []
        for t in (2, 3, 4):
            if t <= u["tier"] or t not in trees:
                continue
            hit = [i for i in trees[t].query(rp, predicate="within")]
            if hit:  # the unit carve() would have kept: preferred source, newest, smallest
                found.append(by_tier[t][min(hit, key=lambda i: carve_order(by_tier[t][i]))])
        if found:
            u["parent"], u["parent_zh"], u["parent_tier"] = found[0]["name"], found[0].get("name_zh"), found[0]["tier"]
            if len(found) > 1:
                u["grandparent"], u["grandparent_tier"] = found[1]["name"], found[1]["tier"]
        elif u.get("parent_hint"):
            u["parent"] = u["parent_hint"]


def load_inputs():
    arcs, gs = topo.load(RAW / "cshapes_2_gw.topojson")
    cshapes = [dict(g["properties"], geom=topo.to_shape(arcs, g)) for g in gs]
    cands = (us_counties() + taiwan() + korea() + burma() + east_asia() + from_present_day() + ohm()
             + russia_1897(cshapes))
    for c in cands:
        if not c["geom"].is_valid:
            c["geom"] = polys(fix_rings(c["geom"]))
        c["area"] = c["geom"].area
        c["area_km2"] = eq_area_km2(c["geom"])
    print("candidate units:", len(cands), pd.Series([c["basis"] for c in cands]).value_counts().to_dict(), flush=True)
    refs = pd.read_csv(REF_WORK / "ref_units.csv", low_memory=False).to_dict("records")
    rgeom = {f["properties"]["ref_id"]: shape(f["geometry"]) for f in json.load(open(REF_WORK / "ref_units.geojson"))["features"]}
    for r in refs:
        r["geom"] = rgeom[r["ref_id"]]
    return cands, refs, cshapes


def partition(date, cands, refs, cshapes, namer):
    """All units of one date: the historical units laid down, the rest of the land, parents."""
    units = [u for u in cshapes if u["start"] <= date <= u["end"]]
    acc = carve(cands, date)
    allu = remainder(acc, refs, units, date, namer)
    parents(allu, cands, date)
    print(date, "units:", len(allu), pd.Series([u["tier"] for u in allu]).value_counts().sort_index().to_dict(),
          flush=True)
    return allu


def write(per_date):
    final = {}
    for date, allu in per_date:
        for u in allu:
            h = hashlib.md5(wkb.dumps(u["geom"])).hexdigest()[:8]
            # a unit whose parent changes between dates (a county of a province that ends) is a new version
            key = (u["uid"], h, u.get("parent"), u.get("grandparent"))
            if key in final:
                final[key]["dates"].append(date)
            else:
                final[key] = dict(u, dates=[date], geom_hash=h)
    # one id per distinct unit; versions of one unit that differ between dates get a suffix
    versions = defaultdict(list)
    for key, u in final.items():
        versions[u["uid"]].append(u)
    rows = []
    for uid, vs in versions.items():
        for k, u in enumerate(sorted(vs, key=lambda u: u["dates"][0])):
            u["unit_id"] = uid if len(vs) == 1 else f"{uid}#{k + 1}"
            rp = u["geom"].representative_point()
            rows.append(u | dict(label_lon=round(rp.x, 4), label_lat=round(rp.y, 4),
                                 area_km2=round(eq_area_km2(u["geom"]), 2), snapshots="|".join(u["dates"]),
                                 tier_zh=TIER_ZH[u["tier"]], tier_en=TIER_EN[u["tier"]]))
    cols = ["unit_id", "name", "name_zh", "name_en", "tier", "tier_zh", "tier_en", "kind", "basis", "source", "note",
            "start", "end", "partial", "parent", "parent_zh", "grandparent", "parent_tier", "grandparent_tier", "ohm_level",
            "wikidata", "cshapes_fid", "snapshots", "area_km2", "label_lon", "label_lat"]
    df = pd.DataFrame([{c: r.get(c) for c in cols} for r in rows])
    df.to_csv(WW2_WORK / "hist_units.csv", index=False)
    with open(WW2_WORK / "hist_units.geojson", "w") as f:
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"unit_id": r["unit_id"]}, "geometry": mapping(r["geom"])}
            for r in rows]}, f)
    print("distinct units:", len(df))
    print(df.groupby("tier_en").size())


def main(args):
    """  ww2_histunits.py [DATE ...]       all dates (or those given) in one process
      ww2_histunits.py --part DATE      one date, saved to work/<set>/hist_part_<DATE>.pkl
      ww2_histunits.py --merge          write the outputs from the saved parts of all dates"""
    if args[:1] == ["--merge"]:
        write([(d, pickle.load(open(WW2_WORK / f"hist_part_{d}.pkl", "rb"))) for d in DATES])
        return
    cands, refs, cshapes = load_inputs()
    namer = Namer()
    if args[:1] == ["--part"]:
        allu = partition(args[1], cands, refs, cshapes, namer)
        pickle.dump(allu, open(WW2_WORK / f"hist_part_{args[1]}.pkl", "wb"))
        return
    write([(d, partition(d, cands, refs, cshapes, namer)) for d in (args or DATES)])


if __name__ == "__main__":
    main(sys.argv[1:])
