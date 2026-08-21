# 🌧️ 雨生编辑器（Flora Editor）

> 面向中文文字与小说创作的 Windows 本地 AI 编辑器：用提示词模板组织设定，以文风系统提供参考，再调用用户选择的大语言模型生成和修改文章。

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Flask](https://img.shields.io/badge/Flask-3.1-lightgrey)
![Tauri](https://img.shields.io/badge/Tauri-2-green)
![Platform](https://img.shields.io/badge/Platform-Windows-orange)
![License](https://img.shields.io/badge/License-MIT-green)

雨生编辑器是 Flora Editor 的中文产品名。这是一款本地运行的桌面小工具：它把人物、背景、剧情、范例和其他约束整理成可复用模板，通过可视化生成链路组合提示词，并将成稿、模板和文风语料保存在本机。

项目以 Windows 桌面端为正式产品形态；浏览器地址只用于本机开发测试，不提供 Web、SaaS 或远程自托管能力。

## 功能特点

- **提示词模板管理**：将人物、背景、剧情、范例文章和其他约束分开保存，按本次写作需要启用。
- **多服务 AI 生成**：选择不同 AI 服务和模型，按当前模板、上下文与文风配置生成文章。
- **智能风格链**：从范例文章提取 Style Card，并按写作场景选择少量参考片段。
- **Style RAG 文风语料库**：导入大规模 TXT、DOC 或 DOCX 参考文本，检索与当前写作场景匹配、同时降低内容复用风险的文风片段。
- **本地 Style Engine**：在本机分析中文句式节奏、标点和功能词等特征；语义向量只是可选辅助信号。
- **续写与修改**：支持续写、重写、扩写、润色、去 AI 味处理，以及可选的 RAG 风格参考二次改写。
- **编辑与历史**：在全屏 Markdown 编辑器中修改、比较版本，并管理生成记录。
- **生成前检查**：预估 Token 用量，在超过模型上下文限制前给出提示。

## 快速开始

### Windows 桌面版

桌面版是普通用户的主要使用方式：

1. 获取同一版本的 `雨生编辑器.exe` 和 `flora-server.exe`。
2. 将两个文件放在同一目录，不要单独移动其中一个。
3. 双击 `雨生编辑器.exe`，等待工作台打开。

桌面版不要求用户安装 Python、Node.js 或 Rust。首次启动会在用户目录创建本地数据文件。

> 当前仓库根目录中的两个 EXE 是构建脚本生成的直接运行版；正式安装包位于构建产物的 NSIS 目录。

### 本机开发运行

需要 Python 3.10 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python server\app.py
```

然后访问 <http://127.0.0.1:5000>。该服务固定监听本机回环地址；可用 `FLORA_PORT` 修改开发端口。

开发检查、桌面调试和目录说明见[开发指南](docs/development.md)。

## 基本使用

1. 在“模板管理”中创建或选择人物、背景、剧情、范例文章等模板。新数据库会提供“推云童子雨生”和“雨落万物生”两个可修改、可删除的入门案例；删除后不会再次自动生成。
2. 在顶栏选择 AI 服务并填写该服务的 API Key。
3. 回到工作台，在左侧启用本次需要的模板；模板内容会按原文直接进入生成链，不需要特殊占位符。
4. 按需选择提示词编排、风格卡和上下文输入，然后点击“生成文章”。初次生成结果显示在“04 生成初稿”。
5. 若开启“05 语言自然化”或“06 风格参考”，系统会在初稿完成后各执行一次可选处理，处理后的版本显示在“07 最终成稿”。
6. 点击初稿或最终成稿节点查看正文，也可进入全屏编辑器继续修改。

API Key 由不同服务商分别签发，不能混用。思考模式是否可用取决于当前 Provider 和模型能力。

### 使用文风功能

- 少量范例可使用“智能风格链”：先为范例模板生成 Style Card 和参考片段，再在工作台启用。
- 大规模参考文本可使用“文风管理”：创建语料库、导入文件，然后选择是否建立语义向量索引；工作台开启“06 风格参考”后，系统会在初稿完成后检索片段并进行一次受约束的二次改写。
- Style Engine 的主要文风分析和排序在本机完成；没有语义模型时仍可降级运行，不会导致整个文风检索不可用。

详细原理、索引兼容规则和内容复用保护见 [Style RAG 与 Style Engine](docs/style-rag.md)。

## Embedding 模式

当前代码同时支持两种可插拔 Embedding 后端，但 **默认选择本地模式**：

| 模式 | 实现 | 是否需要 API Key | 用途 |
|---|---|---:|---|
| 本地（默认） | `BAAI/bge-small-zh-v1.5` + ONNX Runtime CPU | 否 | 为场景/语义提供辅助信号 |
| 远程（兼容） | 硅基流动 `BAAI/bge-m3` | 是 | 兼容已有远程索引和手动选择 |

本地模型和运行时缺失时，检索会回退到不含语义分数的本地 Style Engine。不同模型生成的向量不会混用；更换后端或模型后，需要重新向量化对应语料库。

安装方法、模型目录和发行包说明见[本地 Embedding](docs/local-embedding.md)。

## 支持的 AI 服务

当前应用配置包含以下 Provider：

- DeepSeek
- OpenAI
- Kimi（月之暗面官方）
- 通义千问（阿里云百炼）
- 智谱 GLM
- Google Gemini
- xAI Grok
- 硅基流动

实际可用模型、思考能力、上下文限制和费用可能随服务商调整，请以应用内当前配置和各服务商 API 为准。

## 数据与隐私

- API Key 仅从当前输入框随请求使用，不写入 SQLite，也不保存到文件或浏览器本地存储；重新打开应用后需要再次输入。
- 模板、文风语料索引和生成记录保存在 `%USERPROFILE%\.flora-editor\data\flora.db`。
- 本地 Embedding 模型保存在 `%USERPROFILE%\.flora-editor\models\`，不写入 SQLite。
- 可用 `FLORA_DATA_DIR` 和 `FLORA_MODELS_DIR` 覆盖开发测试目录。
- Flask 服务只监听 `127.0.0.1`；桌面端使用随机回环端口，开发模式默认使用 `5000`。
- 卸载应用默认保留 SQLite 数据和 WebView2 本地缓存。如需彻底删除，请先备份，再手动清理相应用户目录。

从旧品牌目录迁移时，程序只在新数据库尚不存在时复制旧数据，并保留原文件作为备份。

## 开发文档

- [架构说明](docs/architecture.md)：Tauri、Flask Sidecar、前后端与数据层的关系。
- [开发指南](docs/development.md)：源码运行、项目目录和质量检查命令。
- [Style RAG 与 Style Engine](docs/style-rag.md)：语料导入、文风特征、检索和兼容性。
- [本地 Embedding](docs/local-embedding.md)：本地/远程后端、模型安装与重新索引。
- [Windows 构建](docs/build.md)：后端打包、Tauri 构建和产物位置。
- [故障排查](docs/troubleshooting.md)：启动、Embedding、构建和 API 常见问题。
- [Style Engine 设计文档](docs/style-engine/README.md)：里程碑、特征规格和评测计划。

## 构建

安装 Node.js 18+、Rust 工具链和 Python 3.10+ 后：

```powershell
npm install
npm run build:all
```

该命令生成 Flask Sidecar、Tauri 桌面程序和 NSIS 安装包。详细前置条件、分步命令和本地 Embedding 打包选项见 [Windows 构建](docs/build.md)。

## License

本项目采用 [MIT License](LICENSE)。
