# 断面生产 SOP（1900–1991 历史省级区划地图）

本文把已做过的 19 个断面（1900–1934 七个、1939–1945 六个、1946–1991 六个）及 2026 年图层所用的规则，整理成新增断面时可逐项执行的流程。规则的来龙去脉见 [ww2/README.md](../ww2/README.md)，本文只写“做一个新断面要做什么、按什么口径做”。

> 约定：本文中“断面”= 一个精确日期上的世界地图（`snapshot`，`YYYY-MM-DD`）；“集合”= 共用一个数据库和一份控制规则表的一组断面（`ww2` / `early` / `postwar`）。

---

## 0. 先选生产路径

| | 路径 A：轻量追加（`ww1_maps.py` 方式） | 路径 B：完整流水线（`pipeline.py`） |
|---|---|---|
| 做法 | 从仓库内已有的 SQLite 和地图数据出发，借一个已建好的“基准断面”的历史区划，按新日期重切国界、套控制规则、分配人口，追加到数据库和 `admin.bin` 末尾 | 把日期加进某个集合，从原始资料重新提取当日施行的区划，跑完整的区划 → 快照 → 省级合并 → 数据库 → 网页地图 |
| 需要下载 | 不需要 | 约 4 GB（OpenHistoricalMap 1.3 GB 等） |
| 用时 | 每批几分钟 | 首次约 80 分钟；之后按指纹只重算变动部分（改一个时期的规则约 6 分钟） |
| 区划精度 | 沿用基准断面的区划，只加入在新日期前后有明确施行日期的替代区划；**不会**补出基准日期之后才设立、又未收录的新区划 | 当日施行的全部已收录区划 |
| 适合 | 与已有断面相隔不远、区划基本没变的事件日（如 1915–1917 借 1914） | 区划有大变动的日期，或离所有现有断面都很远的日期 |
| 现状限制 | `ww1_maps.py` 目前写死为 1900–1934 数据库、基准 1914-08-04、三个一战日期（见 §8.1 的一次性改造） | `ww2` 集合的阵营按断面序号切片（见 §9 坑 1） |

**判定规则：** 新日期与最近的已有断面之间，若该地区的一级区划没有大的重划（建省、撤省、领土大规模易手后的新行政体系），走 A；否则走 B。一批里两种都有时，先走 B 把需要重算区划的日期并入集合，再走 A 追加其余日期。

**日期范围：** 1900-01-01 至 2000-12-31（人口来自 `world_history_1900_2000.sqlite` 的 `unit_year`，国界来自 CShapes 2.0）。2000 年以后只有单独的 2026 图层，不在本 SOP 范围内。

---

## 1. 断面定义规则

1. **用精确事件日，不用年中。** 选一个有明确日期的事件（宣战、停战、建国、条约生效、战役开始）。所有判断都按“当日”做：当日已生效的才算，次日生效的不算（例如 1914-08-04 黑山、日本尚未参战）。
2. **标题三件套：** `(日期, 中文事件, English event)`，写进 `scripts/ww2_common.py` 的对应列表。中文标题写事件本身，不写评价；必要时用分号并列两件事（“辽沈战役开始；朝鲜半岛南北分立”）。
3. **口径说明：** 每个断面在地图图例下要有两段文字（§6）：`bloc`（阵营怎么划）和 `control`（实际控制的要点，以及哪些是近似）。口径上的取舍必须写出来，例如“阵营表示已加入战争的一方，不表示当日已与对方每个成员交战”。
4. **同日多事件**：以标题事件为准，其他同日变化照常按当日处理（如 1916-08-27 意大利同日对德宣战）。

---

## 2. 区划规则（不可违背）

1. **只用当日施行的区划，不用现代政区代替。** 所有区划资料按 `start_date`/`end_date` 筛选；后设的区划不能出现在更早的日期。
2. **只显示省级。** 县级、地区级单位并入所属的省：上级链中第一个省级单位；各套资料自带的归属优先（朝鲜郡→道、美国县→州、台湾郡市→州厅等）。
3. **层级 `tier` 只有四种：** 3 省级、4 大区级（只用在没有省级资料处）、5 整个国家 / 殖民地（CShapes 当日轮廓）、6 岛屿属地（CShapes 未画出的小属地，见 `ww2_territories.py`）。
4. **没有资料就显示整个政治单元**，不臆造省界；在 `note` 中说明“历史省级资料缺失”。
5. **今日轮廓只在两种情况下可用作区划：** 该单位当日已存在且界线基本未变（`basis = present_day_outline_same_unit`），或可由今日单位精确合成（`present_day_outline_merged`，登记在 `curated/present_day_units_1946_1991.csv`）。差异写进单位的 `note`。用今日县拼合的历史省份标 `basis = reconstructed_from_present_day_counties`，属近似。
6. **今日政区可以作为控制规则的“参照”**（规则用今日地名书写，因为战线不沿任何区划），但**从不作为区划输出**。
7. **数值阈值（脚本内常数，不要逐断面改）：**

| 规则 | 阈值 | 位置 |
|---|---|---|
| OHM 轮廓先简化 | 0.0005°（约 50 m） | `ww2_histunits.py` |
| OHM 单位水面超过此比例则裁到陆地 | 10%（海岸线简化 0.002°） | `ww2_histunits.py` |
| 无上级的小县级单位并入相邻单位 | < 300 km² | `ww2_provinces.py` |
| 零星未覆盖小块并入最近的省 | < 5,000 km² 且 < 该政治单元 3% | `ww2_provinces.py` |
| 省内控制不同，切出单独一块的下限 | ≥ 8% 或 ≥ 1,500 km² | `ww2_snapshots.py`（`CONTROL_MIN_SHARE`/`CONTROL_MIN_KM2`） |
| 碎块并入同省最大块 | < 5 km² | `ww2_provinces.py` |
| 1897 俄国省落入他国部分单独切出 | ≥ 300 km² | `ww2_snapshots.py` |
| 地图几何简化 | 省 0.008°、政治单元 0.02°、控制区 0.012° | `ww2_webmap.py` |
| 国名标注的最小领土 | 2,500 km² | `ww2_webmap.py` |

8. **跨界切开：** 省跨 CShapes 当日国界时按国界切开；省内实际控制者不同时按控制者切开。控制者在合并成省之前、在最细的历史区划（或参照区）上判定，所以切线保留县一级精度。切开的块 `control_split = 1`。

---

## 3. 实际控制判定

### 3.1 优先级（低 → 高，后者覆盖前者）

1. CShapes 2.0 当日的国界与宗主（殖民地归宗主国）。
2. `curated/control_events.csv` 中的整国事件（`scope = whole` 覆盖整个单元；`partial` 只记在 `partial_control_events`，具体范围由分区规则画）。
3. 东亚历史图层（满洲国、关东州、蒙疆、1942 日占区、中共根据地、1941 割泰地），只在 `ww2_snapshots.control_overlay` 中按日期生效。`field` 为 `*` 或 `unit` 的整单元规则**不会**覆盖这些图层。
4. 分区规则 CSV，**按文件顺序执行，最后匹配者生效**。所以先写大范围规则，再写例外（先“整个法国 = 德占”，再“维希区 = 维希”）。

### 3.2 规则表格式（路径 B：`ww2_region_control.csv` / `region_control_1900_1934.csv` / `region_control_1946_1991.csv`）

```
snapshots,iso3,field,match,controller_name,controller_name_zh,controller_gwcode,control_type,confidence,note
```

| 列 | 写法 |
|---|---|
| `snapshots` | 适用的日期，`|` 分隔。新增断面时，**先检查已有规则是否也应适用于新日期**，把新日期加进去，而不是复制一行 |
| `iso3` | 参照区所在今日国家的 ISO3，`|` 分隔，`*` = 不限 |
| `field` | `*` 整个国家；`unit` CShapes 政治单元名；`hist` 历史单位本身或其所属省的名称；`adm1_modern` / `adm2_modern` 今日一级 / 二级政区名；`name` 参照区名称（支持末尾 `*` 前缀匹配）；`geo` 按经纬度画范围（见下） |
| `match` | 匹配值，`|` 分隔 |
| `geo` 的 `match` | `box:西,南,东,北`、`circle:经度,纬度,公里`、`poly:经 纬;经 纬;...`，可 `|` 并列；判断参照区的标注点是否落在其中。用于不沿任何区划的界线（三八线、内战据点、停火线） |
| `controller_gwcode` | 有国家的用 Gleditsch-Ward 代码；没有国家的政权用**负数自定义码**（见 §3.4） |
| `control_type` | 用已有词表（§3.3），不要新造近义词 |
| `confidence` | `whole`（整区确实归属）或 `approximate`（按整区近似、沿用临近年份范围、真实前线可能穿过；地图画斜线） |
| `note` | 英文，写清日期依据和事件（如 “Tianjin taken 14 July 1900; the relief force entered Beijing on 14 August 1900”） |

### 3.3 `control_type` 词表（已用过的）

`independent`、`colony`、`protectorate`、`annexation`、`military_occupation`、`allied_occupation`、`client_state`、`satellite_state`、`collaborationist_state`、`de_facto_state`、`de_facto_government`、`secession`、`autonomy`、`civil_war`、`contested`、`front_line`、`besieged`、`partition`、`leased_territory`、`un_administration`、`international_administration`、`surrendering_forces`、`liberated`、`military_intervention`、`defense_agreement`、`free_french`。

### 3.4 控制者编码约定

- 有 CShapes 国家的：用其 gwcode（德 255、英 200、法 220、俄/苏 365、美 2、日 740、中 710、意 325……完整颜色表见 `ww2_webmap.COLOR`）。
- **`-20` = 交战区 / 前线争夺**，阵营永远是 `contested`，地图不写国名。
- `-1` 盟国 / 协约国联军；`-2` 中国共产党（1949-10-01 起名为中华人民共和国）。
- 其余负数码按集合分段登记，**新码必须同时登记三处**：名称（`ww2_snapshots.py` 的 `STATE` / `EARLY_STATE` / `POSTWAR_STATE`，只在某日改名的写进 `*_STATE_ON`）、颜色（`ww2_webmap.COLOR`）、阵营（§4）。已占用：1939–45 用 −1…−30，1900–34 用 −30…−80，1946–91 用 −100…−131。新码在本段内顺延，不复用。
- 同一国家在不同日期的名称（俄国临时政府、苏维埃俄国、俄罗斯）用 `*_STATE_ON` 或 `UNIT_FIX` 按日期改，不另立代码。

### 3.5 控制者的划分口径（控制国视图）

- 军事占领区、吞并区算作**占领国**。
- 有自己政府的傀儡、附庸政权**单列**（满洲国、维希法国、克罗地亚独立国、盖特曼国……）。
- 几国联合控制写“联军”（`-1`、`-10`）；四国共管写盟国共管。
- 殖民地、保护国、委任统治地在控制国视图归宗主国；在国家视图用宗主国颜色的浅色。
- 精确战线未知：整省（或整个殖民地）标 `-20` + `approximate`；已知大致范围但不沿区划：用 `geo` 或参照区近似，标 `approximate`。**不准把近似画成精确**。
- 很小的租借地（低于切块下限）不单独切出，只在城市提示中说明。

### 3.6 CShapes 的已知问题按日期修补

- 政治单元状态与事实不符：写进 `ww2_snapshots.UNIT_FIX[(日期, CShapes 名)] = (status, 宗主 gw, 英文名, 中文名)`（例：1918-11-11 塞尔维亚、黑山已光复；1991-12-26 苏联改称俄罗斯）。
- CShapes 当日留白的陆地：写进 `ww2_common.UNCOVERED` / `UNCOVERED_BOX`（例：1918-11-11 的拉脱维亚算俄国）。
- 界线与当日事实不符（如 CShapes 把朝鲜停战线一直用到 1945 年）：法理单元仍用 CShapes，实际控制另用 `geo` 规则划。
- 政治单元的中文名、时期名称在 `curated/unit_names.csv`（`cshapes_name, applies_to, year_from, year_to, name_en, name_zh`）。新断面出现未登记的单元时补一行。

---

## 4. 阵营规则

1. **固定四类：** `allied`、`axis`、`neutral`、`contested`。字段名固定，**含义按断面重新定义**，图例文字由 `bloc_names` 给出（例如 1934 年 allied = 国际联盟成员国，1991 年 axis = 独联体）。
2. **属地随宗主**（阵营按控制者判定）。
3. **`-20` 永远是 `contested`。**
4. **只算当日已处于该状态的：** 已宣战 / 已加入 / 已签署。次日生效、尚未参战的放 `neutral`，并在图例说明里点名。
5. 每个断面写两个集合（`allied`、`axis` 的 gwcode），其余自动为 `neutral`：
   - `early`：`ww2_snapshots.EARLY_BLOCS[日期]`；
   - `postwar`：`ww2_snapshots.POSTWAR_BLOCS[日期]`；
   - `ww2`：`ww2_snapshots.AXIS` / `ALLIED` 按断面序号切片（见 §9 坑 1）；
   - 路径 A：`ww1_maps.ALLIED` / `AXIS`。
6. 特殊判定写在 `early_bloc` / `postwar_bloc` 里，按 `detail`（控制者细节）区分，例如 1900 年东南互保各省（清廷代码但计中立）、满洲国随日本、维希法国计中立。

---

## 5. 人口规则

1. **两步法：** 用 GHS-POP 1975（30″）算每块在本政治单元内的人口占比 → 乘以该单元当年人口（`world_history_1900_2000.sqlite` 的 `unit_year`）。美国另按州普查校准；小属地用约 1940 年的近似总数。路径 A 改用基准断面的历史省级人口密度分布，按面积调整后缩放到同年单元人口，整数舍入守恒。
2. **人口在最细区划上算，省和块的人口是所含单位之和。**
3. **年中以后才出现的政治单元**（如 1947-08-15 的印巴、1991 年独立各国）用下一年的人口；记录在当年年中不存在时，取同名单元当年人口按面积分摊，或该记录最近一年的估计。
4. 这是分布格局估计，不是事件日普查：不另算战时死亡、难民、军队。说明文字要写这一点。

---

## 6. 地图文案

每个断面在 `ww2_webmap.py` 的 `EARLY_META` / `POSTWAR_META`（路径 A 在 `ww1_maps.NOTES` 与 `export_snapshot` 中的 `bloc_names`）写。1939–45 集合目前没有 META，页面用模板里的默认图例（同盟国 / 轴心国）；给该集合加日期且图例需要不同说法时，在 `META` 中加该日期即可：

```python
"YYYY-MM-DD": dict(
    bloc_names={"allied": "…", "axis": "…", "neutral": "…", "contested": "交战区"},
    notes={"bloc_title": "<主题> · 人口",
           "bloc": "阵营怎么划：点名谁在哪一边、谁当日尚未加入；交战区在哪（斜线）。",
           "control": "实际控制的要点；哪些按整区、整县近似。"}),
```

写法：

- 中文，句号结尾，事实带日期（“1947 年 3 月杜鲁门主义……”）。
- 必须说出所有 `approximate` 的大类（“均为按整区、整县的近似”）。
- 不写来源以外的推断；不写评价性形容词。

---

## 7. 城市规则

| 集合 | 表 | 日期码 |
|---|---|---|
| 1900–1934（含 1915–17） | `curated/cities_1900_1934.csv` | `00 14 15 16 17 18 34` |
| 1939–1945 | `curated/ww2_cities.csv`（无 `dates` 列） | `39 40 41 42 44 45` |
| 1946–1991 | `curated/cities_1946_1991.csv` | `46 47 48 49 53 91` |

列：`name_zh,name_en,lon,lat,kinds,dates,capital,seat,rank,note`

- **新日期必须先在 `scripts/cities.py` 的 `EARLY_CODE` / `POSTWAR_CODE` / `CODE` 中登记两位码**（同一集合内两位码不能重复；若与已有码冲突，用别的两位数并在表头注释中说明）。
- `dates`：该行显示于哪些断面，空格分隔；`*` = 全部。**新增断面时要把码追加到所有仍应显示的行**，否则这些城市在新断面消失。
- `kinds`：`I` 工业、`P` 港口、`C` 其他重要城市，可组合（`IP`）；空 = 只有首都 / 首府角色。
- `capital` / `seat`：`码 码=政权名;码=政权名`，`*=政权名` 表示全部断面。`capital` = 当日政府驻地（★），`seat` = 殖民地首府、临时政府驻地、流亡政府（◉）。按**当日政府实际驻地**判定（1942 重庆、维希；1915 塞尔维亚驻尼什；1917 罗马尼亚驻雅西）。
- **改名的城市每个名字一行**，用 `dates` 区分（圣彼得堡 / 彼得格勒 / 列宁格勒；北平 / 北京；西贡 / 胡志明市）。同一断面不得出现同一坐标两行。
- `rank`：0 / 1 / 2，决定从哪个缩放级显示；首都自动不大于 1。
- `note`：中文，一句话说明当日地位或特点。
- 坐标：构建时按英文名到 Natural Earth 1.5° 内找点替换；路径 A 直接用表内坐标。

---

## 8. 生产流程

### 8.0 每个断面的录入卡片（先填卡片，再动代码）

批量生产时，每个断面先填这一张卡片；卡片齐了再一次性写入各文件。建议把卡片存为 `work/cards/<日期>.md`（不提交）或直接贴在提交说明里。

```
日期：YYYY-MM-DD            集合：early / ww2 / postwar      路径：A / B
中文标题：                   English title：
基准断面（路径 A）：         与基准之间的区划变化：无 / 有（列出）
阵营
  allied（gwcode 列表）：
  axis（gwcode 列表）：
  点名“当日尚未加入”的国家：
  bloc_names 四项：
控制（每条一行：范围写法 field/match → 控制者 gwcode / 中文名 / control_type / whole|approximate / 依据与日期 / 来源链接）
  - 整国事件（control_events.csv）：
  - 分区规则：
  - 交战区（-20）：
  - 需复用并追加新日期的已有规则行号：
新的负数控制者码（名称 / 颜色 / 阵营）：
CShapes 修补（UNIT_FIX / UNCOVERED / unit_names）：
首都 / 首府变化（城市 → capital/seat 写法）：
新增或改名城市：
图例文案：bloc_title / bloc / control
来源链接：
```

### 8.1 路径 A：轻量追加

**一次性改造（第一次批量走 A 之前做一次，之后每批不用再做）：** `ww1_maps.py` 目前写死了 `DATABASE`（1900–1934 库）、`BASE_DATE = "1914-08-04"`、`DATES = SNAPSHOTS_WWI`、`ALLIED`/`AXIS`/`NOTES` 三个字典、`export_snapshot` 中的 `bloc_names`，以及继承 1914 年控制的 `control_source IN ('rule:8','rule:9','rule:69','overlay:kwantung')`。要用于其他年代，需把这些改成按断面配置（每个日期：目标数据库、基准日期、阵营、文案、继承的规则），`ww1-build.json` 的“追加部分”逻辑保持不变。`verify_ww1_maps.py` 中写死的历史断言（巴黎、柏林、华沙等的控制者）也要改为按日期配置。

**每批步骤：**

1. 填卡片（§8.0）。
2. `scripts/ww2_common.py`：在 `SNAPSHOTS_WWI`（或改造后的追加列表）加 `(日期, 中文, English)`。
3. 控制规则：写进 `curated/ww1_region_control.csv`（或改造后的对应表），格式：
   ```
   snapshots,unit_match,admin_match,reference,controller_name,controller_name_zh,controller_gwcode,control_type,confidence,note,source_url
   ```
   - `unit_match`：CShapes 政治单元名，支持 `*` 通配，`|` 分隔；
   - `admin_match`：历史区划的 `admin_id`（如 `FR1939-ardennes`、`OHM-r2945069`），支持 `*`；
   - `reference`：可选，今日一级政区的 ISO 3166-2 码或今日国名，用作近似裁切的范围（只裁切，不作区划）；
   - `source_url`：**必填**，每条规则都要能查到来源；
   - **每条规则在它列出的每个日期上都必须命中至少一块，否则脚本报错停止**（`Unmatched control rules`）。
4. 阵营、文案：`ww1_maps.ALLIED` / `AXIS` / `NOTES`（改造后为配置）。
5. 城市：`cities.py` 登记日期码，城市表追加码、首都 / 首府。
6. 运行（只生成，不测试）：
   ```sh
   python3 scripts/ww1_maps.py
   python3 scripts/ww2_html.py
   ```
   在流水线中则是 `ww1` 任务（排在该集合数据库和 `webmap` 之后、`html` 之前）。
7. 产物：数据库中新增的断面行、`ww2/maps/data/snap-<日期>.json`、`geo-<日期>.bin`、追加后的 `admin.bin`、`index.json`、`ww1-build.json`、`ww2/maps/<日期>.html`、对应 `coverage*_<集合>.csv`。
8. **禁止**手改 `ww1-build.json` 的校验值。若脚本报 “admin.bin changed since ww1_maps.py last ran”，先重跑 `ww2_webmap.py` 再跑 A。

### 8.2 路径 B：完整流水线

**一个新日期要改的文件清单（逐项勾）：**

| # | 文件 | 改什么 |
|---|---|---|
| 1 | `scripts/ww2_common.py` | `SNAPSHOTS_EARLY` / `SNAPSHOTS_WW2` / `SNAPSHOTS_POSTWAR` 加一行（按日期顺序）；必要时 `UNCOVERED` / `UNCOVERED_BOX` |
| 2 | `scripts/ww2_snapshots.py` | 阵营（`EARLY_BLOCS` / `POSTWAR_BLOCS` / ww2 的 `AXIS`·`ALLIED`）；新控制者名称（`*_STATE`、`*_STATE_ON`）；`UNIT_FIX`；如需东亚图层按新日期生效，改 `control_overlay` 的日期条件 |
| 3 | `scripts/ww2_webmap.py` | `EARLY_META` / `POSTWAR_META` 文案；新控制者颜色 `COLOR` |
| 4 | `scripts/cities.py` | 日期两位码 |
| 5 | `curated/region_control_*.csv` / `ww2_region_control.csv` | 新规则；已有规则的 `snapshots` 追加新日期 |
| 6 | `curated/control_events.csv` | 新的整国事件（`event_id,unit_name,unit_gwcode,start_date,end_date,scope,control_type,controller_name,controller_name_zh,controller_gwcode,note`），注意起止日期覆盖新断面 |
| 7 | `curated/cities_*.csv` | 日期码、首都 / 首府、改名城市 |
| 8 | `curated/unit_names.csv` | 新出现的政治单元名称 |
| 9 | 区划资料（仅当新日期需要而现有资料没有时） | 例如 `present_day_units_1946_1991.csv`、`china_counties_1946_1954.csv` 的新时期列、`russia_1897.csv` |
| 10 | `README.md`、`ww2/README.md` | 断面表、打开方式里的链接、阵营划分方式、实际控制要点、覆盖程度数字 |

**运行（只生成，不测试）：**

```sh
python3 scripts/pipeline.py --sets <集合> --dry-run   # 看会跑哪些任务
python3 scripts/pipeline.py --sets <集合>             # 生成；中断后重跑即续跑
```

- 只改了控制规则 / 阵营 / 文案时，指纹机制会只重算快照、数据库、覆盖率和网页地图，区划不动。
- 日志：`work/pipeline/pipeline.log`，各任务 `work/pipeline/logs/<任务>.log`。失败时先看日志最后几行。
- 内存不够时会自动单独重跑被杀的任务；不要手动改 `stats.json`。

### 8.3 批量节奏（流水线生产）

1. **按集合成批**：同一集合的多个日期一次填卡、一次改文件、一次运行，避免网页地图（最慢的一步，约 30 分钟）反复重建。
2. **先 B 后 A**：同一批里既有需要重算区划的日期也有轻量日期时，先跑完 B，再跑 A（A 依赖 B 写出的 `admin.bin`）。
3. **规则复用优先**：相邻断面大部分控制相同，先把已有规则的 `snapshots` 加上新日期，再写差异规则。新写的规则放在相关已有规则之后（最后匹配生效）。
4. **每批一次提交**，提交说明列出日期、事件、主要控制取舍和近似（格式见 §10）。

---

## 9. 已踩过的坑

1. **`ww2` 集合的阵营按序号切片**（`S[2:5]` 之类）。往 `SNAPSHOTS_WW2` 中间插日期会让所有国家的阵营错位。要往 1939–45 加日期，先把 `AXIS` / `ALLIED` 改成按日期的集合（像 `POSTWAR_BLOCS` 那样），再加日期。
2. **规则“最后匹配生效”**：例外规则写在大范围规则前面会被覆盖。
3. **整单元规则不覆盖东亚图层**（`field` 为 `*`/`unit` 时跳过 overlay 来源），要改满洲国、日占区等，用 `hist`、`adm1_modern` 或 `geo` 规则。
4. **城市漏码**：新日期码没加到旧行的 `dates`，首都、港口会在新断面整体消失。
5. **CShapes 名称不是当时名称**：控制者、政治单元显示名都要经 `Namer`（`unit_names.csv`）或 `*_STATE_ON` 按日期改，否则会出现“Russia (Soviet Union)”之类。
6. **`admin.bin` 的追加段**：路径 A 依赖 `ww1-build.json` 的长度和校验值。任何对 `admin.bin` 的其他修改都会让 A 停下；正确做法是重建网页地图后再跑 A。
7. **2026 图层的单元编号是独立空间**，不能与历史 CShapes 编号混用（`ww1_maps.main` 中已排除）。
8. **年中以后成立的国家**取下一年人口；忘了会出现人口为空或被并入前宗主。
9. **今日轮廓误用为区划**：今日政区只作控制参照；要作区划，必须满足 §2 第 5 条并登记 `basis`。
10. **近似必须标出**：凡按整省、整区、`geo` 范围、沿用临近年份判定的控制，一律 `approximate`，否则地图不画斜线，读者会当成精确战线。
11. **受限网络**：1897 年俄国省界来自 `heidata.uni-heidelberg.de`，构建 B 时该域名需在允许列表中。

---

## 10. 提交约定

- 分支：在指定的开发分支上提交、推送；不直接推 `main`。
- 一批一个提交，标题英文、祈使式、写清日期，例如：
  `Add 1919-06-28, 1920-08-10 and 1923-07-24 snapshots (Versailles, Sèvres, Lausanne)`
- 正文：每个日期一两句：事件、阵营口径、主要控制取舍、哪些是近似；以及走的是 A 还是 B。
- 生成的二进制（`*.sqlite`、`geo-*.bin`、`admin.bin`）与生成它们的代码 / 整理表放在同一个提交里，或紧随其后的“Map data …”提交里。
- `README.md`、`ww2/README.md` 的断面表与说明同批更新。

## 11. 验证（仅在要求时执行）

已有的检查脚本，平时生产不跑，需要时再执行：

```sh
python3 scripts/verify_ww1_maps.py     # 路径 A：数据库连接、日期有效性、地图引用、历史断言
python3 scripts/verify_database.py     # 1900–2000 逐年数据库
```

路径 B 的数据库和覆盖率见 `ww2/coverage*.csv`；地图用 `cd ww2/maps && python3 -m http.server 8000` 打开 `http://localhost:8000/#<日期>` 目视检查。
