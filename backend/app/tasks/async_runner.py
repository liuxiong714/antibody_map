"""Celery worker 内运行协程的辅助函数。

背景：Celery 任务通常用 asyncio.run() 运行异步代码，但 asyncio.run() 每次调用
都会创建并销毁一个新的事件循环。而项目中的 asyncpg 数据库连接池
（app.models.base 的模块级单例 engine）会在首次使用它的那个事件循环上建立连接；
后续任务用新的事件循环复用这些连接时，会报 "Future attached to a different loop"
错误，导致任务失败。

解决方案：在 worker 进程内维护一个常驻的后台事件循环，所有异步任务都提交到该
循环执行，从而保证连接池始终绑定在同一个事件循环上。
"""
import asyncio
import threading
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

_loop: "asyncio.AbstractEventLoop | None" = None
_loop_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            new_loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=new_loop.run_forever,
                name="worker-async-loop",
                daemon=True,
            )
            thread.start()
            _loop = new_loop
        return _loop


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """在 worker 的常驻事件循环上同步等待协程完成，返回结果。"""
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()
