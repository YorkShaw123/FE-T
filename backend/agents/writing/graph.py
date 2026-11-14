"""写作图装配。

八个节点、四个条件边，形状与 03-Agent图设计 第 2.3 节一致。
写作是一次性任务，不挂 checkpointer（与课件"简历 Agent 不传 MemorySaver"同理）。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.writing.nodes import (
    assemble_prompt_node,
    budget_check_node,
    deai_rewrite_node,
    draft_node,
    finalize_node,
    persist_node,
    style_retrieve_node,
    style_rewrite_node,
)
from backend.agents.writing.state import WritingState


def route_after_budget(state: WritingState) -> str:
    """预算超限直接中止，不浪费一次模型调用。"""
    return 'abort' if state.get('errors') else 'draft'


def route_after_draft(state: WritingState) -> str:
    if state.get('deai_enabled') and (state.get('story_content') or '').strip():
        return 'deai_rewrite'
    if state.get('style_reference_enabled'):
        return 'style_retrieve'
    return 'finalize'


def route_after_deai(state: WritingState) -> str:
    if state.get('style_reference_enabled'):
        return 'style_retrieve'
    return 'finalize'


def route_after_retrieve(state: WritingState) -> str:
    return 'style_rewrite' if state.get('reference_excerpts') else 'finalize'


async def abort_node(state: WritingState) -> dict:
    """预算超限的收尾节点：不落库，保留错误信息给调用方。"""
    return {'final_content': ''}


def build_writing_graph():
    builder = StateGraph(WritingState)

    builder.add_node('assemble_prompt', assemble_prompt_node)
    builder.add_node('budget_check', budget_check_node)
    builder.add_node('draft', draft_node)
    builder.add_node('deai_rewrite', deai_rewrite_node)
    builder.add_node('style_retrieve', style_retrieve_node)
    builder.add_node('style_rewrite', style_rewrite_node)
    builder.add_node('finalize', finalize_node)
    builder.add_node('persist', persist_node)
    builder.add_node('abort', abort_node)

    builder.add_edge(START, 'assemble_prompt')
    builder.add_edge('assemble_prompt', 'budget_check')
    builder.add_conditional_edges(
        'budget_check',
        route_after_budget,
        {'draft': 'draft', 'abort': 'abort'},
    )
    builder.add_conditional_edges(
        'draft',
        route_after_draft,
        {
            'deai_rewrite': 'deai_rewrite',
            'style_retrieve': 'style_retrieve',
            'finalize': 'finalize',
        },
    )
    builder.add_conditional_edges(
        'deai_rewrite',
        route_after_deai,
        {'style_retrieve': 'style_retrieve', 'finalize': 'finalize'},
    )
    builder.add_conditional_edges(
        'style_retrieve',
        route_after_retrieve,
        {'style_rewrite': 'style_rewrite', 'finalize': 'finalize'},
    )
    builder.add_edge('style_rewrite', 'finalize')
    builder.add_edge('finalize', 'persist')
    builder.add_edge('persist', END)
    builder.add_edge('abort', END)

    return builder.compile()
