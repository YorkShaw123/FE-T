"""桌面端昂贵模型操作的进程内并发保护。"""

from threading import Lock

from services.errors import GenerationError


_MODEL_OPERATION_LOCK = Lock()


def acquire_model_operation():
    """同一 Sidecar 同时只允许一个计费/高资源模型任务。"""
    if not _MODEL_OPERATION_LOCK.acquire(blocking=False):
        raise GenerationError('已有模型任务正在运行，请等待完成或停止后再试')


def release_model_operation():
    if _MODEL_OPERATION_LOCK.locked():
        _MODEL_OPERATION_LOCK.release()
