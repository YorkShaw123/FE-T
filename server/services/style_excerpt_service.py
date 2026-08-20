"""范例文章切片、批量标签分析与场景检索。"""
import hashlib
import json
import re
from datetime import datetime, timezone

from database import db
from database.models import PromptTemplate, StyleExcerpt, StyleProfile
from services.api_client import LLMClient
from services.errors import GenerationError
from services.style_profile_service import _extract_response_json, style_source_hash


SCENE_TYPES = {'dialogue', 'action', 'psychology', 'environment', 'transition', 'narration', 'mixed'}
PACES = {'slow', 'medium', 'fast'}
SCENE_LABELS = {
    'dialogue': '对话', 'action': '动作', 'psychology': '心理',
    'environment': '环境', 'transition': '转场', 'narration': '叙述', 'mixed': '综合',
}


def _content_hash(content):
    return hashlib.sha256((content or '').encode('utf-8')).hexdigest()


def _split_long_paragraph(paragraph, maximum):
    sentences = re.split(r'(?<=[。！？!?])', paragraph)
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


def split_reference_text(content, target=560, minimum=260, maximum=1000):
    """按自然段聚合为 300—1000 字左右的语义片段。"""
    raw_paragraphs = [item.strip() for item in re.split(r'\n\s*\n+', content or '') if item.strip()]
    paragraphs = []
    for paragraph in raw_paragraphs:
        if len(paragraph) > maximum:
            paragraphs.extend(_split_long_paragraph(paragraph, maximum))
        else:
            paragraphs.append(paragraph)
    chunks, current = [], []
    current_length = 0
    for paragraph in paragraphs:
        next_length = current_length + len(paragraph) + (2 if current else 0)
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


def _label_prompt(batch):
    excerpts = '\n\n'.join(
        f'<excerpt index="{index}">{content}</excerpt>'
        for index, content in batch
    )
    return f"""请为下面的文学片段生成检索标签，不要总结剧情，不要复述原文。
只输出 JSON 对象，格式严格如下：
{{"items":[{{"index":0,"scene_type":"dialogue|action|psychology|environment|transition|narration|mixed",
"pov":"叙述人称与限制视角","emotion":"最多三个情绪词，以顿号连接",
"pace":"slow|medium|fast","tags":["最多5个可检索标签"],
"functions":["信息试探|关系变化等叙事功能"]}}]}}

{excerpts}"""


def _normalize_label(item, index):
    scene_type = str(item.get('scene_type', 'mixed')).strip().lower()
    pace = str(item.get('pace', 'medium')).strip().lower()
    try:
        normalized_index = int(item.get('index', index))
    except (TypeError, ValueError):
        normalized_index = index
    return {
        'index': normalized_index,
        'scene_type': scene_type if scene_type in SCENE_TYPES else 'mixed',
        'pov': str(item.get('pov', '')).strip(),
        'emotion': str(item.get('emotion', '')).strip(),
        'pace': pace if pace in PACES else 'medium',
        'tags': [str(value).strip() for value in item.get('tags', []) if str(value).strip()][:5],
        'functions': [str(value).strip() for value in item.get('functions', []) if str(value).strip()][:5],
    }


def _label_batches(chunks, client, model):
    labels = {}
    for offset in range(0, len(chunks), 6):
        batch_contents = chunks[offset:offset + 6]
        batch = list(enumerate(batch_contents, start=offset))
        response = client.generate(
            model=model,
            messages=[
                {'role': 'system', 'content': '你是文学场景片段标签器。只输出合法 JSON，不输出解释。'},
                {'role': 'user', 'content': _label_prompt(batch)},
            ],
            stream=False,
            thinking_enabled=False,
            max_tokens=2500,
        )
        payload = _extract_response_json(response)
        items = payload.get('items', []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            raise GenerationError('片段标签结果缺少 items 数组')
        for fallback_index, item in enumerate(items, start=offset):
            if isinstance(item, dict):
                normalized = _normalize_label(item, fallback_index)
                labels[normalized['index']] = normalized
    return labels


def rebuild_style_excerpts(template_id, api_key, provider, model):
    template = db.session.get(PromptTemplate, template_id)
    if not template or template.category != 'example':
        raise GenerationError('只有范例文章模板可以生成参考片段')
    profile = StyleProfile.query.filter_by(template_id=template.id).first()
    if not profile or profile.analysis_status != 'ready':
        raise GenerationError('请先生成有效的 Style Card')
    if profile.source_hash != style_source_hash(template.content):
        raise GenerationError('Style Card 已过期，请先重新分析风格')
    if not api_key or not api_key.strip():
        raise GenerationError('请先输入 API 密钥')
    chunks = split_reference_text(template.content)
    if not chunks:
        raise GenerationError('范例文章没有可切分的正文')

    client = LLMClient(provider=provider, api_key=api_key)
    labels = _label_batches(chunks, client, model)
    if set(labels) != set(range(len(chunks))):
        raise GenerationError('部分片段未获得有效标签，请重新分析')

    StyleExcerpt.query.filter_by(style_profile_id=profile.id).delete(synchronize_session=False)
    now = datetime.now(timezone.utc)
    for index, content in enumerate(chunks):
        label = labels[index]
        db.session.add(StyleExcerpt(
            style_profile_id=profile.id,
            content=content,
            content_hash=_content_hash(content),
            source_order=index,
            scene_type=label['scene_type'],
            pov=label['pov'],
            emotion=label['emotion'],
            dialogue_ratio=_dialogue_ratio(content),
            pace=label['pace'],
            tags_json=json.dumps(label['tags'], ensure_ascii=False),
            functions_json=json.dumps(label['functions'], ensure_ascii=False),
            analysis_model=model,
            analysis_status='ready',
            created_at=now,
            updated_at=now,
        ))
    db.session.commit()
    return StyleExcerpt.query.filter_by(style_profile_id=profile.id).order_by(StyleExcerpt.source_order).all()


def get_style_excerpts(template_id):
    template = db.session.get(PromptTemplate, template_id)
    if not template:
        raise GenerationError('模板不存在')
    profile = StyleProfile.query.filter_by(template_id=template.id).first()
    if not profile:
        return []
    return StyleExcerpt.query.filter_by(style_profile_id=profile.id).order_by(StyleExcerpt.source_order).all()


def update_style_excerpt(template_id, excerpt_id, data):
    template = db.session.get(PromptTemplate, template_id)
    excerpt = db.session.get(StyleExcerpt, excerpt_id)
    if not template or not excerpt or excerpt.profile.template_id != template.id:
        raise GenerationError('参考片段不存在')
    if 'scene_type' in data:
        value = str(data['scene_type']).strip().lower()
        excerpt.scene_type = value if value in SCENE_TYPES else 'mixed'
    if 'pov' in data:
        excerpt.pov = str(data['pov']).strip()
    if 'emotion' in data:
        excerpt.emotion = str(data['emotion']).strip()
    if 'pace' in data:
        value = str(data['pace']).strip().lower()
        excerpt.pace = value if value in PACES else 'medium'
    if 'is_enabled' in data:
        excerpt.is_enabled = bool(data['is_enabled'])
    if 'is_pinned' in data:
        excerpt.is_pinned = bool(data['is_pinned'])
    excerpt.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return excerpt


def delete_style_excerpt(template_id, excerpt_id):
    excerpt = db.session.get(StyleExcerpt, excerpt_id)
    if not excerpt or excerpt.profile.template_id != template_id:
        raise GenerationError('参考片段不存在')
    db.session.delete(excerpt)
    db.session.commit()


def infer_scene_type(text):
    text = (text or '').lower()
    keyword_groups = {
        'dialogue': ('对话', '交谈', '争执', '询问', '回答', '谈判', '台词', '开口'),
        'action': ('战斗', '追逐', '逃跑', '袭击', '动作', '冲突', '搏斗', '追杀'),
        'psychology': ('心理', '内心', '回忆', '思考', '犹豫', '梦境', '意识'),
        'environment': ('环境', '景色', '清晨', '黄昏', '夜晚', '房间', '街道', '天气'),
        'transition': ('转场', '数日后', '第二天', '多年后', '与此同时', '离开', '抵达'),
    }
    scores = {key: sum(text.count(word) for word in words) for key, words in keyword_groups.items()}
    winner = max(scores, key=scores.get) if scores else 'mixed'
    return winner if scores.get(winner, 0) else 'mixed'


def _text_tokens(text):
    return set(re.findall(r'[\u4e00-\u9fff]{2}|[a-zA-Z]{3,}', (text or '').lower()))


def select_style_excerpts(profile_entries, scene_type='auto', query_text='', style_strength='light'):
    """为本次场景选择 2—4 个片段，并返回可解释评分。"""
    profile_ids = [profile.id for _, profile, _ in profile_entries]
    if not profile_ids:
        return [], 'mixed'
    target_scene = scene_type if scene_type in SCENE_TYPES else infer_scene_type(query_text)
    target_pace = {'action': 'fast', 'psychology': 'slow', 'environment': 'slow', 'dialogue': 'medium'}.get(target_scene, 'medium')
    target_dialogue = {'dialogue': .42, 'action': .14, 'psychology': .08, 'environment': .04}.get(target_scene, .18)
    profile_map = {profile.id: (template, profile, card) for template, profile, card in profile_entries}
    excerpts = StyleExcerpt.query.filter(
        StyleExcerpt.style_profile_id.in_(profile_ids), StyleExcerpt.is_enabled.is_(True)
    ).all()
    query_tokens = _text_tokens(query_text)
    candidates = []
    for excerpt in excerpts:
        template, profile, card = profile_map[excerpt.style_profile_id]
        score, reasons = 0.0, []
        if excerpt.is_pinned:
            score += 100
            reasons.append('人工置顶')
        if excerpt.scene_type == target_scene:
            score += 35
            reasons.append('场景类型一致')
        elif excerpt.scene_type == 'mixed':
            score += 8
            reasons.append('综合场景可迁移')
        card_pov = str(card.get('narration', {}).get('person', '')).strip()
        if card_pov and excerpt.pov and (card_pov in excerpt.pov or excerpt.pov in card_pov):
            score += 20
            reasons.append('叙述视角一致')
        if profile.is_primary:
            score += 20
            reasons.append('主风格模板')
        if excerpt.pace == target_pace:
            score += 10
            reasons.append('节奏接近')
        ratio_score = max(0, 10 - abs(excerpt.dialogue_ratio - target_dialogue) * 25)
        score += ratio_score
        excerpt_data = excerpt.to_dict()
        tags = excerpt_data['tags'] + excerpt_data['functions']
        overlap = query_tokens & _text_tokens(' '.join(tags) + ' ' + excerpt.emotion)
        if overlap:
            bonus = min(20, len(overlap) * 4)
            score += bonus
            reasons.append(f'语义标签命中 {len(overlap)} 项')
        candidates.append((score, excerpt, reasons, template.name))
    candidates.sort(key=lambda item: (-item[0], item[1].source_order))

    limit = {'light': 2, 'medium': 3, 'strict': 4}.get(style_strength, 2)
    selected = []
    for score, excerpt, reasons, template_name in candidates:
        tokens = _text_tokens(excerpt.content)
        too_similar = False
        for existing in selected:
            existing_tokens = _text_tokens(existing['content'])
            union = tokens | existing_tokens
            if union and len(tokens & existing_tokens) / len(union) > .55:
                too_similar = True
                break
        if too_similar and not excerpt.is_pinned:
            continue
        selected.append({
            **excerpt.to_dict(), 'score': round(score, 1), 'reasons': reasons,
            'template_name': template_name,
        })
        if len(selected) >= limit:
            break
    return selected, target_scene
