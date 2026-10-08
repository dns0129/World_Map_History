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
    coast_deg: float = 0            # masks of present-day regions reach this far out to sea (degrees), for
                                    # historical coasts drawn further out than the present-day ones
    min_piece_km2: float = 0        # pieces smaller than this are merged into a neighbour (add_snapshots.absorb)
    client_states: bool = False     # control view: client states (Manchukuo, Mengjiang, ...) and Vichy France as
                                    # countries of their own, as on the 1939-45 dates (ww2_webmap.country_key)
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

# 1942 month by month, from the divisions and control of 1942-11-01 (the greatest Axis extent). Every control of
# that date that does not come from CShapes or a whole-unit event (the curated rules and the East Asia layers) is
# carried over piece by piece; curated/ww2_1942_region_control.csv then says what was different on each date.
# Blocs as on the 1939-45 dates (ww2_snapshots.WW2_BLOCS): Ethiopia and Iraq with the Allies, as on 1942-11-01.
_ALLIED42 = {200, 20, 900, 920, 560, 750, 290, 210, 211, 212, 385, 710, -1, -2, -4, 2, 365, 345, 350,
             40, 41, 42, 90, 91, 92, 93, 94, 95, 530, 645}   # Cuba to Panama declared war in December 1941
_AXIS42 = {255, 325, 740, 317, -10, -12, 310, 360, 355, 375}
_NOTE42 = "前线与占领区按整省、整区近似（斜线）；中国战场沿用 1942 年日占区与中共根据地范围，浙赣战役等短期进退未单列。"
_CHECKS42 = dict(places=[("Berlin", 13.4, 52.52, 255), ("Moscow", 37.62, 55.75, 365), ("Chongqing", 106.55, 29.56, 710)])
WW2_1942 = Group(
    key="m42", set="ww2", base="1942-11-01", rules="ww2_1942_region_control.csv", cities="ww2_cities.csv",
    client_states=True, min_piece_km2=30, coast_deg=0.1, label="1942 monthly", period="1942",
    inherit=("overlay:ccp_bases_1941_42", "overlay:indochina_ceded", "overlay:kwantung", "overlay:manchukuo",
             "overlay:mengjiang", "overlay:occupied_zone_1942", "rule:2", "rule:5", "rule:8", "rule:9", "rule:10",
             "rule:11", "rule:12", "rule:14", "rule:15", "rule:21", "rule:22", "rule:23", "rule:29", "rule:30",
             "rule:32", "rule:33", "rule:34", "rule:35", "rule:36", "rule:43", "rule:44", "rule:45", "rule:46",
             "rule:48", "rule:50", "rule:52", "rule:54", "rule:55", "rule:59", "rule:60", "rule:61", "rule:63",
             "rule:67", "rule:68", "rule:70", "rule:71", "rule:72", "rule:75", "rule:76", "rule:78", "rule:79",
             "rule:97", "rule:98", "rule:99", "rule:100", "rule:101", "rule:102"),
    pop_method=("Province population pattern of 1942-11-01 (GHS-POP 1975 shares of the 1939-45 database), "
                "area-adjusted for new pieces and scaled to each political unit's 1942 population in "
                "world_history_1900_2000.sqlite; rounded with conserved unit totals"),
    control_note="控制沿用 1942-11-01 的分区规则与东亚图层，再按各月的战局改写。" + _NOTE42,
    bloc_names={"allied": "同盟国一方", "axis": "轴心国一方", "neutral": "中立 / 维希", "contested": "前线争夺"},
    bloc_title="实际控制阵营 · 人口",
    # the short names of the 1939-45 dates (ww2_snapshots.STATE)
    names={255: ("Germany", "德国"), 325: ("Italy", "意大利"), 740: ("Japan", "日本"), 365: ("Soviet Union", "苏联"),
           200: ("United Kingdom", "英国"), 2: ("United States", "美国"), 220: ("France", "法国"),
           710: ("Republic of China", "中华民国"), 310: ("Hungary", "匈牙利"), 360: ("Romania", "罗马尼亚"),
           355: ("Bulgaria", "保加利亚"), 375: ("Finland", "芬兰"), 800: ("Thailand", "泰国"),
           317: ("Slovakia", "斯洛伐克"), 210: ("Netherlands", "荷兰"), 211: ("Belgium", "比利时"),
           235: ("Portugal", "葡萄牙"), 230: ("Spain", "西班牙"), 900: ("Australia", "澳大利亚"),
           339: ("Albania", "阿尔巴尼亚"), 290: ("Poland", "波兰"), 345: ("Yugoslavia", "南斯拉夫"),
           350: ("Greece", "希腊"), 560: ("South Africa", "南非"), 20: ("Canada", "加拿大"), 920: ("New Zealand", "新西兰"),
           -1: ("Allied powers", "同盟国"), -10: ("Axis powers", "轴心国"),
           -12: ("Independent State of Croatia", "克罗地亚独立国"), -20: ("Front line (contested)", "前线（双方争夺）"),
           -2: ("Chinese Communist Party", "中国共产党"), -30: ("Tuvan People's Republic", "图瓦人民共和国"),
           -4: ("Free France", "自由法国"),
           -5: ("French North and West Africa (Darlan)", "法属北非与西非（达尔朗）")},
    snapshots=[
        Snapshot(
            "1942-01-01", "《联合国家宣言》签署；日军进攻马来亚与菲律宾",
            "Declaration by United Nations; Japan advances in Malaya and the Philippines",
            allied=_ALLIED42, axis=_AXIS42, city_code="4201",
            bloc_note="1 月 1 日 26 国在华盛顿签署《联合国家宣言》。同盟国一方含英联邦、苏联、美国、中华民国、自由法国、各流亡政府，"
                      "以及 1941 年 12 月对轴心国宣战的古巴、海地、多米尼加和中美洲各国。泰国 1941 年 12 月 21 日与日本结盟，"
                      "1 月 25 日才对英美宣战，此时计入中立。",
            control_note="苏军冬季反攻：莫斯科州西部、图拉州南部、加里宁、卡卢加仍在争夺；刻赤半岛已被苏军收复，塞瓦斯托波尔被围。"
                         "英军十字军行动后收复昔兰尼加。日军已占吕宋大部、马来亚北部、槟城、沙捞越、香港、关岛。" + _NOTE42,
            checks=dict(blocs={800: "neutral", 70: "neutral"}, places=_CHECKS42["places"] + [("Benghazi", 20.07, 32.12, 200)])),
        Snapshot(
            "1942-02-01", "日军逼近新加坡，隆美尔重夺班加西", "Japan nears Singapore; Rommel retakes Benghazi",
            allied=_ALLIED42, axis=_AXIS42 | {800}, city_code="4202",
            bloc_note="泰国 1 月 25 日对英美宣战，计入轴心国一方。墨西哥（5 月）、巴西（8 月）尚未参战。",
            control_note="英军 1 月 31 日撤入新加坡岛，马来半岛全境为日军占领；日军攻占缅甸丹那沙林、婆罗洲东岸与北苏拉威西、"
                         "拉包尔。苏军巴尔文科沃突出部（哈尔科夫以南）与杰米扬斯克一带激战；北非轴心国军重占班加西。" + _NOTE42,
            checks=dict(blocs={800: "axis"})),
        Snapshot(
            "1942-03-01", "新加坡陷落后，日军登陆爪哇", "After the fall of Singapore: Japanese landings on Java",
            allied=_ALLIED42, axis=_AXIS42 | {800}, city_code="4203",
            bloc_note="泰国计入轴心国一方。墨西哥、巴西尚未参战。",
            control_note="新加坡 2 月 15 日陷落；日军已占婆罗洲、苏拉威西、摩鹿加、巴厘、帝汶与苏门答腊南部，3 月 1 日登陆爪哇（交战）；"
                         "缅甸日军渡过锡当河，仰光、勃固为交战区。北非两军对峙于加查拉防线。" + _NOTE42),
        Snapshot(
            "1942-04-01", "日军占领荷属东印度与下缅甸", "Japan holds the Dutch East Indies and Lower Burma",
            allied=_ALLIED42, axis=_AXIS42 | {800}, city_code="4204",
            bloc_note="泰国计入轴心国一方。墨西哥、巴西尚未参战。",
            control_note="荷属东印度 3 月 8 日投降；仰光 3 月 8 日、同古 3 月 30 日失守；日军 3 月 23 日占领安达曼群岛，3 月占莱城、"
                         "萨拉马瓦。菲律宾巴丹半岛仍在抵抗。" + _NOTE42),
        Snapshot(
            "1942-05-01", "巴丹失守，日军攻占曼德勒", "After Bataan: Japan takes Mandalay",
            allied=_ALLIED42, axis=_AXIS42 | {800}, city_code="4205",
            bloc_note="泰国计入轴心国一方。墨西哥 5 月 22 日才参战。",
            control_note="巴丹 4 月 9 日投降，科雷希多尔仍在坚守；日军登陆宿务、班乃与棉兰老；缅甸腊戍、曼德勒失守，英中军向钦敦江撤退。"
                         "刻赤半岛与巴尔文科沃突出部仍为苏军控制。" + _NOTE42),
        Snapshot(
            "1942-06-01", "第二次哈尔科夫战役之后，加查拉激战", "After the Second Battle of Kharkov; the Battle of Gazala",
            allied=_ALLIED42 | {70}, axis=_AXIS42 | {800}, city_code="4206",
            bloc_note="墨西哥 5 月 22 日对德意日宣战，计入同盟国一方；泰国计入轴心国一方。巴西尚未参战。",
            control_note="德军 5 月收复刻赤半岛、歼灭巴尔文科沃突出部，塞瓦斯托波尔被围；加查拉战役进行中（托布鲁克一带为交战区）；"
                         "菲律宾、缅甸全境失守；英军 5 月占领马达加斯加北端迭戈苏亚雷斯；泰国军队进入景栋。" + _NOTE42),
        Snapshot(
            "1942-07-01", "德军发动“蓝色行动”，非洲军团抵阿拉曼", "Case Blue begins; the Afrika Korps at El Alamein",
            allied=_ALLIED42 | {70}, axis=_AXIS42 | {800}, city_code="4207",
            bloc_note="墨西哥计入同盟国一方，泰国计入轴心国一方。巴西尚未参战。",
            control_note="德军 6 月 28 日向沃罗涅日、顿河发动夏季攻势，塞瓦斯托波尔最后的战斗；托布鲁克 6 月 21 日失守，轴心国军进入埃及"
                         "马特鲁省，止于阿拉曼。日军 5 月占领图拉吉。" + _NOTE42),
        Snapshot(
            "1942-08-01", "德军突入顿河大弯曲部与库班", "The Germans in the Don bend and the Kuban",
            allied=_ALLIED42 | {70}, axis=_AXIS42 | {800}, city_code="4208",
            bloc_note="墨西哥计入同盟国一方，泰国计入轴心国一方。巴西 8 月 22 日才参战。",
            control_note="罗斯托夫 7 月 24 日失守，A 集团军群进入库班与斯塔夫罗波尔，B 集团军群在顿河大弯曲部逼近斯大林格勒；"
                         "日军在新几内亚布纳登陆（7 月 21 日），在瓜达尔卡纳尔岛修建机场。" + _NOTE42),
        Snapshot(
            "1942-09-01", "斯大林格勒与瓜达尔卡纳尔岛的争夺", "The battles of Stalingrad and Guadalcanal",
            allied=_ALLIED42 | {70, 140}, axis=_AXIS42 | {800}, city_code="4209",
            bloc_note="巴西 8 月 22 日对德意宣战，计入同盟国一方；墨西哥计入同盟国一方，泰国计入轴心国一方。",
            control_note="德军 8 月 23 日抵伏尔加河，斯大林格勒为交战区；克拉斯诺达尔、迈科普失守，前线到捷列克河；美军 8 月 7 日登陆瓜达尔卡纳尔岛；"
                         "日军 8 月 26 日占领瑙鲁。" + _NOTE42),
        Snapshot(
            "1942-10-01", "斯大林格勒巷战，英军推进马达加斯加", "Street fighting in Stalingrad; the British advance in Madagascar",
            allied=_ALLIED42 | {70, 140}, axis=_AXIS42 | {800}, city_code="4210",
            bloc_note="墨西哥、巴西计入同盟国一方，泰国计入轴心国一方。",
            control_note="斯大林格勒巷战；高加索前线在捷列克河与图阿普谢以北；英军 9 月占领马达加斯加的马任加、塔马塔夫、塔那那利佛，"
                         "向南推进。阿拉曼两军对峙。" + _NOTE42),
        Snapshot(
            "1942-12-01", "“火炬”与“天王星”行动之后", "After Operation Torch and Operation Uranus",
            allied=_ALLIED42 | {70, 140, -5}, axis=_AXIS42 | {800}, city_code="4212",
            bloc_note="法属北非与西非在达尔朗与盟国的协议（11 月 22 日）后倒向同盟国，单列；留尼汪 11 月 28 日加入自由法国。"
                      "墨西哥、巴西计入同盟国一方，泰国计入轴心国一方。",
            control_note="德意 11 月 11 日占领维希法国本土（意军占罗讷河以东与科西嘉）；盟军登陆摩洛哥、阿尔及利亚后向突尼斯推进，"
                         "轴心国军据守突尼斯东北部；英军收复昔兰尼加；苏军 11 月 23 日合围斯大林格勒的德军第六集团军（城区仍为交战区）。"
                         + _NOTE42,
            checks=dict(blocs={-5: "allied"}, places=_CHECKS42["places"] + [("Algiers", 3.06, 36.75, -5),
                                                                              ("Tunis", 10.18, 36.8, -10)])),
    ],
)

GROUPS = [WW1, WW2_1942]

SNAPSHOTS_ADDED = sorted((s.date, s.title_zh, s.title_en) for g in GROUPS for s in g.snapshots)
