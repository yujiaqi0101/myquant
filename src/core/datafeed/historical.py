"""
src/core/datafeed/historical.py
===============================

HistoricalDataFeed 回测专用数据流。

从 SQLite 数据库读取历史日频K线，按交易日逐根推送 BarEvent。

数据来源：DatabaseManager.get_stock_daily()，返回多级索引 (trade_date, stock_code)
的 DataFrame，含 open/high/low/close/volume/amount 等字段（见 t_stock_daily 表）。

核心设计：
    1. start() 时一次性加载全市场（或订阅的 symbol）数据到内存，按 symbol 分组
       存入 Dict[symbol, DataFrame]，并收集所有交易日排序
    2. next_bar() 按交易日推进，构造 BarEvent：
       - 主体 OHLC 取"第一个 symbol"（排序后）的当日 bar
       - extra["symbols_bars"] 承载全市场当日 bar 字典（兼容阶段1 BarEvent 单symbol结构）
       - extra["trade_date"] 承载当前交易日字符串
    3. history(symbol, fields, count) 切片截止当前交易日（含）的数据，避免未来函数

注：BarEvent 在阶段1定义为单 symbol 结构（OHLC + extra）。
    本类用 extra["symbols_bars"] 传递全市场当日数据，供选股策略（如小市值全市场选股）使用。

用法：
    from src.data.database import DatabaseManager
    from src.core.datafeed.historical import HistoricalDataFeed
    feed = HistoricalDataFeed(db, "2024-01-01", "2024-06-30")
    feed.set_event_engine(engine)
    feed.subscribe(["600000.SH"])   # 可选，不订阅则加载全市场
    feed.start()
    while True:
        bar = feed.next_bar()
        if bar is None:
            break
        # 处理 bar
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from src.core.datafeed.base import DataFeed
from src.core.events import BarEvent

logger = logging.getLogger(__name__)


class HistoricalDataFeed(DataFeed):
    """回测专用历史数据流。

    Attributes:
        _db: DatabaseManager 实例（提供 get_stock_daily 方法）
        _start_date / _end_date: 回测起止日期（字符串 YYYY-MM-DD）
        _bars_by_symbol: 按 symbol 分组的日频 DataFrame，索引为 trade_date
        _dates: 排序后的所有交易日列表（pd.Timestamp）
        _current_idx: 当前推进到的日期索引（-1 表示尚未开始）
    """

    def __init__(self, db: Any, start_date: str, end_date: str) -> None:
        """初始化回测数据流。

        Args:
            db: DatabaseManager 实例，需提供 get_stock_daily 方法
            start_date: 起始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
        """
        super().__init__()
        # DatabaseManager 实例，用于读取 t_stock_daily
        self._db = db
        # 回测时间范围
        self._start_date = start_date
        self._end_date = end_date
        # 按 symbol 分组的日频数据：symbol -> DataFrame(index=trade_date)
        self._bars_by_symbol: Dict[str, pd.DataFrame] = {}
        # 排序后的所有交易日列表
        self._dates: List[pd.Timestamp] = []
        # 当前推进到的日期索引，-1 表示尚未开始
        self._current_idx: int = -1

    # ------------------------------------------------------------------
    # 订阅与启动
    # ------------------------------------------------------------------

    def subscribe(self, symbols: List[str]) -> None:
        """订阅 symbol 列表。

        必须在 start() 前调用，否则 start() 会加载全市场数据。
        订阅后 start() 只加载这些 symbol，节省内存。

        Args:
            symbols: 标的代码列表
        """
        self._symbols = list(symbols)

    def start(self) -> None:
        """启动数据流：从 DB 加载日频数据到内存。

        若 subscribe 已设置 symbol 列表，则只加载这些 symbol；否则加载全市场。
        加载后按 symbol 分组，并收集所有交易日排序。
        """
        # 订阅列表为空时传 None，表示加载全市场
        stock_codes: Optional[List[str]] = self._symbols if self._symbols else None
        # 调用 DatabaseManager.get_stock_daily 读取日频数据
        raw_df = self._db.get_stock_daily(
            stock_codes=stock_codes,
            start_date=self._start_date,
            end_date=self._end_date,
        )

        # 数据为空：初始化空结构
        if raw_df.empty:
            logger.warning(
                "HistoricalDataFeed 加载到空数据：start=%s end=%s symbols=%s",
                self._start_date, self._end_date, stock_codes or "全市场",
            )
            self._bars_by_symbol = {}
            self._dates = []
            self._current_idx = -1
            return

        # raw_df 索引为 (trade_date, stock_code) 多级索引
        # 按 stock_code 分组，每组 droplevel 后得到单 symbol 的单索引 DataFrame
        self._bars_by_symbol = {}
        for stock_code, group in raw_df.groupby(level="stock_code"):
            # 去掉 stock_code 层级，保留 trade_date 作为索引，并按日期排序
            sym_df = group.droplevel("stock_code").sort_index()
            self._bars_by_symbol[stock_code] = sym_df

        # 收集所有交易日并去重排序
        all_dates = raw_df.index.get_level_values("trade_date").unique().sort_values()
        self._dates = list(all_dates)
        # 重置游标到起始前
        self._current_idx = -1
        logger.info(
            "HistoricalDataFeed 已加载：symbols=%d, trading_days=%d, 范围=%s~%s",
            len(self._bars_by_symbol), len(self._dates),
            self._dates[0].strftime("%Y-%m-%d") if self._dates else "-",
            self._dates[-1].strftime("%Y-%m-%d") if self._dates else "-",
        )

    def stop(self) -> None:
        """停止数据流。回测模式无后台资源，仅清理内存引用。"""
        self._bars_by_symbol = {}
        self._dates = []
        self._current_idx = -1

    # ------------------------------------------------------------------
    # 逐根推进（回测核心）
    # ------------------------------------------------------------------

    def next_bar(self) -> Optional[BarEvent]:
        """按交易日逐根推进，返回 BarEvent 或 None（数据耗尽）。

        每次调用推进一个交易日。当日所有 symbol 的 bar 收集到 extra["symbols_bars"]，
        主体 OHLC 取排序后第一个 symbol 的当日 bar。

        Returns:
            BarEvent 或 None（所有交易日已推送完毕）
        """
        # 推进到下一个交易日
        self._current_idx += 1
        # 游标越界：数据耗尽
        if self._current_idx >= len(self._dates):
            return None

        current_date = self._dates[self._current_idx]

        # 收集当日所有 symbol 的 bar 字段字典
        symbols_bars: Dict[str, Dict[str, Any]] = {}
        for symbol, sym_df in self._bars_by_symbol.items():
            # 当前日期是否在该 symbol 的索引中
            if current_date in sym_df.index:
                # 取该日该 symbol 的一行（Series），转为字段字典
                row = sym_df.loc[current_date]
                symbols_bars[symbol] = row.to_dict()

        # 当日无任何 symbol 数据：跳过该交易日，递归取下一个
        if not symbols_bars:
            return self.next_bar()

        # 取排序后第一个 symbol 的 bar 作为 BarEvent 主体字段（保证稳定）
        first_symbol = sorted(symbols_bars.keys())[0]
        first_bar = symbols_bars[first_symbol]

        # Timestamp 转 datetime（BarEvent.timestamp 需要 datetime 类型）
        if hasattr(current_date, "to_pydatetime"):
            ts = current_date.to_pydatetime()
        else:
            ts = current_date

        # 交易日字符串，便于策略日志/判断
        trade_date_str = (
            current_date.strftime("%Y-%m-%d")
            if hasattr(current_date, "strftime")
            else str(current_date)
        )

        # 构造 BarEvent：主体是第一个 symbol 的 OHLC，extra 承载全市场数据
        bar_event = BarEvent(
            timestamp=ts,
            symbol=first_symbol,
            open=float(first_bar.get("open", 0.0)),
            high=float(first_bar.get("high", 0.0)),
            low=float(first_bar.get("low", 0.0)),
            close=float(first_bar.get("close", 0.0)),
            volume=float(first_bar.get("volume", 0.0)),
            amount=float(first_bar.get("amount", 0.0)),
            frequency="1d",
            extra={
                "symbols_bars": symbols_bars,
                "trade_date": trade_date_str,
            },
        )
        return bar_event

    # ------------------------------------------------------------------
    # 历史查询（避免未来函数）
    # ------------------------------------------------------------------

    def history(self, symbol: str, fields: Optional[List[str]] = None, count: int = 100) -> pd.DataFrame:
        """查询单 symbol 截止当前交易日（含）的历史K线。

        严格避免未来函数：只返回 trade_date <= 当前交易日的数据。

        Args:
            symbol: 标的代码
            fields: 字段列表；None 表示全部字段
            count: 返回最近 N 根

        Returns:
            DataFrame，索引为 trade_date；无数据返回空 DataFrame
        """
        # symbol 不在已加载列表中
        if symbol not in self._bars_by_symbol:
            return pd.DataFrame()
        sym_df = self._bars_by_symbol[symbol]
        # 尚未开始推送（游标为 -1）：返回空，避免未来函数
        if self._current_idx < 0:
            return pd.DataFrame()
        # 截止当前交易日（含）的数据切片
        current_date = self._dates[self._current_idx]
        sub = sym_df[sym_df.index <= current_date].tail(count)
        # 按需过滤字段
        if fields:
            avail = [f for f in fields if f in sub.columns]
            sub = sub[avail]
        return sub

    def history_multi(self, symbols: List[str], fields: Optional[List[str]] = None, count: int = 100) -> Dict[str, pd.DataFrame]:
        """批量查询多 symbol 的历史K线。

        Args:
            symbols: 标的代码列表
            fields: 字段列表；None 表示全部
            count: 每个 symbol 返回最近 N 根

        Returns:
            Dict[symbol, DataFrame]
        """
        return {s: self.history(s, fields, count) for s in symbols}

    def get_current_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取指定 symbol 的当前 bar 字段字典。

        Args:
            symbol: 标的代码

        Returns:
            当前 bar 字段字典；无数据返回 None
        """
        # symbol 未加载或尚未推进
        if symbol not in self._bars_by_symbol:
            return None
        if self._current_idx < 0 or self._current_idx >= len(self._dates):
            return None
        current_date = self._dates[self._current_idx]
        sym_df = self._bars_by_symbol[symbol]
        # 当前日期不在该 symbol 索引中（可能当日停牌）
        if current_date not in sym_df.index:
            return None
        return sym_df.loc[current_date].to_dict()
