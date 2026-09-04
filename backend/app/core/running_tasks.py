"""进程内"当前运行中的长任务"注册表。

用于系统设置「任务状态」页聚合展示后端当前正在执行的任务（如报告生成、知识图谱抽取）。

背景：
- 文献AI信息提取由 Celery worker 在独立进程后台执行，其运行状态从数据库 literature 表的
  extraction_status（queued/processing）读取，跨进程可靠，不走本注册表。
- 报告生成与知识图谱抽取是 FastAPI 进程内的长协程，运行期间没有持久化状态可查，
  因此在请求进入时登记、结束（含异常）时移除本注册表，供 /system/active-tasks 聚合查询。

线程安全：FastAPI 的 async 协程跑在事件循环单线程上，但为兼容同步调用/多线程场景，
仍用线程锁保护关键区。
"""

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

_lock = threading.Lock()
# {task_type: [ {id, started_at, updated_at, **extra}, ... ]}
_registry: dict[str, list[dict[str, Any]]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start(task_type: str, **extra: Any) -> str:
    """登记一个运行中任务，返回任务 id。"""
    task_id = uuid.uuid4().hex
    entry: dict[str, Any] = {"id": task_id, "started_at": _now_iso(), "updated_at": _now_iso()}
    entry.update(extra)
    with _lock:
        _registry.setdefault(task_type, []).append(entry)
    return task_id


def update(task_type: str, task_id: str, **extra: Any) -> None:
    """更新已登记任务的附加信息（如已处理篇数），不存在则忽略。"""
    with _lock:
        for e in _registry.get(task_type, []):
            if e["id"] == task_id:
                e.update(extra)
                e["updated_at"] = _now_iso()
                return


def finish(task_type: str, task_id: str) -> None:
    """移除一个任务（无论成败，均由 finally 调用）。"""
    with _lock:
        arr = _registry.get(task_type)
        if arr is None:
            return
        _registry[task_type] = [e for e in arr if e["id"] != task_id]
        if not _registry[task_type]:
            _registry.pop(task_type, None)


def active(task_type: str | None = None) -> list[dict[str, Any]]:
    """返回当前登记的任务列表（浅拷贝的快照）。task_type 为空则返回全部。"""
    with _lock:
        if task_type is not None:
            return list(_registry.get(task_type, []))
        out: list[dict[str, Any]] = []
        for arr in _registry.values():
            out.extend(arr)
        return out