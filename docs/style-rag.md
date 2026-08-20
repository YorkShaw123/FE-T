# Style RAG 与 Style Engine

## 用户目标

Style RAG 用于中文写作中的文风参考，而不是世界知识问答。用户可导入大规模参考文章；系统在生成时选择 3～5 个与当前写作场景相配、文风接近且内容不过度重合的片段。

## 数据流程

```text
TXT / DOC / DOCX
  → 文档文本提取
  → 语料切片与规则标签
  → Style Window
  → 本地 Style Feature / Signature
  → Author 与 Scene Profile
  → 可选 Embedding 索引
  → Style Retrieval + 内容复用惩罚 + 多样性重排
  → 仅将原始 current chunk 注入提示词
```

单个上传文件上限由 Flask 配置为 20 MB；单个语料库最多 5000 个片段。Style Window 可结合相邻片段提高统计稳定性，但不会跨文章边界，最终注入仍只使用当前片段。

## 主要排序信号

当前检索以本地、可解释的文风相似度为主要信号，包括：

- 句长与段落节奏
- 标点习惯
- 功能词和基础句法
- Style Signature
- 场景标签和统计画像可靠性

语义 Embedding 和 SQLite FTS5/BM25 是辅助信号。检索还会检查关键词、字符 n-gram 和连续长字符串等内容重合，降低把相同剧情或独特表达当作文风参考的风险。MMR 或本地等价相似度用于避免返回的多个片段彼此过于相似。

详细特征口径、架构和评测计划位于 [style-engine/](style-engine/README.md)。

## Embedding 兼容规则

Embedding 是可插拔辅助能力：

- 默认后端：本地 ONNX Runtime CPU，`BAAI/bge-small-zh-v1.5`，512 维。
- 兼容后端：硅基流动 `BAAI/bge-m3`，1024 维，需要对应 API Key。
- 没有可用模型或运行时：降级为不含 semantic score 的 Style Engine 检索。

语料索引会保存 backend、model ID、model version 和 dimension。查询时签名必须完全一致；本地与远程向量、不同模型或不同维度不能混用。更换模型后应重新向量化。

注意：`server/config.py` 中的 `EMBEDDING_MODEL` 是远程兼容后端配置，不代表默认 UI 模式；`/api/style-corpora/embedding-config` 和文风管理界面都将本地后端设为默认。

## 数据存储

片段、标签、Feature、Profile、Signature 和向量存入用户 SQLite 数据库。向量以 float32 BLOB 保存，检索时用 NumPy 矩阵计算，不依赖独立向量数据库。本地模型文件单独放在用户 models 目录，详情见 [local-embedding.md](local-embedding.md)。
