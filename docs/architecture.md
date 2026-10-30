# 程序结构

`scripts/` 中的脚本分成七层。一个模块只导入同层或下层的模块；`tests/test_layers.py` 检查这一点，新脚本必须先在那里归入某一层。

| 层 | 模块 | 作用 |
|---|---|---|
| 数据 | `common`、`added_dates`、`controllers`、`ww2_territories` | 路径、常量和按日期写出的事实：追加断面的配置（`added_dates`），各断面的控制者名称、阵营、东亚占领图层规则（`controllers`），岛屿属地。只含数据和极简的规则函数，不导入 numpy、shapely 等 |
| 库 | `topo`、`georef`、`mapdata`、`ww2_common`、`ww2_geo`、`cities`、`sources` | 共用的读写与几何：TopoJSON、地图配准、网页数据格式、几何工具、城市表、来源清单 |
| 来源 | `fetch_sources`、`ww2_fetch`、`ww2_ohm`、`okh_lage_ost`、`scripts/trace/*`、`lagekarten`、`frontlines_*`、`ccp_areas`、`atlas_fronts` | 下载原始资料（按 `sources.json` 锁定的版本），以及把描图读数换算成 `curated/` 中的战线与区域 |
| 构建 | `build_*`、`ww2_reference`、`ww2_histunits`、`ww2_snapshots`、`ww2_provinces`、`ww2_database`、`ww2_relief`、`modern_2026`、`add_snapshots` | 1900–2000 逐年数据库（`build_*`）；三个时期的事件日（路径 B）；追加断面（路径 A） |
| 导出 | `export_years`、`render_maps`、`ww2_webmap`、`ww2_html`、`publish_artifact`、`data_release`、`game_economy` | 逐年导出与地图、交互地图的数据与页面、发布到 Artifact 和 GitHub Release、游戏的人均 GDP 表 |
| 检查 | `verify_*`、`ww2_coverage` | 数据库、追加断面、几何的检查，覆盖率 |
| 运行 | `pipeline` | 按依赖和指纹调度构建步骤；每步在单独的进程中运行，所以它只导入数据层和库层 |

唯一的向上导入：`add_snapshots` 用 `ww2_webmap` 的配色和标注函数写出追加断面的地图数据（`tests/test_layers.py` 的 `ALLOWED`）。

## 两条路径与控制规则

- **路径 B**（`pipeline.py`）从历史区划和 CShapes 逐日构建事件日：`ww2_snapshots.py` 依次取 CShapes 主权、整单位控制事件（`curated/control_events.csv`）、东亚占领图层（`controllers.OVERLAY_RULES`）、地区规则（`curated/*_region_control.csv`，最后命中者为准）。
- **路径 A**（`add_snapshots.py`）从某个基准日的区划出发追加日期，规则写在各组的 `curated/<组>_region_control.csv`，日期配置写在 `added_dates.py`。
- 两条路径共用 `controllers.bloc()`（阵营）和 `controllers.STATE`（1939–45 的控制者名称）。路径 B 中各日期的名称、阵营、特例和东亚图层规则都是 `controllers.py` 里的数据，代码里不再按日期写分支。

## 主程序的结构

较长的主程序都按“读取 → 计算 → 写出”拆开，计算部分可以单独调用和测试：

| 脚本 | 读取 | 计算 | 写出 |
|---|---|---|---|
| `ww2_snapshots.py` | `read_inputs(dates)` | `pieces_on(snap, inp)`、`estimate_population(cur, snap, inp)` | `write_outputs(rows, piece_geom)` |
| `ww2_webmap.py` | `read_snapshots()` | `admin_index(...)`、`unit_outlines(...)`、`one_snapshot(ctx, k)` | `main` 中写 `admin.bin`、各断面文件、`index.json` |
| `modern_2026.py` | `Countries()` | `provinces()`、`carve_pieces()`、`dejure_units()`、`colours()`、`control()`、`snapshot_rows()`、`estimate_population()` | `write_outputs(...)` |
| `build_yearly.py` | `read_inputs()` | `calibrated_grids()`、`unit_grid()`、`stage2()`、`aggregate()`、`unit_year()` | `write_static(X)`、`write_outputs(...)` |
| `build_database.py` | — | `unit_year_named()`、`sovereign_aggregates()` | `write_meta()`、`write_units()`、`write_pieces()`、`write_inputs()`、`write_grids()`、`write_rasters()`、`write_physical()` |

## 游戏（`game/`）

文明时代 demo 不经过 Python 构建：它在浏览器里读取交互地图的同一批数据文件（`ww2/maps/data/`，格式见 `scripts/mapdata.py`），只多一个由 `scripts/game_economy.py` 写出的 `game/economy.json`（各历史单位在各断面年份的人均 GDP）。模块按“读取 → 棋盘 → 规则 → 电脑 → 页面”分开，前四个不碰页面，可以在 Node 中运行：

| 模块 | 作用 |
|---|---|
| `data.js` | 解码 `geo-<日期>.bin`，读 `snap-<日期>.json` 与 `admin.bin`，给出每个地图要素（省或切块）的轮廓与名称 |
| `geometry.js` | 由轮廓算出棋盘：0.05° 网格上共用的边界格即陆上相邻；0.1° 陆地栅格上从海岸向海面逐格扩散，两省的扩散在 2° 内相遇即隔海峡相望（路径不穿过陆地，有共同邻省的不算）；省内标注点；点所在的省 |
| `rules.js` | 剧本（开局控制、核心、首都、按断面的战争与同盟、兵力、人均 GDP 与战力）、经济、行军与战斗、外交、回合结算、存档 |
| `ai.js` | 电脑国家：议和、结盟、偶尔进攻弱小邻国、花钱、按威胁布防、集中兵力进攻、把内地兵力送往前线或港口 |
| `main.js` | 页面：MapLibre 地图（沿用地图页的地形底图与字形）、开局选择、顶栏数据、省份与国家面板、调兵、外交、排行、大事记、本机存档 |

## 测试

```sh
python3 -m unittest discover tests      # 不需要原始资料和构建结果，约 1 秒
node --test tests/game/game.test.js     # 游戏（tests/test_game.py 也会在装有 Node.js 时运行它）
```

单元测试覆盖规则匹配（两条路径）、阵营与东亚图层规则、网页数据格式的编码与追加记录、配准与加密、人口取整、整区划块的轮廓判断、发布分批、数据发布的打包与下载校验、流水线的模块依赖和分层。改动构建脚本后，结果是否逐字节不变仍要用实际数据核对（见 `docs/snapshot-sop.md`）。
