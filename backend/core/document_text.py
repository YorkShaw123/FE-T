"""TXT / DOCX / 旧版 DOC 的安全文本提取。

从 ``server/routes/support/document_text.py`` 平移而来，逻辑一字未改：
大小上限 10MB、编码按 utf-8-sig → gb18030 → utf-16 → big5 依次尝试、
DOCX 直接读 word/document.xml、老 DOC 用 olefile 抽 WordDocument 流。
差别只有包装方式：这里接收 bytes + 文件名，与 FastAPI 的 UploadFile 对接。
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_ARTICLE_FILE_SIZE = 10 * 1024 * 1024
SUPPORTED_ARTICLE_EXTENSIONS = frozenset({'.txt', '.doc', '.docx'})


def extract_uploaded_bytes(raw: bytes, filename: str) -> str:
    """按扩展名提取文本。调用方负责先做大小检查（或直接用本函数的超限判断）。"""
    if not filename:
        raise ValueError('请选择要导入的文件')

    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_ARTICLE_EXTENSIONS:
        raise ValueError('仅支持 .txt、.doc、.docx 文件')
    if len(raw) > MAX_ARTICLE_FILE_SIZE:
        raise OverflowError('文件不能超过 10 MB')
    if not raw:
        raise ValueError('文件内容为空')

    if extension == '.txt':
        text = _decode_text_file(raw)
    elif extension == '.docx':
        text = _extract_docx(raw)
    else:
        text = _extract_legacy_doc(raw)

    text = text.replace('\x00', '').strip()
    if not text:
        raise ValueError('文件中没有可读取的文本内容')
    return text


def extract_document_path(path) -> str:
    """从本地文件路径提取文本（离线批处理工具用；不修改原文件）。"""
    file_path = Path(path)
    extension = file_path.suffix.lower()
    if extension not in SUPPORTED_ARTICLE_EXTENSIONS:
        raise ValueError('仅支持 .txt、.doc、.docx 文件')
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise ValueError(f'无法读取文件：{file_path.name}') from exc
    if size > MAX_ARTICLE_FILE_SIZE:
        raise OverflowError('文件不能超过 10 MB')
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise ValueError(f'无法读取文件：{file_path.name}') from exc
    return extract_uploaded_bytes(raw, file_path.name)


def _decode_text_file(raw: bytes) -> str:
    for encoding in ('utf-8-sig', 'gb18030', 'utf-16', 'big5'):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')


def _extract_docx(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            document_xml = archive.read('word/document.xml')
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError('DOCX 文件已损坏或格式不正确') from exc

    root = ElementTree.fromstring(document_xml)
    namespace = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    paragraphs = []
    for paragraph in root.iter(namespace + 'p'):
        text = ''.join(node.text or '' for node in paragraph.iter(namespace + 't'))
        if text:
            paragraphs.append(text)
    return '\n'.join(paragraphs)


def _extract_legacy_doc(raw: bytes) -> str:
    try:
        import olefile
    except ImportError as exc:
        raise ValueError('服务器缺少旧版 DOC 解析组件，请安装 requirements.txt 中的依赖') from exc

    try:
        with olefile.OleFileIO(io.BytesIO(raw)) as ole:
            stream = ole.openstream('WordDocument').read()
    except Exception as exc:
        raise ValueError('DOC 文件已损坏或不是有效的 Word 文档') from exc

    decoded = stream.decode('utf-16le', errors='ignore')
    unicode_text = [
        item.strip()
        for item in re.findall(
            r'[\u0009\u0020-\u007e\u3000-\u9fff\uff00-\uffef]{4,}', decoded
        )
    ]
    ansi_text = [
        item.decode('gb18030', errors='ignore').strip()
        for item in re.findall(rb'[\x09\x20-\x7e\x80-\xff]{8,}', stream)
    ]
    candidates = [
        item
        for item in unicode_text + ansi_text
        if item and not item.startswith(('Microsoft', 'Word.Document'))
    ]
    if not candidates:
        raise ValueError('未能从该 DOC 文件中识别出文本，建议另存为 DOCX 后重试')
    return '\n'.join(dict.fromkeys(candidates))
