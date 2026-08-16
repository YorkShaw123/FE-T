"""可插拔文本向量后端；Embedding 只为 Style Retrieval 提供可选辅助信号。"""
from __future__ import annotations

import json
import hashlib
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from config import Config
from services.api_client import LLMClient, LLMClientError


LOCAL_MODEL_ID = 'BAAI/bge-small-zh-v1.5'
LOCAL_MODEL_VERSION = '1.5-onnx-v1'
LOCAL_EMBEDDING_DIMENSION = 512
LOCAL_MAX_TOKENS = 512
QUERY_INSTRUCTION = '为这个句子生成表示以用于检索相关文章：'


class EmbeddingBackendError(RuntimeError):
    """Embedding 后端执行失败。"""


class EmbeddingBackendUnavailable(EmbeddingBackendError):
    """可选运行时或模型文件不可用。"""


class EmbeddingBackend(ABC):
    backend_id: str
    model_id: str
    model_version: str
    dimension: int

    @property
    def signature(self):
        return (self.backend_id, self.model_id, self.model_version, self.dimension)

    def embed_text(self, text, *, is_query=False):
        vectors = self.embed_batch([text], is_query=is_query)
        if len(vectors) != 1:
            raise EmbeddingBackendError('Embedding 后端返回数量异常')
        return vectors[0]

    @abstractmethod
    def embed_batch(self, texts, *, is_query=False):
        """按输入顺序返回向量。"""


class RemoteEmbeddingBackend(EmbeddingBackend):
    backend_id = 'remote:siliconflow'
    model_id = Config.EMBEDDING_MODEL
    model_version = 'provider-current'
    dimension = Config.EMBEDDING_DIMENSIONS

    def __init__(self, api_key, provider='siliconflow'):
        if provider != 'siliconflow':
            raise EmbeddingBackendUnavailable('当前远程 Embedding 仅兼容硅基流动')
        if not (api_key or '').strip():
            raise EmbeddingBackendUnavailable('远程 Embedding 需要 API Key')
        self._client = LLMClient(provider=provider, api_key=api_key.strip())

    def embed_batch(self, texts, *, is_query=False):
        del is_query
        try:
            return self._client.embed(list(texts))
        except LLMClientError as exc:
            raise EmbeddingBackendError(str(exc)) from exc


def default_models_dir():
    override = os.environ.get('FLORA_MODELS_DIR')
    if override:
        return Path(override).expanduser()
    models_dir = Path.home() / '.flora-editor' / 'models'
    if models_dir.exists():
        return models_dir
    previous_brand = 'fore' + 'star'
    previous_models_dir = Path.home() / f'.{previous_brand}-editor' / 'models'
    return previous_models_dir if previous_models_dir.exists() else models_dir


_SESSION_CACHE = {}
_SESSION_LOCK = threading.Lock()
_CHECKSUM_CACHE = {}


def _verify_checksum(path, expected):
    if not expected:
        return
    stat = path.stat()
    cache_key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, expected)
    with _SESSION_LOCK:
        if cache_key in _CHECKSUM_CACHE:
            return
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest().lower() != str(expected).lower():
        raise EmbeddingBackendUnavailable(f'本地模型文件校验失败：{path.name}，请重新安装模型')
    with _SESSION_LOCK:
        _CHECKSUM_CACHE[cache_key] = True


class LocalEmbeddingBackend(EmbeddingBackend):
    backend_id = 'local:onnxruntime-cpu'

    def __init__(self, model_dir=None, session_factory=None):
        self.model_dir = Path(model_dir or default_models_dir() / 'bge-small-zh-v1.5')
        manifest_path = self.model_dir / 'manifest.json'
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise EmbeddingBackendUnavailable(
                f'本地 Embedding 模型缺失或 manifest 无效：{manifest_path}'
            ) from exc
        self.model_id = str(manifest.get('model_id') or LOCAL_MODEL_ID)
        self.model_version = str(manifest.get('model_version') or LOCAL_MODEL_VERSION)
        self.dimension = int(manifest.get('dimension') or LOCAL_EMBEDDING_DIMENSION)
        self.max_tokens = min(int(manifest.get('max_tokens') or LOCAL_MAX_TOKENS), LOCAL_MAX_TOKENS)
        self.query_instruction = str(manifest.get('query_instruction') or QUERY_INSTRUCTION)
        self._model_path = self.model_dir / str(manifest.get('model_file') or 'model.onnx')
        self._vocab_path = self.model_dir / str(manifest.get('vocab_file') or 'vocab.txt')
        if not self._model_path.is_file() or not self._vocab_path.is_file():
            raise EmbeddingBackendUnavailable('本地 Embedding 模型文件不完整，请安装后重新索引')
        _verify_checksum(self._model_path, manifest.get('model_sha256'))
        _verify_checksum(self._vocab_path, manifest.get('vocab_sha256'))
        self._vocab = {
            token.rstrip('\r\n'): index
            for index, token in enumerate(self._vocab_path.read_text(encoding='utf-8').splitlines())
        }
        for token in ('[PAD]', '[UNK]', '[CLS]', '[SEP]'):
            if token not in self._vocab:
                raise EmbeddingBackendUnavailable(f'本地模型词表缺少 {token}')
        self._session = self._get_session(session_factory)

    def _get_session(self, session_factory):
        cache_key = str(self._model_path.resolve())
        with _SESSION_LOCK:
            if cache_key not in _SESSION_CACHE:
                if session_factory is None:
                    try:
                        import onnxruntime as ort  # noqa: PLC0415
                    except ImportError as exc:
                        raise EmbeddingBackendUnavailable('未安装可选依赖 onnxruntime') from exc
                    session_factory = lambda path: ort.InferenceSession(  # noqa: E731
                        path, providers=['CPUExecutionProvider'],
                    )
                try:
                    _SESSION_CACHE[cache_key] = session_factory(str(self._model_path))
                except Exception as exc:
                    raise EmbeddingBackendUnavailable(f'无法加载本地 ONNX 模型：{exc}') from exc
            return _SESSION_CACHE[cache_key]

    def _wordpiece(self, text):
        """轻量中文优先 WordPiece；连续英文/数字按标准子词贪心切分。"""
        import re

        basic = re.findall(r'[\u4e00-\u9fff]|[A-Za-z]+|\d+|[^\s]', text.lower())
        output = []
        for token in basic:
            if token in self._vocab:
                output.append(token)
                continue
            start, pieces = 0, []
            while start < len(token):
                end, found = len(token), None
                while end > start:
                    piece = token[start:end]
                    candidate = piece if start == 0 else f'##{piece}'
                    if candidate in self._vocab:
                        found = candidate
                        break
                    end -= 1
                if found is None:
                    pieces = ['[UNK]']
                    break
                pieces.append(found)
                start = end
            output.extend(pieces)
        return output

    def _encode(self, text, is_query):
        source = f'{self.query_instruction}{text}' if is_query else str(text or '')
        tokens = self._wordpiece(source)[:self.max_tokens - 2]
        ids = [self._vocab['[CLS]'], *[self._vocab.get(t, self._vocab['[UNK]']) for t in tokens],
               self._vocab['[SEP]']]
        return ids

    def embed_batch(self, texts, *, is_query=False):
        texts = list(texts)
        if not texts:
            return []
        import numpy as np

        encoded = [self._encode(text, is_query) for text in texts]
        width = max(len(ids) for ids in encoded)
        pad = self._vocab['[PAD]']
        input_ids = np.asarray([ids + [pad] * (width - len(ids)) for ids in encoded], dtype=np.int64)
        attention = (input_ids != pad).astype(np.int64)
        available = {item.name for item in self._session.get_inputs()}
        feeds = {'input_ids': input_ids, 'attention_mask': attention}
        if 'token_type_ids' in available:
            feeds['token_type_ids'] = np.zeros_like(input_ids)
        feeds = {name: value for name, value in feeds.items() if name in available}
        try:
            output = self._session.run(None, feeds)[0]
        except Exception as exc:
            raise EmbeddingBackendError(f'本地 Embedding 推理失败：{exc}') from exc
        array = np.asarray(output, dtype=np.float32)
        vectors = array[:, 0, :] if array.ndim == 3 else array
        if vectors.ndim != 2 or vectors.shape != (len(texts), self.dimension):
            raise EmbeddingBackendError(
                f'本地模型输出维度异常：期望 {len(texts)}x{self.dimension}，实际 {vectors.shape}'
            )
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vectors / norms).tolist()


def create_embedding_backend(kind='auto', *, api_key='', provider='siliconflow', model_dir=None):
    """创建后端；auto 优先本地，有显式 API Key 时兼容旧远程行为。"""
    kind = (kind or 'auto').strip().lower()
    if kind == 'remote' or (kind == 'auto' and (api_key or '').strip()):
        return RemoteEmbeddingBackend(api_key, provider=provider)
    if kind not in {'auto', 'local'}:
        raise EmbeddingBackendUnavailable(f'未知 Embedding backend：{kind}')
    return LocalEmbeddingBackend(model_dir=model_dir)


def clear_embedding_session_cache():
    """仅供测试和显式模型升级后释放进程内 Session。"""
    with _SESSION_LOCK:
        _SESSION_CACHE.clear()
        _CHECKSUM_CACHE.clear()
