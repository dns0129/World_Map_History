"""Dates added to a set's database and map data without rebuilding the set (add_snapshots.py).

A group adds dates to the database of one set (ww2 1939-45, early 1900-34, postwar 1946-91). Its dates reuse
the historical divisions of one date already in that database (the base date): the divisions in force on the
base date that are still in force on the new date, plus those of the database with a start or end date
between the two. Political units come from CShapes on the new date, population from the yearly database.
Everything that is particular to a date is written here, so that adding a date means adding a Snapshot (and
its control rules and cities), not changing the scripts.

This module holds data only: the pipeline fingerprints the scripts that import it, so editing it reruns only
add_snapshots.py and ww2_html.py, not the build of the sets.
"""
from dataclasses import dataclass, field


@dataclass
class Snapshot:
    date: str                       # YYYY-MM-DD, the exact day
    title_zh: str
    title_en: str
    allied: set                     # controller codes (gwcode, or the group's negative codes) in each bloc;
    axis: set                       # -20 is always "contested", all others are "neutral"
    bloc_note: str                  # legend: who is in which bloc, who is not yet (Chinese)
    city_code: str                  # the date's code in the dates/capital/seat columns of the group's city table
    bloc_names: dict = None         # legend names of the four blocs; the group's when None
    bloc_title: str = None          # legend heading; the group's when None
    control_note: str = None        # legend: the de facto control; the group's when None
    names: dict = field(default_factory=dict)   # controller names on this date only {gw: (en, zh)}; the
                                                # political units with that gwcode take the name too
    checks: dict = field(default_factory=dict)  # what verify_added_snapshots.py checks on this date:
    #   blocs {gw: bloc}; places [(name, lon, lat, gw)]: the one piece at the point is held by gw;
    #   cities_in / cities_out [name_zh]: shown / not shown; controller_zh {gw: {names}}: all the names gw has


@dataclass
class Group:
    key: str                        # prefix of what the group adds: pieces "KEY:date:...", divisions for land
                                    # without provinces "KEY-CSH-<unit>", control_rules rows "key:<row>",
                                    # sources "key-control-<n>"; must not change once built
    set: str                        # ww2 / early / postwar
    base: str                       # the date whose divisions are reused
    rules: str                      # curated/<rules>: the group's control rules (see add_snapshots.py)
    cities: str                     # curated/<cities>: city table of the set
    pop_method: str                 # pop_methods row of the database
    control_note: str               # legend default for its dates
    bloc_names: dict
    bloc_title: str
    snapshots: list
    density_from: tuple = ()        # dates whose province densities weigh the new pieces where the base date
                                    # has none (the base date's own come first)
    inherit: tuple = ()             # control sources of the base date carried over to every date, piece by
                                    # piece (enclaves curated for the base date; rule:<row> numbers of the set's
                                    # rules table)
    keep_whole: tuple = ()          # control sources of the base date kept for the whole division
    names: dict = field(default_factory=dict)   # controllers without a state of their own {gw: (en, zh)}
    meta_key: str = None            # meta rows <meta_key>_method, <meta_key>_control; key when None
    label: str = None               # sources: "<label> control reference"; key when None
    period: str = ""                # sources: "<period> event-day control facts"


WW1 = Group(
    key="ww1", set="early", base="1914-08-04", rules="ww1_region_control.csv", cities="cities_1900_1934.csv",
    density_from=("1918-11-11",), inherit=("rule:8", "rule:9", "rule:69", "overlay:kwantung"),
    keep_whole=("overlay:kwantung",), meta_key="wwi", label="WWI", period="1915-1917",
    pop_method=("1914 historical province population density (original GHS-POP-derived estimates), "
                "or the existing 1918 estimate where no 1914 province exists; "
                "area-adjusted for new pieces and scaled to the same political unit's annual "
                "population in world_history_1900_2000.sqlite; rounded with conserved unit totals"),
    control_note=("控制区沿用原地图的省级近似方法。西线、加利西亚、非洲战场等没有精确战线资料的省份标为交战区；"
                  "部分占领范围借用同一数据库的现代地区轮廓作近似裁切，并加斜线，不代表精确战线。"
                  "人口为该年估计，并非事件日普查。历史区划缺失处保留整个政治单元。"),
    bloc_names={"allied": "协约国及其盟国（已参战）", "axis": "同盟国（已参战）", "neutral": "中立国 / 尚未参战",
                "contested": "交战区"},
    bloc_title="参战国 · 人口",
    names={-1: ("Allied forces", "协约国联军"), -20: ("Contested front", "交战区（双方争夺）"),
           -70: ("Kingdom of Hejaz", "汉志王国"), -73: ("Outer Mongolia (Bogd Khanate)", "外蒙古（博克多汗国）"),
           -76: ("Greek Provisional Government of National Defence", "希腊国民防卫临时政府")},
    snapshots=[
        Snapshot(
            "1915-05-23", "意大利对奥匈帝国宣战，加入协约国", "Italy declares war on Austria-Hungary",
            allied={200, 220, 365, 340, 345, 341, 211, 20, 900, 920, 560, 740, 325, -1},
            axis={255, 300, 640}, city_code="15",
            bloc_note="意大利当日对奥匈宣战（战争状态次日生效），尚未对德国宣战；日本、黑山和奥斯曼已经参战，保加利亚、罗马尼亚、"
                      "葡萄牙、美国、中国、希腊仍中立。东线在戈尔利采攻势期间，不能套用 1915 年秋的占领范围。",
            checks=dict(blocs={325: "allied", 255: "axis", 300: "axis", 710: "neutral", 2: "neutral", 355: "neutral",
                               235: "neutral"},
                        places=[("Paris", 2.35, 48.86, 220), ("Berlin", 13.4, 52.52, 255), ("Beijing", 116.4, 39.9, 710),
                                ("Riga", 24.11, 56.95, 365), ("Basra", 47.78, 30.51, 200),
                                ("Istanbul", 28.97, 41.04, 640), ("Warsaw", 21.01, 52.23, 365)],
                        cities_in=["彼得格勒"], cities_out=["圣彼得堡"])),
        Snapshot(
            "1916-08-27", "罗马尼亚对奥匈帝国宣战，加入协约国", "Romania declares war on Austria-Hungary",
            allied={200, 220, 365, 340, 345, 341, 211, 20, 900, 920, 560, 740, 325, -1, 235, 360, -70},
            axis={255, 300, 640, 355}, city_code="16",
            bloc_note="罗马尼亚当日对奥匈宣战；意大利当日另对德国宣战。葡萄牙已于 3 月参战，保加利亚属同盟国。美国、中国、希腊仍未"
                      "正式参战。罗马尼亚尚未遭到同盟国的冬季占领。",
            checks=dict(blocs={325: "allied", 255: "axis", 300: "axis", 710: "neutral", 2: "neutral", 355: "axis",
                               235: "allied"},
                        places=[("Paris", 2.35, 48.86, 220), ("Berlin", 13.4, 52.52, 255), ("Beijing", 116.4, 39.9, 710),
                                ("Riga", 24.11, 56.95, 365), ("Basra", 47.78, 30.51, 200),
                                ("Istanbul", 28.97, 41.04, 640), ("Warsaw", 21.01, 52.23, 255)],
                        cities_in=["彼得格勒"], cities_out=["圣彼得堡"])),
        Snapshot(
            "1917-04-06", "美国对德国宣战，加入第一次世界大战", "The United States declares war on Germany",
            allied={200, 220, 365, 340, 345, 341, 211, 20, 900, 920, 560, 740, 325, -1, 235, 360, 2, -70, -76},
            axis={255, 300, 640, 355}, city_code="17",
            names={365: ("Russia (Provisional Government)", "俄国（临时政府）")},
            bloc_note="美国当日对德国宣战（对奥匈宣战在 12 月）；俄国临时政府继续参加协约国战争。中国、巴西、暹罗尚未对德宣战，"
                      "希腊尚未统一参战；萨洛尼卡临时政府及协约国驻军另作近似处理。俄国此时尚未发生十月革命，也未签订布列斯特和约。",
            checks=dict(blocs={325: "allied", 255: "axis", 300: "axis", 710: "neutral", 2: "allied", 355: "axis",
                               235: "allied"},
                        places=[("Paris", 2.35, 48.86, 220), ("Berlin", 13.4, 52.52, 255), ("Beijing", 116.4, 39.9, 710),
                                ("Riga", 24.11, 56.95, 365), ("Basra", 47.78, 30.51, 200),
                                ("Istanbul", 28.97, 41.04, 640), ("Warsaw", 21.01, 52.23, 255),
                                ("Baghdad", 44.37, 33.32, 200)],
                        cities_in=["彼得格勒", "雅西"], cities_out=["圣彼得堡"],
                        controller_zh={365: {"俄国（临时政府）"}})),
    ],
)

GROUPS = [WW1]

SNAPSHOTS_ADDED = sorted((s.date, s.title_zh, s.title_en) for g in GROUPS for s in g.snapshots)
