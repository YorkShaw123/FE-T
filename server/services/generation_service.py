"""
文章生成服务
编排完整的生成流程：组装提示词 -> 调用API -> 去AI味 -> 保存结果
"""
import json
from datetime import datetime, timezone
from database import db
from database.models import GenerationRecord
from services.prompt_assembler import (
    assemble_prompt,
    assemble_structured_messages,
    assemble_style_pipeline_messages,
    get_all_variables,
)
from services.api_client import LLMClient
from services.errors import GenerationError, friendly_error_message
from services.generation.editing import transform_article_text
from services.generation.records import delete_record, get_record, get_records, update_record
from services.summarizer import should_summarize, summarize_text
from services.token_budget import calculate_token_budget, format_budget_error
from config import Config


def utcnow():
    return datetime.now(timezone.utc)


def _build_user_message(
    templates,
    variable_values,
    custom_prefix='',
    custom_suffix='',
    previous_article='',
    summarize_client=None,
    summarize_model=None,
    use_api_summarize=False,
    style_strength='light',
):
    """
    构建完整的用户消息

    重要：剧情设定(plot)模板是设定信息，绝不压缩！
    只有传入的「前置文章」(previous_article)太长时才会压缩。

    :param previous_article: 用户手动输入的前置文章（如第一章内容）
    :param use_api_summarize: 是否使用 API 压缩前置文章（默认 False，使用本地截断）
    """
    # 剧情设定模板是设定信息，绝不压缩
    # 只对用户传入的前置文章做压缩处理
    compressed_previous = ''
    if previous_article and previous_article.strip():
        if should_summarize(previous_article):
            compressed_previous = summarize_text(
                previous_article,
                client=summarize_client if use_api_summarize else None,
                model=summarize_model,
            )
        else:
            compressed_previous = previous_article.strip()

    # 组装完整提示词
    assembled = assemble_prompt(
        templates=templates,
        variable_values=variable_values or {},
        custom_prefix=custom_prefix or '',
        custom_suffix=custom_suffix or '',
        previous_article=compressed_previous,
        style_strength=style_strength,
    )

    return assembled


def _build_structured_messages(
    templates,
    variable_values,
    custom_prefix='',
    custom_suffix='',
    previous_article='',
    style_strength='light',
):
    """构建有明确角色及内容边界的消息数组。"""
    compressed_previous = ''
    if previous_article and previous_article.strip():
        compressed_previous = (
            summarize_text(previous_article)
            if should_summarize(previous_article)
            else previous_article.strip()
        )
    return assemble_structured_messages(
        templates=templates,
        variable_values=variable_values or {},
        custom_prefix=custom_prefix or '',
        custom_suffix=custom_suffix or '',
        previous_article=compressed_previous,
        style_strength=style_strength,
        system_prompt=Config.GENERATION_SYSTEM_PROMPT,
    )


def _build_smart_style_messages(
    templates,
    variable_values,
    custom_prefix='',
    custom_suffix='',
    previous_article='',
    style_strength='light',
    scene_type='auto',
    style_corpus_ids=(),
    embedding_api_key='',
):
    """构建智能风格消息，并返回本次 Style Card 快照元数据。

    :param style_corpus_ids: Style RAG 语料库 ID 列表；非空时优先走海量语料动态检索
    :param embedding_api_key: Embedding API 密钥（与 LLM 密钥分开，用于向量化检索）
    """
    compressed_previous = ''
    if previous_article and previous_article.strip():
        compressed_previous = (
            summarize_text(previous_article)
            if should_summarize(previous_article)
            else previous_article.strip()
        )
    return assemble_style_pipeline_messages(
        templates=templates,
        variable_values=variable_values or {},
        custom_prefix=custom_prefix or '',
        custom_suffix=custom_suffix or '',
        previous_article=compressed_previous,
        style_strength=style_strength,
        system_prompt=Config.GENERATION_SYSTEM_PROMPT,
        scene_type=scene_type,
        style_corpus_ids=style_corpus_ids or (),
        embedding_api_key=embedding_api_key,
    )


def _messages_preview(messages):
    """将消息数组转换为适合保存和预览的可读文本。"""
    return '\n\n'.join(
        f'===== {item["role"].upper()} #{index} =====\n{item["content"]}'
        for index, item in enumerate(messages, start=1)
    )


def generate_article(
    templates,
    variable_values,
    api_key,
    provider='deepseek',
    model='deepseek-v4-pro',
    thinking_enabled=False,
    reasoning_effort='high',
    custom_prefix='',
    custom_suffix='',
    deai_enabled=False,
    deai_prompt='',
    title='',
    previous_article='',
    stream=False,
    style_strength='light',
    structured_prompt_enabled=False,
    style_mode='legacy',
    scene_type='auto',
    style_corpus_ids=(),
    embedding_api_key='',
):
    """
    生成文章的核心流程

    流程：
    1. 变量填充 + 前置文章压缩（如果用户传入了前置文章且超过阈值）
    2. 组装完整提示词（剧情设定模板绝不压缩）
    3. 调用 LLM 生成第一版
    4. （可选）发送去AI味提示词生成第二版
    5. 保存记录到数据库

    :param templates: 模板对象列表
    :param variable_values: 变量值字典
    :param api_key: API 密钥
    :param provider: 提供商
    :param model: 模型ID
    :param thinking_enabled: 是否启用思考模式
    :param reasoning_effort: 思考强度
    :param custom_prefix: 自定义系统提示词前缀
    :param custom_suffix: 自定义输出要求后缀
    :param deai_enabled: 是否启用去AI味
    :param deai_prompt: 去AI味提示词
    :param title: 文章标题
    :param previous_article: 前置文章内容（续写时传入之前的章节）
    :param stream: 是否流式返回（True 返回生成器，False 返回完整结果）
    :return: dict 或 generator
    """
    # 验证
    if not api_key or not api_key.strip():
        raise GenerationError('请输入API密钥')

    if not templates:
        raise GenerationError('请至少启用一个提示词模板')

    style_mode = style_mode if style_mode in {'legacy', 'smart', 'off'} else 'legacy'
    active_templates = [
        t for t in templates
        if t.is_active and not (style_mode == 'off' and t.category == 'example')
    ]
    if not active_templates:
        raise GenerationError('没有活跃的模板')
    if provider not in Config.LLM_PROVIDERS:
        raise GenerationError('不支持的模型提供商')
    if not LLMClient.validate_model(provider, model):
        raise GenerationError('所选模型与提供商不匹配，请刷新模型列表后重试')
    if reasoning_effort not in {'high', 'max'}:
        raise GenerationError('思考强度参数无效')

    # 初始化 LLM 客户端
    client = LLMClient(provider=provider, api_key=api_key.strip())

    style_metadata = {'profiles': [], 'fallback_reason': ''}
    resolved_style_mode = style_mode
    if style_mode == 'smart':
        messages, style_metadata = _build_smart_style_messages(
            templates=active_templates,
            variable_values=variable_values,
            custom_prefix=custom_prefix,
            custom_suffix=custom_suffix,
            previous_article=previous_article,
            style_strength=style_strength,
            scene_type=scene_type,
            style_corpus_ids=style_corpus_ids or (),
            embedding_api_key=embedding_api_key,
        )
        if messages:
            assembled_prompt = _messages_preview(messages)
        else:
            # 智能链缺少有效卡时回退；不阻断用户原本可用的生成流程。
            resolved_style_mode = 'smart_fallback_legacy'
    else:
        messages = None

    if messages is None and structured_prompt_enabled:
        messages = _build_structured_messages(
            templates=active_templates,
            variable_values=variable_values,
            custom_prefix=custom_prefix,
            custom_suffix=custom_suffix,
            previous_article=previous_article,
            style_strength=style_strength,
        )
        assembled_prompt = _messages_preview(messages)
    elif messages is None:
        # 兼容模式：完整保留原有“system + 单一 user 字符串”链路。
        assembled_prompt = _build_user_message(
            templates=active_templates,
            variable_values=variable_values,
            custom_prefix=custom_prefix,
            custom_suffix=custom_suffix,
            previous_article=previous_article,
            use_api_summarize=False,
            style_strength=style_strength,
        )
        messages = [
            {'role': 'system', 'content': Config.GENERATION_SYSTEM_PROMPT},
            {'role': 'user', 'content': assembled_prompt},
        ]

    token_budget = calculate_token_budget(
        assembled_prompt=assembled_prompt,
        provider=provider,
        model=model,
        deai_enabled=deai_enabled,
        deai_prompt=deai_prompt,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
        messages=messages if (structured_prompt_enabled or resolved_style_mode == 'smart') else None,
    )
    if token_budget['status'] == 'over':
        raise GenerationError(format_budget_error(token_budget))

    # 模板使用记录
    templates_used_ids = [t.id for t in active_templates]
    style_profile_snapshot = json.dumps(style_metadata, ensure_ascii=False)

    if stream:
        return _generate_stream_flow(
            client, model, messages, thinking_enabled, reasoning_effort,
            deai_enabled, deai_prompt, assembled_prompt,
            templates_used_ids, variable_values, title, provider,
            resolved_style_mode, style_profile_snapshot,
        )
    else:
        return _generate_sync_flow(
            client, model, messages, thinking_enabled, reasoning_effort,
            deai_enabled, deai_prompt, assembled_prompt,
            templates_used_ids, variable_values, title, provider,
            resolved_style_mode, style_profile_snapshot,
        )


def _generate_sync_flow(
    client, model, messages, thinking_enabled, reasoning_effort,
    deai_enabled, deai_prompt, assembled_prompt,
    templates_used_ids, variable_values, title, provider,
    style_mode, style_profile_snapshot,
):
    """同步生成流程"""
    # 第一版生成
    response1 = client.generate(
        model=model,
        messages=messages,
        stream=False,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
    )

    first_content = response1.get('content', '')
    reasoning_content = response1.get('reasoning_content', '')

    # 去AI味处理
    deai_content = ''
    if deai_enabled and first_content:
        deai_prompt_text = deai_prompt or Config.DEFAULT_DEAI_PROMPT

        deai_messages = [
            *messages,
            {'role': 'assistant', 'content': first_content},
            {
                'role': 'user',
                'content': (
                    f'{deai_prompt_text}\n\n'
                    '仅改写上一版文章，不新增设定、不改变事实与情节顺序；'
                    '直接输出完整终稿，不要解释修改内容。'
                ),
            },
        ]

        response2 = client.generate(
            model=model,
            messages=deai_messages,
            stream=False,
            thinking_enabled=False,
        )

        deai_content = response2.get('content', '')

    # 保存记录
    record = GenerationRecord(
        title=title or '未命名',
        content=first_content,
        deai_content=deai_content,
        model_used=model,
        thinking_enabled=thinking_enabled,
        reasoning_content=reasoning_content,
        assembled_prompt=assembled_prompt,
        templates_used=json.dumps(templates_used_ids),
        variable_values=json.dumps(variable_values or {}, ensure_ascii=False),
        deai_prompt=deai_prompt if deai_enabled else '',
        style_mode=style_mode,
        style_profile_snapshot=style_profile_snapshot,
        created_at=utcnow(),
    )
    db.session.add(record)
    db.session.commit()

    return {
        'success': True,
        'record': record.to_dict(),
        'first_content': first_content,
        'deai_content': deai_content,
        'reasoning_content': reasoning_content,
        'assembled_prompt': assembled_prompt,
    }


def _generate_stream_flow(
    client, model, messages, thinking_enabled, reasoning_effort,
    deai_enabled, deai_prompt, assembled_prompt,
    templates_used_ids, variable_values, title, provider,
    style_mode, style_profile_snapshot,
):
    """流式生成流程 - 返回生成器，逐chunk产出内容"""
    # 构建流式参数
    params = {
        'model': model,
        'messages': messages,
        'stream': True,
        'max_tokens': Config.DEFAULT_MAX_TOKENS,
    }

    params = client.configure_generation_params(
        params,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
    )

    # 流式生成第一版
    full_content = ''
    full_reasoning = ''

    try:
        stream_gen = client.generate_stream_aggregated(params)
        for event in stream_gen:
            if event['type'] in ('content', 'reasoning'):
                if event['type'] == 'content':
                    full_content += event['data']
                elif event['type'] == 'reasoning':
                    full_reasoning += event['data']
                yield event
            elif event['type'] == 'done':
                break

        # 去AI味处理（如果需要）
        deai_content = ''
        if deai_enabled and full_content:
            yield {'type': 'status', 'data': 'deai_start'}
            deai_prompt_text = deai_prompt or Config.DEFAULT_DEAI_PROMPT

            deai_messages = [
                *messages,
                {'role': 'assistant', 'content': full_content},
                {
                    'role': 'user',
                    'content': (
                        f'{deai_prompt_text}\n\n'
                        '仅改写上一版文章，不新增设定、不改变事实与情节顺序；'
                        '直接输出完整终稿，不要解释修改内容。'
                    ),
                },
            ]

            deai_params = {
                'model': model,
                'messages': deai_messages,
                'stream': True,
                'max_tokens': Config.DEFAULT_MAX_TOKENS,
            }
            deai_params = client.configure_generation_params(
                deai_params,
                thinking_enabled=False,
                reasoning_effort='high',
            )

            deai_stream = client.generate_stream_aggregated(deai_params)
            for event in deai_stream:
                if event['type'] == 'content':
                    deai_content += event['data']
                    yield event
                elif event['type'] == 'done':
                    break
            yield {'type': 'status', 'data': 'deai_done'}

        # 保存记录到数据库
        record = GenerationRecord(
            title=title or '未命名',
            content=full_content,
            deai_content=deai_content,
            model_used=model,
            thinking_enabled=thinking_enabled,
            reasoning_content=full_reasoning,
            assembled_prompt=assembled_prompt,
            templates_used=json.dumps(templates_used_ids),
            variable_values=json.dumps(variable_values or {}, ensure_ascii=False),
            deai_prompt=deai_prompt if deai_enabled else '',
            style_mode=style_mode,
            style_profile_snapshot=style_profile_snapshot,
            created_at=utcnow(),
        )
        db.session.add(record)
        db.session.commit()

        # 发送完成事件
        yield {
            'type': 'complete',
            'record_id': record.id,
            'reasoning_content': full_reasoning,
            'first_content': full_content,
            'deai_content': deai_content,
        }

    except Exception as e:
        db.session.rollback()
        # 流内错误：发送错误事件（转换为用户能看懂的中文）
        error_msg = friendly_error_message(e)
        yield {
            'type': 'error',
            'data': error_msg,
        }


def get_assembled_preview(
    templates,
    variable_values=None,
    custom_prefix='',
    custom_suffix='',
    previous_article='',
    style_strength='light',
    provider='deepseek',
    model='deepseek-v4-pro',
    deai_enabled=False,
    deai_prompt='',
    thinking_enabled=False,
    reasoning_effort='high',
    structured_prompt_enabled=False,
    style_mode='legacy',
    scene_type='auto',
    style_corpus_ids=(),
    embedding_api_key='',
):
    """
    预览组装后的提示词（不调用API）
    """
    style_mode = style_mode if style_mode in {'legacy', 'smart', 'off'} else 'legacy'
    active_templates = [
        t for t in templates
        if t.is_active and not (style_mode == 'off' and t.category == 'example')
    ]
    style_metadata = {'profiles': [], 'fallback_reason': ''}
    resolved_style_mode = style_mode

    if style_mode == 'smart':
        messages, style_metadata = _build_smart_style_messages(
            templates=active_templates,
            variable_values=variable_values or {},
            custom_prefix=custom_prefix,
            custom_suffix=custom_suffix,
            previous_article=previous_article,
            style_strength=style_strength,
            scene_type=scene_type,
            style_corpus_ids=style_corpus_ids or (),
            embedding_api_key=embedding_api_key,
        )
        if messages:
            assembled = _messages_preview(messages)
        else:
            resolved_style_mode = 'smart_fallback_legacy'
    else:
        messages = None

    if messages is None and structured_prompt_enabled:
        messages = _build_structured_messages(
            templates=active_templates,
            variable_values=variable_values or {},
            custom_prefix=custom_prefix,
            custom_suffix=custom_suffix,
            previous_article=previous_article,
            style_strength=style_strength,
        )
        assembled = _messages_preview(messages)
    elif messages is None:
        assembled = _build_user_message(
            templates=active_templates,
            variable_values=variable_values or {},
            custom_prefix=custom_prefix,
            custom_suffix=custom_suffix,
            previous_article=previous_article,
            style_strength=style_strength,
        )

    all_vars = get_all_variables(active_templates)
    token_budget = calculate_token_budget(
        assembled_prompt=assembled,
        provider=provider,
        model=model,
        deai_enabled=deai_enabled,
        deai_prompt=deai_prompt,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
        messages=messages,
    )

    return {
        'assembled_prompt': assembled,
        'variables': all_vars,
        'template_count': len(active_templates),
        'char_count': len(assembled),
        'token_budget': token_budget,
        'prompt_mode': (
            'smart-style' if resolved_style_mode == 'smart'
            else ('structured' if structured_prompt_enabled else 'legacy')
        ),
        'style_mode': resolved_style_mode,
        'style_metadata': style_metadata,
        'message_count': len(messages) if messages else 2,
    }
