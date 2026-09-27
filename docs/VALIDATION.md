# 发布验证 / Release validation

验证日期：2026-09-27；公开版 v0.1.0。下面只报告本次发布整理实际检查的范围。

| 检查 | 结果与适用范围 |
|---|---|
| 六个插件 manifest 与 SKILL | 官方本地校验器均通过；UTF-8 方式读取中文技能 |
| Codex 市场安装 | CLI 0.153.4，在隔离配置目录中注册本地仓库并安装六个插件成功；没有替换作者日用配置 |
| 仓库检查 | JSON / Python 语法、插件入口、图标引用、Markdown 本地链接、分发文件与明显凭据模式检查 |
| 自有自动测试 | 7 组、121 项通过：色彩检查25、审美库存取24、成果依赖24、CAD桥契约7、参数化面板19、场地分析16、SU桥契约6 |
| Windows 安装辅助脚本 | PowerShell AST、Node 语法；隔离的模拟 Plugins 目录中验证实际复制、哈希、WhatIf不写入和拒绝覆盖；配置输出可被 TOML 解析 |
| 天正命令索引 | 空表与用户外置 JSON 检索通过；不附厂商完整命令目录 |
| Rhino Python 运行时 | 在独立环境安装；初始化、列举68个工具、缺失文档提示通过；130份上游文件哈希与82份schema检查通过，非法GUID被拒绝；没有连接真实Rhino |

场地分析测试使用合成输入及模拟响应，覆盖缺失数据、来源与质量判断，不表示世界各地数据源在运行时都可访问。上游 Rhino 的全仓库同步测试涉及未收录的 C# 仓库，不计入上述 121 项；本分发的 Rhino 安装与协议检查见 [runtime 说明](../plugins/rhino-model/runtime/README.md)。

本轮没有在真实 SketchUp、AutoCAD 或 Rhino 文档中进行建模/制图，也没有重新验收真实模型保存、空间可用性和表现效果。AutoCAD C# 源码本轮没有重新编译：本机可用的 dotnet 只有运行时，没有 SDK。使用者需要按 [桥接说明](BRIDGES.md) 在自己的 SDK/软件环境中构建并验收。

原作者既有的使用经历不等于公开副本或另一台机器已通过同等测试。安装成功、协议可列举、模型正确、设计认可分别判断。

## English

Release checks on 2026-09-27 passed for six plugin manifests and skill files, isolated local marketplace installation with Codex CLI 0.153.4, and 121 tests across seven first-party suites. Installer checks covered syntax, simulated-folder copying and hashes, dry-run behavior, overwrite refusal, and parseable MCP configuration.

Geospatial tests use synthetic inputs and mocked responses. They do not prove live data-source availability. The full upstream Rhino repository tests are outside this reduced distribution; see the runtime guide for its separate checks.

The separate Rhino Python check passed installation, MCP initialization, registration of 68 tools, explicit reporting of excluded documentation, 130 upstream file hashes and 82 schemas, including rejection of an invalid GUID. It did not connect to a live Rhino document. The release constrains the Python MCP SDK to the compatible v1 API.

No live design document was modified during this release process. The AutoCAD C# bridge was not rebuilt because a .NET SDK was unavailable. Desktop connection, geometry, editability, visual quality and saved-file behavior must be checked on the downloader's device. See [Environment and adaptation](ENVIRONMENT.md).
