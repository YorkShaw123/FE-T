# Forestar Editor 项目架构审计报告

> 审计日期：2026-08-11；高/中高风险整改复核：2026-08-13
> 审计范围：当前工作区中的应用源码、构建配置、部署配置与说明文档  
> 审计方式：初始报告采用静态分析；整改后执行语法检查与本地临时数据库烟雾测试，未调用外部模型、未执行压力测试
> 说明：本报告中的“问题”和“风险”是基于当前源码的架构判断，不等同于已确认的线上故障。

## 0. 执行摘要

Forestar Editor 是一个以 **Windows 桌面应用为唯一产品形态** 的本地 AI 文字创作工具。其运行时由 Tauri 桌面壳启动 PyInstaller 打包的 Flask Sidecar，页面使用 Flask 模板和原生 JavaScript，通过回环 HTTP API 与后端交互；浏览器入口仅供本机开发测试。

项目已经形成较清晰的“路由层—服务层—持久化层”结构，并具备模板版本、流式生成、Token 预算、Style Card、Style RAG、局部编辑和历史记录等完整业务能力。当前最值得关注的问题集中在：

1. 桌面 Sidecar 与本机浏览器测试共用同一套后端；服务现已强制绑定回环地址，不再提供 Web 自托管能力。
2. Flask 开发服务器承担本机 Sidecar，长耗时生成/向量化任务仍同步占用请求线程，但昂贵模型任务已限制为单并发。
3. 配置、模型元数据、提示词和协议适配较集中，第三方 API 变化会产生较大维护面。
4. SQLite 同时承载业务数据、全文索引和向量 BLOB，适合本地单用户，但扩展到多用户或大语料时存在明显上限。
5. 前端为原生 ES Modules，模块边界已有雏形，但仍依赖全局 DOM、共享状态和字符串协议，缺少端到端类型约束。

## 1. 技术栈

### 1.1 桌面与运行容器

| 层次 | 技术 | 用途 |
|---|---|---|
| 桌面壳 | Tauri 2 | Windows 桌面窗口、Sidecar 生命周期管理、安装包构建 |
| 桌面后端 | Rust | 启动 Flask Sidecar、分配随机端口、健康检查、退出清理 |
| 后端打包 | PyInstaller | 将 Python/Flask 后端打包为 `forestar-server.exe` |
| 构建入口 | npm scripts + PowerShell | 串联后端打包和 Tauri 构建 |

### 1.2 后端

| 技术 | 用途 |
|---|---|
| Python 3.10+ | 后端业务实现 |
| Flask 3.x | HTTP 服务、页面渲染、Blueprint API |
| Flask-SQLAlchemy / SQLAlchemy | ORM 与数据库会话 |
| SQLite | 模板、风格信息、生成历史、设置、FTS 数据持久化 |
| SQLite FTS5 trigram | Style RAG 的中文 BM25 文本召回 |
| NumPy | 向量矩阵计算、余弦相似度和 MMR 重排 |
| `urllib.request` | 轻量实现第三方 LLM/Embedding HTTP 客户端 |
| python-docx / pywin32 | DOCX/DOC 文本提取 |

### 1.3 前端

| 技术 | 用途 |
|---|---|
| HTML5 + Flask/Jinja 模板 | 单页工作台主体 |
| CSS | 全部界面样式、暗色/亮色主题、面板和编辑器布局 |
| 原生 JavaScript ES Modules | 模板管理、生成、历史、风格、编辑器和 UI 状态 |
| Fetch + ReadableStream | REST 请求与 SSE 流式内容消费 |
| localStorage | 主题、缩放和工作台草稿等客户端偏好 |

### 1.4 外部服务

后端通过官方 OpenAI 兼容接口统一封装 DeepSeek、OpenAI、月之暗面 Kimi、阿里云通义千问、智谱 GLM、Google Gemini、xAI Grok 与硅基流动。Style RAG 的 Embedding 默认使用硅基流动的 `BAAI/bge-m3`；不再依赖明文 HTTP 或 Gemini 非官方中转。

## 2. 文件结构

```text
Forestar_Editor/
├─ server/                         # Flask 应用
│  ├─ app.py                       # 应用工厂、运行模式、数据迁移、健康检查
│  ├─ config.py                    # 模型、Token、Embedding、数据库等配置
│  ├─ database/
│  │  ├─ __init__.py               # SQLAlchemy 初始化、SQLite PRAGMA
│  │  ├─ models.py                 # ORM 实体
│  │  └─ migrations.py             # 幂等式 SQLite 轻量迁移
│  ├─ routes/
│  │  ├─ template_routes.py        # 模板 CRUD、版本、导入导出
│  │  ├─ generation_routes.py      # 生成、预览、编辑、历史 API
│  │  ├─ style_routes.py           # Style Card 与风格片段 API
│  │  ├─ style_corpora_routes.py   # Style RAG 语料、索引、检索 API
│  │  └─ support/                  # 请求解析和文档文本提取
│  ├─ services/
│  │  ├─ api_client.py             # LLM/Embedding 协议适配
│  │  ├─ generation_service.py     # 正文生成总编排
│  │  ├─ prompt_assembler.py       # 三种提示词组装模式
│  │  ├─ template_service.py       # 模板领域逻辑和版本控制
│  │  ├─ style_profile_service.py  # Style Card 分析与校验
│  │  ├─ style_excerpt_service.py  # 单篇范例切片、标注、选择
│  │  ├─ style_rag_service.py      # 语料切片、向量化、混合检索
│  │  ├─ token_budget.py           # Token 估算与上下文预算
│  │  ├─ summarizer.py             # 长前情压缩
│  │  └─ generation/               # 局部编辑与记录管理
│  ├─ templates/index.html         # 主工作台页面
│  └─ static/                      # CSS、JS、图标
├─ src/index.html                  # Tauri 等待后端就绪页面
├─ src-tauri/                      # Tauri/Rust 桌面工程
│  ├─ src/lib.rs                   # Sidecar 启停和窗口逻辑
│  ├─ src/main.rs                  # 桌面程序入口
│  ├─ capabilities/default.json    # Tauri 权限
│  ├─ binaries/                    # 构建时放置的 Sidecar
│  ├─ icons/                       # 多平台图标
│  ├─ Cargo.toml
│  └─ tauri.conf.json
├─ scripts/                        # Windows 构建脚本
├─ forestar-server.spec            # PyInstaller 配置
├─ package.json                    # Tauri CLI 与构建命令
├─ requirements.txt                # Python 依赖
└─ README.md                       # 产品、使用和构建说明
```

`.venv/`、`node_modules/`、`src-tauri/target/`、`dist/`、根目录 EXE 和 Python `__pycache__/` 属于依赖、缓存或构建产物，不是业务源码。

## 3. 核心功能

### 3.1 提示词模板

- 按人物、背景、剧情、范例文章和约束分类管理。
- 支持 `{{变量}}` 占位符、启用/禁用、排序和变量记忆。
- 内容修改形成版本链，支持查看历史和恢复版本。
- 支持 JSON/Markdown 导出以及 JSON 导入。

### 3.2 文章生成

- 支持同步生成接口和默认使用的 SSE 流式生成接口。
- 支持多模型、多提供商、思考模式和 reasoning 内容展示。
- 生成前执行提示词预览和 Token 预算检查。
- 过长前置文章可调用模型压缩；异常时有简单截断回退。
- 可选执行第二次“去 AI 味”模型调用。
- 保存正文、去 AI 版、思考内容、提示词快照和模板快照。

### 3.3 提示词组装

项目包含三种组装方式：

1. **原文拼接（legacy）**：按模板顺序填充变量并拼接。
2. **结构化消息**：将角色设定、背景、剧情、示例与约束编排为不同消息段。
3. **智能风格链**：结合 Style Card、单篇风格片段或 Style RAG 检索结果注入风格约束；不可用时回退普通提示词并返回原因。

### 3.4 风格系统

- **Style Card**：调用 LLM 将范例文章解析为结构化的叙事、节奏、语言和对话特征。
- **Style Excerpt**：切分单篇范例，由 LLM 批量标注场景、视角、情绪和节奏，并在生成时挑选相关片段。
- **Style RAG**：导入 TXT/DOC/DOCX，规则切片和打标，调用 Embedding API 生成向量；检索采用向量召回、FTS5/BM25、RRF 融合及 MMR 去冗余。

### 3.5 编辑与历史

- 全屏 Markdown 编辑。
- 对选区执行续写、重写、扩写和润色。
- 保存人工编辑版和局部 AI 操作历史。
- 历史记录支持分页、查看、评分、备注、置顶、删除和清空。

## 4. 用户操作流程

### 4.1 桌面启动流程

```text
用户运行 Forestar Editor.exe
  → Tauri 选择本机空闲端口
  → 设置 FORESTAR_PORT / FORESTAR_RUN_MODE
  → 启动 forestar-server Sidecar
  → 轮询 /api/health
  → 后端就绪后将窗口导航到本地 Flask 页面
  → 用户退出时终止 Sidecar
```

### 4.2 首次配置与创作流程

```text
进入工作台
  → 前端加载模型清单和模板分组
  → 用户创建或导入普通模板
  → 用户启用模板并填写变量、标题和前情
  → 选择提供商、模型、思考模式和风格模式
  → 可选选择 Style RAG 语料库与去 AI 化
  → 输入 API Key
  → 预览提示词并检查 Token 预算
  → 发起流式生成
  → 查看正文、思考内容及去 AI 版本
  → 复制、下载或进入全屏编辑
  → 结果与编辑历史保存到 SQLite
```

### 4.3 Style RAG 使用流程

```text
创建语料库
  → 上传 TXT/DOC/DOCX
  → 提取文本、切片、规则打标
  → 使用 Embedding API Key 批量向量化
  → 在工作台勾选语料库
  → 生成时根据当前剧情执行混合检索
  → 选择 3～5 个低冗余风格片段
  → 注入智能风格链提示词
```

## 5. API 调用流程

### 5.1 内部 API 分组

| 前缀 | 主要职责 |
|---|---|
| `/api/health` | Sidecar 健康检查和运行模式识别 |
| `/api/templates` | 模板 CRUD、版本、导入导出 |
| `/api/generation` | 模型列表、文档提取、预览、生成、局部编辑、记录 |
| `/api/style-profiles` | Style Card 与单篇风格片段 |
| `/api/style-corpora` | 语料库、切片、向量化和检索测试 |

### 5.2 流式文章生成调用链

```text
generation.js
  → POST /api/generation/preview-prompt
  → GenerationRequest 解析并校验请求
  → prompt_assembler 读取模板并构造消息
  → token_budget 估算输入、输出和安全余量
  → 前端根据 ok / warning / over 决定是否继续

generation.js
  → POST /api/generation/generate-stream
  → generation_routes.generate_stream
  → generation_service.generate_article(stream=True)
  → 加载模板、填充变量、处理前情
  → 按 style_mode 组装消息
      ├─ legacy / structured
      └─ smart：Style Card/Excerpt/RAG 检索
  → LLMClient.stream_chat_completion
  → 第三方 Chat Completions/Gemini 接口
  → 后端转发 SSE：reasoning / content / status
  → 可选发起第二次去 AI 化调用
  → 写入 GenerationRecord
  → SSE complete 携带 record_id 和最终内容
  → 前端增量渲染并开放编辑器
```

### 5.3 外部 API 封装

`LLMClient` 根据 provider 选择 `base_url` 和请求协议，统一处理 Bearer Token、超时、有限重试、同步响应、SSE 流和 Embedding。API Key 从浏览器请求体进入 Flask，仅用于当次上游请求，ORM 模型未定义 API Key 字段。

## 6. 数据流

### 6.1 运行时数据流

```text
用户输入 / localStorage 草稿
  → 浏览器 DOM 与 JS state
  → JSON 或 multipart/form-data
  → Flask Blueprint
  → 请求解析/领域服务
  ├─ SQLite：读取模板、风格资料和历史
  ├─ 文件解析：TXT/DOC/DOCX → 纯文本
  └─ 第三方 API：Chat Completion / Embedding
       → 返回正文、reasoning 或向量
  → SQLite：保存业务结果和快照
  → JSON/SSE 返回前端
  → DOM 渲染、复制或本地下载
```

### 6.2 持久化实体关系

- `PromptTemplate`：模板主体，同时通过父记录/版本字段形成版本链。
- `StyleProfile`：与范例模板关联的单份 Style Card。
- `StyleExcerpt`：隶属于 StyleProfile 的可检索风格片段。
- `StyleCorpus`：独立的大规模风格语料库元数据。
- `StyleChunk`：隶属于语料库，保存文本、标签和 float32 向量 BLOB。
- `GenerationRecord`：正文、去 AI 版、编辑版、reasoning、提示词、模板/变量/风格快照。
- `ProjectSetting`：非敏感键值设置；设计上不保存 API Key。

### 6.3 数据存储位置

- 默认数据库：`%USERPROFILE%/.forestar-editor/data/forestar.db`。
- `FORESTAR_DATA_DIR` 可覆盖数据目录，`DATABASE_URL` 可覆盖数据库连接。
- 本机测试模式与桌面模式默认共享数据库；旧版项目内 `data/` 首次运行时复制迁移到公共目录。
- 浏览器侧 localStorage 保存主题和工作台草稿；当前草稿字段不包含顶部 API Key。

## 7. 当前架构问题

### 7.1 安全边界未按桌面/Web 模式拆分（高）

历史版本允许通过 `FORESTAR_HOST` 对外自托管，而 API 没有面向多用户的认证和权限模型。

> **已解决（2026-08-13）**：删除 Docker 自托管入口，`app.py` 忽略外部 host 配置并固定监听 `127.0.0.1`；桌面版成为唯一产品场景，本机浏览器入口仅用于测试。

### 7.2 使用 Flask 开发服务器承载实际运行（高）

`app.run()` 用于打包后的本机 Sidecar 及浏览器测试。流式生成、文档解析和批量向量化是长耗时操作，仍可能长期占用请求线程并受异常退出影响。

> **风险降级（2026-08-13）**：Web 自托管已移除，Flask 仅作为本机 Sidecar/测试服务；昂贵模型操作增加进程内单任务锁。替换 WSGI 会影响 SSE 与 PyInstaller，当前桌面场景暂不引入额外服务器依赖。

### 7.3 长任务缺少独立任务模型（高）

语料导入、Embedding 批处理、Style Card 分析和文章生成都在 HTTP 请求生命周期内执行。浏览器断开、桌面退出或上游超时可能留下“调用已发生但客户端不知道结果”的状态；项目也缺少任务 ID、持久状态、进度恢复和取消传播机制。

### 7.4 服务层职责偏重（中高）

`generation_service.py` 同时处理请求编排、前情压缩、提示词选择、上游调用、流式事件和记录保存；`prompt_assembler.py` 同时承担模板读取、模式决策和风格注入。功能继续增长时，条件分支和组合测试成本会快速上升。

### 7.5 API 契约是隐式的（中高）

前后端通过手写 JSON 字段和 SSE 字符串事件协作，没有 OpenAPI、JSON Schema、共享 DTO 或静态类型。字段重命名、默认值变化或新增事件时，错误通常只能在运行时发现。

> **部分缓解（2026-08-11）**：前端通用 `api()` 已统一 HTTP 状态、JSON 解析和业务错误处理；语料导入与模板导出的直接 `fetch` 也补充了状态检查。完整契约化仍需要 OpenAPI/Schema，暂未进行大规模改造。

### 7.6 SQLite 被赋予过多职责（中）

SQLite 同时保存核心业务数据、FTS5 索引和大量向量 BLOB。该方案非常适合本地单用户和轻量发布，但全文索引一致性、批量向量写入、数据库体积、备份耗时和多实例写锁会随语料规模增加而放大。

### 7.7 数据库迁移机制能力有限（中）

当前采用手写 `ALTER TABLE` 和 `CREATE TABLE IF NOT EXISTS` 的幂等迁移，没有显式 schema version、迁移历史、回滚策略和迁移事务边界。复杂结构变更或失败后的半迁移状态较难治理。

### 7.8 配置与提供商适配集中且静态（中）

模型列表、上下文窗口、网关地址、默认提示词和协议差异集中在源码配置中。模型下线、名称变化、上下文调整或网关协议变化都需要重新发布客户端，且配置事实可能与真实上游能力漂移。

### 7.9 前端状态与 DOM 耦合较强（中）

虽然 JavaScript 已按功能拆分，但模块共享单例 `state`，大量行为依赖固定 DOM ID、HTML 字符串和跨模块导入。缺少集中状态转换、组件生命周期和视图测试，复杂面板之间容易出现隐式联动。

> **暂缓**：彻底解决需要引入组件化视图、集中状态模型或前端框架，并重写大量事件绑定，回归风险明显高于当前危害。本轮只修复具体链路与错误处理，不宣称该结构性问题已解决。

### 7.10 源码、依赖、缓存和发布产物混放（低至中）

工作区中存在 `.venv`、`node_modules`、`src-tauri/target`、`dist`、Sidecar 和根目录 EXE。即使部分已被 Git 忽略，仍增加扫描、备份、IDE 索引、磁盘占用和误提交风险，也使“源码状态”与“已发布二进制是否最新”难以直观看出。

## 8. 潜在风险

| 等级 | 风险 | 触发条件与影响 |
|---|---|---|
| 已解决 | 未授权远程访问 | **2026-08-13**：所有模式固定监听 `127.0.0.1`，删除 Docker/远程自托管入口，并保留同源写入校验。风险边界明确为本机用户。 |
| 已解决 | 明文网络传输 API Key | **2026-08-13**：服务不再允许跨机器访问；Key 只在本机回环 HTTP 与上游 HTTPS 之间流转；同时删除唯一使用明文 HTTP 的爱化身提供商。 |
| 已解决 | SSRF/网关信任风险 | **2026-08-13**：`LLMClient` 移除自定义 `base_url`，只接受 `Config.LLM_PROVIDERS` 中的内置地址。 |
| 风险降低 | 上游费用失控 | **2026-08-13**：同一 Sidecar 同时只允许一个生成/局部编辑/风格分析/片段标注/向量化任务，阻止重复点击和多窗口并发计费；精确费用额度依赖各提供商。 |
| 风险降低 | 长任务失败与结果不一致 | **2026-08-13**：用户中止 SSE 时自动保存已生成正文为“未完成”记录；任务锁在流关闭时释放。无法保证第三方已停止计费，仍需上游取消协议支持。 |
| 风险降低 | SQLite 锁竞争或损坏 | **2026-08-13**：取消远程 Web 多实例场景，模型写任务单并发；继续使用 WAL、外键、busy timeout。用户手动启动多个进程仍可能竞争。 |
| 已解决 | 语料规模导致内存峰值 | **2026-08-13**：单语料库和单次检索候选均限制 5000 片段，矩阵保持 float32，不再转换为 float64。 |
| 已解决 | FTS 索引一致性 | **2026-08-13**：保留事务内同步维护；启动时比较主表与 FTS 的行数及 rowid 校验值，仅在不一致时从 `StyleChunk` 重建索引。 |
| 中 | Prompt Injection 与数据外发 | 导入的范例、语料或前情会进入模型提示词；恶意文本可能影响指令层级，敏感内容也会发送给第三方提供商。 |
| 中 | HTML/Markdown 渲染风险 | 生成文本属于不可信内容；若格式化函数或后续 Markdown 渲染未完整转义，可能产生 DOM XSS。应持续验证所有渲染入口。 |
| 中 | 文档解析兼容与安全 | DOC 依赖 Windows 自动化能力，DOCX 属于压缩 XML；损坏文件、超大解压比或 Office 环境差异可能造成资源消耗或解析失败。 |
| 中 | 第三方 API 漂移 | 非官方中转站、模型 ID、SSE 字段和思考参数可能随时变化，造成部分提供商突然不可用。 |
| 已解决 | 默认密钥与调试配置 | **2026-08-11 已修复**：默认配置改为 ProductionConfig；未配置 `SECRET_KEY` 时由应用启动时生成随机密钥。 |
| 中 | 隐私与备份缺失 | 数据库包含文章、前情、提示词及风格语料，但未见内置加密、自动备份、保留策略或安全擦除机制。 |
| 低至中 | 二进制与源码版本漂移 | 根目录 EXE、Tauri Sidecar 和当前源码可能不是同一次构建，排障时容易误判实际运行版本。 |

## 9. 建议的治理优先级

本节保留治理路线；已完成的最小化措施会明确标记，未标记者仍是后续建议。

### P0：明确部署安全边界

- **部分完成（2026-08-11）**：默认启用生产配置和随机进程密钥；浏览器写请求增加同源校验；增加基础安全响应头。
- **已完成（2026-08-13）**：删除 web/self-hosted 产品形态，所有启动模式固定绑定 `127.0.0.1`，并移除 Docker 发布入口。
- **已完成（2026-08-13）**：模型地址改为内置白名单，删除明文 HTTP 提供商；高费用模型操作增加单任务互斥。
- 若未来重新引入远程或多用户模式，必须先独立设计认证、CSRF、限流、HTTPS 与操作审计，不复用当前本机测试入口。

### P1：提高生成链路可靠性

- 为生成、风格分析和向量化建立持久任务状态与幂等键。
- 明确取消语义、超时语义、断线恢复和重复请求处理。
- 使用适合生产的服务容器承载 Web 模式；桌面模式也应明确并发和关闭策略。

### P1：固化 API 与数据契约

- 为 REST 请求、响应和 SSE 事件建立可校验 schema。
- 补充关键链路的集成测试：预览与实际组装一致性、回退路径、流式终止、记录落库、迁移幂等性。
- 引入明确的数据库 schema 版本和可追踪迁移历史。

### P2：拆分高复杂度领域服务

- 将生成编排拆为准备、风格检索、模型执行、后处理和持久化阶段。
- 将不同模型提供商实现为显式 Adapter，统一能力声明与错误分类。
- 将 Style RAG 的索引构建、检索和存储职责分离，为未来替换存储后端保留边界。

### P2：建立数据与隐私治理

- 提供数据库备份、恢复、导出和容量可视化。
- 明确第三方数据发送提示、敏感内容警告和本地数据保留策略。
- 对大语料设置容量、切片数、并发与费用预估上限。

## 10. 总体评价

该项目的产品链路完整度高，桌面 Sidecar、本地数据、流式生成、模板版本和智能风格系统已经形成可用闭环。现有分层对于本地单用户桌面产品基本合理，轻量依赖和 SQLite 选择也符合“易分发”的目标。

主要架构矛盾不是功能不足，而是**单用户本地工具仍同时承担长任务、向量检索和多提供商网关职责**。本轮已经移除 Web 自托管和示例模板链路，并以限额、白名单和单任务互斥降低主要风险。后续应继续保持桌面单用户边界；如果未来扩展到局域网、多用户或云端部署，认证授权、任务队列、生产服务容器、契约化 API 和可扩展存储必须先于新功能建设。

---

## 11. UI 到后端的逐功能链路遍历

### 11.1 遍历方法与判定标准

本轮补充按以下固定路径逐项追踪：

```text
可见 UI / 浏览器事件
  → 前端事件处理函数
  → 前端状态与请求数据组装
  → HTTP 方法与 URL
  → Flask 路由函数
  → Service / Prompt 处理函数
  → 第三方 API 或数据库操作
  → HTTP JSON / 文件 / SSE 返回
  → 前端渲染、下载或持久化结果
```

判定含义：

- **闭环**：UI、前端处理、后端路由、服务实现和结果反馈均可定位。
- **前端本地闭环**：该动作设计上不需要后端，只修改 DOM、内存状态、剪贴板、下载或 localStorage。
- **部分闭环**：主功能可用，但存在取消、错误反馈、状态一致性或可观测性缺口。
- **后端孤立能力**：后端存在接口，但当前 UI 没有调用入口。

“遍历”在本报告中指源码级静态执行路径检查。为避免修改用户数据、产生第三方 API 费用或执行不可逆删除，本轮未实际点击破坏性按钮，也未真实调用 LLM/Embedding。

### 11.2 应用启动与公共 UI

| # | 用户动作 | 前端/桌面逻辑 | 后端链路 | 结果与存储 | 判定 |
|---:|---|---|---|---|---|
| 1 | 启动桌面程序 | Tauri Rust 启动 Sidecar、选择随机端口并轮询 | `GET /api/health` → `app.health` | 就绪后窗口导航至 Flask 首页；退出时清理 Sidecar | 闭环 |
| 2 | 打开首页 | 浏览器请求根路径 | `GET /` → `app.index` → `render_template` | 返回 `server/templates/index.html` | 闭环 |
| 3 | 切换工作台/模板/历史标签 | `main.initTabs` 更新 `state.currentTab`；按需调用列表加载 | 模板页调用模板列表；历史页调用记录列表；工作台调用分组模板 | DOM 切页并刷新对应数据 | 闭环 |
| 4 | 切换亮/暗主题 | `main.initTheme` | 无后端调用 | 写入主题 localStorage 并修改 `data-theme` | 前端本地闭环 |
| 5 | 放大、缩小、恢复缩放 | `zoom.stepZoom/applyZoom`，含 Ctrl/滚轮快捷键 | 无后端调用 | 修改 CSS 缩放变量并写 localStorage | 前端本地闭环 |
| 6 | 显示/隐藏 API Key | `main.initApiKey` 切换 input 类型 | 无后端调用 | 仅改变可见性；Key 不写 localStorage | 前端本地闭环 |
| 7 | 切换提供商/模型 | `main.initModelSelector` | 初始 `GET /api/generation/models` → `get_models` → `Config.LLM_PROVIDERS` | 更新模型选项与思考模式可用状态 | 闭环 |
| 8 | 编辑工作台表单 | `saveWorkspaceDraft/restoreWorkspaceDraft` | 无后端调用 | 标题、前情、模式等写 localStorage；API Key 不在草稿字段内 | 前端本地闭环 |

### 11.3 工作台模板与前置文章

| # | 用户动作 | 前端函数 | 路由 → 服务/处理 | 数据落点与返回 | 判定 |
|---:|---|---|---|---|---|
| 9 | 加载/刷新工作台模板 | `loadWorkspaceTemplates` | `GET /api/templates/grouped?active_only=false` → `list_grouped_templates` → `get_templates_by_category` | 读取 `PromptTemplate`，按分类返回，写入 `state.groupedTemplates` | 闭环 |
| 10 | 展开/折叠模板分类 | `templatePanel` 分类 header click | 无后端调用 | 只改变 DOM 展开状态 | 前端本地闭环 |
| 11 | 启用/禁用单个模板 | `toggleWorkspaceTemplate` | `POST /api/templates/{id}/toggle` → `toggle_template` → `toggle_template_active` | 更新 `PromptTemplate.is_active`，返回模板后同步工作台和模板页 | 闭环 |
| 12 | 填写普通模板变量 | 工作台根据全部已启用普通模板的 `variables` 动态生成输入框，值仅保存到本机 localStorage | `getWorkspaceVariableValues()` 同时供 Prompt 预览与正式生成使用 → `variable_values` → `fill_variables` | 预览与生成使用同一组变量值，并随 `GenerationRecord.variable_values` 保存 | **已解决（2026-08-11）** |
| 13 | 点击选择前置文章文件 | `btn-browse-article` → 文件 input | 不直接访问后端，随后进入导入链 | 打开系统文件选择器 | 前端本地闭环 |
| 14 | 拖拽/选择 TXT、DOC、DOCX | `importArticleFile` | `POST /api/generation/extract-text` → `extract_article_text` → `extract_uploaded_text` → TXT 解码/DOCX XML/DOC 提取 | 返回纯文本，填入 `previous-article` 并纳入草稿 | 闭环 |
| 15 | 直接粘贴/修改前情 | textarea input → 草稿保存 | 预览或生成时作为 `previous_article` 传入 | 超阈值时后端 `summarizer` 调用 LLM 压缩，失败时截断 | 闭环，压缩属于生成链子步骤 |

### 11.4 Prompt 预览与 Token 预算

| # | 用户动作 | 前端函数 | 路由 → Prompt/业务逻辑 | 返回结果 | 判定 |
|---:|---|---|---|---|---|
| 16 | 展开/收起预览抽屉 | `setPromptPreviewDrawer` | 无后端调用 | 修改抽屉 DOM/ARIA 状态 | 前端本地闭环 |
| 17 | 生成提示词预览 | `fetchPromptPreview` | `POST /api/generation/preview-prompt` → `GenerationRequest.from_http` → `get_assembled_preview` → legacy/structured/smart assembler → `calculate_token_budget` | 返回 prompt/messages、style metadata、选中片段、fallback 原因和 Token 预算并渲染 | 闭环 |
| 18 | 清空预览 | `btn-close-preview` | 无后端调用 | 清空预览 DOM，不改变模板或数据库 | 前端本地闭环 |
| 19 | 生成前自动预检 | `btn-generate` 首先调用 `fetchPromptPreview` | 与 #17 相同 | `over` 阻止生成，`warning` 提示，smart 回退显示原因 | 闭环；预览与实际生成分别组装，存在并发数据变化造成差异的理论窗口 |

Prompt 模式分支如下：

```text
style_mode = legacy
  → assemble_prompt / 普通拼接

structured_prompt_enabled = true
  → assemble_structured_messages / 结构化消息

style_mode = smart
  → assemble_style_pipeline_messages
      ├─ 读取 StyleProfile / StyleExcerpt
      ├─ 可选 hybrid_search_style 检索 StyleCorpus
      ├─ 选择风格片段与生成约束
      └─ 条件不足时 smart_fallback_legacy
```

### 11.5 文章流式生成、去 AI 化与输出

| # | 用户动作 | 前端函数 | 路由 → 服务 → 外部 API | 保存/返回 | 判定 |
|---:|---|---|---|---|---|
| 20 | 点击“生成文章” | `generation.js` click handler → `generateStream` | `POST /api/generation/generate-stream` → `generate_stream` → `GenerationRequest` → `generate_article(stream=True)` → `_generate_stream_flow` → `LLMClient` | SSE 返回 `reasoning/content/status/complete/error`；完成后创建 `GenerationRecord` | 闭环 |
| 21 | 启用思考模式 | 模型能力决定 checkbox 状态，值进入生成 payload | `LLMClient` 校验模型能力并组装 thinking/reasoning 参数 | SSE `reasoning` 事件渲染到思考区，完整内容进入记录 | 闭环；依赖上游协议稳定性 |
| 22 | 启用“去 AI 味” | checkbox 首次加载默认提示词 | `GET /api/generation/default-deai-prompt` → Config；生成第一版后再次调用 `LLMClient` | SSE `deai_start/content/deai_done`；保存 `deai_content/deai_prompt` | 闭环；一次用户动作可能产生两次计费调用 |
| 23 | 自定义去 AI 提示词 | textarea input | 随生成 payload 进入 `GenerationRequest` 和生成服务 | 用作第二阶段 Prompt 并保存到记录 | 闭环 |
| 24 | 点击“停止生成” | `AbortController.abort()` 终止浏览器 fetch | 当前没有独立取消 API，也未证明取消信号能终止已发往第三方的请求 | 前端保留已收到内容，但通常不会收到 `complete`，未必生成记录 | **部分闭环**：UI 能停收，服务端/上游取消和落库语义不完整 |
| 25 | 查看流式正文/思考/去 AI 版 | SSE parser 增量拼接 | 后端 generator 转发上游分块 | DOM 增量渲染；complete 后设置 `currentRecordId` | 闭环 |
| 26 | 复制结果 | `navigator.clipboard.writeText` | 无后端调用 | 优先复制去 AI 版，否则第一版 | 前端本地闭环 |
| 27 | 下载结果 | Blob + Object URL | 无后端调用 | 下载 `{标题}.txt`，优先去 AI 版 | 前端本地闭环 |

文章保存的精确落点：

```text
GenerationRecord
├─ title
├─ content                 # 第一版
├─ deai_content            # 去 AI 版
├─ edited_content          # 人工/局部 AI 编辑后版本
├─ edit_history            # 局部替换历史 JSON
├─ model_used / thinking_enabled / reasoning_content
├─ assembled_prompt
├─ templates_used / variable_values
├─ deai_prompt
└─ style_mode / style_profile_snapshot
```

### 11.6 全屏结果编辑与局部 AI 编辑

| # | 用户动作 | 前端函数 | 路由 → 服务 → 外部 API/数据库 | 返回与 UI | 判定 |
|---:|---|---|---|---|---|
| 28 | 打开全屏编辑器 | `openResultEditor` | 有 record ID 时 `GET /api/generation/records/{id}` → `get_single_record` → `get_record` | 加载最终基线、已有修改版及 `edit_history` | 闭环 |
| 29 | 直接编辑 Markdown | editor input | 无即时后端调用 | 更新预览并标记 dirty | 前端本地闭环，需手动保存 |
| 30 | Markdown 工具栏/预览开关 | 本地 selection/DOM 处理 | 无后端调用 | 修改文本或切换预览 | 前端本地闭环 |
| 31 | 选择“重写/续写/扩写/润色” | operation button 更新 `resultEditState.operation` | 无即时后端调用 | 为下一次 transform 选择操作 | 前端本地闭环 |
| 32 | 生成局部 AI 候选 | `btn-result-transform` | `POST /api/generation/transform-text` → `transform_text` → `transform_article_text` → `OPERATION_PROMPTS` → `LLMClient.chat_completion` | 返回候选文本，展示原文/候选 diff | 闭环；不自动落库 |
| 33 | 取消局部 AI 请求 | `AbortController.abort()` | 无后端取消端点 | 前端停止等待；上游调用可能继续 | 部分闭环，与 #24 同类 |
| 34 | 编辑 AI 候选 | contenteditable input | 无后端调用 | 更新候选纯文本缓存 | 前端本地闭环 |
| 35 | 保留原文/关闭对比 | 隐藏 overlay | 无后端调用 | 不改编辑器内容 | 前端本地闭环 |
| 36 | 应用 AI 候选 | `setRangeText`，追加 editHistory | 无即时后端调用 | 替换选区并标记 dirty | 前端本地闭环，需手动保存 |
| 37 | 保存修改版 | `btn-save-result-edit` | `PUT /api/generation/records/{id}` → `edit_record` → `update_record` | 更新 `GenerationRecord.edited_content/edit_history` | 闭环 |
| 38 | 退出编辑器 | 检查 dirty 并关闭面板 | 无后端调用 | 未保存内容可能经确认后丢弃 | 前端本地闭环 |

### 11.7 模板管理

| # | 用户动作 | 前端函数 | 路由 → 服务 | 数据结果 | 判定 |
|---:|---|---|---|---|---|
| 39 | 查看/筛选/搜索模板 | `loadTemplatesList/renderTemplateList` | `GET /api/templates?category=...` → `list_templates` → `get_all_templates` | 从 `PromptTemplate` 返回；搜索仅在当前已加载列表中进行 | 闭环 |
| 40 | 新建模板 | `openTemplateEditor(null)` + 保存 | `POST /api/templates` → `add_template` → `create_template` | 插入 `PromptTemplate` | 闭环 |
| 41 | 打开普通模板 | `openTemplateEditor(id)` | `GET /api/templates/{id}` → `get_single_template` → `get_template` | 返回模板并填充编辑器 | 闭环 |
| 42 | 编辑并保存模板 | `btn-save-template` | `PUT /api/templates/{id}` → `edit_template` → `update_template` | 元数据原地更新；内容变更按服务规则创建版本记录/新版本 | 闭环 |
| 46 | Markdown 编辑/本地预览 | 工具栏、`renderMarkdownPreview` | 无后端调用 | 修改 textarea 并以转义后的简易 Markdown 显示 | 前端本地闭环 |
| 47 | 删除单个模板 | delete button | `DELETE /api/templates/{id}` → `delete_template` | 删除模板；关系配置决定关联 Style 数据级联 | 闭环，UI 有确认框 |
| 48 | 删除全部模板 | `deleteAllTemplates` | `DELETE /api/templates/all` → `delete_all_templates` | 批量删除模板 | 闭环，属于高影响操作 |
| 49 | 查看版本历史 | `btn-version-history` | `GET /api/templates/{id}/versions` → `get_version_history` | 返回同版本链数据并渲染 | 闭环 |
| 50 | 恢复历史版本 | version button | `POST /api/templates/{id}/restore/{version_id}` → `restore_version` | 以历史内容恢复/形成当前版本，刷新编辑器 | 闭环 |
| 51 | 导出模板 | `btn-export-templates` | `POST /api/templates/export` → `export_templates` | 返回 JSON Blob；前端下载文件 | 闭环；当前 UI 固定导出全部 JSON，Markdown/指定 ID 仅 API 支持 |
| 52 | 导入模板 | file input change | `POST /api/templates/import` multipart → `import_templates` | 批量插入，返回 imported/skipped | 闭环 |

### 11.8 Style Card 与单篇风格片段

| # | 用户动作 | 前端函数 | 路由 → 服务 → 外部 API/数据库 | 返回与状态 | 判定 |
|---:|---|---|---|---|---|
| 53 | 打开风格卡 | `loadStyleProfile` | `GET /api/style-profiles/{template_id}` → `get_profile` → `get_style_profile` | 读取 `StyleProfile`，并基于模板 hash 标识 stale | 闭环，仅 example 分类显示入口 |
| 54 | 首次分析风格卡 | `analyzeCurrentStyleCard` | `POST .../{id}/analyze` → `analyze_style_profile` → `LLMClient.chat_completion` → JSON 提取/校验 | upsert `StyleProfile` 并返回结构化 Card | 闭环 |
| 55 | 重新分析风格卡 | 同一 `analyzeCurrentStyleCard` | 当前 UI **仍调用 `/analyze`**，后端 `/refresh` 未被使用 | 效果可达，但 `/refresh` 是冗余后端入口 | 闭环但接口语义重复 |
| 56 | 编辑表单或应用 JSON | `collectStyleCard/renderStyleCard` | 无即时后端调用 | 只修改页面表单 | 前端本地闭环 |
| 57 | 保存风格卡/设为主风格 | `btn-save-style-card` | `PUT /api/style-profiles/{id}` → `update_style_profile` → `validate_style_card` | 更新 `StyleProfile.card_json/is_primary` | 闭环 |
| 58 | 恢复自动分析版本 | `btn-restore-style-card` | `POST .../{id}/restore` → `restore_analysis_card` | 恢复自动分析 Card 并返回 | 闭环 |
| 59 | 加载风格片段 | `loadStyleExcerpts` | `GET .../{id}/excerpts` → `get_style_excerpts` | 读取并渲染 `StyleExcerpt` | 闭环 |
| 60 | 生成/重建风格片段 | `rebuildCurrentStyleExcerpts` | `POST .../{id}/excerpts/rebuild` → `split_reference_text` → LLM 批量标注 → `rebuild_style_excerpts` | 删除/重建该 Profile 的片段并提交 | 闭环，高费用/长任务 |
| 61 | 修改片段场景 | `updateExcerpt` | `PUT .../excerpts/{excerpt_id}` → `update_style_excerpt` | 更新 `scene_type` | 闭环 |
| 62 | 置顶/取消置顶片段 | `updateExcerpt` | 同 #61 | 更新 `is_pinned` | 闭环 |
| 63 | 启用/排除片段 | `updateExcerpt` | 同 #61 | 更新 `is_enabled` | 闭环 |

### 11.9 Style RAG 语料库

| # | 用户动作 | 前端函数 | 路由 → 服务 → 外部 API/数据库 | 返回与状态 | 判定 |
|---:|---|---|---|---|---|
| 64 | 打开语料管理/加载语料库 | `openCorpusPanel/loadCorporaList` | `GET /api/style-corpora` → `list_corpus` → `list_corpora` | 返回 `StyleCorpus` 列表并同步工作台复选项 | 闭环 |
| 65 | 新建语料库 | `createCorpus` | `POST /api/style-corpora` → `create_corpus` | 插入空 `StyleCorpus` | 闭环 |
| 66 | 导入语料文件 | `importCorpusFile` | `POST .../{id}/import` → `extract_uploaded_text` → `split_corpus_text` → `rule_tag_chunk` → `import_corpus_text` | 重建 `StyleChunk`、FTS 内容与 corpus 统计 | 闭环；上传 input 接受 `.md`，后端文档扩展名集合不含 `.md`，存在 UI/后端契约不一致 |
| 67 | 向量化语料 | `indexCorpus` | `POST .../{id}/index` → `index_corpus` → `LLMClient.create_embeddings` | 分批写入 `embedding_blob/model/dim`，更新 corpus 状态 | 闭环，高费用/长任务且无进度事件 |
| 68 | 清空语料内容 | `clearCorpus` | `POST .../{id}/clear` → `clear_corpus_chunks` | 删除 chunks/FTS 数据并重置 corpus 统计 | 闭环，高影响操作 |
| 69 | 删除语料库 | `deleteCorpus` | `DELETE /api/style-corpora/{id}` → `delete_corpus` | 删除 corpus 及关联 chunks/FTS 数据 | 闭环，高影响操作 |
| 70 | 工作台选择语料库 | corpus checkbox change | 无即时后端调用；ID 随预览/生成 payload 发送 | `style_corpus_ids` 参与智能风格链检索 | 闭环，前半段本地、生成时后端生效 |
| 71 | 输入独立 Embedding Key | password input | 随向量化、检索或生成请求传入；为空时生成流程回退顶部 Key | 不持久化 | 闭环 |
| 72 | 检索测试 | `runSearchTest` | `POST /api/style-corpora/search` → `hybrid_search_style` → 可选 query embedding + BM25 + RRF + MMR | 返回片段、得分和 meta 并渲染 | 闭环 |
| 73 | 智能风格生成时检索 | `generateStream/fetchPromptPreview` | `assemble_style_pipeline_messages` → `hybrid_search_style` | 命中片段注入 Prompt，并进入生成记录风格快照 | 闭环；检索失败时可回退普通模式 |

### 11.10 生成记录

| # | 用户动作 | 前端函数 | 路由 → 服务/数据库 | 返回与 UI | 判定 |
|---:|---|---|---|---|---|
| 74 | 查看记录列表 | `loadHistoryList` | `GET /api/generation/records` → `list_records` → `get_records` | 按置顶/时间分页读取 brief 数据 | 闭环；当前 UI 未暴露翻页控制，只使用默认第一页 |
| 75 | 搜索历史 | `renderHistoryList` | 无新后端请求 | 只过滤当前已加载的默认页记录 | 前端本地闭环；不是全库搜索 |
| 76 | 查看记录详情 | `loadHistoryDetail` | `GET /api/generation/records/{id}` → `get_record` | 展示最终版、修改版、第一版和 assembled prompt | 闭环 |
| 77 | 切换详情内容标签 | detail tab click | 无后端调用 | 在已取得 record 对象中切换内容 | 前端本地闭环 |
| 78 | 置顶/取消置顶记录 | `toggleRecordPinned` | `PUT /api/generation/records/{id}` → `update_record(pinned=...)` | 更新 `GenerationRecord.pinned` 并刷新列表 | 闭环 |
| 79 | 删除单条记录 | `deleteRecord` | `DELETE /api/generation/records/{id}` → `delete_record` | 删除记录并刷新 | 闭环，高影响操作 |
| 80 | 删除全部记录 | `deleteAllRecords` | `DELETE /api/generation/records` → `delete_all_records` | 清空记录并刷新 | 闭环，高影响操作 |

## 12. 后端接口反向覆盖检查

前述检查从 UI 向后追踪；本节反向从所有 Flask 路由检查是否存在当前 UI 调用者。

### 12.1 当前 UI 可达接口

以下接口族均有明确前端调用：

- 模板：列表、分组、示例、详情、新建、编辑、删除、删除全部、启停、版本、恢复、导入、导出、示例另存。
- 生成：模型列表、默认去 AI Prompt、文档提取、流式生成、Prompt 预览、局部变换、记录 CRUD。
- Style Card：详情、分析、编辑、恢复、片段列表、重建、片段编辑。
- Style RAG：列表、新建、导入、向量化、清空、删除、检索。

### 12.2 后端存在但当前 UI 未调用

| 接口 | 后端能力 | 当前状态/影响 |
|---|---|---|
| `GET /api/generation/categories` | 返回模板分类 | 前端使用 `state.categoryConfig` 和 HTML 固定选项，形成双份分类定义 |
| `POST /api/generation/generate` | 同步生成 | UI 只使用 `generate-stream`；属于兼容/备用接口 |
| `POST /api/style-profiles/{id}/refresh` | 重新分析 Style Card | “重新分析”按钮仍调用 `/analyze`，该接口无 UI 调用者 |
| `DELETE /api/style-profiles/{id}/excerpts/{excerpt_id}` | 删除单个风格片段 | UI 只提供启用/排除与重建，没有单片段删除按钮 |
| `GET /api/style-corpora/embedding-config` | 返回 Embedding 配置 | UI 未请求，展示与行为依赖本地固定认知 |
| `GET /api/style-corpora/{id}` | 获取单个语料库 | UI 列表数据已满足当前展示，没有详情调用 |
| `PUT /api/style-corpora/{id}` | 修改语料库名称/说明 | UI 没有编辑入口 |
| `GET /api/style-corpora/{id}/chunks` | 分页查看切片 | UI 没有语料切片浏览器 |

这些接口不一定是缺陷，但应明确标记为“预留/兼容 API”，否则会增加维护与测试范围，并造成“后端有能力但产品不可发现”的认知偏差。

## 13. 功能链遍历发现的问题

### 13.1 明确的前后端契约偏差

1. **已解决（2026-08-11）—语料导入扩展名不一致**：前端已移除未受后端支持的 `.md`，前后端统一为 `.txt/.doc/.docx`。
2. **Style Card refresh 接口未实际使用**：“重新分析”按钮与首次分析都请求 `/analyze`，`/refresh` 成为重复实现。
3. **分类配置双源**：后端提供 `/api/generation/categories`，前端却维护固定 `categoryConfig` 且 HTML 中另有固定 `<option>`。分类变化需要同步多处。
4. **已解决（2026-08-11）—历史分页能力未映射到 UI**：历史列表已增加上一页/下一页、当前页、总页数和总记录数。搜索仍是当前页本地过滤；若未来需要全库搜索，应新增服务端查询参数。
5. **部分后端能力不可发现**：单片段删除、语料元数据编辑、切片浏览等没有 UI 入口。
6. **已解决（2026-08-11）—普通模板变量填写链缺失**：工作台现会聚合已启用模板变量、记忆用户输入，并把同一份 `variable_values` 传给预览和生成。

### 13.2 取消链路不是端到端取消

生成和局部 AI 编辑的“停止/取消”都是浏览器侧 AbortController。该动作能停止前端继续读取响应，但没有专用后端取消请求、任务标识或上游连接取消确认。因此：

- 用户看到“已停止”不代表第三方 API 已停止计费或计算。
- 流式生成被停止时通常无法进入 `complete` 分支，当前片段可能不落库。
- 服务端是否及时发现客户端断开取决于 WSGI/网络栈行为。

### 13.3 前端成功判断存在薄弱点

- **已解决（2026-08-11）**：模板导出在创建 Blob 前检查 HTTP 状态并解析错误 JSON。
- **部分解决（2026-08-11）**：通用 `api()` 已统一 HTTP/JSON/业务错误；语料导入也使用一致的状态判断。SSE 和文件下载仍因响应类型不同保留专用处理。
- SSE parser 对无法解析的事件行选择跳过；协议字段漂移可能表现为静默缺块，而不是立即失败。

### 13.4 UI 状态与数据库状态的时间差

- 模板、语料和历史操作成功后多采用重新加载列表，主路径最终一致；但并发窗口或刷新失败时，UI 可能保留旧状态。
- Prompt 预览和实际生成是两个独立请求，两次都会读取当前数据库。如果两者之间模板被另一窗口或实例修改，预览不保证与实际 Prompt 完全相同。
- 局部 AI 候选只有点击“应用”后进入前端 edit history，再点击“保存修改版”才持久化；中途关闭页面会丢失候选和未保存编辑。

### 13.5 用户动作覆盖结论

原审计共识别 80 类用户动作/自动 UI 行为；删除 3 条示例模板动作后，当前保留 **77 类**：

- 具有完整后端落点或符合设计的本地闭环：绝大多数主功能。
- 主要部分闭环：文章生成取消、局部 AI 请求取消。
- 已解决：普通模板变量输入与 payload 映射。
- 已解决：Style RAG 文件选择范围与后端一致。
- 后端存在但 UI 不可达：8 条接口能力。
- 产品可达性缺口：历史后续分页、语料切片浏览、语料元数据编辑、单风格片段删除。

因此，当前主创作链条可以精确定位为：

```text
UI 工作台
  → generation.js / promptPreview.js
  → GenerationRequest
  → generation_routes
  → generation_service
  → prompt_assembler
      → Template / StyleProfile / StyleExcerpt / StyleCorpus 数据
      → token_budget / summarizer / hybrid_search_style
  → LLMClient
  → 第三方 Chat Completion / Embedding API
  → JSON 或 SSE
  → 前端正文/思考/diff 渲染
  → GenerationRecord / edited_content / edit_history
```

主链及普通模板变量子链已形成闭环；下一阶段最应优先处理的是**端到端取消语义、服务端历史搜索、重复/孤立 API 和 SSE 契约**。

## 14. 简化治理实施结果（2026-08-11）

### 14.1 已解决

| 问题 | 最小化解决方式 | 验证 |
|---|---|---|
| 普通模板变量链断开 | 在现有原生 JS/HTML 内增加动态变量区；不引入框架；预览和生成共用同一取值函数 | JS 语法检查通过；静态确认两条 payload 均调用 `getWorkspaceVariableValues()` |
| 历史后续页不可达 | 直接复用后端已有分页字段，增加上一页/下一页控件 | JS 语法检查通过；请求包含 `page/per_page` |
| Style RAG `.md` 契约不一致 | 从文件选择器移除 `.md` | 前后端扩展名集合一致 |
| API 错误处理薄弱 | 强化现有 `api()`；为文件上传/下载补充 HTTP 与业务状态检查 | JS 语法检查通过 |
| 记录更新字段过宽 | `update_record` 改为明确 allowlist，仅允许标题、编辑内容、编辑历史、评分、置顶和备注 | Python 语法检查通过 |
| 固定默认 SECRET_KEY / 开发配置 | 默认使用 ProductionConfig；启动时生成随机 SECRET_KEY | Flask 冒烟测试通过 |
| 基础跨站写入风险 | 对带 Origin 的写请求执行同源校验；增加 nosniff、DENY frame、no-referrer 和 Permissions-Policy | Flask 测试客户端验证恶意 Origin 返回 403、同源请求通过 |
| 历史模型名渲染 | 对列表和详情中的模型名执行 HTML 转义 | JS 语法检查通过 |

### 14.2 部分解决

- **部署安全边界（已解决）**：服务固定绑定回环地址且不再提供 Docker/自托管入口；未来若恢复远程访问，需要重新建立认证和部署安全体系。
- **API 契约**：统一错误处理降低了前端分歧，但仍没有 OpenAPI、Schema 和 SSE 类型定义。
- **前端耦合**：新增功能沿用当前模块组织，没有继续引入全局变量；但 DOM ID 与单例状态的结构性耦合仍在。
- **历史搜索**：分页已可达，搜索仍限当前页，尚不是数据库级全文搜索。

### 14.3 暂缓及风险说明

以下事项需要明显扩大改动面，当前危害与本地单用户定位相比不足以支持立即重构：

1. **前端框架/集中状态重写**：会触及所有面板、事件和渲染逻辑，极易产生 UI 回归。
2. **认证与多用户权限体系**：需要登录、密码/令牌生命周期、会话、CSRF、迁移和部署文档的完整设计，不能只加一个硬编码密码。
3. **任务队列与端到端取消**：需要把生成、向量化、风格分析改造成持久任务，并处理进度、幂等、断线恢复和 Sidecar 退出。
4. **替换 Flask 开发服务器**：引入 Waitress 等生产服务器会改变依赖、PyInstaller spec、Sidecar 关闭和流式响应行为，应单独回归打包与 SSE。
5. **SQLite/向量存储替换**：会引入数据迁移、部署复杂度和发布体积，不符合当前本地轻量目标。
6. **OpenAPI/DTO 全量契约化**：价值明确，但需要覆盖全部 REST/SSE 字段并建立生成与校验流程，适合作为独立迭代。

## 15. 高/中高风险最小化整改（2026-08-13）

### 15.1 已实施

- **删除示例模板整条链路**：移除前端入口、只读/另存 UI、状态字段、专用路由和服务函数。为避免破坏用户现有 SQLite，数据库仅保留兼容列，并在启动迁移时把旧示例无损转为普通可编辑模板。
- **桌面场景唯一化**：删除 Docker 发布文件，`app.py` 固定绑定 `127.0.0.1`，浏览器运行仅保留为本机测试入口。
- **外部请求收口**：提供商地址只能从内置配置读取，调用方不能提交自定义 `base_url`；移除唯一使用明文 HTTP 的提供商。
- **费用与并发保护**：生成、局部 AI 编辑、Style Card 分析、片段重建和语料向量化共用一个轻量进程锁；已有任务运行时，新任务立即返回可理解错误，不新增队列依赖。
- **流式中断保护**：客户端中断后，如服务端已获得部分正文，将其保存为“未完成”历史记录，再释放任务锁。
- **语料资源上限**：单语料库最多 5000 个切片，单次向量候选最多 5000 条，NumPy 保持 float32，避免大语料造成突发内存翻倍。
- **FTS 自修复**：启动时比较主表和 FTS 的数量及 rowid 校验值，仅在不一致时重建，不为正常启动增加全量重建成本。

### 15.2 新增机制如何工作

本轮只新增 `operation_guard.py` 一个极小模块：它保存一个进程内互斥锁。高费用路由开始工作前尝试获取锁；若锁已占用就拒绝重复任务；路由在成功、失败或流关闭的 `finally` 阶段统一释放。它不创建后台线程、不引入 Redis/任务队列，也不改变现有 API 成功响应。

### 15.3 有意暂缓

- **持久任务队列、真正的上游取消与断线恢复**需要重写生成协议和任务状态，风险明显高于本地单用户收益。
- **前端框架、OpenAPI 和服务层大拆分**会扩大回归面，本轮不为架构形式牺牲已有功能稳定性。
- **数据库加密、自动备份和安全擦除**涉及密钥管理、恢复策略与用户选择，属于独立产品功能，不用不可靠的“简单加密”冒充已解决。
- **第三方 Prompt Injection/数据外发**无法仅靠本地过滤彻底消除；应在后续产品设计中增加发送提示、敏感内容告警和提供商隐私说明。

### 15.4 开源项目取向参考

本轮参考的是成熟项目的边界选择，而非复制其技术栈：

- [GPT4All Local API Server](https://github.com/nomic-ai/gpt4all/wiki/Local-API-Server) 将桌面模型服务默认置于 localhost，与本项目固定回环 Sidecar 的边界一致。
- [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm/blob/master/README.md?plain=1) 明确区分 Desktop 与 Docker 产品形态；本项目选择只保留 Desktop，避免维护两套安全模型。
- [Cherry Studio](https://github.com/CherryHQ/cherry-studio) 证明桌面客户端可以在本地统一管理多模型提供商；本项目保留该能力，但把提供商地址收口为内置白名单。
- [OpenPawz](https://github.com/OpenPawz/openpawz) 展示了 Tauri/offline-first 的更彻底本地化方案；改为原生 IPC 会触发大规模重构，因此本轮只固定回环 HTTP，不迁移通信架构。
