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
