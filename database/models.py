"""
数据库ORM模型定义
包含模板、生成记录、项目设置三个核心模型
"""
from datetime import datetime, timezone
from database import db


def utcnow():
    """获取当前UTC时间"""
    return datetime.now(timezone.utc)


class PromptTemplate(db.Model):
    """提示词模板模型
    支持版本控制：每次修改创建新版本，通过 parent_id 追溯历史
    支持变量占位符：模板中使用 {{variable_name}} 标记可修改部分
    """
    __tablename__ = 'prompt_templates'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='constraint')
    content = db.Column(db.Text, nullable=False)
    # 模板说明/备注
    description = db.Column(db.Text, default='')
    # 自动提取的变量列表（JSON数组字符串）
    variables = db.Column(db.Text, default='[]')
    # 是否启用
    is_active = db.Column(db.Boolean, default=True)
    # 风格参考强度，仅对 example 分类生效：light / medium / strict
    style_strength = db.Column(db.String(20), nullable=False, default='light')
    # 排序权重
    sort_order = db.Column(db.Integer, default=0)
    # 版本控制字段
    version = db.Column(db.Integer, default=1)
    parent_id = db.Column(db.Integer, db.ForeignKey('prompt_templates.id'), nullable=True)
    # 时间戳
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    # 自引用关系：版本历史
    versions = db.relationship(
        'PromptTemplate',
        backref=db.backref('parent', remote_side=[id]),
        foreign_keys=[parent_id],
        lazy='dynamic'
    )

    def to_dict(self):
        """序列化为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'content': self.content,
            'description': self.description,
            'variables': self.variables,
            'is_active': self.is_active,
            'style_strength': self.style_strength or 'light',
            'sort_order': self.sort_order,
            'version': self.version,
            'parent_id': self.parent_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<PromptTemplate {self.name} v{self.version}>'


class StyleProfile(db.Model):
    """范例文章对应的结构化风格卡；与具体模板版本绑定。"""
    __tablename__ = 'style_profiles'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    template_id = db.Column(
        db.Integer,
        db.ForeignKey('prompt_templates.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
        index=True,
    )
    template_version = db.Column(db.Integer, nullable=False, default=1)
    source_hash = db.Column(db.String(64), nullable=False, index=True)
    schema_version = db.Column(db.Integer, nullable=False, default=1)
    # 最近一次自动分析结果，以及用户当前实际使用的结果。
    analysis_card_json = db.Column(db.Text, nullable=False, default='{}')
    card_json = db.Column(db.Text, nullable=False, default='{}')
    analysis_model = db.Column(db.String(100), default='')
    analysis_status = db.Column(db.String(30), nullable=False, default='ready')
    error_message = db.Column(db.Text, default='')
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    template = db.relationship('PromptTemplate', backref=db.backref(
        'style_profile', uselist=False, cascade='all, delete-orphan', passive_deletes=True
    ))

    def to_dict(self, current_source_hash=None):
        import json
        try:
            card = json.loads(self.card_json or '{}')
        except (TypeError, json.JSONDecodeError):
            card = {}
        return {
            'id': self.id,
            'template_id': self.template_id,
            'template_version': self.template_version,
            'source_hash': self.source_hash,
            'schema_version': self.schema_version,
            'card': card,
            'analysis_model': self.analysis_model,
            'analysis_status': self.analysis_status,
            'error_message': self.error_message,
            'is_primary': self.is_primary,
            'is_stale': bool(current_source_hash and current_source_hash != self.source_hash),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class StyleExcerpt(db.Model):
    """由范例文章切分得到的可检索风格片段。"""
    __tablename__ = 'style_excerpts'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    style_profile_id = db.Column(
        db.Integer,
        db.ForeignKey('style_profiles.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    content = db.Column(db.Text, nullable=False)
    content_hash = db.Column(db.String(64), nullable=False, index=True)
    source_order = db.Column(db.Integer, nullable=False, default=0)
    scene_type = db.Column(db.String(50), nullable=False, default='mixed', index=True)
    pov = db.Column(db.String(80), default='')
    emotion = db.Column(db.String(200), default='')
    dialogue_ratio = db.Column(db.Float, nullable=False, default=0.0)
    pace = db.Column(db.String(30), nullable=False, default='medium')
    tags_json = db.Column(db.Text, nullable=False, default='[]')
    functions_json = db.Column(db.Text, nullable=False, default='[]')
    analysis_model = db.Column(db.String(100), default='')
    analysis_status = db.Column(db.String(30), nullable=False, default='ready')
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    is_pinned = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    profile = db.relationship('StyleProfile', backref=db.backref(
        'excerpts', cascade='all, delete-orphan', passive_deletes=True,
        order_by='StyleExcerpt.source_order',
    ))

    def to_dict(self):
        import json

        def load_list(value):
            try:
                result = json.loads(value or '[]')
                return result if isinstance(result, list) else []
            except (TypeError, json.JSONDecodeError):
                return []

        return {
            'id': self.id,
            'style_profile_id': self.style_profile_id,
            'content': self.content,
            'char_count': len(self.content or ''),
            'source_order': self.source_order,
            'scene_type': self.scene_type,
            'pov': self.pov,
            'emotion': self.emotion,
            'dialogue_ratio': self.dialogue_ratio,
            'pace': self.pace,
            'tags': load_list(self.tags_json),
            'functions': load_list(self.functions_json),
            'analysis_model': self.analysis_model,
            'analysis_status': self.analysis_status,
            'is_enabled': self.is_enabled,
            'is_pinned': self.is_pinned,
        }


class GenerationRecord(db.Model):
    """生成记录模型
    保存每次AI生成的文章及所有上下文信息
    """
    __tablename__ = 'generation_records'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(500), nullable=False, default='未命名')
    # 第一版生成内容
    content = db.Column(db.Text, default='')
    # 去AI味后的内容
    deai_content = db.Column(db.Text, default='')
    # 用户在全屏 Markdown 编辑器中保存的修改版
    edited_content = db.Column(db.Text, default='')
    # 局部 AI 替换记录（JSON 数组），用于追踪修改来源
    edit_history = db.Column(db.Text, default='[]')
    # 使用的模型
    model_used = db.Column(db.String(100), default='')
    # 是否启用思考模式
    thinking_enabled = db.Column(db.Boolean, default=False)
    # 思考内容
    reasoning_content = db.Column(db.Text, default='')
    # 组装后的完整提示词
    assembled_prompt = db.Column(db.Text, default='')
    # 使用的模板ID列表（JSON数组）
    templates_used = db.Column(db.Text, default='[]')
    # 变量填充值（JSON对象）
    variable_values = db.Column(db.Text, default='{}')
    # 去AI味提示词
    deai_prompt = db.Column(db.Text, default='')
    # 质量评分（用户手动打分）
    rating = db.Column(db.Integer, default=0)
    # 备注
    notes = db.Column(db.Text, default='')
    # API原始响应
    api_response_raw = db.Column(db.Text, default='')
    # 风格链运行快照；旧记录默认为 legacy。
    style_mode = db.Column(db.String(30), nullable=False, default='legacy')
    style_profile_snapshot = db.Column(db.Text, default='[]')
    # 时间戳
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'deai_content': self.deai_content,
            'edited_content': self.edited_content,
            'edit_history': self.edit_history,
            'model_used': self.model_used,
            'thinking_enabled': self.thinking_enabled,
            'reasoning_content': self.reasoning_content,
            'assembled_prompt': self.assembled_prompt,
            'templates_used': self.templates_used,
            'variable_values': self.variable_values,
            'deai_prompt': self.deai_prompt,
            'rating': self.rating,
            'notes': self.notes,
            'style_mode': self.style_mode or 'legacy',
            'style_profile_snapshot': self.style_profile_snapshot or '[]',
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def to_brief_dict(self):
        """简要信息，用于列表展示"""
        return {
            'id': self.id,
            'title': self.title,
            'model_used': self.model_used,
            'thinking_enabled': self.thinking_enabled,
            'rating': self.rating,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'has_deai': bool(self.deai_content),
            'has_edited': bool(self.edited_content),
            'content_preview': (self.deai_content or self.content)[:200] + '...' if len(self.deai_content or self.content) > 200 else (self.deai_content or self.content),
        }

    def __repr__(self):
        return f'<GenerationRecord {self.title}>'


class ProjectSetting(db.Model):
    """项目设置模型
    存储简单的键值对配置（不存储API密钥）
    """
    __tablename__ = 'project_settings'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, default='')
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    @staticmethod
    def get_value(key, default=None):
        """获取设置值"""
        setting = ProjectSetting.query.filter_by(key=key).first()
        return setting.value if setting else default

    @staticmethod
    def set_value(key, value):
        """设置值"""
        setting = ProjectSetting.query.filter_by(key=key).first()
        if setting:
            setting.value = value
            setting.updated_at = utcnow()
        else:
            setting = ProjectSetting(key=key, value=value)
            db.session.add(setting)
        db.session.commit()

    def __repr__(self):
        return f'<ProjectSetting {self.key}>'
