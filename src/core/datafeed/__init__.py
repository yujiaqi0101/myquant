"""
src/core/datafeed/__init__.py
=============================

数据流抽象层包初始化模块。

统一导出 DataFeed 抽象基类及其两个实现：
    - HistoricalDataFeed：回测专用，从 SQLite 读取历史K线，按交易日逐根推送
    - LiveDataFeed：模拟盘/实盘专用，多线程异步行情，内存缓存最近N根K线

设计文档第 4.1 节：DataFeed 是事件驱动内核的行情入口，由 EventEngine 在
启动时调用 start()，按交易日/实时推送 BarEvent 到事件总线。

用法：
    from src.core.datafeed import DataFeed, HistoricalDataFeed, LiveDataFeed
"""

from src.core.datafeed.base import DataFeed
from src.core.datafeed.historical import HistoricalDataFeed
from src.core.datafeed.live import LiveDataFeed

__all__ = ["DataFeed", "HistoricalDataFeed", "LiveDataFeed"]
