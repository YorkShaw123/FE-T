"""写作图的风格参考检索（接回 KBBackend）。

P2 这里是占位；现在换成 ``core/knowledge_base`` 的真实实现。
写作图只需要"给我几段参考 + 检索元信息"，底下是本地 SQLite 还是 Milvus 与它无关。
"""

from __future__ import annotations

from typing import Any

from backend.core.knowledge_base import get_kb_backend


async def retrieve_reference_excerpts(
    *,
    query_text: str,
    corpus_ids: list[int],
    scene_type: str,
    top_k: int = 3,
    api_key: str = '',
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    backend = get_kb_backend()
    return await backend.search(
        query_text=query_text,
        corpus_ids=list(corpus_ids or []),
        scene_type=scene_type,
        top_k=top_k,
        api_key=api_key,
    )
