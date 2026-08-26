"""工作模式预设（骨架）。

为后续“公众号/运营文案”等工作模式预留的声明式配置。
当前仅“小说创作”为已实现模式；其余模式只定义结构与元数据，
不包含任何业务逻辑，前端与后端可据此逐步接入。
"""

# 模式的 id 会直接作为 URL 片段使用，保持小写与连字符命名。
WORK_MODES = {
    "novel": {
        "name": "小说创作",
        "description": "人物、背景、剧情、范例组成的设定化写作（当前已实现）。",
        "categories": ("background", "character", "plot", "example", "constraint"),
        "output_spec": {
            "title_required": False,
            "sections": False,
            "default_max_length": None,
        },
        "postprocess": ("deai", "style_reference"),
        "enabled": True,
    },
    "marketing": {
        "name": "公众号/运营文案",
        "description": "公众号文章、运营文案、更新日志等公告与营销文体（规划中，骨架预留）。",
        "categories": ("copy_article", "copy_update", "copy_social", "copy_brand"),
        "output_spec": {
            "title_required": True,
            "sections": True,
            "default_max_length": 3000,
        },
        "postprocess": ("deai",),
        "enabled": False,
    },
}


def _serializable(mode):
    """把元组转为列表，便于 JSON 序列化。"""
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in mode.items()}


def list_work_modes():
    """返回可序列化的模式列表（含 id 字段）。"""
    return [
        {"id": mode_id, **_serializable(mode)}
        for mode_id, mode in WORK_MODES.items()
    ]
