"""图内事件出口。

节点在执行过程中需要往前端推 token / 状态事件，但节点函数本身不应该知道
SSE 的存在。这里用一个 ContextVar 装"当前请求的写出口"：

- 流式请求在任务里用 ``use_writer`` 绑定一个把事件塞进队列的函数；
- 非流式请求不绑定，``emit`` 直接丢弃。

这样同一份节点代码既能流式跑，也能同步跑，不需要两套实现。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator

Writer = Callable[[dict[str, Any]], None]

_writer: ContextVar[Writer | None] = ContextVar('writing_event_writer', default=None)


def emit(event: dict[str, Any]) -> None:
    writer = _writer.get()
    if writer is not None:
        writer(event)


@contextmanager
def use_writer(writer: Writer) -> Iterator[None]:
    token = _writer.set(writer)
    try:
        yield
    finally:
        _writer.reset(token)
