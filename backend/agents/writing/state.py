"""写作图的状态定义。

分三组：入参（来自请求，图内只读）、过程（节点之间传递）、产出（落库与返回）。
字段与原 ``GenerationRequest`` 一一对应，没有新增语义。
"""

from __future__ import annotations

from typing import Any, TypedDict


class WritingState(TypedDict, total=False):
    # ── 入参组 ───────────────────────────────────────────
    templates: list[dict[str, Any]]
    template_ids: list[int]
    previous_article: str
    title: str
    api_key: str
    provider: str
    model: str
    thinking_enabled: bool
    reasoning_effort: str
    max_tokens: int
    sampling: dict[str, Any]
    custom_prefix: str
    custom_suffix: str
    deai_enabled: bool
    deai_prompt: str
    style_reference_enabled: bool
    style_mode: str
    style_strength: str
    scene_type: str
    style_corpus_ids: list[int]
    embedding_api_key: str
    structured_prompt_enabled: bool
    stream: bool

    # ── 过程组 ───────────────────────────────────────────
    messages: list[dict[str, str]]
    assembled_prompt: str
    token_budget: dict[str, Any]
    style_metadata: dict[str, Any]
    reference_excerpts: list[dict[str, Any]]
    style_rewrite_status: str
    errors: list[str]
    fallback_used: bool
    prompt_route: str

    # ── 产出组 ───────────────────────────────────────────
    story_content: str
    reasoning_content: str
    deai_content: str
    style_reference_content: str
    final_content: str
    finish_reason: str | None
    sampling_dropped: list[str]
    record_id: int | None
