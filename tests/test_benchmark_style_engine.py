import csv
import json
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from benchmark_style_engine import BenchmarkError, METHODS, run_benchmark  # noqa: E402
from services.style_feature_service import (  # noqa: E402
    STYLE_FEATURE_VERSION,
    analyze_style_features,
)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path.name


def build_fixture(tmp_path):
    reference = (
        "雨沿着旧窗缓慢落下，他没有立刻回答，只把杯子轻轻推到桌边。"
        "过了片刻，她才抬起眼睛，仿佛那些未说出口的话仍停在灯影里。"
    ) * 18
    close = (
        "风从长廊尽头缓慢吹来，他没有马上离开，只将信纸轻轻压在书下。"
        "片刻以后，她终于转过身，仿佛沉默仍旧藏在昏黄的光线里。"
    ) * 18
    short = "走。停。看。等。" * 180
    existing = (
        "夜色沉下来，他站在门旁，许久没有说话。她望着远处，随后慢慢合上书。"
    ) * 25
    features = analyze_style_features(reference)["features"]
    profile_features = {}
    for feature_id, value in features.items():
        if value is None:
            continue
        profile_features[feature_id] = {
            "median": value,
            "p25": value,
            "p75": value,
            "reliability": 1.0,
            "normalization": {"center": value, "scale": max(1.0, abs(value) * 0.15)},
        }
    profile = {
        "feature_version": STYLE_FEATURE_VERSION,
        "sample_count": 30,
        "valid_char_count": 30000,
        "confidence": 1.0,
        "features": profile_features,
    }
    (tmp_path / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    reference_path = write(tmp_path / "reference.txt", reference)
    candidates = {
        "baseline": {"text": write(tmp_path / "baseline.txt", short), "injected_references": []},
        "existing": {
            "text": write(tmp_path / "existing.txt", existing),
            "injected_references": [reference_path],
        },
        "new": {
            "text": write(tmp_path / "new.txt", close),
            "injected_references": [reference_path],
        },
        "strict": {
            "text": write(tmp_path / "strict.txt", reference),
            "injected_references": [reference_path],
        },
    }
    manifest = {
        "benchmark_id": "repeatable-fixture",
        "blind_seed": "fixed-seed",
        "author_profile": "profile.json",
        "tasks": [{
            "id": "task-01",
            "writing_task": "写一段雨夜重逢后的克制叙述。",
            "scene_type": "narration",
            "reference_author_samples": [reference_path],
            "candidates": candidates,
        }],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def snapshot_files(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_benchmark_outputs_metrics_and_repeatable_blind_package(tmp_path):
    manifest = build_fixture(tmp_path)
    output = tmp_path / "report"

    first = run_benchmark(manifest, output)
    first_snapshot = snapshot_files(first)
    second = run_benchmark(manifest, output)

    assert snapshot_files(second) == first_snapshot
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["methods"] == list(METHODS)
    assert summary["task_count"] == 1
    assert summary["automatic_metrics_are_not_human_judgment"] is True
    with (output / "task_scores.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    by_method = {row["method"]: row for row in rows}
    assert float(by_method["new"]["style_distance"]) < float(
        by_method["baseline"]["style_distance"]
    )
    assert float(by_method["strict"]["content_leakage"]) > 0.9
    assert int(float(by_method["strict"]["max_longest_common_substring"])) > 100
    assert float(by_method["strict"]["max_character_ngram_overlap"]) == 1.0

    blind = output / "blind-test" / "task-01"
    assert {path.name for path in blind.iterdir()} == {
        "reference_01.txt", "candidate_A.txt", "candidate_B.txt",
        "candidate_C.txt", "candidate_D.txt", "QUESTION.txt",
    }
    question = (blind / "QUESTION.txt").read_text(encoding="utf-8")
    assert all(method not in question.lower() for method in METHODS)
    admin = json.loads((output / "blind-test-admin-key.json").read_text(encoding="utf-8"))
    assert set(admin["tasks"]["task-01"].values()) == set(METHODS)


def test_non_baseline_candidate_requires_actual_injected_references(tmp_path):
    manifest_path = build_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tasks"][0]["candidates"]["existing"]["injected_references"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkError, match="实际注入"):
        run_benchmark(manifest_path, tmp_path / "invalid-report")
