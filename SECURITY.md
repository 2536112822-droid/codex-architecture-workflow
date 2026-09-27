# 本地桥接边界 / Local bridge boundaries

SketchUp、CAD 和 Rhino 桥接可以读取和修改本机文档，部分入口也可执行脚本。仅在可信本机环境使用，保持回环地址，不公开端口、不转发到公网。连接模型前核对活动文档，修改重要原件前保存可恢复副本。

These bridges can read and modify desktop documents; some interfaces can execute code. Keep them on loopback in a trusted local environment. Do not expose or forward their ports. Verify the active document and create a recoverable working copy before important edits.

插件安装只加载工作方法，不会自动安装商业软件、改写全局配置或启用 Rhino 高权限选项。外部服务接收到的数据由实际使用的工具和授权决定；不要把“本地资料库”理解为模型推理必然离线。

Skills do not install commercial applications, rewrite global configuration or enable privileged Rhino operations automatically. Model and external-tool data handling depends on the chosen service; a local reference library does not imply offline inference.
