# 本地 Embedding

## 当前方案

Flora Editor 的 Style Engine 不要求远程 Embedding。默认语义辅助后端是 `BAAI/bge-small-zh-v1.5` 的 ONNX CPU 推理，模型维度为 512；模型 Session 在进程内缓存，不会为每次请求重新加载。

远程硅基流动 `BAAI/bge-m3`（1024 维）仍作为手动选择和旧索引兼容方案保留。远程模式需要硅基流动 API Key。本地与远程后端不会混用向量。

## 安装模型

“文风管理”中的“下载本地 ONNX 语义向量引擎”按钮用于检查安装状态并展示安装步骤。为避免桌面服务静默下载和安装大型依赖，实际安装需要在项目根目录显式运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-local-embedding.ps1
.\.venv\Scripts\python scripts\verify_local_embedding.py
```

安装脚本使用一次性导出环境取得官方权重并生成本地 ONNX 文件。模型默认安装到：

```text
%USERPROFILE%\.flora-editor\models\bge-small-zh-v1.5
```

可用 `FLORA_MODELS_DIR` 覆盖 models 根目录。旧品牌模型目录存在时，程序会继续读取以避免重复下载。

模型目录包含 `manifest.json`、`model.onnx` 和 `vocab.txt`。启动后会校验清单和文件完整性；模型不写入 SQLite，也不会加入 Git。

## 运行时

源码开发环境需要安装可选运行时：

```powershell
.\.venv\Scripts\python -m pip install -r requirements-local-embedding.txt
```

默认构建脚本使用 `-BundleLocalEmbedding` 将 ONNX Runtime 打入 `flora-server.exe`，但模型权重仍单独安装在用户目录。若手动运行 `scripts\build-backend.ps1` 且不传该开关，则生成的后端不含 ONNX Runtime，只能使用纯 Style Engine 或远程兼容后端。

## 索引与降级

- 安装或更换模型后，对已有语料库重新执行“向量化”。
- 索引记录后端、模型版本和维度；签名变化时程序会要求重建，不会静默使用旧向量。
- 本地运行时、模型或校验文件不可用时，文风检索会省略语义信号，而不是让整个 Style RAG 失败。
- 百万字语料的首次向量化是批处理任务，耗时取决于 CPU、片段数量和磁盘；界面会显示片段进度、耗时和预计剩余时间。

本地 Embedding 只测试语义/场景相关性，不用于证明作者文风相似度。
