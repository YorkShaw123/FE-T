"""模型上下文 Token 预算估算与超限校验。"""
import math
import re

from config import Config


_CJK_PATTERN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]')
_ASCII_WORD_PATTERN = re.compile(r'[A-Za-z0-9_]+')
STYLE_REFERENCE_BUDGET_CHUNK_COUNT = 4
STYLE_REFERENCE_BUDGET_CHARS_PER_CHUNK = 900


def build_style_reference_rewrite_instruction(reference_texts):
    """构造 RAG 风格参考二次改写指令；正文由调用方作为上一条 assistant 消息传入。"""
    references = '\n\n'.join(
        f'【参考片段 {index}】\n{text}'
        for index, text in enumerate(reference_texts, start=1)
        if str(text or '').strip()
    )
    return (
        '请仅对上一版文章做一次风格参考重写。\n\n'
        '必须保持：剧情、事实、人物、世界观、已有信息、事件顺序和用户要求。\n'
        '只允许调整：句式、节奏、标点、语言组织、修辞和段落方式。\n'
        '下面的片段只用于参考语言习惯；不得复制其中的人物、地点、事件、专有名词、'
        '独特表达或连续长句，也不得把参考片段的剧情带入文章。\n\n'
        f'<style_references>\n{references}\n</style_references>\n\n'
        '直接输出改写后的完整文章，不要解释修改过程，不要输出分析或额外说明。'
    )


def estimate_tokens(text):
    """偏保守地估算中英文混合文本 Token 数，不依赖特定厂商 tokenizer。"""
    if not text:
        return 0
    ascii_matches = list(_ASCII_WORD_PATTERN.finditer(text))
    cjk_count = len(_CJK_PATTERN.findall(text))
    ascii_tokens = sum(max(1, math.ceil(len(item.group(0)) / 4)) for item in ascii_matches)
    ascii_chars = sum(len(item.group(0)) for item in ascii_matches)
    whitespace = sum(1 for char in text if char.isspace())
    other = max(0, len(text) - cjk_count - ascii_chars - whitespace)
    raw_estimate = cjk_count + ascii_tokens + math.ceil(other / 2)
    return max(1, math.ceil(raw_estimate * Config.TOKEN_ESTIMATE_SAFETY_FACTOR))


def get_model_context_window(provider, model):
    for model_config in Config.LLM_PROVIDERS.get(provider, {}).get('models', []):
        if model_config.get('id') == model:
            return int(model_config.get('context_window') or Config.DEFAULT_CONTEXT_WINDOW)
    return Config.DEFAULT_CONTEXT_WINDOW


def _phase_budget(input_tokens, context_window, output_tokens, safety_tokens):
    usable = max(0, context_window - output_tokens - safety_tokens)
    remaining = usable - input_tokens
    ratio = input_tokens / usable if usable else 1.0
    status = 'over' if remaining < 0 else ('warning' if ratio >= Config.TOKEN_BUDGET_WARNING_RATIO else 'safe')
    return {
        'input_tokens': input_tokens,
        'context_window': context_window,
        'output_reserved_tokens': output_tokens,
        'safety_reserved_tokens': safety_tokens,
        'usable_input_tokens': usable,
        'remaining_tokens': remaining,
        'usage_ratio': round(ratio, 4),
        'status': status,
    }


def calculate_token_budget(
    assembled_prompt,
    provider,
    model,
    deai_enabled=False,
    deai_prompt='',
    thinking_enabled=False,
    reasoning_effort='high',
    messages=None,
    style_reference_enabled=False,
    strict_style_rewrite_enabled=False,
    max_tokens=0,
):
    """计算正文生成及可选二次润色阶段的上下文预算。"""
    context_window = get_model_context_window(provider, model)
    reasoning_tokens = 0
    if thinking_enabled:
        reasoning_tokens = 16384 if reasoning_effort == 'max' else 8192
    requested_output_tokens = (
        max_tokens
        if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and max_tokens > 0
        else Config.DEFAULT_MAX_TOKENS
    )
    output_tokens = min(requested_output_tokens + reasoning_tokens, context_window // 2)
    safety_tokens = min(Config.TOKEN_BUDGET_SAFETY_TOKENS, context_window // 8)
    if messages:
        primary_input = sum(estimate_tokens(item.get('content', '')) for item in messages)
        primary_input += Config.CHAT_MESSAGE_OVERHEAD_TOKENS * len(messages)
    else:
        primary_input = (
            estimate_tokens(assembled_prompt)
            + estimate_tokens(Config.GENERATION_SYSTEM_PROMPT)
            + Config.CHAT_MESSAGE_OVERHEAD_TOKENS * 2
        )
    primary = _phase_budget(primary_input, context_window, output_tokens, safety_tokens)
    phases = {'primary': primary}
    status = primary['status']
    blocking_phase = 'primary' if status == 'over' else None

    if deai_enabled:
        instruction_tokens = estimate_tokens(deai_prompt or Config.DEFAULT_DEAI_PROMPT)
        deai_input = primary_input + output_tokens + instruction_tokens + Config.CHAT_MESSAGE_OVERHEAD_TOKENS * 2
        deai = _phase_budget(deai_input, context_window, output_tokens, safety_tokens)
        phases['deai'] = deai
        if deai['status'] == 'over':
            status, blocking_phase = 'over', 'deai'
        elif deai['status'] == 'warning' and status == 'safe':
            status = 'warning'

    # strict_style_rewrite_enabled 仅保留为旧 API 的兼容别名。
    if style_reference_enabled or strict_style_rewrite_enabled:
        placeholder = '示' * STYLE_REFERENCE_BUDGET_CHARS_PER_CHUNK
        rewrite_instruction_tokens = estimate_tokens(build_style_reference_rewrite_instruction(
            [placeholder] * STYLE_REFERENCE_BUDGET_CHUNK_COUNT
        ))
        rewrite_input = (
            primary_input + output_tokens + rewrite_instruction_tokens
            + Config.CHAT_MESSAGE_OVERHEAD_TOKENS * 2
        )
        style_reference = _phase_budget(
            rewrite_input, context_window, output_tokens, safety_tokens
        )
        phases['style_reference'] = style_reference
        if style_reference['status'] == 'over':
            status, blocking_phase = 'over', 'style_reference'
        elif style_reference['status'] == 'warning' and status == 'safe':
            status = 'warning'

    return {
        'estimated': True,
        'provider': provider,
        'model': model,
        'reasoning_reserved_tokens': reasoning_tokens,
        'status': status,
        'blocking_phase': blocking_phase,
        'phases': phases,
    }


def format_budget_error(budget):
    phase_key = budget.get('blocking_phase') or 'primary'
    phase_names = {
        'primary': '正文生成',
        'deai': '去 AI 味二次处理',
        'style_reference': '风格参考二次改写',
    }
    phase_name = phase_names.get(phase_key, '正文生成')
    phase = budget['phases'][phase_key]
    exceeded = abs(min(0, phase['remaining_tokens']))
    return (
        f'{phase_name}预计超出模型上下文预算约 {exceeded:,} Token。'
        f'当前预计输入 {phase["input_tokens"]:,}，可用输入预算 {phase["usable_input_tokens"]:,}'
        f'（模型窗口 {phase["context_window"]:,}，已预留输出 {phase["output_reserved_tokens"]:,}'
        f' 和安全余量 {phase["safety_reserved_tokens"]:,}）。'
        '请减少模板、前置文章或关闭二次处理。'
    )
