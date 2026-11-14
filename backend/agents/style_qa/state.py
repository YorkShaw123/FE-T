"""风格问答图的状态。"""

from __future__ import annotations

from typing import Any, TypedDict


class StyleQAState(TypedDict, total=False):
    # ── 入参 ─────────────────────────────────────────────
    user_id: str
    session_id: str
    user_message: str
    messages: list[dict[str, str]]
    corpus_ids: list[int]
    scene_type: str
    api_key: str
    provider: str | None
    model: str | None

    # ── 过程 ─────────────────────────────────────────────
    query_type: str            # PRECISE / VAGUE / BROAD / GENERAL
    hyde_doc: str
    rewritten_queries: list[str]
    chunks: list[dict[str, Any]]
    confidence: float
    is_high_confidence: bool
    sources: list[str]
    pending_enqueued: bool
    errors: list[str]

    # ── 产出 ─────────────────────────────────────────────
    answer: str
    answer_mode: str           # rag / direct / general
