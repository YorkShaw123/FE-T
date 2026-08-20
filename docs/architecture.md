# Flora Editor 架构说明

## 产品边界

Flora Editor 是 Windows 本地桌面应用。Tauri 2 + Flask Sidecar 是正式产品架构，浏览器入口仅用于 `127.0.0.1` 上的开发测试。

## 运行结构

```text
Tauri 窗口
  └─ 启动 flora-server Sidecar
       └─ Flask 应用
            ├─ server/templates + server/static（界面）
            ├─ server/routes（HTTP 输入输出）
            ├─ server/services（生成、模板与文风业务）
            └─ server/database（SQLite、模型与迁移）
```

`src-tauri/src/lib.rs` 在启动时选择空闲回环端口，通过 `FLORA_PORT` 交给 Sidecar，等待 Flask 就绪后再导航窗口。应用退出时会清理 Sidecar 进程树。

前端没有独立框架构建链。Flask 直接提供 `server/templates/index.html` 和 `server/static/` 下的原生 JavaScript/CSS，桌面端与本机浏览器调试复用同一套界面。

## 后端职责

- `server/app.py`：应用工厂、蓝图注册、安全响应头、数据目录和本机启动入口。
- `server/routes/`：解析请求、校验 HTTP 边界并返回 JSON 或流式响应。
- `server/services/generation_service.py`：文章生成公共编排，复用提示词组装、检索、去 AI 味和严格文风重写。
- `server/services/api_client.py`：不同 LLM Provider 的 OpenAI 兼容请求及协议差异。
- `server/services/prompt_assembler.py`：兼容、结构化和智能风格链提示词组装。
- `server/services/style_*`：Style Card、Style Feature、统计画像、检索、Diff、Signature 和语料索引。
- `server/database/models.py`：模板、Style Card、语料、生成记录等 ORM 模型。
- `server/database/migrations.py`：现有 SQLite 的幂等轻量迁移。

路由层不应承载领域算法；Provider 协议差异不应散落到路由或前端。数据库变更必须继续使用现有迁移机制。

## 数据与兼容性

用户数据库默认位于 `%USERPROFILE%\.flora-editor\data\flora.db`。`server/app.py` 会在新数据库不存在时复制旧项目或旧品牌数据，源文件不会被删除。`FLORA_DATA_DIR` 只用于显式覆盖数据目录。

Style Card 与 Author Style Profile 是不同概念：前者是针对范例模板的结构化分析结果，后者是从语料 Style Window 聚合出的本地统计画像。两者不得互相覆盖。

Style Corpus 的片段、文风特征、签名和可选向量均保存在 SQLite。向量记录后端、模型、版本和维度；签名不一致时不能静默混用。

## 构建结构

PyInstaller 将 Flask 后端打包为 `flora-server.exe`，Tauri 通过 `externalBin` 将其作为 Sidecar 分发。直接运行版因此包含两个同目录 EXE：一个是桌面壳与生命周期管理程序，一个是可复用的本地后端。

详细构建步骤见 [build.md](build.md)，文风架构见 [style-rag.md](style-rag.md) 和 [style-engine/ARCHITECTURE.md](style-engine/ARCHITECTURE.md)。
