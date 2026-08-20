"""风格语料库（Style RAG）API：语料管理、导入、向量化与检索测试。"""
from flask import Blueprint, jsonify, request

from routes.support.document_text import extract_uploaded_text
from services.errors import GenerationError, friendly_error_message
from services.operation_guard import acquire_model_operation, release_model_operation
from services.style_index_progress import (
    fail_index_progress,
    finish_index_progress,
    get_index_progress,
    start_index_progress,
    update_index_progress,
)
from services.style_rag_service import (
    clear_corpus_chunks,
    create_corpus,
    delete_corpus,
    get_corpus,
    hybrid_search_style,
    import_corpus_text,
    index_corpus,
    list_chunks,
    list_corpora,
    update_corpus,
)


style_corpora_bp = Blueprint('style_corpora', __name__, url_prefix='/api/style-corpora')


@style_corpora_bp.route('/embedding-config', methods=['GET'])
def embedding_config():
    """返回 Embedding 提供商配置（前端展示用）。"""
    from config import Config
    from services.embedding_backends import (
        LOCAL_EMBEDDING_DIMENSION,
        LOCAL_MODEL_ID,
        LOCAL_MODEL_VERSION,
    )
    return jsonify({'success': True, 'data': {
        'provider': Config.EMBEDDING_PROVIDER,
        'model': Config.EMBEDDING_MODEL,
        'dimensions': Config.EMBEDDING_DIMENSIONS,
        'default_backend': 'local',
        'remote_compatible': True,
        'local': {
            'model': LOCAL_MODEL_ID,
            'model_version': LOCAL_MODEL_VERSION,
            'dimensions': LOCAL_EMBEDDING_DIMENSION,
            'runtime': 'onnxruntime-cpu',
            'bundled': False,
        },
    }})


@style_corpora_bp.route('/embedding-model/status', methods=['GET'])
def embedding_model_status_route():
    """检查本地 ONNX 运行时和模型文件；不访问网络、不加载模型。"""
    from services.embedding_backends import local_embedding_installation_status

    return jsonify({'success': True, 'data': local_embedding_installation_status()})


@style_corpora_bp.route('/embedding-model/install', methods=['POST'])
def install_embedding_model_route():
    """兼容旧前端：返回安装状态，不在服务进程中静默下载大型模型。"""
    from services.embedding_backends import local_embedding_installation_status

    status = local_embedding_installation_status()
    return jsonify({'success': True, 'data': {
        **status,
        'started': False,
        'manual_install': not status['installed'],
    }})


@style_corpora_bp.route('/embedding-model/install-progress', methods=['GET'])
def embedding_model_install_progress_route():
    """兼容旧前端：模型安装现为显式的本地脚本流程。"""
    return jsonify({'success': True, 'data': {
        'status': 'manual',
        'message': '请按照本地 ONNX 安装说明执行安装脚本',
    }})


@style_corpora_bp.route('', methods=['GET'])
def list_corpus():
    try:
        corpora = list_corpora()
        return jsonify({'success': True, 'data': [item.to_dict() for item in corpora]})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@style_corpora_bp.route('', methods=['POST'])
def create_corpus_route():
    data = request.get_json() or {}
    try:
        corpus = create_corpus(data.get('name', ''), data.get('description', ''))
        return jsonify({'success': True, 'data': corpus.to_dict()}), 201
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@style_corpora_bp.route('/<int:corpus_id>', methods=['GET'])
def get_corpus_route(corpus_id):
    try:
        corpus = get_corpus(corpus_id)
        return jsonify({'success': True, 'data': corpus.to_dict()})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404


@style_corpora_bp.route('/<int:corpus_id>', methods=['PUT'])
def update_corpus_route(corpus_id):
    data = request.get_json() or {}
    try:
        corpus = update_corpus(
            corpus_id,
            name=data.get('name'),
            description=data.get('description'),
        )
        return jsonify({'success': True, 'data': corpus.to_dict()})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@style_corpora_bp.route('/<int:corpus_id>', methods=['DELETE'])
def delete_corpus_route(corpus_id):
    try:
        delete_corpus(corpus_id)
        return jsonify({'success': True})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@style_corpora_bp.route('/<int:corpus_id>/import', methods=['POST'])
def import_corpus_route(corpus_id):
    """导入本地语料文件（TXT/DOC/DOCX），自动切片 + 规则打标。"""
    uploaded = request.files.get('file')
    try:
        if not uploaded or not uploaded.filename:
            return jsonify({'success': False, 'error': '请选择要导入的语料文件'}), 400
        text = extract_uploaded_text(uploaded)
        count = import_corpus_text(corpus_id, text, filename=uploaded.filename)
        corpus = get_corpus(corpus_id)
        return jsonify({'success': True, 'data': {
            'chunk_count': count,
            'total_chars': corpus.total_chars,
            'corpus': corpus.to_dict(),
        }})
    except (OverflowError, ValueError) as exc:
        return jsonify({'success': False, 'error': friendly_error_message(exc)}), 413 if isinstance(exc, OverflowError) else 400
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@style_corpora_bp.route('/<int:corpus_id>/index', methods=['POST'])
def index_corpus_route(corpus_id):
    """使用显式选择的本地或远程后端生成可选语义向量。"""
    data = request.get_json() or {}
    try:
        corpus = get_corpus(corpus_id)
        start_index_progress(corpus_id, corpus.chunk_count)
        acquire_model_operation()
        try:
            count = index_corpus(
                corpus_id,
                api_key=data.get('api_key', ''),
                provider=data.get('provider', 'siliconflow'),
                backend=data.get('backend', 'auto'),
                progress_callback=lambda completed, total: update_index_progress(
                    corpus_id, completed, total,
                ),
            )
        finally:
            release_model_operation()
        finish_index_progress(corpus_id, count)
        corpus = get_corpus(corpus_id)
        return jsonify({'success': True, 'data': {'indexed_count': count, 'corpus': corpus.to_dict()}})
    except GenerationError as exc:
        fail_index_progress(corpus_id, str(exc))
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        fail_index_progress(corpus_id, friendly_error_message(exc))
        return jsonify({'success': False, 'error': friendly_error_message(exc)}), 500


@style_corpora_bp.route('/<int:corpus_id>/index-progress', methods=['GET'])
def index_corpus_progress_route(corpus_id):
    progress = get_index_progress(corpus_id)
    if progress is None:
        return jsonify({'success': True, 'data': {
            'corpus_id': corpus_id,
            'status': 'idle',
            'completed': 0,
            'total': 0,
            'percent': 0.0,
            'elapsed_seconds': 0.0,
            'estimated_remaining_seconds': None,
            'message': '尚未开始向量化',
        }})
    return jsonify({'success': True, 'data': progress})


@style_corpora_bp.route('/<int:corpus_id>/clear', methods=['POST'])
def clear_corpus_route(corpus_id):
    try:
        clear_corpus_chunks(corpus_id)
        return jsonify({'success': True})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@style_corpora_bp.route('/<int:corpus_id>/chunks', methods=['GET'])
def list_chunks_route(corpus_id):
    try:
        page = request.args.get('page', 1, type=int)
        per_page = min(max(request.args.get('per_page', 50, type=int), 1), 200)
        corpus, items, total = list_chunks(corpus_id, page=page, per_page=per_page)
        return jsonify({'success': True, 'data': {
            'corpus': corpus.to_dict(),
            'total': total,
            'page': page,
            'per_page': per_page,
            'items': [item.to_dict() for item in items],
        }})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404


@style_corpora_bp.route('/search', methods=['POST'])
def search_corpus_route():
    """检索测试：输入一句话，返回匹配的风格片段与评分解释。"""
    data = request.get_json() or {}
    try:
        items, meta = hybrid_search_style(
            query_text=data.get('query_text', ''),
            corpus_ids=data.get('corpus_ids'),
            scene_type=data.get('scene_type') or None,
            pacing=data.get('pacing') or None,
            pov=data.get('pov') or None,
            top_k=int(data.get('top_k', 3)),
            api_key=data.get('api_key', ''),
            provider=data.get('provider', 'siliconflow'),
        )
        return jsonify({'success': True, 'data': {'items': items, 'meta': meta}})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'success': False, 'error': friendly_error_message(exc)}), 500
