# 开发指南

## 环境

- Windows
- Python 3.10+
- Node.js 18+（Tauri CLI）
- Rust 工具链（桌面构建或静态检查）

## 本机运行

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python server\app.py
```

访问 <http://127.0.0.1:5000>。可用 `FLORA_PORT` 覆盖端口，用 `FLORA_DATA_DIR` 隔离测试数据库。

## 主要目录

```text
server/       Flask 后端与原生 Web 界面
src/          Tauri 后端等待页
src-tauri/    Tauri 2 桌面程序
scripts/      构建、Embedding 与诊断脚本
tests/        pytest 自动化测试
docs/         开发与架构文档
```

## 开发依赖与检查

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt

# Python Lint
.\.venv\Scripts\python -m ruff check server scripts tests

# Python 测试
.\.venv\Scripts\python -m pytest

# 原生 JavaScript 语法
Get-ChildItem server\static\js\*.js | ForEach-Object { node --check $_.FullName }

# Rust/Tauri 静态检查
cargo check --manifest-path src-tauri\Cargo.toml --locked
```

Python 目前只启用 Ruff 的基础可靠规则，尚未开启严格静态类型检查。测试包括本地服务安全边界、Style Engine 算法、Embedding 后端、生成链和构建辅助工具；需要真实 LLM API 的端到端生成不应进入默认自动化测试。

## 开发原则

- 桌面端与浏览器调试复用 Flask 提供的同一套页面，不要建立第二套前端。
- API Key 只在当前请求中传递，不得写入日志、数据库或本地存储。
- 数据库修改通过 `server/database/migrations.py` 添加幂等迁移。
- Style Engine 变更遵循 `docs/style-engine/EXEC_PLAN.md`，并补充对应算法测试。
- 私人语料、真实生成正文、数据库、模型和构建产物不得加入 Git。

桌面调试可运行 `npm run tauri:dev`；完整发行构建见 [build.md](build.md)。
