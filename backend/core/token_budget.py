"""上下文 Token 预算估算与超限校验（P2 公共层）。

与旧 ``server/services/token_budget.py`` 逐函数一致：不依赖厂商 tokenizer，
按"中文按字、英文按 4 字符一词、其余按 2 字符"保守估算，再乘 1.15 安全系数。

写作图把它的返回值当作条件边的判据：``status == 'over'`` 直接中止并告诉用户
哪一段超了，``warning`` 则允许继续（桌面端默认不打断）。
"""

from __future__ import annotations

import math
import re
from typing import Any

from backend.config import (
    CHAT_MESSAGE_OVERHEAD_TOKENS,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_DEAI_PROMPT,
    LLM_PROVIDERS,
    TOKEN_BUDGET_SAFETY_TOKENS,
    TOKEN_BUDGET_WARNING_RATIO,
    TOKEN_ESTIMATE_SAFETY_FACTOR,
    get_settings,
)

_CJK_PATTERN = re.compile(
    r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]'
)
_ASCII_WORD_PATTERN = re.compile(r'[A-Za-z0-9_]+')

STYLE_REFERENCE_BUDGET_CHUNK_COUNT = 5
STYLE_REFERENCE_BUDGET_CHARS_PER_CHUNK = 900

_BOLD_REWRITE_REQUIREMENTS = (
    '允许并要求对表达方式进行大幅度重写：可以大规模删改冗余措辞，拆分或合并句子，'
    '调整句序与段落结构，重写叙述、对话、动作和心理描写；不要逐句做轻微同义替换。\n'
    '重写后的文字应与上一版有明显差异，但不得删掉必要信息，不得改变剧情、事实、人物、'
    '世界观、事件顺序、人物关系、因果关系和用户要求。'
)


def build_deai_rewrite_instruction(deai_prompt: str = '') -> str:
    """语言自然化二次重写指令；正文由调用方作为上一条 assistant 消息传入。"""
    prompt = str(deai_prompt or DEFAULT_DEAI_PROMPT).strip()
    return (
        f'{prompt}\n\n'
        f'{_BOLD_REWRITE_REQUIREMENTS}\n'
        '重点清理模板化连接、重复解释、机械总结和僵硬句式，使全文像重新写过，'
        '而不是只替换几个词。\n'
        '直接输出重写后的完整文章，不要解释修改内容，不要输出分析或额外说明。'
    )


def build_style_reference_rewrite_instruction(reference_texts: list[str]) -> str:
    """RAG 风格参考二次改写指令；正文由调用方作为上一条 assistant 消息传入。"""
    references = '\n\n'.join(
        f'【参考片段 {index}】\n{text}'
        for index, text in enumerate(reference_texts, start=1)
        if str(text or '').strip()
    )
    return (
        '请对上一版文章做一次幅度明显的风格参考重写。\n\n'
        f'{_BOLD_REWRITE_REQUIREMENTS}\n'
        '应主动重塑句式、节奏、标点、语言组织、修辞和段落方式，使整体语言习惯明显贴近参考片段；'
        '不要只做少量词语替换。\n'
        '下面的片段只用于参考语言习惯；不得复制其中的人物、地点、事件、专有名词、'
        '独特表达或连续长句，也不得把参考片段的剧情带入文章。\n\n'
        f'<style_references>\n{references}\n</style_references>\n\n'
        '直接输出改写后的完整文章，不要解释修改过程，不要输出分析或额外说明。'
    )


def build_style_reference_preview_instruction() -> str:
    """固定指令预览，不伪造参考片段。"""
    return (
        '【以下是固定重写要求预览】\n'
        '初稿完成后，系统才会加入真实检索命中的 3～5 个风格片段，'
        '并在运行时附加到模型请求；'
        '本预览不伪造、不展示、也不发送占位片段。\n\n'
        '请对上一版文章做一次幅度明显的风格参考重写。\n\n'
        f'{_BOLD_REWRITE_REQUIREMENTS}\n'
        '应主动重塑句式、节奏、标点、语言组织、修辞和段落方式，'
        '不要只做少量词语替换。'
    )


def estimate_tokens(text: str | None) -> int:
    """偏保守地估算中英文混排文本的 Token 数。"""
    if not text:
        return 0
    ascii_matches = list(_ASCII_WORD_PATTERN.finditer(text))
    cjk_count = len(_CJK_PATTERN.findall(text))
    ascii_tokens = sum(max(1, math.ceil(len(item.group(0)) / 4)) for item in ascii_matches)
    ascii_chars = sum(len(item.group(0)) for item in ascii_matches)
    whitespace = sum(1 for char in text if char.isspace())
    other = max(0, len(text) - cjk_count - ascii_chars - whitespace)
    raw_estimate = cjk_count + ascii_tokens + math.ceil(other / 2)
    return max(1, math.ceil(raw_estimate * TOKEN_ESTIMATE_SAFETY_FACTOR))


def get_model_context_window(provider: str, model: str) -> int:
    for model_config in LLM_PROVIDERS.get(provider, {}).get('models', []):
        if model_config.get('id') == model:
            return int(model_config.get('context_window') or DEFAULT_CONTEXT_WINDOW)
    return DEFAULT_CONTEXT_WINDOW


def _phase_budget(
    input_tokens: int,
    context_window: int,
    output_tokens: int,
    safety_tokens: int,
) -> dict[str, Any]:
    usable = max(0, context_window - output_tokens - safety_tokens)
    remaining = usable - input_tokens
    ratio = input_tokens / usable if usable else 1.0
    status = 'over' if remaining < 0 else (
        'warning' if ratio >= TOKEN_BUDGET_WARNING_RATIO else 'safe'
    )
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
    assembled_prompt: str,
    provider: str,
    model: str,
    *,
    deai_enabled: bool = False,
    deai_prompt: str = '',
    thinking_enabled: bool = False,
    reasoning_effort: str = 'high',
    messages: list[dict[str, str]] | None = None,
    style_reference_enabled: bool = False,
    max_tokens: int = 0,
) -> dict[str, Any]:
    """计算初稿与两个可选后处理阶段的上下文预算。"""
    settings = get_settings()
    context_window = get_model_context_window(provider, model)

    reasoning_tokens = 0
    if thinking_enabled:
        reasoning_tokens = 16384 if reasoning_effort == 'max' else 8192

    requested_output = (
        max_tokens
        if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and max_tokens > 0
        else settings.default_max_tokens
    )
    output_tokens = min(requested_output + reasoning_tokens, context_window // 2)
    safety_tokens = min(TOKEN_BUDGET_SAFETY_TOKENS, context_window // 8)

    if messages:
        primary_input = sum(estimate_tokens(item.get('content', '')) for item in messages)
        primary_input += CHAT_MESSAGE_OVERHEAD_TOKENS * len(messages)
    else:
        primary_input = (
            estimate_tokens(assembled_prompt)
            + CHAT_MESSAGE_OVERHEAD_TOKENS * 2
        )

    primary = _phase_budget(primary_input, context_window, output_tokens, safety_tokens)
    phases: dict[str, Any] = {'primary': primary}
    status = primary['status']
    blocking_phase = 'primary' if status == 'over' else None

    if deai_enabled:
        instruction_tokens = estimate_tokens(build_deai_rewrite_instruction(deai_prompt))
        deai_input = (
            primary_input + output_tokens + instruction_tokens
            + CHAT_MESSAGE_OVERHEAD_TOKENS * 2
        )
        deai = _phase_budget(deai_input, context_window, output_tokens, safety_tokens)
        phases['deai'] = deai
        if deai['status'] == 'over':
            status, blocking_phase = 'over', 'deai'
        elif deai['status'] == 'warning' and status == 'safe':
            status = 'warning'

    if style_reference_enabled:
        placeholder = '示' * STYLE_REFERENCE_BUDGET_CHARS_PER_CHUNK
        rewrite_instruction_tokens = estimate_tokens(
            build_style_reference_rewrite_instruction(
                [placeholder] * STYLE_REFERENCE_BUDGET_CHUNK_COUNT
            )
        )
        rewrite_input = (
            primary_input + output_tokens + rewrite_instruction_tokens
            + CHAT_MESSAGE_OVERHEAD_TOKENS * 2
        )
        style_reference = _phase_budget(rewrite_input, context_window, output_tokens, safety_tokens)
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


def format_budget_error(budget: dict[str, Any]) -> str:
    """把超限预算翻成一句用户能看懂的话。"""
    phase = budget.get('blocking_phase') or 'primary'
    names = {
        'primary': '初稿生成',
        'deai': '语言自然化',
        'style_reference': '风格参考改写',
    }
    detail = budget.get('phases', {}).get(phase, {})
    remaining = detail.get('remaining_tokens')
    window = detail.get('context_window')
    if remaining is not None and window:
        return (
            f'本次请求上下文超出模型限制：「{names.get(phase, phase)}」阶段'
            f'还差 {abs(int(remaining))} tokens（窗口 {window}）。'
            '请减少启用的模板内容、缩短前置文章，或换用上下文更大的模型。'
        )
    return (
        f'本次请求上下文超出模型限制（{names.get(phase, phase)} 阶段）。'
        '请减少启用的模板内容、缩短前置文章，或换用上下文更大的模型。'
    )
