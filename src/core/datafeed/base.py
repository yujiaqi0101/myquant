"""
src/core/datafeed/base.py
=========================

DataFeed 数据流抽象基类模块。

DataFeed 是事件驱动内核的行情入口抽象，屏蔽回测/模拟盘/实盘三种模式的数据来源差异：
    - 回测：HistoricalDataFeed 从 SQLite 按时间顺序读取历史K线
    - 模拟盘/实盘：LiveDataFeed 多线程异步从行情源订阅实时K线

核心契约（设计文档 4.1 节）：
    1. start() 启动数据流（回测加载历史数据，实盘启动后台线程）
    2. 按交易日/实时推送 BarEvent 到 EventEngine
    3. history(symbol, fields, count) 切片历史K线，严格避免未来函数
       （返回的数据不得包含当前时间点之后的数据）
    4. get_current_bar(symbol) 返回当前 bar 的原始字段字典

依赖注入：
    EventEngine 通过 set_event_engine(engine) 注入，DataFeed 据此推送事件。

用法示例：
    feed = HistoricalDataFeed(db, "2024-01-01", "2024-06-30")
    feed.set_event_engine(engine)
    feed.subscribe(["600000.SH", "000001.SZ"])
    feed.start()
    bar = feed.next_bar()  # 回测专用，逐根推进
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import pandas as pd

from src.core.event_engine import EventEngine


class DataFeed(ABC):
    """数据流抽象基类。

    子类必须实现 7 个抽象方法：start/stop/subscribe/history/history_multi/
    get_current_bar。next_bar 不是抽象方法（仅回测 HistoricalDataFeed 需要）。

    Attributes:
        _event_engine: 注入的事件总线（None 表示未注入，推送事件前必须设置）
        _symbols: 订阅的 symbol 列表（subscribe 设置）
    """

    def __init__(self) -> None:
        # 事件总线，由 set_event_engine 注入；推送 BarEvent/TickEvent 时使用
        self._event_engine: Optional[EventEngine] = None
        # 订阅的 symbol 列表，subscribe 时填充
        self._symbols: List[str] = []

    # ------------------------------------------------------------------
    # 依赖注入
    # ------------------------------------------------------------------

    def set_event_engine(self, engine: EventEngine) -> None:
        """注入事件总线。

        DataFeed 在获取到新 bar/tick 时，通过该总线 publish 事件。
        必须在 start() 前调用。

        Args:
            engine: EventEngine 实例
        """
        self._event_engine = engine

    # ------------------------------------------------------------------
    # 抽象方法（子类必须实现）
    # ------------------------------------------------------------------

    @abstractmethod
    def start(self) -> None:
        """启动数据流。

        - HistoricalDataFeed：从 DB 加载历史K线到内存
        - LiveDataFeed：启动后台轮询线程
        """
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """停止数据流，释放后台资源（线程/连接）。"""
        raise NotImplementedError

    @abstractmethod
    def subscribe(self, symbols: List[str]) -> None:
        """订阅 symbol 列表。

        回测模式下应在 start() 前调用以限定加载范围；未订阅则加载全市场。
        实盘模式下设置实时行情订阅范围。

        Args:
            symbols: 标的代码列表，如 ["600000.SH", "000001.SZ"]
        """
        raise NotImplementedError

    @abstractmethod
    def history(self, symbol: str, fields: Optional[List[str]] = None, count: int = 100) -> pd.DataFrame:
        """查询单个 symbol 的历史K线（避免未来函数）。

        返回的数据严格截止当前时间点（含当前 bar），不含未来数据。

        Args:
            symbol: 标的代码
            fields: 需要的字段列表（如 ["open","close"]）；None 表示全部字段
            count: 返回最近 N 根 K 线

        Returns:
            DataFrame，索引为交易日，列为请求的字段；无数据时返回空 DataFrame
        """
        raise NotImplementedError

    @abstractmethod
    def history_multi(self, symbols: List[str], fields: Optional[List[str]] = None, count: int = 100) -> Dict[str, pd.DataFrame]:
        """批量查询多个 symbol 的历史K线。

        Args:
            symbols: 标的代码列表
            fields: 需要的字段列表；None 表示全部
            count: 每个 symbol 返回最近 N 根

        Returns:
            Dict[symbol, DataFrame]，每个 symbol 对应一个历史K线 DataFrame
        """
        raise NotImplementedError

    @abstractmethod
    def get_current_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取指定 symbol 的当前 bar 字段字典。

        在 on_event(BAR) 回调中调用，返回当前交易日该 symbol 的 OHLC 等字段。

        Args:
            symbol: 标的代码

        Returns:
            当前 bar 的字段字典；无数据时返回 None
        """
        raise NotImplementedError
