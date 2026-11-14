"""一致性审查图装配。

形状：装载设定 → 抽取实体 → 四维并行（人设 / 时间线 / 伏笔 / 文风漂移）
→ 汇总 → 出报告。四个检查节点同时写 ``findings``，靠 State 上的 ``operator.add``
reducer 合并，这就是课件第二章扩展里讲的 Reducer。

一次性任务，不挂 checkpointer。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.consistency.nodes import (
    build_report_node,
    check_character_node,
    check_foreshadow_node,
    check_style_drift_node,
    check_timeline_node,
    extract_entities_node,
    load_setting_node,
    synthesize_node,
)
from backend.agents.consistency.state import ConsistencyState


def build_consistency_graph():
    builder = StateGraph(ConsistencyState)

    builder.add_node('load_setting', load_setting_node)
    builder.add_node('extract_entities', extract_entities_node)
    builder.add_node('check_character', check_character_node)
    builder.add_node('check_timeline', check_timeline_node)
    builder.add_node('check_foreshadow', check_foreshadow_node)
    builder.add_node('check_style_drift', check_style_drift_node)
    builder.add_node('synthesize', synthesize_node)
    builder.add_node('build_report', build_report_node)

    builder.add_edge(START, 'load_setting')
    builder.add_edge('load_setting', 'extract_entities')

    # 四维并行：同一层的多个节点会同时执行
    for check in ('check_character', 'check_timeline', 'check_foreshadow', 'check_style_drift'):
        builder.add_edge('extract_entities', check)
        builder.add_edge(check, 'synthesize')

    builder.add_edge('synthesize', 'build_report')
    builder.add_edge('build_report', END)

    return builder.compile()
