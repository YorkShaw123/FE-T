# 03 Agent 图设计

> 本文档定义迁移后的三张 LangGraph 图：写作主图、风格问答图、设定一致性审查图。
> 前置阅读：[01-模块映射表](01-模块映射表.md)。口径：L1 范式对齐课件，L3 用适配器替换。

## 0. 三条设计原则

**第一，图只管顺序与分支，不管业务。** 节点函数里不允许出现提示词拼装、SQL 语句、检索打分。这些分别属于 `prompts.py`、`db/store.py`、`adapters/kb_local.py`。节点只做「取数据 → 调服务 → 写回 State」。

**第二，事件即状态。** Flora 的界面是 7 个固定节点（01 提示词编排 / 02 风格卡 / 03 上下文 / 04 生成初稿 / 05 语言自然化 / 06 风格参考 / 07 最终成稿）。图里每推进一步，必须能在前端点亮对应节点。这张映射表（第 2.5 节）是前后端的契约，比 State 字段更容易被改坏。

**第三，算法进适配器，不进图。** Style Engine 的十九个里程碑、Style RAG 的检索栈，都通过第 4 节的 `KBBackend` 与 `EmbeddingBackend` 两个协议接入。图换掉不影响算法，算法改动不影响图。

## 1. 三张图的分工

| 图 | 触发场景 | checkpointer | 流式 | 输入 | 输出 |
| --- | --- | --- | --- | --- | --- |
| `writing` | 用户点「生成文章 / 续写 / 局部改写」 | 否（一次性任务） | 是 | WritingState | record_id + 四份正文 |
| `style_qa` | 用户问设定、问风格、找参考片段 | 是（多轮对话） | 是 | StyleQAState | answer + sources + 记忆 |
| `consistency` | 用户点「审稿」或写作完成后自动触发 | 否 | 否 | ConsistencyState | 结构化报告 |

三者共用：`core/llm_factory.py`、`core/retry.py`、`core/memory.py`、`core/exceptions.py`。

节点函数统一签名：

```python
async def xxx_node(state: XxxState) -> dict:
    """返回要合并进 State 的增量字典；不抛异常，错误写进 state['errors']。"""
```

图内不捕获"可预期错误"以外的异常——可预期错误由节点自己转成 `errors` 列表项，不可预期异常交给 `core/retry.py` 的三层兜底。

## 2. 写作主图 WritingAgent

### 2.1 State 字段

WritingState 分三组：**入参组**（来自 HTTP 请求，图内只读）、**过程组**（节点之间传递）、**产出组**（最后落库与返回）。

入参组（与现有 `GenerationRequest` 字段一一对应，不新增语义）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `templates` | `list[dict]` | 已启用模板的快照（id/name/category/content/version） |
| `template_ids` | `list[int]` | 落库用的模板 id 列表 |
| `previous_article` | `str` | 前置文章（续写时） |
| `title` | `str` | 标题，默认为空则"未命名" |
| `api_key` | `str` | 只存在于本次 State，不落库 |
| `provider` / `model` | `str` | 服务商与模型 id |
| `thinking_enabled` / `reasoning_effort` | `bool` / `str` | 思考开关与强度 |
| `max_tokens` / `sampling` | `int` / `dict` | 采样参数 |
| `custom_prefix` / `custom_suffix` | `str` | 自定义前后缀 |
| `deai_enabled` / `deai_prompt` | `bool` / `str` | 05 语言自然化 |
| `style_reference_enabled` | `bool` | 06 风格参考开关 |
| `style_mode` / `style_strength` / `scene_type` | `str` | 风格链模式、强度、场景 |
| `style_corpus_ids` / `embedding_api_key` | `tuple[int]` / `str` | 语料库范围与可选远程向量 key |
| `structured_prompt_enabled` | `bool` | 结构化消息编排 |
| `stream` | `bool` | 是否流式 |

过程组：

| 字段 | 类型 | 由谁写 |
| --- | --- | --- |
| `messages` | `list[dict]` | `assemble_prompt` |
| `assembled_prompt` | `str` | `assemble_prompt`（供预览与落库） |
| `token_budget` | `dict` | `budget_check` |
| `style_metadata` | `dict` | `assemble_prompt` / `style_retrieve` |
| `reference_excerpts` | `list[dict]` | `style_retrieve` |
| `style_rewrite_status` | `str` | `style_retrieve` / `style_rewrite`（disabled/skipped/applied/empty_response） |
| `errors` | `list[dict]` | 任何节点 |
| `fallback_used` | `bool` | `core/retry.py` 降级时置位 |

产出组：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `story_content` | `str` | 初稿正文 |
| `reasoning_content` | `str` | 思维链（DeepSeek 思考模式） |
| `deai_content` | `str` | 去 AI 味后的版本 |
| `style_reference_content` | `str` | 风格参考改写后的版本 |
| `final_content` | `str` | 三选一的最终稿 |
| `finish_reason` | `str` | `stop` / `length` |
| `record_id` | `int` | 落库主键 |

### 2.2 八个节点

| 序号 | 节点 | 职责 | 依赖的现有模块 | 产出 |
| --- | --- | --- | --- | --- |
| 1 | `assemble_prompt` | 按 legacy / structured / smart 三条路线组装 messages；smart 缺卡时回退 legacy | `prompt_assembler` | `messages`、`assembled_prompt`、`style_metadata` |
| 2 | `budget_check` | 预估各阶段 Token，超限拦截 | `token_budget` | `token_budget` |
| 3 | `draft` | 调模型流式出初稿，聚合正文与思维链 | `llm_factory` + `adapters/llm_openai_compat` | `story_content`、`reasoning_content` |
| 4 | `deai_rewrite` | 第二阶段：去 AI 味 | 同上（stream） | `deai_content` |
| 5 | `style_retrieve` | 用最新正文检索风格参考片段；空则标记 skip | `adapters/kb_local` | `reference_excerpts`、`style_metadata.style_reference` |
| 6 | `style_rewrite` | 第三阶段：受约束二次改写 | 同上 | `style_reference_content` |
| 7 | `finalize` | 选最终稿（风格 > 去味 > 初稿）＋空正文兜底 | 纯函数 | `final_content` |
| 8 | `persist` | 写 `generation_records`（含用户中止的部分保存分支） | `db/store` | `record_id` |

把检索与改写分成两个节点的原因：检索可能慢（千级语料），单独成节点后既能单独重试，也能在检索为空时干净地跳过改写，而不用在改写节点里写 if。

### 2.3 图装配

```text
START
  │
  ▼
assemble_prompt
  │
  ▼
budget_check ──(over)──→ abort ──→ END
  │
 (ok / warning)
  ▼
draft ────────────(事件: token / reasoning)──────────→ 前端 04 节点
  │
  ├──(deai_enabled 且 draft 非空)──→ deai_rewrite ──→ 前端 05 节点
  │                                        │
  ├──(style_reference_enabled)─────────────┤
  │                                        ▼
  │                                  style_retrieve
  │                                   ├─(有片段)→ style_rewrite ──→ 前端 06 节点
  │                                   └─(空)────→ finalize
  │                                        │
  └────────────────────────────────────────┴──→ finalize
                                                     │
                                                     ▼
                                                  persist ──→ 前端 07 节点
                                                     │
                                                     ▼
                                                    END
```

条件边函数（四个）：

```python
def route_after_budget(state) -> str:      # "draft" | "abort"
def route_after_draft(state) -> str:       # "deai_rewrite" | "style_retrieve" | "finalize"
def route_after_deai(state) -> str:        # "style_retrieve" | "finalize"
def route_after_retrieve(state) -> str:    # "style_rewrite" | "finalize"
```

每个函数只读 State，不做副作用，判断依据全部是布尔开关加内容非空检查——这样才能在单元测试里不带模型就跑通路由。

### 2.4 中断点与异常路径

**中断点一：预算警告。** `budget_check` 返回 `status == 'warning'` 时，默认自动继续（桌面端不打断用户），但保留 `interrupt()` 开关：把 `options = ["继续", "缩短输出"]` 交给前端，选了缩短就把 `max_tokens` 降一档再进 `draft`。这是课件试卷批改里 Human-in-the-Loop 的同构用法，只是这里决策的是预算而不是评分。

**中断点二：用户点停止。** 前端断开 SSE 时，`draft` 节点内部的流会被取消。在图外用一个 `try/finally` 把已收到的 `story_content` 交给 `persist` 的 `partial=True` 分支，记录标题追加"（未完成）"、备注写"生成被用户停止"。这条现在就在做（`GeneratorExit` 分支），迁移时不许丢。

**异常路径**：`draft` 三次重试全失败 → `core/retry.py` 的第二层降级返回"当前模型不可用，请稍后重试"文案，并把 `fallback_used=True` 写回 State；第三层系统兜底保证 SSE 一定有个 `done` 事件，前端不会一直转圈。

### 2.5 事件协议（前后端契约）

现有前端解析的是 `event: <type>` + `data: {...}`，改造后沿用这个格式，只统一事件名：

| 事件 | 载荷 | 对应界面节点 |
| --- | --- | --- |
| `token_budget` | `{status, phases, blocking_phase}` | 生成前提示 |
| `status: prompt_preparing` | `{}` | 01/02/03 组装中 |
| `token` | `{data: "文本片段"}` | 04 或 05 或 06（按 `stage` 字段区分） |
| `reasoning` | `{data: "思维链片段"}` | 04 折叠区 |
| `status: deai_start` / `deai_done` | `{}` | 05 |
| `status: style_reference_retrieving` / `start` / `done` / `skipped` | `{reference_count, corpus_ids, reason}` | 06 |
| `complete` | 四份正文 + `record_id` + `finish_reason` + `truncated` + `sampling_dropped` | 07 |
| `error` | `{data: 中文可读信息}` | 全局 |
| `done` | `{}` | 收尾 |

与课件的差异：课件用 `sse-starlette` 的 `{"data": json}` 单一通道，Flora 用命名事件。**保留 Flora 的命名事件**，因为前端 19 个模块已经按事件名分派，改成单通道等于重写前端。这是"L3 适配"的一处具体体现。

### 2.6 与现有模块的接口约定

| 图内调用点 | 现有函数 | 改造要求 |
| --- | --- | --- |
| `assemble_prompt` | `prompt_assembler.assemble_prompt / assemble_structured_messages / assemble_style_pipeline_messages` | 签名不变；返回值从 messages 或字符串统一成 messages |
| `budget_check` | `token_budget.calculate_token_budget` | 不变，直接调用 |
| `draft` / `deai_rewrite` / `style_rewrite` | 现 `LLMClient.generate_stream_aggregated` | 改为 `llm_factory.get_llm("writing", streaming=True)` 的 `astream`，Provider 差异留在 `adapters/llm_openai_compat` |
| `style_retrieve` | `style_rag_service.hybrid_search_style(query_text, corpus_ids, scene_type, top_k, ...) -> (items, meta)` | 通过 `KBBackend.search()` 调用，签名保持 |
| `persist` | `generation/records.py` + `GenerationRecord` | 改 async session，字段一个不能少 |
| 图外 | `operation_guard` | 换成 `asyncio.Lock`，在图调用前 acquire、图结束后 release |

## 3. 风格问答图 StyleQAAgent

结构与课件第五章的 QA Agent 一致，只把"知识库"从课程文档换成"文风语料"。

### 3.1 State 字段

| 字段 | 说明 |
| --- | --- |
| `messages` / `session_id` / `user_id` | 会话三件套 |
| `query_type` | `PRECISE` / `VAGUE` / `BROAD` / `GENERAL` |
| `requested_scene` / `corpus_ids` | 硬过滤条件 |
| `hyde_doc` | 假设性回答（VAGUE 分支用） |
| `rewritten_queries` | 多查询改写结果（BROAD 分支用） |
| `candidates` / `reranked` | 召回与精排结果 |
| `is_high_confidence` | 置信度判定 |
| `answer` / `answer_mode` / `sources` / `confidence` | 产出 |
| `memory_summary` | 记忆压缩结果 |
| `pending_enqueued` | 是否已进"待补语料"队列 |

### 3.2 节点与条件边

```text
START → classify_query
  ├─ GENERAL  → generate_general
  ├─ PRECISE  → retrieve
  ├─ VAGUE    → hyde_generate    → retrieve
  └─ BROAD    → multi_query_rewrite → retrieve

retrieve → rerank
  ├─ 高置信 → generate_rag ────→ save_memory → END
  └─ 低置信 → generate_direct → enqueue_pending → save_memory → END
```

`classify_query` 用 LLM 做四分类（与课件 8.4 一致：跨场景路由交给 LLM，不用本地小模型）。本地 ONNX 分类器作为可选加速项，缺模型时纯 LLM 兜底——这与现有 `embedding_backends` 的降级策略同源。

`rerank` 节点在桌面端默认走"规则 + MMR"，接 `EmbeddingBackend` 时才有向量精排；接入 BGE-Reranker 是可选增强，不是必需。

`enqueue_pending` 是本图新增的一张小表：当检索置信度低、答不上来时，把问题记进 `style_pending_questions`，用户下次可以据此补语料。这是课件"低置信度入队"的直接迁移。

### 3.3 与课件的差异对照

| 课件 | Flora 落地 | 原因 |
| --- | --- | --- |
| Milvus HNSW + WeightedRanker(0.7/0.3) | `LocalKB`：SQLite 存向量 + numpy 余弦 + FTS5 BM25 + RRF + MMR | Windows 桌面不能跑 Milvus 集群；检索口径与现有 Style RAG 一致 |
| BGE-M3（torch 2.2GB） | `bge-small-zh-v1.5` ONNX（512 维），`embedding_flag` 可选 | 安装包体积；AGENTS.md 禁止 PyTorch 进发行包 |
| MiniLM 微调分类器 | LLM 分类 + 规则兜底 | 少一个 87MB 模型；桌面端调用量低 |
| MCP Server（知识库 + Web 搜索） | 保留知识库 MCP 接口形态，Web 搜索默认关闭 | 本地写作工具不联网更符合隐私定位 |

## 4. 设定一致性审查图 ConsistencyAgent（新增能力）

这是本次改造唯一真正新增的图，也是最能说明"为什么值得从单体改成 Agent"的地方：原来的系统只能生成，不能自查。这张图把课件"简历六维评审"的结构搬过来——**并行多维度 → 汇总 → 报告**。

### 4.1 State 字段

| 字段 | 说明 |
| --- | --- |
| `chapter_text` | 待审正文 |
| `setting_snapshot` | 当前启用的人物/背景/剧情模板内容 |
| `history_digest` | 前文章节摘要（来自 `summarizer`） |
| `entities` | 抽取出的人物、地点、物品 |
| `findings` | 各维度发现的问题列表 |
| `severity` | `blocker` / `major` / `minor` |
| `report` | 最终报告 Markdown |
| `record_id` | 关联的生成记录 |

### 4.2 节点与并行分支

```text
START → load_setting → extract_entities
                          │
        ┌─────────────────┼──────────────────┬─────────────────┐
        ▼                 ▼                  ▼                 ▼
  check_character   check_timeline     check_foreshadow   check_style_drift
   (人设一致性)        (时间线/因果)        (伏笔回收)          (文风漂移)
        └─────────────────┼──────────────────┴─────────────────┘
                          ▼
                     synthesize（合并去重 + 定级）
                          ▼
                     report → persist → END
```

四个 `check_*` 节点是并行的（LangGraph 里同一层的多个节点并行执行），这正是课件简历 Agent"六维度并行评审"的做法——把 N 次串行模型调用压成一次并发等待。

`check_style_drift` 复用现有 `style_diff_service.analyze_style_diff`：它本来就在算"你的稿子离目标画像有多远"，只是以前只用来生成改写建议，现在当成审稿维度之一。

### 4.3 编排方式

它既能单跑（用户点"审稿"），也能挂在写作图后面跑（写 → 审 串联），这就是课件 8.3 的 Pipeline 模式在 Flora 里的落点：

```python
_pipelines = {
    "write_and_review": [AgentType.WRITING, AgentType.CONSISTENCY],
}
```

前一步产出的 `record_id` 与 `final_content` 注入后一步的 `context`，与课件"前序 structured_output 注入后序 context"完全同构。

## 5. Orchestrator 编排

### 5.1 枚举与 Schema

```python
class AgentType(str, Enum):
    WRITING     = "writing"
    STYLE_QA    = "style_qa"
    CONSISTENCY = "consistency"

class ExecutionMode(str, Enum):
    SINGLE   = "single"
    PIPELINE = "pipeline"
    CLARIFY  = "clarify"
```

`AgentRequest` 沿用课件字段，做两处本地化：`student_id` → `user_id`，`tenant_id` 保留但固定为 `local_default`；`thread_id` 规则改为 `flora_{user_id}_session_{session_id}`。

`AgentResponse` 一字不改：`success / agent_type / content / structured / fallback_used / error_msg / metadata`。前端只认这一套。

### 5.2 路由规则

统一入口 `api/v1/chat.py` 四步，与课件 8.4/8.5 一致：

1. **规则前置拦截**（零 Token）：把"生成新章节""续写""改写这段""帮我审稿"这类明确的写作指令直接路由，不花模型调用去猜。
2. **LLM 路由**：真正含糊的输入（"帮我看看这段""这段是不是有点平"）交给 LLM 判类，失败默认落到 `style_qa`。
3. **推 `routing_decision` 事件**：前端显示"已切换到写作 / 风格问答 / 审稿"。
4. **分发**：`writing` 走流式，`consistency` 走进度条，`style_qa` 走 token 流。

澄清分支（CLARIFY）：输入既不像写作指令也不像提问时，反问一句并给出三个可点选项（写新章 / 问设定 / 审稿），与课件的 clarify 完全一致。

## 6. 记忆与线程

只有 `style_qa` 挂 checkpointer（多轮问答需要上下文），`writing` 与 `consistency` 是一次性任务，不挂——这与课件"简历 Agent 不传 checkpointer、QA 传 MemorySaver"的判断标准相同。

记忆压缩用现有 `summarizer`：超过阈值（默认 30000 字符）时先压缩再进 State。`thread_id` 与 `session_id` 一一对应，换会话即换线程，不做跨会话记忆，因为本地写作工具不需要"记住你上周问过什么"，且避免隐私问题。

## 7. 与课件章节的对应表

| Flora 图/组件 | 课件出处 | 迁移要点 |
| --- | --- | --- |
| WritingState / 八节点 | 4.2 State 与数据模型、4.7 持久化与图装配 | 直线图 + 条件边的混合形态 |
| 预算中断点 | 6.9 Human-in-the-Loop | `interrupt()` 换决策内容 |
| StyleQAState / 四分支 | 5.11–5.15 State、节点、图装配 | 检索后端换适配器 |
| 低置信入队 | 5.14 节点③生成与入队 | 新表 `style_pending_questions` |
| ConsistencyAgent 并行四维 | 4.5 六维度并行评审 | 维度从"简历"换成"设定" |
| Orchestrator 双模式 | 8.2 单 Agent 直达、8.3 Pipeline | Pipeline 换成"写→审" |
| 统一入口四步 | 8.4 前置拦截与 LLM 路由、8.5 SSE 分发 | 事件名保留 Flora 风格 |
| 三层兜底 | 3.5 三层兜底与重试 | 降级文案换成写作场景 |
| 幂等迁移 | 3.2 数据库设计与建表 | 方言换 SQLite，机制不变 |

## 8. 验收标准

- 三张图都能在**不启动服务、不配 API Key** 的情况下 `build_*_graph()` 编译通过，并打印节点列表（课件也是这么自测的）；
- 用假模型（返回固定文本）跑通写作图全程，事件序列与第 2.5 节表格逐条对应；
- 切断 API Key 后，`writing` 能落到第三层兜底并正常结束 SSE；
- `style_qa` 在无向量模型时仍能出结果（纯 Style 降级），这是现有能力，不允许退化；
- 写 → 审 的 Pipeline 能一次调用跑完两步，且前一步的 `record_id` 出现在后一步的 `context` 里。
