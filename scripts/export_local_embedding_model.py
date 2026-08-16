"""从官方 Hugging Face 权重导出 Flora 使用的本地 ONNX 模型。"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path


MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_VERSION = "1.5-onnx-v1"
DIMENSION = 512
MAX_TOKENS = 512
ONNX_OPSET = 17
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(model_path: Path, vocab_path: Path) -> dict:
    return {
        "schema_version": 1,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "dimension": DIMENSION,
        "max_tokens": MAX_TOKENS,
        "model_file": model_path.name,
        "vocab_file": vocab_path.name,
        "model_sha256": sha256_file(model_path),
        "vocab_sha256": sha256_file(vocab_path),
        "onnx_opset": ONNX_OPSET,
        "pooling": "cls",
        "normalize": "l2",
        "query_instruction": QUERY_INSTRUCTION,
        "source": f"https://huggingface.co/{MODEL_ID}",
        "source_license": "MIT",
        "exporter": {
            "torch": "2.7.1",
            "transformers": "4.53.2",
            "onnx": "1.18.0",
        },
    }


def export_model(output_dir: Path) -> None:
    import onnx  # noqa: PLC0415
    import torch  # noqa: PLC0415
    from transformers import AutoModel, AutoTokenizer  # noqa: PLC0415

    class LastHiddenState(torch.nn.Module):
        def __init__(self, model):
            super().__init__()
            self.model = model

        def forward(self, input_ids, attention_mask, token_type_ids):
            return self.model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
                return_dict=False,
            )[0]

    output_dir.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=False)
    model = AutoModel.from_pretrained(MODEL_ID, trust_remote_code=False).eval()
    if int(model.config.hidden_size) != DIMENSION:
        raise RuntimeError(f"模型维度异常：预期 {DIMENSION}，实际 {model.config.hidden_size}")

    encoded = tokenizer(
        ["雨夜中的街道", "厨房里正在做饭"],
        padding=True,
        truncation=True,
        max_length=MAX_TOKENS,
        return_tensors="pt",
    )
    token_type_ids = encoded.get("token_type_ids", torch.zeros_like(encoded["input_ids"]))
    model_path = output_dir / "model.onnx"
    torch.onnx.export(
        LastHiddenState(model),
        (encoded["input_ids"], encoded["attention_mask"], token_type_ids),
        model_path,
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "token_type_ids": {0: "batch", 1: "sequence"},
            "last_hidden_state": {0: "batch", 1: "sequence"},
        },
        opset_version=ONNX_OPSET,
        do_constant_folding=True,
        dynamo=False,
    )
    onnx.checker.check_model(onnx.load(str(model_path)))

    saved_vocab = tokenizer.save_vocabulary(str(output_dir))
    if not saved_vocab:
        raise RuntimeError("Tokenizer did not export vocab.txt")
    vocab_path = Path(saved_vocab[0])
    if vocab_path.name != "vocab.txt":
        target_vocab = output_dir / "vocab.txt"
        shutil.copy2(vocab_path, target_vocab)
        vocab_path = target_vocab
    manifest = build_manifest(model_path, vocab_path)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def install_atomically(target_dir: Path, force: bool) -> None:
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.exists() and not force:
        raise FileExistsError(f"目标目录已存在：{target_dir}；如需替换请使用 --force")
    with tempfile.TemporaryDirectory(prefix="flora-embedding-") as temporary:
        staging = Path(temporary) / target_dir.name
        export_model(staging)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(staging, target_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="最终模型目录")
    parser.add_argument("--force", action="store_true", help="替换已存在的模型目录")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    install_atomically(args.output.expanduser().resolve(), args.force)
    print(f"本地模型已安装：{args.output.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
