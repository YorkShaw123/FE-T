"""工作模式预设（声明式配置，与旧实现一致）。

目前只有"小说创作"是已实现模式；"公众号/运营文案"只定义结构与元数据，
不包含业务逻辑，生成接口按预设骨架返回 501。
"""

from __future__ import annotations

from typing import Any

WORK_MODES: dict[str, dict[str, Any]] = {
    'novel': {
        'name': '小说创作',
        'description': '人物、背景、剧情、范例组成的设定化写作（当前已实现）。',
        'categories': ('background', 'character', 'plot', 'example', 'constraint'),
        'output_spec': {
            'title_required': False,
            'sections': False,
            'default_max_length': None,
        },
        'postprocess': ('deai', 'style_reference'),
        'enabled': True,
    },
    'marketing': {
        'name': '公众号/运营文案',
        'description': '公众号文章、运营文案、更新日志等公告与营销文体（规划中，骨架预留）。',
        'categories': ('copy_article', 'copy_update', 'copy_social', 'copy_brand'),
        'output_spec': {
            'title_required': True,
            'sections': True,
            'default_max_length': 3000,
        },
        'postprocess': ('deai',),
        'enabled': False,
    },
}


def _serializable(mode: dict[str, Any]) -> dict[str, Any]:
    """元组转列表，便于 JSON 序列化。"""
    return {key: (list(value) if isinstance(value, tuple) else value) for key, value in mode.items()}


def list_work_modes() -> list[dict[str, Any]]:
    return [{'id': mode_id, **_serializable(mode)} for mode_id, mode in WORK_MODES.items()]


def get_work_mode(mode_id: str) -> dict[str, Any] | None:
    mode = WORK_MODES.get(mode_id)
    if mode is None:
        return None
    return {'id': mode_id, **_serializable(mode)}
