# 项目级 Codex 指令

> 文件位置：项目根目录 `AGENTS.md`
>
> 本文件只负责**当前项目的事实、约束、启动规则与个性化信息**。通用工程原则继承自 `~/.codex/AGENTS.md`，不要在这里重复整套全局规则。

## 1. 核心原则

处理本项目时：

1. 先理解项目，再修改代码。
2. 优先遵守当前仓库已经形成的约定。
3. README、文档、测试、配置和代码都可能过期；发现冲突时必须指出，不得静默猜测。
4. 不要为了“最佳实践”重写一个已经能工作的项目。
5. 对已有项目优先做最小正确变更；对空项目先明确需求再搭建。
6. 不要编造项目背景、业务目标、技术约束或用户需求。

---

# 2. 项目启动检测（每个新仓库首次工作时执行）

先判断仓库属于哪种状态。

## 状态 A：空项目 / 几乎空项目

满足以下情况之一时，可视为尚未建立项目：

* 目录为空或只有 Git / 编辑器基础文件；
* 没有 README、源码、依赖清单、构建配置等足以判断项目性质的内容；
* 当前文件明显只是占位符。

此时**不要自行决定产品需求或技术栈**。

先向用户收集最关键的信息，一次最多询问 3～5 个问题，优先包括：

* 项目名称与一句话目标；
* 目标用户 / 核心使用场景；
* MVP 核心功能；
* 预期交付形态（Web / App / CLI / API / Library 等）；
* 已确定的技术栈、部署、安全或合规约束。

用户回答后：

1. 填写下方“项目画像”；
2. 只在必要时继续询问真正会影响架构的 Blocking Unknown；
3. 再进入 Bootstrap 流程；
4. 不要为了收集信息而无限访谈。

## 状态 B：已有 README + 已有项目

如果存在有意义的 `README.md` 且仓库已有源码/配置：

**第一优先读取 README。**

然后按相关性读取：

1. 根目录 `README.md`；
2. 依赖/构建清单，例如 `package.json`、`pyproject.toml`、`go.mod`、`Cargo.toml` 等；
3. 目录结构与主要入口；
4. `.env.example`、配置文件；
5. 测试目录与测试配置；
6. CI/CD；
7. `docs/`、ADR；
8. 数据库 schema / migrations；
9. 与当前任务直接相关的模块。

不要一开始无差别读取整个仓库。

读取后，基于**可观察事实**自动建立项目画像，并使用这些事实继续当前任务。

## 状态 C：已有项目，但 README 缺失或明显过时

不要因为没有 README 就把它当成空项目。

优先读取：

* 依赖/构建清单；
* 目录结构；
* 入口文件；
* 配置；
* 测试；
* CI；
* 关键模块。

从仓库事实推断技术画像。

如果 README 与代码明显冲突：

标记：

`README / Repository Mismatch`

说明冲突，并优先使用更能代表当前可运行状态的证据，同时建议后续同步 README。

---

# 3. 项目画像（由 Codex 自动维护）

> 本区块是项目特定信息的事实摘要。
>
> 如果字段可以从 README、代码、配置、测试或 CI **可靠推断**，Codex 可以自动填写。
>
> 如果无法可靠推断，保留 `TBD`，不得猜测。
>
> 自动填写时只更新本区块，不要借机重写本文件其他规则。
>
> 如果当前会话中修改了本区块，立即使用已发现的事实继续工作；无需等待下一次会话重新加载。

<!-- PROJECT_PROFILE_START -->

## 基本信息

* 项目名称：Forestar Editor
* 一句话描述：本地运行的 AI 文字创作助手，通过提示词模板组装指令并调用大语言模型 API 生成、编辑文章。
* 项目阶段：已有可运行与可打包的 1.0.0 桌面应用
* 目标用户：TBD
* 核心使用场景：管理提示词模板与风格语料，调用多家大语言模型生成、续写、重写、扩写和润色文章。
* 核心价值 / 业务目标：TBD

## 产品形态

* 类型：Windows 桌面应用；浏览器入口仅用于本机开发测试，不属于产品分发形态。
* 主要入口：桌面端 `Forestar Editor.exe`；开发测试入口为 `python server/app.py`。
* 主要用户流程：配置并启用提示词模板 → 填写模板变量与 API 密钥 → 可选配置 Style Card / Style RAG → 选择模型生成文章 → 编辑或查看历史记录。

## 技术栈

* 前端：原生 HTML / CSS / JavaScript，由 Flask 提供模板与静态资源；Tauri 2 WebView 承载桌面界面。
* 后端：Flask 3.1 本地 Sidecar，按 routes / services / database 分层。
* 语言 / Runtime：Python 3.10+、Rust 2021、JavaScript（ES Modules）、Node.js 18+。
* 数据库：SQLite，默认位于 `%USERPROFILE%\.forestar-editor\data\forestar.db`；Style RAG 同时使用 SQLite FTS5 与 BLOB 向量。
* ORM / 数据访问：Flask-SQLAlchemy 3.1；`server/database/migrations.py` 提供幂等轻量迁移。
* 缓存 / 队列：无独立缓存或消息队列。
* Auth：无账户认证；应用固定监听回环地址，并校验跨源写请求。
* 对象存储 / 第三方服务：无对象存储；通过各厂商 HTTP API 接入 DeepSeek、OpenAI、Kimi、通义千问、智谱 GLM、Google Gemini、xAI、硅基流动，Embedding 使用硅基流动 BGE-M3。
* 包管理器：npm（Tauri CLI）、pip（Python）、Cargo（Rust）。
* Monorepo / Workspace：单仓库混合技术栈，不使用 npm/Cargo workspace。

## 工程与运行

* 开发启动命令：后端本机测试 `.\.venv\Scripts\python server\app.py`；桌面开发 `npm run tauri:dev`。
* 构建命令：完整构建 `npm run build:all`；后端 `npm run build:backend`；Tauri/NSIS `npm run tauri:build`。
* Lint：未配置。
* Type-check：未配置独立命令；Rust 类型检查由 Cargo/Tauri 构建覆盖。
* 单元测试：未配置。
* 集成测试：未配置。
* E2E：未配置。
* 本地依赖 / Docker：开发需 Python 3.10+、Node.js 18+、Rust 工具链；未配置 Docker。
* CI/CD：未配置仓库 CI；通过 PowerShell、PyInstaller 与 Tauri CLI 在 Windows 本地构建。
* 部署目标：Windows x64 桌面端，提供同目录直接运行版与 current-user 模式的简体中文 NSIS 安装包。

## 代码结构

* 主要源码目录：`server/`（Flask 后端与 Web UI）、`src-tauri/`（Tauri/Rust 桌面壳）、`src/`（Tauri 启动等待页）。
* 核心模块：`server/routes/`、`server/services/`、`server/database/`、`server/templates/`、`server/static/`、`src-tauri/src/`。
* 测试目录：无。
* 文档目录：无独立 `docs/`；项目说明集中在 `README.md`。
* 数据库迁移目录：无独立迁移目录；幂等迁移集中在 `server/database/migrations.py`。
* 主要架构模式：单机模块化应用；Tauri 管理 Flask Sidecar 生命周期，Flask 内部采用路由层、服务层、数据访问层分层。

## 项目约束

* 已知安全要求：服务只能监听 `127.0.0.1`；跨源写请求必须拒绝；API 密钥仅由用户当次输入，不得写入文件或数据库；发布包不得共享固定 Flask `SECRET_KEY`。
* 已知性能要求：Style RAG 单库最多 5000 个切片、检索候选最多 5000 个；上传请求上限 20MB。
* 已知兼容性要求：主产品面向 Windows x64；开发/构建要求 Python 3.10+、Node.js 18+ 与 Rust 工具链；旧版项目内 SQLite 数据首次运行时复制迁移并保留原文件。
* 已知合规要求：TBD
* 明确禁止的技术 / 方案：浏览器模式不得作为远程访问或 Web 自托管能力；Style RAG 当前不引入 ChromaDB、Qdrant 等独立向量数据库。

## 当前已知风险 / 技术债

* 当前未配置自动化测试、Lint、独立类型检查或 CI，变更主要依赖针对性手工验证与构建验证。
* PyInstaller 单文件程序未签名，可能被杀毒软件误报。
* 模型 ID、接口能力和费用由第三方厂商控制，存在外部变更风险。

<!-- PROJECT_PROFILE_END -->

---

# 4. 自动填写项目画像的规则

自动填写不是“猜项目”，而是“总结仓库证据”。

## 可以自动填写

可以从以下证据可靠得到的信息：

* README 明确描述；
* manifest / lockfile；
* framework 配置；
* CI 脚本；
* Docker / Compose；
* `.env.example`；
* 数据库 schema；
* 测试配置；
* 清晰的目录与入口代码。

例如：

* `package.json` 明确包含 Next.js → 可填写前端框架；
* `pnpm-lock.yaml` → 可填写包管理器；
* Prisma schema 使用 PostgreSQL provider → 可填写数据库/ORM；
* `.github/workflows/ci.yml` 实际执行 `pnpm test` → 可填写测试命令。

## 不得自行填写

仅靠代码无法可靠得出的产品事实，例如：

* “目标用户是中小企业”；
* “核心价值是降低 30% 成本”；
* “预计 100 万 DAU”；
* “必须符合某项法规”；
* “未来一定会做微服务”。

这些字段保持 `TBD`，必要时再询问用户。

## 证据冲突

若 README、配置、测试、代码互相冲突：

1. 不要静默覆盖；
2. 指出冲突；
3. 判断哪个来源更可能代表当前真实运行状态；
4. 把不确定字段标记为 `TBD` 或附简短说明；
5. 若冲突影响当前任务，先解决或向用户确认。

---

# 5. 项目规则与局部约束

以下内容用于填写**当前项目真正特殊的规则**，不要复制全局工程常识。

<!-- PROJECT_RULES_START -->

## 必须遵守

* 桌面端是唯一产品分发形态；本机浏览器入口只用于开发测试。
* Flask 服务必须固定监听 `127.0.0.1`；桌面端端口由 Tauri 探测后通过 `FORESTAR_PORT` 传递。
* API 密钥必须保持仅当次使用，不得持久化到文件或数据库。
* 新增数据库结构变更必须沿用 `server/database/migrations.py` 的幂等 SQLite 迁移机制，并兼容已有用户数据库。
* 修改构建或分发方式时，保持 `Forestar Editor.exe` 与 `forestar-server.exe` 同目录直接运行的约定。

## 禁止事项

* 禁止把开发用浏览器入口扩展为远程监听或自托管服务。
* 禁止将模型提供商协议差异散落到路由层或前端；统一收敛在 `server/services/api_client.py`。
* 未经明确需求，不为 Style RAG 引入独立向量数据库或其他常驻基础设施。

## 目录 / 模块边界

* HTTP 路由与输入输出处理放在 `server/routes/`；领域校验与业务逻辑放在 `server/services/`；数据库模型与迁移放在 `server/database/`。
* 文章生成公共门面为 `server/services/generation_service.py`；局部编辑与生成记录逻辑分别位于 `server/services/generation/editing.py` 和 `records.py`。
* 提示词编排、Style Card、风格片段和 Style RAG 分别由现有对应 service 模块负责，新增逻辑应保持该职责边界。

## API / 数据约定

* API 统一返回 JSON；失败响应沿用 `success: false` 与中文 `error` 文案。
* 外部 LLM/Embedding 调用通过 `server/services/api_client.py` 适配，模型与提供商配置集中在 `server/config.py`。
* SQLite 用户数据默认存放在 `%USERPROFILE%\.forestar-editor\data`；仅开发测试可用 `FORESTAR_DATA_DIR` / `DATABASE_URL` 覆盖。

## UI / 设计系统约定

* 桌面 UI 复用 `server/templates/` 与 `server/static/`，不要为 Tauri 另建重复前端。
* 前端继续沿用原生 HTML/CSS/JavaScript 与现有模块拆分；未有明确需求时不引入前端框架。

## Git / 发布约定

* 发布版本号需同步检查 `package.json`、`src-tauri/Cargo.toml`、`src-tauri/tauri.conf.json` 与 Windows 后端版本信息文件。
* 生成物 `build/`、`dist/`、`src-tauri/target/`、`src-tauri/binaries/` 及根目录两个 exe 不纳入 Git。

<!-- PROJECT_RULES_END -->

Codex 可以在发现明确、稳定且项目特有的约定时补充本区块，例如：

* “所有数据库访问必须经过 `packages/db`”；
* “前端默认使用 Server Components”；
* “禁止引入 Redux”；
* “新增环境变量必须同步 `.env.example`”。

不得把临时任务要求写成永久项目规则。

---

# 6. 已有项目的工作方式

当项目不是空项目时：

1. 先读取 README 和当前任务相关的仓库事实；
2. 确认项目画像中与当前任务相关的信息；
3. 查找项目现有实现模式；
4. 优先沿用已有架构、命名、错误处理、测试和目录惯例；
5. 再选择合适的工作模式：Feature / Bug Fix / Refactor / Investigation / Quick Change / Architecture；
6. 只读取完成当前任务所需的上下文；
7. 执行最小正确变更；
8. 使用仓库实际存在的命令验证；
9. 如果行为、配置或架构发生重要变化，同步相关文档与项目画像。

不要每次任务都重新做完整项目盘点。项目画像已可靠填写后，只需验证与当前任务有关的部分。

---

# 7. 空项目的 Bootstrap 流程

当确认是空项目，并已经获得必要需求后：

## Stage 0 — Requirements

至少明确：

* Problem
* Users
* Goals
* Non-goals
* MVP
* User Stories
* Acceptance Criteria

必要时创建 `docs/product.md`。

## Stage 1 — Architecture

只设计当前 MVP 需要的架构，覆盖：

* 系统边界；
* 核心组件；
* 数据模型；
* API / 外部契约；
* Auth / Security；
* 部署方式；
* 关键权衡。

必要时创建 `docs/architecture.md` 和 ADR。

## Stage 2 — Engineering Foundation

根据技术栈建立适量基础设施：

* 项目结构；
* 包管理 / 依赖；
* lint / format / type-check；
* 环境变量；
* 测试；
* CI；
* 本地开发环境；
* README。

不要一次性搭建未来可能才需要的基础设施。

## Stage 3 — First Vertical Slice

选择最小但真实的用户流程，完成：

数据 → 服务 / API → UI（如有）→ 测试 → 文档。

确保项目首次真正可运行、可验证。

---

# 8. README 与项目事实

README 是已有项目的首要入口，但不是绝对真理。

优先级按具体问题判断，通常参考：

1. 用户当前明确要求；
2. 已批准 ADR / 项目级规则；
3. 可执行测试和 CI；
4. 当前配置与可运行实现；
5. README / docs；
6. 历史注释。

如果 README 描述的是目标架构，而代码仍处于迁移途中，必须明确区分“目标状态”和“当前状态”。

---

# 9. 项目文档

若项目已有 `docs/`，优先遵循其组织方式。

如果没有，不要为了简单任务强制创建大量文档。

常见最小集合可为：

* `docs/product.md`
* `docs/architecture.md`
* `docs/development.md`
* `docs/testing.md`
* `docs/adr/`

只有实际需要时再增加 security、deployment、api、database、operations 等文档。

---

# 10. 当前任务执行规则

用户给出任务后：

* 若属于简单、低风险、局部修改：直接执行；
* 若涉及架构、数据库、Auth、公共 API、新生产依赖、跨模块大改：先给简短计划；
* 若是调查任务：默认只分析，不修改，除非用户明确要求实施；
* 若信息不足但不影响核心方案：使用安全默认值并说明；
* 若属于真正的 Blocking Unknown：再询问用户；
* 不要重复询问仓库已经能够回答的问题。

完成后简洁说明：

* 改了什么；
* 为什么；
* 如何验证；
* 哪些验证未执行；
* 是否有需要用户决策的后续项。

---

# 11. 项目画像维护时机

在以下情况发生后，检查是否需要更新“项目画像”：

* 初次接手已有项目；
* 技术栈发生真实变化；
* 启动 / 构建 / 测试命令改变；
* 核心目录或模块边界改变；
* 数据库 / Auth / 部署方式改变；
* 项目明确新增长期约束。

不要因为每个普通功能变更都修改项目画像。

---

# 12. 启动指令

现在开始处理当前仓库：

1. 判断它是空项目、已有项目，还是 README 缺失/过时的已有项目；
2. 如果是已有项目：优先读取 README，再读取与项目识别和当前任务相关的代码/配置；
3. 基于可靠证据填写或刷新“项目画像”中的 `TBD`；
4. 如果是空项目：不要自行假设需求，向用户收集 3～5 个最关键的信息；
5. 完成项目识别后，再执行用户当前任务；
6. 不要为了初始化画像而阻塞一个本来可以立即完成的低风险任务。
