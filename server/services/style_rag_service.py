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
import math
import re
from datetime import datetime, timezone

# 注意：numpy 为延迟导入（仅在向量化/向量检索时加载），避免拖慢后端启动。
from config import Config
from database import db
from database.models import StyleCorpus, StyleChunk
from services.api_client import LLMClient, LLMClientError
from services.errors import GenerationError


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


def _split_long_paragraph(paragraph, maximum):
    """超长段落按句号/感叹号/问号寻找语义断点拆分，严禁把句子切成两半。

    若整段无任何句末标点（极端情况），按 maximum 硬切兜底，避免切片超限。
    """
    sentences = re.split(r'(?<=[。！？!?])', paragraph)
    if len(sentences) == 1:
        # 无句子边界：固定长度硬切（此时不存在"语义断点"可保）
        return [paragraph[i:i + maximum] for i in range(0, len(paragraph), maximum)]
    chunks, current = [], ''
    for sentence in sentences:
        if current and len(current) + len(sentence) > maximum:
            chunks.append(current.strip())
            current = sentence
        else:
            current += sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks


def split_corpus_text(content, target=420, minimum=200, maximum=900):
    """按自然段聚合为 200~900 字的风格切片。

    切片以完整自然段为边界，连续短对话段合并为"对话互动块"；
    超长描写段按句号断点拆分。返回切片列表。
    """
    raw_paragraphs = [item.strip() for item in re.split(r'\n\s*\n+', content or '') if item.strip()]
    paragraphs = []
    for paragraph in raw_paragraphs:
        if len(paragraph) > maximum:
            paragraphs.extend(_split_long_paragraph(paragraph, maximum))
        else:
            paragraphs.append(paragraph)

    chunks, current, current_length = [], [], 0
    for paragraph in paragraphs:
        next_length = current_length + len(paragraph) + (2 if current else 0)
        # 超出上限：先结算当前块（若为空则直接独立成块）
        if current and next_length > maximum:
            chunks.append('\n\n'.join(current))
            current, current_length = [], 0
        current.append(paragraph)
        current_length += len(paragraph) + (2 if len(current) > 1 else 0)
        if current_length >= target:
            chunks.append('\n\n'.join(current))
            current, current_length = [], 0
    if current:
        tail = '\n\n'.join(current)
        if chunks and len(tail) < minimum and len(chunks[-1]) + len(tail) + 2 <= maximum:
            chunks[-1] += '\n\n' + tail
        else:
            chunks.append(tail)
    return [item for item in chunks if item.strip()]


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

    # 清空旧内容（含 FTS5 残留）
    StyleChunk.query.filter_by(corpus_id=corpus_id).delete(synchronize_session=False)
    db.session.execute(db.text(
        "DELETE FROM style_chunks_fts WHERE rowid IN "
        "(SELECT id FROM style_chunks WHERE corpus_id = :cid)"
    ), {'cid': corpus_id})

    now = _now()
    inserted = []
    for index, content in enumerate(chunks):
        tag = rule_tag_chunk(content)
        chunk = StyleChunk(
            corpus_id=corpus_id,
            content=content,
            content_hash=_content_hash(content),
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
        db.session.execute(db.text(
            "INSERT INTO style_chunks_fts(rowid, content) VALUES (:rid, :content)"
        ), {'rid': chunk.id, 'content': content})
        inserted.append(chunk)

    corpus.source_filename = filename or corpus.source_filename
    corpus.total_chars = len(text)
    corpus.chunk_count = len(inserted)
    # 文本变更后，旧向量失效
    corpus.index_status = 'imported'
    corpus.embedding_model = ''
    corpus.embedding_dim = 0
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
    StyleChunk.query.filter_by(corpus_id=corpus_id).delete(synchronize_session=False)
    db.session.execute(db.text(
        "DELETE FROM style_chunks_fts WHERE rowid IN "
        "(SELECT id FROM style_chunks WHERE corpus_id = :cid)"
    ), {'cid': corpus_id})
    corpus.chunk_count = 0
    corpus.total_chars = 0
    corpus.index_status = 'empty'
    corpus.embedding_model = ''
    corpus.embedding_dim = 0
    corpus.updated_at = _now()
    db.session.commit()


# ---------- 向量化（Embedding） ----------

def index_corpus(corpus_id, api_key, provider='siliconflow'):
    """调用 Embedding API 为语料库全部切片生成向量并写入 BLOB。"""
    corpus = get_corpus(corpus_id)
    chunks = StyleChunk.query.filter_by(
        corpus_id=corpus_id, is_enabled=True
    ).order_by(StyleChunk.id).all()
    if not chunks:
        raise GenerationError('语料库为空，请先导入文本')
    api_key = (api_key or '').strip()
    if not api_key:
        raise GenerationError('请输入硅基流动 API 密钥用于向量化')

    client = LLMClient(provider=provider, api_key=api_key)
    try:
        vectors = client.embed([chunk.content for chunk in chunks])
    except LLMClientError as exc:
        raise GenerationError(str(exc)) from exc
    if len(vectors) != len(chunks):
        raise GenerationError('向量数量与切片数量不一致，请重试')

    now = _now()
    np = _np()  # 延迟加载 numpy（向量写入需要）
    for chunk, vector in zip(chunks, vectors):
        chunk.embedding_blob = np.asarray(vector, dtype=np.float32).tobytes()
        chunk.embedding_model = Config.EMBEDDING_MODEL
        chunk.embedding_dim = Config.EMBEDDING_DIMENSIONS
    corpus.embedding_model = Config.EMBEDDING_MODEL
    corpus.embedding_dim = Config.EMBEDDING_DIMENSIONS
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


def _load_matrix(chunks):
    """把切片向量 BLOB 恢复为 (N, dim) 归一化矩阵；无向量数据返回 None。"""
    np = _np()  # 延迟加载 numpy（向量矩阵计算需要）
    rows, dim = [], None
    for chunk in chunks:
        blob = chunk.embedding_blob
        if not blob:
            continue
        arr = np.frombuffer(blob, dtype=np.float32).astype(np.float64)
        if dim is None:
            dim = arr.shape[0]
        rows.append(arr)
    if not rows:
        return None
    matrix = np.stack(rows)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _bm25_scores(corpus_ids, query_text, limit=60):
    """FTS5 BM25（trigram）：将查询拆成短短语用 OR 组合，返回 {chunk_id: bm25_score}。

    trigram 分词下，未加引号的查询词默认按 AND 且要求连续短语出现，过于苛刻；
    因此把查询切为 3~12 字的词/窗口，用 OR 连接（含引号短语），提升召回。
    """
    if not query_text or not query_text.strip():
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
    rows = db.session.execute(db.text(
        "SELECT rowid, bm25(style_chunks_fts) FROM style_chunks_fts "
        "WHERE content MATCH :q ORDER BY bm25(style_chunks_fts) LIMIT :limit"
    ), {'q': match_expr, 'limit': limit}).fetchall()
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

    # 1) 候选池 + 标签硬过滤
    query = StyleChunk.query.filter(StyleChunk.is_enabled.is_(True))
    if corpus_ids:
        query = query.filter(StyleChunk.corpus_id.in_(corpus_ids))
    if scene_type:
        query = query.filter(StyleChunk.scene_type == scene_type)
    if pacing:
        query = query.filter(StyleChunk.pacing == pacing)
    if pov:
        query = query.filter(StyleChunk.pov == pov)
    chunks = query.order_by(StyleChunk.id).all()
    relaxed_scene = False
    if not chunks and scene_type:
        # 场景硬过滤无候选时放宽场景条件重试，避免风格检索落空
        relaxed_scene = True
        query = StyleChunk.query.filter(StyleChunk.is_enabled.is_(True))
        if corpus_ids:
            query = query.filter(StyleChunk.corpus_id.in_(corpus_ids))
        if pacing:
            query = query.filter(StyleChunk.pacing == pacing)
        if pov:
            query = query.filter(StyleChunk.pov == pov)
        chunks = query.order_by(StyleChunk.id).all()
    if not chunks:
        return [], {'mode': 'empty', 'reason': '无满足过滤条件的片段'}

    chunk_by_id = {chunk.id: chunk for chunk in chunks}
    corpus_ids_used = sorted({chunk.corpus_id for chunk in chunks})

    # 2) 向量余弦检索（主信号）
    vector_ranked, vector_scores = [], {}
    api_key = (api_key or '').strip()
    if api_key:
        matrix = _load_matrix(chunks)
        if matrix is not None:
            try:
                client = LLMClient(provider=provider, api_key=api_key)
                q_vec = client.embed([query_text])[0]
                np = _np()  # 延迟加载 numpy（向量余弦计算需要）
                q_vec = np.asarray(q_vec, dtype=np.float64)
                q_norm = np.linalg.norm(q_vec)
                if q_norm > 0:
                    q_vec = q_vec / q_norm
                    scores = matrix @ q_vec  # 余弦相似度（矩阵已归一化）
                    order = np.argsort(-scores)
                    vector_ranked = [chunks[i].id for i in order][:60]
                    vector_scores = {chunks[i].id: float(scores[i]) for i in order}
            except LLMClientError as exc:
                raise GenerationError(str(exc)) from exc

    # 3) FTS5 BM25（词汇级补充信号）
    bm25_scores = _bm25_scores(corpus_ids_used, query_text)

    # 4) RRF 融合
    fused = _rrf_rank(vector_ranked, [cid for cid in sorted(bm25_scores, key=lambda c: -bm25_scores[c])])
    if not fused:
        raise GenerationError('检索未命中任何片段，请调整过滤条件或扩大语料库')

    ranked = sorted(fused.items(), key=lambda item: -item[1])

    # 5) MMR 多样性重排（基于向量相似度）
    candidates = []
    for chunk_id, _ in ranked[:40]:
        chunk = chunk_by_id.get(chunk_id)
        if chunk:
            candidates.append((chunk_id, float(fused[chunk_id])))
    if len(candidates) > top_k and matrix is not None:
        # 片段间余弦相似度矩阵（避免句式重复）
        sim_map = {}
        id_to_row = {chunk.id: idx for idx, chunk in enumerate(chunks)}
        idxs = [id_to_row[cid] for cid in candidates if cid in id_to_row]
        sub = matrix[idxs] if idxs else None
        if sub is not None:
            sub_norms = np.linalg.norm(sub, axis=1, keepdims=True)
            sub_norms[sub_norms == 0] = 1.0
            sub = sub / sub_norms
            sim = sub @ sub.T
            valid_ids = [cid for cid in candidates if cid in id_to_row]
            for i, cid_i in enumerate(valid_ids):
                for j, cid_j in enumerate(valid_ids):
                    sim_map[(cid_i, cid_j)] = float(sim[i, j])
        selected = _mmr_rerank(candidates, sim_map, lambda_=mmr_lambda, top_k=top_k)
    else:
        selected = candidates[:top_k]

    # 6) 组装返回
    items = []
    for chunk_id, fused_score in selected:
        chunk = chunk_by_id.get(chunk_id)
        if not chunk:
            continue
        vector_score = vector_scores.get(chunk_id)
        bm25_score = bm25_scores.get(chunk_id)
        reasons = []
        if vector_score is not None:
            reasons.append(f'语义相关 {vector_score:.2f}')
        if bm25_score is not None:
            reasons.append('词汇句式命中')
        if not reasons:
            reasons.append('综合检索')
        items.append({
            **chunk.to_dict(include_content=True),
            'corpus_name': chunk.corpus.name if chunk.corpus else '',
            'score': round(float(fused_score), 4),
            'vector_score': round(vector_score, 4) if vector_score is not None else None,
            'bm25_score': round(bm25_score, 4) if bm25_score is not None else None,
            'reasons': reasons,
        })

    meta = {
        'mode': 'style_rag',
        'corpus_ids': corpus_ids_used,
        'candidate_count': len(chunks),
        'vector_enabled': bool(vector_ranked),
        'bm25_enabled': bool(bm25_scores),
        'resolved_scene_type': scene_type or 'auto',
        'resolved_pacing': pacing or 'auto',
        'relaxed_scene': relaxed_scene,
    }
    return items, meta
