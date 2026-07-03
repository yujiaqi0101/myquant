"""
小市值策略（基于统一事件驱动内核）
====================================

本文件是引擎统一重构后的小市值策略实现，基于 src/core/strategy.py 的 Strategy 基类。

策略逻辑（设计文档 7.1 节）：
    1. 月度调仓：每月第一个交易日调仓（由 TimerEvent 触发）
    2. 选股逻辑：从全市场选取总市值最小的 N 只股票
    3. 等权配置：每只股票分配 1/N 仓位
    4. 排除条件：ST/新股/停牌/涨跌停由风控管线自动过滤（不在策略层处理）

数据来源：
    - K线数据：BarEvent.extra["symbols_bars"]（全市场当日OHLC）
    - 市值数据：t_stock_mktvalue 表（通过 context.get_db() 只读查询）

参数：
    - top_n: 持仓数量（默认 5）
    - rebalance_at: 调仓频率（month_start/month_end/week_start，默认 month_start）

用法：
    from src.core.strategy import auto_discover
    from src.core.engine import BacktestEngine
    auto_discover()  # 自动发现并注册策略
    strategy_cls = get_strategy_class("small_cap")
    strategy = strategy_cls(params={"top_n": 5})
    engine = BacktestEngine(strategy=strategy, db=db, ...)
    result = engine.run()
"""

import logging
from typing import Any, Dict, List, Optional

from src.core.context import Context
from src.core.events import Event, EventType
from src.core.strategy import Strategy, register_strategy

logger = logging.getLogger(__name__)


@register_strategy("small_cap")
class SmallCapStrategy(Strategy):
    """小市值策略（统一事件驱动内核版）。

    月度调仓，从全市场选取市值最小的 N 只股票，等权配置。
    ST/新股/停牌/涨跌停由风控管线自动过滤。

    Parameters
    ----------
    top_n : int
        持仓数量（默认 5）
    rebalance_at : str
        调仓频率：month_start / month_end / week_start（默认 month_start）
    """

    name = "small_cap"

    def __init__(self, params: Optional[Dict] = None) -> None:
        super().__init__(params)
        # 持仓数量
        self.top_n: int = int(self.params.get("top_n", 5))
        # 调仓频率
        self.rebalance_at: str = str(self.params.get("rebalance_at", "month_start"))
        # 数据库连接（on_init 时从 context 获取）
        self._db: Any = None
        # 是否已首次建仓
        self._bought: bool = False
        # 上一次调仓日（避免同一交易日重复调仓）
        self._last_rebalance_date: str = ""

    # ------------------------------------------------------------------
    # 生命周期回调
    # ------------------------------------------------------------------

    def on_init(self, context: Context) -> None:
        """初始化：获取数据库连接，注册调仓定时器。"""
        # 获取数据库连接（只读用途，查询市值数据）
        self._db = context.get_db()
        # 注册调仓定时器
        context.add_timer("rebalance", self.rebalance_at)
        context.log("info", "小市值策略初始化",
                    top_n=self.top_n, rebalance_at=self.rebalance_at)

    def on_event(self, event: Event, context: Context) -> None:
        """统一事件处理：TimerEvent 触发调仓，首个 BarEvent 也触发首次建仓。"""
        # 首个 BarEvent：触发首次建仓（确保回测开始即建仓）
        if event.type is EventType.BAR and not self._bought:
            self._rebalance(context, event)
            self._bought = True
            return

        # TimerEvent：调仓定时器触发
        if event.type is EventType.TIMER and event.name == "rebalance":
            self._rebalance(context, event)

    def on_stop(self, context: Context) -> None:
        """策略停止。"""
        context.log("info", "小市值策略停止")

    # ------------------------------------------------------------------
    # 调仓逻辑
    # ------------------------------------------------------------------

    def _rebalance(self, context: Context, event: Event) -> None:
        """执行调仓：选股 + 等权下单 + 清仓非目标持仓。

        步骤：
            1. 获取当前交易日和全市场股票列表
            2. 查询市值数据，选市值最小的 TopN
            3. 等权配置（target_weight = 1/top_n）
            4. 清仓不在目标池的持仓
        """
        # 获取当前交易日字符串
        trade_date = self._get_trade_date(event)
        if not trade_date:
            return

        # 避免同一交易日重复调仓
        if trade_date == self._last_rebalance_date:
            return

        # 获取当日全市场股票列表
        symbols_bars = self._get_symbols_bars(event)
        if not symbols_bars:
            return

        # 选股：市值最小的 TopN
        candidates = list(symbols_bars.keys())
        target_symbols = self._select_top_n(trade_date, candidates)

        if not target_symbols:
            context.log("warning", "调仓日无合格目标股票", trade_date=trade_date)
            return

        # 等权配置
        weight = 1.0 / self.top_n if self.top_n > 0 else 0.0

        # 对目标股票下目标权重订单
        for sym in target_symbols:
            context.submit_order(
                symbol=sym,
                direction="target",
                target_weight=weight,
                price_type="market",
            )

        # 清仓不在目标池的持仓
        positions = context.get_positions()
        for sym in positions:
            if sym not in target_symbols:
                context.submit_order(
                    symbol=sym,
                    direction="target",
                    target_weight=0.0,
                    price_type="market",
                )

        self._last_rebalance_date = trade_date
        context.log("info", "调仓完成",
                    trade_date=trade_date,
                    target_count=len(target_symbols),
                    weight=round(weight, 4))

    # ------------------------------------------------------------------
    # 选股逻辑
    # ------------------------------------------------------------------

    def _select_top_n(self, trade_date: str, candidates: List[str]) -> List[str]:
        """从候选股票中选市值最小的 TopN。

        Args:
            trade_date: 交易日（YYYY-MM-DD）
            candidates: 候选股票代码列表

        Returns:
            目标股票代码列表（按市值升序，取前 top_n）
        """
        if self._db is None:
            # 无数据库：直接取候选列表前 top_n
            return candidates[: self.top_n]

        try:
            # 查询当日市值数据
            df = self._db.get_stock_mktvalue(
                stock_codes=candidates,
                start_date=trade_date,
                end_date=trade_date,
            )
        except Exception as e:
            logger.warning("查询市值数据失败: %s，回退到候选列表前 %d", e, self.top_n)
            return candidates[: self.top_n]

        if df is None or df.empty:
            # 当日无市值数据：尝试查询最近一日
            return self._select_with_latest_market_cap(trade_date, candidates)

        # 过滤有效市值（tot_mv > 0）
        if "tot_mv" not in df.columns:
            return candidates[: self.top_n]
        df = df[df["tot_mv"] > 0]
        if df.empty:
            return candidates[: self.top_n]

        # 按总市值升序排序，取前 top_n
        df = df.sort_values("tot_mv")
        return df["stock_code"].head(self.top_n).tolist()

    def _select_with_latest_market_cap(
        self, trade_date: str, candidates: List[str]
    ) -> List[str]:
        """当日无市值数据时，查询最近一日市值数据选股。

        Args:
            trade_date: 当前交易日
            candidates: 候选股票列表

        Returns:
            目标股票代码列表
        """
        if self._db is None:
            return candidates[: self.top_n]

        try:
            # 查询截止当前日期的全部市值数据，取每只股票最近一条
            df = self._db.get_stock_mktvalue(
                stock_codes=candidates,
                end_date=trade_date,
            )
        except Exception:
            return candidates[: self.top_n]

        if df is None or df.empty:
            return candidates[: self.top_n]

        # 按 stock_code 分组取最近一条
        if "trade_date" in df.columns and "tot_mv" in df.columns:
            df = df[df["tot_mv"] > 0]
            # 取每只股票最近一日的市值
            df = df.sort_values("trade_date").groupby("stock_code").last().reset_index()
            df = df.sort_values("tot_mv")
            return df["stock_code"].head(self.top_n).tolist()

        return candidates[: self.top_n]

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _get_trade_date(event: Event) -> str:
        """从事件中提取交易日字符串。"""
        # BarEvent 和 TimerEvent 都可能携带 extra
        extra = getattr(event, "extra", None)
        if extra and isinstance(extra, dict):
            return extra.get("trade_date", "")
        return ""

    @staticmethod
    def _get_symbols_bars(event: Event) -> Dict[str, Any]:
        """从事件中获取全市场当日 bar 字典。"""
        extra = getattr(event, "extra", None)
        if extra and isinstance(extra, dict):
            return extra.get("symbols_bars", {})
        return {}
