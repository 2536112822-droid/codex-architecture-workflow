# 配置环境与迁移 / Environment and adaptation

## 这是一套个人环境中形成的工作流

原始工作流长期运行在个人 Windows / PowerShell / Codex 环境中，并连接本机安装的建筑软件。其可用性依赖具体版本、软件安装位置、桌面桥接、权限、模型服务和数据源。公开版已移除私人路径并做必要的参数化，但它不是已经覆盖所有机器的通用安装包。

**请下载者按自己的设备调整，再做代表性验证；不要直接复制作者整套个人配置。** 不使用某个专业软件时，可只安装研究与总控模块。

| 项目 | 本工作流的来源或面向环境 | 下载者应调整 / 检查 |
|---|---|---|
| 系统与终端 | Windows、PowerShell；部分 Python 方法可跨平台 | 路径分隔符、执行入口、写入权限；桌面桥未承诺跨平台 |
| Codex | 本次插件打包验证使用 CLI 0.153.4 | 自己版本是否支持 plugin marketplace；工具是否在新会话中注册 |
| Python / Node.js | Python 3.12、Node.js；各模块依赖分开 | 真实解释器而非商店占位别名；建议独立虚拟环境 |
| SketchUp | 桌面版 Ruby 扩展 + 本地 MCP 适配器 | 本机版本、Plugins 文件夹、Ruby 接口兼容与端口；不要用 Web 版替代 |
| CAD / 天正 | AutoCAD 2025 / .NET 8；天正 T30 为可选协同软件 | SDK 引用目录、插件编译、NETLOAD、启动程序与命令版本 |
| Rhino | Rhino 8 + RhinoMCP | Rhino 端插件、Python MCP 服务、contracts 位置、开关与版本匹配 |
| 图像与文档工具 | 由当时可用的 Codex 工具或外部插件提供 | 账号权限、实际工具注册与计费方式；本仓库不携带这些服务 |
| 场地数据 | OSM、地形和气候等公开数据源 | 所在地区覆盖、网络、许可、精度和缺失数据 |
| 审美资料库 | 用户自己选定的本地目录 | `ARCH_TASTE_HOME` 或 `--home`；正式入库仍需当轮选择 |

推荐迁移顺序：先做一次只读参考分析，再验证所需桥接的状态读取，接着在新建的可丢弃测试文件上操作，最后才进入实际项目副本。分别核对文件身份、单位、几何/可编辑性、视图和保存结果。

自动测试和插件安装验证只证明各自检查的范围；它们不等于三款桌面软件在另一台电脑上的实际建模、制图与保存验收。参考 [安装说明](INSTALL.md) 和 [桥接说明](BRIDGES.md)。

## English

This workflow grew out of a specific personal Windows, PowerShell and Codex setup. It depends on particular application versions, installation paths, desktop bridges, permissions, model services and data sources. The public package removes personal paths and exposes configurable settings, but it is **not a universally tested turnkey installer**.

Adapt it to your own computer. Check your Codex plugin commands, Python and Node executables, desktop application versions, SDK paths, plugin folders, loopback ports, bridge contracts and service permissions. Commercial applications and accounts must be supplied separately. You may use just the research and coordination modules.

The original CAD target is AutoCAD 2025 with .NET 8, with Tianzheng T30 as an optional integration. Rhino targets Rhino 8. SketchUp requires the desktop Ruby environment. This release's packaging checks use Codex CLI 0.153.4 and Python 3.12; these checks do not establish a universal minimum version or compatibility with every platform.

Start with a read-only task, then a bridge status query, then a disposable test document. Confirm document identity, units, native geometry, editability, visual output and saved-file behavior before using a real project copy. Automated tests and successful skill installation do not replace this device-specific acceptance check.
