"""
文章生成 API 路由
"""
import json
from xml.etree import ElementTree
from flask import Blueprint, request, jsonify, Response, stream_with_context
from services.generation_service import (
    generate_article,
    get_record,
    get_records,
    update_record,
    delete_record,
    get_assembled_preview,
    transform_article_text,
)
from services.generation.records import delete_all_records
from services.errors import GenerationError, friendly_error_message
from services.operation_guard import acquire_model_operation, release_model_operation
from config import Config
from routes.support.document_text import extract_uploaded_text
from routes.support.generation_request import GenerationRequest

generation_bp = Blueprint('generation', __name__, url_prefix='/api/generation')

@generation_bp.route('/extract-text', methods=['POST'])
def extract_article_text():
    """提取用户上传的前置文章文本。"""
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return jsonify({'success': False, 'error': '请选择要导入的文件'}), 400

    try:
        text = extract_uploaded_text(uploaded)
        return jsonify({
            'success': True,
            'data': {'text': text, 'char_count': len(text), 'filename': uploaded.filename},
        })
    except OverflowError as exc:
        return jsonify({'success': False, 'error': friendly_error_message(exc)}), 413
    except (ValueError, ElementTree.ParseError) as exc:
        return jsonify({'success': False, 'error': friendly_error_message(exc)}), 400


@generation_bp.route('/models', methods=['GET'])
def get_models():
    """获取可用模型列表"""
    providers = {}
    for key, provider_config in Config.LLM_PROVIDERS.items():
        providers[key] = {
            'name': provider_config['name'],
            'models': provider_config['models'],
        }
    return jsonify({
        'success': True,
        'data': providers,
    })


@generation_bp.route('/categories', methods=['GET'])
def get_categories():
    """获取模板分类定义"""
    return jsonify({
        'success': True,
        'data': Config.TEMPLATE_CATEGORIES,
    })


@generation_bp.route('/default-deai-prompt', methods=['GET'])
def get_default_deai_prompt():
    """获取默认的去AI味提示词"""
    return jsonify({
        'success': True,
        'data': Config.DEFAULT_DEAI_PROMPT,
    })


@generation_bp.route('/transform-text', methods=['POST'])
def transform_text():
    """对生成结果中选中的局部文字进行AI处理。"""
    try:
        data = request.get_json() or {}
        api_key = data.get('api_key', '').strip()
        if not api_key:
            return jsonify({'success': False, 'error': '请输入API密钥'}), 400

        acquire_model_operation()
        try:
            result = transform_article_text(
                text=data.get('text', ''),
                operation=data.get('operation', 'rewrite'),
                instruction=data.get('instruction', ''),
                surrounding_context=data.get('surrounding_context', ''),
                api_key=api_key,
                provider=data.get('provider', 'deepseek'),
                model=data.get('model', 'deepseek-v4-pro'),
            )
        finally:
            release_model_operation()
        return jsonify({
            'success': True,
            'data': {
                'content': result.get('content', ''),
                'usage': result.get('usage', {}),
            },
        })
    except (GenerationError, Exception) as exc:
        status = 400 if isinstance(exc, GenerationError) else 500
        return jsonify({'success': False, 'error': friendly_error_message(exc)}), status


@generation_bp.route('/generate', methods=['POST'])
def generate():
    """
    同步生成文章
    同时支持去AI味处理
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'}), 400

        generation_request = GenerationRequest.from_mapping(data)
        acquire_model_operation()
        try:
            result = generate_article(**generation_request.generation_kwargs(stream=False))
        finally:
            release_model_operation()

        return jsonify(result), 200

    except GenerationError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': friendly_error_message(e)}), 500


@generation_bp.route('/generate-stream', methods=['POST'])
def generate_stream():
    """
    流式生成文章（Server-Sent Events）
    前端通过 ReadableStream 接收逐字输出
    """
    operation_acquired = False
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'}), 400

        generation_request = GenerationRequest.from_mapping(data)
        if not generation_request.api_key.strip():
            return jsonify({'success': False, 'error': '请输入API密钥'}), 400

        acquire_model_operation()
        operation_acquired = True
        # 获取流式生成器
        stream_gen = generate_article(**generation_request.generation_kwargs(stream=True))

        def sse_events():
            """生成 SSE 格式的事件流"""
            try:
                for event in stream_gen:
                    event_type = event.get('type', 'content')
                    if event_type == 'complete':
                        payload = {
                            'type': 'complete',
                            'record_id': event.get('record_id'),
                            'reasoning_content': event.get('reasoning_content', ''),
                            'first_content': event.get('first_content', ''),
                            'deai_content': event.get('deai_content', ''),
                        }
                        yield f"event: complete\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    elif event_type == 'error':
                        error_payload = {
                            'type': 'error',
                            'data': event.get('data', '未知错误'),
                        }
                        yield f"event: error\ndata: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
                    else:
                        event_data = event.get('data', '')
                        yield f"event: {event_type}\ndata: {json.dumps({'type': event_type, 'data': event_data}, ensure_ascii=False)}\n\n"

                # 最终完成
                yield "event: done\ndata: {}\n\n"
            finally:
                close_stream = getattr(stream_gen, 'close', None)
                if callable(close_stream):
                    close_stream()
                release_model_operation()

        return Response(
            stream_with_context(sse_events()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
            },
        )

    except GenerationError as e:
        if operation_acquired:
            release_model_operation()
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        if operation_acquired:
            release_model_operation()
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': friendly_error_message(e)}), 500


@generation_bp.route('/preview-prompt', methods=['POST'])
def preview_prompt():
    """预览组装后的提示词"""
    try:
        data = request.get_json() or {}
        generation_request = GenerationRequest.from_mapping(data)
        preview = get_assembled_preview(**generation_request.preview_kwargs())

        return jsonify({
            'success': True,
            'data': preview,
        })
    except GenerationError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': friendly_error_message(e)}), 500


# ==================== 生成记录管理 ====================

@generation_bp.route('/records', methods=['GET'])
def list_records():
    """获取生成记录列表"""
    page = request.args.get('page', 1, type=int)
    per_page = min(max(request.args.get('per_page', 50, type=int), 1), 100)

    result = get_records(page=page, per_page=per_page)
    return jsonify({
        'success': True,
        'data': result,
    })


@generation_bp.route('/records/<int:record_id>', methods=['GET'])
def get_single_record(record_id):
    """获取单条生成记录"""
    record = get_record(record_id)
    if not record:
        return jsonify({'success': False, 'error': '记录不存在'}), 404
    return jsonify({
        'success': True,
        'data': record.to_dict(),
    })


@generation_bp.route('/records/<int:record_id>', methods=['PUT'])
def edit_record(record_id):
    """更新生成记录"""
    try:
        data = request.get_json() or {}
        record = update_record(record_id, **data)
        return jsonify({
            'success': True,
            'data': record.to_dict(),
        })
    except GenerationError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@generation_bp.route('/records/<int:record_id>', methods=['DELETE'])
def remove_record(record_id):
    """删除生成记录"""
    try:
        delete_record(record_id)
        return jsonify({'success': True})
    except GenerationError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@generation_bp.route('/records', methods=['DELETE'])
def remove_all_records():
    """删除所有生成记录"""
    try:
        delete_all_records()
        return jsonify({'success': True, 'deleted': True})
    except Exception as e:
        return jsonify({'success': False, 'error': friendly_error_message(e)}), 500
