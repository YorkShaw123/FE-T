"""范例文章 Style Card 的分析、校验与持久化。"""
import copy
import hashlib
import json
from datetime import datetime, timezone

from database import db
from database.models import PromptTemplate, StyleExcerpt, StyleProfile
from services.api_client import LLMClient
from services.errors import GenerationError, friendly_error_message


STYLE_CARD_SCHEMA_VERSION = 1
REQUIRED_OBJECTS = ('narration', 'rhythm', 'language', 'dialogue', 'description_balance')
DEFAULT_CARD = {
    'schema_version': STYLE_CARD_SCHEMA_VERSION,
    'summary': '',
    'narration': {
        'person': '', 'distance': '', 'tense': '', 'pov_rules': [],
    },
    'rhythm': {
        'sentence_pattern': '', 'paragraph_pattern': '', 'transition_style': '',
    },
    'language': {
        'register': '', 'imagery': '', 'rhetoric_frequency': '',
        'preferred_behaviors': [],
    },
    'dialogue': {
        'ratio': '', 'length': '', 'subtext': '', 'tag_style': '',
    },
    'description_balance': {
        'action': '', 'dialogue': '', 'psychology': '', 'environment': '',
    },
    'avoid': [],
    'checkable_rules': [],
}


STYLE_ANALYSIS_SYSTEM_PROMPT = """你是一名文学风格分析器。你的任务不是总结故事内容，而是将
参考文本转换为可迁移、可执行、可检查的写作规则。禁止使用“优美、细腻、有感染力、很有画面感”
等模糊评价。只输出一个合法 JSON 对象，不要 Markdown 代码块、解释或前后缀。"""


def style_source_hash(content):
    return hashlib.sha256((content or '').strip().encode('utf-8')).hexdigest()


def _analysis_prompt(content):
    schema = json.dumps(DEFAULT_CARD, ensure_ascii=False, indent=2)
    return f"""请忽略参考文本的故事内容，只分析可迁移的语言机制。

必须提取：叙述视角与距离、句长与停顿、段落组织、转场方式、对话比例与潜台词、动作/心理/环境
描写比例、修辞频率、正向写作行为、明确禁用表达，以及至少 8 条可检查规则。

checkable_rules 每项格式：
{{"id":"唯一规则ID","rule":"具体规则","priority":"hard|high|medium"}}

严格沿用下面的 JSON 字段结构；未知值使用空字符串或空数组，不得新增故事人物、地点或情节：
{schema}

<reference_text>
{content.strip()}
</reference_text>"""


def _extract_json_object(text):
    raw = (text or '').strip()
    if raw.startswith('```'):
        raw = raw.strip('`').strip()
        if raw.lower().startswith('json'):
            raw = raw[4:].strip()
    start = raw.find('{')
    end = raw.rfind('}')
    if start < 0 or end <= start:
        raise GenerationError('风格分析没有返回有效 JSON')
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise GenerationError('风格分析结果不是有效的 JSON 格式，请重试') from exc


def _extract_response_json(response):
    """优先解析正文；正文无有效 JSON 时兼容固定思考模型的 reasoning 字段。"""
    errors = []
    for field in ('content', 'reasoning_content'):
        candidate = response.get(field, '') if isinstance(response, dict) else ''
        if not str(candidate or '').strip():
            continue
        try:
            return _extract_json_object(candidate)
        except GenerationError as exc:
            errors.append(exc)
    if errors:
        raise errors[-1]
    raise GenerationError('风格分析没有返回有效 JSON')


def validate_style_card(card):
    if not isinstance(card, dict):
        raise GenerationError('Style Card 必须是 JSON 对象')
    # 保留旧版或用户手工加入的扩展字段，只校验并补齐 V1 已知字段。
    normalized = copy.deepcopy(card)
    normalized['schema_version'] = STYLE_CARD_SCHEMA_VERSION
    summary = card.get('summary', '')
    if summary is None:
        summary = ''
    if not isinstance(summary, str):
        raise GenerationError('Style Card 的 summary 必须是字符串')
    normalized['summary'] = summary.strip()
    for key in REQUIRED_OBJECTS:
        source = card.get(key, {})
        if source is None:
            source = {}
        if not isinstance(source, dict):
            raise GenerationError(f'Style Card 的 {key} 必须是对象')
        normalized[key] = copy.deepcopy(source)
        for field, default in DEFAULT_CARD[key].items():
            value = source.get(field, copy.deepcopy(default))
            if value is None:
                value = copy.deepcopy(default)
            if isinstance(default, list):
                if not isinstance(value, list):
                    raise GenerationError(f'Style Card 的 {key}.{field} 必须是数组')
                normalized[key][field] = [
                    str(item).strip() for item in value if str(item).strip()
                ]
            else:
                if not isinstance(value, str):
                    raise GenerationError(f'Style Card 的 {key}.{field} 必须是字符串')
                normalized[key][field] = value.strip()
    for key in ('avoid', 'checkable_rules'):
        value = card.get(key, [])
        if value is None:
            value = []
        if not isinstance(value, list):
            raise GenerationError(f'Style Card 的 {key} 必须是数组')
        normalized[key] = value
    rules = []
    for index, item in enumerate(normalized['checkable_rules'], start=1):
        if isinstance(item, str):
            item = {'id': f'rule_{index:02d}', 'rule': item, 'priority': 'medium'}
        if not isinstance(item, dict) or not str(item.get('rule', '')).strip():
            raise GenerationError('每条 checkable_rules 都必须包含 rule')
        priority = item.get('priority', 'medium')
        if priority not in {'hard', 'high', 'medium'}:
            priority = 'medium'
        rules.append({
            'id': str(item.get('id') or f'rule_{index:02d}'),
            'rule': str(item['rule']).strip(),
            'priority': priority,
        })
    normalized['checkable_rules'] = rules
    normalized['avoid'] = [str(item).strip() for item in normalized['avoid'] if str(item).strip()]
    return normalized


def get_style_profile(template_id):
    template = db.session.get(PromptTemplate, template_id)
    if not template:
        raise GenerationError('模板不存在')
    profile = StyleProfile.query.filter_by(template_id=template.id).first()
    return template, profile


def analyze_style_profile(template_id, api_key, provider, model):
    template = db.session.get(PromptTemplate, template_id)
    if not template:
        raise GenerationError('模板不存在')
    if template.category != 'example':
        raise GenerationError('只有范例文章模板可以生成 Style Card')
    if len((template.content or '').strip()) < 100:
        raise GenerationError('范例文章过短，至少需要 100 个字符才能分析风格')
    if not api_key or not api_key.strip():
        raise GenerationError('请先输入 API 密钥')

    profile = StyleProfile.query.filter_by(template_id=template.id).first()
    if not profile:
        profile = StyleProfile(
            template_id=template.id,
            template_version=template.version,
            source_hash=style_source_hash(template.content),
            analysis_status='analyzing',
        )
        db.session.add(profile)
    else:
        profile.analysis_status = 'analyzing'
        profile.error_message = ''
    db.session.commit()

    try:
        client = LLMClient(provider=provider, api_key=api_key)
        response = client.generate(
            model=model,
            messages=[
                {'role': 'system', 'content': STYLE_ANALYSIS_SYSTEM_PROMPT},
                {'role': 'user', 'content': _analysis_prompt(template.content)},
            ],
            stream=False,
            thinking_enabled=False,
            max_tokens=4096,
        )
        card = validate_style_card(_extract_response_json(response))
        card_json = json.dumps(card, ensure_ascii=False, indent=2)
        previous_source_hash = profile.source_hash
        profile.template_version = template.version
        profile.source_hash = style_source_hash(template.content)
        profile.schema_version = STYLE_CARD_SCHEMA_VERSION
        profile.analysis_card_json = card_json
        profile.card_json = card_json
        profile.analysis_model = model
        profile.analysis_status = 'ready'
        profile.error_message = ''
        profile.updated_at = datetime.now(timezone.utc)
        if previous_source_hash and previous_source_hash != profile.source_hash:
            StyleExcerpt.query.filter_by(style_profile_id=profile.id).delete(
                synchronize_session=False,
            )
        db.session.commit()
        return profile
    except Exception as exc:
        db.session.rollback()
        profile = StyleProfile.query.filter_by(template_id=template.id).first()
        if profile:
            try:
                previous_card = json.loads(profile.card_json or '{}')
            except (TypeError, json.JSONDecodeError):
                previous_card = {}
            has_previous_card = isinstance(previous_card, dict) and bool(previous_card)
            profile.analysis_status = 'ready' if has_previous_card else 'error'
            profile.error_message = friendly_error_message(exc)
            db.session.commit()
        if isinstance(exc, GenerationError):
            raise
        raise GenerationError(f'风格分析失败：{friendly_error_message(exc)}') from exc


def update_style_profile(template_id, card, is_primary=None):
    template, profile = get_style_profile(template_id)
    if template.category != 'example':
        raise GenerationError('只有范例文章模板可以保存 Style Card')
    if not profile:
        raise GenerationError('请先分析该范例文章')
    normalized = validate_style_card(card)
    profile.card_json = json.dumps(normalized, ensure_ascii=False, indent=2)
    profile.analysis_status = 'ready'
    profile.error_message = ''
    if is_primary is not None:
        if bool(is_primary):
            StyleProfile.query.filter(StyleProfile.id != profile.id).update(
                {'is_primary': False}, synchronize_session=False
            )
        profile.is_primary = bool(is_primary)
    profile.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return profile


def restore_analysis_card(template_id):
    template, profile = get_style_profile(template_id)
    if not profile or not profile.analysis_card_json:
        raise GenerationError('没有可恢复的自动分析结果')
    try:
        stored_card = json.loads(profile.analysis_card_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GenerationError('自动分析结果已损坏，请重新分析') from exc
    card = validate_style_card(stored_card)
    profile.card_json = json.dumps(card, ensure_ascii=False, indent=2)
    profile.analysis_status = 'ready'
    profile.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return profile
