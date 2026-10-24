"""Controllers of the event dates of the province sets (path B) as data, and the one bloc rule of both paths.

Names: the short names of the controllers that appear on the dates (STATE, 1939-45), the controllers without a state
of their own on the 1900-34 and 1946-91 dates (EARLY_STATE, POSTWAR_STATE; other states take the name the period
used, build_database.Namer) and the states named on one date only (*_STATE_ON); names_on(set, date) combines them.
Blocs: who is in which bloc on each date (*_BLOCS), and the controllers whose bloc depends on what they are rather
than who they are (DETAIL_BLOCS: Vichy France, the Southeast Mutual Protection provinces of 1900, Manchukuo, the
Russia of 26 December 1991). bloc() is the rule of path B (ww2_snapshots.py) and of path A (add_snapshots.py, whose
dates list their blocs in added_dates.py).
MANCHU_ROC, UNIT_FIX: Manchukuo before its own provinces; political units whose CShapes status misdescribes them.
"""

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

# Bloc of each controller on each date (simplified; neutral otherwise), by date so that a date can be added
# anywhere in the list; colonies follow their sovereign (the controller).
#   Britain, France, the Dominions, Poland, China and the governments in exile from 1939 (France again
#   from 1944); the Soviet Union, the United States, Yugoslavia and Greece from 1941; Latin America and
#   others as they declared war; Italy (here the Italian Social Republic in 1944) with the Axis until its
#   surrender, Romania and Bulgaria with the Allies in 1945
_AXIS39 = {255, 325, 740, 317, -10}
_ALLIED39 = {200, 20, 900, 920, 560, 750, 290, 210, 211, 212, 385, 710, -1, -2, -4}
_AXIS41 = _AXIS39 | {-12, 310, 360, 355, 375}
_ALLIED41 = _ALLIED39 | {2, 365, 345, 350}
_LATAM42 = {40, 41, 42, 70, 90, 91, 92, 93, 94, 95, 140, 530, 645}
_ALLIED44 = _ALLIED41 | _LATAM42 | {220, 100, 145, 450, 630}
WW2_BLOCS = {
    "1939-09-01": dict(allied=_ALLIED39 | {220}, axis=_AXIS39),
    "1940-07-01": dict(allied=_ALLIED39, axis=_AXIS39 | {-12}),
    "1941-12-07": dict(allied=_ALLIED41, axis=_AXIS41),
    "1942-11-01": dict(allied=_ALLIED41 | _LATAM42, axis=_AXIS41 | {800}),
    "1944-06-06": dict(allied=_ALLIED44, axis=_AXIS41 | {800}),
    "1945-09-02": dict(allied=_ALLIED44 | {101, 130, 135, 150, 155, 160, 165, 355, 360, 390, 640, 651, 652, 660, 663,
                                           670, 712},
                       axis={255, 740, -10}),
}
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

BASE_NAMES = {"ww2": STATE, "early": EARLY_STATE, "postwar": POSTWAR_STATE}
NAMES_ON = {"ww2": {}, "early": EARLY_STATE_ON, "postwar": POSTWAR_STATE_ON}
BLOCS = {"ww2": WW2_BLOCS, "early": EARLY_BLOCS, "postwar": POSTWAR_BLOCS}
# (dates or None for all, controller or None for any, test, text, bloc), tried in order before the members of the
# blocs; the test ("contains", "startswith" or "lacks") is on the controller's detail (the controlling regime)
DETAIL_BLOCS = {
    "ww2": [(None, None, "contains", "Vichy", "neutral")],
    "early": [(("1900-08-14",), 710, "contains", "Mutual Protection", "neutral"),
              (None, 740, "startswith", "Manchukuo", "axis")],
    "postwar": [(("1991-12-26",), 365, "lacks", "Soviet", "axis")],
}


def names_on(set_, snap):
    """Controller names for one date: the set's names, then the states named for that date only."""
    return {**BASE_NAMES[set_], **NAMES_ON[set_].get(snap, {})}


def _holds(test, text, detail):
    if not detail:
        return False
    if test == "contains":
        return text in detail
    if test == "startswith":
        return detail.startswith(text)
    return text not in detail


def bloc(gw, allied, axis, detail=None, rules=(), snap=None):
    """The bloc of controller gw: contested for the front line, then the first detail rule that holds, then its
    membership (allied, axis, otherwise neutral)."""
    if gw in CONTESTED:
        return "contested"
    for dates, who, test, text, b in rules:
        if (dates is None or snap in dates) and (who is None or gw == who) and _holds(test, text, detail):
            return b
    return "allied" if gw in allied else "axis" if gw in axis else "neutral"


def bloc_on(set_, gw, snap, detail):
    """The bloc of controller gw on a date of a province set."""
    b = BLOCS[set_][snap]
    return bloc(gw, b["allied"], b["axis"], detail, DETAIL_BLOCS[set_], snap)


# Before Manchukuo's own provinces (1934-41) are known, its territory is that of these 1928-45 provinces
MANCHU_ROC = {"Liaoning": ("Fengtian", "奉天"), "Jilin": ("Jilin", "吉林"), "Heilongjiang": ("Heilongjiang", "黑龙江"),
              "Jehol": ("Rehe", "热河")}
# Political units whose CShapes status on the date misdescribes them: (date, CShapes name) ->
# (status, sovereign gw, name en, name zh). Serbia and Montenegro had been freed by 11 November 1918.
UNIT_FIX = {("1918-11-11", "Serbia"): ("independent", 345, "Serbia", "塞尔维亚"),
            ("1918-11-11", "Montenegro"): ("independent", 341, "Montenegro", "黑山"),
            ("1991-12-26", "Russia (Soviet Union)"): ("independent", 365, "Russia", "俄罗斯"),
            ("1991-12-26", "German Federal Republic"): ("independent", 260, "Germany", "德国")}


# The East Asian occupation layers (K. Lawson's tracings, ww2_snapshots.overlays) and the divisions that stand
# for a client state or a leased territory: the first rule that applies gives the controller, a rule with no
# controller (None) means none of them does. A rule applies when the date lies in since..until (inclusive, None:
# open), the division's de facto parent kind is one of `kinds`, its parent one of `parents`, its country one of
# `iso3` (and none of `not_iso3`), and the place lies in the `layer` (ceded, ccp, meng, occ). Text in the names:
# {parent}/{parent_zh} the parent division, {roc}/{roc_zh} the Manchukuo province of MANCHU_ROC.
_MK, _LT, _ROC = "省 (Manchukuo)", "leased territory", "ROC Manchuria"
_KW_JP = (740, "Kwantung Leased Territory (Japan)", "关东州（日本租借地）", "leased_territory", "overlay:kwantung", "whole")
_OCC = (740, "Japanese-occupied China (incl. Wang Jingwei regime)", "日占区（含汪精卫政权）", "military_occupation",
        "overlay:occupied_zone_1942")
_MENG = (740, "Mengjiang (Japanese client state)", "蒙疆（日本扶植政权）", "client_state", "overlay:mengjiang")


def _r(since=None, until=None, ctrl=None, *, dates=None, kinds=None, parents=None, iso3=None, not_iso3=None,
       layer=None):
    return dict(since=since, until=until, dates=dates, kinds=kinds, parents=parents, iso3=iso3, not_iso3=not_iso3,
                layer=layer, ctrl=ctrl)


OVERLAY_RULES = [
    # after the war only two layers still mean something: the Indochinese land Thailand kept until the Washington
    # agreement of November 1946, and the Kwantung territory (Port Arthur and Dalny), held by the Soviet Union
    # under the treaty of August 1945
    _r("1945-09-03", "1946-11-17", iso3=("KHM", "LAO"), layer="ceded",
       ctrl=(800, "Thailand (territory ceded by French Indochina in 1941, returned in November 1946)",
             "泰国（1941 年法属印度支那割让地，1946 年 11 月归还）", "annexation", "overlay:indochina_ceded", "whole")),
    _r("1945-09-03", "1949-09-30", kinds=(_LT,),
       ctrl=(365, "Soviet Union (Port Arthur naval base and Dalny, treaty of 14 August 1945)",
             "苏联（旅顺海军基地与大连，1945 年 8 月 14 日条约）", "leased_territory", "overlay:kwantung", "whole")),
    _r("1945-09-03"),
    # before the war with China: Manchukuo in the provinces of the Republic (Jehol from March 1933), Kwantung
    _r("1932-03-01", "1933-03-03", kinds=(_ROC,), parents=("Jehol",)),
    _r("1932-03-01", "1937-07-06", kinds=(_ROC,),
       ctrl=(740, "Manchukuo ({roc} Province)", "伪满洲国（{roc_zh}省）", "client_state", "overlay:manchukuo_roc",
             "whole")),
    _r(None, "1905-09-04", kinds=(_LT,),
       ctrl=(365, "Kwantung Leased Territory (Russia, Port Arthur and Dalny)", "关东州（俄国租借地，旅顺、大连）",
             "leased_territory", "overlay:kwantung", "whole")),
    _r(None, "1937-07-06", kinds=(_LT,), ctrl=_KW_JP),
    _r(None, "1937-07-06"),
    # 1937-1945
    _r("1945-09-02", "1945-09-02", kinds=(_MK, _LT),
       ctrl=(365, "Soviet military occupation of Manchuria", "苏军占领东北", "military_occupation", "overlay:manchukuo",
             "whole")),
    _r(kinds=(_LT,), ctrl=_KW_JP),
    _r(kinds=(_MK,), ctrl=(740, "Manchukuo ({parent} Province)", "伪满洲国（{parent_zh}省）", "client_state",
                           "overlay:manchukuo", "whole")),
    _r("1941-05-09", None, not_iso3=("CHN",), iso3=("KHM", "LAO"), layer="ceded",
       ctrl=(800, "Thailand (territory ceded by French Indochina, 1941)", "泰国（1941年法属印度支那割让地）",
             "annexation", "overlay:indochina_ceded", "whole")),
    _r(not_iso3=("CHN",)),
    _r(dates=("1941-12-07", "1942-11-01"), layer="ccp",
       ctrl=(-2, "CCP base area / guerrilla zone (1941-42)", "中共抗日根据地 / 游击区（1941-42）", "resistance_base",
             "overlay:ccp_bases_1941_42", "approximate")),
    _r(dates=("1939-09-01",), layer="meng", ctrl=_MENG + ("approximate",)),
    _r(None, "1945-09-01", layer="meng", ctrl=_MENG + ("whole",)),
    _r("1945-09-02", "1945-09-02", layer="occ",
       ctrl=(740, "Japanese forces pending surrender (occupied zone of 1942)", "待投降日军（1942年占领区范围）",
             "surrendering_forces", "overlay:occupied_zone_1942", "approximate")),
    _r(dates=("1939-09-01", "1940-07-01", "1944-06-06"), layer="occ", ctrl=_OCC + ("approximate",)),
    _r(layer="occ", ctrl=_OCC + ("whole",)),
]


def overlay_control(snap, county, inside):
    """The controller the East Asian layers give a place (OVERLAY_RULES), or None. county: the reference unit with
    iso3 and its historical division's defacto_parent_kind, defacto_parent, defacto_parent_zh; inside(layer): whether
    the place lies in that layer (False when the layer is missing)."""
    kind, parent = county.get("defacto_parent_kind"), county.get("defacto_parent")
    for r in OVERLAY_RULES:
        if (r["since"] and snap < r["since"]) or (r["until"] and snap > r["until"]) or \
                (r["dates"] and snap not in r["dates"]) or (r["kinds"] and kind not in r["kinds"]) or \
                (r["parents"] and parent not in r["parents"]) or (r["iso3"] and county["iso3"] not in r["iso3"]) or \
                (r["not_iso3"] and county["iso3"] in r["not_iso3"]) or (r["layer"] and not inside(r["layer"])):
            continue
        if r["ctrl"] is None:
            return None
        gw, en, zh, typ, src, conf = r["ctrl"]
        roc = MANCHU_ROC[parent] if "{roc" in en else ("", "")
        fill = dict(parent=parent, parent_zh=county.get("defacto_parent_zh") or "", roc=roc[0], roc_zh=roc[1])
        return gw, en.format(**fill), zh.format(**fill), typ, src, conf
    return None
