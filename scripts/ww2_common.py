"""Shared settings for the county-level historical database.

Three sets of snapshots go through the same scripts:
  ww2      1939-1945, six dates of the Second World War (the default)
  early    1900-1934, four dates before it
  postwar  1946-1991, six dates after it
Choose with the environment variable WW2_SET, e.g. `WW2_SET=early python3 ww2_histunits.py`.
Each set has its own work directory, control rules and database; the present-day reference
units (ww2_reference.py) are shared.
"""
import os
from pathlib import Path

from common import RAW, WORK, ROOT, DB_DIR

SET = os.environ.get("WW2_SET", "ww2")
assert SET in ("ww2", "early", "postwar"), SET
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
SNAPSHOTS_POSTWAR = [
    ("1946-06-26", "国共内战全面爆发（中原突围）", "Full-scale Chinese Civil War begins"),
    ("1947-08-15", "印度、巴基斯坦分治独立", "Partition and independence of India and Pakistan"),
    ("1948-09-12", "辽沈战役开始；朝鲜半岛南北分立", "Liaoshen campaign begins; two Korean states"),
    ("1949-10-01", "中华人民共和国成立", "Founding of the People's Republic of China"),
    ("1953-07-27", "朝鲜停战协定签署", "Korean Armistice Agreement"),
    ("1991-12-26", "苏联解体", "Dissolution of the Soviet Union"),
]
# Supplemental WWI dates are built from the shipped SQLite databases by ww1_maps.py.
# Keep the original raw-data pipeline's four dates separate so a full rebuild retains
# the same historical reference divisions before adding these snapshots.
SNAPSHOTS_WWI = [
    ("1915-05-23", "意大利对奥匈帝国宣战，加入协约国", "Italy declares war on Austria-Hungary"),
    ("1916-08-27", "罗马尼亚对奥匈帝国宣战，加入协约国", "Romania declares war on Austria-Hungary"),
    ("1917-04-06", "美国对德国宣战，加入第一次世界大战", "The United States declares war on Germany"),
]
SNAPSHOTS = {"early": SNAPSHOTS_EARLY, "postwar": SNAPSHOTS_POSTWAR}.get(SET, SNAPSHOTS_WW2)
SNAP_DATES = [s[0] for s in SNAPSHOTS]

if SET == "early":
    WW2_DB = DB_DIR / "divisions_1900_1934.sqlite"
    RULES = ROOT / "curated" / "region_control_1900_1934.csv"
elif SET == "postwar":
    WW2_DB = DB_DIR / "divisions_1946_1991.sqlite"
    RULES = ROOT / "curated" / "region_control_1946_1991.csv"
else:
    WW2_DB = DB_DIR / "ww2_divisions_1939_1945.sqlite"
    RULES = ROOT / "curated" / "ww2_region_control.csv"

# Land CShapes leaves blank on a date counts as part of this unit: on 11 November 1918, Latvia,
# renounced by Russia at Brest-Litovsk and not yet independent (18 November)
UNCOVERED = {"1918-11-11": "Russia (Soviet Union)"}
UNCOVERED_BOX = {"1918-11-11": (20.9, 55.6, 28.3, 58.1)}  # where that land lies (Latvia), lon/lat bounds

TYPICAL_COUNTY_KM2 = 1500.0  # target size used to pick each country's county level


def _cgroup_memory():
    """(limit, in use) in bytes of the memory cgroup of this process (v1 or v2; page cache that can be dropped
    is not counted as in use), or None when there is no limit."""
    try:
        for line in open("/proc/self/cgroup"):
            _, ctrl, path = line.rstrip("\n").split(":", 2)
            if ctrl == "memory":
                d, lim, use, stat = Path("/sys/fs/cgroup/memory") / path.lstrip("/"), "memory.limit_in_bytes", \
                    "memory.usage_in_bytes", "total_inactive_file"
            elif ctrl == "" and Path("/sys/fs/cgroup/memory.max").exists():
                d, lim, use, stat = Path("/sys/fs/cgroup") / path.lstrip("/"), "memory.max", "memory.current", \
                    "inactive_file"
            else:
                continue
            limit = (d / lim).read_text().strip()
            if limit == "max" or int(limit) >= 2 ** 60:
                return None
            st = dict(x.split() for x in (d / "memory.stat").read_text().splitlines())
            return int(limit), int((d / use).read_text()) - int(st.get(stat, 0))
    except (OSError, ValueError):
        pass
    return None


def memory_limit_gb():
    """Memory this process and its children may use in all: the cgroup limit, else the machine's memory."""
    cg = _cgroup_memory()
    if cg:
        return cg[0] / 2 ** 30
    kb = next(int(line.split()[1]) for line in open("/proc/meminfo") if line.startswith("MemTotal"))
    return kb / 2 ** 20


def memory_free_gb():
    """Memory that can still be taken now: what the machine has available, and no more than the cgroup allows
    (the cgroup limit can be lower than the machine's memory; the kernel kills a process that goes past it)."""
    kb = next(int(line.split()[1]) for line in open("/proc/meminfo") if line.startswith("MemAvailable"))
    free = kb / 2 ** 20
    cg = _cgroup_memory()
    if cg:
        free = min(free, (cg[0] - cg[1]) / 2 ** 30)
    return free


def workers(n, gb_each):
    """Worker processes for n independent jobs that each hold about gb_each GB: as many as the memory free now
    allows (one GB kept free), at most n; WW2_POOL fixes the number instead."""
    if os.environ.get("WW2_POOL"):
        return max(1, min(n, int(os.environ["WW2_POOL"])))
    try:
        return max(1, min(n, int((memory_free_gb() - 1) / gb_each)))
    except (OSError, StopIteration):
        return 1


def memory_gb():
    """(current, peak) resident memory of this process in GB, for the progress lines of the long steps."""
    try:
        st = dict(line.split(":", 1) for line in open("/proc/self/status"))
        return int(st["VmRSS"].split()[0]) / 2 ** 20, int(st["VmHWM"].split()[0]) / 2 ** 20
    except (OSError, KeyError):
        return 0.0, 0.0


if __name__ == "__main__":
    # `python3 ww2_common.py jobs N GB` prints how many of N jobs of GB each to run at once (for xargs -P)
    import sys
    if sys.argv[1:2] == ["jobs"]:
        print(workers(int(sys.argv[2]), float(sys.argv[3])))
