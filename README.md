# 🌲 Forestar Editor - AI文字创作助手

> 一款本地运行的 AI 文字创作工具：通过提示词模板快速组装指令，调用大语言模型 API 生成文章。
> **产品定位**：桌面端（Tauri + Flask Sidecar）为唯一主分发形态；内置 Web 版后端仅作为**开发调试 / 高级用户自托管入口**。

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Flask](https://img.shields.io/badge/Flask-3.1-lightgrey)
![Tauri](https://img.shields.io/badge/Tauri-2-green)
![Platform](https://img.shields.io/badge/Platform-Windows-orange)
![License](https://img.shields.io/badge/License-MIT-green)

## 功能特点

### 核心功能
- **提示词模板管理**：按分类（人物设定、背景设定、剧情设定、范例文章、更多约束）管理自定义提示词模板
- **示例模板**：可将模板标记为示例模板（提示内容只读），填写变量后一键另存为新模板
- **挖空修改**：模板中使用 `{{变量名}}` 标记可修改的部分，自动生成输入框
- **一键生成**：将所有活跃模板自动拼接为完整提示词，调用 AI 生成文章
- **三种提示词组装模式**：兼容字符串、结构化消息、智能风格链
- **智能风格链**：自动分析范例文章生成 Style Card，按场景检索风格片段，让文风稳定贴近参考
- **去AI味处理**：第一次生成后自动发送去AI味提示词，获得更自然的文章
- **前情提要压缩**：过长的前情提要自动压缩为概述
- **前置文章导入**：支持 TXT、DOC、DOCX 文本一键导入
- **Token 预算预检**：生成前估算 Token 用量，超限提前拦截并提示
- **全屏编辑器**：对生成结果全屏 Markdown 编辑，支持局部续写/重写/扩写/润色与 diff 对比
- **多模型支持**：DeepSeek、OpenAI、硅基流动 Kimi，以及爱化身兼容接口
- **思考模式**：支持 DeepSeek 与 Kimi 对应模型的思考模式（思维链展示）
- **暗色/亮色模式**：一键切换

### 高级功能
- **提示词版本控制**：修改内容自动创建新版本，支持版本回溯和恢复
- **生成记录管理**：保存生成的文章及使用的模板、时间等信息，支持置顶、删除单条与一键清空
- **修改版追踪**：全屏编辑器中的修改与 AI 处理历史保存到记录，可按行对比原文与修改版
- **智能链回退告警**：智能风格链不可用时，预览与生成前醒目提示回退原因并给出修复指引
- **A/B测试支持**：快速切换模板配置，对比不同提示词效果
- **导入/导出**：支持 JSON 和 Markdown 格式的模板导入导出
- **API密钥安全**：每次使用手动输入，不存储到文件或数据库
- **模板变量记忆**：变量输入值自动保存到 localStorage
- **错误提示中文化**：后端异常统一转换为中文提示，常见英文错误（鉴权失败、限流、余额不足等）自动翻译

## 目录结构

```
Forestar_Editior/
├── Forestar Editor.exe                            # 桌面端主程序（双击即可运行，主分发形态）
├── forestar-server.exe    # 桌面端内嵌后端（与主程序同目录分发）
├── README.md
├── LICENSE                                        # MIT 开源许可证
├── requirements.txt                               # Python 依赖（Web 版）
├── package.json                                   # Tauri 构建脚本
├── forestar-server.spec                           # PyInstaller 打包配置
├── forestar-version-info.txt                      # 后端 exe 版本信息（降低杀软误报）
├── Dockerfile                                     # Web 版容器化（自托管入口）
├── .dockerignore
├── server/                                        # Flask Web 后端
│   ├── app.py                                     # Web 版入口（开发调试 / 自托管）
│   ├── config.py                                  # 应用配置
│   ├── database/                                  # ORM 模型、轻量迁移
│   ├── services/                                  # 业务服务层
│   ├── routes/                                    # API 路由层
│   ├── templates/                                 # 前端页面模板
│   └── static/                                    # 前端静态资源
├── src/                                           # Tauri 启动等待页（后端就绪后自动跳转）
├── src-tauri/                                     # Tauri 桌面应用（主产品）
│   ├── src/                                       # Rust 源码（Sidecar 启动与清理）
│   ├── icons/                                     # 应用图标
│   ├── capabilities/                              # Tauri 权限配置
│   ├── binaries/                                  # 后端打包产物（构建时生成）
│   ├── Cargo.toml
│   └── tauri.conf.json                            # externalBin 指向后端二进制
├── scripts/                                       # 构建 / 维护脚本
│   ├── build-all.ps1                              # 一键构建 + 复制直接运行版到根目录
│   ├── build-backend.ps1                          # 仅打包 Flask 后端
│   └── generate-icon.py                           # 生成应用图标源图
└── data/                                          # Web 版旧数据目录（迁移后保留备份）
```

### 后端职责分层

`server/services/` 中 `generation_service.py` 是文章生成公共门面；新增代码按职责放入对应模块：

```text
server/
├── services/
│   ├── errors.py                    # 跨服务领域异常与中文错误文案
│   ├── generation_service.py        # 兼容门面 + 正文生成编排
│   ├── generation/
│   │   ├── editing.py               # 局部续写、重写、扩写、润色
│   │   └── records.py               # 生成记录查询与持久化
│   ├── prompt_assembler.py          # 兼容/结构化/智能风格链提示词编排
│   ├── style_profile_service.py     # Style Card 分析与主风格管理
│   ├── style_excerpt_service.py     # 风格片段切分、标注与场景检索
│   ├── token_budget.py              # Token 预算与超限检查
│   └── api_client.py                # 各 LLM 提供商协议适配
├── routes/
│   ├── template_routes.py           # 模板 API
│   ├── generation_routes.py         # 生成 API
│   ├── style_routes.py              # 风格 API
│   └── support/                     # 文档提取、请求解析等支撑逻辑
└── database/
    └── migrations.py                # 幂等 SQLite 轻量迁移
```

路由层只处理 HTTP 输入输出；领域校验放在服务层；提供商协议差异集中在 `api_client.py`，避免散落到路由或前端。

## 快速开始

### 方式一：桌面版（推荐，唯一主分发形态）

项目根目录已包含可直接运行的两个文件（由构建脚本生成）：

1. 将 `Forestar Editor.exe` 与 `forestar-server.exe` 放在**同一目录**（保持文件在根目录即可）
2. 双击 `Forestar Editor.exe`，等待本地服务启动后自动进入工作台

> 桌面版无需安装 Python、Node 或 Rust，用户数据（SQLite）自动持久化在 `%USERPROFILE%\.forestar-editor\data`。

### 方式二：Web 版（开发调试 / 高级用户自托管入口）

> Web 版与桌面版共用同一份 SQLite 数据库（见下方「数据互通」）。
> 产品定位：**桌面版是唯一主分发形态**；Web 版面向开发者日常调试、以及熟悉 Python/Docker 的高级用户自托管，不面向普通用户分发。

**方式 2.1：本地运行（开发调试）**

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\python -m pip install -r requirements.txt

# 2. 启动 Web 版（后端入口位于 server/ 下）
.\.venv\Scripts\python server\app.py
```

浏览器访问 http://127.0.0.1:5000。可用环境变量覆盖监听地址与端口：`FORESTAR_HOST`（默认 `127.0.0.1`）、`FORESTAR_PORT`（默认 `5000`）。

**方式 2.2：Docker 自托管（高级用户）**

```bash
docker build -t forestar-editor .
docker run -d -p 5000:5000 \
  -v forestar-data:/root/.forestar-editor/data \
  forestar-editor
```

访问 http://127.0.0.1:5000。数据默认持久化在 Docker 卷 `forestar-data`（容器内 `/root/.forestar-editor/data`），可通过环境变量 `FORESTAR_DATA_DIR` 指定其他目录。

## 使用说明

### 1. 配置模板
在「模板管理」页面中，按分类创建提示词模板。使用 `{{变量名}}` 标记需要修改的位置。

### 2. 填写API密钥
在顶部输入框中输入所选平台对应的 API 密钥（不会保存）。选择「Kimi（硅基流动）」时，请使用硅基流动 API Key。

### 3. 填写变量
在工作台的变量区域，填写每个 `{{变量}}` 对应的值。

### 4. 生成文章
选择模型，根据需要启用思考模式和去AI味处理，点击「生成文章」。

### 5. 使用智能风格链（可选）
1. 在「模板管理」中创建或选择一个「范例文章」分类的模板，粘贴参考文本
2. 打开「风格卡」面板，点击「分析当前范例」，自动生成 Style Card（叙述视角、节奏、语言风格、检查规则等）
3. 点击「重新生成片段」，将范例切成参考片段并按场景打标
4. 回到工作台，将风格模式切换为「智能风格链」，生成时会按当前场景自动挑选最相关的风格片段

> 若范例模板尚未生成有效的 Style Card，智能风格链会自动回退为普通提示词，并在预览与生成前给出醒目提示与修复指引。

### 6. 查看历史
在「生成记录」页面查看和管理所有历史生成结果。

## 支持的模型

| 提供商 | 模型 | 思考模式 |
|--------|------|----------|
| DeepSeek | V4 Flash | ✅ |
| DeepSeek | V4 Pro | ✅ |
| OpenAI | GPT-4o | ❌ |
| OpenAI | GPT-4o Mini | ❌ |
| Kimi（硅基流动） | Kimi K2.6 | ✅ 可切换 |
| Kimi（硅基流动） | Kimi K2.5 | ✅ 可切换 |
| Kimi（硅基流动） | Kimi K2 Thinking | ✅ 固定开启 |
| Kimi（硅基流动） | Kimi K2 Instruct / 0905 | ❌ |
| 爱化身 | DeepSeek V4 Flash | ❌ |

## 数据互通（Web 版与桌面版共用同一份数据）

- **统一数据目录**：两版的数据统一存放在 `%USERPROFILE%\.forestar-editor\data\forestar.db`，可通过环境变量 `FORESTAR_DATA_DIR` 覆盖到其他位置
- **Web 版**（`python server\app.py`）：同样使用上述公共目录；首次运行时若检测到旧的 `data\forestar.db`，会自动**复制**迁移到公共目录（原目录保留作为备份，仅执行一次）
- **桌面版**：安装或直接运行后，数据直接读写同一公共目录，与 Web 版完全互通——在网页版创建的模板、生成的记录，桌面版打开即可见，反之亦然
- **端口说明**：桌面版每次启动自动使用**随机空闲端口**（不再固定占用 5000），Web 版默认 `5000`，两者可同时运行互不冲突

## 打包构建（Windows）

前置要求：Node.js ≥ 18、Rust 工具链、Python 3.10+。

```powershell
# 1. 安装前端依赖（Tauri CLI）
npm install

# 2. 一键构建：先打包 Python 后端，再构建 Tauri 安装包，
#    最后把「直接运行版」主程序 + 后端复制到项目根目录
npm run build:all
```

构建产物：

| 产物 | 位置 | 说明 |
|------|------|------|
| 直接运行版主程序 | 项目根目录 `Forestar Editor.exe` | 与 `forestar-server.exe` 同目录双击运行 |
| 内嵌后端 | 项目根目录 `forestar-server.exe` | 由 PyInstaller 打包，随主程序分发 |
| NSIS 安装包 | `src-tauri\target\release\bundle\nsis\` | 面向普通用户的安装程序 |

分步构建：

```powershell
# 仅打包后端（生成 src-tauri\binaries\forestar-server-*.exe）
npm run build:backend

# 仅构建 Tauri 桌面应用与安装包
npm run tauri:build
```

> 打包说明：后端 exe 关闭了 UPX 压缩（降低杀软误报率）并注入标准 Windows 版本信息（[forestar-version-info.txt](forestar-version-info.txt)）；`build:backend` 的原始产物位于 `dist/forestar-server.exe`。

### 桌面版架构说明

- **前端 100% 复用**：`server/templates/`、`server/static/` 由 Flask 直接提供，桌面窗口在后端就绪后自动导航到 `http://127.0.0.1:5000`，前端代码零修改
- **后端 100% 复用**：`server/services/`、`server/routes/`、`server/database/` 用 PyInstaller 编译为单文件可执行程序，由 Tauri 以 Sidecar 方式自动拉起
- **Sidecar 启动**（`src-tauri/src/lib.rs`）：Tauri 启动时以 `shell.sidecar("forestar-server")` 拉起 Flask 后端，先探测空闲端口并通过环境变量 `FORESTAR_PORT` 传给后端，轮询该端口就绪后跳转；退出时自动 kill 子进程，避免残留
- **`useLocalToolsDir: true`**（`tauri.conf.json`）：将 NSIS 等打包工具缓存到项目内 `src-tauri/target/.tauri/`，避免写入系统缓存目录（无权限或沙箱环境下必要）

### 安装与卸载

- 安装：双击 `Forestar Editor_1.0.0_x64-setup.exe`，默认安装到当前用户目录（`currentUser` 模式，无需管理员权限），语言为简体中文；安装时会创建开始菜单与桌面快捷方式
- 卸载：通过「设置 → 应用」或开始菜单中的卸载入口执行；NSIS 卸载器会移除应用文件、快捷方式与注册表条目
- 数据保留：卸载时**默认保留用户数据**——SQLite 数据库存放在统一用户数据目录，前端缓存存放在 `%LOCALAPPDATA%\com.forestar.editor`（WebView2 数据）；如需彻底清除，可手动删除这两个目录

## 常见问题排查

| 现象 | 原因 | 解决 |
|---|---|---|
| 窗口提示「后端启动超时」 | 随机端口被占用、杀毒软件拦截、上次运行残留进程 | 任务管理器结束 `forestar-server.exe` 后重试；将应用加入杀毒白名单 |
| 直接运行版双击无反应 | 主程序与后端不在同一目录，或后端被杀毒软件拦截 | 确认 `forestar-server.exe` 与主程序同目录；将应用加入杀毒白名单 |
| `cargo` 命令找不到 | cargo 不在 PATH | `$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"` |
| `NSIS directory is missing some files` | 打包工具缓存损坏或网络下载失败 | 删除 `src-tauri\target\.tauri\NSIS` 目录后重新 `npm run tauri:build` |
| Sidecar 无法启动（终端无输出） | `binaries/` 下二进制命名不匹配 | 确认存在 `forestar-server-x86_64-pc-windows-msvc.exe`，重新执行 `npm run build:backend` |
| 杀毒软件误报 | PyInstaller 单文件程序未签名 | 加入白名单，或后续配置代码签名证书 |
| 构建下载超时（GitHub 资源被阻断） | 网络代理问题 | 使用镜像或代理下载后手动放入缓存，再重试构建 |

## License

本项目暂未指定开源许可证，使用前请联系作者确认授权方式。
