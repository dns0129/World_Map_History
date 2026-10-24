# 描图资料的来源与复现

`curated/` 中按历史地图描出的数据，分两类：

- **自动描出**：按颜色提取、按特征匹配转移控制点等。脚本都在 `scripts/trace/`，可以从原图重新生成。每个脚本都有 `--check`：从原图重做一遍，与仓库中的文件逐字节比较，不写入。
- **目视读出**：控制点、转折点、边界是在原图上逐点读出的。读数本身就是原始资料，直接保存在 `curated/` 中，原图只用于核对。

原图下载到 `raw/trace/`（不提交）。下载地址和 sha256 写在 `sources.json` 的 `files`、`nids` 两节，下载脚本核对校验值，原图有变就停下。

## 自动描出（`scripts/trace/`）

| 数据 | 原图 | 脚本 | 内容 |
|---|---|---|---|
| `curated/atlas_1945.json` | 美国陆军部《Atlas of the World Battle Fronts》PDF（`sources.json` → `files.atlas_1945`），第 82、86、90、94、98 页 | `trace/atlas_1945.py` | 页面图像（`pdfimages`）；控制点（`curated/trace/atlas_1945_cities.json` 中 93 个城市圆点，按霍夫圆检测校正，再用 SIFT 单应变换转到其他各页）；盟军区（粉红、深红）按颜色提取，并向海面外扩；各页图框 |
| `curated/ccp_areas.json` 中 `north_china_1942_09` 的轮廓 | 战史丛书第 50 卷附图第五（NIDS `050_332`） | `trace/ccp_050_332.py` | 红色网点按颜色提取，8 像素格密度、平滑、填洞，去掉图上 4 个文字框 |
| `curated/china_front_1942.json` 中 `055_294` 的主线与线后据点 | 战史丛书第 55 卷附图第二（NIDS `055_294`） | `trace/china_055_294.py` | 蓝线按颜色提取；在 `curated/trace/china_055_294_waypoints.json` 的转折点之间，沿蓝线求最短路径 |

NIDS 附图由 `trace/nids.py` 下载。图像只在同一会话中先打开该卷页面和附图页面之后才会给出，服务器有时会返回错误页，所以最多重试四次。

完整复现某一项：

```sh
python3 scripts/trace/atlas_1945.py --check    # 与仓库比较
python3 scripts/trace/atlas_1945.py            # 重写 curated/atlas_1945.json
python3 scripts/atlas_fronts.py                # 再生成 curated/frontlines_1945/
```

## 目视读出（原图只用于核对）

| 数据 | 原图 | 读出的内容 |
|---|---|---|
| `curated/lagekarten_1941.json` … `1944.json` | 德俄数字化项目的 OKH 态势图 Lage Ost（wwii.germandocsinrussia.org，各条目的 `url`；网站条款只允许研究用途，原图不复制） | 每月的德军主战线，以经纬度写出（个别图幅以像素读出、带控制点）；`note` 记下图上依据 |
| `curated/loc_west_1944.json` | 美国国会图书馆 HQ Twelfth Army Group 每日态势图（各条目的 `url`、`image`；像素为 IIIF 图像 pct:50） | 控制点（经纬网交点或城镇）、战线、据点；同一图幅的各期用 SIFT 转移控制点 |
| `curated/china_front_1937.json` | JACAR 北支那方面军作战经过要图（`sources.json` → `files.jacar_*`）、NIDS 附图（`nids` 一节） | 各关键日日军所及范围（`reach`、`add`、`cut`，经纬度） |
| `curated/ccp_areas.json` 中其他轮廓与全部控制点 | NIDS `050_331`、`018_323`、`050_332` | 陕甘宁边区界、晋察冀边区界（像素）、城镇控制点 |
| `curated/china_front_1942.json` 中的控制点、海上闭合线、`fix` | NIDS `055_294` | 57 个城镇控制点等 |
| `curated/trace/*.json` | 同上 | 自动描图的起点：城市圆点、转折点 |

改动目视读数后，按各数据的生成脚本（`atlas_fronts.py`、`ccp_areas.py`、`frontlines_china.py`、`lagekarten.py`、`frontlines_west.py`）重新生成，再重建追加的断面，并运行 `scripts/verify_geometry.py`。
