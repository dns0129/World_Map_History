"""Important cities on the maps: capitals, seats of colonial or provisional governments,
industrial cities and ports.

  1939-1945  curated/ww2_cities.csv. The capital and seat columns say on which snapshot dates
             a city was the seat of which government ("*" = all six), so Paris is France's
             capital in 1939 and 1945 but not under occupation, Vichy from 1940 to 1944,
             Chongqing throughout the war.
  1900-1934  curated/cities_1900_1934.csv, the same columns plus `dates`: the snapshots a row
             is shown on, so a renamed city has one row per name (St Petersburg, Petrograd,
             Leningrad).
  2026       the national capitals of Natural Earth populated places, plus
             curated/cities_2026.csv (major industrial cities and ports).

Coordinates come from Natural Earth populated places when the city is found there by name
within 1.5 degrees of the curated position. Each city is
[name, lon, lat, flags, rank, role, note, population] with flags 1 capital, 2 seat of a
colonial / provisional government, 4 industrial, 8 port, 16 other major city; rank 0-2
decides from which zoom it is shown.
"""
import csv
import json
import math

from common import RAW, ROOT
from ww2_geo import norm

CODE = {"1939-09-01": "39", "1940-07-01": "40", "1941-12-07": "41", "1942-11-01": "42", "1944-06-06": "44",
        "1945-09-02": "45"}
EARLY_CODE = {"1900-08-14": "00", "1914-08-04": "14", "1918-11-11": "18", "1934-10-16": "34"}
KIND_FLAG = {"I": 4, "P": 8, "C": 16}
NAME_FIX = {"Washington,  D.C.": "华盛顿", "Washington, D.C.": "华盛顿"}
NOTE_2026 = {"Jerusalem": "以色列宣布的首都，其地位未获国际社会普遍承认",
             "Taipei": "台湾当局所在地", "Hargeisa": "索马里兰（未获普遍承认）首府", "Pristina": "科索沃首都（部分国家承认）"}

_places = None


def places():
    global _places
    if _places is None:
        _places = {}
        for f in json.load(open(RAW / "naturalearth" / "ne_10m_populated_places.geojson"))["features"]:
            p = f["properties"]
            for n in [p["NAME"], p["NAMEASCII"], *(p.get("NAMEALT") or "").split("|")]:
                if n:
                    _places.setdefault(norm(n), []).append(p)
    return _places


def locate(name_en, lon, lat):
    best = None
    for p in places().get(norm(name_en), []):
        d = math.hypot(p["LONGITUDE"] - lon, p["LATITUDE"] - lat)
        if d < 1.5 and (best is None or d < best[0]):
            best = (d, p)
    return best[1] if best else None


def roles(s, code):
    for part in (s or "").split(";"):
        if "=" not in part:
            continue
        snaps, polity = part.split("=", 1)
        if snaps.strip() == "*" or code in snaps.split():
            return polity.strip()
    return None


def ww2(snap):
    early = snap in EARLY_CODE
    code = EARLY_CODE[snap] if early else CODE[snap]
    out = []
    for r in csv.DictReader(open(ROOT / "curated" / ("cities_1900_1934.csv" if early else "ww2_cities.csv"))):
        if early and r["dates"] != "*" and code not in r["dates"].split():
            continue
        cap, seat = roles(r["capital"], code), roles(r["seat"], code)
        flags = sum(KIND_FLAG[k] for k in r["kinds"])
        if cap:
            flags |= 1
        if seat:
            flags |= 2
        if not flags:
            continue  # a seat of government only on other dates, nothing else
        rank = int(r["rank"])
        if cap:
            rank = min(rank, 1)
        p = locate(r["name_en"], float(r["lon"]), float(r["lat"]))
        lon, lat = (p["LONGITUDE"], p["LATITUDE"]) if p else (float(r["lon"]), float(r["lat"]))
        role = "；".join(x for x in [f"首都：{cap}" if cap else None, f"首府 / 政府驻地：{seat}" if seat else None] if x)
        out.append([r["name_zh"], round(lon, 3), round(lat, 3), flags, rank, role, r["note"] or None, None])
    return out


def y2026(country_zh):
    out = []
    caps = []
    for f in json.load(open(RAW / "naturalearth" / "ne_10m_populated_places.geojson"))["features"]:
        p = f["properties"]
        if p.get("ADM0CAP") == 1 and p["ADM0_A3"] != "ATA":
            caps.append(p)
    rows = list(csv.DictReader(open(ROOT / "curated" / "cities_2026.csv")))
    used = set()
    for p in caps:
        name = NAME_FIX.get(p["NAME"]) or p.get("NAME_ZH") or p["NAME"]
        flags, note, rank = 1, NOTE_2026.get(p["NAME"]), 0 if p["SCALERANK"] <= 1 else 1 if p["SCALERANK"] <= 3 else 2
        for i, r in enumerate(rows):
            if i not in used and math.hypot(float(r["lon"]) - p["LONGITUDE"], float(r["lat"]) - p["LATITUDE"]) < 0.4:
                used.add(i)
                flags |= sum(KIND_FLAG[k] for k in r["kinds"])
                note = note or r["note"] or None
        country = country_zh.get(p["ADM0_A3"]) or p["ADM0NAME"]
        out.append([name, round(p["LONGITUDE"], 3), round(p["LATITUDE"], 3), flags, rank, f"首都：{country}", note,
                    int(p["POP_MAX"]) if p.get("POP_MAX") else None])
    for i, r in enumerate(rows):
        if i in used:
            continue
        p = locate(r["name_en"], float(r["lon"]), float(r["lat"]))
        lon, lat = (p["LONGITUDE"], p["LATITUDE"]) if p else (float(r["lon"]), float(r["lat"]))
        out.append([r["name_zh"], round(lon, 3), round(lat, 3), sum(KIND_FLAG[k] for k in r["kinds"]), int(r["rank"]),
                    None, r["note"] or None, int(p["POP_MAX"]) if p and p.get("POP_MAX") else None])
    return out
