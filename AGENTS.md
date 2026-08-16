# Flora Editor 项目级开发约束

本文件只记录本项目长期有效、每次开发都必须遵守的约束。通用工程规则遵循上级 `AGENTS.md`。

## 产品与架构

- Flora Editor 是 Windows 本地桌面程序。
- Tauri 2 + Flask Sidecar 是正式产品架构；浏览器入口只用于本机开发测试。
- 不得擅自把项目改造成 Web、SaaS、远程服务或自托管平台。
- 用户数据使用本地 SQLite；数据库变更必须通过 `server/database/migrations.py` 的现有幂等迁移机制完成，并兼容已有数据。
- 尽量保持现有文章生成 API、Style RAG API 和持久化数据向后兼容。

## Style Engine

- Style Engine 默认必须完全本地工作，不得依赖远程 Embedding API；远程能力只能作为明确设计后的可选增强。
- Style Engine 必须优先支持中文，算法口径、测试样例和评测基准均以中文为主。
- 优先复用 SQLite、NumPy 和现有 services/routes/database 分层，不引入不必要的大型依赖或独立向量数据库。
- 不得把 PyTorch、TensorFlow 等大型运行时直接加入发行包，除非后续已有明确设计决定、体积评估和回退方案。
- 不得一次实现整个 Style Engine；必须按 `docs/style-engine/EXEC_PLAN.md` 的 milestone 逐阶段实施。
- 对重大 Style Engine 修改，先更新 `docs/style-engine/EXEC_PLAN.md`，写清范围、兼容性、风险和验收标准，再修改业务代码。
- Style Feature、相似度、检索、重排、文本复用检测或 Prompt 约束算法发生变化时，必须新增或更新自动化测试。

## 验证与数据

- 每个实施阶段必须运行与改动相关的 pytest 和 Ruff；涉及 Rust/Tauri 或前端脚本时，再运行对应静态检查。
- 不得声称未实际运行的检查已经通过；未验证项必须说明原因。
- 不得把测试用的百万字私人语料、受版权保护的完整作品、API Key、用户数据库或真实生成记录加入 Git。
- 基准测试优先使用可公开再分发、明确授权或程序生成的小型固定样本；大型私人语料只允许在本地通过忽略路径使用。

