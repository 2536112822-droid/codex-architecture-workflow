# 第三方来源与发布范围

本仓库收录个人建筑工作流、技能说明及配套源代码。根目录许可证适用于本仓库自己的贡献；外部软件、数据和引用资料保留各自的许可与使用条件。

## RhinoMCP：随附的 MIT 源码与外部桌面插件

Rhino 工作流使用 [Jingcheng Chen 的 RhinoMCP](https://github.com/jingcheng-chen/rhinomcp)。本机整理时对应 server 0.3.2、提交 [`235169c397c6f57984639797daeffd537199db5d`](https://github.com/jingcheng-chen/rhinomcp/commit/235169c397c6f57984639797daeffd537199db5d)。上游 [MIT 许可证](https://github.com/jingcheng-chen/rhinomcp/blob/235169c397c6f57984639797daeffd537199db5d/LICENSE)标注 `Copyright (c) 2026 Jingcheng Chen`。

为使严格协议校验可复现，本仓库在 [Rhino runtime](plugins/rhino-model/runtime/README.md) 内收录必要的 Python server 源码与相邻 contracts，保留上游 [LICENSE](plugins/rhino-model/runtime/rhinomcp/LICENSE) 及逐文件来源哈希。收录的 130 个上游文件保持原字节；上游附带的 RhinoScript 提取文档没有打包，该位置使用本仓库的小型适配文件，让相关文档工具明确返回“未包含”。结构化建模工具不依赖这份文档数据。

不包含 Rhino 内的 Yak 安装包或 Python 虚拟环境。使用者另行安装所需桌面插件与依赖，并保留各自许可证。

## 未纳入的本机组件

- **Creative Production**：本机插件 manifest 标为 `Proprietary`，来源为 OpenAI 的 `oai-maintained-plugins`。本仓库不复制其技能、服务代码、模板或素材；相关工作流中的提及仅说明可选集成。
- **天正完整命令表**：原工作区中的完整目录从已安装软件的 `tchcmd.txt` 提取，没有随本仓库分发。命令检索数据应由使用者从自己的安装中本地生成；生成的数据仍保留在本机。
- **原有 SketchUp 材质图片**：原工作区的砖、混凝土、金属、木材四张 PNG 缺少随附来源记录，未纳入本仓库。运行时可加载使用者自行提供且有权使用的贴图。
- **商业桌面软件与编译产物**：不包含 SketchUp、AutoCAD、天正、Rhino、Autodesk SDK 程序集、预编译桥接 DLL、安装包或授权文件。使用相应集成需要自行安装软件及所需开发环境。
- **私人资料**：不包含个人审美库、项目模型、参考原件、对话历史、记忆、账户配置或凭据。

## 方法与数据来源

技能参考文档保留了方法来源链接，包括建筑教育与实践框架、设计理论和软件项目。部分方法借鉴已经在对应段落说明，例如成果依赖检查对 text-to-cad 思路的适配；引用不表示相关项目为本仓库背书，也不表示已接入其代码或服务。

场地分析运行时可获取 OpenStreetMap、SRTM 与 Open-Meteo 数据。本仓库未打包这些数据集；生成成果须保留来源、日期和相应署名，详见 [数据来源说明](plugins/site-analysis/skills/site-analysis/references/data_sources.md)。用户提供的照片、地图截图及其他参考资料也不因被工具处理而改变其权利归属。

Node.js、Python、.NET 及 Python 依赖均由使用者另行安装；本仓库不重新授权这些依赖。
