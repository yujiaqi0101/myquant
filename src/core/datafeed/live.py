"""
src/core/datafeed/live.py
=========================

LiveDataFeed 模拟盘/实盘数据流。

多线程异步获取实时行情，内存缓存最近 N 根 K 线供 history() 查询。

核心设计：
    1. start() 启动后台轮询线程 _poll_loop
    2. _poll_loop 循环调用 _fetch_latest_bar() 获取最新 bar：
       - 命中则更新内存缓存并 publish BarEvent 到事件总线
       - 未命中（返回 None）则按 _poll_interval 休眠后重试
    3. _fetch_latest_bar() 为预留接口，当前返回 None：
       - 实盘接入东财掘金实时行情 API
       - 模拟盘可降级为定时从 DB 读取最新 bar（阶段5 PaperEngine 接入）
    4. history/history_multi/get_current_bar 从内存缓存查询

线程安全：
    - 使用 threading.Event 作为停止标志，支持优雅退出
    - deque(maxlen=cache_size) 线程安全地维护最近 N 根 K 线
    - 轮询线程设为 daemon，主进程退出时自动结束

用法：
    from src.core.datafeed.live import LiveDataFeed
    feed = LiveDataFeed(source="eastmoney", cache_size=100)
    feed.set_event_engine(engine)
    feed.subscribe(["600000.SH"])
    feed.start()           # 启动后台线程
    ...
    feed.stop()            # 停止
"""

import logging
import threading
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

import pandas as pd

from src.core.datafeed.base import DataFeed
from src.core.events import BarEvent

logger = logging.getLogger(__name__)


class LiveDataFeed(DataFeed):
    """实时数据流（模拟盘/实盘）。

    Attributes:
        _source: 数据源标识（如 "eastmoney"），用于日志和未来路由
        _cache_size: 每个 symbol 缓存的最近 K 线数量
        _cache: symbol -> deque(maxlen=cache_size)，存最近 N 根 bar 字段字典
        _poll_thread: 后台轮询线程
        _stop_flag: 停止标志（threading.Event）
        _poll_interval: 轮询间隔（秒）
    """

    def __init__(self, source: str = "eastmoney", cache_size: int = 100) -> None:
        """初始化实时数据流。

        Args:
            source: 数据源标识，默认 "eastmoney"
            cache_size: 每个 symbol 内存缓存的最近 K 线数量，默认 100
        """
        super().__init__()
        # 数据源标识（东财掘金/通达信等）
        self._source = source
        # 缓存容量
        self._cache_size = cache_size
        # 内存缓存：symbol -> deque，存最近 N 根 bar 字段字典
        self._cache: Dict[str, Deque[Dict[str, Any]]] = {}
        # 后台轮询线程
        self._poll_thread: Optional[threading.Thread] = None
        # 停止标志，控制轮询线程退出
        self._stop_flag = threading.Event()
        # 轮询间隔（秒），模拟盘降级时为定时读 DB 的周期
        self._poll_interval = 1.0

    # ------------------------------------------------------------------
    # 订阅与启动
    # ------------------------------------------------------------------

    def subscribe(self, symbols: List[str]) -> None:
        """订阅 symbol 列表，并为每个 symbol 初始化缓存队列。

        Args:
            symbols: 标的代码列表
        """
        self._symbols = list(symbols)
        # 为每个 symbol 初始化定长缓存队列
        for s in self._symbols:
            if s not in self._cache:
                self._cache[s] = deque(maxlen=self._cache_size)

    def start(self) -> None:
        """启动后台轮询线程。

        线程为 daemon，主进程退出时自动结束。
        """
        # 重置停止标志，支持 restart
        self._stop_flag.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name=f"LiveDataFeed-{self._source}",
            daemon=True,
        )
        self._poll_thread.start()
        logger.info("LiveDataFeed 已启动：source=%s, symbols=%d", self._source, len(self._symbols))

    def stop(self) -> None:
        """停止轮询线程，等待最多 3 秒退出。"""
        # 设置停止标志
        self._stop_flag.set()
        # 等待线程退出
        if self._poll_thread is not None and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=3.0)
            if self._poll_thread.is_alive():
                logger.warning("LiveDataFeed 轮询线程在 3 秒内未退出")
        self._poll_thread = None

    # ------------------------------------------------------------------
    # 轮询循环
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """行情轮询主循环。

        循环调用 _fetch_latest_bar() 获取最新 bar，命中则更新缓存并推送事件。
        通过 _stop_flag.wait(interval) 实现可中断的休眠。
        """
        while not self._stop_flag.is_set():
            try:
                bar = self._fetch_latest_bar()
                if bar is not None:
                    self._on_new_bar(bar)
            except Exception:
                # 单次轮询异常不应终止线程
                logger.exception("LiveDataFeed 轮询获取行情异常")
            # 可中断的休眠：stop() 时立即唤醒
            self._stop_flag.wait(self._poll_interval)

    def _on_new_bar(self, bar: Dict[str, Any]) -> None:
        """处理新到的 bar：更新缓存并推送 BarEvent。

        Args:
            bar: bar 字段字典，需含 symbol 字段
        """
        symbol = bar.get("symbol", "")
        # 只缓存已订阅的 symbol
        if symbol in self._cache:
            self._cache[symbol].append(bar)
        # 推送 BarEvent 到事件总线
        if self._event_engine is not None:
            # 时间戳处理：优先用 bar 自带时间，否则用当前墙钟时间
            ts = bar.get("timestamp")
            if not isinstance(ts, datetime):
                ts = datetime.now()
            event = BarEvent(
                timestamp=ts,
                symbol=symbol,
                open=float(bar.get("open", 0.0)),
                high=float(bar.get("high", 0.0)),
                low=float(bar.get("low", 0.0)),
                close=float(bar.get("close", 0.0)),
                volume=float(bar.get("volume", 0.0)),
                amount=float(bar.get("amount", 0.0)),
                frequency=bar.get("frequency", "1d"),
                extra=bar.get("extra", {}),
            )
            self._event_engine.publish(event)

    def _fetch_latest_bar(self) -> Optional[Dict[str, Any]]:
        """从数据源获取最新 bar（预留接口）。

        当前阶段未接入真实行情源，返回 None。
        - 实盘：接入东财掘金实时行情 API，返回最新 tick/bar 字段字典
        - 模拟盘：可降级为定时从 DB 读取最新 bar（阶段5 PaperEngine 接入）

        Returns:
            bar 字段字典（需含 symbol/open/high/low/close/volume/amount 等）；
            无新数据返回 None
        """
        # 预留接口，当前无数据源接入
        return None

    # ------------------------------------------------------------------
    # 历史查询（从内存缓存）
    # ------------------------------------------------------------------

    def history(self, symbol: str, fields: Optional[List[str]] = None, count: int = 100) -> pd.DataFrame:
        """从内存缓存查询单 symbol 最近 N 根 K 线。

        Args:
            symbol: 标的代码
            fields: 字段列表；None 表示全部字段
            count: 返回最近 N 根

        Returns:
            DataFrame；无数据返回空 DataFrame
        """
        # symbol 未订阅或无缓存
        if symbol not in self._cache:
            return pd.DataFrame()
        # 取最近 count 根（deque 已是时序，直接切片）
        bars = list(self._cache[symbol])[-count:]
        if not bars:
            return pd.DataFrame()
        df = pd.DataFrame(bars)
        # 按需过滤字段
        if fields:
            avail = [f for f in fields if f in df.columns]
            df = df[avail]
        return df

    def history_multi(self, symbols: List[str], fields: Optional[List[str]] = None, count: int = 100) -> Dict[str, pd.DataFrame]:
        """批量查询多 symbol 的最近 N 根 K 线。

        Args:
            symbols: 标的代码列表
            fields: 字段列表；None 表示全部
            count: 每个 symbol 返回最近 N 根

        Returns:
            Dict[symbol, DataFrame]
        """
        return {s: self.history(s, fields, count) for s in symbols}

    def get_current_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取指定 symbol 的最新（缓存末尾）bar 字段字典。

        Args:
            symbol: 标的代码

        Returns:
            最新 bar 字段字典的拷贝；无数据返回 None
        """
        # symbol 无缓存或缓存为空
        if symbol not in self._cache or not self._cache[symbol]:
            return None
        # 返回拷贝，避免外部修改污染缓存
        return dict(self._cache[symbol][-1])
