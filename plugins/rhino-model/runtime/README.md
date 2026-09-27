# RhinoMCP Python 运行时

此目录保留 [RhinoMCP](https://github.com/jingcheng-chen/rhinomcp) 的 Python server 0.3.2 和协议契约，来源提交为 `235169c397c6f57984639797daeffd537199db5d`。上游文件、逐文件 SHA-256 与唯一替换文件见 [UPSTREAM_MANIFEST.json](rhinomcp/UPSTREAM_MANIFEST.json)，许可见 [LICENSE](rhinomcp/LICENSE)。不包含 Rhino 内的 Yak 插件、商业软件或虚拟环境。

从仓库根目录使用自己的 Python 3.10+ 创建独立环境：

```powershell
python -m venv .venv-rhino
& .\.venv-rhino\Scripts\python.exe -m pip install -c './plugins/rhino-model/runtime/constraints.txt' -e './plugins/rhino-model/runtime/rhinomcp/server[validation]'
```

必须使用上述 editable 安装，保留 `server` 与相邻 `contracts` 的目录关系；普通 wheel 安装不包含上游的外置契约。`[validation]` 安装必需的 `jsonschema`，约束文件避免安装移除了 FastMCP API 的 MCP SDK 2.x。安装后 stdio 入口为 `.venv-rhino/Scripts/rhinomcp.exe`，无需参数；契约目录为 `plugins/rhino-model/runtime/rhinomcp/contracts`。按仓库桥接说明启用 strict 校验、回环地址及三个执行工具的禁用门禁。

可在同一环境中运行不连接实际 Rhino 的检查：

```powershell
& .\.venv-rhino\Scripts\python.exe -B ./plugins/rhino-model/runtime/verify_runtime.py
```

原上游附带的 RhinoScript 提取文档被替换为明确说明“本发布未包含”的小型适配文件，相关文档查询工具仍注册，但会返回这一限制。结构化建模与 Grasshopper 工具不依赖该文档数据。

安装及 MCP 协议检查不证明已经连接 Rhino、创建了模型或通过桌面建模验收。实际使用还需安装对应 Rhino Yak 插件，启动 `MCPStart` 并核对活动文档。
