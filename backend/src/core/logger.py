"""全局日志配置 - 基于 loguru，支持文件轮转 + 控制台彩色输出"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

from .config import get_settings


def setup_logger() -> None:
    """初始化日志（在应用启动时调用一次即可）"""
    settings = get_settings()

    # ---------- 1. 移除 loguru 默认处理器 ----------
    logger.remove()

    # ---------- 2. 控制台输出（彩色，Windows 兼容） ----------
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=settings.DEBUG,
        diagnose=settings.DEBUG,
        enqueue=True,
    )

    # ---------- 3. 文件输出（按大小轮转）----------
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"{settings.APP_NAME.lower()}.log"
    logger.add(
        log_file,
        level=settings.LOG_LEVEL,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}"
        ),
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        compression="zip",
        encoding="utf-8",
        backtrace=settings.DEBUG,
        diagnose=False,
        enqueue=True,
    )

    # ---------- 4. Error 级别单独文件 ----------
    error_file = log_dir / "error.log"
    logger.add(
        error_file,
        level="ERROR",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}\n{exception}"
        ),
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        compression="zip",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )

    logger.info(f"Logger initialized | level={settings.LOG_LEVEL} | env={settings.APP_ENV}")


# 确保标准 logging 也被 loguru 拦截（可选，用于第三方库日志）
def intercept_standard_logging() -> None:
    """将标准 logging 的输出重定向到 loguru"""
    import logging

    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
