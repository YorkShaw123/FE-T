"""一致性审查图的状态。

``findings`` 用 ``operator.add`` 作为 reducer：四个检查节点并行执行、各自往
同一个列表里追加，LangGraph 会按 reducer 合并，而不是报"同一状态键被多处写入"。
这正是课件第二章扩展里讲的 Reducer 用法。
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

SEVERITY_ORDER = {'blocker': 0, 'major': 1, 'minor': 2}


def merge_findings(
    existing: list[dict[str, Any]] | None,
    update: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """自定义 Reducer：四个并行分支各写一份，这里按"问题"去重并按严重度排序。

    不用 ``operator.add`` 是因为并行分支可能报同一条问题（例如人物矛盾同时被
    人设维度和伏笔维度发现），直接拼列表会重复。
    """
    merged = [*(existing or []), *(update or [])]
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in merged:
        key = (
            str(item.get('code', '')),
            str(item.get('problem', '')),
            str(item.get('quote', '')),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda item: SEVERITY_ORDER.get(item.get('severity', 'minor'), 9))
    return unique


class ConsistencyState(TypedDict, total=False):
    # ── 入参 ─────────────────────────────────────────────
    user_id: str
    session_id: str
    chapter_text: str
    template_ids: list[int]
    setting_snapshot: dict[str, list[dict[str, Any]]]
    history_digest: str
    api_key: str
    provider: str | None
    model: str | None

    # ── 过程 ─────────────────────────────────────────────
    entities: dict[str, list[str]]
    findings: Annotated[list[dict[str, Any]], merge_findings]
    severity_count: dict[str, int]
    errors: list[str]

    # ── 产出 ─────────────────────────────────────────────
    report: str
