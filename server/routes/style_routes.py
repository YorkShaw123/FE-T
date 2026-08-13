"""范例文章 Style Card API。"""
from flask import Blueprint, jsonify, request

from services.errors import GenerationError, friendly_error_message
from services.operation_guard import acquire_model_operation, release_model_operation
from services.style_profile_service import (
    analyze_style_profile,
    get_style_profile,
    restore_analysis_card,
    style_source_hash,
    update_style_profile,
)
from services.style_excerpt_service import (
    delete_style_excerpt,
    get_style_excerpts,
    rebuild_style_excerpts,
    update_style_excerpt,
)


style_bp = Blueprint('styles', __name__, url_prefix='/api/style-profiles')


def _response(profile, template):
    return profile.to_dict(style_source_hash(template.content)) if profile else {
        'template_id': template.id,
        'analysis_status': 'missing',
        'is_stale': False,
        'card': None,
        'is_primary': False,
    }


@style_bp.route('/<int:template_id>', methods=['GET'])
def get_profile(template_id):
    try:
        template, profile = get_style_profile(template_id)
        return jsonify({'success': True, 'data': _response(profile, template)})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404


def _analyze(template_id):
    data = request.get_json() or {}
    try:
        acquire_model_operation()
        try:
            profile = analyze_style_profile(
                template_id=template_id,
                api_key=str(data.get('api_key', '') or ''),
                provider=str(data.get('provider', 'deepseek') or 'deepseek'),
                model=str(data.get('model', 'deepseek-v4-pro') or 'deepseek-v4-pro'),
            )
        finally:
            release_model_operation()
        template, _ = get_style_profile(template_id)
        return jsonify({'success': True, 'data': _response(profile, template)})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'success': False, 'error': friendly_error_message(exc)}), 500


@style_bp.route('/<int:template_id>/analyze', methods=['POST'])
def analyze_profile(template_id):
    return _analyze(template_id)


@style_bp.route('/<int:template_id>/refresh', methods=['POST'])
def refresh_profile(template_id):
    return _analyze(template_id)


@style_bp.route('/<int:template_id>', methods=['PUT'])
def save_profile(template_id):
    data = request.get_json() or {}
    try:
        profile = update_style_profile(
            template_id,
            card=data.get('card'),
            is_primary=data.get('is_primary') if 'is_primary' in data else None,
        )
        template, _ = get_style_profile(template_id)
        return jsonify({'success': True, 'data': _response(profile, template)})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@style_bp.route('/<int:template_id>/restore', methods=['POST'])
def restore_profile(template_id):
    try:
        profile = restore_analysis_card(template_id)
        template, _ = get_style_profile(template_id)
        return jsonify({'success': True, 'data': _response(profile, template)})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@style_bp.route('/<int:template_id>/excerpts', methods=['GET'])
def list_excerpts(template_id):
    try:
        excerpts = get_style_excerpts(template_id)
        return jsonify({'success': True, 'data': [item.to_dict() for item in excerpts]})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404


@style_bp.route('/<int:template_id>/excerpts/rebuild', methods=['POST'])
def rebuild_excerpts(template_id):
    data = request.get_json() or {}
    try:
        acquire_model_operation()
        try:
            excerpts = rebuild_style_excerpts(
                template_id=template_id,
                api_key=str(data.get('api_key', '') or ''),
                provider=str(data.get('provider', 'deepseek') or 'deepseek'),
                model=str(data.get('model', 'deepseek-v4-pro') or 'deepseek-v4-pro'),
            )
        finally:
            release_model_operation()
        return jsonify({'success': True, 'data': [item.to_dict() for item in excerpts]})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'success': False, 'error': friendly_error_message(exc)}), 500


@style_bp.route('/<int:template_id>/excerpts/<int:excerpt_id>', methods=['PUT'])
def save_excerpt(template_id, excerpt_id):
    try:
        excerpt = update_style_excerpt(template_id, excerpt_id, request.get_json() or {})
        return jsonify({'success': True, 'data': excerpt.to_dict()})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400


@style_bp.route('/<int:template_id>/excerpts/<int:excerpt_id>', methods=['DELETE'])
def remove_excerpt(template_id, excerpt_id):
    try:
        delete_style_excerpt(template_id, excerpt_id)
        return jsonify({'success': True})
    except GenerationError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
