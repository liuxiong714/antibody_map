from celery import Celery, signals

from app.config import settings
from app.core.logging_config import setup_logging

_LOG_LEVEL = "DEBUG" if settings.APP_DEBUG else "INFO"


def _configure_worker_logging(**kwargs):
    """统一日志配置：连接 Celery 的 setup_logging 信号。

    Celery 会在 worker 启动时触发该信号；只要有 receiver 被调用且返回
    非空，Celery 就会跳过它自带的默认日志配置（否则会清空 root handler
    并换成 Celery 自己的 stderr handler，导致标准 logging 无法落盘）。
    """
    setup_logging(level=_LOG_LEVEL)
    return True


# 连接 setup_logging 信号，阻止 Celery 覆盖我们的 loguru 拦截
signals.setup_logging.connect(_configure_worker_logging)


def _reconfigure_logging_in_child(**kwargs):
    """在 fork 出的每个 ForkPoolWorker 子进程中重建 loguru sink。

    loguru 的 enqueue=True sink 依赖后台线程写入，fork 后线程不会复制到
    子进程，队列无人消费会导致日志丢失；因此需在子进程内重新初始化。
    """
    setup_logging(level=_LOG_LEVEL)


# 连接 worker_process_init 信号，确保 AI 提取子进程日志也能落盘
signals.worker_process_init.connect(_reconfigure_logging_in_child)

celery_app = Celery(
    "antibody_map",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.extract_task", "app.tasks.quality_task", "app.tasks.background_task"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 任务时间上限：防止 LLM 长任务（本地 Ollama 推理）异常悬挂占满 worker。
    # 软限制触发 SoftTimeLimitExceeded（任务可自行捕获清理）；硬限制到点强制终止。
    # 取值需明显大于单次 LLM 调用超时（LLM_REQUEST_TIMEOUT=600s），且覆盖本地模型整篇多步提取。
    task_soft_time_limit=3600,
    task_time_limit=4200,
)