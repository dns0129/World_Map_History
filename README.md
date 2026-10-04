# World Map History · 世界历史地图数据

为“动态世界地图”收集整理的历史数据，分两部分：

| 部分 | 内容 | 说明 |
|---|---|---|
| **1900–2000 逐年世界数据** | 每年的实际控制政治地图、政治单元、人口与 GDP（总量和占比）、0.5° 人口网格、地形与河流，每年一张地图 | [docs/world-1900-2000.md](docs/world-1900-2000.md) |
| **1939–1945 历史省级区划与战局** | 六个断面上当日施行的省级区划（只用当时的区划，不用现代政区代替；被国界或战线穿过的省份按界线切开）、实际控制者、阵营、估计人口、重要城市；六张可交互地图，分阵营视图和各国控制区视图 | [ww2/README.md](ww2/README.md) |
| **1900–1934 四个断面** | 同样的省级区划、实际控制、阵营与城市：1900 年八国联军攻入北京、1914 年一战爆发、1918 年停战、1934 年长征开始 | [ww2/README.md](ww2/README.md#19001934-年的四个断面) |
| **2026 年当今世界** | 同一张地图的第七个标签页：当今的一级行政区、法理与实际控制、军事同盟、2025–26 年人口、首都与重要工业城市和港口 | [ww2/README.md](ww2/README.md#2026-年地图) |

![1942 年地图](maps/1942.png)

## 打开方式

先把仓库下载到本地：

```sh
git clone https://github.com/dns0129/World_Map_History.git
cd World_Map_History
```

### 1. 交互地图（1900–1945 十个断面与 2026 年）

地图页面需要从本地网页服务器打开。直接双击 HTML 文件时，浏览器会拦截数据文件的读取。任选一条命令启动服务器：

```sh
cd ww2/maps
python3 -m http.server 8000          # macOS / Linux
py -m http.server 8000               # Windows
npx --yes http-server -p 8000        # 已安装 Node.js 时也可以用这个
```

然后在浏览器中打开：

| 地址 | 内容 |
|---|---|
| http://localhost:8000/ | 默认 1942-11-01，页面上方可切换各个断面 |
| http://localhost:8000/1900-08-14.html | 八国联军攻入北京 |
| http://localhost:8000/1914-08-04.html | 英国对德宣战，一战全面爆发 |
| http://localhost:8000/1918-11-11.html | 贡比涅停战协定生效，一战结束 |
| http://localhost:8000/1934-10-16.html | 中央红军开始长征 |
| http://localhost:8000/1939-09-01.html | 德国入侵波兰 |
| http://localhost:8000/1940-07-01.html | 法国停战后 |
| http://localhost:8000/1941-12-07.html | 珍珠港事件当日 |
| http://localhost:8000/1942-11-01.html | 轴心国最大范围 |
| http://localhost:8000/1944-06-06.html | 诺曼底登陆日 |
| http://localhost:8000/1945-09-02.html | 日本签署投降书 |
| http://localhost:8000/2026.html | 2026 年当今世界 |
| http://localhost:8000/#1944-06-06/control | 任一页面后加 `#日期`，可直接跳到该断面；再加 `/nation` 或 `/control` 直接打开国家或控制国视图 |

停止服务器：在终端按 `Ctrl + C`。

地图功能：

- **视图：**
  - **阵营：** 按同盟国 / 轴心国 / 中立 / 前线着色，粗线为当日的法理国界和殖民地界。
  - **国家：** 每个国家按自己的法理领土着一种颜色，不计占领（1942 年的法国、波兰仍按原国界着色）；殖民地、保护国、委任统治地用宗主国颜色的浅色。
  - **控制国：** 各国的实际控制区，每个国家一种颜色，同一国家控制的地方连成一片。占领区算作占领国，例如 1942 年从法国北部到乌克兰都是“德国”；满洲国、蒙疆、维希法国、意大利社会共和国等傀儡政权单列。
  - 另有人口密度、区划资料两种着色。
- **底图：** 可在“地形”和“白色”之间切换。地形底图为分层设色加山体晕渲（低地浅绿、高原土黄、高山赭褐），白色底图为白底浅色的政区图；两种底图上山体阴影都叠在政区颜色之上。
- **地名：** 国名用小号宋体，固定在每块领土内部最中间的位置，只在名字放得进领土时显示，拖动、缩放时不会漂移。省名、河名同样由地图直接绘制，河名沿河书写。
- **点击层级：** 第一次点击选中国家（控制国视图为实际控制国，其他视图为法理上的国家 / 殖民地），面板显示人口、面积、所辖地区和主要省份；在该国范围内再点一次进入省级，显示省的历史资料和各块的实际控制者。面板顶部可从省返回国家。
- **省份与边界：** 只显示省级区划，当时的县、地区都并入所属的省。国界或战线穿过一个省时，省被切成几块，各块分别归属。
- **重要城市：** 标出首都（★，按当日的政府驻地，例如 1942 年的重庆、维希、新京，1944 年的萨勒诺和萨洛）、殖民地首府与临时政府驻地（◉）、重要港口（⚓）和工业城市（⚙）。鼠标停在城市上显示它当日的地位和简介。
- **2026 年：** 当今世界的一级行政区，可同样切换阵营（北约 / 集体安全条约组织）、国家（国际普遍承认的领土）和控制国（实际控制）视图，并标出各国首都和当今的主要工业城市、港口。
- **河流：** Natural Earth 1:1000 万河流湖泊，加粗、加深颜色；放大后加入欧洲、北美的细部水系。湖泊用 1939–45 年的样子（不含战后修的水库，咸海、乍得湖用 1960 年代以前的轮廓）。
- **查找：** 按中外文名称查找省份（如“京畿道”“Seine”“Kursk”）。
- **图层开关：** 省界、国界 / 控制线、山体晕渲、河流湖泊、地名、近似斜线、重要城市。

### 2. 数据库（SQLite）

| 文件 | 内容 |
|---|---|
| `db/ww2_divisions_1939_1945.sqlite` | 1939–1945 历史省级区划与实际控制 |
| `db/divisions_1900_1934.sqlite` | 1900–1934 四个断面的省级区划与实际控制（表结构相同） |
| `db/world_history_1900_2000.sqlite` | 1900–2000 逐年世界数据 |

几何存为 GeoJSON 文本，不需要 GIS 扩展。可以用命令行、Python 或图形界面打开：

```sh
sqlite3 db/ww2_divisions_1939_1945.sqlite
sqlite> .tables
sqlite> SELECT snapshot, bloc, SUM(population_est) FROM snapshot_full GROUP BY snapshot, bloc;
```

```python
import sqlite3, pandas as pd
con = sqlite3.connect("db/ww2_divisions_1939_1945.sqlite")
df = pd.read_sql("SELECT * FROM snapshot_full WHERE snapshot = '1942-11-01'", con)
```

图形界面可用 [DB Browser for SQLite](https://sqlitebrowser.org/)（免费）：打开文件后在 “Browse Data” 中选表或视图。

### 3. 逐年地图与导出文件（1900–2000）

```
maps/<年份>.png                 每年一张预览地图，直接用图片查看器打开
exports/years/<年份>.json       每年一份、结构一致的数据，供前端导入
exports/geometry/units.topojson 全部历史政治单元边界
```

### 4. 在线访问（可选）

- **GitHub Pages：** 在仓库的 Settings → Pages 中，把 Source 设为 “Deploy from a branch”，分支选 `main`、目录 `/ (root)`，保存。几分钟后地图可在 `https://dns0129.github.io/World_Map_History/ww2/maps/` 打开。
- **Claude Artifact：** 本仓库构建时另发布了一份私有链接（https://claude.ai/artifact/3s4bb36QVmiUUhQAaxUnXf）。只有所有者和被分享的人能打开。

## 目录

```
README.md                  本文件
docs/world-1900-2000.md    1900–2000 部分的说明（方法、表结构、核对结果、局限）
ww2/README.md              1900–1945 部分的说明（区划来源、省级合并、覆盖程度、控制判定、表结构）
ww2/maps/                  交互地图（index.html、每个断面一页、data/、vendor/）
ww2/coverage*.csv          各层级、各政治单元的省级区划覆盖程度（*_1900_1934 为早期四个断面）
db/                        两个 SQLite 数据库
exports/                   1900–2000 逐年导出文件
maps/                      1900–2000 逐年地图
curated/                   人工整理的控制事件、控制规则、名称对照
scripts/                   全部构建脚本
build_all.sh               一键重建
checks.json                1900–2000 数据库的核对结果
```

## 重建

所有数据都可以从原始来源重新生成。原始下载放在 `raw/`，中间文件放在 `work/`，这两个目录不提交。

```sh
pip install shapely pyproj rasterio numpy scipy pillow matplotlib pyshp pandas pyreadr osmium
./build_all.sh
```

全流程约 1.5–2 小时，需要下载约 4 GB：

- 1900–2000 部分约 30 分钟；
- 1900–1945 部分需要 OpenHistoricalMap 全球数据约 1.3 GB，构建约 2 小时。

各步骤见 `build_all.sh` 中的注释。

## 来源与许可

- **CShapes 2.0、中研院台湾历史图层：** CC BY-NC-SA 4.0，非商业。因此整个数据集只可用于非商业用途。
- **OpenHistoricalMap、Newberry 美国县界史、Natural Earth、K. Lawson 东亚图层：** CC0 或公有领域。
- **地形：** Mapzen / AWS Terrarium 高程瓦片（SRTM、GMTED2010、ETOPO1 等，见其说明）；地图文字字形取自 OpenMapTiles 字库的 Noto Sans（SIL OFL）。
- **GHS-POP、geoBoundaries：** CC BY 4.0（2026 年人口用 GHS-POP 2025）。
- **人口与 GDP 序列：** 联合国 WPP、Gapminder、Maddison Project，许可见各自来源。

完整引用写在两个数据库的 `sources` 表中。本仓库的代码与 `curated/` 整理表为 CC0。
