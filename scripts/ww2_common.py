"""Shared settings for the county-level historical database.

Two sets of snapshots go through the same scripts:
  ww2    1939-1945, six dates of the Second World War (the default)
  early  1900-1934, four dates before it
Choose with the environment variable WW2_SET, e.g. `WW2_SET=early python3 ww2_histunits.py`.
Each set has its own work directory, control rules and database; the present-day reference
units (ww2_reference.py) are shared.
"""
import os

from common import RAW, WORK, ROOT, DB_DIR

SET = os.environ.get("WW2_SET", "ww2")
assert SET in ("ww2", "early"), SET
WW2_RAW = RAW / "ww2"
GB = RAW / "geoboundaries"
REF_WORK = WORK / "ww2"            # present-day reference units, shared by both sets
WW2_WORK = WORK / SET
WW2_OUT = ROOT / "ww2"
WW2_WORK.mkdir(parents=True, exist_ok=True)
WW2_OUT.mkdir(parents=True, exist_ok=True)

# Exact dates, not mid-year.
SNAPSHOTS_WW2 = [
    ("1939-09-01", "德国入侵波兰，第二次世界大战在欧洲爆发", "Germany invades Poland"),
    ("1940-07-01", "法国停战后，德国控制西欧", "After the fall of France"),
    ("1941-12-07", "珍珠港事件当日，德军止步莫斯科城下", "Pearl Harbor; Germans before Moscow"),
    ("1942-11-01", "轴心国扩张的最大范围（阿拉曼、斯大林格勒之前）", "Greatest Axis extent"),
    ("1944-06-06", "诺曼底登陆日", "D-Day"),
    ("1945-09-02", "日本签署投降书，战争结束", "Japan signs the surrender"),
]
SNAPSHOTS_EARLY = [
    ("1900-08-14", "八国联军攻入北京", "The Eight-Nation Alliance enters Beijing"),
    ("1914-08-04", "英国对德宣战，第一次世界大战全面爆发", "Britain declares war on Germany"),
    ("1918-11-11", "贡比涅停战协定生效，第一次世界大战结束", "The Armistice of Compiègne"),
    ("1934-10-16", "中央红军开始长征", "The Long March begins"),
]
SNAPSHOTS = SNAPSHOTS_EARLY if SET == "early" else SNAPSHOTS_WW2
SNAP_DATES = [s[0] for s in SNAPSHOTS]

if SET == "early":
    WW2_DB = DB_DIR / "divisions_1900_1934.sqlite"
    RULES = ROOT / "curated" / "region_control_1900_1934.csv"
else:
    WW2_DB = DB_DIR / "ww2_divisions_1939_1945.sqlite"
    RULES = ROOT / "curated" / "ww2_region_control.csv"

# Land CShapes leaves blank on a date counts as part of this unit: on 11 November 1918, Latvia,
# renounced by Russia at Brest-Litovsk and not yet independent (18 November)
UNCOVERED = {"1918-11-11": "Russia (Soviet Union)"}
UNCOVERED_BOX = {"1918-11-11": (20.9, 55.6, 28.3, 58.1)}  # where that land lies (Latvia), lon/lat bounds

TYPICAL_COUNTY_KM2 = 1500.0  # target size used to pick each country's county level
