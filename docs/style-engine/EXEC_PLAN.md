# Style Engine 执行计划

> 本文件是 Style Engine 实施范围、状态和验收标准的唯一计划入口。  
> 状态取值：`未开始`、`进行中`、`已完成`、`阻塞`。  
> 原则：一次只推进一个可验收 milestone；完成状态必须有实际测试或基准证据。

## 总体目标

在不破坏现有文章生成 API 和 Style RAG 数据的前提下，逐步构建默认离线、中文优先、适合普通 Windows CPU 的本地 Style Engine。继续复用 SQLite、NumPy 和现有 Flask 分层，不在当前计划中决定具体 Embedding 模型。

## 状态总览

| Milestone | 名称 | 状态 | 主要产物 |
|---|---|---|---|
| M0 | 架构与评测基线 | 已完成 | 本目录五份设计文档 |
| M1 | Feature V1 设计与冻结 | 已完成 | 冻结登记表、文本规则、测试矩阵与实现边界 |
| M2 | 本地 Feature Extractor | 已完成 | 独立提取服务与单元测试 |
| M3 | Style Window 与版本化 Feature 存储 | 已完成 | 邻接窗口、幂等迁移、Feature 与 confidence |
| M4 | 离线 Corpus Analysis 工具 | 已完成 | CLI、raw dataset、corpus statistics 与 outliers |
| M5 | Author Style Profile | 已完成 | Feature V1.1、统计画像、robust normalizer 与版本失效识别 |
| M6 | Scene/Mode Profile 与自动 Feature 升级 | 已完成 | 现有场景标签聚合、fallback 和旧 chunk 原地重算 |
| M7 | Style Retrieval Engine | 已完成 | Style-first 可解释排序、Content Leakage Penalty 与 diversity |
| M8 | 可插拔 Embedding Backend | 已完成 | 远程兼容、本地 ONNX 接口、签名隔离与纯 Style 降级 |
| M9 | Style Signature | 已完成 | 受限功能结构词表、版本化稀疏向量与检索子分 |
| M10 | Style Diff | 已完成 | 本地结构化差异、置信度过滤与可执行建议 |
| M11 | Strict Style Rewrite 生成链集成 | 已完成 | 可选单次重写、Token 预算、持久化与 UI |
| M12 | Style Retrieval Debugger | 已完成 | 分项评分、关键理由、Profile/场景摘要与详细指标 |
| M13 | 最终 Style Engine Benchmark | 已完成 | 冻结 A/B/C/D 结果评测、泄漏报告与匿名盲测包 |

## M0 — 架构与评测基线

范围：建立长期约束、当前/目标架构、执行计划、Feature 草案和 Benchmark 方法。

验收标准：

- 文档明确区分当前实现与目标状态；
- 不修改业务代码、数据库、依赖或配置；
- Feature 文档不把未验证算法标为冻结；
- 后续 milestone 有范围、风险与可核验的完成条件。

## M1 — Feature V1 研究与冻结

范围：验证约 40～50 个中文表层风格候选 Feature，冻结文本统计口径和完整登记表。

工作项：

- 建立可提交的小型公开授权或合成中文 fixtures；
- 比较切句、段落、标点标准化和混合字符口径；
- 确定 Feature ID、公式、单位、最小样本、权重和缺失策略；
- 检查重复、共线性、体裁混杂和长度偏差；
- 更新 `STYLE_FEATURE_V1.md` 为 `Frozen`。

验收标准：

- 每个 Feature 具备文档规定的全部字段；
- 规则边界有预期结果 fixture；
- 候选项通过 `BENCHMARK.md` 的稳定性和长度敏感性检查；
- 高度共线项被删除、降权或分簇；
- 未引入远程服务或大型运行时。

完成记录（2026-08-14）：

- 冻结 `style_feature_version = 1` 与 44 个 Feature；
- 冻结中文切句、段落、标点标准化、有效字符和每千字口径；
- 冻结功能词词典、最低样本、权重、归一化与缺失策略；
- 完成共线性审查和 M2 测试矩阵；
- 本里程碑只修改文档，未实现业务代码；性能基线和统计稳定性实测留在 M2，未以未经测量的数据冒充验收结果。

## M2 — 本地 Feature Extractor

范围：实现独立、无数据库副作用的纯本地提取器，不接入生成流程。

本次实施范围（2026-08-14）：

- 新增 `server/services/style_feature_service.py`，公开 `analyze_style_features(text)`；
- 严格实现 `STYLE_FEATURE_V1.md` 冻结的 44 个 raw Feature；
- 阈值、Feature ID 和功能词词典集中管理；
- 新增 `tests/test_style_feature_service.py`，覆盖中文叙述、长短句、对话、逻辑标点、代词、功能词和异常输入；
- 不新增路由、数据库表、网络调用、LLM/Embedding 调用、RAG 检索或 Prompt 接入。

兼容性与风险：

- 新服务尚未接入任何现有调用链，因此关闭/旧路径行为不变；
- 中文引号、半角句点和语气词位置存在规则边界，以冻结文档和回归测试为准；
- `的/地/得/了/着/过` 及把/被结构是字面代理指标，不作词性或完整句法结论；
- 回退方式为移除新增 service 与测试，不涉及数据迁移。

本次验收命令：

- `.\.venv\Scripts\python -m pytest tests/test_style_feature_service.py`
- `.\.venv\Scripts\python -m ruff check server/services/style_feature_service.py tests/test_style_feature_service.py`

验收标准：

- 输入文本、输出版本化 Feature 结果；
- 同输入重复运行结果一致；
- 规范化、切句和每个 Feature 均有参数化单测；
- 100 万字符性能达到 M1 冻结的时间和内存门槛；
- Ruff 和相关 pytest 通过；
- 无网络调用，无大型新增依赖。

完成记录（2026-08-14）：

- 新增职责单一的纯本地 Analyzer，实现全部 44 个 raw Feature；
- 新增并审查 29 个直接测试，覆盖冻结测试矩阵、具体数值/范围断言、CRLF、英文缩写、交叉配对与 schema 一致性；
- 目标 pytest：`29 passed`；仓库完整 pytest：`33 passed`；
- 目标 Ruff：通过；仓库全量 Ruff 仍有 24 个本次改动前已存在的问题，未扩大范围修改；
- 100 万有效字符复核基线：约 `1.743s`；带 `tracemalloc` 的 866,667 字诊断峰值约 `4.89MB`（追踪模式耗时不作为正常延迟）；
- 未新增运行时依赖，未访问数据库或网络，未接入 RAG、Prompt、路由和 UI；M3 保持未开始。

## M3 — Style Window 与版本化 Feature 存储

范围：保持现有 chunk 和 RAG 行为不变，为每个 chunk 使用同文章相邻上下文建立分析窗口，并保存窗口 Feature、有效字符数和可扩展 confidence。Corpus Profile 聚合留给后续独立 milestone。

本次实施范围（2026-08-14）：

- 新增纯本地 Style Window 服务，默认使用 previous + current + next；不足约 800 有效字符时在同文章内向外扩展，扩展不得主动超过约 1500；
- 当前 chunk 始终完整保留，并按原顺序位于窗口中部；文章首尾按可用邻居降级；
- 一次 corpus 导入视为一篇 article，并用稳定 `article_key` 显式记录边界；
- 通过幂等迁移为 `style_chunks` 增加 Feature 版本、Feature JSON、窗口有效字符数、confidence 和窗口起止顺序；
- 导入时从 Style Window 计算 Feature，但 `StyleChunk.content`、FTS 内容、Embedding 输入、检索排序和最终 Prompt 注入仍只使用 current chunk；
- 新增单 chunk、双 chunk、多 chunk、首/中/末窗口和跨 article 防护测试。

兼容性、风险和回退：

- 所有新列都有安全默认值；旧 chunk 继续可检索，只是尚无窗口 Feature；
- 不改变现有 RAG 排序、过滤、Embedding 和返回内容语义；
- 当前仓库没有独立 Article 表，因此 `article_key` 以本次导入正文哈希表示文章边界；未来支持一个 corpus 多文章时沿用该字段；
- 回退时可停止写入新列，旧路径不依赖这些列；不做破坏性删列或旧数据重写。

本次验收命令：

- `.\.venv\Scripts\python -m pytest tests/test_style_window_service.py tests/test_style_rag_service.py`
- `.\.venv\Scripts\python -m ruff check server/services/style_window_service.py server/services/style_rag_service.py server/database/models.py server/database/migrations.py tests/test_style_window_service.py tests/test_style_rag_service.py`

验收标准：

- 迁移幂等；旧数据库可升级，原 chunk 内容和已有 Style RAG 数据不被破坏；
- 单、双、多 chunk 的窗口顺序正确，首尾安全降级且绝不跨 `article_key`；
- Feature 版本、窗口范围、有效字符数和 confidence 可追踪；
- confidence 初版主要由有效字符数决定，结构允许未来增加其他 factor；
- RAG 排序逻辑和最终注入仍只使用 current chunk；
- 相关数据库测试、pytest 和 Ruff 通过。

完成记录（2026-08-14）：

- 新增纯本地 Style Window 服务；中间 chunk 使用对称邻居，首尾只按文章边界降级；
- 新增 `article_key` 与 6 个窗口分析字段，迁移可重复执行且旧行使用安全默认值；
- 导入后保存 Style Feature V1、窗口有效字符数、confidence 分数和窗口起止顺序；
- 新增 10 个窗口/持久化测试；相关测试 `11 passed`，仓库完整测试 `43 passed`；
- 相关 Ruff 通过；
- 复核确认 FTS、Embedding、RRF、MMR、检索排序与最终返回的 `content` 仍只使用原 current chunk；
- 未开始后续 Corpus Profile、Style Diff、检索改造或 Prompt 接入。

## M4 — 离线 Corpus Analysis 工具

范围：提供开发/诊断 CLI，读取用户明确指定的本地 TXT/DOCX 目录，复用现有 chunk、Style Window 和 Style Analyzer，输出可重复生成的 raw Feature 数据集、语料统计与异常值报告。Style Diff 留给后续独立 milestone。

本次实施范围（2026-08-15）：

- 新增 `scripts/analyze_style_corpus.py`，必填本地语料目录，允许可选 `--output` 和 `--include-text`；
- 复用现有文档解析、`split_corpus_text`、Style Window 与 Style Feature V1；
- 默认递归扫描 `.txt`/`.docx`，按稳定相对路径排序，逐文档处理并显示进度；
- 默认报告目录为项目根目录下被 Git 忽略的 `style-analysis-reports/<目录名>-<路径哈希>/`；
- 输出 `summary.json`、`feature_stats.csv`、`chunk_features.csv`、`outliers.csv`；
- 默认 raw dataset 只保存稳定文档/chunk ID、窗口元数据和 Feature，不保存正文；
- corpus 统计包含 median、MAD、P25/P75、P05/P95、missing ratio 和 zero ratio；
- outlier 使用可解释的 MAD robust score，并在 MAD 退化时使用 IQR fallback；
- 不访问数据库、网络、模型 API，不修改原始文件。

兼容性、隐私、风险与回退：

- 私人语料和默认报告目录均不进入 Git；显式 `--output` 由用户自行选择，但工具仍不会修改语料；
- DOCX 继续使用项目现有安全解析逻辑，不新增文档解析依赖；
- 百万字处理按文档流式推进，避免把全部原文、全部窗口正文和完整 CSV 同时保存在内存；
- Feature 分布仍会受体裁、短窗口和输入排版影响，报告保留 missing/confidence 供诊断；
- 回退只需移除 CLI、测试和默认报告忽略项，不涉及数据库或用户数据迁移。

本次验收命令：

- `.\.venv\Scripts\python -m pytest tests/test_analyze_style_corpus.py`
- `.\.venv\Scripts\python -m ruff check scripts/analyze_style_corpus.py server/routes/support/document_text.py server/services/style_chunk_service.py server/services/style_window_service.py server/services/style_rag_service.py tests/test_analyze_style_corpus.py tests/test_style_window_service.py`

验收标准：

- TXT/DOCX 目录能生成四个格式稳定的报告文件；
- summary 和 CSV 的统计值、缺失率、零值率可由 raw dataset 重算；
- 默认无正文列，显式选项才输出 current chunk 正文；
- 同一输入重复运行得到相同报告内容；
- 不读取未指定目录，不写入或修改原始文章；
- 相关 pytest、Ruff 和 CLI 冒烟测试通过。

完成记录（2026-08-15）：

- 新增离线 CLI，递归读取用户明确指定目录中的 TXT/DOCX，生成四份稳定报告；
- 抽出无 Flask/数据库副作用的共享切块模块，现有 Style RAG 与离线工具共用原切块算法；
- 默认不输出正文，默认报告目录已加入 `.gitignore`，未读取用户私人语料；
- 新增 3 个 CLI/报告测试，与 M3 相关测试合计 `11 passed`；仓库完整 pytest `46 passed`；
- 相关 Ruff 通过，`--help` CLI 冒烟测试通过；
- 未修改 RAG 排序、Prompt 组装或最终用户 UI，M5 保持未开始。

## M5 — Author Style Profile

范围：根据真实 corpus 诊断确认 Style Feature V1.1（机器 schema version `2`），并从同一 corpus 的有效 Style Window 构建可重算的纯本地统计画像。本阶段不实现检索、重排、Prompt 或 UI。

诊断决策（2026-08-15）：

- AuthorA 的 11 份文档、923,325 有效字符用于本地诊断，私人正文和诊断中间产物不进入 Git；
- 同文 500/800/1000/1500 字窗口下，主要句长、段落、逗号、句号和高频功能词中位数整体稳定；稀疏 Feature 继续低权重而不删除；
- 已知非功能词至少占所有字面命中：`地` 46.9%、`得` 34.0%、`过` 54.8%，V1.1 必须使用轻量上下文排除；
- 总标点不再计入引号字符，稀疏指标使用可用率/非零率参与 reliability；
- 未提供第二位作者语料，因此跨作者区分力明确标记为未验证，不伪造结论。

实施范围：

- 新增与现有 LLM Style Card 明确分离的 `AuthorStyleProfile` 表和服务；
- 每个 corpus 最多一份当前统计画像，重建采用同一行更新，不删除 chunk/Embedding/FTS 数据；
- 保存 Feature 版本、样本数、有效字符数、median/MAD/P05/P25/P75/P95、normalizer 参数和 reliability；
- robust scale 优先使用 `1.4826 * MAD`，MAD 为零时回退到 `IQR / 1.349`，再退化时使用 epsilon；z 默认限制在 `[-5, 5]`；
- 旧 Feature 版本的 Profile 保留但显式标记 stale，不静默混用。

验收标准：

- 幂等迁移不覆盖现有 `style_profiles` Style Card 或 Style RAG 数据；
- 统计值和 robust normalization 边界有具体数值测试；
- 空 corpus、旧 Feature 版本、无效 JSON、MAD=0 和极端值安全处理；
- 重建 Profile 可重复执行，并能识别 Feature 版本失效；
- 完整 pytest 和相关 Ruff 通过。

完成记录（2026-08-15）：

- 确认 Style Feature V1.1（machine schema version `2`）：总标点排除引号，并对 `地/得/了/着/过` 增加冻结的轻量词汇排除；
- 新增 `author_style_profiles` 独立表，不覆盖或改写现有 `style_profiles` Style Card、Style Chunk、FTS 或 Embedding；
- 新增可重建的 Author Style Profile 服务，保存 44 项统计、版本、样本数、有效字符、confidence 和 robust normalizer；
- MAD=0 依次回退 IQR 和 epsilon，z-score 限制为 `[-5, 5]`，并修复 epsilon 被六位小数舍入为零的边界；
- 新增 6 个 V1.1/Profile 直接测试；相关专项测试 `45 passed`，仓库完整 pytest `52 passed`；相关 Ruff 通过；
- 未实现路由、UI、RAG 排序、Style Diff 或 Prompt 接入，完成后停止。

## M6 — Scene/Mode Profile 与自动 Feature 升级

范围：在全局 Author Style Profile 上增加场景/模式统计，并在重建前将旧 chunk Feature 原地升级到当前版本。本阶段不修改 RAG 排序、Embedding、FTS、Prompt、路由或 UI。

实施范围（2026-08-15）：

- 自动升级复用现有 chunk、`article_key` 和 Style Window，只改写 Feature 版本/数值、窗口范围、有效字符和 confidence；
- 场景使用现有 `dialogue/action/psychology/environment/transition/narration/mixed`；产品模式 `description` 映射 `environment`，`exposition` 映射 `narration`；
- 更宽回退类别为 `dynamic(dialogue+action)`、`reflective(psychology+environment)`、`narrative(transition+narration)`，再回退 global；
- 场景 Profile 最低 20 个有效窗口：该门槛使 P05/P95 至少接近一个尾部样本，同时不对中小 corpus 过度苛刻；
- 每个有效模式保存 median/MAD/P25/P75、reliability 和最多 3 个靠近 robust 中心的 representative chunk ID；
- pacing、pov、emotion 仍使用现有 chunk 标签命名，作为可追踪分组统计，不创建冲突分类。

验收标准：

- 自动升级后正文、标签、Embedding 和已有 RAG 数据保持不变；
- 样本充足、不足、未知场景、宽类回退和 global 回退均有具体测试；
- 场景统计不会覆盖全局 Profile，且重建可重复执行；
- 完整 pytest 和相关 Ruff 通过。

完成记录（2026-08-15）：

- Author Profile 重建会自动检测并原地升级旧 chunk Feature，仅更新分析字段；
- 新增 6 个主要模式、3 个宽类 fallback、global fallback、representative sample IDs 与 pacing/pov/emotion facet 聚合；
- 新增本地维护命令 `scripts/rebuild_author_style_profiles.py`，支持 `--corpus-id` 或 `--all`；
- 测试覆盖样本充足、样本不足、未知场景、宽类回退、global 回退和旧版本升级；
- 仓库完整 pytest `55 passed`，相关 Ruff 和 CLI `--help` 通过；
- 已在本机正式 SQLite 执行 `--all`，当前数据库没有 Style Corpus，因此安全结束且无数据被改写；
- 未进入 RAG 检索/重排、Prompt、路由或 UI 阶段。

## M7 — Style Retrieval Engine

范围：在现有 `hybrid_search_style` 候选过滤、可选 Embedding、FTS5 和 MMR 链路内，将本地 Style Feature 提升为主排序信号，并对内容泄漏显式扣分。不新增 Embedding 模型或改变最终 chunk 正文注入语义。

实施决策（2026-08-15）：

- V1.1 只有 Rhythm、Punctuation、Function/Grammar 三组；不伪造 Narrative Structure、Rhetoric 或 Style Signature 得分；
- 候选 chunk 与对应 global/scene Author Profile 做 robust Feature 相似度，组内按 Feature reliability 聚合；
- 初始总分权重：Style `0.72`、scene `0.12`、semantic `0.10`、BM25 `0.06`；Content Leakage Penalty 最高以 `0.45` 系数扣分；
- BM25 仅使用归一化排名分，不能决定候选是否进入 Style 排序；
- Leakage 使用忽略空白/标点的内容字符、8-gram 重合、较长连续字符串和低权重关键字组重合；本地规则无法可靠确认专有名称，因此 V1 不伪造实体识别分数；
- MMR 继续保留，无 Embedding 时使用本地字符 n-gram 相似度防止返回近重复片段。

验收标准：

- 返回项包含 `style_score/rhythm_score/punctuation_score/function_word_score/scene_score/semantic_score/content_overlap_penalty/confidence`；
- 解释数据可追溯到 Feature 分组、Profile fallback 和各信号权重；
- A（文风近内容远）在固定测试中可高于 B（内容近文风远），并覆盖 C（两者都近）、D（两者都远）；
- 正常功能词和标点重合不会单独产生高 Leakage Penalty；
- 无 API Key/无 Embedding 时仍可完成 Style-first 检索；
- 完整 pytest 和相关 Ruff 通过。

完成记录（2026-08-15）：

- 在原 `hybrid_search_style` 链路内完成 Style-first 评分，未新建冲突检索 API；
- 返回 Style/Rhythm/Punctuation/Function Word/Scene/Semantic/Leakage/Confidence 与 `ranking_explanation`；
- 本地 Style 权重 `0.72`，高于 scene `0.12`、semantic `0.10` 和 BM25 `0.06`；BM25 不再决定 Style 候选入围；
- 新增标点/空白无关的 Content Leakage Penalty，并保留无向量时的 n-gram MMR diversity；
- 新增 A/B/C/D 可解释排序、功能词/标点误惩罚和无 Embedding 集成测试，A（文风近内容远）可高于 B（内容近文风远）；
- 仓库完整 pytest `58 passed`，相关 Ruff 通过；
- 未新增 Embedding 模型，未实现 Narrative Structure/Rhetoric/Style Signature 伪指标，未修改 Prompt 注入或 UI。

## 计划变更规则

## M8 — 可插拔 Embedding Backend

范围：保留现有硅基流动 BGE-M3 索引能力，同时把 Embedding 降为可选的 semantic/scene 辅助信号。默认无 API Key；本地模型或运行时缺失、索引签名不一致时，检索继续使用 Style-first + BM25 + 本地 diversity。

实施决策（2026-08-15）：

- 新增统一 `EmbeddingBackend`，公开 `embed_text`、`embed_batch`、`dimension`、`model_id`、`model_version` 与 `backend_id`；
- `RemoteEmbeddingBackend` 兼容现有硅基流动 `BAAI/bge-m3`；已有调用传入 API Key 时仍走远程后端；
- `LocalEmbeddingBackend` 采用 ONNX Runtime CPU 路线，首个候选为 MIT 许可的 `BAAI/bge-small-zh-v1.5`（512 维、最大 512 token）。模型目录为用户数据根目录旁的 `models/`，不写 SQLite、不打进 `forestar-server.exe`；
- 不加入 Transformers/PyTorch。使用固定 BERT WordPiece 词表、本地 ONNX、CLS pooling 与 L2 normalization；Session 按模型路径进程内缓存，支持批量推理；
- ONNX Runtime 作为可选依赖。其 Windows x64 wheel 约 13–14 MB，打包后仍会增加体积，因此本阶段不进入主 `requirements.txt`；缺失时后端返回可诊断的 unavailable 状态；
- corpus/chunk 增加 backend、model version 元数据；向量只有在 backend/model/version/dimension 完全一致时才参与计算，不一致明确提示重新索引；
- 当前 `embedding_model`/`embedding_dim` 保留，迁移只增列，不删除旧向量。旧索引因缺少完整签名只能在显式远程兼容条件下使用，否则安全降级；
- 不改变 Style Score 权重与现有 RAG 最终正文注入逻辑。

风险与回退：

- 官方仓库未直接发布本项目所需的稳定 ONNX 成品，实际模型文件必须由发布流程转换、校验 SHA-256 并附 manifest；不自动信任第三方转换；
- WordPiece 与导出模型的输入/输出名称必须由 manifest 和运行时检查；维度、返回数量或签名不符时禁止写库；
- 回退只需不安装可选运行时或移走本地模型，Style Retrieval 会继续纯本地运行；远程兼容路径不受影响。

验收标准：

- 默认检索不要求 API Key；本地模型缺失不会使 Style Retrieval 失败；
- batch、Session 缓存、模型签名隔离、重索引提示和旧远程后端均有测试；
- 可用本地模型时，小型语义测试满足同场景相似度高于无关场景，不用 Embedding 验证作者文风；
- 完整 pytest 与 Ruff 通过。

完成记录（2026-08-15）：

- 已实现统一 backend、远程兼容适配、本地 ONNX CPU adapter、WordPiece、batch、Session 缓存及完整索引签名；
- SQLite 幂等迁移新增 backend/model version 字段，旧向量不删除，BGE-M3 旧索引保留远程兼容映射；
- 检索遇到无模型、无运行时、混合签名或维度错误时输出明确原因并降级，未向量化语料仍可进入纯 Style 检索；
- 本地 adapter 的固定语义测试验证“同场景 > 无关场景”，没有用 Embedding 判断作者文风；
- 完整 pytest `64 passed`，本次相关 Python 文件 Ruff 与原生 JavaScript `node --check` 通过；全库 Ruff 仍有 23 个既存、与 M8 无关的告警。

## M9 — Style Signature

范围：在 Dense Style Features 之外增加受限、可解释的本地 Style Signature。Signature 只从功能词、功能短语、代词、连接结构和规范化标点组成，不提取普通内容字符 n-gram，不替代 Dense Features。

实施决策（2026-08-15）：

- 固定 `STYLE_SIGNATURE_VERSION = 1`，每个 corpus 从其 Style Window 建立独立词表；算法版本固定不等于跨作者强行使用同一组稀疏模式；
- tokenizer 只识别冻结的功能词词典、少量语法结构原子和规范化标点。无法识别的普通汉字、英文、数字和内容词只作为边界，不进入候选；
- 候选仅为允许的单 token，以及相邻 2～3 token 功能结构；单独的“时候”等可能具有内容含义的原子不得成为单 token Feature；
- 删除总频次不足 3、窗口 document frequency 不足 `max(2, ceil(3% * windows))` 的模式；样本不少于 8 时删除覆盖全部窗口的模式，样本不少于 20 时删除覆盖率不低于 95% 的模式；
- 按 `df_ratio * (1 - df_ratio) * log(1 + count)` 的稳定信息量代理排序，再按模式长度和字典序确定性打破并列；最多保留 192 维，不为达到 128 维填充低价值模式；
- 每个 chunk 保存当前 Style Window 的每千有效字符 Signature 值；Author Profile 对每维保存 median/MAD/P25/P75/P05/P95 和 reliability；
- `style_corpora.signature_version`、`style_chunks.style_signature_version/style_signature_json` 和 Profile payload 同时记录版本。缺失或不同版本不得参与 Signature Score，并触发重建而不是静默混用；
- Retrieval 的 Style Score 增加 `signature_score` 子项。初始组权重为 Rhythm `0.32`、Function/Grammar `0.28`、Punctuation `0.20`、Signature `0.20`；缺失 Signature 时对已有 Dense 组重新归一化，保持旧数据兼容；
- 不修改 Embedding、BM25、Content Leakage、MMR 和最终 current chunk 注入语义。

风险与回退：

- 单作者 corpus 只能筛除稀疏和无变化模式，不能证明跨作者区分力；后续 Benchmark 有第二作者数据后再调整 df 阈值和权重；
- corpus 很小时词表可能少于 128 维甚至为空，这是比填充垃圾特征更安全的预期结果；
- 回退时将 Signature 权重重新分配给三个 Dense 组即可，不删除既有 Feature/Profile/RAG 数据。

验收标准：

- 候选中不存在普通内容词或普通内容字符 n-gram；功能结构、标点组合和代词结构可被稳定提取；
- 稀疏、全覆盖和版本不一致模式有直接测试；构建重复运行得到相同词表与向量；
- corpus/chunk/Profile 版本一致才计算 `signature_score`，返回结果可解释；
- Signature 相近能在 Dense Features 相同条件下提高 Style Score；旧数据无 Signature 时继续工作；
- 完整 pytest 与相关 Ruff 通过。

完成记录（2026-08-15）：

- 新增纯本地 `style_signature_service.py`，冻结 Signature V1 的允许词元、规范化、1～3 token 候选、DF/全覆盖过滤、稳定排序和 192 维上限；
- corpus-specific 词表保留模式文本与 token，未加入普通内容字符 n-gram；实际维度由有效候选决定，不足 128 不填充；
- SQLite 幂等迁移增加 corpus/chunk Signature 版本和 chunk 稀疏向量 JSON；Author Profile 保存词表及 global/scene/broad robust statistics；
- Style Retrieval 返回 `signature_score` 和版本兼容状态；Signature 占 Style 组内 0.20，缺失或版本不符时 Dense 组自动重新归一化；
- 测试覆盖内容词排除、多字符标点、稀疏/全覆盖过滤、确定性、每千字向量、Profile 分位数、迁移、版本失效和 Signature 排序贡献；
- 完整 pytest `70 passed`，相关 Ruff 与 `git diff --check` 通过；未修改 Embedding、BM25、Leakage、MMR 或 Prompt 注入。

## M10 — Style Diff

范围：对生成稿调用与参考语料完全相同的 `analyze_style_features()`，再与目标 Scene/Mode Profile 和 global Author Profile 比较，输出少量结构化、可执行差异。本阶段不修改正文、不调用 LLM、不接入自动重写。

实施决策（2026-08-15）：

- 新增纯函数式 `analyze_style_diff(text, author_profile, scene_type=None, max_differences=6)`；默认上限 6，调用方可在 5～8 范围内调整；
- 目标 Profile 复用 M6 的 `resolve_mode_profile`：scene 足够时使用 scene，中间可回退 broad，最后回退 global；同时保留 global median/deviation 供解释，不另造场景体系；
- 仅比较当前 Feature V1.1 已实现且 generated/target 都有效的 Dense Features；M10 不伪造 dialogue ratio、叙事结构或修辞 Feature；
- 明显偏差初始门槛为 `abs(robust z) >= 1.5` 且 generated value 超出目标 P25～P75；严重度分为 moderate `1.5～2.5`、high `2.5～4.0`、critical `>=4.0`；输出 z 截断到 `[-5, 5]`；
- 证据置信度由目标 Feature reliability、目标 Profile confidence 和生成稿有效字符长度置信度共同决定；综合证据低于 `0.35` 的指标不报告；
- 排序分数综合 deviation、冻结的 Feature importance、sample reliability 和 style confidence；同一高度相关簇最多选 2 项，避免均值/中位数/分位数等重复提示淹没结果；
- 每项输出 `feature_id/generated_value/target_median/target_range/normalized_deviation/severity/human_message/rewrite_instruction`，并附目标来源、global median、reliability/confidence 作为解释字段；
- high/low 文案和重写建议由冻结映射生成。未知 Feature 使用可解释通用模板，但不会越过相同置信度与偏差门槛。

风险与回退：

- 当前 Analyzer 没有独立 dialogue ratio Feature，因此本阶段不能可靠输出“对话比例过高”；未来必须先增加版本化 Feature，不能从引号覆盖率冒充；
- 极短生成稿的统计方差很大，会因长度置信度不足少报或不报，这是预期保护；
- 回退只需停止调用 Diff 服务，不影响生成稿、Profile、RAG、数据库或 Prompt。

验收标准：

- 接近 Profile 的生成稿少报或不报；明显短句稿能命中句长/短句方向；
- 低 reliability、低 Profile confidence 或极短文本不强行下结论；
- 输出不超过配置上限，排序稳定，并对高共线 Feature 做限流；
- scene/broad/global fallback 与 global 对照信息有测试；
- 完整 pytest 和相关 Ruff 通过。

完成记录（2026-08-15）：

- 新增纯本地 `style_diff_service.py`，公开稳定入口 `analyze_style_diff`，不访问数据库、网络、LLM 或正文写入路径；
- 复用 Feature V1.1 Analyzer 与 M6 scene/broad/global fallback，返回目标 Profile 来源和 global 对照；
- 冻结明显偏差、严重度、证据置信度、Feature importance、共线簇限流及默认 6 条上限；
- 为全部 44 个 Dense Feature 提供中文名称，并按节奏、段落、标点、功能结构生成方向明确的解释和改写指令；
- 测试覆盖接近 Profile、明显短句、低 reliability、极短文本、Scene/global 对照、输出上限和确定性；
- 完整 pytest `75 passed`，相关 Ruff 与 `git diff --check` 通过；未接入自动改写或修改生成 API。

## M11 — Strict Style Rewrite 生成链集成

范围：在现有 `generation_service` 单一生成流水线内增加用户显式启用的 Strict Style Rewrite。顺序固定为正文生成、可选去 AI 味、本地 Style Diff、至多一次文风重写；不建立第二套生成管线，不改变 Style Retrieval 排序。

实施决策（2026-08-15）：

- 新模式使用独立布尔开关，默认关闭；关闭时不分析 Diff、不增加 API 调用，保持既有接口行为；
- Diff 以正文生成或去 AI 味后的最新稿件为输入，复用 M10 Analyzer 与所选 corpus 的 scene/broad/global Author Profile；Profile 缺失、失效或无显著差异时安全跳过；
- 只有 Diff 已报告达到冻结阈值的差异时才重写，自动重写次数硬限制为 1，不循环复检；
- 第二次重写继续使用原生成上下文与已有 3～5 个参考片段，并明确保持剧情、事实、人物、世界观、已有信息和用户要求，只调整句式、节奏、标点、语言组织、修辞和段落；
- 重写提示明确禁止复制参考原文中的人物、地点、事件和独特表达，Style Diff 最多转换为 6 条自然语言要求；
- Token Budget 增加独立 `style_rewrite` 阶段，按原提示、最长输出草稿和重写指令预留估算；
- GenerationRecord 通过现有幂等迁移追加可选重写结果、Diff 快照、启用/应用状态和次数，旧记录与旧 API 字段继续有效；
- 同步与流式路径共用同一准备逻辑，前端最终展示、复制、下载和编辑优先使用严格文风终稿。

风险与回退：

- 多 corpus 检索时初版使用最高排序参考片段所属 corpus 的 Profile，返回的诊断元数据记录实际目标；无法确定目标时跳过而不阻断正文；
- 二次调用会增加费用和延迟，因此只在用户显式开启且 Diff 显著时执行，并在 UI 标明“最多一次额外调用”；
- 回退时关闭开关即可恢复旧流程；新增数据库列均有安全默认值，不删除或重写旧记录。

验收标准：

- 默认关闭时 LLM 调用次数与旧版本一致；开启但 Diff 足够接近时不发生额外调用；
- 开启且存在显著偏差时只发生一次重写，最终结果和持久化记录使用重写稿；
- mock LLM 测试验证调用次数、流程顺序、保留约束、可执行 Diff 指令、反复制约束和最大次数；
- Token Budget 的正文、去 AI 味、严格重写阶段均可独立预警或拦截；
- 旧请求、旧记录、Style RAG 注入与同步/流式返回保持向后兼容；
- 完整 pytest、相关 Ruff、原生 JavaScript 语法检查与 `git diff --check` 通过。

完成记录（2026-08-15）：

- 在原 `generation_service` 同步与流式路径中接入 Strict Style Rewrite，没有创建平行 pipeline；
- 新开关默认关闭；关闭时不运行 Diff，开启但 Profile 不可用或 Diff 无显著差异时不增加 LLM 调用；
- Diff 使用去 AI 味稿或初稿中的最新版本，显著偏差最多触发一次重写；提示保留事实与故事信息，只调整语言形式，并包含反复制约束；
- Token Budget 增加 `style_rewrite` 阶段；GenerationRecord 通过幂等迁移保存终稿、Diff、启用/应用状态和次数；
- 前端支持开关、流式终稿显示，复制、下载、历史详情与全屏编辑优先使用最终稿；
- 新增 6 个 mock/预算测试，验证默认零额外调用、接近目标跳过、显著偏差单次重写、去 AI 味顺序、提示约束和预算阶段；
- 完整 pytest `81 passed`，相关 Ruff、全部原生 JavaScript `node --check` 与 `git diff --check` 通过。

## M12 — Style Retrieval Debugger

范围：升级现有 Style Corpus“检索测试”区域，复用 `hybrid_search_style` 的可解释返回，把单一相关度展示扩展为分项 Style Retrieval 调试信息。不引入前端框架，不改变排序算法或生成时 Prompt 注入。

实施决策（2026-08-15）：

- 每个命中默认展示综合、文风、节奏、标点、功能词、Style Signature、场景、语义、内容重合惩罚和 confidence；不可用语义明确显示“未启用”，不伪造零分；
- 主要理由由候选 Style Window 与实际解析到的 Author/Scene Profile 生成，只返回少量高价值 Feature 的接近或差异描述，不在默认视图倾倒 44 个底层指标；
- query 使用现有本地规则打标，返回“规则判定场景”和用户显式过滤后的“实际检索场景”；不新建分类器或调用 LLM；
- meta 返回每个参与 corpus 的 Author Profile 样本量、有效字符、confidence、Feature/Signature 版本，以及当前 scene/broad/global Profile 的来源与样本摘要；
- “展开详细指标”显示现有 ranking explanation、Feature 使用数量、内容重合分解、Profile fallback 和排序权重；
- UI 继续使用现有原生 JavaScript、`details` 元素和主题变量，保持旧 API 字段向后兼容。

风险与回退：

- query 场景是轻量关键词规则，只作为调试提示，不冒充语义模型结论；
- 稀疏 Signature 或 Embedding 不可用时显示缺失状态，避免把不可比较误写成低相似；
- 回退只需移除新增 meta/解释字段和展示块，既有 `items/score/content` 仍保持不变。

验收标准：

- 后端测试验证所有分项、有限条主要理由、query 场景、Author Profile 摘要和 scene fallback 摘要；
- 默认 UI 只显示关键得分与少量理由，详细信息可展开；所有后端文字经 HTML 转义；
- 无 Embedding、无 Signature、多个 corpus 和 Profile fallback 状态可解释；
- 完整 pytest、相关 Ruff、原生 JavaScript `node --check` 与 `git diff --check` 通过。

完成记录（2026-08-15）：

- 复用 `hybrid_search_style` 返回的 Style-first 得分，检索测试不再只显示模糊相关度；
- 默认卡片展示 10 个核心分项，其中缺失 Semantic/Signature 显式标记“未启用”，不伪造零分；
- 新增最多 4 条高可靠 Dense Feature 理由，并可补充场景和对话比例匹配，总理由最多 5 条；
- 新增 query 规则场景、实际检索场景、每个 corpus 的 Author Profile 与 scene/broad/global fallback 摘要；
- 详细折叠区展示参与 Feature 数、Profile 来源、BM25、内容 8-gram、关键词和最长连续重合；
- 保持现有原生 JavaScript/CSS 风格，未新增依赖、框架、数据库迁移或排序变更；
- 新增/扩展 2 个直接测试，完整 pytest `82 passed`，相关 Ruff、全部原生 JavaScript `node --check` 与 `git diff --check` 通过。

## M13 — 最终 Style Engine Benchmark

范围：建立不新增算法、不调用网络或 LLM 的可重复离线 Benchmark。对同一组任务已经生成并冻结的 Baseline、Existing、New、Strict 四份候选稿使用当前 Analyzer/Profile/Leakage 口径统一评分，并输出聚合报告与匿名盲测包。

实施决策（2026-08-15）：

- 旧 Style RAG 已被 M7 原地升级，仓库不恢复或伪造旧排序算法；Existing 使用升级前真实保存的生成结果和当时实际注入片段；
- manifest 固定任务 ID、场景、候选稿路径、每个方案实际注入 reference 路径、盲测参考样本、Profile JSON 与匿名种子；
- Style/Rhythm/Punctuation/Function-word distance 复用 `analyze_style_features`、`resolve_mode_profile` 和现有 Style 相似度；Scene compatibility 复用现有规则场景与场景相似度；
- Content Leakage 复用现有较长连续字符串、字符 8-gram、关键词和综合 penalty，对每份稿件报告其所有实际注入片段中的最大值及对应匿名 reference ID；
- 自动输出 `summary.json`、`task_scores.csv`、`report.md`、盲测目录和单独的管理员映射；盲测候选 A～D 使用固定 seed 按任务稳定打乱；
- 私人语料、候选正文、注入片段、报告和盲测包默认写入 Git 忽略目录；Git 只保存工具、manifest 示例和合成测试；
- 报告必须声明自动指标不等价于人类判断，不声称文学质量或统计显著性。

风险与回退：

- LLM 本身可能非确定，因此“生成”与“评分”分离；可重复性针对冻结输入和评分输出，不虚构模型逐次生成完全一致；
- Existing 必须使用历史实际稿件，若没有保存则标为缺失，不能用 New 冒充；
- 少量任务或单次人工盲测只能作为探索性证据，报告不做显著提升结论。

验收标准：

- 同一 manifest 重复运行产生相同 JSON/CSV/Markdown、盲测候选顺序与管理员映射；
- A/B/C/D 使用相同任务 ID，缺文件、版本不兼容或未提供实际注入片段时给出明确错误；
- 六类指标和连续复用、字符 n-gram、实际注入片段最大重合均有具体数值测试；
- 盲测包不暴露方法名，管理员映射与盲测目录分离；
- 完整 pytest、相关 Ruff、CLI `--help` 和 `git diff --check` 通过。

完成记录（2026-08-15）：

- 新增纯离线 `benchmark_style_engine.py`，不调用 LLM、Embedding、网络或新增评分算法；
- manifest 固定同一写作任务的 Baseline/Existing/New/Strict 正文及各方案真实注入片段，Existing 缺历史结果时明确报错而不伪造；
- 输出六类要求指标，并分别报告最大字符 8-gram、关键词、最长连续字符串和最高重合 reference ID；
- 输出确定性的 `summary.json`、`task_scores.csv`、`report.md`、匿名盲测包和分离的管理员映射；
- Author Profile 可从 JSON 或现有 corpus ID 读取，旧/失效 Feature 版本会被拒绝；
- 默认报告目录加入 `.gitignore`，示例 manifest 不包含私有正文、API Key 或真实路径内容；
- 新增 2 个自动化测试，验证具体距离/泄漏数值、实际 reference 要求、盲测匿名和逐文件重复性；
- 完整 pytest `84 passed`，相关 Ruff、CLI `--help` 和 `git diff --check` 通过。

## M14 — Local Style Engine 审查修复

目标：修复 M7～M13 交付后审查确认的本地可用性、规模性能和排序口径问题，不新增模型、依赖或独立检索管线。

范围与涉及文件：

- `style_window_service.py`、`style_rag_service.py`、`author_style_profile_service.py`：消除窗口构建 O(N²) 和全窗口常驻内存，避免把重叠窗口当作独立 Profile 样本；
- `embedding_backends.py`、Style Corpus 路由和原生 JavaScript：显式区分纯本地、本地 ONNX、远程 Embedding，禁止隐式复用 LLM API Key；
- `style_retrieval_service.py`、`style_rag_service.py`：为多 corpus 构造统一目标 Profile，统一 effective scene，并在 SQL 内限定 BM25 corpus；
- `generation_service.py`、`token_budget.py`：让严格重写预算使用同一条实际指令构造逻辑；
- 对应 pytest 与 JavaScript 语法检查。数据库 schema 和既有 API 字段保持兼容，只允许增加可选请求字段。

风险与回退：

- 统一多 corpus Profile 会改变多选语料时的排序，但单 corpus 口径保持不变；可通过恢复逐 corpus profile 解析回退，不影响数据；
- Profile 改用不重叠代表窗口后样本量会下降，这是对统计独立性的修正；旧 Profile 在版本标记变化后自动重建；
- 本地模型缺失、ONNX Runtime 缺失或向量签名不兼容时只关闭 semantic 辅助，纯本地 Style/BM25 检索继续工作；
- 不修改现有 SQLite 表，不进行数据删除或破坏性迁移。

验收标准：

- 单篇 5000 chunk 的窗口边界计算不再重复扫描整篇，导入路径不保存全部 `window_text`；
- 多 corpus 候选使用同一个合并目标 Profile，不能分别对各自 corpus 自归一化；
- UI 可无 Key 使用纯本地检索或本地 ONNX，远程 Embedding 仅在显式选择并填写独立 Key 后启用；
- auto scene 在 Profile、scene score 和返回元数据中一致；BM25 只能返回所选 corpus；
- 完整 pytest、Ruff、全部原生 JavaScript `node --check`、Rust `cargo check --locked` 和 `git diff --check` 通过。

实施记录（2026-08-15）：

- Style Window 的 chunk 字符数改为每篇只计算一次，窗口从 current chunk 按上限扩展；导入与 Signature 构建改用迭代接口，不再保存全部重叠窗口文本；
- Author Profile schema 升至 3，统计聚合只采用不重叠窗口；旧 schema 会被判定 stale 并通过现有链路自动重建；
- 多 corpus 检索使用一个合并 Dense Feature 目标，跨 corpus 不比较不兼容的 Signature 词表；单 corpus Signature 行为保持不变；
- auto scene 的 Profile、scene score 与调试元数据统一；BM25 在数据库查询 Top-N 前限制 corpus 和 enabled 状态；
- UI 显式选择本地 ONNX 或远程 Embedding，不再复用顶部 LLM Key；本地模式无需 Key；
- 严格重写提示与预算共用同一构造器，预算按最多六条差异预留；
- 新增窗口线性计数、重叠样本、多 corpus 合并目标、BM25 corpus 隔离和 FTS 不可用降级回归测试；完整 pytest `89 passed`，全量 Ruff、全部 JavaScript `node --check`、Rust `cargo check --locked` 与 `git diff --check` 通过；
- 清理了阻断全量 Ruff 的少量既有未使用导入、重复导入和单行分号，不改变对应业务行为；PyInstaller 默认明确排除可选 ONNX Runtime，并支持显式构建本地语义专用包。

开始重大 Style Engine 修改前，先在对应 milestone 下补充：目标、涉及文件、数据库/API 影响、风险、回退方法和本次验收命令。只有实际产物与验收证据齐全后才能将状态改为“已完成”。不得为了赶进度同时跨越多个未验收 milestone。

## M15 — 文风管理信息架构

目标：降低工作台信息密度，将 Style Corpus、Embedding 配置与 Style Retrieval Debugger 集中到独立的顶级“文风管理”页面；工作台只保留本次生成所需的模式、语料选择、强度和管理入口。

范围与兼容性：

- 仅调整 `index.html`、`styleCorpora.js`、`main.js` 与相关 CSS，不改变 Style RAG API、SQLite 数据或生成请求字段；
- “文风管理”与工作台、模板管理、生成记录同级，包含语料库 CRUD、文件导入、可选向量化、Embedding 后端/独立密钥以及检索评分调试；
- 模板专属 Style Card 和参考片段继续留在模板管理，因为其编辑对象依赖当前范例模板；
- 工作台保留可用语料库多选，因此现有勾选状态和生成流程不变。

风险与回退：

- DOM 元素迁移后原生 JavaScript 仍通过稳定 ID 绑定；新增测试保证关键元素唯一且不再出现在工作台；
- 页面切换时重新加载 corpus 列表，避免管理操作后工作台状态过期；回退只需恢复原 DOM 位置，不涉及数据迁移。

验收标准与实施记录（2026-08-15）：

- 顶栏存在同级“文风管理”，工作台不再展示 Embedding Key、后端选择和检索调试；
- 管理页完整覆盖新建、导入、向量化、清空、删除、刷新和检索调试；
- 新增首页结构回归测试；完整 pytest、全量 Ruff、全部 JavaScript `node --check`、Rust `cargo check --locked` 与 `git diff --check` 通过。

## M16 — 本地 Embedding 运行时与官方模型产物

状态：已完成。

目标：把 M8 已实现但尚未落地安装的本地 ONNX backend 变成可重复构建、可校验、可实际运行的 Windows CPU 能力。Embedding 仍只提供语义/场景辅助信号，不改变 Style-first 排序权重。

范围与兼容性：

- 从 `BAAI/bge-small-zh-v1.5` 官方 Hugging Face 仓库下载官方权重，在开发机临时环境中导出固定 opset 的 ONNX；不采用来源不明的第三方 ONNX 转换文件；
- 导出所需 PyTorch/Transformers 只存在于被 Git 忽略的构建环境，不进入应用依赖或 PyInstaller 发行包；
- 运行时只增加 `onnxruntime`，正式一键构建默认携带该 CPU runtime；约 96 MB 模型继续外置在 `%USERPROFILE%\.forestar-editor\models\bge-small-zh-v1.5`；
- 安装产物包含模型身份、版本、维度、opset、官方来源和 SHA-256；损坏或缺失时明确报错，并继续允许 Style-only 降级；
- 不修改数据库 schema、既有向量或检索权重；安装完成后由用户对需要语义辅助的 corpus 主动重新索引。

风险与回退：

- 首次构建需要下载临时导出依赖和官方模型，耗时、磁盘与网络开销明显；导出环境可在验证后删除；
- ONNX Runtime 会增加 sidecar 体积，但不携带 PyTorch，模型也不进入单文件 exe；
- 回退时可删除外置模型目录并用不含 `-BundleLocalEmbedding` 的后端构建，Style Feature/Profile/Signature 检索仍可运行。

验收命令：

- `powershell -ExecutionPolicy Bypass -File scripts\install-local-embedding.ps1`
- `.\.venv\Scripts\python scripts\verify_local_embedding.py`
- `.\.venv\Scripts\python -m pytest tests/test_embedding_backends.py tests/test_local_embedding_tools.py tests/test_style_retrieval_service.py`
- `.\.venv\Scripts\python -m ruff check server/services/embedding_backends.py scripts/export_local_embedding_model.py scripts/verify_local_embedding.py tests/test_embedding_backends.py tests/test_local_embedding_tools.py`

完成记录（2026-08-16）：

- 新增可重复的 Windows 安装流程：隔离下载官方权重、导出 opset 17 ONNX、生成带 SHA-256 的 manifest，并在成功后清理 PyTorch/Transformers 临时环境；
- `.venv` 已安装 `onnxruntime 1.27.0`，模型外置安装到用户模型目录；正式 `build:all`/`build:backend` 默认携带 ONNX CPU Runtime，但不携带模型或 PyTorch；
- 真实产物为 512 维、约 94.9 MB 的 ONNX；真实 CPU batch 推理中相近雨夜场景余弦分数 `0.544926`，无关厨房场景 `0.498866`；
- 增加模型/词表校验和验证与损坏模型拒绝测试；完整 pytest `92 passed`，全量 Ruff 通过，真实模型验证通过。

## M17 — 百万字本地向量化吞吐与进度反馈

状态：已完成。

目标：修复本地索引一次性把全 corpus 送入 ONNX 的超大 batch，改为有界分批推理，并让桌面端明确显示已完成片段、百分比、耗时和预计剩余时间。

范围与兼容性：

- 保持现有 chunk、Embedding backend 签名、向量格式、最终索引状态和 Style Retrieval 排序不变；
- `index_corpus` 增加可选进度回调并使用集中配置的 batch size，逐批推理和写入同一数据库事务，失败时整体回滚；
- 新增只读进度查询 API，进度只保存在 Sidecar 进程内，不新增数据库表；原同步 index API 的响应格式保持兼容；
- 原生 JavaScript 增加向量化进度弹窗，不引入前端框架；
- 不增加模型、不量化模型、不改变 embedding 数值算法。

实测基线（2026-08-16）：真实 corpus 为 1,328,470 字、2658 chunk、平均 441 字。128 个真实 chunk 的 Windows CPU 测试中，batch 1 为 15.92 chunk/s，batch 8 为 22.19 chunk/s；预计全量纯推理约 120 秒，另加分词、SQLite 写入和首次模型加载时间。当前无进度的单一 2658 大 batch 属于不合理实现。

风险与回退：

- 不同 CPU 的耗时差异较大，ETA 只能按当前已完成批次动态估算；
- Flask 必须能并发处理进度 GET 与索引 POST；当前开发服务和 Sidecar 均使用线程化本地服务；
- 回退仅需恢复单次 `embed_batch` 和移除进度 UI/API，不涉及数据库迁移或既有向量删除。

验收命令：

- `.\.venv\Scripts\python -m pytest tests/test_embedding_backends.py tests/test_style_rag_service.py tests/test_style_index_progress.py tests/test_app.py`
- `.\.venv\Scripts\python -m ruff check server/services/style_rag_service.py server/services/style_index_progress.py server/routes/style_corpora_routes.py tests/test_style_index_progress.py`
- `node --check server/static/js/styleCorpora.js`

完成记录（2026-08-16）：

- 本地索引改为固定 16 chunk 分批推理，远程兼容路径固定 32 chunk；不再创建 2658 chunk 的单一超大 ONNX batch；
- 每批完成后更新进程内进度，最终仍在同一 SQLite 事务提交；任一批失败会整体回滚，不留下被标记为完成的半索引；
- 新增进度查询 API 与原生桌面弹窗，显示百分比、完成/总片段数、已用时间和动态 ETA，完成或失败后才允许关闭；
- 真实 128 chunk 基准确认 batch 16 约 21.89 chunk/s，当前 2658 chunk 预计纯推理约 121 秒；实际耗时还包括首次模型加载、Python 分词与 SQLite 写入；
- 完整 pytest `95 passed`，全量 Ruff、全部原生 JavaScript 语法检查和 `git diff --check` 通过；包含 ONNX Runtime 的根目录 sidecar 已重新构建。

## M18 — 生成前 Style Retrieval 延迟优化

状态：已完成。

目标：缩短用户点击生成到首个 LLM 请求真正发出之间的本地准备时间，不改变 LLM、Style Score 权重、最终 Prompt API 或已建索引。

实测基线（2026-08-16）：对真实 `西游记` corpus（132.8 万字、2658 chunk、512 维本地向量）执行一次生成前检索，冷启动约 16.4 秒，随后一次约 21.8 秒。cProfile 显示约 1900 万次 Python 调用；主要浪费在所有 2658 个候选都执行内容泄漏检测，以及 60 个精排候选预先构造完整 60×60 内容 n-gram 多样性矩阵。完整 ORM 加载、本地 backend 初始化和 Style Score 全量计算是次要成本。

范围与兼容性：

- Style Dense/Signature 主分数仍覆盖全部合格候选，不能以内容或 semantic 预筛替代 Style-first；
- 内容泄漏检测只对初步高分池执行，并保留足够候选余量；Feature 解释只为最终调试候选生成；
- MMR 相似度改为按选择过程惰性计算并利用对称缓存，不再预算无用的全矩阵；
- 对完全相同且 corpus 版本未变化的短时间检索结果做有界进程内缓存，用于复用“生成前预检 → 正式生成”的重复检索；缓存不持久化、不包含 API Key 明文，corpus 更新后自动失效；
- 本地 query backend 复用已加载实例；远程 backend 不缓存密钥或客户端；
- 不修改数据库 schema、Embedding、Style Score 权重、Prompt 内容或文章生成 API。

风险与回退：

- 泄漏精排池过小可能漏掉被高泄漏惩罚后应补位的候选，因此使用显著大于最终 3–5 条的固定安全池并增加排名回归测试；
- 进程缓存占用受最大条目与 TTL 限制，返回前复制，避免调用者污染缓存；
- 回退只涉及检索服务内部实现，不需要重建语料或向量。

验收：真实 corpus 冷/热检索显著低于基线；A 文风近内容远仍可高于 B 内容近文风远；完整 pytest、Ruff、JavaScript 检查和打包版冒烟测试通过。

完成记录（2026-08-16）：

- Style Dense/Signature 仍对全部 2658 个候选评分；内容泄漏检测改用单调上界精确停止，确保未检查候选不可能进入最终 Top-60 后才停止；
- MMR 改为惰性候选对计算并对称缓存，自动测试确认选择结果与原完整相似度矩阵一致且调用数显著减少；
- Feature 命中解释只为最终返回片段生成，不再为全部候选生成；
- 增加最大 16 条、TTL 30 秒的版本化进程缓存，复用生成按钮的 Prompt 预检与正式生成之间完全相同的检索；缓存键包含 corpus/Profile 版本和 API Key 摘要，不存密钥明文；
- 真实 corpus 实测：冷检索 `16.393s → 2.415s`，不同 query 热检索 `21.789s → 1.686s`，完全相同的预检后检索约 `0.001s`；
- 完整 pytest `96 passed`，全量 Ruff、全部 JavaScript 语法检查与 `git diff --check` 通过。
