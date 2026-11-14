"""系统级端点（桌面环境辅助）。

旧版有四个端点，服务化后依然保留接口，方便前端与旧脚本继续调用：

- 读取本机 DeepSeek API Key（读环境变量或密钥文件，不落库）
- 打开社区提示词页面 / 打开帮助链接（调用系统默认浏览器）
- 关闭后端（Tauri / 脚本退出时使用）

浏览器不可用时不会抛错，只返回 opened=False，保证接口在无界面环境也能用。
"""

from __future__ import annotations

import os
import threading
import webbrowser
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.services.local_api_key import find_local_deepseek_key, mask_key

router = APIRouter()

COMMUNITY_PROMPTS_URL = 'https://www.aishort.top/community-prompts'
HELP_LINKS = {
    'deepseek': 'https://api-docs.deepseek.com/',
    'openai': 'https://platform.openai.com/docs/overview',
    'moonshot': 'https://platform.moonshot.cn/docs/intro',
    'qwen': 'https://help.aliyun.com/zh/model-studio/getting-started/what-is-model-studio',
    'zhipu': 'https://docs.bigmodel.cn/cn/guide/start/quick-start',
    'gemini': 'https://ai.google.dev/gemini-api/docs',
    'xai': 'https://docs.x.ai/docs/overview',
    'siliconflow': 'https://docs.siliconflow.cn/',
    'aishort': COMMUNITY_PROMPTS_URL,
}


def _open_url(url: str) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


@router.post('/v1/system/deepseek-key', tags=['系统'])
@router.post('/system/deepseek-api-key', tags=['系统'], include_in_schema=False)
async def read_local_deepseek_key() -> dict[str, Any]:
    key = find_local_deepseek_key()
    return {
        'success': True,
        'data': {
            'found': bool(key),
            'masked': mask_key(key) if key else '',
            'api_key': key,
            'message': (
                '已从本机读取 DeepSeek API Key'
                if key
                else '未在本机找到 DeepSeek API Key，请设置 DEEPSEEK_API_KEY 或密钥文件'
            ),
        },
    }


@router.post('/v1/system/open-community-prompts', tags=['系统'])
@router.post('/system/open-community-prompts', tags=['系统'], include_in_schema=False)
async def open_community_prompts() -> dict[str, Any]:
    return {'success': True, 'data': {'opened': _open_url(COMMUNITY_PROMPTS_URL),
                                      'url': COMMUNITY_PROMPTS_URL}}


@router.post('/v1/system/open-help/{link_key}', tags=['系统'])
@router.post('/system/open-help-link/{link_key}', tags=['系统'], include_in_schema=False)
async def open_help_link(link_key: str) -> Any:
    url = HELP_LINKS.get(link_key)
    if url is None:
        return JSONResponse(status_code=404, content={'success': False, 'error': '没有这个帮助链接'})
    return {'success': True, 'data': {'opened': _open_url(url), 'url': url}}


@router.post('/v1/system/shutdown', tags=['系统'])
@router.post('/system/shutdown', tags=['系统'], include_in_schema=False)
async def shutdown_backend() -> dict[str, Any]:
    """先返回响应，再延迟退出进程。"""
    def _exit() -> None:
        os._exit(0)

    threading.Timer(0.5, _exit).start()
    return {'success': True, 'message': '后端正在关闭'}
