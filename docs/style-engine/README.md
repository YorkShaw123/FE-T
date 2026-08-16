# Flora Style Engine 文档入口

Style Engine 的目标是：在普通 Windows CPU 电脑上，使用纯本地、轻量、可解释的方法分析中文写作风格，并把可执行的风格约束交给现有 Prompt 组装流程。它关注句长、节奏、标点、功能词、基础句法和语言组织习惯，不承担世界知识检索，也不以复制原文内容为目标。

## 当前状态

项目目前已有 Style RAG、Style Profile 和 Style Excerpt：

- Style RAG 负责导入语料、切片、规则标签、Embedding、BM25/向量混合检索和 MMR 重排。
- Style Profile 使用模型生成较抽象的 Style Card。
- Style Excerpt 从范例中生成带标签的参考片段。
- Prompt Assembler 将可用的 Style Card、片段和语料检索结果注入生成 Prompt。

Style Engine 是在这些能力旁边逐步增加的本地风格分析层，不是一次性替换现有系统。迁移期间必须保留旧 API 和旧 Style RAG 数据。

## 文档地图

- [ARCHITECTURE.md](ARCHITECTURE.md)：当前架构、目标架构、组件边界和兼容策略。
- [EXEC_PLAN.md](EXEC_PLAN.md)：按里程碑推进的执行计划、状态和验收标准。
- [STYLE_FEATURE_V1.md](STYLE_FEATURE_V1.md)：V1 Feature 的结构、设计原则和待验证决策；当前不是最终算法清单。
- [BENCHMARK.md](BENCHMARK.md)：文风匹配、稳定性、性能和文本复用风险的评测方案。

## 不变约束

- 正式产品仍是 Tauri + Flask Sidecar 的 Windows 本地桌面程序。
- Style Engine 默认离线运行，优先中文，CPU 和内存成本适合普通电脑。
- 优先复用 SQLite、NumPy 和当前 Flask 服务分层。
- 不引入大型向量数据库或大型神经网络运行时。
- 数据库变化必须可迁移，现有生成 API 和 Style RAG 数据必须保持兼容。
- 每个算法阶段都必须有自动化测试和可重复的 Benchmark。

## 文档维护规则

`EXEC_PLAN.md` 是实施状态的唯一入口。重大设计变化先更新架构和执行计划；算法经过基准验证并被接受后，再在 Feature 文档中冻结具体口径。文档中的“目标”不能被描述成已经实现的能力。

