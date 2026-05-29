"""
日志工具模块
============

提供统一的日志配置，支持：
- 控制台输出（带颜色）
- 文件输出（按天轮转，保留7天）
- 多种日志级别
- 与现有代码无缝集成
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


# 日志目录
LOG_DIR = Path(__file__).parent.parent.parent / 'logs'
LOG_DIR.mkdir(exist_ok=True)


class ColoredFormatter(logging.Formatter):
    """带颜色的控制台格式化器"""

    # ANSI颜色码
    COLORS = {
        'DEBUG': '\033[36m',     # 青色
        'INFO': '\033[32m',      # 绿色
        'WARNING': '\033[33m',   # 黄色
        'ERROR': '\033[31m',     # 红色
        'CRITICAL': '\033[35m',  # 紫色
    }
    RESET = '\033[0m'

    def format(self, record):
        # 添加颜色
        if record.levelname in self.COLORS:
            record.levelname = (
                f"{self.COLORS[record.levelname]}"
                f"{record.levelname}"
                f"{self.RESET}"
            )
        return super().format(record)


def setup_logger(
    name: str = None,
    level: int = logging.INFO,
    log_file: str = None,
    console: bool = True,
    file_level: int = logging.DEBUG,
) -> logging.Logger:
    """
    配置并返回日志记录器

    Parameters
    ----------
    name : str, optional
        日志记录器名称，默认为 root logger
    level : int
        控制台日志级别，默认为 INFO
    log_file : str, optional
        日志文件名，默认格式: aquant_YYYYMMDD.log
    console : bool
        是否输出到控制台，默认为 True
    file_level : int
        文件日志级别，默认为 DEBUG

    Returns
    -------
    logging.Logger
        配置好的日志记录器

    Example
    -------
    >>> from src.utils import setup_logger
    >>> logger = setup_logger('myapp', level=logging.DEBUG)
    >>> logger.info('Hello')
    """
    logger = logging.getLogger(name or 'aquant')

    # 避免重复添加handler
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    # 日志格式
    file_formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = ColoredFormatter(
        fmt='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )

    # 控制台输出
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # 文件输出（按天轮转，保留7天）
    if log_file is None:
        log_file = f'aquant_{datetime.now().strftime("%Y%m%d")}.log'

    file_path = LOG_DIR / log_file
    file_handler = TimedRotatingFileHandler(
        filename=file_path,
        when='midnight',           # 每天午夜轮转
        interval=1,
        backupCount=30,           # 保留30天
        encoding='utf-8',
        atTime=datetime.strptime('00:00', '%H:%M').time()
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    获取已配置的日志记录器

    如果尚未配置，则使用默认配置

    Parameters
    ----------
    name : str, optional
        日志记录器名称

    Returns
    -------
    logging.Logger
    """
    logger = logging.getLogger(name or 'aquant')
    if not logger.handlers:
        # 未配置过，使用默认配置
        return setup_logger(name)
    return logger


def get_log_files() -> list:
    """
    获取所有日志文件列表

    Returns
    -------
    list
        日志文件路径列表，按修改时间排序
    """
    if not LOG_DIR.exists():
        return []
    return sorted(LOG_DIR.glob('*.log'), key=lambda p: p.stat().st_mtime, reverse=True)


def cleanup_old_logs(days: int = 7) -> int:
    """
    清理超过指定天数的日志文件

    Parameters
    ----------
    days : int
        保留天数，默认为30天

    Returns
    -------
    int
        删除的文件数量
    """
    from datetime import timedelta

    if not LOG_DIR.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=days)
    count = 0

    for log_file in LOG_DIR.glob('*.log'):
        if datetime.fromtimestamp(log_file.stat().st_mtime) < cutoff:
            log_file.unlink()
            count += 1

    return count
