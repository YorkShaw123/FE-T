"""风格语料库的读写（异步版）。

从 ``style_rag_service`` 的导入链路平移而来，关键顺序一字未改：
**必须先删 FTS5 再删 style_chunks**。否则 ORM 的 autoflush 会提前删主表，
FTS 里残留旧 rowid，新切片复用 id 后插入 FTS 会撞主键。

"索引"这一步在桌面端只做本地特征与签名，不产出向量：
语义向量需要 embedding 运行时，属于可选增强，缺失时检索走纯 Style 路径。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import STYLE_CORPUS_MAX_CHUNKS
from backend.core.exceptions import GenerationError
from backend.db.models import StyleChunk, StyleCorpus
from backend.services.style_chunk_service import split_corpus_text
from backend.services.style_feature_service import STYLE_FEATURE_VERSION
from backend.services.style_signature_service import (
    build_signature_vocabulary,
    signature_payload,
)
from backend.services.style_tagging import rule_tag_chunk
from backend.services.style_window_service import iter_style_window_analyses

SIGNATURE_VERSION = 1
LOCAL_INDEX_BACKEND = 'local-feature'


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def content_hash(text_value: str | None) -> str:
    import hashlib

    return hashlib.sha256((text_value or '').encode('utf-8')).hexdigest()


async def _fts_available(session: AsyncSession) -> bool:
    row = (await session.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'style_chunks_fts'"
    ))).first()
    return row is not None


async def _drop_fts_rows(session: AsyncSession, corpus_id: int) -> None:
    if not await _fts_available(session):
        return
    await session.execute(text(
        'DELETE FROM style_chunks_fts WHERE rowid IN '
        '(SELECT id FROM style_chunks WHERE corpus_id = :cid)'
    ), {'cid': corpus_id})


# ── 语料库 CRUD ──────────────────────────────────────────

async def create_corpus(
    session: AsyncSession,
    name: str,
    description: str = '',
) -> StyleCorpus:
    name = (name or '').strip()
    if not name:
        raise GenerationError('语料库名称不能为空')
    corpus = StyleCorpus(name=name, description=(description or '').strip())
    session.add(corpus)
    await session.flush()
    return corpus


async def get_corpus(session: AsyncSession, corpus_id: int) -> StyleCorpus:
    corpus = await session.get(StyleCorpus, corpus_id)
    if not corpus:
        raise GenerationError('语料库不存在')
    return corpus


async def list_corpora(session: AsyncSession) -> list[StyleCorpus]:
    return list((await session.execute(
        select(StyleCorpus).order_by(StyleCorpus.id.desc())
    )).scalars().all())


async def update_corpus(
    session: AsyncSession,
    corpus_id: int,
    name: str | None = None,
    description: str | None = None,
) -> StyleCorpus:
    corpus = await get_corpus(session, corpus_id)
    if name is not None:
        name = str(name).strip()
        if not name:
            raise GenerationError('语料库名称不能为空')
        corpus.name = name
    if description is not None:
        corpus.description = str(description).strip()
    corpus.updated_at = utcnow()
    await session.flush()
    return corpus


async def delete_corpus(session: AsyncSession, corpus_id: int) -> None:
    corpus = await get_corpus(session, corpus_id)
    await _drop_fts_rows(session, corpus_id)
    await session.execute(delete(StyleChunk).where(StyleChunk.corpus_id == corpus_id))
    await session.delete(corpus)
    await session.flush()


# ── 导入与切片 ───────────────────────────────────────────

async def import_corpus_text(
    session: AsyncSession,
    corpus_id: int,
    content: str,
    filename: str = '',
) -> int:
    corpus = await get_corpus(session, corpus_id)
    content = (content or '').strip()
    if not content:
        raise GenerationError('导入内容为空')

    chunks = split_corpus_text(content)
    if not chunks:
        raise GenerationError('未能从文本中切分出有效片段')
    if len(chunks) > STYLE_CORPUS_MAX_CHUNKS:
        raise GenerationError(
            f'单个语料库最多 {STYLE_CORPUS_MAX_CHUNKS} 个片段，请拆分后导入'
        )

    # 顺序很重要：先删 FTS，再删主表（见模块 docstring）
    fts_available = await _fts_available(session)
    await _drop_fts_rows(session, corpus_id)
    await session.execute(delete(StyleChunk).where(StyleChunk.corpus_id == corpus_id))

    now = utcnow()
    article_key = content_hash(content)
    inserted: list[StyleChunk] = []
    for index, chunk_text in enumerate(chunks):
        tag = rule_tag_chunk(chunk_text)
        chunk = StyleChunk(
            corpus_id=corpus_id,
            content=chunk_text,
            content_hash=content_hash(chunk_text),
            article_key=article_key,
            source_order=index,
            char_count=len(chunk_text),
            scene_type=tag['scene_type'],
            pacing=tag['pacing'],
            pov=tag['pov'],
            emotion=tag['emotion'],
            dialogue_ratio=tag['dialogue_ratio'],
            created_at=now,
        )
        session.add(chunk)
        await session.flush()  # 取到 id 供 FTS rowid 使用
        if fts_available:
            await session.execute(text(
                'INSERT INTO style_chunks_fts(rowid, content) VALUES (:rid, :content)'
            ), {'rid': chunk.id, 'content': chunk_text})
        inserted.append(chunk)

    # Style Window 特征：以邻接窗口为单位计算，存入每个片段
    for analysis in iter_style_window_analyses(inserted):
        chunk = analysis.source
        chunk.style_feature_version = STYLE_FEATURE_VERSION
        chunk.style_features_json = json.dumps(
            analysis.features, ensure_ascii=False, separators=(',', ':')
        )
        chunk.style_window_valid_chars = analysis.valid_char_count
        chunk.style_confidence = analysis.confidence['score']
        chunk.style_window_start_order = analysis.start_order
        chunk.style_window_end_order = analysis.end_order

    corpus.source_filename = filename or corpus.source_filename
    corpus.total_chars = len(content)
    corpus.chunk_count = len(inserted)
    corpus.index_status = 'imported'
    corpus.embedding_model = ''
    corpus.embedding_backend = ''
    corpus.embedding_model_version = ''
    corpus.embedding_dim = 0
    corpus.signature_version = 0
    corpus.updated_at = now
    await session.flush()
    return len(inserted)


async def list_chunks(
    session: AsyncSession,
    corpus_id: int,
    page: int = 1,
    per_page: int = 50,
) -> tuple[StyleCorpus, list[StyleChunk], int]:
    corpus = await get_corpus(session, corpus_id)
    total = (await session.execute(
        select(func.count()).select_from(StyleChunk).where(StyleChunk.corpus_id == corpus_id)
    )).scalar_one()
    items = (await session.execute(
        select(StyleChunk)
        .where(StyleChunk.corpus_id == corpus_id)
        .order_by(StyleChunk.source_order)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()
    return corpus, list(items), total


async def clear_corpus_chunks(session: AsyncSession, corpus_id: int) -> None:
    corpus = await get_corpus(session, corpus_id)
    await _drop_fts_rows(session, corpus_id)
    await session.execute(delete(StyleChunk).where(StyleChunk.corpus_id == corpus_id))
    corpus.chunk_count = 0
    corpus.total_chars = 0
    corpus.index_status = 'empty'
    corpus.embedding_model = ''
    corpus.embedding_backend = ''
    corpus.embedding_model_version = ''
    corpus.embedding_dim = 0
    corpus.signature_version = 0
    corpus.updated_at = utcnow()
    await session.flush()


# ── 本地索引 ─────────────────────────────────────────────

async def index_corpus_local(
    session: AsyncSession,
    corpus_id: int,
    progress_callback=None,
) -> int:
    """构建本地特征与签名，不产出语义向量。

    签名用受限功能词表对整个语料建词表，再给每个片段生成稀疏表示；
    它和向量是两回事——向量依赖 embedding 运行时，签名纯本地可算。
    """
    corpus = await get_corpus(session, corpus_id)
    chunks = list((await session.execute(
        select(StyleChunk)
        .where(StyleChunk.corpus_id == corpus_id)
        .order_by(StyleChunk.source_order)
    )).scalars().all())
    if not chunks:
        raise GenerationError('语料库还没有可索引的片段，请先导入文本')

    vocabulary = build_signature_vocabulary([chunk.content for chunk in chunks])
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        chunk.style_signature_json = signature_payload(chunk.content, vocabulary)
        chunk.style_signature_version = SIGNATURE_VERSION
        if progress_callback is not None:
            progress_callback(index, total)

    corpus.index_status = 'indexed'
    corpus.embedding_backend = LOCAL_INDEX_BACKEND
    corpus.embedding_model = ''
    corpus.embedding_model_version = ''
    corpus.embedding_dim = 0
    corpus.signature_version = SIGNATURE_VERSION
    corpus.updated_at = utcnow()
    await session.flush()
    return total


async def corpus_stats(session: AsyncSession, corpus_id: int) -> dict[str, Any]:
    corpus = await get_corpus(session, corpus_id)
    return corpus.to_dict()
