---
name: site-analysis
description: Build reliable architectural site-analysis diagrams from a site location and user-provided imagery using real open geospatial, elevation, and climate data. Use for site context, figure-ground, circulation, land use, slope/aspect, solar, wind, photo viewpoints, and presentation-ready analysis boards.
metadata:
  short-description: 真实数据驱动的场地分析图与九宫格总板
---

# 场地分析

## 文件保存与收尾

文件暂存、正式保存、中间数据保留与清理遵循当前全局 AGENTS.md 和本任务已有授权。已有授权或默认策略覆盖的事项直接执行，只询问仍缺少的必要决定；本节优先于下文及参考文件中的保存和保留默认值。


把坐标、边界、照片与公开数据转换为可追溯的建筑场地分析。先按请求选择范围：完整场地分析包交付单图、3×3 总板、来源、质量报告和哈希清单；单项分析、已有图板修改或事实查询只完成对应成果与必要核验。

## 核心规则

- 至少需要一个真实位置：优先使用经纬度，其次使用可核验地址。无法定位时只问一次，不得编造。
- 所有距离、面积、坡度与比例尺都在本地 UTM 米制坐标系计算。
- 红色虚线圆表示研究范围，不是地块红线；只有用户提供带 CRS 的边界文件时，才画红色实线地块边界。
- 把内容区分为 `fact`（来源数据）、`inference`（设计判断）和 `unknown`（待确认）。数据缺失不等于要素不存在。
- 用户截图和无 GPS 照片只能作为视觉证据；没有控制点时不得声称已精确配准。

## 按范围执行

- 续做已有分析时先读 `latest.json`，再按问题读取该 run 的 manifest、质量报告、来源或目标图；相关位置、口径与源数据仍适用时复用，不机械重抓所有数据。
- 单项事实查询直接给来源与限制；单项制图提供需要的可编辑/矢量和预览成果，不强制扩展成整板。
- 下列完整流水线适用于新建或确需重算的整套分析；现有脚本会生成整套成果，不声称它支持未实现的局部重算。局部修订另存版本并记录来源，不混用不同 run 的数据伪装成一次运行。

## 完整分析包工作流

1. 确认场地中心、研究半径、名称和可选边界；记录用户图像的来源与尺度锚点。
2. 若有照片，先运行 `scripts/ingest_imagery.py`，提取 EXIF GPS 并生成 `imagery_manifest.json`。
3. 运行 `scripts/analyze_site.py`，将 `--out-dir` 指向本任务暂存区。它会获取 OSM/Overpass、SRTM 与 Open-Meteo 数据，缓存原始数据，并生成唯一运行目录；这些是工作数据，正式交付按全局保存策略执行。
4. 打开 `quality_report.json` 与 `provenance.json`；`fail` 必须修复，`warn` 必须在交付中说明。
5. 用 `view_image` 检查 `00_analysis_board.png`，重点看北箭头、比例尺、研究范围/真实边界、图例、裁切、字体与空数据面板。
6. 如果视觉或数值不合格，修正输入或脚本后创建新 run；不要覆盖旧 run，也不要从旧目录拼接成果。
7. 展示 `latest.json` 指向 run 的成果，报告坐标、CRS、数据年份、质量与限制；按全局保存策略和本任务授权交付所需文件，核对依赖和 manifest。各 runs、原始下载和失败版本按全局保留策略处理；共享缓存不纳入任务清理，不重问已有决定。

## 命令

```powershell
python <skill-dir>/scripts/analyze_site.py `
  --site-name "Newcastle study site" `
  --lat -32.9283 --lon 151.7817 --radius 500 `
  --site-boundary "site.geojson" `
  --out-dir "site-analysis-output"
```

边界未知时省略 `--site-boundary`。可用 `--climate-start`、`--climate-end`、`--climate-model` 固定气候数据口径；调试时才使用 `--skip-osm`、`--skip-elevation` 或 `--skip-climate`。

```powershell
python <skill-dir>/scripts/ingest_imagery.py `
  --input-dir "site-photos" --out-dir "site-analysis-output" --copy
```

脚本首次运行可在当前项目创建 `.venv` 并一次性安装依赖。正式成果不能依赖跳过数据源的离线烟测。

## 完整分析包输出质量门

- `00_analysis_board.{png,svg,pdf}`：六张主图 + 项目指标 + 数据来源 + QA 状态。
- `01`–`06` 单图均提供 PNG/SVG/PDF；不得只交位图。
- `quality_report.json`：投影、范围、POI 几何、DEM 覆盖、风速单位、边界和 OSM 层检查。
- `provenance.json`：请求端点、时间、CRS、输入、缓存来源和生成器哈希。
- `manifest.json`：仅列本次运行创建的文件，并包含 SHA-256；`latest.json` 指向最新 run。
- 北箭头必须向上/真北，比例尺必须使用投影坐标的真实米数，气候风速统一为 m/s。
- SRTM 约 30 m，只支持场地趋势判断，不可替代测绘或土方设计。

需要决定分析图组合和绘图语法时，读取 [analysis_catalog.md](references/analysis_catalog.md)。发布前读取 [data_sources.md](references/data_sources.md) 和 [output-contract.md](references/output-contract.md)。
