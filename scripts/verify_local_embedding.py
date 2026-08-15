"""验证 Forestar 本地 Embedding 模型、batch 推理与基本中文场景语义。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from services.embedding_backends import LocalEmbeddingBackend  # noqa: E402


def cosine(left, right) -> float:
    return float(np.asarray(left, dtype=np.float32) @ np.asarray(right, dtype=np.float32))


def verify(model_dir: Path | None = None) -> dict:
    backend = LocalEmbeddingBackend(model_dir=model_dir)
    query = backend.embed_text("雨夜里，一个人沿着湿漉漉的街道前行。", is_query=True)
    same_scene, unrelated = backend.embed_batch([
        "夜雨落在路灯下，行人踩过积水。",
        "厨师把面粉和鸡蛋放进烤箱。",
    ])
    same_score = cosine(query, same_scene)
    unrelated_score = cosine(query, unrelated)
    if len(query) != backend.dimension:
        raise RuntimeError(f"向量维度错误：{len(query)} != {backend.dimension}")
    if same_score <= unrelated_score:
        raise RuntimeError(
            f"中文场景验证失败：相近={same_score:.4f}，无关={unrelated_score:.4f}"
        )
    return {
        "backend": backend.backend_id,
        "model": backend.model_id,
        "version": backend.model_version,
        "dimension": backend.dimension,
        "same_scene_score": round(same_score, 6),
        "unrelated_scene_score": round(unrelated_score, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path)
    args = parser.parse_args()
    result = verify(args.model_dir)
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
