# 桌面软件桥接安装

技能文件负责工作方法；桌面软件桥接负责读取和修改实际模型。只安装技能不等于已经连接 SketchUp、AutoCAD 或 Rhino。以下面向 Windows，示例从仓库根目录执行。

**这是个人工作环境的公开迁移版本，不保证下载后原样即用。** 原环境的软件版本、安装位置、插件与桥接配置有特定组合；每位使用者都需要按实际情况调整版本、路径、解释器、插件加载方式和 Codex MCP 配置，再完成连接与小范围操作验收。示例中的路径仅作格式演示，没有包含原作者真实个人目录。

公开版保留 SketchUp 与 AutoCAD 桥接源代码，删除个人绝对路径、构建缓存、既有 DLL/PDB、来源不明的图片和厂商完整命令表。商业软件、Autodesk SDK 引用程序集和软件许可均需使用者自行准备。本仓库的 MIT 许可不覆盖这些产品。

## 运行要求

| 组件 | 前提 | 连接方式 |
| --- | --- | --- |
| SketchUp | 桌面版 SketchUp；原工作流以 2025 为基线；Node.js 18+ | Ruby 服务只监听 `127.0.0.1:45678`；Node MCP 无 npm 依赖 |
| AutoCAD | Windows AutoCAD 2025、Python 3.10+、.NET SDK 8+ 用于编译 | C# 桥只监听回环端口 `45679–45699`；Python MCP 核心仅标准库 |
| 天正 | 与 AutoCAD 相匹配的已授权天正安装 | 从当前 AutoCAD 实例中识别已加载模块，再执行用户本机支持的命令 |
| Rhino | Rhino 8、匹配的 RhinoMCP 桥与严格契约 | 使用 `MCPStart` / `MCPStop`，仅回环端口 `1999`；见 [Rhino 配置说明](../plugins/rhino-model/skills/rhino-model/references/local-runtime.md) |

上述版本说明是源工作流的目标环境，不代表每个更新版本均已测试。公开副本的静态/契约检查不能替代你机器上的连接和保存验收。

## SketchUp

找到你所用版本的用户 Plugins 目录。示例中的 `2025` 必须与你实际版本一致；目录需要已存在。

```powershell
./scripts/install-bridges.ps1 -Target SketchUp `
  -Destination "$env:APPDATA\SketchUp\SketchUp 2025\SketchUp\Plugins" -WhatIf

./scripts/install-bridges.ps1 -Target SketchUp `
  -Destination "$env:APPDATA\SketchUp\SketchUp 2025\SketchUp\Plugins"
```

脚本安装 `su_model_launcher.rb` 与 `su_model_runtime/`，不会覆盖同名文件。升级前先保留现有安装备份。安装脚本不启动软件，也不关闭未保存的模型；在自行保存现有工作并重新打开 SketchUp 后，扩展菜单中的「SU AI 建模」提供启动、停止和状态检查。启动器会延迟尝试启动本地服务。

公开版没有工具栏 PNG 和材质纹理包；按钮/文字菜单仍可使用。自检中找不到 `textures/concrete.png` 时保留纯色材质并明确返回 `texture=SKIP`，这不表示纹理功能通过测试。实际项目请使用你有权使用的纹理并核对模型效果。

服务脚本按安装目录相对定位；高级用户可以在 SketchUp 启动前设置 `SU_MODEL_SERVER` 指向自己的 `su_server.rb`。

## AutoCAD / 天正

AutoCAD 桥从源代码编译，不发布本机已有二进制。准备 .NET SDK 8 或更新的兼容 SDK，使用实际 AutoCAD 2025 安装目录中的 `acmgd.dll`、`acdbmgd.dll`、`accoremgd.dll`；这些程序集不会复制到发布包或安装 bundle。

```powershell
./scripts/install-bridges.ps1 -Target AutoCAD `
  -AutoCADDir 'C:\Program Files\Autodesk\AutoCAD 2025' `
  -Destination "$env:APPDATA\Autodesk\ApplicationPlugins"
```

`-Destination` 要求是已存在的 ApplicationPlugins 目录。使用便携 SDK 时附加 `-DotNetExecutable 'C:\path\to\dotnet.exe'`。脚本拒绝覆盖已有 `TzServer.bundle`，构建中间文件留在仓库 `work/bridge-build-*`。成功后按 AutoCAD 的可信插件加载设置加载 bundle；无需也不应为了本项目全局关闭安全加载。脚本不会调整信任列表、启动 AutoCAD 或写入图纸。

如果只需编译审查：

```powershell
dotnet build ./plugins/cad-tz-model/runtime/autocad/TzServer.csproj `
  -c Release '-p:AutoCADDir=C:\Program Files\Autodesk\AutoCAD 2025'
```

`cad_screenshot` 额外依赖 Pillow 与 pywin32。用运行 MCP 的同一个 Python 环境安装：

```powershell
python -m pip install -r ./plugins/cad-tz-model/runtime/requirements-screenshot.txt
```

自动启动器可使用 `CAD_TARCH_LAUNCHER` 指定天正 EXE，或 `CAD_AUTOCAD_EXE` 指定 AutoCAD EXE。没有配置时只检查标准 AutoCAD 2025 安装位置。多个实例必须用工具选定目标；不能把「进程存在」当作活动图纸已确认。

公开版的 `tz_cmds.json` 是空数组。`tz_cmds` 返回空结果不表示天正未安装，也不影响普通 CAD 几何操作。可设置 `CAD_TZ_COMMANDS_FILE` 指向用户自行维护、仅在本机使用的 JSON 文件：数组元素包含 `cmd` 和 `label` 字段。命令名称与参数应按用户安装版本的帮助确认，不把厂商完整目录提交进本仓库。

## 生成 Codex MCP 配置片段

以下只打印配置，**不修改**全局 `config.toml`。显式传入真实解释器路径，避免 Windows Store 的 `python.exe` 占位别名：

```powershell
./scripts/install-bridges.ps1 -Target McpConfig `
  -NodeExecutable 'C:\Program Files\nodejs\node.exe' `
  -PythonExecutable 'C:\path\to\python.exe'
```

输出包含 `[mcp_servers.su]` 和 `[mcp_servers.cad]`，使用当前仓库位置的绝对脚本路径。检查现有注册后再合并到 Codex 设置；如果插件或其它配置已经提供同一 MCP，只保留一个注册来源。移动仓库或 Python 环境后需重新生成。Rhino 使用独立配置和验证，不能套用这两个入口。

## 连接后的最小验收

1. 保存原件，打开一个明确的测试副本，确认唯一目标实例与文档。
2. SketchUp 调用 `su_ping`、`su_info`；AutoCAD 调用 `cad_discover`、`cad_state`；Rhino 调用能力与活动文档摘要。安装脚本完成不表示这一步通过。
3. 在测试副本验证一个小构件的单位、位置、修改、撤销/回滚与另存，再从保存文件独立读回。视觉检查另外核对相机、材质和可见性。
4. 再执行批量任务，保存时使用明确的新文件名。同一模型只保留一个写入者。

所有桥接仅面向可信本机使用，未实现远程用户认证。不要暴露或转发端口。SketchUp 的 `su_eval` 是能执行任意 Ruby 的高级备用入口，普通任务应优先使用结构化计划；只连接可信 MCP 客户端。无须使用时可在客户端禁用此工具并在软件中停止服务。

## 源码检查

```powershell
python -B -m unittest discover -s ./plugins/su-model/runtime/tests -v
python -B -m unittest discover -s ./plugins/cad-tz-model/runtime/tests -v
node --check ./plugins/su-model/runtime/mcp/server.js
```

这些测试不打开设计软件，不验证实时几何、安装后的 UI、用户许可或最终模型质量。Rhino 单独使用其 runtime 测试与 preflight；preflight 的静态就绪和实时就绪分开报告，仍需实际活动文档确认。
