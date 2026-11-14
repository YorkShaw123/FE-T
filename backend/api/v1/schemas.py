"""P1 阶段的请求/响应模型。

对照课件 3.3：请求体一律用 Pydantic 声明，字段与旧 Flask 版本逐一对齐，
默认值也照抄，避免前端行为漂移。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TemplateCreate(BaseModel):
    name: str = Field(default='', description='模板名称')
    category: str = Field(default='constraint', description='模板分类')
    content: str = Field(default='', description='模板内容')
    description: str = Field(default='', description='模板说明')
    sort_order: int = Field(default=0, description='排序权重')
    style_strength: str = Field(default='light', description='风格参考强度')


class TemplateUpdate(BaseModel):
    """全部字段可选；只改元数据时不会产生新版本。"""

    name: str | None = None
    category: str | None = None
    content: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    style_strength: str | None = None

    def allowed_kwargs(self) -> dict[str, Any]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


class TemplateExportRequest(BaseModel):
    ids: list[int] | None = None
    format: str = Field(default='json')


class TemplateImportRequest(BaseModel):
    data: str = Field(default='', description='JSON 文本；缺省时用整个请求体')


class ModeGenerateRequest(BaseModel):
    """工作模式生成入口的占位请求体（P2 接入写作图后启用）。"""

    templates: list[dict[str, Any]] = Field(default_factory=list)
    api_key: str = ''
    provider: str = 'deepseek'
    model: str = 'deepseek-v4-pro'
