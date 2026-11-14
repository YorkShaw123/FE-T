"""风格参考检索的接入位。

P3 会把这里换成 ``adapters/kb_local`` 的真实混合检索（BM25 + 向量 + RRF + MMR +
内容泄漏惩罚）。现在返回"无片段"，让写作图能完整跑通、并在事件里如实说明原因，
而不是伪造参考片段。
"""

from __future__ import annotations

from typing import Any


async def retrieve_reference_excerpts(
    *,
    query_text: str,
    corpus_ids: list[int],
    scene_type: str,
    top_k: int = 3,
    api_key: str = '',
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return [], {
        'mode': 'unavailable',
        'reason': '风格检索适配层尚未接入（P3）',
        'corpus_ids': list(corpus_ids or []),
        'scene_type': scene_type,
        'query_chars': len(query_text or ''),
        'top_k': top_k,
        'api_key_present': bool(api_key),
    }
