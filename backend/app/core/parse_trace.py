"""提取解析路径追踪（Observability）。

用 ContextVar 在同一提取任务（通常同一线程）内累计这次实际跳过的解析引擎，
供 extract_task 结束时打一条汇总日志（如 "全文=pdf-inspector, 表格=pdfplumber"），
逐层定位哪个引擎产出文本/表格，降低排查成本。

用副本读写避免污染 context 默认值，跨并发任务安全。
"""
import contextvars
from typing import List

_parse_path: contextvars.ContextVar[List[str]] = contextvars.ContextVar(
    "parse_path_trace", default=[]
)


def reset() -> None:
    """清空当前任务的解析路径记录（任务开始/结束时调用）。"""
    _parse_path.set([])


def record(path: str) -> None:
    """记录本次实际走了某个解析路径（去重）。"""
    paths = list(_parse_path.get())
    if path not in paths:
        paths.append(path)
        _parse_path.set(paths)


def snapshot() -> List[str]:
    """返回并清空当前记录，供日志汇总后一次消费。"""
    paths = list(_parse_path.get())
    _parse_path.set([])
    return paths