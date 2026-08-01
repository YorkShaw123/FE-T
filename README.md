# Forestar Editor - AI文字创作助手

一个基于 Flask + SQLite 的本地 Web 应用，用于快速组装提示词模板并调用大语言模型 API 生成文章。

## 功能特点

### 核心功能
- **提示词模板管理**：按分类（人物设定、背景设定、剧情设定、范例文章、更多约束）管理自定义提示词模板
- **挖空修改**：模板中使用 `{{变量名}}` 标记可修改的部分，自动生成输入框
- **一键生成**：将所有活跃模板自动拼接为完整提示词，调用 AI 生成文章
- **去AI味处理**：第一次生成后自动发送去AI味提示词，获得更自然的文章
- **前情提要压缩**：过长的前情提要自动压缩为概述
- **多模型支持**：DeepSeek、OpenAI、硅基流动 Kimi，以及爱化身兼容接口
- **思考模式**：支持 DeepSeek 与 Kimi 对应模型的思考模式（思维链展示）
- **暗色/亮色模式**：一键切换

### 高级功能
- **提示词版本控制**：修改内容自动创建新版本，支持版本回溯和恢复
- **生成记录管理**：保存生成的文章及使用的模板、时间等信息
- **A/B测试支持**：快速切换模板配置，对比不同提示词效果
- **导入/导出**：支持 JSON 和 Markdown 格式的模板导入导出
- **API密钥安全**：每次使用手动输入，不存储到文件或数据库
- **模板变量记忆**：变量输入值自动保存到 localStorage

## 快速开始

### 安装依赖
```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\python -m pip install -r requirements.txt
```

如果项目是从另一台电脑复制而来，请重新创建 `.venv`，不要复用其中记录的旧 Python 路径。

### 启动
```bash
.\.venv\Scripts\python app.py
```

浏览器访问 http://127.0.0.1:5000。

> API 密钥只存在当前页面的输入框中，不写入数据库，也不会保存到浏览器草稿。

### 原有环境仍有效时
```bash
pip install -r requirements.txt
python app.py
```

访问 http://127.0.0.1:5000

## 项目结构
```
Forestar_Editior/
├── app.py                     # Flask 主入口
├── config.py                  # 应用配置
├── requirements.txt           # Python 依赖
├── data/                      # SQLite 数据库存储
├── database/
│   ├── __init__.py            # 数据库初始化
│   └── models.py              # ORM 模型定义
├── services/
│   ├── __init__.py
│   ├── api_client.py          # LLM API 客户端
│   ├── prompt_assembler.py    # 提示词组装器
│   ├── summarizer.py          # 文本压缩服务
│   ├── template_service.py    # 模板CRUD+版本控制
│   └── generation_service.py  # 文章生成编排
├── routes/
│   ├── __init__.py
│   ├── template_routes.py     # 模板API路由
│   └── generation_routes.py   # 生成API路由
├── templates/
│   └── index.html             # 前端单页应用
├── static/
│   ├── css/
│   │   └── style.css          # 完整样式表
│   └── js/
│       └── app.js             # 前端业务逻辑
└── README.md
```

### 后端职责分层

为保持既有导入兼容，`services/generation_service.py` 继续作为文章生成公共门面；新增代码应优先放入对应职责模块：

```text
services/
├── errors.py                    # 跨服务领域异常
├── generation_service.py       # 兼容门面 + 正文生成编排
├── generation/
│   ├── editing.py              # 局部续写、重写、扩写、润色
│   └── records.py              # 生成记录查询与持久化
├── prompt_assembler.py         # 兼容/结构化提示词编排
├── token_budget.py             # Token 预算与超限检查
└── api_client.py               # 各 LLM 提供商协议适配

routes/support/
├── document_text.py            # TXT、DOC、DOCX 文本提取
└── generation_request.py       # 生成请求解析、默认值、模板选择

database/
└── migrations.py               # 幂等 SQLite 轻量迁移
```

路由层只处理 HTTP 输入输出；领域校验放在服务层；提供商协议差异集中在 `api_client.py`，避免散落到路由或前端。

## 使用说明

### 1. 配置模板
在"模板管理"页面中，按分类创建提示词模板。使用 `{{变量名}}` 标记需要修改的位置。

### 2. 填写API密钥
在顶部输入框中输入所选平台对应的 API 密钥（不会保存）。选择“Kimi（硅基流动）”时，请使用硅基流动 API Key。

### 3. 填写变量
在工作台的变量区域，填写每个 `{{变量}}` 对应的值。

### 4. 生成文章
选择模型，根据需要启用思考模式和去AI味处理，点击"生成文章"。

### 5. 查看历史
在"生成记录"页面查看和管理所有历史生成结果。

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
