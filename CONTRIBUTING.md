# 参与维护 / Contributing

欢迎提交可复现的问题或小范围改进。请写清插件、软件版本、预期与实际行为，并使用可公开的最小输入。不要上传个人图纸、私有模型、资料库、登录配置或凭据。

Please report the module, software versions, expected behavior and observed result, using a minimal public example. Do not submit private projects, reference libraries, authentication files or credentials.

开发检查（Python 3.12、Node.js）：

```powershell
python -m pip install -r requirements-dev.txt
python scripts/run_checks.py
```

`python scripts/run_checks.py --core` 只跳过地理数据测试，仍需 Pillow。测试使用合成数据和协议检查，不会修改实时 SketchUp、CAD 或 Rhino 文档。桌面行为变更需要额外在工作副本中验证，并报告范围。

Changes to desktop behavior require a separate check on a recoverable working copy. Unit and protocol tests do not prove visual quality, spatial usability or compatibility with every application version.

本仓库采用 MIT 许可证。提交第三方代码或素材时保留原许可与出处；没有再分发许可的内容只提供接入说明。
