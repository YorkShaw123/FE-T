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
| M3 | SQLite 版本化存储与语料画像 | 未开始 | 幂等迁移、存储与聚合服务 |
| M4 | Style Diff 与可解释建议 | 未开始 | 距离、置信度、建议合并逻辑 |
| M5 | 本地风格检索与重排 | 未开始 | Feature 检索、去重复、多样性重排 |
| M6 | Prompt 渐进接入 | 未开始 | 向后兼容的 Style Guidance 注入 |
| M7 | 产品化、回归与发布门槛 | 未开始 | UI/任务状态、全量基准、发布检查 |

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

## M3 — SQLite 版本化存储与语料画像

范围：通过现有迁移机制保存文档/切片 Feature，并聚合 Corpus Style Profile。

验收标准：

- 迁移幂等；旧数据库可升级，现有 Style RAG 数据未改变；
- Feature 版本、样本量、可用性和分析范围可追踪；
- 重算和失败恢复不会留下半成品状态；
- 聚合不让单个超长文档或短异常片段支配结果；
- 数据库测试、pytest 和 Ruff 通过。

## M4 — Style Diff 与可解释建议

范围：比较目标 Profile 与文本，输出少量显著且不冲突的中文建议。

验收标准：

- 只比较相同 Feature 版本和双方可用值；
- 相关 Feature 采用分簇/组预算，避免重复计权；
- 短文本返回低置信或不比较，而非伪精确结论；
- 建议说明相对目标的方向，不评价文学质量；
- 合成扰动测试能识别已知变化；
- 相关 pytest 和 Ruff 通过。

## M5 — 本地风格检索与重排

范围：把 Feature 相似度用于候选检索或重排，并增加多样性与文本复用保护。现有 BM25/Embedding 路径继续兼容。

验收标准：

- 无远程 Embedding 时可以完成检索；
- Feature、BM25、旧 Embedding 等信号可独立开关并做消融比较；
- 同主题不同风格、同风格不同主题的测试优于现有基线；
- 近重复片段不会集中入选；
- 延迟和内存符合 Benchmark 门槛；
- 现有 Style RAG API 和数据回归测试通过。

## M6 — Prompt 渐进接入

范围：把 Style Diff 转为少量 Style Guidance，通过现有 Prompt Assembler 可选注入。

验收标准：

- 不新增破坏性的生成 API 必填字段；
- 关闭 Style Engine 时行为与当前版本一致；
- 缺失、失败或旧数据库状态可安全回退；
- Prompt 不直接注入全部统计值，不重复给出冲突建议；
- 文风匹配 Benchmark 改善，文本复用风险不劣化；
- 生成、Prompt 和回退路径测试通过。

## M7 — 产品化、回归与发布门槛

范围：补足用户可见状态、后台任务体验、全量回归、文档与打包检查。

验收标准：

- Windows 桌面端可完成导入、分析、生成和重算流程；
- 百万字分析不会长时间阻塞 UI，任务失败可理解、可重试；
- 旧用户数据库、旧语料库和旧生成流程通过回归；
- pytest、Ruff、JavaScript 语法检查、`cargo check --locked` 和构建检查按影响范围通过；
- 发布包体积、启动时间和内存变化已记录；
- README 与实际能力同步。

## 计划变更规则

开始重大 Style Engine 修改前，先在对应 milestone 下补充：目标、涉及文件、数据库/API 影响、风险、回退方法和本次验收命令。只有实际产物与验收证据齐全后才能将状态改为“已完成”。不得为了赶进度同时跨越多个未验收 milestone。
