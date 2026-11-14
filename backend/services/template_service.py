"""模板服务（异步版）。

与旧 ``server/services/template_service.py`` 逐函数对应，语义完全一致：

- 列表只返回版本链的最新节点（旧版本仍留在版本历史里）；
- 修改内容或风格强度会生成新版本，旧版本置为非活跃；
- 恢复历史版本会基于目标内容再生成一个新版本，保证"可追溯、不覆盖"；
- 导入时按「名称 + 分类 + 内容」判定重复，重复的静默跳过。

差别只有两处：函数改为 async 并接收 ``AsyncSession``；异常改为统一的
``TemplateServiceError``（``InvalidInputError`` 子类，HTTP 层映射 400）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.core.exceptions import InvalidInputError
from backend.db.models import PromptTemplate

STYLE_STRENGTHS = {'light', 'medium', 'strict'}

CATEGORY_NAMES = {
    'character': '人物设定',
    'background': '背景设定',
    'plot': '剧情设定',
    'example': '范例文章',
    'constraint': '更多约束',
}


class TemplateServiceError(InvalidInputError):
    """模板服务异常（用户可读，映射 400）。"""

    event = 'template_service_error'


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_style_strength(value: str | None) -> str:
    return value if value in STYLE_STRENGTHS else 'light'


# ── 基础 CRUD ────────────────────────────────────────────

async def create_template(
    session: AsyncSession,
    name: str,
    category: str,
    content: str,
    description: str = '',
    sort_order: int = 0,
    style_strength: str = 'light',
) -> PromptTemplate:
    if not name or not name.strip():
        raise TemplateServiceError('模板名称不能为空')
    if not content or not content.strip():
        raise TemplateServiceError('模板内容不能为空')

    template = PromptTemplate(
        name=name.strip(),
        category=category,
        content=content.strip(),
        description=(description or '').strip(),
        sort_order=sort_order,
        style_strength=normalize_style_strength(style_strength),
        version=1,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(template)
    await session.flush()
    return template


async def get_template(session: AsyncSession, template_id: int) -> PromptTemplate | None:
    return await session.get(PromptTemplate, template_id)


def _latest_nodes_stmt():
    """只取版本链最新节点的查询基础（与旧实现同构）。

    注意：子表必须用别名，否则 SQLAlchemy 会把 ``parent_id == id`` 自动关联到
    外层同一行，判断条件退化成恒假，旧版本就会继续出现在列表里。
    """
    child = aliased(PromptTemplate)
    return select(PromptTemplate).where(
        ~select(child.id).where(child.parent_id == PromptTemplate.id).exists()
    )


async def get_all_templates(
    session: AsyncSession,
    category: str | None = None,
    active_only: bool = False,
) -> list[PromptTemplate]:
    stmt = _latest_nodes_stmt()
    if category:
        stmt = stmt.where(PromptTemplate.category == category)
    if active_only:
        stmt = stmt.where(PromptTemplate.is_active.is_(True))

    # 按版本链根模板 id 排序，保证更新生成新版本后位置不变
    root_id = case(
        (PromptTemplate.parent_id.is_(None), PromptTemplate.id),
        else_=PromptTemplate.parent_id,
    )
    stmt = stmt.order_by(PromptTemplate.sort_order, root_id)
    return list((await session.execute(stmt)).scalars().all())


async def get_templates_by_category(
    session: AsyncSession,
    active_only: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """工作台左侧的分组视图（与旧 prompt_assembler 的同名函数输出一致）。"""
    templates = await get_all_templates(session, active_only=active_only)
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORY_NAMES}
    for template in templates:
        if template.category in grouped:
            grouped[template.category].append(template.to_dict())
    return grouped


async def update_template(
    session: AsyncSession,
    template_id: int,
    **kwargs: Any,
) -> PromptTemplate:
    template = await get_template(session, template_id)
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

    content_changed = content is not None and content.strip() != template.content
    style_changed = style_strength != (template.style_strength or 'light')

    if content_changed or style_changed:
        # 内容变了就生成新版本，旧版本保留在历史中
        new_template = PromptTemplate(
            name=(name or template.name).strip(),
            category=category or template.category,
            content=content.strip() if content is not None else template.content,
            description=(
                description if description is not None else template.description
            ).strip(),
            style_strength=style_strength,
            sort_order=sort_order if sort_order is not None else template.sort_order,
            is_active=True,
            version=(template.version or 1) + 1,
            parent_id=template.id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        template.is_active = False
        session.add(new_template)
        await session.flush()
        return new_template

    # 只改元数据时不产生新版本
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
    await session.flush()
    return template


async def delete_template(session: AsyncSession, template_id: int) -> None:
    template = await get_template(session, template_id)
    if not template:
        raise TemplateServiceError(f'模板不存在: {template_id}')
    await session.delete(template)
    await session.flush()


async def delete_all_templates(session: AsyncSession) -> None:
    for template in (await session.execute(select(PromptTemplate))).scalars().all():
        await session.delete(template)
    await session.flush()


async def toggle_template_active(session: AsyncSession, template_id: int) -> PromptTemplate:
    template = await get_template(session, template_id)
    if not template:
        raise TemplateServiceError(f'模板不存在: {template_id}')
    template.is_active = not template.is_active
    template.updated_at = utcnow()
    await session.flush()
    return template


# ── 版本控制 ─────────────────────────────────────────────

async def get_version_history(session: AsyncSession, template_id: int) -> list[dict[str, Any]]:
    template = await get_template(session, template_id)
    if not template:
        return []

    history: list[dict[str, Any]] = []
    current: PromptTemplate | None = template
    while current is not None:
        history.append(current.to_dict())
        if current.parent_id is None:
            break
        current = await get_template(session, current.parent_id)

    descendants = (await session.execute(
        select(PromptTemplate).where(PromptTemplate.parent_id == template_id)
    )).scalars().all()
    history.extend(item.to_dict() for item in descendants)
    return history


async def _is_same_lineage(
    session: AsyncSession,
    a: PromptTemplate | None,
    b: PromptTemplate | None,
) -> bool:
    if not a or not b:
        return False

    ancestors: set[int] = set()
    current: PromptTemplate | None = a
    while current is not None:
        ancestors.add(current.id)
        current = await get_template(session, current.parent_id) if current.parent_id else None

    current = b
    while current is not None:
        if current.id in ancestors:
            return True
        current = await get_template(session, current.parent_id) if current.parent_id else None
    return False


async def restore_version(
    session: AsyncSession,
    template_id: int,
    version_id: int,
) -> PromptTemplate:
    target = await get_template(session, version_id)
    if not target:
        raise TemplateServiceError(f'版本不存在: {version_id}')

    current = await get_template(session, template_id)
    if not await _is_same_lineage(session, current, target):
        raise TemplateServiceError('不能恢复到不同版本链的模板')

    restored = PromptTemplate(
        name=target.name,
        category=target.category,
        content=target.content,
        description=target.description,
        style_strength=target.style_strength or 'light',
        sort_order=target.sort_order,
        is_active=True,
        version=(current.version or 1) + 1,
        parent_id=target.parent_id or target.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    current.is_active = False
    session.add(restored)
    await session.flush()
    return restored


# ── 导入导出 ─────────────────────────────────────────────

async def export_templates(
    session: AsyncSession,
    template_ids: Iterable[int] | None = None,
    format: str = 'json',
) -> str:
    if template_ids:
        templates = []
        for template_id in template_ids:
            template = await get_template(session, template_id)
            if template is not None:
                templates.append(template)
    else:
        templates = await get_all_templates(session, active_only=True)

    if format == 'json':
        data = {
            'export_time': utcnow().isoformat(),
            'version': '1.0',
            'templates': [template.to_dict() for template in templates],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
    if format == 'markdown':
        return _export_to_markdown(templates)
    raise TemplateServiceError(f'不支持的导出格式: {format}')


def _export_to_markdown(templates: Iterable[PromptTemplate]) -> str:
    lines = ['# 提示词模板导出', '', f'导出时间: {utcnow().isoformat()}', '']
    strength_names = {'light': '轻度', 'medium': '中度', 'strict': '严格'}

    for cat_id, cat_name in CATEGORY_NAMES.items():
        cat_templates = [t for t in templates if t.category == cat_id]
        if not cat_templates:
            continue
        lines.append(f'## {cat_name}')
        lines.append('')
        for tpl in cat_templates:
            lines.append(f'### {tpl.name}')
            if tpl.category == 'example':
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


async def import_templates(session: AsyncSession, json_data: str) -> tuple[int, int]:
    """返回 (导入条数, 跳过条数)。"""
    try:
        data = json.loads(json_data)
    except json.JSONDecodeError:
        raise TemplateServiceError('导入文件不是有效的 JSON 格式，请检查文件内容后重试')

    if not isinstance(data, dict) or 'templates' not in data:
        raise TemplateServiceError('无效的导入数据：缺少 templates 字段')

    imported = 0
    total = len(data['templates'])
    for tpl_data in data['templates']:
        try:
            existing = (await session.execute(
                select(PromptTemplate.id).where(
                    PromptTemplate.name == tpl_data.get('name', ''),
                    PromptTemplate.category == tpl_data.get('category', ''),
                    PromptTemplate.content == tpl_data.get('content', ''),
                )
            )).first()
            if existing:
                continue

            session.add(PromptTemplate(
                name=tpl_data.get('name', '未命名'),
                category=tpl_data.get('category', 'constraint'),
                content=tpl_data.get('content', ''),
                description=tpl_data.get('description', ''),
                style_strength=normalize_style_strength(tpl_data.get('style_strength', 'light')),
                is_active=True,
                version=1,
                created_at=utcnow(),
                updated_at=utcnow(),
            ))
            imported += 1
        except Exception:  # 单条坏数据不影响整批
            continue

    await session.flush()
    return imported, total - imported
