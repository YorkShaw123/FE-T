# 接手须知（HANDOVER）

本文件面向下一个接手 Flora Editor 的人（或未来的自己）。它只记录**读代码看不出来**的东西：现状锚点、运行陷阱、约束和待决事项。产品功能与设计请看 [README.md](../README.md)、[architecture.md](architecture.md)、[style-engine/](../style-engine/)。

## 一、这是什么

面向中文小说创作的 Windows 本地 AI 写作工具，产品名「雨生编辑器」，Tauri 2 壳 + Flask Sidecar + 原生 JS 界面 + 本地 SQLite。核心差异化是**本地中文文风引擎**（Style Engine）：句长节奏、标点、功能词等可解释特征 + BM25/向量混合检索 + 内容泄漏惩罚，默认完全离线，不依赖远程 Embedding，不引入 PyTorch。

正式形态只有一种：Windows 桌面程序。浏览器入口仅供本机开发，不得改造成 Web / SaaS / 自托管。

## 二、现状锚点

| 项 | 值 |
| --- | --- |
| 版本号 | `1.0.2`（`package.json` / `src-tauri/tauri.conf.json` / EXE 资源一致） |
| 版本标签 | `v1.0.2` → `0e29113`；历史标签 `v1.0.0`(8/21)、`v1.0.1`(8/21) |
| 最后代码提交 | `0e29113` 2026-08-26 17:40「帮助文案优化 + 工作模式预设接口骨架 + 清理构建缓存」 |
| 已发布构建 | 2026-08-24 09:39–09:49（`dist/Yusheng.Editor_1.0.2_x64-setup.exe`，安装到 `D:\Flora`） |
| 质量状态 | pytest 169 passed；ruff 全绿（E4/E7/E9/F，py310，line-length 120） |

**关键事实：最后两笔提交（`6436a61` 本机 Key 读取、`0e29113` 工作模式骨架）从未进入任何构建。** 已安装的 1.0.2 不含它们（PyInstaller 归档中无 `local_api_key` / `work_modes` / `mode_routes` 模块）。

## 三、本机运行

```powershell
# 起开发服务（务必隔离数据目录，见第四节）
$env:FLORA_DATA_DIR = "$PWD\.tmp-data"
$env:FLORA_PORT = '5099'
.\.venv\Scripts\python.exe server\app.py       # 访问 http://127.0.0.1:5099

# 检查
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check server scripts tests
Get-ChildItem server\static\js\*.js | ForEach-Object { node --check $_.FullName }
cargo check --manifest-path src-tauri\Cargo.toml --locked
```

沙箱环境下 `ruff` 会因 `.ruff_cache` 写失败而报错，加 `--no-cache`。

`GET /api/health` 可用于确认服务存活；`app.url_map` 当前有 59 个端点（templates 13、style-corpora 15、generation 13、style-profiles 9、system 4、modes 3、health 1、`/` 1）。

## 四、数据目录（最容易踩的坑）

1. **开发与桌面版共用同一份数据**：默认 `%USERPROFILE%\.flora-editor\data\flora.db`（`server/app.py` `_resolve_data_dir`）。不设 `FLORA_DATA_DIR` 就直接读写真实用户库。
2. **`_migrate_legacy_data()` 的候选顺序有陷阱**：目标目录没有 `flora.db` 时，它会**先**找旧品牌目录 `%USERPROFILE%\.forestar-editor\data\forestar.db`（约 51MB 的老库），其次才是项目根 `data/`。所以"设个新的 `FLORA_DATA_DIR` 得到干净库"是错的——你会拿到旧品牌数据。要干净库就先手动清空目标目录。
3. **端口被占用会直接抛异常**（`_ensure_web_port_available`），不会自动换端口；起服务前先确认没有残留进程。
4. 数据迁移只能通过 `server/database/migrations.py` 的幂等机制追加，必须兼容已有数据。

## 五、代码地形

| 文件 | 职责 | 动它的风险 |
| --- | --- | --- |
| `server/services/style_rag_service.py` | 切片、FTS、向量、BM25+RRF+MMR、搜索缓存 | 高（签名/缓存键耦合） |
| `server/services/generation_service.py` | 生成总编排，同步与流式两条路径 | 高（流式与落库顺序敏感） |
| `server/services/author_style_profile_service.py` | 语料统计画像聚合 | 高（feature_version 失效规则） |
| `server/services/style_feature_service.py` | 中文特征提取（纯规则） | 中（口径已冻结在 `STYLE_FEATURE_V1.md`） |
| `server/services/prompt_assembler.py` | legacy / structured / smart 三条提示词路线 | 中（三条都要兼容） |
| `server/database/models.py` | 8 张表 ORM | 中（改结构必须配迁移） |
| `server/app.py` | 应用工厂、蓝图、数据目录、安全头 | 中（含数据迁移逻辑） |
| `server/static/js/generation.js` | 流式生成主驱动 | 中（SSE 解析与节点状态机） |
| `server/templates/index.html` | 唯一页面，7 个流程节点 | 低（但常与 JS 同步改） |

前端无构建链：19 个原生 JS 模块，全局状态在 `server/static/js/state.js`；改工作台节点时同步看 `workflowCanvas.js` 和 `promptPreview.js`。

一次生成的链路：

```
/api/generation/generate(-stream)
  → generation_service.generate_article
    → prompt_assembler（三路线） → token_budget（预估与拦截）
    → api_client（8 家 Provider 协议差异只在这里）
    → 05 语言自然化（可选）→ 06 风格参考（style_rag + style_retrieval + style_diff）
  → generation_records（初稿 / 去AI味 / 风格改写 / 手改 四份正文）
```

## 六、三条不许混的 Style 数据线

- `style_profiles`：**Style Card**，针对单个范例模板的结构化分析结果。
- `author_style_profiles`：**统计画像**，由语料 Style Window 聚合出的本地统计。
- `style_corpora` + `style_chunks`：RAG 语料与切片，含可选向量与签名。

签名（backend/model/version/dim）不一致时不能静默混用，会降级为纯 Style 排序；换 embedding 后端必须重新向量化。

## 七、硬约束

1. 不得改造成 Web / SaaS / 远程服务；浏览器入口仅本机开发。
2. 数据库变更必须走 `server/database/migrations.py` 的幂等迁移。
3. Style Engine 必须离线、中文优先，不引入 PyTorch / TensorFlow / 独立向量数据库；算法改动必须先更新 `docs/style-engine/EXEC_PLAN.md` 再改代码，并补测试。
4. API Key 只随请求传递，不写数据库、日志或 localStorage。
5. 私人语料、真实生成正文、`*.db`、模型权重、构建产物不得入 Git。
6. 每个阶段必须真跑 pytest + ruff；未验证项必须说明原因，不得声称跑过。

## 八、构建产物与版本纪律

- 产物：`dist/flora-server.exe`、`src-tauri/binaries/flora-server-x86_64-pc-windows-msvc.exe`、根目录两个直接运行版 EXE、NSIS 安装包在 `src-tauri/target/release/bundle/nsis/`。
- 全部不入 Git（已核对 `git ls-files`）。因此**根目录 EXE 不代表当前代码**，判断依据永远是 commit + 构建时间。
- 已知细节：仓库根目录的 `雨生编辑器.exe` 与安装目录 `D:\Flora\雨生编辑器.exe` 只差 3 字节（一处编译期标记字符串），后端 EXE 完全同哈希——是同一构建的两个拷贝。
- 发布纪律：改版本号 → 构建 → 实测 → 打 annotated tag → 推送，四步缺一不可（1.0.2 当初漏了 tag 和推送）。

## 九、待决事项

1. `6436a61`（本机读取 DeepSeek Key）与 `0e29113`（工作模式骨架，`marketing` 模式 `enabled: False`）尚未进入任何构建，也未在安装版验证过：继续做完还是回退，需要决定。
2. `server/cloud_run.py` 是为云端演示临时开的 `0.0.0.0:8000` 入口，与"只监听回环"的正式约束并存；是否保留需要明确。
3. 桌面壳的运行痕迹调查：`%LOCALAPPDATA%\com.flora.editor\EBWebView` 自 2026-08-21 后无写入，安装版是否真被启动并验证过存疑，重新出包后必须实测桌面端。
4. 历史遗留：`docs/defense/` 与 `docs/实训材料/` 曾从主干被 reset 掉，现已从 `59bf5d3` 恢复入库；stash 中仍有一条 2026-08-22 的工作日志未处理。

## 十、常用命令速查

```powershell
git log --oneline -10                 # 提交
git status --short                    # 工作区
git tag -n                            # 版本锚点
git stash list                        # 遗留 WIP

npm run build:all                     # 后端 + 桌面 + 安装包（需 Rust/Node）
npm run build:backend                 # 只打后端，含本地 Embedding 运行时
npm run tauri:dev                     # 桌面调试
```
