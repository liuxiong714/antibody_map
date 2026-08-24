"""Prometheus 业务指标定义与后台采集循环。

分工说明：
- HTTP 请求量 / 延迟直方图（http_requests_total、http_request_duration_*_seconds）
  由 prometheus-fastapi-instrumentator 在 main.py 中自动收集；
- 本模块负责应用自定义业务指标，并统一暴露给 prometheus_client
  （注册到默认 REGISTRY，/metrics 端点会一并输出）。

自定义指标：
- llm_extraction_total：LLM 提取次数（按 model / status）
- llm_tokens_total：Token 消耗数（按 model / kind[prompt|completion]）
- llm_cost_usd_total：LLM 累计费用（USD，按 model）
- extraction_duration_seconds：文献提取耗时直方图（按 model）
- celery_task_queue_depth：Celery 队列积压（Gauge，按 queue）
- data_point_count：数据点数量（Gauge，按 review_status / disease）

安全设计：
- 所有指标对象惰性初始化，包裹在 try/except 中；若 prometheus_client 未安装，
  各记录函数静默降级为 no-op，绝不影响既有功能与性能。
- 指标写入均为极轻量操作（increment / set），不涉及 IO，对请求性能影响可忽略。
"""

import asyncio
import logging
from typing import Optional

from sqlalchemy import select, func

from app.config import settings
from app.models.base import async_session
from app.models.data_point import DataPoint

logger = logging.getLogger("uvicorn")

# 指标元素存根：依赖不可用时为 None，所有操作 no-op
_METRICS: dict = {}


def _init_metrics() -> dict:
    """惰性创建并注册所有业务指标（幂等，重复注册由客户端忽略）。"""
    if _METRICS:
        return _METRICS
    from prometheus_client import Counter, Histogram, Gauge

    metrics = {
        # HTTP 层异常计数（未处理异常→500），与 instrumentator 的请求量互补
        "http_exceptions_total": Counter(
            "http_exceptions_total",
            "Total number of unhandled HTTP exceptions.",
            ["status_code"],
        ),
        "llm_extraction_total": Counter(
            "llm_extraction_total",
            "Total number of LLM extractions by model and status.",
            ["model", "status"],
        ),
        "llm_tokens_total": Counter(
            "llm_tokens_total",
            "Total tokens consumed by LLM, by model and kind.",
            ["model", "kind"],
        ),
        "llm_cost_usd_total": Counter(
            "llm_cost_usd_total",
            "Estimated cumulative LLM cost in USD by model.",
            ["model"],
        ),
        "extraction_duration_seconds": Histogram(
            "extraction_duration_seconds",
            "Duration of literature extraction in seconds.",
            ["model"],
            buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, float("inf")),
        ),
        "celery_task_queue_depth": __import__("prometheus_client").Gauge(
            "celery_task_queue_depth",
            "Number of pending tasks in Celery queues.",
            ["queue"],
        ),
        "data_point_count": Gauge(
            "data_point_count",
            "Number of data points by review status and disease.",
            ["review_status", "disease"],
        ),
        "orphan_cleanup_orphan_total": Gauge(
            "orphan_cleanup_orphan_total",
            "Number of orphan files/objects detected by cleanup scan, by storage.",
            ["storage"],
        ),
    }
    _METRICS.update(metrics)
    return _METRICS


def _metric(name: str):
    """取指定指标对象；依赖缺失时返回 None。"""
    try:
        return _init_metrics().get(name)
    except Exception:  # pragma: no cover - 依赖缺失兜底
        return None


# ================= 记录函数（供业务代码调用）=================

def record_http_exception(status_code: int = 500) -> None:
    """记录一次未处理的 HTTP 异常（用于 5xx 计数的补充）。"""
    m = _metric("http_exceptions_total")
    if m is not None:
        try:
            m.labels(status_code=str(status_code)).inc()
        except Exception:  # 指标记录失败不阻断请求
            pass


def record_llm_extraction(model: str, status: str) -> None:
    """记录一次 LLM 提取的结局（status ∈ success / error）。"""
    m = _metric("llm_extraction_total")
    if m is not None:
        try:
            m.labels(model=model, status=status).inc()
        except Exception:
            pass


def record_llm_tokens(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """记录一次 LLM 调用的 token 消耗（不包含费用，费用见 record_llm_cost）。"""
    m = _metric("llm_tokens_total")
    if m is not None:
        try:
            m.labels(model=model, kind="prompt").inc(prompt_tokens)
            m.labels(model=model, kind="completion").inc(completion_tokens)
        except Exception:
            pass


def record_llm_cost(model: str, cost_usd: float) -> None:
    """记录一次 LLM 调用的估算费用（USD）。"""
    m = _metric("llm_cost_usd_total")
    if m is not None:
        try:
            m.labels(model=model).inc(cost_usd)
        except Exception:
            pass


def record_llm_completion(model: str, status: str, usage_summary: Optional[dict] = None) -> None:
    """提取完成时一次性记录 LLM 指标（结局计数 + token + 费用）。

    供 extract_task 在提取完成后调用：status ∈ success / error。
    - usage_summary 结构见 usage_tracker.get_usage_summary()；
    - token 按 models 子表逐模型累加，费用按提取器汇总值计入主模型标签（近似）。
    """
    record_llm_extraction(model, status)
    if not usage_summary:
        return
    models = usage_summary.get("models") or {}
    if models:
        for m_name, m in models.items():
            record_llm_tokens(m_name, m.get("prompt_tokens", 0), m.get("completion_tokens", 0))
    else:
        record_llm_tokens(
            model,
            usage_summary.get("total_prompt_tokens", 0),
            usage_summary.get("total_completion_tokens", 0),
        )
    record_llm_cost(model, usage_summary.get("estimated_cost_usd", 0))


def record_llm_usage(model: str, prompt_tokens: int, completion_tokens: int, cost_usd: float) -> None:
    """一次性记录 token 与费用，供 usage_tracker 在单点调用。"""
    record_llm_tokens(model, prompt_tokens, completion_tokens)
    record_llm_cost(model, cost_usd)


def observe_extraction_duration(model: str, seconds: float) -> None:
    """记录一次提取耗时。"""
    m = _metric("extraction_duration_seconds")
    if m is not None:
        try:
            m.labels(model=model).observe(seconds)
        except Exception:
            pass


def record_orphan_scan(storage: str, count: int) -> None:
    """记录一次孤儿扫描结果（storage ∈ local / minio），用于 /metrics 观测。"""
    m = _metric("orphan_cleanup_orphan_total")
    if m is not None:
        try:
            m.labels(storage=storage).set(count)
        except Exception:
            pass


# ================= /metrics 访问控制 =================

def metrics_accessible(request) -> bool:
    """判断当前请求是否有权访问 /metrics。

    规则（满足任一即可）：
    - 功能关闭（METRICS_ENABLED=False）：不允许
    - 开发环境（APP_ENV == development）：允许
    - 客户端 IP 命中 METRICS_ALLOW_IPS（逗号分隔）：允许
    """
    if not getattr(settings, "METRICS_ENABLED", True):
        return False
    env = getattr(settings, "APP_ENV", "development")
    if env == "development":
        return True
    allow_ips_raw = getattr(settings, "METRICS_ALLOW_IPS", "")
    if not allow_ips_raw:
        return False
    client_host = request.client.host if request.client else ""
    allow_set = {ip.strip() for ip in allow_ips_raw.split(",") if ip.strip()}
    return client_host in allow_set


# ================= 后台指标采集循环 =================

async def _update_data_point_gauges() -> None:
    """按 (review_status, disease) 分组刷新数据点数（Gauge.set）。"""
    m = _metric("data_point_count")
    if m is None:
        return
    async with async_session() as db:
        result = await db.execute(
            select(
                DataPoint.review_status,
                DataPoint.disease,
                func.count(DataPoint.id),
            ).group_by(DataPoint.review_status, DataPoint.disease)
        )
        for review_status, disease, count in result.all():
            m.labels(
                review_status=review_status or "unknown",
                disease=disease or "unknown",
            ).set(count)


async def _update_celery_queue_depth() -> None:
    """读取各 Celery 队列的 pending 任务数（Redis LLEN）。"""
    m = _metric("celery_task_queue_depth")
    if m is None:
        return
    from redis.asyncio import Redis

    client = Redis.from_url(
        settings.CELERY_BROKER_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        # Celery 默认队列名为 "celery"；如需追踪更多队列可在此扩展
        queues = getattr(settings, "CELERY_QUEUES", "") or "celery"
        for q in [q.strip() for q in queues.split(",") if q.strip()]:
            depth = await client.llen(q)
            m.labels(queue=q).set(int(depth or 0))
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


async def metrics_loop(interval: int = 60) -> None:
    """后台循环：按固定间隔刷新 Gauge 指标，单个失败不影响整体。"""
    await asyncio.sleep(20)  # 启动留出表结构就绪时间
    while True:
        try:
            await _update_data_point_gauges()
        except Exception as e:
            logger.warning(f"[metrics] 刷新 data_point_count 失败: {e}")
        try:
            await _update_celery_queue_depth()
        except Exception as e:
            logger.warning(f"[metrics] 刷新 celery_task_queue_depth 失败: {e}")
        await asyncio.sleep(interval)


def start_metrics_background_tasks(interval: int = 60) -> list:
    """启动指标后台采集任务，返回任务列表（由 lifespan 管理生命周期）。"""
    return [asyncio.create_task(metrics_loop(interval))]