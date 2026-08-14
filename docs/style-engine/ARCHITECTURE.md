# Style Engine 架构

## 1. 目的

本文区分 Forestar 当前可运行架构和 Style Engine 的目标架构。目标架构是渐进方向，不代表相关模块已经实现。

## 2. 当前架构

Forestar 是 Windows 本地桌面应用：

```text
Tauri 桌面壳
  └─ 启动并管理 Flask Sidecar
       ├─ server/routes/          HTTP 输入输出
       ├─ server/services/        业务逻辑
       ├─ server/database/        SQLite 模型与幂等迁移
       ├─ server/templates/       页面
       └─ server/static/          原生 JS/CSS
```

当前风格相关调用链概括如下：

```text
TXT/DOC/DOCX 导入
  → style_corpora_routes
  → style_rag_service
  → 段落切片与规则标签
  → SQLite 保存 corpus/document/chunk
  → 可选远程 Embedding 写入 float32 BLOB
  → 生成时使用向量 + BM25 + RRF + MMR 检索片段
  → prompt_assembler
  → generation_service
  → api_client 调用用户选择的生成模型
```

并行存在两条较小规模的风格链：

- `style_profile_service.py`：调用外部模型分析范例，形成抽象 Style Card。
- `style_excerpt_service.py`：切分范例并产生场景、视角、节奏等标签，供生成时选片段。

当前 Style RAG 的语义 Embedding 有利于找“内容相近”的片段，但文风模仿需要更多主题无关的表层和结构特征。这是 Style Engine 要解决的核心差距。

## 3. 目标架构

目标是在现有 Style RAG 旁增加本地分析、风格画像、比较和检索能力：

```text
原始中文语料
  → 统一文本规范化与边界识别
  → 本地 Feature Extractor
  → 文档/切片 Feature
  → SQLite 版本化存储
  → Corpus Style Profile 聚合
  → 本地 Style Diff / Style Similarity
  → 风格检索与多样性重排
  → 可执行 Style Guidance
  → 现有 prompt_assembler
  → 现有 generation_service / API
```

旧的语义检索可以在迁移期作为可选信号继续存在，但默认 Style Engine 不要求远程 Embedding。最终采用何种 Embedding 模型不在当前阶段决定。

## 4. 组件职责

### 4.1 Text Normalizer

负责 Unicode、空白、段落、句界和逻辑标点的一致处理。它必须是确定性的，并向 Feature Extractor 提供结构化统计单元。具体规则要经过测试和 Benchmark 后才冻结。

### 4.2 Feature Extractor

纯本地提取版本化的中文文风 Feature。首版候选范围仅包括节奏与长度、标点习惯、功能词和基础句法代理，不负责主题、情绪、文学流派等抽象判断。

### 4.3 Feature Store

通过现有 SQLite 和迁移机制保存：分析对象、Feature 版本、原始值、可用性、样本统计和计算时间。设计时应优先考虑：

- 旧数据库可升级；
- 旧 Style RAG 表和数据不变；
- 同版本分析可缓存并重算；
- Feature 版本不兼容时不会静默混用。

本阶段不冻结表名和字段，数据库方案应在对应 milestone 开始前写入执行计划并评审。

### 4.4 Corpus Style Profile

从多个文档或切片聚合作者/语料库风格。必须保留样本量和离散程度，不能只保存一个平均值；短文本和异常片段不能过度支配结果。

### 4.5 Style Diff / Similarity

比较目标语料与待生成/已生成文本，输出差异方向、置信度和可解释建议。相关 Feature 需要分组或降权，不能把高度共线指标当作多份独立证据。

### 4.6 Local Retrieval and Reranking

从语料中选择文风相近、主题泄漏较低且彼此多样的参考片段。候选信号可包括 Feature 距离、BM25、现有 Embedding 和去重复惩罚，但每个信号必须可关闭、可测试、可基准比较。

### 4.7 Style Guidance Adapter

把少量显著 Feature 差异转换成可执行的中文写作约束，再交给现有 `prompt_assembler.py`。它不改变生成 API 的必填参数，也不把几十项原始统计直接塞入 Prompt。

### 4.8 Reuse Risk Guard

在选择片段和检查生成结果时检测过长连续复用、字符 n-gram 重合和近重复。它是独立安全层，不能只依赖 Prompt 中“不要照抄”的文字要求。

## 5. 兼容策略

- 新能力默认以可选字段或内部服务加入；旧调用方不传新参数时保持原行为。
- 现有 Style RAG 数据只读兼容，不做破坏性重写；新索引失败时应能回退到旧路径。
- Schema 仅通过 `server/database/migrations.py` 增量迁移，迁移必须幂等。
- Feature、Profile 和 Benchmark 结果必须记录版本；跨版本比较需要显式迁移或重算。
- Style Profile/Excerpt 的 LLM 抽象标签可作为辅助信息，但不得伪装成本地 Feature 或填补缺失值。

## 6. 性能和依赖边界

- 目标语料规模约 100 万中文字符。
- 运行环境是普通 Windows CPU 电脑；核心分析不得要求 GPU。
- 算法优先单次线性扫描、批量 SQLite 操作和紧凑 NumPy 数组。
- 不引入 PyTorch、TensorFlow、独立向量数据库或常驻服务。
- 新依赖必须说明发行包体积、启动时间、内存、许可证和 PyInstaller 兼容性；标准库或现有依赖能完成时不新增依赖。

## 7. 关键风险

- 文本主题、对话比例和体裁会与作者风格混杂。
- 中文切句、引号和省略号规则不同会显著改变统计结果。
- 短文本 Feature 方差大，容易产生虚假差异。
- 直接注入原文片段可能提高复制风险。
- 高度相关的 Feature 会重复计权。
- 本地规则可能稳定但不够准确；抽象 AI 标签可能丰富但不可复现。

这些风险由 Feature 版本化、分层 Benchmark、复用风险检测、最小样本门槛和逐 milestone 验收共同控制。

