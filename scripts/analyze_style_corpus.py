"""离线分析本地中文风格语料，输出可重复生成的诊断报告。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from routes.support.document_text import extract_document_path  # noqa: E402
from services.style_feature_service import (  # noqa: E402
    STYLE_FEATURE_IDS,
    STYLE_FEATURE_VERSION,
    count_valid_characters,
)
from services.style_chunk_service import split_corpus_text  # noqa: E402
from services.style_window_service import iter_style_window_analyses  # noqa: E402


SUPPORTED_CORPUS_EXTENSIONS = frozenset({".txt", ".docx"})
DEFAULT_REPORT_ROOT = PROJECT_ROOT / "style-analysis-reports"
OUTLIER_ROBUST_Z_THRESHOLD = 3.5
OUTLIER_IQR_MULTIPLIER = 3.0

CHUNK_METADATA_FIELDS = (
    "document_id",
    "chunk_id",
    "source_order",
    "current_valid_chars",
    "window_start_order",
    "window_end_order",
    "window_valid_chars",
    "style_confidence",
)
FEATURE_STATS_FIELDS = (
    "feature_id",
    "available_count",
    "missing_count",
    "zero_count",
    "median",
    "mad",
    "p05",
    "p25",
    "p75",
    "p95",
    "missing_ratio",
    "zero_ratio",
)
OUTLIER_FIELDS = (
    "document_id",
    "chunk_id",
    "source_order",
    "feature_id",
    "value",
    "median",
    "mad",
    "robust_z",
    "reason",
)


class CorpusAnalysisError(RuntimeError):
    pass


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _rounded(value: float | int | None):
    return None if value is None else round(value, 6)


def _feature_statistics(values: list[float], window_count: int) -> dict:
    available_count = len(values)
    missing_count = window_count - available_count
    zero_count = sum(value == 0 for value in values)
    median = statistics.median(values) if values else None
    deviations = [abs(value - median) for value in values] if median is not None else []
    mad = statistics.median(deviations) if deviations else None
    return {
        "available_count": available_count,
        "missing_count": missing_count,
        "zero_count": zero_count,
        "median": _rounded(median),
        "mad": _rounded(mad),
        "p05": _rounded(_percentile(values, 0.05)),
        "p25": _rounded(_percentile(values, 0.25)),
        "p75": _rounded(_percentile(values, 0.75)),
        "p95": _rounded(_percentile(values, 0.95)),
        "missing_ratio": _rounded(missing_count / window_count if window_count else 0.0),
        "zero_ratio": _rounded(zero_count / available_count if available_count else 0.0),
    }


def _stable_document_id(relative_path: str) -> str:
    return hashlib.sha256(relative_path.replace("\\", "/").encode("utf-8")).hexdigest()[:16]


def _default_output_dir(source_dir: Path) -> Path:
    safe_name = "".join(char if char.isalnum() or char in "-_" else "_" for char in source_dir.name) or "corpus"
    path_hash = hashlib.sha256(str(source_dir.resolve()).casefold().encode("utf-8")).hexdigest()[:8]
    return DEFAULT_REPORT_ROOT / f"{safe_name}-{path_hash}"


def _discover_documents(source_dir: Path) -> list[Path]:
    files = [
        path for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_CORPUS_EXTENSIONS
    ]
    return sorted(files, key=lambda path: path.relative_to(source_dir).as_posix().casefold())


def _write_json(path: Path, payload: dict):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_feature_stats(path: Path, stats_by_feature: dict):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FEATURE_STATS_FIELDS)
        writer.writeheader()
        for feature_id in STYLE_FEATURE_IDS:
            writer.writerow({"feature_id": feature_id, **stats_by_feature[feature_id]})


def _outlier_details(value: float, stats: dict) -> tuple[float | None, str | None]:
    median = stats["median"]
    mad = stats["mad"]
    if median is None:
        return None, None
    if mad and mad > 0:
        robust_z = abs(value - median) / (1.4826 * mad)
        return robust_z, "mad" if robust_z >= OUTLIER_ROBUST_Z_THRESHOLD else None
    p25 = stats["p25"]
    p75 = stats["p75"]
    if p25 is None or p75 is None:
        return None, None
    iqr = p75 - p25
    if iqr > 0:
        lower = p25 - OUTLIER_IQR_MULTIPLIER * iqr
        upper = p75 + OUTLIER_IQR_MULTIPLIER * iqr
        return None, "iqr" if value < lower or value > upper else None
    return None, "constant_baseline" if value != median else None


def _write_outliers(chunk_features_path: Path, outliers_path: Path, stats_by_feature: dict):
    with chunk_features_path.open("r", newline="", encoding="utf-8-sig") as source, outliers_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as target:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(target, fieldnames=OUTLIER_FIELDS)
        writer.writeheader()
        for row in reader:
            for feature_id in STYLE_FEATURE_IDS:
                raw = row.get(feature_id, "")
                if raw == "":
                    continue
                value = float(raw)
                robust_z, reason = _outlier_details(value, stats_by_feature[feature_id])
                if reason:
                    writer.writerow({
                        "document_id": row["document_id"],
                        "chunk_id": row["chunk_id"],
                        "source_order": row["source_order"],
                        "feature_id": feature_id,
                        "value": value,
                        "median": stats_by_feature[feature_id]["median"],
                        "mad": stats_by_feature[feature_id]["mad"],
                        "robust_z": _rounded(robust_z),
                        "reason": reason,
                    })


def analyze_corpus(source_dir: Path | str, output_dir: Path | str | None = None, include_text: bool = False) -> Path:
    source_dir = Path(source_dir).expanduser().resolve()
    if not source_dir.exists():
        raise CorpusAnalysisError(f"语料目录不存在：{source_dir}")
    if not source_dir.is_dir():
        raise CorpusAnalysisError(f"语料路径不是目录：{source_dir}")
    documents = _discover_documents(source_dir)
    if not documents:
        raise CorpusAnalysisError("目录中没有找到 TXT 或 DOCX 文件")

    output_dir = Path(output_dir).expanduser().resolve() if output_dir else _default_output_dir(source_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_paths = {
        name: output_dir / f".{name}.tmp"
        for name in ("summary.json", "feature_stats.csv", "chunk_features.csv", "outliers.csv")
    }
    final_paths = {name: output_dir / name for name in temp_paths}

    values_by_feature = {feature_id: [] for feature_id in STYLE_FEATURE_IDS}
    file_count = 0
    total_characters = 0
    total_valid_characters = 0
    chunk_count = 0
    window_count = 0
    chunk_fields = list(CHUNK_METADATA_FIELDS) + list(STYLE_FEATURE_IDS)
    if include_text:
        chunk_fields.append("content")

    try:
        with temp_paths["chunk_features.csv"].open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=chunk_fields)
            writer.writeheader()
            for file_index, path in enumerate(documents, start=1):
                relative_path = path.relative_to(source_dir).as_posix()
                print(f"[{file_index}/{len(documents)}] 分析 {relative_path}", flush=True)
                try:
                    text = extract_document_path(path)
                except (OSError, ValueError, OverflowError) as exc:
                    raise CorpusAnalysisError(f"读取失败 {relative_path}：{exc}") from exc
                chunks = split_corpus_text(text)
                if not chunks:
                    raise CorpusAnalysisError(f"无法切分文档：{relative_path}")
                document_id = _stable_document_id(relative_path)
                sources = [
                    {"article_key": document_id, "source_order": index, "content": content}
                    for index, content in enumerate(chunks)
                ]
                for analysis in iter_style_window_analyses(sources):
                    source = analysis.source
                    feature_values = analysis.features["features"]
                    row = {
                        "document_id": document_id,
                        "chunk_id": f"{document_id}:{source['source_order']:06d}",
                        "source_order": source["source_order"],
                        "current_valid_chars": count_valid_characters(source["content"]),
                        "window_start_order": analysis.start_order,
                        "window_end_order": analysis.end_order,
                        "window_valid_chars": analysis.valid_char_count,
                        "style_confidence": analysis.confidence["score"],
                    }
                    for feature_id in STYLE_FEATURE_IDS:
                        value = feature_values[feature_id]
                        row[feature_id] = "" if value is None else value
                        if value is not None:
                            values_by_feature[feature_id].append(float(value))
                    if include_text:
                        row["content"] = source["content"]
                    writer.writerow(row)
                    window_count += 1
                file_count += 1
                total_characters += len(text)
                total_valid_characters += count_valid_characters(text)
                chunk_count += len(chunks)

        stats_by_feature = {
            feature_id: _feature_statistics(values_by_feature[feature_id], window_count)
            for feature_id in STYLE_FEATURE_IDS
        }
        _write_feature_stats(temp_paths["feature_stats.csv"], stats_by_feature)
        _write_outliers(temp_paths["chunk_features.csv"], temp_paths["outliers.csv"], stats_by_feature)
        summary = {
            "schema_version": 1,
            "style_feature_version": STYLE_FEATURE_VERSION,
            "source_name": source_dir.name,
            "file_count": file_count,
            "total_characters": total_characters,
            "total_valid_characters": total_valid_characters,
            "chunk_count": chunk_count,
            "style_window_count": window_count,
            "include_text": include_text,
            "zero_ratio_denominator": "available_values",
            "features": stats_by_feature,
        }
        _write_json(temp_paths["summary.json"], summary)
        for name, temp_path in temp_paths.items():
            os.replace(temp_path, final_paths[name])
    except Exception:
        for temp_path in temp_paths.values():
            temp_path.unlink(missing_ok=True)
        raise

    print(f"完成：{file_count} 个文件，{chunk_count} 个 chunks，报告目录：{output_dir}", flush=True)
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线分析本地 TXT/DOCX 中文风格语料")
    parser.add_argument("corpus_dir", help="包含 TXT/DOCX 的本地语料目录")
    parser.add_argument("--output", help="报告输出目录；默认写入项目 style-analysis-reports/")
    parser.add_argument("--include-text", action="store_true", help="在 chunk_features.csv 中包含 current chunk 正文")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        analyze_corpus(args.corpus_dir, args.output, include_text=args.include_text)
    except CorpusAnalysisError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
