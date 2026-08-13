"""统一日志配置：基于 loguru 的结构化日志。

- 拦截 Python 标准 logging 的所有记录，统一转交给 loguru 处理
- 同时输出到控制台和滚动文件（按大小轮转）
- 对现有使用 logging.getLogger() 的模块保持完全向后兼容
"""
import logging
import sys
from pathlib import Path

from loguru import logger

# 日志目录（后端项目根目录下 logs/）
LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


class _InterceptHandler(logging.Handler):
    """将标准 logging 记录转发到 loguru 的处理器。"""

    def emit(self, record: logging.LogRecord) -> None:
        # 获取对应的 loguru 方法
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 提取调用方帧信息，保证日志定位到原始调用位置
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """初始化统一日志配置。可在应用启动时调用一次。"""
    log_dir = log_dir or LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    # 清空默认处理器，避免重复输出
    logger.remove()

    # 控制台输出：带颜色，便于开发调试
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # 文件输出：按大小轮转（50MB），保留最近 7 天
    logger.add(
        str(log_dir / "app_{time:YYYY-MM-DD}.log"),
        level=level,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} - {message}"
        ),
        rotation="50 MB",
        retention="7 days",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
    )

    # 拦截标准 logging，统一转发给 loguru
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for _name in logging.root.manager.loggerDict:
        existing = logging.getLogger(_name)
        existing.handlers = [_InterceptHandler()]
        existing.propagate = False


# 提供便捷别名，兼容现有 `from loguru import logger` 用法
__all__ = ["logger", "setup_logging"]