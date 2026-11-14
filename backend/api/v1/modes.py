"""工作模式路由（3 个端点）。

``generate`` 与旧实现一样只是占位：返回 501，等 P2 把写作图接进来后
再改成真正的生成入口。现在保持 501 是"行为一致"，不是"没做完"。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.api.v1.schemas import ModeGenerateRequest
from backend.services.work_modes import get_work_mode, list_work_modes

router = APIRouter()

MODE_NOT_FOUND = {'success': False, 'error': '工作模式不存在'}


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content=MODE_NOT_FOUND)


@router.get('/v1/modes', tags=['工作模式'])
@router.get('/modes', tags=['工作模式'], include_in_schema=False)
async def list_modes() -> dict[str, Any]:
    return {'success': True, 'data': {'modes': list_work_modes()}}


@router.get('/v1/modes/{mode_id}', tags=['工作模式'])
@router.get('/modes/{mode_id}', tags=['工作模式'], include_in_schema=False)
async def get_mode(mode_id: str) -> Any:
    mode = get_work_mode(mode_id)
    if mode is None:
        return _not_found()
    return {'success': True, 'data': mode}


@router.post('/v1/modes/{mode_id}/generate', tags=['工作模式'])
@router.post('/modes/{mode_id}/generate', tags=['工作模式'], include_in_schema=False)
async def generate_for_mode(mode_id: str, payload: ModeGenerateRequest | None = None) -> Any:
    mode = get_work_mode(mode_id)
    if mode is None:
        return _not_found()
    return JSONResponse(
        status_code=501,
        content={
            'success': False,
            'error': f"工作模式「{mode['name']}」的生成接口尚未实现（预设骨架）",
        },
    )
