"""生成记录的查询与持久化操作。"""

from database import db
from database.models import GenerationRecord
from services.errors import GenerationError


def get_record(record_id):
    return db.session.get(GenerationRecord, record_id)


def get_records(page=1, per_page=20):
    pagination = GenerationRecord.query.order_by(
        GenerationRecord.pinned.desc(),
        GenerationRecord.created_at.desc(),
    ).paginate(page=page, per_page=per_page, error_out=False)
    return {
        'items': [record.to_brief_dict() for record in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
    }


def update_record(record_id, **kwargs):
    record = get_record(record_id)
    if not record:
        raise GenerationError(f'记录不存在: {record_id}')
    allowed_fields = {'title', 'edited_content', 'edit_history', 'rating', 'pinned', 'notes'}
    unknown_fields = set(kwargs) - allowed_fields
    if unknown_fields:
        raise GenerationError(f'不允许更新字段: {", ".join(sorted(unknown_fields))}')
    for key, value in kwargs.items():
        setattr(record, key, value)
    db.session.commit()
    return record


def delete_record(record_id):
    record = get_record(record_id)
    if not record:
        raise GenerationError(f'记录不存在: {record_id}')
    db.session.delete(record)
    db.session.commit()


def delete_all_records():
    """删除所有生成记录"""
    GenerationRecord.query.delete()
    db.session.commit()
