"""生成结果的局部续写、重写、扩写与润色。"""

from config import Config
from services.api_client import LLMClient
from services.errors import GenerationError


OPERATION_PROMPTS = {
    'continue': (
        '在所选原文之后自然续写。输出必须包含原文以及新增的续写内容，'
        '以便直接替换所选片段。保持人物、视角、时态和语言风格一致。'
    ),
    'rewrite': (
        '重新表达所选原文，保留事实、人物关系、情节结果与核心含义，'
        '改善表达和节奏。只输出可替换原文的新版本。'
    ),
    'expand': (
        '扩写所选原文，补充合理的动作、感官、情绪或环境细节，'
        '不得增加与上下文冲突的新设定。只输出扩写后的完整替换文本。'
    ),
    'polish': (
        '润色所选原文，修正语病、重复、僵硬衔接和不自然措辞，'
        '尽量保持原意、篇幅和作者语气。只输出润色后的完整替换文本。'
    ),
}


def transform_article_text(text, operation, instruction, surrounding_context, api_key, provider, model):
    """对选中文字执行局部编辑，返回统一的 LLM 响应。"""
    if operation not in OPERATION_PROMPTS:
        raise GenerationError('不支持的局部处理方式')
    if not text or not text.strip():
        raise GenerationError('请先选择需要处理的文字')
    if len(text) > 12000:
        raise GenerationError('单次处理的选中文字不能超过12000字')
    if not api_key or not api_key.strip():
        raise GenerationError('请输入API密钥')
    if provider not in Config.LLM_PROVIDERS:
        raise GenerationError('不支持的模型提供商')
    if not LLMClient.validate_model(provider, model):
        raise GenerationError('所选模型与提供商不匹配')

    context = (surrounding_context or '').strip()
    user_content = (
        f'【任务】\n{OPERATION_PROMPTS[operation]}\n\n'
        f'【上下文，仅用于理解，不要重复输出】\n{context or "无"}\n\n'
        f'【所选原文】\n{text.strip()}'
    )
    if instruction and instruction.strip():
        user_content += f'\n\n【用户附加要求】\n{instruction.strip()}'

    client = LLMClient(provider=provider, api_key=api_key.strip())
    return client.generate(
        model=model,
        messages=[
            {
                'role': 'system',
                'content': (
                    '你是一名专业中文文学编辑。严格执行局部编辑任务，'
                    '只输出可以直接放回正文的文本，不解释、不加标题、不使用代码块。'
                ),
            },
            {'role': 'user', 'content': user_content},
        ],
        stream=False,
        thinking_enabled=False,
    )

