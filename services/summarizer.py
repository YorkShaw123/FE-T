"""
文本压缩/摘要服务
用于将过长的前情提要自动压缩为概述
"""
from config import Config


def should_summarize(text, threshold=None):
    """
    判断文本是否需要压缩（用于前置文章长度检测）
    :param text: 原始文本
    :param threshold: 字符数阈值，默认使用配置中的值
    :return: bool
    """
    if threshold is None:
        threshold = Config.PREVIOUS_ARTICLE_COMPRESS_THRESHOLD
    return len(text.strip()) > threshold


def summarize_text(text, client=None, model=None):
    """
    调用 LLM 压缩文本
    :param text: 原始文本
    :param client: LLMClient 实例（如果为 None 则返回简单截断）
    :param model: 模型ID
    :return: 压缩后的概述
    """
    if not text or not text.strip():
        return ''

    if client is None:
        # 无 API 客户端时，使用简单截断策略
        return simple_truncate(text)

    try:
        prompt = Config.PREVIOUS_ARTICLE_COMPRESS_PROMPT.format(content=text)
        messages = [
            {'role': 'user', 'content': prompt}
        ]

        response = client.generate(
            model=model or 'deepseek-v4-flash',
            messages=messages,
            stream=False,
            thinking_enabled=False,
            max_tokens=500,
        )

        summary = response.get('content', '').strip()
        return summary if summary else simple_truncate(text)

    except Exception:
        # 摘要失败时回退到简单截断
        return simple_truncate(text)


def simple_truncate(text, max_chars=None):
    """
    简单文本截断策略（无需API调用）
    按段落分割，每段取首句，直到达到字数限制
    """
    if not text:
        return ''
    max_chars = max_chars or Config.PREVIOUS_ARTICLE_SUMMARY_LENGTH

    if len(text) <= max_chars:
        return text

    # 保留开头建立的上下文与结尾最近发生的情节，避免续写时丢失衔接点。
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]
    head_budget = int(max_chars * 0.55)
    tail_budget = max_chars - head_budget
    head = '\n'.join(paragraphs)
    tail = head
    if len(head) > max_chars:
        head = head[:head_budget].rsplit('。', 1)[0] or head[:head_budget]
        tail = tail[-tail_budget:]
        first_stop = tail.find('。')
        if first_stop >= 0:
            tail = tail[first_stop + 1:]
    return (
        f'【前情压缩，原文{len(text)}字】\n'
        f'{head.strip()}\n……\n{tail.strip()}'
    )
