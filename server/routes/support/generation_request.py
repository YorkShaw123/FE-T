"""生成接口请求的解析、默认值与模板选择。"""
from dataclasses import dataclass, field

from database import db
from database.models import PromptTemplate
from services.errors import GenerationError


@dataclass(frozen=True)
class GenerationRequest:
    api_key: str = ''
    provider: str = 'deepseek'
    model: str = 'deepseek-v4-pro'
    thinking_enabled: bool = False
    reasoning_effort: str = 'high'
    custom_prefix: str = ''
    custom_suffix: str = ''
    deai_enabled: bool = False
    deai_prompt: str = ''
    title: str = ''
    previous_article: str = ''
    variable_values: dict = field(default_factory=dict)
    template_ids: tuple = field(default_factory=tuple)
    style_strength: str = 'light'
    structured_prompt_enabled: bool = False
    style_mode: str = 'legacy'
    scene_type: str = 'auto'
    # Style RAG：语料库 ID 列表与 Embedding API 密钥（与 LLM 密钥分开）
    style_corpus_ids: tuple = field(default_factory=tuple)
    embedding_api_key: str = ''

    @classmethod
    def from_mapping(cls, data):
        data = data or {}
        variable_values = data.get('variable_values', {})
        if not isinstance(variable_values, dict):
            raise GenerationError('variable_values 必须是对象')
        raw_ids = data.get('template_ids') or ()
        if not isinstance(raw_ids, (list, tuple)):
            raise GenerationError('template_ids 必须是数组')
        try:
            template_ids = tuple(int(item) for item in raw_ids)
        except (TypeError, ValueError) as exc:
            raise GenerationError('template_ids 只能包含整数') from exc
        style_mode = str(data.get('style_mode', 'legacy') or 'legacy')
        if style_mode not in {'legacy', 'smart', 'off'}:
            raise GenerationError('style_mode 仅支持 legacy、smart 或 off')
        scene_type = str(data.get('scene_type', 'auto') or 'auto')
        if scene_type not in {
            'auto', 'dialogue', 'action', 'psychology', 'environment',
            'transition', 'narration', 'mixed',
        }:
            raise GenerationError('scene_type 参数无效')
        raw_corpus_ids = data.get('style_corpus_ids') or ()
        if not isinstance(raw_corpus_ids, (list, tuple)):
            raise GenerationError('style_corpus_ids 必须是数组')
        try:
            style_corpus_ids = tuple(int(item) for item in raw_corpus_ids)
        except (TypeError, ValueError) as exc:
            raise GenerationError('style_corpus_ids 只能包含整数') from exc
        return cls(
            api_key=str(data.get('api_key', '') or ''),
            provider=str(data.get('provider', 'deepseek') or 'deepseek'),
            model=str(data.get('model', 'deepseek-v4-pro') or 'deepseek-v4-pro'),
            thinking_enabled=bool(data.get('thinking_enabled', False)),
            reasoning_effort=str(data.get('reasoning_effort', 'high') or 'high'),
            custom_prefix=str(data.get('custom_prefix', '') or ''),
            custom_suffix=str(data.get('custom_suffix', '') or ''),
            deai_enabled=bool(data.get('deai_enabled', False)),
            deai_prompt=str(data.get('deai_prompt', '') or ''),
            title=str(data.get('title', '') or ''),
            previous_article=str(data.get('previous_article', '') or ''),
            variable_values=variable_values,
            template_ids=template_ids,
            style_strength=str(data.get('style_strength', 'light') or 'light'),
            structured_prompt_enabled=bool(data.get('structured_prompt_enabled', False)),
            style_mode=style_mode,
            scene_type=scene_type,
            style_corpus_ids=style_corpus_ids,
            embedding_api_key=str(data.get('embedding_api_key', '') or ''),
        )

    def load_templates(self):
        if not self.template_ids:
            return PromptTemplate.query.filter_by(is_active=True).all()
        templates = []
        for template_id in self.template_ids:
            template = db.session.get(PromptTemplate, template_id)
            if template is not None:
                templates.append(template)
        return templates

    def generation_kwargs(self, stream):
        return {
            'templates': self.load_templates(),
            'variable_values': self.variable_values,
            'api_key': self.api_key,
            'provider': self.provider,
            'model': self.model,
            'thinking_enabled': self.thinking_enabled,
            'reasoning_effort': self.reasoning_effort,
            'custom_prefix': self.custom_prefix,
            'custom_suffix': self.custom_suffix,
            'deai_enabled': self.deai_enabled,
            'deai_prompt': self.deai_prompt,
            'title': self.title,
            'previous_article': self.previous_article,
            'stream': stream,
            'style_strength': self.style_strength,
            'structured_prompt_enabled': self.structured_prompt_enabled,
            'style_mode': self.style_mode,
            'scene_type': self.scene_type,
            'style_corpus_ids': self.style_corpus_ids,
            'embedding_api_key': self.embedding_api_key,
        }

    def preview_kwargs(self):
        values = self.generation_kwargs(stream=False)
        for key in ('api_key', 'title', 'stream'):
            values.pop(key)
        return values
