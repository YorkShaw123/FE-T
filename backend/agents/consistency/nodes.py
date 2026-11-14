"""一致性审查图的节点。

四个维度并行检查：人设、时间线、伏笔走模型，文风漂移走本地特征。
能不用模型的地方就不用——省钱、更快，也让这一维完全可解释。

所有 LLM 调用走 ``_call_model`` 一个接缝，测试替换它即可离线跑通整张图。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from backend.agents.consistency.state import ConsistencyState
from backend.core.llm_factory import LLMFactory
from backend.core.logger import get_logger
from backend.db import session_scope
from backend.db.models import PromptTemplate
from backend.services.style_feature_service import analyze_style_features

logger = get_logger(__name__)

SEVERITIES = ('blocker', 'major', 'minor')
# 句长偏离超过这个比例，算文风漂移
STYLE_DRIFT_RATIO = 0.35
# 参与漂移比较的特征：都是纯本地可算、且对中文有区分度的量
DRIFT_FEATURES = (
    ('rhythm.sentence_length.mean', '平均句长'),
    ('rhythm.short_sentence_ratio', '短句占比'),
)

CHECK_SYSTEM = (
    '你是小说编辑。只输出 JSON，不要解释。'
    '发现的问题用 {"code":"简短标识","quote":"原文片段","problem":"问题说明",'
    '"suggestion":"修改建议","severity":"blocker|major|minor"} 表示。'
    '没有问题时输出 {"findings":[]}。'
)


def _build_model(state: ConsistencyState):
    llm, _dropped = LLMFactory.get_llm(
        'consistency',
        api_key=state.get('api_key', ''),
        provider=state.get('provider'),
        model=state.get('model'),
        temperature=0,
    )
    return llm


async def _call_model(state: ConsistencyState, system_prompt: str, user_prompt: str) -> str:
    llm = _build_model(state)
    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    content = response.content
    if isinstance(content, list):
        return ''.join(
            part.get('text', '') if isinstance(part, dict) else str(part) for part in content
        )
    return content or ''


def _parse_findings(raw: str, dimension: str, default_severity: str = 'minor') -> list[dict]:
    """容错解析：模型偶尔会带围栏或前后说明。"""
    text = (raw or '').strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []

    items = payload.get('findings') if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []

    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        severity = str(item.get('severity', default_severity)).lower()
        results.append({
            'dimension': dimension,
            'code': str(item.get('code', '')).strip() or dimension,
            'quote': str(item.get('quote', '')).strip(),
            'problem': str(item.get('problem', '')).strip(),
            'suggestion': str(item.get('suggestion', '')).strip(),
            'severity': severity if severity in SEVERITIES else default_severity,
        })
    return [item for item in results if item['problem']]


# ── 节点 1：装载设定 ─────────────────────────────────────

async def load_setting_node(state: ConsistencyState) -> dict[str, Any]:
    snapshot: dict[str, list[dict[str, Any]]] = {}
    template_ids = list(state.get('template_ids') or [])

    if template_ids:
        async with session_scope() as session:
            rows = (await session.execute(
                select(PromptTemplate).where(PromptTemplate.id.in_(template_ids))
            )).scalars().all()
            for row in rows:
                snapshot.setdefault(row.category, []).append({
                    'id': row.id,
                    'name': row.name,
                    'content': row.content or '',
                })

    return {'setting_snapshot': snapshot, 'findings': [], 'errors': []}


# ── 节点 2：抽取实体 ─────────────────────────────────────

async def extract_entities_node(state: ConsistencyState) -> dict[str, Any]:
    if not state.get('api_key'):
        return {'entities': {}}

    setting_text = '\n\n'.join(
        item['content']
        for items in (state.get('setting_snapshot') or {}).values()
        for item in items
    )[:4000]
    chapter = (state.get('chapter_text') or '')[:6000]

    raw = await _call_model(
        state,
        '你是信息抽取器。只输出 JSON：{"people":[],"places":[],"items":[]}。',
        f'设定：\n{setting_text}\n\n正文：\n{chapter}',
    )
    try:
        start, end = raw.find('{'), raw.rfind('}')
        entities = json.loads(raw[start:end + 1]) if start >= 0 else {}
    except json.JSONDecodeError:
        entities = {}

    return {'entities': {
        key: [str(value) for value in (entities.get(key) or [])]
        for key in ('people', 'places', 'items')
    }}


# ── 节点 3/4/5：三个需要读懂的维度 ────────────────────────

def _review_context(state: ConsistencyState, limit: int = 6000) -> str:
    setting_text = '\n\n'.join(
        f'【{name}】\n{item["content"]}'
        for name, items in (state.get('setting_snapshot') or {}).items()
        for item in items
    )[:limit]
    chapter = (state.get('chapter_text') or '')[:limit]
    entities = state.get('entities') or {}
    entity_text = '、'.join(
        [*entities.get('people', []), *entities.get('places', []), *entities.get('items', [])]
    )
    return f'设定：\n{setting_text}\n\n正文：\n{chapter}\n\n文中实体：{entity_text or "无"}'


async def check_character_node(state: ConsistencyState) -> dict[str, Any]:
    if not state.get('api_key'):
        return {'findings': []}
    raw = await _call_model(
        state,
        CHECK_SYSTEM,
        '检查正文中的人物性格、说话方式、能力是否与设定冲突。\n\n' + _review_context(state),
    )
    return {'findings': _parse_findings(raw, 'character', 'major')}


async def check_timeline_node(state: ConsistencyState) -> dict[str, Any]:
    if not state.get('api_key'):
        return {'findings': []}
    raw = await _call_model(
        state,
        CHECK_SYSTEM,
        '检查正文中的时间顺序、因果链是否与已有设定和前文一致。\n\n' + _review_context(state),
    )
    return {'findings': _parse_findings(raw, 'timeline', 'major')}


async def check_foreshadow_node(state: ConsistencyState) -> dict[str, Any]:
    if not state.get('api_key'):
        return {'findings': []}
    raw = await _call_model(
        state,
        CHECK_SYSTEM,
        '检查正文中埋下的伏笔是否与设定冲突、是否存在已被草率处理的情况。\n\n'
        + _review_context(state),
    )
    return {'findings': _parse_findings(raw, 'foreshadow', 'minor')}


# ── 节点 6：文风漂移（纯本地，不调模型）───────────────────

def style_metrics(text: str) -> dict[str, float]:
    """取几个本地可算的特征值；算不出来的直接省略，不编造。"""
    features = analyze_style_features(text or '').get('features', {})
    metrics: dict[str, float] = {}
    for key, _label in DRIFT_FEATURES:
        value = features.get(key)
        if isinstance(value, (int, float)):
            metrics[key] = float(value)
    return metrics


async def check_style_drift_node(state: ConsistencyState) -> dict[str, Any]:
    chapter = state.get('chapter_text') or ''
    examples = [
        item['content']
        for item in (state.get('setting_snapshot') or {}).get('example', [])
    ]
    if not chapter.strip() or not examples:
        return {'findings': []}

    chapter_metrics = style_metrics(chapter)
    baseline_metrics = style_metrics('\n\n'.join(examples))

    findings = []
    for key, label in DRIFT_FEATURES:
        if key not in chapter_metrics or key not in baseline_metrics:
            continue
        base = baseline_metrics[key]
        current = chapter_metrics[key]
        if base <= 0:
            continue
        drift = abs(current - base) / base
        if drift < STYLE_DRIFT_RATIO:
            continue
        findings.append({
            'dimension': 'style_drift',
            'code': key,
            'quote': '',
            'problem': f'{label}与范例相差 {drift:.0%}：正文 {current:.2f}，范例 {base:.2f}',
            'suggestion': f'如果范例是目标文风，考虑把{label}拉回范例水平。',
            'severity': 'minor',
        })

    return {'findings': findings}


# ── 节点 7：汇总统计 ─────────────────────────────────────

def dedupe_findings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """与 State 上的 reducer 用同一套去重口径（问题 + 引文），保证两处一致。"""
    from backend.agents.consistency.state import merge_findings

    return merge_findings([], items)


async def synthesize_node(state: ConsistencyState) -> dict[str, Any]:
    """并行分支的 findings 已由 reducer 合并；这里只做统计，不改列表本身。"""
    counts = {name: 0 for name in SEVERITIES}
    for item in dedupe_findings(list(state.get('findings') or [])):
        counts[item.get('severity', 'minor')] += 1
    return {'severity_count': counts}


# ── 节点 8：生成报告 ─────────────────────────────────────

async def build_report_node(state: ConsistencyState) -> dict[str, Any]:
    findings = dedupe_findings(list(state.get('findings') or []))
    counts = state.get('severity_count') or {}

    lines = ['# 一致性审查报告', '']
    if not state.get('api_key'):
        lines.append('未提供 API Key，本次只做了文风漂移这一项本地检查。')
        lines.append('')

    if not findings:
        lines.append('没有发现明显冲突。')
        return {'report': '\n'.join(lines)}

    lines.append(
        f'共 {len(findings)} 条：阻断 {counts.get("blocker", 0)}、'
        f'重要 {counts.get("major", 0)}、次要 {counts.get("minor", 0)}。'
    )
    lines.append('')

    dimension_names = {
        'character': '人物一致性',
        'timeline': '时间线',
        'foreshadow': '伏笔',
        'style_drift': '文风漂移',
    }
    for index, item in enumerate(findings, start=1):
        lines.append(
            f"## {index}. [{item['severity']}] {dimension_names.get(item['dimension'], item['dimension'])}"
        )
        if item.get('quote'):
            lines.append(f"> 原文：{item['quote']}")
        lines.append('')
        lines.append(item['problem'])
        if item.get('suggestion'):
            lines.append('')
            lines.append(f"建议：{item['suggestion']}")
        lines.append('')

    return {'report': '\n'.join(lines).strip()}
