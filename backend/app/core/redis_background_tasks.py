"""Redis-backed 后台长任务状态注册表。

用于「报告生成」与「知识图谱抽取」这类从 FastAPI HTTP 同步长协程改造为
Celery 后台异步任务后的运行状态登记。Worker 在后台执行任务时写入 Redis，
backend 的 /system/active-tasks 从同一 Redis 读取，从而跨进程共享状态。

Redis 同时是 Celery broker，worker 与 backend 天然共享同一实例，无需额外部署。

安全语义：
- Redis 不可用时 fail-open：读取失败返回空，写入失败静默忽略，仅影响
  「任务状态」页的展示，绝不影响报告/KG 的后台执行主流程。
- 所有 key 带 TTL，避免异常残留任务永远堆积。
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger("uvicorn")

_PREFIX = "bg_task"
# 进行中的任务（保持运行）TTL：须大于最长任务（本地模型报告/KG 可达数分钟）
_RUNNING_TTL = 3600
# 完成/失败任务保留时长，供前端读取一次完成状态后再清理
_FINISHED_TTL = 600


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _client() -> Any:
    """惰性创建 Redis 客户端。"""
    import redis.asyncio as aioredis

    return aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


async def start(task_type: str, task_id: str | None = None, **extra: Any) -> str | None:
    """登记一个后台任务，返回任务 id；Redis 故障时返回 ''（调用方视为未登记）。

    task_id 可选：外部（如 Celery 任务）可显式传入自己的任务 id，
    使 API 返回的 celery id 与 Redis 状态 id 一致，便于前端按 id 轮询。
    """
    tid = task_id or uuid.uuid4().hex
    entry: dict[str, Any] = {
        "type": task_type,
        "status": "running",
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    extra.pop("status", None)
    extra.pop("type", None)
    entry.update(extra)
    try:
        r = _client()
        await r.hset(f"{_PREFIX}:{tid}", mapping=entry)
        await r.expire(f"{_PREFIX}:{tid}", _RUNNING_TTL)
        await r.sadd(f"{_PREFIX}:{task_type}:ids", tid)
        await r.expire(f"{_PREFIX}:{task_type}:ids", _RUNNING_TTL)
        return tid
    except Exception as e:  # fail-open
        logger.warning(f"登记后台任务失败（忽略）: {e}")
        return ""


async def update(task_type: str, task_id: str, **extra: Any) -> None:
    """更新任务附加信息（如进度）。"""
    if not task_id:
        return
    try:
        r = _client()
        await r.hset(f"{_PREFIX}:{task_id}", mapping={**extra, "updated_at": _now_iso()})
        await r.expire(f"{_PREFIX}:{task_id}", _RUNNING_TTL)
    except Exception as e:  # fail-open
        logger.warning(f"更新后台任务状态失败（忽略）: {e}")


async def finish(task_type: str, task_id: str, status: str = "done", result: Any = None, error: str = "") -> None:
    """结束任务：写最终状态并记为完成，TTL 缩短供前端读取。"""
    if not task_id:
        return
    try:
        r = _client()
        extra: dict[str, Any] = {"status": status, "updated_at": _now_iso()}
        if result is not None:
            extra["result_json"] = json.dumps(result, ensure_ascii=False, default=str)
        if error:
            extra["error"] = error[:2000]
        await r.hset(f"{_PREFIX}:{task_id}", mapping=extra)
        await r.expire(f"{_PREFIX}:{task_id}", _FINISHED_TTL)
        await r.srem(f"{_PREFIX}:{task_type}:ids", task_id)
    except Exception as e:  # fail-open
        logger.warning(f"结束后台任务失败（忽略）: {e}")


async def active_task_ids(task_type: str) -> list[str]:
    """返回某类型仍在进行中的任务 id。"""
    try:
        r = _client()
        ids = await r.smembers(f"{_PREFIX}:{task_type}:ids")
        return sorted(ids)
    except Exception:  # fail-open
        return []


async def get_task(task_id: str) -> dict[str, Any] | None:
    """读单个任务状态；不存在/Redis 故障返回 None。"""
    if not task_id:
        return None
    try:
        r = _client()
        d = await r.hgetall(f"{_PREFIX}:{task_id}")
        if not d:
            return None
        result = d.pop("result_json", None)
        if result:
            try:
                d["result"] = json.loads(result)
            except Exception:
                d["result"] = None
        return dict(d)
    except Exception:  # fail-open
        return None


async def active_tasks(task_type: str) -> list[dict[str, Any]]:
    """返回某类型进行中任务的状态快照列表（供 /system/active-tasks 使用）。"""
    out: list[dict[str, Any]] = []
    for tid in await active_task_ids(task_type):
        t = await get_task(tid)
        if t:
            t["id"] = tid
            out.append(t)
    return out