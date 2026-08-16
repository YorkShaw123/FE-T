# Style Engine 架构

## 1. 目的

本文区分 Flora 当前可运行架构和 Style Engine 的目标架构。目标架构是渐进方向，不代表相关模块已经实现。

## 2. 当前架构

Flora 是 Windows 本地桌面应用：

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

已实现的 `AuthorStyleProfile` 以 corpus 为单位，保存 Style Feature 版本、median/MAD/分位数、robust normalizer、样本量、有效字符和 reliability。它与现有 `StyleProfile` 完全不同：后者是由 LLM 分析单篇范例得到的 Style Card，不得与本地统计画像混用或相互覆盖。

Scene/Mode Profile 是 Author Style Profile 的子结构，不另造标签体系：

- 继续使用 chunk 已有的 `dialogue/action/psychology/environment/transition/narration/mixed`；
- 面向写作模式时，`description` 映射 `environment`，`exposition` 映射 `narration`；
- 精确模式样本不足时，依次回退到 `dynamic/reflective/narrative` 宽类和 global Profile；
- pacing、pov、emotion 作为沿用现有标签的 facet 聚合，不参与新的场景推断。

重建 Author Profile 前会检查 chunk Feature 版本。如果发现旧版本或无效 payload，系统使用原 chunk 和同 article Style Window 原地重算；正文、场景标签、FTS 和 Embedding 不变。

### 4.5 Style Diff / Similarity

比较目标语料与待生成/已生成文本，输出差异方向、置信度和可解释建议。相关 Feature 需要分组或降权，不能把高度共线指标当作多份独立证据。

### 4.6 Local Retrieval and Reranking

从语料中选择文风相近、主题泄漏较低且彼此多样的参考片段。候选信号可包括 Feature 距离、BM25、现有 Embedding 和去重复惩罚，但每个信号必须可关闭、可测试、可基准比较。

已实现的 Style Retrieval Engine 继续使用 `hybrid_search_style` 公共入口和现有候选过滤，但排序改为 Style-first：

- candidate Style Window Feature 与对应 global/scene Author Profile 做 robust 距离；
- V1.1 只输出已实现的 Rhythm、Punctuation、Function/Grammar 三组；
- 可选 semantic 与 BM25 只是小权重辅助，无 API Key 时仍可本地检索；
- Content Leakage Penalty 检测忽略标点/空白后的 8-gram、较长连续字符串和内容词组重合；
- MMR 有 Embedding 时结合向量相似度，无 Embedding 时回退到字符 n-gram diversity。

检索返回保留旧 `score/vector_score/bm25_score` 字段，并增加分组 Style Score、scene/semantic 得分、leakage penalty、confidence 和完整 `ranking_explanation`，因此现有调用方可向后兼容。

### 4.7 Style Guidance Adapter

把少量显著 Feature 差异转换成可执行的中文写作约束，再交给现有 `prompt_assembler.py`。它不改变生成 API 的必填参数，也不把几十项原始统计直接塞入 Prompt。

### 4.8 Reuse Risk Guard

在选择片段和检查生成结果时检测过长连续复用、字符 n-gram 重合和近重复。它是独立安全层，不能只依赖 Prompt 中“不要照抄”的文字要求。

### 4.9 Embedding Backends

Embedding 不是 Style Engine 的核心依赖，只提供低权重 semantic/scene 辅助信号：

```text
Style Retrieval
  ├─ Style Feature/Profile（主信号，始终本地可用）
  ├─ LocalEmbeddingBackend（可选，ONNX Runtime CPU）
  ├─ RemoteEmbeddingBackend（兼容路径，需用户 API Key）
  └─ 无可用 backend → semantic_score = null，继续 Style-first 检索
```

统一 backend 必须声明 `backend_id/model_id/model_version/dimension`。该完整签名同时写入 corpus 和 chunk；查询向量与库存向量的签名必须完全一致，禁止仅凭维度相同而混用。更换模型、模型版本或维度后，旧索引标记为需要重建，但原 chunk、Style Feature、Author Profile 和 FTS 数据不删除。

本地模型存放在 `%USERPROFILE%\.flora-editor\models`（开发时可用 `FLORA_MODELS_DIR` 覆盖），不存入 SQLite，也不随单文件后端打包。ONNX Session 进程内复用，CPU batch 推理；模型/运行时缺失是预期的可降级状态。

当前落地产物（2026-08-16）：`BAAI/bge-small-zh-v1.5` 官方权重由项目脚本导出为 opset 17 ONNX（512 维、CLS pooling、L2 normalization），manifest 固定记录来源、许可、导出器版本及模型/词表 SHA-256。ONNX Runtime 随正式 sidecar 构建，约 95 MB 模型仍作为用户目录外置资产；PyTorch/Transformers 只用于隔离的一次性导出，不属于运行时或发行包。

首版本候选比较：

| 方案 | 中文/维度 | 模型体积与 CPU | ONNX / 打包影响 | 许可与结论 |
|---|---|---|---|---|
| 现有 BGE-M3 远程接口 | 多语种，1024 维 | 本地无模型，但依赖网络和 API Key | 保留现有 HTTP 兼容能力 | 仅作可选远程增强，不是默认 |
| `BAAI/bge-small-zh-v1.5` | 中文，512 维，官方 C-MTEB retrieval 61.77 | 官方 safetensors 约 95.8 MB；4 层/512 hidden，普通 CPU 候选中较轻 | BERT 结构可导出 ONNX；`onnxruntime` Windows x64 wheel 约 13–14 MB，模型必须外置 | MIT；选为首个本地候选 |
| multilingual-e5-small | 多语种，384 维 | 通常更小，但 Flora 默认中文，不需要为多语种牺牲中文基准 | 同样需要 ONNX 与前缀协议适配 | 当前不采用，保留未来多语种选项 |

选择 `bge-small-zh-v1.5` 不是把 Embedding 当作文风模型：它只验证“同场景语义高于无关场景”。官方源模型不等于可直接分发的 ONNX 产物；正式发布前仍需固定导出流程、opset、模型 SHA-256 和真实 Windows CPU 基准。若这些验证失败，可替换 backend 而不影响 Style Feature/Profile。

### 4.10 Style Signature

Style Signature 补充 Dense Features 无法表达的局部功能结构习惯，但它不是普通字符 n-gram：

```text
Style Window
  → 仅识别冻结的功能词 / 代词 / 结构原子 / 规范化标点
  → 相邻 1～3 token 候选（内容字符会中断）
  → corpus DF、总频次、全覆盖过滤
  → 最多 192 维的 corpus 词表
  → chunk 每千有效字符向量
  → Author / Scene Profile robust statistics
  → version-compatible signature_score
```

词表是 corpus-specific：`signature.000` 在不同 corpus 中不保证对应同一模式，因此只允许 chunk 与其所属 corpus Profile 比较。实际模式文本和 token 同时保存在 Profile 词表中以便解释。`signature_version` 必须在 corpus、chunk 和 Profile 三处一致；不一致时先重建，无法重建时忽略 Signature 并对 Dense 组重新归一化。

Style Score 的组内权重为 Rhythm 0.32、Function/Grammar 0.28、Punctuation 0.20、Signature 0.20。Signature 不改变外层 Style/Scene/Semantic/BM25/Leakage 权重，也不参与内容泄漏检测或 MMR 内容多样性计算。

### 4.11 Style Diff

Style Diff 是无副作用的诊断层，不是自动改写器：

```text
generated text
  → 与 corpus 相同的 Style Feature Analyzer
  → resolve scene / broad / global target Profile
  → robust normalized deviation
  → reliability × profile confidence × text-length confidence
  → 偏差门槛 + 共线簇限流 + importance 排序
  → 最多 5～8 条结构化差异
```

每项差异包含 generated value、目标 median/P25～P75、robust deviation、severity、中文解释和一条可执行重写指令，同时保留 global median/deviation 作为场景 Profile 的对照。本层不会修改原文，也不会自行把建议发送给 LLM。

当前 Diff 只覆盖 Feature V1.1 已实现的 Dense Features。Signature 模式属于 corpus-specific 稀疏结构，尚未冻结逐模式的人类改写语义，因此不在 M10 冒充可操作 Diff；dialogue ratio、叙事结构与修辞同理，必须等对应版本化 Feature 存在后再加入。

### 4.12 Strict Style Rewrite

Strict Style Rewrite 是现有生成流水线的可选末段，不是另一套生成系统：

```text
Style Retrieval / Prompt 注入
  → Draft
  → 可选去 AI 味
  → 本地 Style Analyzer + Style Diff
  → 无显著差异：直接结束
  → 有显著差异：同一 LLM 最多重写一次
  → Final
```

开关默认关闭，因此旧请求不会增加 API 调用。开启后仍要求存在版本有效的 Author Profile；多 corpus 时使用最高排序参考片段所属 corpus 作为目标，并在 Diff 中记录目标 ID。重写继续携带原生成消息和参考片段，追加少量自然语言 Diff 指令；它必须保持剧情、事实、人物、世界观、已有信息和用户要求，只调整语言形式，并明确禁止复制参考语料的内容实体、事件和独特表达。同步与流式路径共用相同准备逻辑，自动次数硬限制为一次。

### 4.13 Style Retrieval Debugger

现有 Style Corpus 检索测试直接展示 Style-first 排序的解释数据，不另建检索实现：

- 默认层显示综合、Style、Rhythm、Punctuation、Function/Grammar、Signature、Scene、Semantic、Leakage Penalty 和 confidence；
- 每个候选只选择最多 4 条高可靠 Feature 接近/差异理由，再补充场景或对话比例匹配，不展示完整 Feature 列表；
- 展开层显示实际 Profile fallback、各组参与 Feature 数、BM25 排名分和内容重合分解；
- meta 显示 query 的本地规则场景、实际过滤场景，以及每个 corpus 的 global Author Profile 和 query 对应 scene/broad/global Profile 摘要。

Debugger 只扩展返回字段与原生 JavaScript 展示，不改变既有 `score/content/items` 字段、检索排序权重或生成 Prompt。场景判定是规则诊断信息，必须在 UI 中与用户显式筛选分开标示。

### 4.14 Final Benchmark

最终 Benchmark 与在线生成解耦：先用同一写作任务获得并冻结 Baseline、旧 Style RAG、Style Retrieval 和 Strict Rewrite 四份真实结果，再由离线 CLI 复用当前 Analyzer、Profile、Scene 和 Leakage 函数统一评分。该边界避免为了复现实验恢复旧算法，也避免重复请求 LLM 带来的费用和随机漂移。

Benchmark 输入 manifest 同时固定候选正文、实际注入片段、人工参考样本和盲测种子。报告正文不混入盲测方法映射；自动指标只能作为表层风格和复用风险证据，不能替代匿名人工判断。

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
