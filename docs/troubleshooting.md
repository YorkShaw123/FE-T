# 故障排查

## 桌面程序无法启动

确认 `雨生编辑器.exe` 与 `flora-server.exe` 在同一目录。若提示后端启动超时，先关闭残留的 `flora-server.exe`，再检查杀毒软件是否拦截 Sidecar。

本机开发时可直接运行：

```powershell
.\.venv\Scripts\python server\app.py
```

若浏览器能访问 `http://127.0.0.1:5000`，说明 Flask 本身可以启动，应继续检查 Tauri Sidecar 文件名和构建产物。

## API 请求失败

确认所选 Provider 与 API Key 来自同一服务商。Key 不会在重启后保留，需要重新输入。模型 ID、额度、地区限制和思考模式能力以服务商当前 API 为准。

## 本地向量化不可用

- “未安装可选依赖 onnxruntime”：源码环境安装 `requirements-local-embedding.txt`，发行版则重新构建包含运行时的 Sidecar。
- “模型缺失”或 manifest 校验失败：在文风管理中重新安装模型，或运行 `scripts\install-local-embedding.ps1`。
- 更换模型后检索提示签名不一致：重新向量化该语料库。
- 模型不可用但仍要生成：Style Retrieval 会降级为不含语义信号的本地检索。

## 向量化耗时较长

首次建立索引需要对所有片段执行 CPU 推理。应以界面显示的片段数、已用时间和预计剩余时间判断是否仍在工作。避免同时运行多个索引任务；若进度长期不变化，再检查后端日志、可用内存和模型文件。

## Rust 或 Tauri 构建失败

- `cargo` 找不到：安装 Rust MSVC 工具链，并确认 Cargo 在 PATH 中。
- NSIS 缓存损坏：关闭构建进程后清理 `src-tauri\target\.tauri\NSIS`，再重新构建。
- GitHub 资源下载超时：检查代理或网络后重试，不要把不完整缓存当作构建产物。
- Sidecar 命名错误：确认存在 `src-tauri\binaries\flora-server-x86_64-pc-windows-msvc.exe`。

## 杀毒软件误报

PyInstaller 单文件程序且未进行代码签名时可能被误报。当前构建已关闭 UPX，但无法完全消除信誉型拦截。开发测试可对可信的本地构建添加白名单；面向公开分发时应考虑代码签名。
