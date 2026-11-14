"""
读取本机 DeepSeek API Key（仅本机回环服务使用）。

密钥来源优先级：
1. 环境变量 ``DEEPSEEK_API_KEY``（兼容 ``DEEPSEEK-API-KEY`` 写法）
2. 环境变量 ``FLORA_DEEPSEEK_KEY_FILE`` 指定的文件
   （文件内容即密钥，或包含 ``DEEPSEEK_API_KEY=...`` 的 .env 风格行）
3. 常用默认路径（按顺序探测）：
   - ``%USERPROFILE%\\.flora-editor\\deepseek-api-key.txt``
   - ``%USERPROFILE%\\.flora-editor\\data\\deepseek-api-key.txt``
   - 项目根目录 ``.env``（解析 ``DEEPSEEK_API_KEY=`` 行）
   - 项目根目录 ``deepseek-api-key.txt``
   - ``~/.deepseek-api-key``
   - ``~/.deepseek/api_key``

说明：本模块只在回环地址（127.0.0.1）的本地服务中调用；密钥不会写入
SQLite、日志或任何持久化存储，仅在用户点击“读取本机 Key”时返回给同一
回环来源的前端页面，用于填入密钥输入框。
"""
import os
from pathlib import Path


# 支持的环境变量名（下划线与连字符写法都接受）
_KEY_ENV_NAMES = ("DEEPSEEK_API_KEY", "DEEPSEEK-API-KEY")


def _clean(value):
    """去除首尾空白与成对引号；空值返回 None。"""
    if not value:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    return value or None


def _parse_env_file(text):
    """从 .env 风格文本中解析 DeepSeek 密钥行。"""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip().upper() in _KEY_ENV_NAMES:
            cleaned = _clean(value)
            if cleaned:
                return cleaned
    return None


def _read_key_file(path):
    """读取密钥文件：整文件即密钥，或包含 DEEPSEEK_API_KEY= 的 .env 行。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if not text.strip():
        return None
    whole = _clean(text)
    # 密钥一般不含 '='（DeepSeek Key 形如 sk-...）；含 '=' 视为 .env 格式
    if whole and "=" not in whole:
        return whole
    return _parse_env_file(text)


def _candidate_paths():
    """返回默认探测路径（去重）。"""
    home = Path.home()
    userprofile = Path(os.environ["USERPROFILE"]) if os.environ.get("USERPROFILE") else home
    # server/services/ 的上级的上级 = 项目根目录
    project_root = Path(__file__).resolve().parent.parent.parent
    candidates = [
        userprofile / ".flora-editor" / "deepseek-api-key.txt",
        userprofile / ".flora-editor" / "data" / "deepseek-api-key.txt",
        project_root / ".env",
        project_root / "deepseek-api-key.txt",
        home / ".deepseek-api-key",
        home / ".deepseek" / "api_key",
    ]
    seen = set()
    paths = []
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            paths.append(path)
    return paths


def find_local_deepseek_key():
    """按优先级查找本机 DeepSeek API Key。

    返回 ``(key, source_label)``；未找到时返回 ``(None, None)``。
    """
    # 1) 环境变量
    for name in _KEY_ENV_NAMES:
        value = _clean(os.environ.get(name))
        if value:
            return value, f"环境变量 {name}"

    # 2) 显式指定文件
    explicit = _clean(os.environ.get("FLORA_DEEPSEEK_KEY_FILE"))
    if explicit:
        path = Path(explicit)
        value = _read_key_file(path)
        if value:
            return value, f"文件 {path}"

    # 3) 默认路径
    for path in _candidate_paths():
        value = _read_key_file(path)
        if value:
            return value, f"文件 {path}"

    return None, None


def mask_key(key):
    """脱敏显示：sk-xxxx****abcd。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * 6}{key[-4:]}"
