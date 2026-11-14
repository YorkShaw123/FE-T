"""知识库门面：把"检索"抽象成一个接口，桌面端与云端各用各的实现。

``KBBackend`` 是协议，``LocalKB`` 是桌面端默认实现（SQLite + FTS5 + NumPy）。
将来接 Milvus 时新增一个实现即可，写作图与风格问答图都不需要改。

打分口径沿用 ``style_retrieval_service.final_retrieval_score``：
场景 0.25 / 词汇 0.25 有真实信号，语义依赖向量索引，风格分依赖统计画像。
当前阶段画像尚未迁移，``style_score`` 固定为 0 —— 它是常数项，只压低总分绝对值，
不改变排序，并在 ``meta['signals']`` 里如实标注缺哪一路信号。
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import text

from backend.db import session_scope
from backend.core.logger import get_logger
from backend.services.style_retrieval_service import (
    content_diversity_similarity,
    content_leakage_metrics,
    final_retrieval_score,
    scene_similarity,
)

logger = get_logger(__name__)

# 单次检索最多加载的候选片段数，避免百万字语料一次性进内存
MAX_CANDIDATES = 5000
# 参与重排的候选数（与原实现 SEARCH_RERANK_LIMIT 一致）
RERANK_LIMIT = 60
# BM25 单路召回上限
BM25_LIMIT = 60


@runtime_checkable
class KBBackend(Protocol):
    """检索后端协议。"""

    async def search(
        self,
        *,
        query_text: str,
        corpus_ids: list[int] | None = None,
        scene_type: str | None = None,
        top_k: int = 3,
        api_key: str = '',
        provider: str = 'siliconflow',
        mmr_lambda: float = 0.7,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        ...


def _mmr_rerank_lazy(
    candidates: list[tuple[int, float]],
    similarity_fn,
    lambda_: float = 0.7,
    top_k: int = 3,
) -> list[tuple[int, float]]:
    """仅计算实际参与 MMR 选择的候选对，避免预建完整 N×N 相似度矩阵。"""
    selected: list[tuple[int, float]] = []
    pool = candidates[:]
    while len(selected) < top_k and pool:
        best_index, best_score = None, -float('inf')
        for index, (chunk_id, relevance) in enumerate(pool):
            diversity_penalty = max(
                (similarity_fn(chosen_id, chunk_id) for chosen_id, _score in selected),
                default=0.0,
            )
            score = lambda_ * relevance - (1 - lambda_) * diversity_penalty
            if score > best_score:
                best_index, best_score = index, score
        if best_index is None:
            break
        selected.append(pool.pop(best_index))
    return selected


def build_fts_match(query_text: str) -> str | None:
    """把查询拆成 3~12 字的短语，用 OR 连接（trigram 分词下 AND 过于苛刻）。"""
    cleaned = re.sub(r'[\s，。！？；：、,.!?;:"“”‘’()（）\[\]{}<>]+', ' ', query_text or '').strip()
    words = [word for word in cleaned.split(' ') if len(word) >= 3]
    if not words:
        return None

    pieces: list[str] = []
    for word in words:
        if len(word) <= 12:
            pieces.append(word)
        else:
            pieces.extend(word[i:i + 8] for i in range(0, len(word), 8))
    pieces = list(dict.fromkeys(pieces))[:10]
    return ' OR '.join(f'"{piece}"' for piece in pieces)


class LocalKB:
    """桌面端默认检索器：SQLite 存片段，FTS5 做词汇检索，numpy 留给向量路。"""

    def __init__(self, max_candidates: int = MAX_CANDIDATES) -> None:
        self.max_candidates = max_candidates

    async def search(
        self,
        *,
        query_text: str,
        corpus_ids: list[int] | None = None,
        scene_type: str | None = None,
        top_k: int = 3,
        api_key: str = '',
        provider: str = 'siliconflow',
        mmr_lambda: float = 0.7,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        del provider  # 语义路尚未接入，保留参数以对齐接口
        query_text = (query_text or '').strip()
        if not query_text:
            raise ValueError('检索文本不能为空')

        requested_scene = scene_type if scene_type not in (None, '', 'auto') else None

        async with session_scope() as session:
            chunks = await self._load_candidates(
                session, corpus_ids=corpus_ids, scene=requested_scene
            )
            relaxed = False
            if requested_scene and len(chunks) < top_k:
                relaxed = True
                chunks = await self._load_candidates(session, corpus_ids=corpus_ids, scene=None)

            if not chunks:
                return [], {'mode': 'empty', 'reason': '无满足过滤条件的片段', 'signals': []}

            chunk_by_id = {row['id']: row for row in chunks}
            bm25 = await self._bm25(session, query_text, list(chunk_by_id.keys()))

        corpus_used = sorted({row['corpus_id'] for row in chunks})
        ranked = sorted(bm25, key=lambda cid: -bm25[cid])
        lexical_scores = {
            chunk_id: 1.0 - rank / max(1, len(ranked))
            for rank, chunk_id in enumerate(ranked)
        }

        scored: list[tuple[int, float]] = []
        details: dict[int, dict[str, Any]] = {}
        for chunk in chunks:
            lexical = lexical_scores.get(chunk['id'], 0.0)
            scene = scene_similarity(chunk['scene_type'], requested_scene)
            leakage = content_leakage_metrics(query_text, chunk['content'])
            total = final_retrieval_score(
                style_score=0.0,  # 统计画像尚未迁移，常数项不影响排序
                scene_score=scene,
                semantic_score=None,  # 无向量索引时语义路缺失
                lexical_score=lexical,
                leakage_penalty=leakage['content_overlap_penalty'],
            )
            details[chunk['id']] = {
                'scene_score': round(scene, 6),
                'lexical_score': round(lexical, 6),
                'semantic_score': None,
                'style_score': 0.0,
                **leakage,
                'total_score': total,
            }
            scored.append((chunk['id'], total))

        scored.sort(key=lambda item: (-item[1], item[0]))
        candidates = scored[:RERANK_LIMIT]

        def similarity(left_id: int, right_id: int) -> float:
            if left_id == right_id:
                return 1.0
            return content_diversity_similarity(
                chunk_by_id[left_id]['content'], chunk_by_id[right_id]['content']
            )

        selected = _mmr_rerank_lazy(candidates, similarity, lambda_=mmr_lambda, top_k=top_k)

        items: list[dict[str, Any]] = []
        for chunk_id, total in selected:
            chunk = chunk_by_id[chunk_id]
            items.append({
                'chunk_id': chunk_id,
                'corpus_id': chunk['corpus_id'],
                'content': chunk['content'],
                'score': round(total, 6),
                'scene_type': chunk['scene_type'],
                'pacing': chunk['pacing'],
                'pov': chunk['pov'],
                'emotion': chunk['emotion'],
                'char_count': chunk['char_count'],
                'source': chunk['corpus_name'] or f"语料库 {chunk['corpus_id']}",
                'details': details[chunk_id],
            })

        meta = {
            'mode': 'local_style',
            'signals': ['scene', 'lexical', 'leakage'],
            'missing_signals': ['semantic', 'style_profile'],
            'candidates': len(chunks),
            'corpus_ids': corpus_used,
            'relaxed_scene': relaxed,
            'requested_scene': requested_scene,
            'api_key_present': bool(api_key),
            'cache_hit': False,
        }
        logger.info(
            'kb.search_done',
            candidates=len(chunks),
            selected=len(items),
            relaxed=relaxed,
        )
        return items, meta

    async def _load_candidates(
        self,
        session,
        *,
        corpus_ids: list[int] | None,
        scene: str | None,
    ) -> list[dict[str, Any]]:
        conditions = ['c.is_enabled = 1']
        params: dict[str, Any] = {'limit': self.max_candidates + 1}
        if corpus_ids:
            names = []
            for index, corpus_id in enumerate(sorted({int(item) for item in corpus_ids})):
                names.append(f':cid_{index}')
                params[f'cid_{index}'] = corpus_id
            conditions.append(f"c.corpus_id IN ({', '.join(names)})")
        if scene:
            conditions.append('c.scene_type = :scene')
            params['scene'] = scene

        rows = (await session.execute(text(
            'SELECT c.id, c.corpus_id, c.content, c.char_count, c.scene_type, c.pacing, '
            'c.pov, c.emotion, s.name AS corpus_name '
            'FROM style_chunks AS c LEFT JOIN style_corpora AS s ON s.id = c.corpus_id '
            f"WHERE {' AND '.join(conditions)} "
            'ORDER BY c.id LIMIT :limit'
        ), params)).mappings().all()

        if len(rows) > self.max_candidates:
            raise ValueError(
                f'检索候选超过 {self.max_candidates} 个，请选择更少的语料库或增加过滤条件'
            )
        return [dict(row) for row in rows]

    async def _bm25(
        self,
        session,
        query_text: str,
        chunk_ids: list[int],
    ) -> dict[int, float]:
        match_expr = build_fts_match(query_text)
        if not match_expr or not chunk_ids:
            return {}

        ids = {}
        for index, chunk_id in enumerate(chunk_ids):
            ids[f'id_{index}'] = chunk_id
        placeholders = ', '.join(f':{name}' for name in ids)

        try:
            rows = (await session.execute(text(
                'SELECT f.rowid, bm25(style_chunks_fts) FROM style_chunks_fts AS f '
                f"WHERE style_chunks_fts MATCH :q AND f.rowid IN ({placeholders}) "
                'ORDER BY bm25(style_chunks_fts) LIMIT :limit'
            ), {'q': match_expr, 'limit': BM25_LIMIT, **ids})).fetchall()
        except Exception as exc:  # FTS5 不可用时退化为纯场景排序
            logger.warning('kb.fts_unavailable', error=str(exc))
            return {}

        # bm25() 越小越相关，取负转成越大越好
        return {int(row[0]): -float(row[1]) for row in rows}


_local_kb: LocalKB | None = None


def get_kb_backend() -> KBBackend:
    """当前检索后端（桌面端固定本地实现；云端版可换成 Milvus 实现）。"""
    global _local_kb
    if _local_kb is None:
        _local_kb = LocalKB()
    return _local_kb


def reset_kb_backend() -> None:
    global _local_kb
    _local_kb = None
