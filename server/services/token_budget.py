"""模型上下文 Token 预算估算与超限校验。"""
import math
import re

from config import Config


_CJK_PATTERN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]')
_ASCII_WORD_PATTERN = re.compile(r'[A-Za-z0-9_]+')


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
):
    """计算正文生成及可选二次润色阶段的上下文预算。"""
    context_window = get_model_context_window(provider, model)
    reasoning_tokens = 0
    if thinking_enabled:
        reasoning_tokens = 16384 if reasoning_effort == 'max' else 8192
    output_tokens = min(Config.DEFAULT_MAX_TOKENS + reasoning_tokens, context_window // 2)
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
    phase_name = '去 AI 味二次处理' if phase_key == 'deai' else '正文生成'
    phase = budget['phases'][phase_key]
    exceeded = abs(min(0, phase['remaining_tokens']))
    return (
        f'{phase_name}预计超出模型上下文预算约 {exceeded:,} Token。'
        f'当前预计输入 {phase["input_tokens"]:,}，可用输入预算 {phase["usable_input_tokens"]:,}'
        f'（模型窗口 {phase["context_window"]:,}，已预留输出 {phase["output_reserved_tokens"]:,}'
        f' 和安全余量 {phase["safety_reserved_tokens"]:,}）。'
        '请减少模板、前置文章或关闭二次处理。'
    )
