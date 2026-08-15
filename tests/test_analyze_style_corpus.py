import csv
import json
import zipfile
from pathlib import Path

import pytest

from scripts.analyze_style_corpus import CorpusAnalysisError, analyze_corpus
from services.style_feature_service import STYLE_FEATURE_IDS


def write_docx(path: Path, paragraphs: list[str]):
    body = "".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document.encode("utf-8"))


def read_csv(path: Path):
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def test_analyze_corpus_writes_repeatable_reports_without_text_by_default(tmp_path, capsys):
    corpus_dir = tmp_path / "corpus"
    output_dir = tmp_path / "reports"
    corpus_dir.mkdir()
    (corpus_dir / "a.txt").write_text("\n\n".join(char * 500 for char in "甲乙丙"), encoding="utf-8")
    write_docx(corpus_dir / "b.docx", [char * 500 for char in "丁戊"])

    assert analyze_corpus(corpus_dir, output_dir) == output_dir.resolve()
    first_run = {path.name: path.read_bytes() for path in output_dir.iterdir()}
    assert analyze_corpus(corpus_dir, output_dir) == output_dir.resolve()
    second_run = {path.name: path.read_bytes() for path in output_dir.iterdir()}

    assert set(first_run) == {"summary.json", "feature_stats.csv", "chunk_features.csv", "outliers.csv"}
    assert first_run == second_run
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["file_count"] == 2
    assert summary["chunk_count"] == 5
    assert summary["style_window_count"] == 5
    assert summary["include_text"] is False
    assert summary["total_valid_characters"] == 2500
    assert set(summary["features"]) == set(STYLE_FEATURE_IDS)
    for stats in summary["features"].values():
        assert set(stats) == {
            "available_count", "missing_count", "zero_count", "median", "mad",
            "p05", "p25", "p75", "p95", "missing_ratio", "zero_ratio",
        }
        assert 0 <= stats["missing_ratio"] <= 1
        assert 0 <= stats["zero_ratio"] <= 1

    chunk_rows = read_csv(output_dir / "chunk_features.csv")
    assert len(chunk_rows) == 5
    assert "content" not in chunk_rows[0]
    assert all(row["document_id"] and row["chunk_id"] for row in chunk_rows)
    assert len(read_csv(output_dir / "feature_stats.csv")) == 44
    assert "[1/2]" in capsys.readouterr().out


def test_include_text_only_writes_current_chunk_not_window(tmp_path):
    corpus_dir = tmp_path / "corpus"
    output_dir = tmp_path / "reports"
    corpus_dir.mkdir()
    paragraphs = [char * 500 for char in "甲乙丙"]
    (corpus_dir / "article.txt").write_text("\n\n".join(paragraphs), encoding="utf-8")

    analyze_corpus(corpus_dir, output_dir, include_text=True)

    rows = read_csv(output_dir / "chunk_features.csv")
    assert [row["content"] for row in rows] == paragraphs
    assert all(len(row["content"]) == 500 for row in rows)
    assert all(int(row["window_valid_chars"]) >= len(row["content"]) for row in rows)


def test_missing_or_empty_corpus_directory_is_rejected(tmp_path):
    with pytest.raises(CorpusAnalysisError, match="语料目录不存在"):
        analyze_corpus(tmp_path / "missing", tmp_path / "reports")

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CorpusAnalysisError, match="没有找到 TXT 或 DOCX"):
        analyze_corpus(empty, tmp_path / "reports")
