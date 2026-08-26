"""工作模式预设接口骨架。

仅为后续功能预留路由与请求结构，不实现业务逻辑：
- GET  /api/modes                 列出所有预设工作模式
- GET  /api/modes/<mode_id>       查看单个模式的配置
- POST /api/modes/<mode_id>/generate  占位入口（当前返回 501 未实现）
"""
from flask import Blueprint, jsonify

from services.work_modes import WORK_MODES, list_work_modes

mode_bp = Blueprint('modes', __name__, url_prefix='/api/modes')


@mode_bp.route('', methods=['GET'])
def list_modes():
    """列出所有预设工作模式（含元数据，不含业务逻辑）。"""
    return jsonify({'success': True, 'data': {'modes': list_work_modes()}})


@mode_bp.route('/<mode_id>', methods=['GET'])
def get_mode(mode_id):
    """查看单个工作模式的配置。"""
    mode = WORK_MODES.get(mode_id)
    if not mode:
        return jsonify({'success': False, 'error': '工作模式不存在'}), 404
    from services.work_modes import _serializable
    return jsonify({'success': True, 'data': {'id': mode_id, **_serializable(mode)}})


@mode_bp.route('/<mode_id>/generate', methods=['POST'])
def generate_for_mode(mode_id):
    """占位：为后续按工作模式的生成入口预留，当前仅返回未实现。"""
    mode = WORK_MODES.get(mode_id)
    if not mode:
        return jsonify({'success': False, 'error': '工作模式不存在'}), 404
    return jsonify({
        'success': False,
        'error': f"工作模式「{mode['name']}」的生成接口尚未实现（预设骨架）",
    }), 501
