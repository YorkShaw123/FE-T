"""
提示词模板服务
提供模板的 CRUD、版本控制、导入导出等功能
"""
import json
from datetime import datetime, timezone
from sqlalchemy import case
from sqlalchemy.orm import aliased
from database import db
from database.models import PromptTemplate


class TemplateServiceError(Exception):
    """模板服务异常"""
    pass


def utcnow():
    return datetime.now(timezone.utc)


# ==================== 基础 CRUD ====================

STYLE_STRENGTHS = {'light', 'medium', 'strict'}


def normalize_style_strength(value):
    return value if value in STYLE_STRENGTHS else 'light'


def create_template(
    name,
    category,
    content,
    description='',
    sort_order=0,
    style_strength='light',
):
    """
    创建新模板
    :return: 创建的模板对象
    """
    if not name or not name.strip():
        raise TemplateServiceError('模板名称不能为空')
    if not content or not content.strip():
        raise TemplateServiceError('模板内容不能为空')

    template = PromptTemplate(
        name=name.strip(),
        category=category,
        content=content.strip(),
        description=description.strip(),
        sort_order=sort_order,
        style_strength=normalize_style_strength(style_strength),
        version=1,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.session.add(template)
    db.session.commit()
    return template


def get_template(template_id):
    """获取单个模板"""
    return PromptTemplate.query.get(template_id)


def get_all_templates(category=None, active_only=False):
    """
    获取模板列表
    :param category: 按分类筛选
    :param active_only: 仅活跃模板
    """
    # 列表只展示版本链的最新节点；旧版本仍保留在版本历史中。
    child = aliased(PromptTemplate)
    query = PromptTemplate.query.filter(
        ~db.session.query(child.id)
        .filter(child.parent_id == PromptTemplate.id)
        .exists()
    )
    if category:
        query = query.filter_by(category=category)
    if active_only:
        query = query.filter_by(is_active=True)
    # 按版本链根模板 id 排序，确保更新生成新版本后位置不变
    root_id = case(
        (PromptTemplate.parent_id.is_(None), PromptTemplate.id),
        else_=PromptTemplate.parent_id,
    )
    return query.order_by(PromptTemplate.sort_order, root_id).all()


def update_template(template_id, **kwargs):
    """
    更新模板
    如果内容发生变化，自动创建新版本（旧版本保留，is_active设为False）
    """
    template = get_template(template_id)
    if not template:
        raise TemplateServiceError(f'模板不存在: {template_id}')

    name = kwargs.get('name')
    content = kwargs.get('content')
    description = kwargs.get('description')
    category = kwargs.get('category')
    sort_order = kwargs.get('sort_order')
    is_active = kwargs.get('is_active')
    style_strength = normalize_style_strength(
        kwargs.get('style_strength', template.style_strength or 'light')
    )

    # 检查内容是否变化
    content_changed = content is not None and content.strip() != template.content
    style_changed = style_strength != (template.style_strength or 'light')

    if content_changed or style_changed:
        # 创建新版本
        new_template = PromptTemplate(
            name=(name or template.name).strip(),
            category=category or template.category,
            content=content.strip() if content is not None else template.content,
            description=(description if description is not None else template.description).strip(),
            style_strength=style_strength,
            sort_order=sort_order if sort_order is not None else template.sort_order,
            is_active=True,
            version=template.version + 1,
            parent_id=template.id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        # 旧版本标记为非活跃
        template.is_active = False
        db.session.add(new_template)
        db.session.commit()
        return new_template
    else:
        # 仅更新元数据（不创建新版本）
        if name is not None:
            template.name = name.strip()
        if description is not None:
            template.description = description.strip()
        if category is not None:
            template.category = category
        if sort_order is not None:
            template.sort_order = sort_order
        if is_active is not None:
            template.is_active = is_active
        if 'style_strength' in kwargs:
            template.style_strength = style_strength
        template.updated_at = utcnow()
        db.session.commit()
        return template


def delete_template(template_id):
    """删除模板（物理删除）"""
    template = get_template(template_id)
    if not template:
        raise TemplateServiceError(f'模板不存在: {template_id}')
    db.session.delete(template)
    db.session.commit()


def delete_all_templates():
    """删除所有模板（物理删除）"""
    PromptTemplate.query.delete()
    db.session.commit()


def toggle_template_active(template_id):
    """切换模板启用/禁用状态"""
    template = get_template(template_id)
    if not template:
        raise TemplateServiceError(f'模板不存在: {template_id}')
    template.is_active = not template.is_active
    template.updated_at = utcnow()
    db.session.commit()
    return template


# ==================== 版本控制 ====================

def get_version_history(template_id):
    """
    获取模板的版本历史
    返回从当前版本回溯到最初版本的所有版本（包括同族版本）
    """
    template = get_template(template_id)
    if not template:
        return []

    history = []
    current = template

    # 向前追溯（当前的版本链）
    while current:
        history.append(current.to_dict())
        current = current.parent

    # 向后查找派生版本
    descendants = PromptTemplate.query.filter_by(parent_id=template_id).all()
    for desc in descendants:
        history.append(desc.to_dict())

    return history


def restore_version(template_id, version_id):
    """
    恢复到指定版本
    将被恢复的版本设为活跃，其余同族版本设为非活跃
    """
    target = get_template(version_id)
    if not target:
        raise TemplateServiceError(f'版本不存在: {version_id}')

    # 获取当前活跃版本
    current = get_template(template_id)

    # 确保属于同一版本链
    if not _is_same_lineage(current, target):
        raise TemplateServiceError('不能恢复到不同版本链的模板')

    # 创建恢复版本
    restored = PromptTemplate(
        name=target.name,
        category=target.category,
        content=target.content,
        description=target.description,
        style_strength=target.style_strength or 'light',
        sort_order=target.sort_order,
        is_active=True,
        version=current.version + 1,
        parent_id=target.parent_id or target.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    current.is_active = False
    db.session.add(restored)
    db.session.commit()
    return restored


def _is_same_lineage(a, b):
    """检查两个模板是否在同一版本链上"""
    if not a or not b:
        return False
    # 收集 a 的祖先ID集合
    ancestors_a = set()
    current = a
    while current:
        ancestors_a.add(current.id)
        current = current.parent
    # 如果 b 的 id 或其祖先中有任何一个在祖先集合中，说明同族
    current = b
    while current:
        if current.id in ancestors_a:
            return True
        current = current.parent
    return False


# ==================== 导入导出 ====================

def export_templates(template_ids=None, format='json'):
    """
    导出模板
    :param template_ids: 要导出的模板ID列表，None=全部活跃模板
    :param format: 'json' 或 'markdown'
    :return: 导出字符串
    """
    if template_ids:
        templates = [get_template(tid) for tid in template_ids]
        templates = [t for t in templates if t is not None]
    else:
        templates = get_all_templates(active_only=True)

    if format == 'json':
        data = {
            'export_time': utcnow().isoformat(),
            'version': '1.0',
            'templates': [t.to_dict() for t in templates],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
    elif format == 'markdown':
        return _export_to_markdown(templates)
    else:
        raise TemplateServiceError(f'不支持的导出格式: {format}')


def _export_to_markdown(templates):
    """导出为 Markdown 格式"""
    lines = ['# 提示词模板导出', '', f'导出时间: {utcnow().isoformat()}', '']

    category_names = {
        'character': '人物设定',
        'background': '背景设定',
        'plot': '剧情设定',
        'example': '范例文章',
        'constraint': '更多约束',
    }

    for cat_id, cat_name in category_names.items():
        cat_templates = [t for t in templates if t.category == cat_id]
        if not cat_templates:
            continue
        lines.append(f'## {cat_name}')
        lines.append('')
        for tpl in cat_templates:
            lines.append(f'### {tpl.name}')
            if tpl.category == 'example':
                strength_names = {'light': '轻度', 'medium': '中度', 'strict': '严格'}
                lines.append(
                    f'风格参考强度：{strength_names.get(tpl.style_strength or "light", "轻度")}'
                )
            if tpl.description:
                lines.append(f'*{tpl.description}*')
            lines.append('')
            lines.append(tpl.content)
            lines.append('')
            lines.append('---')
            lines.append('')

    return '\n'.join(lines)


def import_templates(json_data):
    """
    从 JSON 数据导入模板
    :param json_data: JSON 字符串
    :return: (imported_count, skipped_count)
    """
    try:
        data = json.loads(json_data)
    except json.JSONDecodeError:
        raise TemplateServiceError('导入文件不是有效的 JSON 格式，请检查文件内容后重试')

    if 'templates' not in data:
        raise TemplateServiceError('无效的导入数据：缺少 templates 字段')

    imported = 0
    for tpl_data in data['templates']:
        try:
            existing = PromptTemplate.query.filter_by(
                name=tpl_data.get('name', ''),
                category=tpl_data.get('category', ''),
                content=tpl_data.get('content', ''),
            ).first()

            if existing:
                continue  # 跳过完全相同的模板

            template = PromptTemplate(
                name=tpl_data.get('name', '未命名'),
                category=tpl_data.get('category', 'constraint'),
                content=tpl_data.get('content', ''),
                description=tpl_data.get('description', ''),
                style_strength=normalize_style_strength(
                    tpl_data.get('style_strength', 'light')
                ),
                is_active=True,
                version=1,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.session.add(template)
            imported += 1
        except Exception:
            continue

    db.session.commit()
    return imported, len(data['templates']) - imported
