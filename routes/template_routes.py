"""
模板管理 API 路由
"""
import json
from flask import Blueprint, request, jsonify
from database.models import PromptTemplate
from services.template_service import (
    create_template,
    create_template_from_sample,
    get_template,
    get_all_templates,
    get_sample_templates,
    update_template,
    delete_template,
    delete_all_templates,
    toggle_template_active,
    get_version_history,
    restore_version,
    export_templates,
    import_templates,
    TemplateServiceError,
)
from services.prompt_assembler import get_templates_by_category, get_active_templates_by_category

template_bp = Blueprint('templates', __name__, url_prefix='/api/templates')


@template_bp.route('', methods=['GET'])
def list_templates():
    """获取模板列表"""
    category = request.args.get('category')
    active_only = request.args.get('active_only', 'false').lower() == 'true'
    include_samples = request.args.get('include_samples', 'true').lower() == 'true'

    templates = get_all_templates(
        category=category,
        active_only=active_only,
        exclude_samples=not include_samples,
    )
    return jsonify({
        'success': True,
        'data': [t.to_dict() for t in templates],
    })


@template_bp.route('/grouped', methods=['GET'])
def list_grouped_templates():
    """按分类获取模板（工作台使用，默认排除示例模板）
    参数: active_only (bool) - 是否仅返回活跃模板，默认 false（全部返回）
    """
    active_only = request.args.get('active_only', 'false').lower() == 'true'
    grouped = get_templates_by_category(active_only=active_only, exclude_samples=True)
    return jsonify({
        'success': True,
        'data': grouped,
    })


@template_bp.route('/samples', methods=['GET'])
def list_sample_templates():
    """获取所有示例模板"""
    templates = get_sample_templates()
    return jsonify({
        'success': True,
        'data': [t.to_dict() for t in templates],
    })


@template_bp.route('/from-sample', methods=['POST'])
def add_template_from_sample():
    """基于示例模板填写变量后另存为新模板"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'}), 400

        template = create_template_from_sample(
            sample_id=data.get('sample_id'),
            name=data.get('name', ''),
            category=data.get('category', 'constraint'),
            description=data.get('description', ''),
            variable_values=data.get('variable_values', {}),
        )
        return jsonify({
            'success': True,
            'data': template.to_dict(),
        }), 201
    except TemplateServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@template_bp.route('/<int:template_id>', methods=['GET'])
def get_single_template(template_id):
    """获取单个模板"""
    template = get_template(template_id)
    if not template:
        return jsonify({'success': False, 'error': '模板不存在'}), 404
    return jsonify({
        'success': True,
        'data': template.to_dict(),
    })


@template_bp.route('', methods=['POST'])
def add_template():
    """创建模板"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'}), 400

        template = create_template(
            name=data.get('name', ''),
            category=data.get('category', 'constraint'),
            content=data.get('content', ''),
            description=data.get('description', ''),
            sort_order=data.get('sort_order', 0),
            style_strength=data.get('style_strength', 'light'),
            is_sample=data.get('is_sample', False),
        )
        return jsonify({
            'success': True,
            'data': template.to_dict(),
        }), 201
    except TemplateServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@template_bp.route('/<int:template_id>', methods=['PUT'])
def edit_template(template_id):
    """更新模板"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'}), 400

        template = get_template(template_id)
        if not template:
            return jsonify({'success': False, 'error': '模板不存在'}), 404

        allowed_fields = [
            'name', 'category', 'content', 'description', 'sort_order',
            'is_active', 'style_strength', 'is_sample',
        ]
        kwargs = {k: v for k, v in data.items() if k in allowed_fields}

        # 示例模板仅允许修改 is_sample 标记（取消示例），不允许直接修改原文
        if template.is_sample:
            protected_fields = {'name', 'category', 'content', 'description', 'sort_order', 'is_active', 'style_strength'}
            if protected_fields & set(kwargs.keys()):
                return jsonify({
                    'success': False,
                    'error': '示例模板不能直接修改原文，请使用“另存为模板”生成新模板',
                }), 400

        template = update_template(template_id, **kwargs)
        return jsonify({
            'success': True,
            'data': template.to_dict(),
            'is_new_version': template.version > 1 and template.parent_id is not None,
        })
    except TemplateServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@template_bp.route('/<int:template_id>', methods=['DELETE'])
def remove_template(template_id):
    """删除模板"""
    try:
        delete_template(template_id)
        return jsonify({'success': True})
    except TemplateServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@template_bp.route('/all', methods=['DELETE'])
def remove_all_templates():
    """删除所有模板"""
    try:
        delete_all_templates()
        return jsonify({'success': True, 'deleted': True})
    except TemplateServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@template_bp.route('/<int:template_id>/toggle', methods=['POST'])
def toggle_template(template_id):
    """切换模板启用/禁用状态"""
    try:
        template = toggle_template_active(template_id)
        return jsonify({
            'success': True,
            'data': template.to_dict(),
        })
    except TemplateServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@template_bp.route('/<int:template_id>/versions', methods=['GET'])
def template_versions(template_id):
    """获取模板版本历史"""
    try:
        history = get_version_history(template_id)
        return jsonify({
            'success': True,
            'data': history,
        })
    except TemplateServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@template_bp.route('/<int:template_id>/restore/<int:version_id>', methods=['POST'])
def restore_template_version(template_id, version_id):
    """恢复模板到指定版本"""
    try:
        template = restore_version(template_id, version_id)
        return jsonify({
            'success': True,
            'data': template.to_dict(),
        })
    except TemplateServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@template_bp.route('/export', methods=['POST'])
def export_templates_route():
    """导出模板"""
    try:
        data = request.get_json() or {}
        template_ids = data.get('ids')
        fmt = data.get('format', 'json')

        content = export_templates(template_ids=template_ids, format=fmt)

        mimetype = 'application/json' if fmt == 'json' else 'text/markdown'
        ext = 'json' if fmt == 'json' else 'md'

        from flask import Response
        return Response(
            content,
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename=templates_export.{ext}'
            },
        )
    except TemplateServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@template_bp.route('/import', methods=['POST'])
def import_templates_route():
    """导入模板"""
    try:
        if 'file' in request.files:
            file = request.files['file']
            json_data = file.read().decode('utf-8')
        else:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': '请提供JSON文件或数据'}), 400
            json_data = data.get('data', '')
            if not json_data:
                json_data = json.dumps(data)

        imported, skipped = import_templates(json_data)
        return jsonify({
            'success': True,
            'imported': imported,
            'skipped': skipped,
        })
    except TemplateServiceError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
