# Rhino 运行环境与迁移

这套工作流来自个人 Windows 环境。本机的 Rhino 版本、插件版本、配置方式及安全门禁具有特定组合；下载后的内容是迁移起点，不能保证未经调整便可使用。按你的实际安装位置、Python 环境和 RhinoMCP 能力修改配置，再进行只读连接和小范围验收。不要把示例路径当作已存在的本机路径。

## 随仓库提供与需要自行安装的部分

- 原工作流目标：Rhino 8 与社区 RhinoMCP Yak 插件 0.3.2。其它组合需重新验证。
- `runtime/rhinomcp/` 提供 MIT 许可的最小上游 Python MCP server 与 contracts；来源、具体提交与裁剪说明见该目录说明。Rhino 桌面插件（Yak）、Rhino 商业软件与许可不在包内。
- stdio 可执行入口由用户 Python 虚拟环境安装生成，不分发 `.venv` 或本机二进制。
- 仅 `127.0.0.1:1999`；在 Rhino 中使用 `MCPStart` / `MCPStop` 启停。
- 不自动写入全局 Codex 配置。插件本身不再注册第二个 Rhino MCP；只保留一个启用来源。

## Python 侧安装示例

以下从仓库根目录执行，使用你已安装的 Python 版本（具体下限以 runtime 的 pyproject.toml 为准）。如果没有 `py` 启动器，换成真实 Python EXE 的绝对路径。

```powershell
py -3 -m venv ./work/rhino-venv
./work/rhino-venv/Scripts/python.exe -m pip install -c './plugins/rhino-model/runtime/constraints.txt' -e './plugins/rhino-model/runtime/rhinomcp/server[validation]'
```

保留 editable 安装：这个上游实现需要从源码目录定位相邻 `contracts/`。移动仓库后应重新安装并修改入口路径。安装会下载 Python 依赖；由使用者在本机自行执行。

自行安装匹配的 Rhino Yak 插件后，把下面示例中的 `C:/path/to/repository` 换为实际绝对路径。先检查已有 `[mcp_servers.rhino]`，避免重复注册。

```toml
[mcp_servers.rhino]
command = 'C:/path/to/repository/work/rhino-venv/Scripts/rhinomcp.exe'
args = []
default_tools_approval_mode = "writes"
disabled_tools = ["run_command", "execute_rhinoscript_python_code", "execute_rhinocommon_csharp_code"]

[mcp_servers.rhino.env]
RHINO_MCP_HOST = "127.0.0.1"
RHINO_MCP_PORT = "1999"
RHINO_MCP_ALLOW_REMOTE = "0"
RHINO_MCP_VALIDATE = "strict"
RHINO_MCP_ENABLE_RUN_COMMAND = "0"
RHINO_MCP_ENABLE_RHINOSCRIPT = "0"
RHINO_MCP_ENABLE_CSHARP = "0"
RHINO_MCP_DEBUG = "0"
```

`disabled_tools` 与服务侧三项执行门禁均应保留。具体配置字段能否被所用 Codex 版本识别，仍需按实际客户端核对；不能用写入配置成功代替工具行为验证。

## 检查和启动顺序

```powershell
./plugins/rhino-model/skills/rhino-model/scripts/preflight.ps1 `
  -RhinoExe 'C:\Program Files\Rhino 8\System\Rhino.exe' `
  -ServerExe (Resolve-Path './work/rhino-venv/Scripts/rhinomcp.exe').Path `
  -ContractsDir (Resolve-Path './plugins/rhino-model/runtime/rhinomcp/contracts').Path
```

脚本还支持 `-YakExe`、`-PluginVersion`、`-PluginManifest`、`-ShortcutPath` 与 `-ConfigPath`。没有指定快捷方式时不要求桌面快捷方式存在。也可用 `RHINO_MCP_SERVER` 与 `RHINO_MCP_CONTRACTS` 指定前两项路径。`-ConfigPath` 应与当前 Codex CLI 实际使用的配置一致；脚本同时检查 CLI 报告的有效 `rhino` 注册。

1. 首次连接、升级或排障运行 preflight。它只检查安装、配置、进程与监听，不写模型。
2. 若 Rhino 已打开，先唯一锁定目标窗口；否则按你已验证的入口启动。不要强制结束已有未保存会话。
3. 端口未监听时在目标窗口执行 `MCPStart`。端口已监听时先取得 `get_document_summary`，确认预期文档。
4. 取得 `describe_capabilities` 和当前文档摘要后，在工作副本验证小范围操作、撤销/回滚和另存读回，再批量建模。

preflight 将 `static_ready` 与 `live_ready` 分开报告。静态成功、端口监听、工具列表成功都不证明实际模型可编辑或已可靠保存。多个 Rhino 进程、非回环监听、端口归属不符时不得猜测写入对象。多个 stdio 子进程可能属于不同任务，不应直接强杀。

## 升级与差异

当前接口来自社区 RhinoMCP。不要与其它 Rhino MCP 实现并行注册后假定同名工具具有相同语义。升级 Rhino、Yak 包、Python server 或迁移其它实现时，先复核版本、工具参数、contracts、门禁和保存行为，再单套替换。官方文档提取资产未在最小源码包中重分发，涉及这些资料的功能应按 runtime 说明处理。

