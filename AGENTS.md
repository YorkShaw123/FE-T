# Flora Editor 项目级开发约束

本文件只记录本项目长期有效、每次开发都必须遵守的约束。通用工程规则遵循上级 `AGENTS.md`。

## 当前阶段与目标形态（2026-11 起生效）

- 项目正在进行 Agent 架构重构，成果沉淀在新包 `backend/`（FastAPI + LangGraph + 三层兜底 + 三张 Agent 图）。
- **Windows 桌面端不再是最终目标。** Tauri 壳（`src-tauri/`）、NSIS 安装包与 PyInstaller 冻结包（`flora-server.spec`、`run_server.py`）**不再是验收项**，不要求冻结产物可运行；不要在这上面继续投入。
- 运行与自测基准统一为源码模式：`python run_server.py`（读 `FLORA_PORT`），或 `uvicorn backend.main:app`。
- 最终目标形态（本地服务 + 浏览器 / 服务器部署 / 其他）尚未决策。在决策前，**新增依赖与部署方式以"源码可跑"为唯一硬约束**，不要为桌面体积做妥协。
- 旧 `server/`（Flask）在新后端通过完整回归前保持可运行，退场必须单独提交、可 `git revert`。

## 产品与架构

- 新代码一律写在 `backend/` 包内，分层固定为 `api → agents → core/db`，`services` 不依赖 FastAPI，适配器不依赖 API 层。
- 不引入超过需要的分层与抽象；能复用 `services/` 里既有纯算法模块就复用，不要重写。
- 数据库仍是本地 SQLite；变更必须通过 `backend/db/migrations.py` 的幂等迁移完成，并兼容已有用户数据。
- 对外接口双轨：新路径挂 `/api/v1/*`，旧 `/api/*` 以别名装饰器保留，直到前端迁移完成。
- 尽量保持现有文章生成 API、Style RAG API 和持久化数据向后兼容。

## Style Engine

- Style Engine 默认必须完全本地工作，不得依赖远程 Embedding API；远程能力只能作为明确设计后的可选增强。
- Style Engine 必须优先支持中文，算法口径、测试样例和评测基准均以中文为主。
- 检索后端通过 `core/knowledge_base.KBBackend` 协议接入；新增实现只加适配器，不改图与路由。
- 语义向量属于可选增强：没有 embedding 运行时就必须降级为纯 Style 路径，并在 `meta.signals` / `missing_signals` 里如实标注。
- 不得把 PyTorch、TensorFlow 等大型运行时引入默认运行路径；确需引入必须有独立设计、体积评估与回退方案。
- 重大 Style Engine 修改先更新 `docs/style-engine/EXEC_PLAN.md`，写清范围、兼容性、风险与验收标准，再改业务代码。
- Style Feature、相似度、检索、重排、文本复用检测或 Prompt 约束算法发生变化时，必须新增或更新自动化测试。

## 功能取舍（已决策）

- **`smart` 风格链（智能风格链）已停用**：`style_mode='smart'` 不再提供降级或回退路径，直接按停用处理并给出明确提示。不要恢复成"静默降级"。
- 搜索/检索的 `style_score` 在统计画像迁移完成前固定为 0；它是常数项，不影响排序，但必须在返回的 `meta` 里标注缺失信号。

## 验证与数据

- 每个实施阶段必须运行全量 pytest 与 Ruff；涉及前端脚本时再跑 `node --check`。Rust/Tauri 检查仅在被要求时执行。
- 不得声称未实际运行的检查已经通过；未验证项必须说明原因。
- 不得把测试用的百万字私人语料、受版权保护的完整作品、API Key、用户数据库或真实生成记录加入 Git。
- 基准测试优先使用可公开再分发、明确授权或程序生成的小型固定样本；大型私人语料只允许在本地通过忽略路径使用。

## 文档口径

- 设计与迁移材料放在 `docs/agent-migration/`，其中 `04-非技术人员指南.md` 用于对外讲述（简历/答辩），修改时保持"无表格、口语化、按知识点讲"的风格。
- `docs/HANDOVER.md` 是接手入口，架构或运行方式变化时必须同步更新。
