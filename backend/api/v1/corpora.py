"""风格语料库路由（15 个端点）。

旧前缀 ``/api/style-corpora`` 保留为别名，新前缀 ``/api/v1/corpora``。
检索测试端点直接走 ``KBBackend``，与写作图的 06 风格参考用同一套检索，
避免"调试时看到的排序"和"生成时用的排序"不是一回事。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    get_settings,
)
from backend.core.document_text import extract_uploaded_bytes
from backend.core.knowledge_base import get_kb_backend
from backend.core.progress import (
    fail_index_progress,
    finish_index_progress,
    get_index_progress,
    start_index_progress,
    update_index_progress,
)
from backend.dependencies import get_db
from backend.services import corpus_service as svc

router = APIRouter()

LOCAL_MODEL_ID = 'BAAI/bge-small-zh-v1.5'
LOCAL_MODEL_VERSION = 'v1.5-onnx'


class CorpusCreate(BaseModel):
    model_config = ConfigDict(extra='ignore')

    name: str = ''
    description: str = ''


class CorpusUpdate(BaseModel):
    model_config = ConfigDict(extra='ignore')

    name: str | None = None
    description: str | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')

    query_text: str = ''
    corpus_ids: list[int] | None = None
    scene_type: str | None = None
    pacing: str | None = None
    pov: str | None = None
    top_k: int = 3
    api_key: str = ''
    provider: str = 'siliconflow'


def _local_model_installed() -> bool:
    model_dir = get_settings().resolved_models_dir / 'bge-small-zh-v1.5'
    return (model_dir / 'model.onnx').exists()


def _local_status() -> dict[str, Any]:
    installed = _local_model_installed()
    return {
        'installed': installed,
        'model': LOCAL_MODEL_ID,
        'model_version': LOCAL_MODEL_VERSION,
        'dimensions': 512,
        'runtime': 'onnxruntime-cpu',
        'model_dir': str(get_settings().resolved_models_dir / 'bge-small-zh-v1.5'),
        'message': (
            '本地 ONNX 模型已就绪'
            if installed
            else '本地模型未安装：检索会自动退化为纯 Style 路径，不影响使用'
        ),
    }


# ── Embedding 配置与模型状态 ──────────────────────────────

@router.get('/v1/corpora/embedding-config', tags=['文风语料'])
@router.get('/style-corpora/embedding-config', tags=['文风语料'], include_in_schema=False)
async def embedding_config() -> dict[str, Any]:
    return {'success': True, 'data': {
        'provider': EMBEDDING_PROVIDER,
        'model': EMBEDDING_MODEL,
        'dimensions': EMBEDDING_DIMENSIONS,
        'default_backend': 'local',
        'remote_compatible': True,
        'local': {
            'model': LOCAL_MODEL_ID,
            'model_version': LOCAL_MODEL_VERSION,
            'dimensions': 512,
            'runtime': 'onnxruntime-cpu',
            'bundled': False,
            'installed': _local_model_installed(),
        },
    }}


@router.get('/v1/corpora/embedding/status', tags=['文风语料'])
@router.get(
    '/style-corpora/embedding-model/status',
    tags=['文风语料'],
    include_in_schema=False,
)
async def embedding_model_status() -> dict[str, Any]:
    return {'success': True, 'data': _local_status()}


@router.post('/v1/corpora/embedding/install', tags=['文风语料'])
@router.post(
    '/style-corpora/embedding-model/install',
    tags=['文风语料'],
    include_in_schema=False,
)
async def install_embedding_model() -> dict[str, Any]:
    status = _local_status()
    return {'success': True, 'data': {
        **status,
        'started': False,
        'manual_install': not status['installed'],
    }}


@router.get('/v1/corpora/embedding/install-progress', tags=['文风语料'])
@router.get(
    '/style-corpora/embedding-model/install-progress',
    tags=['文风语料'],
    include_in_schema=False,
)
async def install_progress() -> dict[str, Any]:
    return {'success': True, 'data': {
        'status': 'manual',
        'message': '本地向量模型请在项目根目录执行 scripts\\install-local-embedding.ps1 安装',
    }}


# ── 语料库 CRUD ──────────────────────────────────────────

@router.get('/v1/corpora', tags=['文风语料'])
@router.get('/style-corpora', tags=['文风语料'], include_in_schema=False)
async def list_corpus(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    corpora = await svc.list_corpora(db)
    return {'success': True, 'data': [item.to_dict() for item in corpora]}


@router.post('/v1/corpora', tags=['文风语料'], status_code=201)
@router.post('/style-corpora', tags=['文风语料'], status_code=201, include_in_schema=False)
async def create_corpus(
    payload: CorpusCreate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corpus = await svc.create_corpus(db, payload.name, payload.description)
    return {'success': True, 'data': corpus.to_dict()}


@router.get('/v1/corpora/{corpus_id}', tags=['文风语料'])
@router.get('/style-corpora/{corpus_id}', tags=['文风语料'], include_in_schema=False)
async def get_corpus(corpus_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    try:
        corpus = await svc.get_corpus(db, corpus_id)
    except Exception as exc:
        return JSONResponse(status_code=404, content={'success': False, 'error': str(exc)})
    return {'success': True, 'data': corpus.to_dict()}


@router.put('/v1/corpora/{corpus_id}', tags=['文风语料'])
@router.put('/style-corpora/{corpus_id}', tags=['文风语料'], include_in_schema=False)
async def update_corpus(
    corpus_id: int,
    payload: CorpusUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    corpus = await svc.update_corpus(
        db, corpus_id, name=payload.name, description=payload.description
    )
    return {'success': True, 'data': corpus.to_dict()}


@router.delete('/v1/corpora/{corpus_id}', tags=['文风语料'])
@router.delete('/style-corpora/{corpus_id}', tags=['文风语料'], include_in_schema=False)
async def delete_corpus(corpus_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await svc.delete_corpus(db, corpus_id)
    return {'success': True}


# ── 导入 / 切片 / 索引 ───────────────────────────────────

@router.post('/v1/corpora/{corpus_id}/import', tags=['文风语料'])
@router.post('/style-corpora/{corpus_id}/import', tags=['文风语料'], include_in_schema=False)
async def import_corpus(
    corpus_id: int,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> Any:
    filename = file.filename or ''
    try:
        raw = await file.read()
        content = extract_uploaded_bytes(raw, filename)
    except OverflowError as exc:
        return JSONResponse(status_code=413, content={'success': False, 'error': str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={'success': False, 'error': str(exc)})

    count = await svc.import_corpus_text(db, corpus_id, content, filename=filename)
    corpus = await svc.get_corpus(db, corpus_id)
    return {'success': True, 'data': {
        'chunk_count': count,
        'total_chars': corpus.total_chars,
        'corpus': corpus.to_dict(),
    }}


@router.get('/v1/corpora/{corpus_id}/chunks', tags=['文风语料'])
@router.get('/style-corpora/{corpus_id}/chunks', tags=['文风语料'], include_in_schema=False)
async def list_chunks(
    corpus_id: int,
    page: int = 1,
    per_page: int = 50,
    db: AsyncSession = Depends(get_db),
) -> Any:
    per_page = min(max(per_page, 1), 200)
    try:
        corpus, items, total = await svc.list_chunks(db, corpus_id, page=page, per_page=per_page)
    except Exception as exc:
        return JSONResponse(status_code=404, content={'success': False, 'error': str(exc)})
    return {'success': True, 'data': {
        'corpus': corpus.to_dict(),
        'total': total,
        'page': page,
        'per_page': per_page,
        'items': [item.to_dict() for item in items],
    }}


@router.post('/v1/corpora/{corpus_id}/index', tags=['文风语料'])
@router.post('/style-corpora/{corpus_id}/index', tags=['文风语料'], include_in_schema=False)
async def index_corpus(corpus_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    try:
        corpus = await svc.get_corpus(db, corpus_id)
        start_index_progress(corpus_id, corpus.chunk_count)
        count = await svc.index_corpus_local(
            db,
            corpus_id,
            progress_callback=lambda completed, total: update_index_progress(
                corpus_id, completed, total
            ),
        )
        finish_index_progress(corpus_id, count)
    except Exception as exc:
        fail_index_progress(corpus_id, str(exc))
        return JSONResponse(status_code=400, content={'success': False, 'error': str(exc)})

    corpus = await svc.get_corpus(db, corpus_id)
    return {'success': True, 'data': {
        'indexed_count': count,
        'corpus': corpus.to_dict(),
        'note': '本次索引为本地特征与签名，未生成语义向量',
    }}


@router.get('/v1/corpora/{corpus_id}/index-progress', tags=['文风语料'])
@router.get(
    '/style-corpora/{corpus_id}/index-progress',
    tags=['文风语料'],
    include_in_schema=False,
)
async def index_progress(corpus_id: int) -> dict[str, Any]:
    progress = get_index_progress(corpus_id)
    if progress is None:
        return {'success': True, 'data': {
            'corpus_id': corpus_id,
            'status': 'idle',
            'completed': 0,
            'total': 0,
            'percent': 0.0,
            'elapsed_seconds': 0.0,
            'estimated_remaining_seconds': None,
            'message': '尚未开始索引',
        }}
    return {'success': True, 'data': progress}


@router.post('/v1/corpora/{corpus_id}/clear', tags=['文风语料'])
@router.post('/style-corpora/{corpus_id}/clear', tags=['文风语料'], include_in_schema=False)
async def clear_corpus(corpus_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await svc.clear_corpus_chunks(db, corpus_id)
    return {'success': True}


# ── 检索测试 ─────────────────────────────────────────────

@router.post('/v1/corpora/search', tags=['文风语料'])
@router.post('/style-corpora/search', tags=['文风语料'], include_in_schema=False)
async def search_corpus(payload: SearchRequest) -> dict[str, Any]:
    backend = get_kb_backend()
    items, meta = await backend.search(
        query_text=payload.query_text,
        corpus_ids=payload.corpus_ids,
        scene_type=payload.scene_type,
        top_k=max(1, min(int(payload.top_k or 3), 20)),
        api_key=payload.api_key,
        provider=payload.provider,
    )
    return {'success': True, 'data': {'items': items, 'meta': meta}}
