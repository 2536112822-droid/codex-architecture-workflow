# 安装与快速起步

建议先安装研究与总控模块，完成一次只读任务，再按需要连接建模软件。无需一次装齐六个模块。

## 1. 确认使用条件

基础使用需要能够加载本仓库技能的 Codex 环境，以及你有权使用的模型服务。下面的命令适用于提供插件市场功能的 Codex CLI；本仓库不附带 Codex、账号、订阅或 API 密钥。

先查看当前 CLI 支持的入口：

```powershell
codex --version
codex plugin --help
codex plugin marketplace --help
```

如果当前版本没有这些命令，先核对你安装的 Codex 版本及其官方插件说明。不要把旧版 CLI 的命令缺失误判为插件损坏，也不要直接覆盖现有个人配置来排障。

## 2. 添加市场并安装基础模块

仓库的市场索引位于 [`.agents/plugins/marketplace.json`](../.agents/plugins/marketplace.json)，市场名称为 `architecture-workflow`。

```powershell
codex plugin marketplace add 2536112822-droid/codex-architecture-workflow --ref main
codex plugin add architecture-studio@architecture-workflow
codex plugin add architecture-aesthetics@architecture-workflow
```

`main` 会随项目更新。准备长期使用或复现特定成果时，应记录实际采用的仓库提交与插件版本，避免把更新后的行为当作旧版已验证行为。

安装后，在 Codex 的技能或插件列表中核对这两个模块是否可见。若当前对话尚未出现新技能，按你所用客户端的刷新或新会话方式重新加载，再做只读核对。安装成功并不证明外部桥接已连接。

## 3. 完成第一次只读任务

提供一份你有权使用的任务书、图片或项目说明，然后发送：

> 使用 $architecture-studio。先只读我提供的资料，概括项目目标、已确认决定和关键缺项，提出当前阶段的成果与完成依据。暂不改动模型、不写入长期审美库。

或：

> 使用 $architecture-aesthetics 学习这组参考。说明设计思路、空间关系和迁移条件，区分可见事实与推断。分析完成后列出可保存的方面，等我选择后再入库。

检查回答是否引用了实际读到的资料、是否明确未知项，以及是否把你的设计决定留在合适的节点。完成这一步无需 SketchUp、AutoCAD、天正或 Rhino。

## 4. 按任务添加专业模块

```powershell
codex plugin add site-analysis@architecture-workflow
codex plugin add su-model@architecture-workflow
codex plugin add cad-tz-model@architecture-workflow
codex plugin add rhino-model@architecture-workflow
```

| 使用范围 | 另外需要什么 | 先验证什么 |
|---|---|---|
| 场地分析脚本 | Python、模块所列依赖、网络和可用数据源 | 地址/坐标、研究范围、依赖与数据获取；正式图面另做数值与视觉检查 |
| 审美持久库 | Python；由你选择的本地资料库位置 | 实际解析的库路径；任何正式入库先完成当轮范围选择 |
| SketchUp 建模 | SketchUp、SU 扩展和 MCP 适配器 | 工具发现、连接、能力、活动模型与单位 |
| AutoCAD / 天正 | AutoCAD 2025、TzServer 和 MCP 适配器；天正操作需要 T30 | 实例、文档、单位、修订和命令状态 |
| Rhino / Grasshopper | Rhino 8、外部 RhinoMCP、适用的桌面交互能力 | 桥接归属、文档路径、单位、公差与对象状态 |

本地桥接的源码、构建条件、安装入口及外部依赖见 [BRIDGES.md](BRIDGES.md)。仓库提供的 `scripts/install-bridges.ps1` 仅处理该文档说明的范围，不会替你购买、安装或授权商业建模软件。

场地分析的 Python 依赖列在 [`requirements.txt`](../plugins/site-analysis/skills/site-analysis/scripts/requirements.txt)。建议在独立虚拟环境中准备依赖，避免改变其他项目环境。首次正式分析必须核对来源与质量报告；跳过数据源的测试结果不能作为完整场地分析交付。

## 5. 可选工作规则与扩展能力

[`templates/AGENTS.architecture.md`](../templates/AGENTS.architecture.md) 提供可选择采纳的建筑协作规则。先阅读，再把需要的部分合并到你自己的项目规则中；不应自动覆盖全局 `AGENTS.md`，也不需要为了使用插件复制作者的私人设置。

图像生成、PDF、文档和演示工具可按实际交付需要选用，并遵守它们自己的安装与使用条件。Creative Production 是第三方专有内容，本仓库不内嵌、不授予其使用许可；基础研究和协调无需安装它。RhinoMCP 的必要 Python 源码及契约随仓库提供并保留 MIT 署名；Rhino 端插件仍需按上游说明单独安装。

不要把整个个人 Codex 配置目录、账号文件或历史审美库复制进本仓库。需要密钥或服务配置时，应使用相应工具支持的本地配置方式，避免提交到 Git。

## 6. 把安装与运行验收分开

开始真实项目之前，依次确认以下状态：

1. **插件可见：** Codex 能发现所需技能，且读到正确版本。
2. **工具可用：** 需要的 MCP 工具已注册，目标软件与桥接已连接。
3. **目标明确：** 活动文件、单位和状态对应本次任务，多实例时先选定目标。
4. **副本可恢复：** 真实修改前建立工作副本或必要备份。
5. **成果可核验：** 适用的几何、可编辑性、视觉与保存检查都有实际证据。

当前设备的安装通过，不等于其他设备或所有软件版本已通过。遇到问题时先区分命令不支持、插件未启用、工具未注册、桥接未连接和具体调用失败，再处理对应环节。输出超时先查文件或文档状态，不盲目重放写入。

报告问题时可在 [GitHub Issues](https://github.com/2536112822-droid/codex-architecture-workflow/issues) 提供模块名称、版本、具体步骤及脱敏后的报错。不要附带凭据、私人模型或未经许可的案例原件。

