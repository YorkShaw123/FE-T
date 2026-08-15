"""Repeatable offline scoring and blind-test packaging for frozen A/B/C/D outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from routes.support.document_text import extract_document_path  # noqa: E402
from services.author_style_profile_service import resolve_mode_profile  # noqa: E402
from services.style_feature_service import (  # noqa: E402
    STYLE_FEATURE_VERSION,
    analyze_style_features,
)
from services.style_rag_service import rule_tag_chunk  # noqa: E402
from services.style_retrieval_service import (  # noqa: E402
    content_leakage_metrics,
    scene_similarity,
    style_similarity_scores,
)


METHODS = ("baseline", "existing", "new", "strict")
METHOD_LABELS = {
    "baseline": "A. Baseline / 普通提示词",
    "existing": "B. Existing / 旧 Style RAG",
    "new": "C. New / Style Retrieval",
    "strict": "D. Strict / Style Retrieval + Style Diff Rewrite",
}
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "style-benchmark-reports"
SCORE_FIELDS = (
    "style_distance", "rhythm_distance", "punctuation_distance",
    "function_word_distance", "scene_compatibility", "content_leakage",
    "max_character_ngram_overlap", "max_longest_common_substring",
)


class BenchmarkError(RuntimeError):
    pass


def _rounded(value):
    return round(float(value), 6)


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise BenchmarkError(f"文件不存在：{path}")
    if path.suffix.lower() not in {".txt", ".docx"}:
        raise BenchmarkError(f"只支持 TXT/DOCX：{path}")
    text = extract_document_path(path)
    if not text.strip():
        raise BenchmarkError(f"文本为空：{path}")
    return text


def _resolve_path(base: Path, value: str, field: str) -> Path:
    if not value:
        raise BenchmarkError(f"缺少路径字段：{field}")
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def _load_profile(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"无法读取 Author Profile：{path}") from exc
    return _load_profile_payload(payload)


def _load_profile_spec(spec, base: Path) -> tuple[dict, bytes]:
    if isinstance(spec, str):
        path = _resolve_path(base, spec, "author_profile")
        return _load_profile(path), path.read_bytes()
    if not isinstance(spec, dict) or not spec.get("corpus_id"):
        raise BenchmarkError("author_profile 必须是 JSON 路径或包含 corpus_id 的对象")
    from app import create_app
    from services.author_style_profile_service import get_author_style_profile

    app = create_app("production")
    with app.app_context():
        record, stale = get_author_style_profile(int(spec["corpus_id"]))
        if not record:
            raise BenchmarkError("指定 corpus 尚未建立 Author Style Profile")
        if stale:
            raise BenchmarkError("指定 corpus 的 Author Style Profile 已失效，请先重建")
        raw = record.profile_json.encode("utf-8")
        return _load_profile_payload(json.loads(record.profile_json)), raw


def _load_profile_payload(payload: dict) -> dict:
    profile = payload.get("profile", payload)
    if profile.get("feature_version") != STYLE_FEATURE_VERSION:
        raise BenchmarkError(
            f"Author Profile Feature 版本不兼容：需要 {STYLE_FEATURE_VERSION}，"
            f"实际 {profile.get('feature_version')}"
        )
    if not profile.get("features"):
        raise BenchmarkError("Author Profile 缺少 features")
    return profile


def _candidate_config(raw, task_id: str, method: str) -> dict:
    if isinstance(raw, str):
        raw = {"text": raw, "injected_references": []}
    if not isinstance(raw, dict):
        raise BenchmarkError(f"任务 {task_id} 的 {method} 候选格式无效")
    if method != "baseline" and not raw.get("injected_references"):
        raise BenchmarkError(
            f"任务 {task_id} 的 {method} 必须列出当次实际注入的 reference chunks"
        )
    return raw


def _max_leakage(candidate: str, references: list[tuple[str, str]]) -> dict:
    if not references:
        return {
            "content_leakage": 0.0,
            "max_character_ngram_overlap": 0.0,
            "max_longest_common_substring": 0,
            "max_keyword_overlap": 0.0,
            "highest_overlap_reference_id": None,
        }
    measured = []
    for reference_id, reference in references:
        metrics = content_leakage_metrics(candidate, reference)
        measured.append((reference_id, metrics))
    highest_id, highest = max(
        measured,
        key=lambda item: (
            item[1]["content_overlap_penalty"],
            item[1]["ngram_overlap"],
            item[1]["longest_common_substring"],
            item[0],
        ),
    )
    return {
        "content_leakage": highest["content_overlap_penalty"],
        "max_character_ngram_overlap": max(
            item[1]["ngram_overlap"] for item in measured
        ),
        "max_longest_common_substring": max(
            item[1]["longest_common_substring"] for item in measured
        ),
        "max_keyword_overlap": max(item[1]["keyword_overlap"] for item in measured),
        "highest_overlap_reference_id": highest_id,
    }


def score_candidate(text: str, target_profile: dict, scene_type: str, references) -> dict:
    analysis = analyze_style_features(text)
    scores = style_similarity_scores(analysis["features"], target_profile)
    detected_scene = rule_tag_chunk(text)["scene_type"]
    leakage = _max_leakage(text, references)
    return {
        "style_distance": _rounded(1.0 - scores["style_score"]),
        "rhythm_distance": _rounded(1.0 - scores["rhythm_score"]),
        "punctuation_distance": _rounded(1.0 - scores["punctuation_score"]),
        "function_word_distance": _rounded(1.0 - scores["function_word_score"]),
        "scene_compatibility": _rounded(scene_similarity(detected_scene, scene_type)),
        "detected_scene": detected_scene,
        "style_confidence": scores["confidence"],
        "valid_char_count": analysis["statistics"]["valid_char_count"],
        **leakage,
    }


def _anonymous_order(seed: str, task_id: str) -> list[str]:
    return sorted(
        METHODS,
        key=lambda method: hashlib.sha256(
            f"{seed}\0{task_id}\0{method}".encode("utf-8")
        ).hexdigest(),
    )


def _write_json(path: Path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_scores(path: Path, rows: list[dict]):
    fields = (
        "task_id", "method", *SCORE_FIELDS, "max_keyword_overlap",
        "highest_overlap_reference_id", "detected_scene", "style_confidence",
        "valid_char_count",
    )
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _aggregate(rows: list[dict]) -> dict:
    output = {}
    for method in METHODS:
        method_rows = [row for row in rows if row["method"] == method]
        output[method] = {
            "label": METHOD_LABELS[method],
            "task_count": len(method_rows),
            "metrics": {
                field: _rounded(statistics.mean(row[field] for row in method_rows))
                for field in SCORE_FIELDS
            },
        }
    return output


def _write_report(path: Path, benchmark_id: str, aggregate: dict, task_count: int):
    lines = [
        f"# Style Engine Benchmark：{benchmark_id}", "",
        "> 自动指标只衡量冻结规则下的表层风格距离、场景兼容和文本复用风险，"
        "不等价于人类对作者相似度、文学质量或自然度的判断。", "",
        f"任务数：{task_count}；每个任务均包含 Baseline / Existing / New / Strict。", "",
        "## 聚合结果", "",
        "| 方法 | Style↓ | Rhythm↓ | Punctuation↓ | Function-word↓ | Scene↑ | Leakage↓ | 8-gram↓ | 最长连续复用↓ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in METHODS:
        metrics = aggregate[method]["metrics"]
        lines.append(
            f"| {METHOD_LABELS[method]} | {metrics['style_distance']:.4f} | "
            f"{metrics['rhythm_distance']:.4f} | {metrics['punctuation_distance']:.4f} | "
            f"{metrics['function_word_distance']:.4f} | {metrics['scene_compatibility']:.4f} | "
            f"{metrics['content_leakage']:.4f} | "
            f"{metrics['max_character_ngram_overlap']:.4f} | "
            f"{metrics['max_longest_common_substring']:.2f} |"
        )
    lines.extend([
        "", "## 阅读方式", "",
        "- Distance、Leakage、8-gram 和连续复用越低越好；Scene compatibility 越高越好。",
        "- 必须结合匿名人工盲测结果解读，不能只按综合自动指标宣布某方案胜出。",
        "- Existing 代表 manifest 中保存的旧 Style RAG 实际结果，不由本工具重新生成。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_benchmark(manifest_path: Path, output_dir: Path | None = None) -> Path:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"无法读取 manifest：{manifest_path}") from exc
    base = manifest_path.resolve().parent
    benchmark_id = str(manifest.get("benchmark_id") or manifest_path.stem)
    seed = str(manifest.get("blind_seed") or "forestar-style-benchmark-v1")
    author_profile, profile_bytes = _load_profile_spec(manifest.get("author_profile"), base)
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise BenchmarkError("manifest.tasks 必须是非空数组")
    fingerprint = hashlib.sha256(manifest_path.read_bytes()).hexdigest()[:10]
    output = output_dir or DEFAULT_OUTPUT_ROOT / f"{benchmark_id}-{fingerprint}"
    output.mkdir(parents=True, exist_ok=True)
    blind_root = output / "blind-test"
    blind_root.mkdir(exist_ok=True)

    rows = []
    mapping = {"benchmark_id": benchmark_id, "tasks": {}}
    input_hash = hashlib.sha256(manifest_path.read_bytes())
    input_hash.update(profile_bytes)
    seen_ids = set()
    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        if not task_id or task_id in seen_ids:
            raise BenchmarkError("每个任务必须有唯一、非空 id")
        seen_ids.add(task_id)
        scene_type = str(task.get("scene_type") or "mixed")
        writing_task = str(task.get("writing_task") or "").strip()
        if not writing_task:
            raise BenchmarkError(f"任务 {task_id} 缺少 writing_task")
        input_hash.update(writing_task.encode("utf-8"))
        resolution = resolve_mode_profile(author_profile, scene_type)
        target_profile = resolution["profile"]
        candidates = task.get("candidates") or {}
        texts = {}
        for method in METHODS:
            config = _candidate_config(candidates.get(method), task_id, method)
            text = _read_text(_resolve_path(base, config.get("text", ""), f"{task_id}.{method}.text"))
            references = []
            for index, raw_path in enumerate(config.get("injected_references") or [], start=1):
                reference = _read_text(_resolve_path(
                    base, raw_path, f"{task_id}.{method}.injected_references[{index}]"
                ))
                references.append((f"{method}-ref-{index:02d}", reference))
            score = score_candidate(text, target_profile, scene_type, references)
            rows.append({"task_id": task_id, "method": method, **score})
            texts[method] = text
            input_hash.update(text.encode("utf-8"))
            for _, reference in references:
                input_hash.update(reference.encode("utf-8"))

        task_dir = blind_root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        reference_paths = task.get("reference_author_samples") or []
        if not reference_paths:
            raise BenchmarkError(f"任务 {task_id} 缺少 reference_author_samples")
        for index, raw_path in enumerate(reference_paths, start=1):
            reference = _read_text(_resolve_path(
                base, raw_path, f"{task_id}.reference_author_samples[{index}]"
            ))
            (task_dir / f"reference_{index:02d}.txt").write_text(reference, encoding="utf-8")
            input_hash.update(reference.encode("utf-8"))
        order = _anonymous_order(seed, task_id)
        task_mapping = {}
        for label, method in zip("ABCD", order, strict=True):
            (task_dir / f"candidate_{label}.txt").write_text(texts[method], encoding="utf-8")
            task_mapping[label] = method
        (task_dir / "QUESTION.txt").write_text(
            "请先阅读 reference_author_samples，然后回答：\n"
            "1. Candidate A/B/C/D 中，哪一篇在语言习惯上最像参考作者？\n"
            "2. 哪一篇最像在复述或复制参考内容？\n"
            "3. 哪一篇最自然？允许选择平局，并简要说明理由。\n",
            encoding="utf-8",
        )
        mapping["tasks"][task_id] = task_mapping

    aggregate = _aggregate(rows)
    summary = {
        "benchmark_version": 1,
        "benchmark_id": benchmark_id,
        "style_feature_version": STYLE_FEATURE_VERSION,
        "task_count": len(tasks),
        "methods": list(METHODS),
        "input_content_sha256": input_hash.hexdigest(),
        "automatic_metrics_are_not_human_judgment": True,
        "aggregate": aggregate,
    }
    _write_json(output / "summary.json", summary)
    _write_scores(output / "task_scores.csv", rows)
    _write_report(output / "report.md", benchmark_id, aggregate, len(tasks))
    _write_json(output / "blind-test-admin-key.json", mapping)
    return output


def build_parser():
    parser = argparse.ArgumentParser(
        description="对冻结的 A/B/C/D 生成稿执行本地 Style Engine Benchmark。"
    )
    parser.add_argument("manifest", type=Path, help="Benchmark manifest JSON 路径")
    parser.add_argument("--output", type=Path, help="报告目录；默认写入被 Git 忽略的目录")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        output = run_benchmark(args.manifest.resolve(), args.output.resolve() if args.output else None)
    except BenchmarkError as exc:
        print(f"Benchmark 失败：{exc}", file=sys.stderr)
        return 1
    print(f"Benchmark 完成：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
