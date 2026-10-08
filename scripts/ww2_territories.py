"""Territories that CShapes 2.0 does not draw (small islands, protectorates, the Dodecanese,
the Kurils). Their land would otherwise be attached to the nearest drawn unit.
Records give the owner on each date: EARLIER before the Second World War, LATER after it.
"""


# Small territories that CShapes 2.0 does not draw: their counties would otherwise be
# attached to the nearest unit. iso3 -> (unit_id, name_en, name_zh, status, sovereign gw,
# approximate population c. 1940, rounded; used instead of the unit_year table).
_SSM = (-1001, "South Seas Mandate (Japanese)", "南洋群岛（日本委任统治地）", "mandate", 740, 130000)
_GEI = (-1002, "Gilbert and Ellice Islands (British)", "吉尔伯特和埃利斯群岛（英属）", "colony", 200, 35000)
ISLAND_UNITS = {
    "MNP": _SSM, "PLW": _SSM, "FSM": _SSM, "MHL": _SSM, "KIR": _GEI, "TUV": _GEI,
    "GUM": (-1003, "Guam (US territory)", "关岛（美国属地）", "colony", 2, 22000),
    "ASM": (-1004, "American Samoa (US territory)", "美属萨摩亚（美国属地）", "colony", 2, 13000),
    "WSM": (-1005, "Western Samoa (New Zealand mandate)", "西萨摩亚（新西兰委任统治地）", "mandate", 920, 60000),
    "NIU": (-1006, "Niue (New Zealand)", "纽埃（新西兰属地）", "colony", 920, 4000),
    "TON": (-1007, "Tonga (British protectorate)", "汤加（英国保护国）", "protectorate", 200, 34000),
    "NRU": (-1008, "Nauru (Australian-administered mandate)", "瑙鲁（澳大利亚管理的委任统治地）", "mandate", 900, 3400),
    "VUT": (-1009, "New Hebrides (Anglo-French condominium)", "新赫布里底（英法共管地）", "colony", 200, 45000),
    "KWT": (-1010, "Kuwait (British protectorate)", "科威特（英国保护国）", "protectorate", 200, 75000),
    "BHR": (-1011, "Bahrain (British protectorate)", "巴林（英国保护国）", "protectorate", 200, 90000),
    "GRL": (-1012, "Greenland (Danish colony)", "格陵兰（丹麦殖民地）", "colony", 390, 18000),
    "ATG": (-1013, "Antigua (British Leeward Islands)", "安提瓜（英属背风群岛）", "colony", 200, 40000),
    "KNA": (-1014, "St Kitts-Nevis (British Leeward Islands)", "圣基茨和尼维斯（英属背风群岛）", "colony", 200, 41000),
    "DMA": (-1015, "Dominica (British)", "多米尼克（英属）", "colony", 200, 47000),
    "LCA": (-1016, "St Lucia (British Windward Islands)", "圣卢西亚（英属向风群岛）", "colony", 200, 70000),
    "VCT": (-1017, "St Vincent (British Windward Islands)", "圣文森特（英属向风群岛）", "colony", 200, 61000),
    "GRD": (-1018, "Grenada (British Windward Islands)", "格林纳达（英属向风群岛）", "colony", 200, 72000),
    "SYC": (-1019, "Seychelles (British)", "塞舌尔（英属）", "colony", 200, 32000),
    "STP": (-1020, "São Tomé and Príncipe (Portuguese)", "圣多美和普林西比（葡属）", "colony", 235, 60000),
}
_DOD = (-1021, "Italian Islands of the Aegean (Dodecanese)", "意属爱琴海群岛（多德卡尼斯）", "colony", 325, 120000)
_KUR = (-1022, "Kuril Islands (Japan)", "千岛群岛（日本）", "independent", 740, 17000)
ISLAND_UNITS.update({("GRC", n): _DOD for n in (
    "Rhodes", "Halki", "Tilos", "Symi", "Nisyros", "Kos", "Kalymnos", "Leros", "Leipsoi", "Patmos", "Agathonisi",
    "Kasos", "Karpathos", "Kastellorizo", "Astypalaia")})
ISLAND_UNITS.update({("RUS", n): _KUR for n in ("Yuzhno-Kurilsky District", "Kurilsky District", "Severo-Kurilsky District")})


# Before the Second World War some of these had other owners. Unit id of the 1939-45 record ->
# [(first day, last day, record)]; each earlier record has an id of its own.
EARLIER = {
    -1001: [("1899-06-30", "1914-10-13", (-1101, "German Micronesia (Caroline, Mariana and Marshall Islands)",
                                          "德属密克罗尼西亚（加罗林、马里亚纳、马绍尔群岛）", "colony", 255, 70000)),
            ("1914-10-14", "1920-12-16", (-1102, "Japanese-occupied Micronesia (formerly German)",
                                          "日军占领的密克罗尼西亚（原德属）", "occupied", 740, 50000))],
    -1005: [("1900-03-01", "1914-08-28", (-1103, "German Samoa", "德属萨摩亚", "colony", 255, 35000)),
            ("1914-08-29", "1920-12-16", (-1104, "Western Samoa (New Zealand occupation)", "西萨摩亚（新西兰占领）",
                                          "occupied", 920, 38000))],
    -1006: [("1900-04-01", "1901-06-10", (-1105, "Niue (British protectorate)", "纽埃（英国保护地）", "protectorate",
                                          200, 4000))],
    -1008: [("1888-10-01", "1914-11-05", (-1106, "Nauru (German)", "瑙鲁（德属）", "colony", 255, 1500)),
            ("1914-11-06", "1920-12-16", (-1107, "Nauru (Australian occupation)", "瑙鲁（澳大利亚占领）", "occupied",
                                          900, 1500))],
    -1009: [("1887-10-24", "1906-10-19", (-1108, "New Hebrides (Anglo-French Joint Naval Commission)",
                                          "新赫布里底（英法联合海军委员会）", "colony", 200, 60000))],
    -1010: [("1899-01-23", "1914-11-02", (-1109, "Kuwait (British protection, Ottoman suzerainty)",
                                          "科威特（英国保护，奥斯曼名义宗主）", "protectorate", 200, 35000))],
    -1021: [("1878-07-13", "1912-05-03", (-1110, "Dodecanese (Ottoman)", "多德卡尼斯群岛（奥斯曼帝国）",
                                          "independent", 640, 100000)),
            ("1912-05-04", "1923-08-05", (-1111, "Dodecanese (Italian occupation)", "多德卡尼斯群岛（意大利占领）",
                                          "occupied", 325, 100000))],
}
# After the war (1946-1991). None: on these dates the land belongs to a unit CShapes draws (the
# Dodecanese in Greece from the peace treaty, Kuwait and Bahrain once independent).
LATER = {
    -1001: [("1945-09-03", "1947-07-17", (-1201, "Former South Seas Mandate (US military government)",
                                          "原南洋群岛（美国军政府）", "occupied", 2, 50000)),
            ("1947-07-18", "1986-11-02", (-1202, "Trust Territory of the Pacific Islands (US)",
                                          "太平洋岛屿托管地（美国托管）", "mandate", 2, 60000)),
            ("1986-11-03", "1994-09-30", (-1203, "Micronesia, Marshall Islands, Northern Marianas and Palau "
                                          "(US free association, commonwealth and trust territory)",
                                          "密克罗尼西亚、马绍尔群岛、北马里亚纳与帕劳（与美国自由联系、美国联邦属地及托管地）",
                                          "dependency", 2, 205000))],
    -1002: [("1976-01-01", "2100-01-01", (-1204, "Kiribati and Tuvalu", "基里巴斯和图瓦卢", "independent", None,
                                          80000))],
    -1005: [("1945-09-03", "1961-12-31", (-1205, "Western Samoa (New Zealand trust territory)",
                                          "西萨摩亚（新西兰托管地）", "mandate", 920, 80000)),
            ("1962-01-01", "2100-01-01", (-1206, "Western Samoa", "西萨摩亚", "independent", None, 160000))],
    -1006: [("1974-10-19", "2100-01-01", (-1207, "Niue (self-governing, in free association with New Zealand)",
                                          "纽埃（与新西兰自由联系的自治领地）", "dependency", 920, 2300))],
    -1007: [("1970-06-04", "2100-01-01", (-1208, "Tonga", "汤加", "independent", None, 95000))],
    -1008: [("1945-09-14", "1968-01-30", (-1209, "Nauru (Australian-administered trust territory)",
                                          "瑙鲁（澳大利亚管理的托管地）", "mandate", 900, 3000)),
            ("1968-01-31", "2100-01-01", (-1210, "Nauru", "瑙鲁", "independent", None, 9500))],
    -1009: [("1980-07-30", "2100-01-01", (-1211, "Vanuatu", "瓦努阿图", "independent", None, 150000))],
    -1010: [("1945-09-03", "1961-06-18", (-1226, "Kuwait (British protectorate)", "科威特（英国保护国）", "protectorate",
                                          200, 170000)),
            ("1961-06-19", "2100-01-01", None)],
    -1011: [("1945-09-03", "1971-08-14", (-1227, "Bahrain (British protectorate)", "巴林（英国保护国）", "protectorate",
                                          200, 115000)),
            ("1971-08-15", "2100-01-01", None)],
    -1012: [("1953-06-05", "1979-04-30", (-1212, "Greenland (Danish county)", "格陵兰（丹麦的一个郡）", "dependency",
                                          390, 30000)),
            ("1979-05-01", "2100-01-01", (-1213, "Greenland (Danish home rule)", "格陵兰（丹麦自治领地）", "dependency",
                                          390, 56000))],
    -1013: [("1981-11-01", "2100-01-01", (-1214, "Antigua and Barbuda", "安提瓜和巴布达", "independent", None, 63000))],
    -1014: [("1983-09-19", "2100-01-01", (-1215, "Saint Kitts and Nevis", "圣基茨和尼维斯", "independent", None,
                                          41000))],
    -1015: [("1978-11-03", "2100-01-01", (-1216, "Dominica", "多米尼克", "independent", None, 71000))],
    -1016: [("1979-02-22", "2100-01-01", (-1217, "Saint Lucia", "圣卢西亚", "independent", None, 135000))],
    -1017: [("1979-10-27", "2100-01-01", (-1218, "Saint Vincent and the Grenadines", "圣文森特和格林纳丁斯",
                                          "independent", None, 108000))],
    -1018: [("1974-02-07", "2100-01-01", (-1219, "Grenada", "格林纳达", "independent", None, 96000))],
    -1019: [("1976-06-29", "2100-01-01", (-1220, "Seychelles", "塞舌尔", "independent", None, 70000))],
    -1020: [("1975-07-12", "2100-01-01", (-1221, "São Tomé and Príncipe", "圣多美和普林西比", "independent", None,
                                          120000))],
    -1021: [("1945-09-03", "1947-03-30", (-1222, "Dodecanese (British Military Administration)",
                                          "多德卡尼斯群岛（英国军事管理）", "occupied", 200, 115000)),
            ("1947-03-31", "1947-09-14", (-1223, "Dodecanese (Greek military administration, ceded by Italy)",
                                          "多德卡尼斯群岛（希腊军事管理，意大利割让）", "occupied", 350, 115000)),
            ("1947-09-15", "2100-01-01", None)],
    -1022: [("1945-09-03", "1991-12-25", (-1224, "Kuril Islands (Soviet Union)", "千岛群岛（苏联）", "independent", 365,
                                          20000)),
            ("1991-12-26", "2100-01-01", (-1225, "Kuril Islands (Russia; the southern islands claimed by Japan)",
                                          "千岛群岛（俄罗斯；南部诸岛日本主张主权）", "independent", 365, 25000))],
}
ALL_ISLANDS = {v[0]: v for v in ISLAND_UNITS.values()}
ALL_ISLANDS.update({rec[0]: rec for vs in EARLIER.values() for _, _, rec in vs})
ALL_ISLANDS.update({rec[0]: rec for vs in LATER.values() for _, _, rec in vs if rec})


def island_unit(c, date=None):
    u = ISLAND_UNITS.get(c["iso3"]) or ISLAND_UNITS.get((c["iso3"], c.get("name")))
    if u and date:
        for first, last, rec in [*EARLIER.get(u[0], ()), *LATER.get(u[0], ())]:
            if first <= date <= last:
                return rec
    return u
