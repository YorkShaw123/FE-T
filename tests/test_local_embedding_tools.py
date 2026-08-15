import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "server"))

from export_local_embedding_model import build_manifest  # noqa: E402
from services.embedding_backends import (  # noqa: E402
    EmbeddingBackendUnavailable,
    LocalEmbeddingBackend,
    clear_embedding_session_cache,
)


class _Input:
    def __init__(self, name):
        self.name = name


class _Session:
    def __init__(self, _path):
        pass

    def get_inputs(self):
        return [_Input("input_ids"), _Input("attention_mask"), _Input("token_type_ids")]


def _write_fake_model(model_dir: Path):
    model_dir.mkdir()
    model_path = model_dir / "model.onnx"
    vocab_path = model_dir / "vocab.txt"
    model_path.write_bytes(b"onnx-placeholder")
    vocab_path.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n", encoding="utf-8")
    manifest = build_manifest(model_path, vocab_path)
    (model_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return model_path, manifest


def test_manifest_records_identity_source_and_checksums(tmp_path):
    model_path, manifest = _write_fake_model(tmp_path / "model")

    assert manifest["model_id"] == "BAAI/bge-small-zh-v1.5"
    assert manifest["dimension"] == 512
    assert manifest["onnx_opset"] == 17
    assert manifest["source_license"] == "MIT"
    assert manifest["model_sha256"] == hashlib.sha256(model_path.read_bytes()).hexdigest()


def test_backend_rejects_corrupted_installed_model(tmp_path):
    model_path, _manifest = _write_fake_model(tmp_path / "model")
    model_path.write_bytes(b"corrupted")
    clear_embedding_session_cache()

    try:
        LocalEmbeddingBackend(tmp_path / "model", session_factory=_Session)
    except EmbeddingBackendUnavailable as exc:
        assert "校验失败" in str(exc)
    else:
        raise AssertionError("损坏的模型不应被加载")
