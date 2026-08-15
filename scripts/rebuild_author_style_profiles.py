"""Rebuild local Author Style Profiles and upgrade old chunk Feature versions."""

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app import create_app  # noqa: E402
from database.models import StyleCorpus  # noqa: E402
from services.author_style_profile_service import (  # noqa: E402
    AuthorStyleProfileError,
    build_author_style_profile,
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="本地升级 Style Feature 并重建 Author/Scene Profile",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--corpus-id", type=int, help="只重建指定 corpus ID")
    target.add_argument("--all", action="store_true", help="重建全部 corpus")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    app = create_app("production")
    with app.app_context():
        if args.all:
            corpus_ids = [item.id for item in StyleCorpus.query.order_by(StyleCorpus.id).all()]
        else:
            corpus_ids = [args.corpus_id]
        if not corpus_ids:
            print("没有可重建的 Style Corpus。")
            return 0
        failed = 0
        for index, corpus_id in enumerate(corpus_ids, start=1):
            try:
                profile = build_author_style_profile(corpus_id)
            except AuthorStyleProfileError as exc:
                failed += 1
                print(f"[{index}/{len(corpus_ids)}] corpus {corpus_id}: 失败 - {exc}")
                continue
            print(
                f"[{index}/{len(corpus_ids)}] corpus {corpus_id}: "
                f"已重建 {profile.sample_count} 个窗口，Feature v{profile.feature_version}"
            )
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
