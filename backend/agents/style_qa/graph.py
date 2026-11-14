"""风格问答图装配。

四分支结构见 03-Agent图设计 第 3.2 节；比原设计少一个独立 rerank 节点——
``LocalKB.search`` 内部已经做了打分与 MMR 重排，再拆一个空节点只会让图看起来更复杂。
置信度判定放在 ``retrieve`` 的返回里，条件边据此分流。

挂 checkpointer：风格问答是多轮对话，需要上下文。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from backend.agents.style_qa.nodes import (
    classify_query_node,
    enqueue_pending_node,
    generate_direct_node,
    generate_general_node,
    generate_rag_node,
    hyde_generate_node,
    multi_query_rewrite_node,
    retrieve_node,
    save_memory_node,
)
from backend.agents.style_qa.state import StyleQAState

_saver = InMemorySaver()


def route_by_query_type(state: StyleQAState) -> str:
    query_type = (state.get('query_type') or 'PRECISE').upper()
    if query_type == 'GENERAL':
        return 'generate_general'
    if query_type == 'VAGUE':
        return 'hyde_generate'
    if query_type == 'BROAD':
        return 'multi_query_rewrite'
    return 'retrieve'


def route_by_confidence(state: StyleQAState) -> str:
    return 'generate_rag' if state.get('is_high_confidence') else 'generate_direct'


def build_style_qa_graph():
    builder = StateGraph(StyleQAState)

    builder.add_node('classify_query', classify_query_node)
    builder.add_node('hyde_generate', hyde_generate_node)
    builder.add_node('multi_query_rewrite', multi_query_rewrite_node)
    builder.add_node('retrieve', retrieve_node)
    builder.add_node('generate_rag', generate_rag_node)
    builder.add_node('generate_direct', generate_direct_node)
    builder.add_node('generate_general', generate_general_node)
    builder.add_node('enqueue_pending', enqueue_pending_node)
    builder.add_node('save_memory', save_memory_node)

    builder.add_edge(START, 'classify_query')
    builder.add_conditional_edges(
        'classify_query',
        route_by_query_type,
        {
            'generate_general': 'generate_general',
            'hyde_generate': 'hyde_generate',
            'multi_query_rewrite': 'multi_query_rewrite',
            'retrieve': 'retrieve',
        },
    )
    builder.add_edge('hyde_generate', 'retrieve')
    builder.add_edge('multi_query_rewrite', 'retrieve')

    builder.add_conditional_edges(
        'retrieve',
        route_by_confidence,
        {'generate_rag': 'generate_rag', 'generate_direct': 'generate_direct'},
    )
    builder.add_edge('generate_rag', 'save_memory')
    builder.add_edge('generate_direct', 'enqueue_pending')
    builder.add_edge('enqueue_pending', 'save_memory')
    builder.add_edge('generate_general', 'save_memory')
    builder.add_edge('save_memory', END)

    return builder.compile(checkpointer=_saver)
