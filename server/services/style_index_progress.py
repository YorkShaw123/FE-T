"""进程内 Style Corpus 向量化进度；不持久化，也不参与索引算法。"""
from __future__ import annotations

import time
from threading import Lock


_PROGRESS = {}
_LOCK = Lock()


def start_index_progress(corpus_id, total):
    now = time.monotonic()
    state = {
        'corpus_id': int(corpus_id),
        'status': 'running',
        'completed': 0,
        'total': max(int(total), 0),
        'percent': 0.0,
        'elapsed_seconds': 0.0,
        'estimated_remaining_seconds': None,
        'message': '正在加载本地向量模型…',
        '_started_at': now,
    }
    with _LOCK:
        _PROGRESS[int(corpus_id)] = state
    return public_index_progress(state)


def update_index_progress(corpus_id, completed, total):
    with _LOCK:
        state = _PROGRESS.get(int(corpus_id))
        if state is None:
            return None
        completed = min(max(int(completed), 0), max(int(total), 0))
        elapsed = max(time.monotonic() - state['_started_at'], 0.0)
        percent = (completed / total * 100.0) if total else 100.0
        remaining = None
        if completed > 0 and completed < total:
            remaining = elapsed / completed * (total - completed)
        state.update({
            'status': 'running',
            'completed': completed,
            'total': int(total),
            'percent': percent,
            'elapsed_seconds': elapsed,
            'estimated_remaining_seconds': remaining,
            'message': f'正在向量化：{completed} / {total} 个片段',
        })
        return public_index_progress(state)


def finish_index_progress(corpus_id, total):
    with _LOCK:
        state = _PROGRESS.get(int(corpus_id))
        if state is None:
            return None
        elapsed = max(time.monotonic() - state['_started_at'], 0.0)
        state.update({
            'status': 'completed',
            'completed': int(total),
            'total': int(total),
            'percent': 100.0,
            'elapsed_seconds': elapsed,
            'estimated_remaining_seconds': 0.0,
            'message': f'向量化完成：{total} 个片段',
        })
        return public_index_progress(state)


def fail_index_progress(corpus_id, message):
    with _LOCK:
        state = _PROGRESS.get(int(corpus_id))
        if state is None:
            state = {
                'corpus_id': int(corpus_id),
                'status': 'running',
                'completed': 0,
                'total': 0,
                'percent': 0.0,
                '_started_at': time.monotonic(),
            }
            _PROGRESS[int(corpus_id)] = state
        state.update({
            'status': 'failed',
            'elapsed_seconds': max(time.monotonic() - state['_started_at'], 0.0),
            'estimated_remaining_seconds': None,
            'message': str(message),
        })
        return public_index_progress(state)


def get_index_progress(corpus_id):
    with _LOCK:
        state = _PROGRESS.get(int(corpus_id))
        return public_index_progress(state) if state else None


def public_index_progress(state):
    return {
        key: (round(value, 1) if isinstance(value, float) else value)
        for key, value in state.items()
        if not key.startswith('_')
    }


def clear_index_progress_for_tests():
    with _LOCK:
        _PROGRESS.clear()
