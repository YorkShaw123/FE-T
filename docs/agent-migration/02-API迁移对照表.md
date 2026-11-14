# 02 API 迁移对照表

> 59 个端点的逐一去处、请求响应模型、以及"前端零改动"的过渡策略。
> 前置：[01-模块映射表](01-模块映射表.md)、[03-Agent图设计](03-Agent图设计.md)。

## 0. 三条原则

**第一，路径先双轨再收口。** 新实现挂在 `/api/v1/*`，旧 `/api/*` 用叠挂装饰器映射到同一个处理函数。前端 19 个 JS 模块一行不改就能跑通；等回归通过，删掉旧装饰器是一个 commit 的事。

**第二，响应形状不变。** 现在前端到处读 `res.success` / `res.error`，改造后继续返回这个形状。FastAPI 的 `HTTPException` 通过统一异常处理器翻译成 `{"success": false, "error": "中文原因"}`，前端不感知框架换了。

**第三，SSE 保留命名事件。** `/api/generation/generate-stream` 与新的 `/api/v1/chat/stream` 都用 `StreamingResponse`，事件名沿用 `event: token / status / complete / error / done`。理由见 03 文档 2.5 节。

## 1. 总览

| 命名空间 | 端点 | 新归属 |
| --- | --- | --- |
| `/` | 1 | 静态页（`main.py` 挂 templates/static） |
| `/api/health` | 1 | 原位保留 |
| `/api/generation/*` | 13 | 拆成 `/api/v1/writing/*`（8）与 `/api/v1/records/*`（5） |
| `/api/templates/*` | 13 | `/api/v1/templates/*` |
| `/api/style-corpora/*` | 15 | `/api/v1/corpora/*` |
| `/api/style-profiles/*` | 9 | `/api/v1/style/*` |
| `/api/modes/*` | 3 | `/api/v1/modes/*` |
| `/api/system/*` | 4 | `/api/v1/system/*`（桌面专用） |
| **合计** | **59** | |
| 新增 | 3 | `/api/v1/chat/stream`、`/api/v1/auth/session`、`/api/v1/consistency/review` |

## 2. 写作与记录（13 个端点）

`generate` 与 `generate-stream` 改为调 Orchestrator；`records` 五个端点与写作解耦，单独成模块。

| 旧路径（方法） | 新路径 | 动作 | 说明 |
| --- | --- | --- | --- |
| `GET /api/generation/models` | `GET /api/v1/writing/models` | 平移 | 返回 `LLM_PROVIDERS` 配置，结构不变 |
| `GET /api/generation/categories` | `GET /api/v1/writing/categories` | 平移 | 模板分类枚举 |
| `GET /api/generation/default-deai-prompt` | `GET /api/v1/writing/deai-prompt` | 平移 | 路径略短化 |
| `POST /api/generation/preview-prompt` | `POST /api/v1/writing/preview` | 平移 | 只组装不调用模型，供 01–03 节点预览 |
| `POST /api/generation/extract-text` | `POST /api/v1/writing/extract-text` | 重写 | multipart `UploadFile` 替代 `request.files` |
| `POST /api/generation/transform-text` | `POST /api/v1/writing/transform` | 包装 | 局部改写走写作图的 `editing` 节点 |
| `POST /api/generation/generate` | `POST /api/v1/writing/generate` | Agent 化 | 同步模式：跑完图返回 `complete` 载荷 |
| `POST /api/generation/generate-stream` | `POST /api/v1/writing/generate-stream` | Agent 化 | 流式：图的 `astream` 转 SSE |
| `GET /api/generation/records` | `GET /api/v1/records` | 平移 | 分页参数不变 |
| `GET /api/generation/records/{id}` | `GET /api/v1/records/{record_id}` | 平移 | |
| `PUT /api/generation/records/{id}` | `PUT /api/v1/records/{record_id}` | 平移 | 手改正文 |
| `DELETE /api/generation/records/{id}` | `DELETE /api/v1/records/{record_id}` | 平移 | |
| `DELETE /api/generation/records` | `DELETE /api/v1/records` | 平移 | 清空全部 |

## 3. 模板（13 个端点）

| 旧路径（方法） | 新路径 | 动作 | 说明 |
| --- | --- | --- | --- |
| `GET /api/templates` | `GET /api/v1/templates` | 平移 | 支持 `category` / `active_only` 查询参数 |
| `GET /api/templates/grouped` | `GET /api/v1/templates/grouped` | 平移 | 按分类分组，工作台左侧用 |
| `POST /api/templates` | `POST /api/v1/templates` | 平移 | 请求体改 Pydantic `TemplateCreate` |
| `GET /api/templates/{id}` | `GET /api/v1/templates/{template_id}` | 平移 | |
| `PUT /api/templates/{id}` | `PUT /api/v1/templates/{template_id}` | 平移 | 写版本记录的逻辑不动 |
| `DELETE /api/templates/{id}` | `DELETE /api/v1/templates/{template_id}` | 平移 | |
| `DELETE /api/templates/all` | `DELETE /api/v1/templates` | 平移 | 路径规整 |
| `POST /api/templates/{id}/toggle` | `POST /api/v1/templates/{template_id}/toggle` | 平移 | 启用/停用 |
| `GET /api/templates/{id}/versions` | `GET /api/v1/templates/{template_id}/versions` | 平移 | 版本历史 |
| `POST /api/templates/{id}/restore/{vid}` | `POST /api/v1/templates/{template_id}/versions/{version_id}/restore` | 平移 | 路径语义化 |
| `POST /api/templates/starter` | `POST /api/v1/templates/starter` | 平移 | 生成两个入门样例 |
| `POST /api/templates/export` | `POST /api/v1/templates/export` | 平移 | 返回 JSON 或 Markdown |
| `POST /api/templates/import` | `POST /api/v1/templates/import` | 平移 | JSON 请求体，非文件上传 |

## 4. 文风语料库（15 个端点）

这一组里有**长任务**：导入与索引都是秒级到分钟级，迁移时必须保留进度查询端点。

| 旧路径（方法） | 新路径 | 动作 | 说明 |
| --- | --- | --- | --- |
| `GET /api/style-corpora` | `GET /api/v1/corpora` | 平移 | |
| `POST /api/style-corpora` | `POST /api/v1/corpora` | 平移 | |
| `GET /api/style-corpora/{id}` | `GET /api/v1/corpora/{corpus_id}` | 平移 | |
| `PUT /api/style-corpora/{id}` | `PUT /api/v1/corpora/{corpus_id}` | 平移 | |
| `DELETE /api/style-corpora/{id}` | `DELETE /api/v1/corpora/{corpus_id}` | 平移 | 级联删 chunks |
| `GET /api/style-corpora/{id}/chunks` | `GET /api/v1/corpora/{corpus_id}/chunks` | 平移 | 分页，供调试视图 |
| `POST /api/style-corpora/{id}/import` | `POST /api/v1/corpora/{corpus_id}/import` | 重写 | `UploadFile`，单请求上限 20MB 不变 |
| `POST /api/style-corpora/{id}/index` | `POST /api/v1/corpora/{corpus_id}/index` | 包装 | 走 `KBBackend.index_corpus()`，后台任务 |
| `GET /api/style-corpora/{id}/index-progress` | `GET /api/v1/corpora/{corpus_id}/index-progress` | 平移 | 轮询索引进度 |
| `POST /api/style-corpora/{id}/clear` | `POST /api/v1/corpora/{corpus_id}/clear` | 平移 | 清空切片 |
| `GET /api/style-corpora/embedding-config` | `GET /api/v1/corpora/embedding-config` | 平移 | 当前后端与模型 |
| `GET /api/style-corpora/embedding-model/status` | `GET /api/v1/corpora/embedding/status` | 平移 | 本地模型是否就绪 |
| `POST /api/style-corpora/embedding-model/install` | `POST /api/v1/corpora/embedding/install` | 平移 | 触发下载/导出 |
| `GET /api/style-corpora/embedding-model/install-progress` | `GET /api/v1/corpora/embedding/install-progress` | 平移 | |
| `POST /api/style-corpora/search` | `POST /api/v1/corpora/search` | 包装 | 调试用，直接调 `KBBackend.search()` |

## 5. Style Card 与片段（9 个端点）

| 旧路径（方法） | 新路径 | 动作 | 说明 |
| --- | --- | --- | --- |
| `GET /api/style-profiles/{tid}` | `GET /api/v1/style/{template_id}` | 平移 | |
| `PUT /api/style-profiles/{tid}` | `PUT /api/v1/style/{template_id}` | 平移 | 人工编辑卡片 |
| `POST /api/style-profiles/{tid}/analyze` | `POST /api/v1/style/{template_id}/analyze` | 平移 | 调模型生成卡片 |
| `POST /api/style-profiles/{tid}/refresh` | `POST /api/v1/style/{template_id}/refresh` | 平移 | 重新分析 |
| `POST /api/style-profiles/{tid}/restore` | `POST /api/v1/style/{template_id}/restore` | 平移 | 恢复上一次分析结果 |
| `GET /api/style-profiles/{tid}/excerpts` | `GET /api/v1/style/{template_id}/excerpts` | 平移 | |
| `POST /api/style-profiles/{tid}/excerpts/rebuild` | `POST /api/v1/style/{template_id}/excerpts/rebuild` | 包装 | 切片 + 打标签（模型调用） |
| `PUT /api/style-profiles/{tid}/excerpts/{eid}` | `PUT /api/v1/style/{template_id}/excerpts/{excerpt_id}` | 平移 | |
| `DELETE /api/style-profiles/{tid}/excerpts/{eid}` | `DELETE /api/v1/style/{template_id}/excerpts/{excerpt_id}` | 平移 | |

## 6. 工作模式与系统（7 个端点）

| 旧路径（方法） | 新路径 | 动作 | 说明 |
| --- | --- | --- | --- |
| `GET /api/modes` | `GET /api/v1/modes` | 平移 | 返回 `work_modes` 声明式配置 |
| `GET /api/modes/{mode_id}` | `GET /api/v1/modes/{mode_id}` | 平移 | |
| `POST /api/modes/{mode_id}/generate` | `POST /api/v1/modes/{mode_id}/generate` | Agent 化 | 预留模式，内部转发写作图 |
| `POST /api/system/deepseek-api-key` | `POST /api/v1/system/deepseek-key` | 平移 | 桌面专用：读本机 Key |
| `POST /api/system/open-community-prompts` | `POST /api/v1/system/open-community-prompts` | 平移 | 桌面专用：调浏览器 |
| `POST /api/system/open-help-link/{key}` | `POST /api/v1/system/open-help/{link_key}` | 平移 | |
| `POST /api/system/shutdown` | `POST /api/v1/system/shutdown` | 平移 | Tauri 退出时调用，**不能删** |
| `GET /api/health` | `GET /api/health` | 保留 | 前缀不变，监控与冒烟用 |

## 7. 新增端点

| 新路径 | 方法 | 作用 |
| --- | --- | --- |
| `/api/v1/chat/stream` | POST | 统一入口：前置拦截 → LLM 路由 → 分发（03 文档 5.2） |
| `/api/v1/auth/session` | POST | 本地会话令牌；启动时静默签发，用户无感 |
| `/api/v1/consistency/review` | POST | 设定一致性审查（新能力） |

## 8. 请求响应模型

统一约束：所有请求体走 Pydantic，所有错误走同一个异常处理器。

| 模块 | 请求模型 | 关键字段 |
| --- | --- | --- |
| writing | `GenerateRequest` | 对应现有 `GenerationRequest.from_mapping` 的全部字段，一个不少（模板 id 列表、provider/model、采样、deai、style_* 等） |
| writing | `PreviewRequest` | 同上去掉流式与密钥必填 |
| writing | `TransformRequest` | `text`、`operation`、`instruction`、`surrounding_context` |
| records | `RecordUpdate` | `title`、`edited_content`、`rating`、`pinned`、`notes` |
| templates | `TemplateCreate` / `TemplateUpdate` | `name`、`category`、`content`、`description`、`variables`、`is_active`、`style_strength` |
| style | `StyleCardSave` | `card`、`is_primary` |
| corpora | `CorpusCreate` / `CorpusSearch` | `query`、`corpus_ids`、`scene_type`、`top_k` |
| chat | `ChatRequest` | `session_id`、`message`（1–2000 字） |

响应形状保持不变：

```json
{"success": true, "data": {...}}
{"success": false, "error": "请输入API密钥"}
```

`HTTPException` 由处理器翻译：

| 场景 | 现状 | 改造后 |
| --- | --- | --- |
| 参数缺失 | 400 + `{success:false,error}` | 422 由 Pydantic 抛出 → 处理器统一转 400 + 同形状 |
| 资源不存在 | 404 + `{success:false,error}` | 404 + 同形状 |
| 业务异常 | 500 + 友好中文 | `GenerationError` → 400；未知异常 → 500；都转同形状 |

前端只需保证读 `error` 字段，无需判断状态码——这条现状本来就是这样，所以零改动成立。

## 9. 过渡策略：双轨期怎么做

**实现方式**：一个处理函数，两套装饰器。

```python
@router.get("/writing/models")
@router.get("/api/generation/models", include_in_schema=False)   # 过渡期别名
async def get_models():
    ...
```

**收口条件**（三条全满足才删别名）：
1. 前端 19 个 JS 模块的 URL 全部改到 `/api/v1/*`，`grep` 旧前缀为 0；
2. 桌面端与浏览器端各跑一遍冒烟（4 个页签 + 一次生成 + 一次语料导入 + 一次审稿）；
3. 外部无依赖（本项目无第三方调用方，这条天然满足）。

**迁移顺序**（按风险从低到高，每步都能独立回归）：

1. `templates`、`modes`、`health` —— 纯 CRUD，先把 FastAPI 骨架和错误处理器跑通；
2. `corpora`、`style` —— 加上文件上传与长任务进度；
3. `records` —— 加上分页；
4. `writing` —— 这一步接 Agent 图，最难，放最后；
5. `system` —— 桌面专用端点，最后搬，搬完做一次真实安装包验证。

## 10. 验收清单

- 59 个旧端点在新结构里都有唯一归属，旧的 `/api/*` 与新 `/api/v1/*` 同时可达；
- 用同一份请求体对比新旧响应，`success` / `data` 结构一致（除 `data` 内新增的 Agent 元字段）；
- 错误形状三例对比通过：缺 API Key、模板不存在、语料库超限；
- 文件上传（模板导入 JSON、语料导入 multipart）各跑一次；
- 两个 SSE 端点事件序列与 03 文档 2.5 节逐条对应；
- 前端零改动的状态下，四个页签全部可用。
