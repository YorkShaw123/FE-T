"""
Style RAG 服务：海量风格语料的切片、规则打标、向量化与混合检索。

核心链路：
[导入百万字语料] -> [语义切片(200~900字)] -> [规则打标(scene/pacing/pov)]
    -> [Embedding API 向量化] -> [SQLite BLOB + NumPy 矩阵 + FTS5(BM25)]
生成时：
[写作上下文] -> [硬过滤(标签)] -> [向量余弦 Top-N] -> [FTS5 BM25 Top-N]
    -> [RRF 融合] -> [MMR 多样性重排] -> [3~5 个风格示范片段]

设计约束：
- 不引入向量数据库（避免 PyInstaller 体积暴涨与杀软误报）；
  4000×1024 float32 矩阵仅 16MB 内存，纯 NumPy 余弦计算毫秒级。
- 向量存 SQLite BLOB；FTS5 用 trigram tokenizer 支持中文 BM25。
"""
import hashlib
import json
import re
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock

# 注意：numpy 为延迟导入（仅在向量化/向量检索时加载），避免拖慢后端启动。
from config import Config
from database import db
from database.models import AuthorStyleProfile, StyleCorpus, StyleChunk
from services.embedding_backends import (
    EmbeddingBackendError,
    EmbeddingBackendUnavailable,
    RemoteEmbeddingBackend,
    create_embedding_backend,
)
from services.author_style_profile_service import (
    build_author_style_profile,
    get_author_style_profile,
    merge_target_profiles,
    resolve_mode_profile,
)
from services.errors import GenerationError
from services.style_chunk_service import split_corpus_text
from services.style_feature_service import STYLE_FEATURE_VERSION
from services.style_window_service import iter_style_window_analyses
from services.style_retrieval_service import (
    content_diversity_similarity,
    content_leakage_metrics,
    final_retrieval_score,
    explain_style_feature_matches,
    scene_similarity,
    style_similarity_scores,
)


SCENE_TYPES = {'dialogue', 'action', 'psychology', 'environment', 'transition', 'narration', 'mixed'}
PACES = {'slow', 'medium', 'fast'}
SCENE_LABELS = {
    'dialogue': '对话', 'action': '动作', 'psychology': '心理',
    'environment': '环境', 'transition': '转场', 'narration': '叙述', 'mixed': '综合',
}
PACE_LABELS = {'slow': '舒缓', 'medium': '中等', 'fast': '紧凑'}

# ---------- 规则打标关键词库（零成本，不依赖 LLM） ----------
_SCENE_KEYWORDS = {
    'dialogue': ('他说', '她说', '他道', '她道', '笑道', '问道', '回答', '开口', '台词', '说：', '道：', '低语', '喊道', '答道', '“', '”'),
    'action': ('战斗', '追逐', '逃跑', '袭击', '搏斗', '追杀', '拳头', '刀锋', '冲了', '扑向', '挥拳', '猛地', '闪身', '躲避', '厮杀'),
    'psychology': ('心理', '内心', '回忆', '思考', '犹豫', '梦境', '意识', '念头', '思绪', '盘算', '暗自', '觉得', '想道', '浮现', '纠结'),
    'environment': ('环境', '景色', '清晨', '黄昏', '夜晚', '房间', '街道', '天气', '月光', '雨水', '风声', '树影', '远山', '灯火', '窗帘'),
    'transition': ('转场', '数日后', '第二天', '多年后', '与此同时', '离开', '抵达', '回到', '转眼', '片刻后', '良久', '从此'),
}
_POV_PATTERNS = {
    '第一人称': ('我', '我们'),
    '第二人称': ('你', '你们'),
    '第三人称': ('他', '她', '他们', '她们'),
}
_EMOTION_KEYWORDS = {
    '愤怒': ('愤怒', '恼火', '怒', '恨', '咬牙切齿', '暴怒'),
    '悲伤': ('悲伤', '难过', '伤心', '泪', '哽咽', '哀', '痛'),
    '恐惧': ('恐惧', '害怕', '惊慌', '颤抖', '冷汗', '惊惧'),
    '紧张': ('紧张', '紧绷', '攥紧', '屏息', '心跳', '窒息'),
    '温柔': ('温柔', '轻柔', '轻声', '温和', '暖意'),
    '喜悦': ('喜悦', '笑', '开心', '雀跃', '欢喜', '愉快'),
    '压抑': ('压抑', '沉闷', '沉重', '窒息感', '阴郁', '窒息'),
    '宁静': ('宁静', '安静', '静谧', '安然', '平和'),
}

_EMOTION_LABELS = {
    '愤怒': '愤怒', '悲伤': '悲伤', '恐惧': '恐惧', '紧张': '紧张',
    '温柔': '温柔', '喜悦': '喜悦', '压抑': '压抑', '宁静': '宁静',
}
_EMOTION_ORDER = ['愤怒', '悲伤', '恐惧', '紧张', '温柔', '喜悦', '压抑', '宁静']


def _content_hash(content):
    return hashlib.sha256((content or '').encode('utf-8')).hexdigest()


def _dialogue_ratio(content):
    quoted = ''.join(re.findall(r'[“\"]([^”\"]+)[”\"]', content or ''))
    return round(min(1.0, len(quoted) / max(1, len(content or ''))), 3)


def _infer_scene_type(content):
    """关键词计数推断场景类型；命中为 0 时回退 mixed。"""
    scores = {}
    for key, words in _SCENE_KEYWORDS.items():
        scores[key] = sum(content.count(word) for word in words)
    winner = max(scores, key=scores.get)
    return winner if scores.get(winner, 0) > 0 else 'mixed'


def _infer_pacing(content):
    """按平均句长与标点密度推断节奏：<18 字/句为紧凑，>32 字/句为舒缓。"""
    sentences = [s for s in re.split(r'[。！？!?]', content or '') if s.strip()]
    if not sentences:
        return 'medium'
    avg = len(content) / len(sentences)
    if avg < 18:
        return 'fast'
    if avg > 32:
        return 'slow'
    return 'medium'


def _infer_pov(content):
    """按人称代词频次推断叙述视角（第一/第二/第三人称）。"""
    scores = {}
    for name, words in _POV_PATTERNS.items():
        scores[name] = sum(content.count(word) for word in words)
    winner = max(scores, key=scores.get)
    return winner if scores.get(winner, 0) > 0 else ''


def _infer_emotion(content):
    """情绪词计数，输出最多两个情绪标签（顿号连接）。"""
    hits = {}
    for name, words in _EMOTION_KEYWORDS.items():
        count = sum(content.count(word) for word in words)
        if count > 0:
            hits[name] = count
    if not hits:
        return ''
    top = sorted(hits, key=lambda key: -hits[key])[:2]
    return '、'.join(_EMOTION_LABELS[name] for name in top)


def rule_tag_chunk(content):
    """规则打标：推断 scene_type / pacing / pov / emotion / dialogue_ratio。"""
    return {
        'scene_type': _infer_scene_type(content),
        'pacing': _infer_pacing(content),
        'pov': _infer_pov(content),
        'emotion': _infer_emotion(content),
        'dialogue_ratio': _dialogue_ratio(content),
    }


def _now():
    return datetime.now(timezone.utc)


def _fts_available():
    row = db.session.execute(db.text(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'style_chunks_fts'"
    )).first()
    return row is not None


# ---------- 语料库 CRUD ----------

def create_corpus(name, description=''):
    name = (name or '').strip()
    if not name:
        raise GenerationError('语料库名称不能为空')
    corpus = StyleCorpus(name=name, description=(description or '').strip())
    db.session.add(corpus)
    db.session.commit()
    return corpus


def get_corpus(corpus_id):
    corpus = db.session.get(StyleCorpus, corpus_id)
    if not corpus:
        raise GenerationError('语料库不存在')
    return corpus


def list_corpora():
    return StyleCorpus.query.order_by(StyleCorpus.id.desc()).all()


def update_corpus(corpus_id, name=None, description=None):
    corpus = get_corpus(corpus_id)
    if name is not None:
        name = str(name).strip()
        if not name:
            raise GenerationError('语料库名称不能为空')
        corpus.name = name
    if description is not None:
        corpus.description = str(description).strip()
    corpus.updated_at = _now()
    db.session.commit()
    return corpus


def delete_corpus(corpus_id):
    corpus = get_corpus(corpus_id)
    # 先清理 FTS5 虚拟表（不受 ORM 级联管理）
    if _fts_available():
        db.session.execute(db.text(
            "DELETE FROM style_chunks_fts WHERE rowid IN "
            "(SELECT id FROM style_chunks WHERE corpus_id = :cid)"
        ), {'cid': corpus_id})
    db.session.execute(db.text(
        "DELETE FROM style_chunks WHERE corpus_id = :cid"
    ), {'cid': corpus_id})
    db.session.delete(corpus)
    db.session.commit()


# ---------- 导入与切片 ----------

def import_corpus_text(corpus_id, text, filename=''):
    """导入语料文本：切片 + 规则打标 + 写库 + 维护 FTS5。"""
    corpus = get_corpus(corpus_id)
    text = (text or '').strip()
    if not text:
        raise GenerationError('导入内容为空')
    chunks = split_corpus_text(text)
    if not chunks:
        raise GenerationError('未能从文本中切分出有效片段')
    if len(chunks) > Config.STYLE_CORPUS_MAX_CHUNKS:
        raise GenerationError(
            f'单个语料库最多 {Config.STYLE_CORPUS_MAX_CHUNKS} 个片段，请拆分后导入'
        )

    # 清空旧内容：必须先清理 FTS5（其 rowid 依赖 style_chunks.id），再删 style_chunks。
    # 若先执行 ORM delete，随后的 execute() 会触发 autoflush 提前删掉 style_chunks，
    # 导致 FTS 残留旧行，新切片 id 复用后插入 FTS 触发 rowid 冲突（IntegrityError）。
    fts_available = _fts_available()
    if fts_available:
        db.session.execute(db.text(
            "DELETE FROM style_chunks_fts WHERE rowid IN "
            "(SELECT id FROM style_chunks WHERE corpus_id = :cid)"
        ), {'cid': corpus_id})
    StyleChunk.query.filter_by(corpus_id=corpus_id).delete(synchronize_session=False)

    now = _now()
    article_key = _content_hash(text)
    inserted = []
    for index, content in enumerate(chunks):
        tag = rule_tag_chunk(content)
        chunk = StyleChunk(
            corpus_id=corpus_id,
            content=content,
            content_hash=_content_hash(content),
            article_key=article_key,
            source_order=index,
            char_count=len(content),
            scene_type=tag['scene_type'],
            pacing=tag['pacing'],
            pov=tag['pov'],
            emotion=tag['emotion'],
            dialogue_ratio=tag['dialogue_ratio'],
            created_at=now,
        )
        db.session.add(chunk)
        db.session.flush()  # 取得 chunk.id 供 FTS5 rowid 使用
        if fts_available:
            db.session.execute(db.text(
                "INSERT INTO style_chunks_fts(rowid, content) VALUES (:rid, :content)"
            ), {'rid': chunk.id, 'content': content})
        inserted.append(chunk)

    for analysis in iter_style_window_analyses(inserted):
        chunk = analysis.source
        chunk.style_feature_version = STYLE_FEATURE_VERSION
        chunk.style_features_json = json.dumps(analysis.features, ensure_ascii=False, separators=(',', ':'))
        chunk.style_window_valid_chars = analysis.valid_char_count
        chunk.style_confidence = analysis.confidence['score']
        chunk.style_window_start_order = analysis.start_order
        chunk.style_window_end_order = analysis.end_order

    corpus.source_filename = filename or corpus.source_filename
    corpus.total_chars = len(text)
    corpus.chunk_count = len(inserted)
    # 文本变更后，旧向量失效
    corpus.index_status = 'imported'
    corpus.embedding_model = ''
    corpus.embedding_backend = ''
    corpus.embedding_model_version = ''
    corpus.embedding_dim = 0
    corpus.signature_version = 0
    corpus.updated_at = now
    db.session.commit()
    return len(inserted)


def list_chunks(corpus_id, page=1, per_page=50):
    corpus = get_corpus(corpus_id)
    query = StyleChunk.query.filter_by(corpus_id=corpus_id).order_by(StyleChunk.source_order)
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return corpus, items, total


def clear_corpus_chunks(corpus_id):
    corpus = get_corpus(corpus_id)
    # 同样必须先清 FTS5 再删 style_chunks，避免 autoflush 顺序导致 FTS 残留
    if _fts_available():
        db.session.execute(db.text(
            "DELETE FROM style_chunks_fts WHERE rowid IN "
            "(SELECT id FROM style_chunks WHERE corpus_id = :cid)"
        ), {'cid': corpus_id})
    StyleChunk.query.filter_by(corpus_id=corpus_id).delete(synchronize_session=False)
    corpus.chunk_count = 0
    corpus.total_chars = 0
    corpus.index_status = 'empty'
    corpus.embedding_model = ''
    corpus.embedding_backend = ''
    corpus.embedding_model_version = ''
    corpus.embedding_dim = 0
    corpus.signature_version = 0
    corpus.updated_at = _now()
    db.session.commit()


# ---------- 向量化（Embedding） ----------

LOCAL_INDEX_BATCH_SIZE = 16
REMOTE_INDEX_BATCH_SIZE = 32


def index_corpus(
    corpus_id,
    api_key='',
    provider='siliconflow',
    backend='auto',
    model_dir=None,
    progress_callback=None,
):
    """用选定后端生成向量；旧调用传 API Key 时仍自动选择远程后端。"""
    corpus = get_corpus(corpus_id)
    chunks = StyleChunk.query.filter_by(
        corpus_id=corpus_id, is_enabled=True
    ).order_by(StyleChunk.id).all()
    if not chunks:
        raise GenerationError('语料库为空，请先导入文本')
    try:
        embedding_backend = create_embedding_backend(
            backend, api_key=api_key, provider=provider, model_dir=model_dir,
        )
        batch_size = (
            REMOTE_INDEX_BATCH_SIZE
            if isinstance(embedding_backend, RemoteEmbeddingBackend)
            else LOCAL_INDEX_BATCH_SIZE
        )
        np = _np()  # 延迟加载 numpy（向量写入需要）
        total = len(chunks)
        if progress_callback:
            progress_callback(0, total)
        for offset in range(0, total, batch_size):
            batch_chunks = chunks[offset:offset + batch_size]
            vectors = embedding_backend.embed_batch([chunk.content for chunk in batch_chunks])
            if len(vectors) != len(batch_chunks):
                raise GenerationError('向量数量与切片数量不一致，请重试')
            arrays = [np.asarray(vector, dtype=np.float32) for vector in vectors]
            if any(
                array.ndim != 1 or array.shape[0] != embedding_backend.dimension
                for array in arrays
            ):
                raise GenerationError('Embedding 返回维度与 backend 声明不一致，索引未写入')
            for chunk, array in zip(batch_chunks, arrays):
                chunk.embedding_blob = array.tobytes()
                chunk.embedding_backend = embedding_backend.backend_id
                chunk.embedding_model = embedding_backend.model_id
                chunk.embedding_model_version = embedding_backend.model_version
                chunk.embedding_dim = embedding_backend.dimension
            if progress_callback:
                progress_callback(min(offset + len(batch_chunks), total), total)
    except (EmbeddingBackendUnavailable, EmbeddingBackendError) as exc:
        db.session.rollback()
        raise GenerationError(str(exc)) from exc
    except Exception:
        db.session.rollback()
        raise

    now = _now()
    corpus.embedding_backend = embedding_backend.backend_id
    corpus.embedding_model = embedding_backend.model_id
    corpus.embedding_model_version = embedding_backend.model_version
    corpus.embedding_dim = embedding_backend.dimension
    corpus.index_status = 'indexed'
    corpus.updated_at = now
    db.session.commit()
    return len(chunks)


# ---------- 混合检索（向量 + BM25 + MMR） ----------

_NUMPY_MODULE = None


def _np():
    """延迟加载并缓存 numpy，避免在纯 BM25 检索或非 RAG 场景下拖慢启动。"""
    global _NUMPY_MODULE
    if _NUMPY_MODULE is None:
        import numpy as np  # noqa: PLC0415 - 延迟导入以加速后端启动
        _NUMPY_MODULE = np
    return _NUMPY_MODULE


def _load_matrix_with_chunks(chunks):
    """把切片向量 BLOB 恢复为 (N, dim) 归一化矩阵；无向量数据返回 None。"""
    np = _np()  # 延迟加载 numpy（向量矩阵计算需要）
    rows, vector_chunks, dim = [], [], None
    for chunk in chunks:
        blob = chunk.embedding_blob
        if not blob:
            continue
        arr = np.frombuffer(blob, dtype=np.float32)
        declared_dim = getattr(chunk, 'embedding_dim', arr.shape[0])
        if declared_dim <= 0 or arr.shape[0] != declared_dim:
            continue
        if dim is None:
            dim = arr.shape[0]
        if arr.shape[0] != dim:
            continue
        rows.append(arr)
        vector_chunks.append(chunk)
    if not rows:
        return None, []
    matrix = np.stack(rows)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    # matrix 是 np.stack 新建的可写 float32 数组，可以安全地原地归一化。
    # 最大候选池（5000×1024）约 19.5 MiB；避免 `matrix / norms` 再复制一整份，
    # 能显著降低 Style RAG 检索峰值内存，同时保持算法与返回值不变。
    matrix /= norms
    return matrix, vector_chunks


def _load_matrix(chunks):
    """兼容旧测试/内部调用：仅返回归一化矩阵。"""
    return _load_matrix_with_chunks(chunks)[0]


def _embedding_signature(chunk):
    """把旧 BGE-M3 索引映射到兼容远程签名；其他缺元数据索引不猜测。"""
    if not chunk.embedding_blob:
        return None
    backend = chunk.embedding_backend or ''
    version = chunk.embedding_model_version or ''
    if not backend and chunk.embedding_model == Config.EMBEDDING_MODEL:
        backend = RemoteEmbeddingBackend.backend_id
        version = RemoteEmbeddingBackend.model_version
    if not all((backend, chunk.embedding_model, version, chunk.embedding_dim)):
        return None
    return backend, chunk.embedding_model, version, chunk.embedding_dim


def _query_embedding_backend(signature, api_key, provider):
    backend_id = signature[0]
    kind = 'remote' if backend_id.startswith('remote:') else 'local'
    backend = create_embedding_backend(kind, api_key=api_key, provider=provider)
    if backend.signature != signature:
        raise EmbeddingBackendUnavailable('Embedding 模型签名已变化，请重新索引语料库')
    return backend


def _bm25_scores(corpus_ids, query_text, limit=60):
    """FTS5 BM25（trigram）：将查询拆成短短语用 OR 组合，返回 {chunk_id: bm25_score}。

    trigram 分词下，未加引号的查询词默认按 AND 且要求连续短语出现，过于苛刻；
    因此把查询切为 3~12 字的词/窗口，用 OR 连接（含引号短语），提升召回。
    """
    corpus_ids = tuple(sorted({int(corpus_id) for corpus_id in corpus_ids or ()}))
    if not query_text or not query_text.strip() or not corpus_ids or not _fts_available():
        return {}
    cleaned = re.sub(r'[\s，。！？；：、,.!?;:"“”‘’()（）\[\]{}<>]+', ' ', query_text).strip()
    words = [word for word in cleaned.split(' ') if len(word) >= 3]
    if not words:
        return {}
    pieces = []
    for word in words:
        if len(word) <= 12:
            pieces.append(word)
        else:
            # 超长连续串按 8 字窗口滑切，避免短语匹配失败导致召回为零
            pieces.extend(word[i:i + 8] for i in range(0, len(word), 8))
    pieces = list(dict.fromkeys(pieces))[:10]
    match_expr = ' OR '.join(f'"{piece}"' for piece in pieces)
    corpus_params = {f'cid_{index}': corpus_id for index, corpus_id in enumerate(corpus_ids)}
    placeholders = ', '.join(f':{name}' for name in corpus_params)
    rows = db.session.execute(db.text(
        "SELECT f.rowid, bm25(style_chunks_fts) FROM style_chunks_fts AS f "
        "JOIN style_chunks AS c ON c.id = f.rowid "
        f"WHERE style_chunks_fts MATCH :q AND c.corpus_id IN ({placeholders}) "
        "AND c.is_enabled = 1 "
        "ORDER BY bm25(style_chunks_fts) LIMIT :limit"
    ), {'q': match_expr, 'limit': limit, **corpus_params}).fetchall()
    # bm25() 返回值越小越相关，取负转为正向分数
    return {int(row[0]): -float(row[1]) for row in rows}


def _rrf_rank(*ranked_lists, k=60):
    """Reciprocal Rank Fusion：把多路检索排名融合为加权得分。"""
    fused = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return fused


def _mmr_rerank(candidates, similarity_map, lambda_=0.7, top_k=3):
    """MMR 重排：在相关度与多样性之间折中。

    MMR = argmax( lambda*rel - (1-lambda)*max_sim(已选) )。
    candidates: [(chunk_id, rel_score)]；similarity_map 提供片段间相似度。
    """
    selected, pool = [], candidates[:]
    while len(selected) < top_k and pool:
        best, best_score = None, -float('inf')
        for index, (chunk_id, rel) in enumerate(pool):
            diversity_penalty = 0.0
            for chosen_id, _ in selected:
                sim = similarity_map.get((chosen_id, chunk_id), 0.0)
                diversity_penalty = max(diversity_penalty, sim)
            score = lambda_ * rel - (1 - lambda_) * diversity_penalty
            if score > best_score:
                best, best_score = index, score
        if best is None:
            break
        chunk_id, rel = pool.pop(best)
        selected.append((chunk_id, rel))
    return selected


def _mmr_rerank_lazy(candidates, similarity_fn, lambda_=0.7, top_k=3):
    """仅计算实际参与 MMR 选择的候选对，避免预建完整 N×N 相似度矩阵。"""
    selected, pool = [], candidates[:]
    while len(selected) < top_k and pool:
        best, best_score = None, -float('inf')
        for index, (chunk_id, relevance) in enumerate(pool):
            diversity_penalty = max(
                (similarity_fn(chosen_id, chunk_id) for chosen_id, _score in selected),
                default=0.0,
            )
            score = lambda_ * relevance - (1 - lambda_) * diversity_penalty
            if score > best_score:
                best, best_score = index, score
        if best is None:
            break
        selected.append(pool.pop(best))
    return selected


SEARCH_RESULT_CACHE_TTL_SECONDS = 30.0
SEARCH_RESULT_CACHE_MAX_ENTRIES = 16
SEARCH_RERANK_LIMIT = 60
_SEARCH_RESULT_CACHE = OrderedDict()
_SEARCH_RESULT_CACHE_LOCK = Lock()


def _search_cache_key(
    query_text, corpus_ids, scene_type, pacing, pov, top_k, api_key, provider, mmr_lambda,
):
    """用 corpus 版本生成短期缓存键；不保存 API Key 明文。"""
    if db.engine.url.database in (None, ':memory:'):
        return None
    corpus_query = db.session.query(
        StyleCorpus.id, StyleCorpus.updated_at, StyleCorpus.chunk_count,
        StyleCorpus.embedding_backend, StyleCorpus.embedding_model_version,
    )
    if corpus_ids:
        corpus_query = corpus_query.filter(StyleCorpus.id.in_(corpus_ids))
    profile_versions = {
        row.corpus_id: (
            row.feature_version,
            row.updated_at.isoformat() if row.updated_at else '',
        )
        for row in db.session.query(
            AuthorStyleProfile.corpus_id,
            AuthorStyleProfile.feature_version,
            AuthorStyleProfile.updated_at,
        ).all()
    }
    versions = tuple(
        (
            row.id,
            row.updated_at.isoformat() if row.updated_at else '',
            row.chunk_count,
            row.embedding_backend or '',
            row.embedding_model_version or '',
            profile_versions.get(row.id),
        )
        for row in corpus_query.order_by(StyleCorpus.id).all()
    )
    key_fingerprint = hashlib.sha256((api_key or '').encode('utf-8')).hexdigest()[:12]
    return (
        query_text, tuple(sorted(int(item) for item in corpus_ids or ())), scene_type,
        pacing, pov, int(top_k), provider, round(float(mmr_lambda), 4), key_fingerprint, versions,
    )


def _get_cached_search(key):
    if key is None:
        return None
    now = time.monotonic()
    with _SEARCH_RESULT_CACHE_LOCK:
        cached = _SEARCH_RESULT_CACHE.get(key)
        if cached is None:
            return None
        created_at, result = cached
        if now - created_at > SEARCH_RESULT_CACHE_TTL_SECONDS:
            _SEARCH_RESULT_CACHE.pop(key, None)
            return None
        _SEARCH_RESULT_CACHE.move_to_end(key)
        return deepcopy(result)


def _set_cached_search(key, result):
    if key is None:
        return
    with _SEARCH_RESULT_CACHE_LOCK:
        _SEARCH_RESULT_CACHE[key] = (time.monotonic(), deepcopy(result))
        _SEARCH_RESULT_CACHE.move_to_end(key)
        while len(_SEARCH_RESULT_CACHE) > SEARCH_RESULT_CACHE_MAX_ENTRIES:
            _SEARCH_RESULT_CACHE.popitem(last=False)


def hybrid_search_style(
    query_text,
    corpus_ids=None,
    scene_type=None,
    pacing=None,
    pov=None,
    top_k=3,
    api_key='',
    provider='siliconflow',
    mmr_lambda=0.7,
):
    """多维混合检索：硬过滤 + 向量余弦 + FTS5 BM25（RRF 融合）+ MMR 重排。

    :return: (items, meta) items 为风格片段列表，meta 含检索统计信息
    """
    if not query_text or not query_text.strip():
        raise GenerationError('检索文本不能为空')
    cache_key = _search_cache_key(
        query_text, corpus_ids, scene_type, pacing, pov, top_k, api_key, provider, mmr_lambda,
    )
    cached = _get_cached_search(cache_key)
    if cached is not None:
        cached[1]['cache_hit'] = True
        return cached
    query_tags = rule_tag_chunk(query_text)
    requested_scene = scene_type if scene_type not in (None, '', 'auto') else None
    effective_scene = requested_scene or query_tags['scene_type']

    # 1) 候选池 + 标签硬过滤
    query = StyleChunk.query.filter(StyleChunk.is_enabled.is_(True))
    if corpus_ids:
        query = query.filter(StyleChunk.corpus_id.in_(corpus_ids))
    if requested_scene:
        query = query.filter(StyleChunk.scene_type == requested_scene)
    if pacing:
        query = query.filter(StyleChunk.pacing == pacing)
    if pov:
        query = query.filter(StyleChunk.pov == pov)
    chunks = query.order_by(StyleChunk.id).limit(Config.STYLE_SEARCH_MAX_CANDIDATES + 1).all()
    if len(chunks) > Config.STYLE_SEARCH_MAX_CANDIDATES:
        raise GenerationError(
            f'检索候选超过 {Config.STYLE_SEARCH_MAX_CANDIDATES} 个，请选择更少的语料库或增加过滤条件'
        )
    relaxed_scene = False
    if not chunks and requested_scene:
        # 场景硬过滤无候选时放宽场景条件重试，避免风格检索落空
        relaxed_scene = True
        query = StyleChunk.query.filter(StyleChunk.is_enabled.is_(True))
        if corpus_ids:
            query = query.filter(StyleChunk.corpus_id.in_(corpus_ids))
        if pacing:
            query = query.filter(StyleChunk.pacing == pacing)
        if pov:
            query = query.filter(StyleChunk.pov == pov)
        chunks = query.order_by(StyleChunk.id).limit(Config.STYLE_SEARCH_MAX_CANDIDATES + 1).all()
        if len(chunks) > Config.STYLE_SEARCH_MAX_CANDIDATES:
            raise GenerationError(
                f'检索候选超过 {Config.STYLE_SEARCH_MAX_CANDIDATES} 个，请选择更少的语料库或增加过滤条件'
            )
    if not chunks:
        result = ([], {'mode': 'empty', 'reason': '无满足过滤条件的片段'})
        _set_cached_search(cache_key, result)
        return result

    chunk_by_id = {chunk.id: chunk for chunk in chunks}
    corpus_ids_used = sorted({chunk.corpus_id for chunk in chunks})

    # 2) 向量余弦检索（主信号）
    vector_ranked, vector_scores = [], {}
    matrix, vector_chunks = None, []
    vector_fallback_reason = ''
    api_key = (api_key or '').strip()
    blob_chunks = [chunk for chunk in chunks if chunk.embedding_blob]
    signatures = {_embedding_signature(chunk) for chunk in blob_chunks}
    has_incomplete_signature = None in signatures
    signatures.discard(None)
    if has_incomplete_signature:
        vector_fallback_reason = '索引缺少完整模型元数据，请重新索引'
    elif len(signatures) == 1:
        signature = next(iter(signatures))
        compatible_chunks = [chunk for chunk in chunks if _embedding_signature(chunk) == signature]
        matrix, vector_chunks = _load_matrix_with_chunks(compatible_chunks)
        if matrix is not None:
            try:
                embedding_backend = _query_embedding_backend(signature, api_key, provider)
                q_vec = embedding_backend.embed_text(query_text, is_query=True)
                np = _np()  # 延迟加载 numpy（向量余弦计算需要）
                q_vec = np.asarray(q_vec, dtype=np.float32)
                if q_vec.shape != (signature[3],):
                    raise EmbeddingBackendError('查询向量维度与索引不一致')
                q_norm = np.linalg.norm(q_vec)
                if q_norm > 0:
                    q_vec = q_vec / q_norm
                    scores = matrix @ q_vec  # 余弦相似度（矩阵已归一化）
                    order = np.argsort(-scores)
                    vector_ranked = [vector_chunks[i].id for i in order][:60]
                    vector_scores = {vector_chunks[i].id: float(scores[i]) for i in order}
            except (EmbeddingBackendUnavailable, EmbeddingBackendError) as exc:
                matrix, vector_chunks = None, []
                vector_fallback_reason = str(exc)
    elif len(signatures) > 1:
        vector_fallback_reason = '候选语料库使用不同 Embedding 模型，请统一重新索引'
    elif blob_chunks:
        vector_fallback_reason = '索引缺少完整模型元数据，请重新索引'
    else:
        vector_fallback_reason = '语料库没有可用 Embedding 索引'

    # 3) FTS5 BM25（词汇级补充信号）
    bm25_scores = _bm25_scores(corpus_ids_used, query_text)

    # 4) 加载/重建 corpus 统计 Profile；Style 是主排序信号。
    profiles = {}
    for corpus_id in corpus_ids_used:
        record, stale = get_author_style_profile(corpus_id)
        corpus = chunk_by_id[next(
            chunk_id for chunk_id, chunk in chunk_by_id.items() if chunk.corpus_id == corpus_id
        )].corpus
        profile_outdated = bool(
            record and corpus and corpus.updated_at
            and (not record.updated_at or record.updated_at < corpus.updated_at)
        )
        if not record or stale or profile_outdated:
            record = build_author_style_profile(corpus_id)
        profiles[corpus_id] = json.loads(record.profile_json)

    profile_resolutions = {
        corpus_id: resolve_mode_profile(profile, effective_scene)
        for corpus_id, profile in profiles.items()
    }
    common_target_profile = merge_target_profiles([
        resolution['profile'] for resolution in profile_resolutions.values()
    ])

    bm25_ranked = [
        chunk_id
        for chunk_id in sorted(bm25_scores, key=lambda chunk_id: -bm25_scores[chunk_id])
        if chunk_id in chunk_by_id
    ]
    bm25_rank_scores = {
        chunk_id: 1.0 - rank / max(1, len(bm25_ranked))
        for rank, chunk_id in enumerate(bm25_ranked)
    }
    score_details = {}
    preliminary_candidates = []
    for chunk in chunks:
        try:
            feature_payload = json.loads(chunk.style_features_json or '{}')
        except (TypeError, json.JSONDecodeError):
            feature_payload = {}
        raw_features = feature_payload.get('features') or {}
        try:
            signature_payload_data = json.loads(chunk.style_signature_json or '{}')
        except (TypeError, json.JSONDecodeError):
            signature_payload_data = {}
        raw_signature = signature_payload_data.get('values') or {}
        profile_resolution = profile_resolutions[chunk.corpus_id]
        style_scores = style_similarity_scores(
            raw_features,
            common_target_profile,
            raw_signature=raw_signature,
            signature_version=(
                chunk.style_signature_version if len(profile_resolutions) == 1 else None
            ),
        )
        style_scores['confidence'] = round(
            min(style_scores['confidence'], max(0.0, min(1.0, chunk.style_confidence or 0.0))),
            6,
        )
        semantic_raw = vector_scores.get(chunk.id)
        semantic_score = (semantic_raw + 1.0) / 2.0 if semantic_raw is not None else None
        lexical_score = bm25_rank_scores.get(chunk.id, 0.0)
        scene_score = scene_similarity(chunk.scene_type, effective_scene)
        base_score = final_retrieval_score(
            style_score=style_scores['style_score'],
            scene_score=scene_score,
            semantic_score=semantic_score,
            lexical_score=lexical_score,
            leakage_penalty=0.0,
        )
        score_details[chunk.id] = {
            **style_scores,
            'scene_score': round(scene_score, 6),
            'semantic_score': round(semantic_score, 6) if semantic_score is not None else None,
            'lexical_score': round(lexical_score, 6),
            'base_score': base_score,
            'profile_source': profile_resolution['source'],
            'profile_mode': profile_resolution['resolved_mode'],
        }
        preliminary_candidates.append((chunk.id, base_score))
    preliminary_candidates.sort(key=lambda item: (-item[1], item[0]))

    # 泄漏惩罚只可能降低 base score。按 base score 从高到低计算，当前第 60 名
    # 的实际分数一旦不低于下一个未检查候选的理论上限，即可精确停止。
    adjusted_candidates = []
    for index, (chunk_id, base_score) in enumerate(preliminary_candidates):
        chunk = chunk_by_id[chunk_id]
        leakage = content_leakage_metrics(query_text, chunk.content)
        detail = score_details[chunk_id]
        total_score = final_retrieval_score(
            style_score=detail['style_score'],
            scene_score=detail['scene_score'],
            semantic_score=detail['semantic_score'],
            lexical_score=detail['lexical_score'],
            leakage_penalty=leakage['content_overlap_penalty'],
        )
        detail.update({**leakage, 'total_score': total_score})
        adjusted_candidates.append((chunk_id, total_score))
        if len(adjusted_candidates) < SEARCH_RERANK_LIMIT:
            continue
        adjusted_candidates.sort(key=lambda item: (-item[1], item[0]))
        cutoff = adjusted_candidates[SEARCH_RERANK_LIMIT - 1][1]
        next_base = (
            preliminary_candidates[index + 1][1]
            if index + 1 < len(preliminary_candidates) else -float('inf')
        )
        if cutoff >= next_base:
            break
    adjusted_candidates.sort(key=lambda item: (-item[1], item[0]))
    candidates = adjusted_candidates[:SEARCH_RERANK_LIMIT]

    # 5) MMR 保留多样性；无向量时使用本地内容 n-gram 相似度。
    similarity_cache = {}
    id_to_row = {chunk.id: idx for idx, chunk in enumerate(vector_chunks)}

    def candidate_similarity(left_id, right_id):
        pair = (min(left_id, right_id), max(left_id, right_id))
        if pair in similarity_cache:
            return similarity_cache[pair]
        if left_id == right_id:
            similarity = 1.0
        else:
            left, right = chunk_by_id[left_id], chunk_by_id[right_id]
            similarity = content_diversity_similarity(left.content, right.content)
            if matrix is not None and left_id in id_to_row and right_id in id_to_row:
                embedding_similarity = float(matrix[id_to_row[left_id]] @ matrix[id_to_row[right_id]])
                similarity = max(similarity, embedding_similarity)
        similarity_cache[pair] = similarity
        return similarity

    selected = _mmr_rerank_lazy(
        candidates, candidate_similarity, lambda_=mmr_lambda, top_k=top_k,
    )

    # 6) 组装可解释返回
    items = []
    for chunk_id, total_score in selected:
        chunk = chunk_by_id.get(chunk_id)
        if not chunk:
            continue
        vector_score = vector_scores.get(chunk_id)
        bm25_score = bm25_scores.get(chunk_id)
        detail = score_details[chunk_id]
        try:
            selected_features = json.loads(chunk.style_features_json or '{}').get('features') or {}
        except (TypeError, json.JSONDecodeError):
            selected_features = {}
        detail['feature_reasons'] = explain_style_feature_matches(
            selected_features, common_target_profile,
        )
        reasons = [
            f"文风 {detail['style_score']:.2f}",
            f"节奏 {detail['rhythm_score']:.2f}",
            f"标点 {detail['punctuation_score']:.2f}",
            f"功能词 {detail['function_word_score']:.2f}",
            f"风格签名 {detail['signature_score']:.2f}",
        ]
        if detail['content_overlap_penalty'] > 0:
            reasons.append(f"内容重合扣分 {detail['content_overlap_penalty']:.2f}")
        debug_reasons = [item['message'] for item in detail['feature_reasons']]
        effective_query_scene = effective_scene
        if chunk.scene_type == effective_query_scene:
            debug_reasons.append(f"✓ {SCENE_LABELS.get(chunk.scene_type, chunk.scene_type)}场景匹配")
        if (
            effective_query_scene == 'dialogue'
            and abs(float(chunk.dialogue_ratio or 0.0) - query_tags['dialogue_ratio']) <= 0.15
        ):
            debug_reasons.append('✓ 对话比例匹配')
        items.append({
            **chunk.to_dict(include_content=True),
            'corpus_name': chunk.corpus.name if chunk.corpus else '',
            'score': round(float(total_score), 4),
            'style_score': detail['style_score'],
            'rhythm_score': detail['rhythm_score'],
            'punctuation_score': detail['punctuation_score'],
            'function_word_score': detail['function_word_score'],
            'signature_score': detail['signature_score'],
            'scene_score': detail['scene_score'],
            'semantic_score': detail['semantic_score'],
            'content_overlap_penalty': detail['content_overlap_penalty'],
            'confidence': detail['confidence'],
            'ranking_explanation': detail,
            'debug_reasons': debug_reasons[:5],
            'vector_score': round(vector_score, 4) if vector_score is not None else None,
            'bm25_score': round(bm25_score, 4) if bm25_score is not None else None,
            'reasons': reasons,
        })

    profile_summaries = []
    effective_profile_scene = effective_scene
    for corpus_id in corpus_ids_used:
        profile = profiles[corpus_id]
        resolution = resolve_mode_profile(profile, effective_profile_scene)
        resolved_profile = resolution['profile']
        corpus = next(
            (chunk.corpus for chunk in chunks if chunk.corpus_id == corpus_id), None
        )
        profile_summaries.append({
            'corpus_id': corpus_id,
            'corpus_name': corpus.name if corpus else '',
            'feature_version': profile.get('feature_version'),
            'signature_version': (profile.get('style_signature') or {}).get('signature_version'),
            'sample_count': profile.get('sample_count', 0),
            'valid_char_count': profile.get('valid_char_count', 0),
            'confidence': profile.get('confidence', 0.0),
            'scene_profile': {
                'requested_mode': effective_profile_scene,
                'source': resolution['source'],
                'resolved_mode': resolution['resolved_mode'],
                'sample_count': resolved_profile.get('sample_count', 0),
                'valid_char_count': resolved_profile.get('valid_char_count', 0),
                'confidence': resolved_profile.get('confidence', 0.0),
            },
        })

    meta = {
        'mode': 'style_rag',
        'corpus_ids': corpus_ids_used,
        'candidate_count': len(chunks),
        'vector_enabled': bool(vector_ranked),
        'embedding_fallback_reason': vector_fallback_reason or None,
        'bm25_enabled': bool(bm25_scores),
        'ranking_mode': 'style_first',
        'ranking_weights': {
            'style': 0.72, 'scene': 0.12, 'semantic': 0.10,
            'bm25': 0.06, 'content_leakage_penalty': 0.45,
        },
        'resolved_scene_type': requested_scene or 'auto',
        'query_scene_type': query_tags['scene_type'],
        'effective_scene_type': effective_scene,
        'query_tags': query_tags,
        'profile_summaries': profile_summaries,
        'resolved_pacing': pacing or 'auto',
        'relaxed_scene': relaxed_scene,
        'cache_hit': False,
    }
    result = (items, meta)
    _set_cached_search(cache_key, result)
    return result
