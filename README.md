# Codex Architecture Workflow

[简体中文](README.md) | [English](README.en.md)

一套面向建筑学习与设计实践的个人 Codex 工作流，把参考研究、场地证据、设计决策、原生建模、CAD 制图与交付检查连接起来。

**公开版 v0.1.0 · 中文优先 · MIT License**

本项目适合希望用 AI 协助建筑工作、同时保留设计判断和可编辑成果的学生、设计师与开发者。你可以只用其中一个模块，也可以让总控模块协调多阶段项目。它提供技能说明、参考方法、辅助脚本和部分本地桥接源码；桌面软件、模型服务与账号由使用者自行准备。

> An open-source, Chinese-first Codex workflow for architectural research, staged design, site analysis, editable modeling, CAD drafting, and evidence-based review. Six modular plugins; commercial applications and external services are installed separately.

> **请按本机情况调整：** 本项目来自一套独特的个人 Windows 配置。软件版本、安装路径、桥接和可用服务因设备而异，下载者需自行适配并验证后再用于实际项目。详见 [配置环境与迁移](docs/ENVIRONMENT.md)。

## 六个模块

| 模块 | 解决的问题 | 主要使用条件 |
|---|---|---|
| [`architecture-studio`](plugins/architecture-studio/skills/architecture-studio/SKILL.md) | 任务书到成果的跨阶段协调；恢复项目决定，关联模型、图纸和检查 | Codex；只读梳理与方案讨论无需商业建模软件 |
| [`architecture-aesthetics`](plugins/architecture-aesthetics/skills/architecture-aesthetics/SKILL.md) | 建筑方案、空间策略、理论、材料与表达的研习、比较和审阅 | Codex 与可读取的参考资料；持久库脚本需要 Python |
| [`site-analysis`](plugins/site-analysis/skills/site-analysis/SKILL.md) | 用真实地理、地形和气候数据生成可追溯的场地分析 | Python 及地理分析依赖；网络与可用的数据源 |
| [`su-model`](plugins/su-model/skills/su-model/SKILL.md) | SketchUp 结构化建模、局部修改、材质、视图与 SKP 交付 | 已授权的 SketchUp、对应扩展与 MCP 桥接 |
| [`cad-tz-model`](plugins/cad-tz-model/skills/cad-tz-model/SKILL.md) | AutoCAD 制图、量测、图层与真实 DWG/DXF 交付；可结合天正 | AutoCAD 2025 与桥接；天正操作另需天正 T30 |
| [`rhino-model`](plugins/rhino-model/skills/rhino-model/SKILL.md) | Rhino 曲线、曲面、实体及 Grasshopper 工作流 | Rhino 8 与外部 RhinoMCP；适用的桌面交互能力 |

## 从这里开始

1. 阅读 [安装说明](docs/INSTALL.md)，先安装 `architecture-studio` 和 `architecture-aesthetics`。
2. 提供一份任务书、参考图或已有项目说明，先完成只读分析与阶段划分。
3. 按任务需要添加其余模块。桌面建模前，按 [桥接说明](docs/BRIDGES.md) 配置并验证连接。
4. 在关键空间关系或代表性样段确定后，再推进依赖该决定的建模、制图与批量输出。

支持插件市场的 Codex CLI 可使用：

```powershell
codex plugin marketplace add 2536112822-droid/codex-architecture-workflow --ref main
codex plugin add architecture-studio@architecture-workflow
codex plugin add architecture-aesthetics@architecture-workflow
```

CLI 版本与功能可能变化；完整前提、其余模块和排障方式见 [INSTALL.md](docs/INSTALL.md)。安装技能不会自动安装商业软件或建立桌面连接。

## 可以直接使用的提示

**从已有资料开始，不急着建模：**

> 使用 $architecture-studio。先阅读我提供的任务书和图纸，恢复已确认决定，区分事实、推断和缺项。说明当前阶段要解决的问题、可评成果和完成依据；先提出少量有实质差异的空间方向，等我选定后再深化。

**学习一个案例：**

> 使用 $architecture-aesthetics 解析这组建筑资料。重点说明使用活动、空间组织、材料构造和表达如何共同支持方案，哪些方法适合迁移、需要什么条件。先展示分析，再让我选择是否保存及保存范围；不要自动写入长期偏好库。

**做有依据的场地分析：**

> 使用 $site-analysis，分析我提供的真实地址或经纬度及照片。先核对定位、研究范围和资料覆盖，区分真实地块边界与研究范围。输出来源可追溯的图和必要质量检查；缺失数据注明未知，不把示意内容当作实测。

**修改已有模型并保留原件：**

> 使用 $su-model。先确认当前模型身份、单位和修订，另存可恢复工作副本，再按我标出的范围修改。核对成品尺寸、实际通行净空和必要视图，保留可独立编辑的构件，最后验证 SKP 保存结果并说明未核实项。不要覆盖原件。

最后一条需要已经连接的 SketchUp；Rhino 或 CAD 任务可改用相应模块，并明确目标文件与修改范围。

## 工作方式

- **分阶段设计。** AI 自主完成阶段内研究、试做和基本检查；在会影响后续大量工作的节点提供具体成果、独立判断与关键取舍，由使用者决定下一步。
- **来源能回查。** 区分真实证据、模型表示、设计假设和方案分期。新资料先核对受影响对象，再更新相关成果。
- **保护可编辑原件。** 修改前保留可恢复副本；同一实时模型保持单一写入者；超时先查状态，避免重复写入。
- **检查与成果相匹配。** 图像支持视觉判断，实际模型与图纸支持几何、尺寸和可编辑性判断；保存成功不代表设计验收通过。
- **偏好由本人决定。** 案例知识、候选手法、长期偏好和项目规则分开；每轮学习展示结果后，由使用者选择是否入库及具体范围。

完整说明见 [工作流与边界](docs/WORKFLOW.md)。可按需手动采纳 [`templates/AGENTS.architecture.md`](templates/AGENTS.architecture.md)，它不会自动替换你的个人工作规则。

## 范围与依赖

本仓库公开可复用的工作方法与代码，不包含私人设计项目、聊天记录、个人审美库、账号配置、密钥或商业软件安装包。

SketchUp、AutoCAD、天正与 Rhino 需要使用者自行安装并取得适用授权。本仓库附带 MIT 许可的 RhinoMCP Python 服务源码和协议契约；Rhino 内的桌面插件仍需另行安装，来源见 [第三方说明](THIRD_PARTY_NOTICES.md)。Creative Production 属于第三方专有内容，本仓库不分发；图像、文档或演示等扩展能力可在相应工具可用时选用，不是基础研究与项目协调的前提。

工具可用性、软件版本、桥接状态与资料质量会影响执行范围。工作流不承诺无人干预完成设计，也不把 AI 表现图视为实测、施工或合规证明。公开版不能替代朋友在自己设备上的连接与保存验收。

## 仓库导航

- [安装与快速起步](docs/INSTALL.md)
- [设计协作、证据与验收](docs/WORKFLOW.md)
- [桌面软件桥接](docs/BRIDGES.md)
- [本次验证与未验证范围](docs/VALIDATION.md)
- [第三方来源与许可](THIRD_PARTY_NOTICES.md)
- [六个插件源码](plugins/)
- [许可证](LICENSE)

欢迎通过 [Issues](https://github.com/2536112822-droid/codex-architecture-workflow/issues) 报告可复现的问题。请说明模块、软件版本、预期与实际行为，并只提供可公开的最小样例；不要提交账号凭据、私人项目或未经允许的参考原件。



