"""
V2.4 TickEngine — TickEngine

核心：
  - 复用 Strategy / Execution / Portfolio / TradeBook
  - 唯一变化：bar → tick 流
  - 撮合用 tick.price + TickSlippage
  - snapshot_interval 控制权益记录频率

V1 流程：

  1) for tick in feed.stream():
       |
       v
  2) pending.match(tick) → 撮合历史挂单
       |
       v
  3) 把 tick.price 喂 ctx.last_prices
       |
       v
  4) strategy.signal() → 调仓 weights
       |
       v
  5) execution.generate_orders(...)
       |  → Order 列表
       v
  6) new orders → pending.submit
       |
       v
  7) pending.match(tick) → 撮合新单
       |
       v
  8) portfolio.apply_fill(fill)
       |
       v
  9) portfolio.record(tick.timestamp, prices)
       |
       v
  10) 每 snapshot_interval ticks → 记一次 equity

  4-9 复用 BarEngine
  1-3 / 10 是 TickEngine 特有

不做：
  - L2 OrderBook
  - 撮合队列
  - 委托排队
  - 部分成交
  - 高频套利
"""


from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import numpy as np
import pandas as pd

from ..core.base_engine import (
    BaseBacktestEngine,
)
from ..core.backtest_result import (
    BacktestResult,
)
from ..core.portfolio import (
    Portfolio,
)
from ..core.tradebook import (
    TradeBook,
)
from ..core.tick import Tick
from ..core.fill import Fill
from ..core.order import Order
from ..data.tick_feed import (
    BarToTickFeed,
)
from .tick_matcher import (
    TickMatcher,
    TickPendingOrders,
)
from .intrabar_execution import (
    IntrabarExecution,
)
from ..execution.matcher import (
    TargetWeightExecution,
)
from ..execution.commission import (
    PercentageCommission,
)


class TickEngine(BaseBacktestEngine):

    # V1 Tick 回测引擎
    #
    # 关键参数：
    #   data                Dict[symbol, DataFrame]
    #   strategy            有 .signal(ctx) 接口
    #   tick_size           最小价格变动
    #                       默认 0.01
    #   commission_rate     佣金率
    #                       默认 0.0003
    #   snapshot_interval   每 N ticks 记一次 equity
    #                       默认 10
    #   portfolio_constructor 调仓规则
    #                        默认 None
    #                        （直接用 target weights）
    #   execution           撮合
    #                        默认 TargetWeightExecution
    #   initial_cash        初始资金
    #
    # 不重写：
    #   - Strategy
    #   - Execution
    #   - Portfolio
    #   - TradeBook

    def __init__(
        self,
        strategy: Any = None,
        portfolio_constructor: Any = None,
        commission_model: Any = None,
        initial_cash: float = 100000,
        tick_size: float = 0.01,
        commission_rate: float = 0.0003,
        snapshot_interval: int = 10,
    ):

        self.strategy = strategy

        # V1 默认 None
        # （TickEngine 内部不调 constructor）
        # strategy.signal() 直接产 weights
        self.portfolio_constructor = (
            portfolio_constructor
        )

        # 兼容：
        #   commission_model 不传时
        #   内部用 PercentageCommission
        self.commission_model = (
            commission_model
            or PercentageCommission(
                rate=commission_rate
            )
        )

        self.initial_cash = initial_cash

        self.tick_size = tick_size

        self.commission_rate = (
            commission_rate
        )

        self.snapshot_interval = (
            snapshot_interval
        )

        # ---- 内部组件 ----

        # execution
        # 默认 TargetWeightExecution
        self.execution = (
            TargetWeightExecution()
        )

        # tick 级撮合
        self.tick_matcher = TickMatcher(
            tick_size=tick_size,
            commission_rate=(
                commission_rate
            ),
        )

        # intrabar 成交
        self.intrabar_execution = (
            IntrabarExecution(
                tick_size=tick_size,
                commission_rate=(
                    commission_rate
                ),
            )
        )

        # pending orders
        self.pending_orders = (
            TickPendingOrders(
                matcher=self.tick_matcher
            )
        )

    def run(
        self,
        strategy: Any = None,
        data: Dict = None,
        params: Dict = None,
    ) -> BacktestResult:

        # BaseBacktestEngine 协议
        if strategy is not None:
            self.strategy = strategy

        data = data or {}

        params = params or {}

        # 1) 准备 Portfolio / TradeBook
        portfolio = Portfolio(
            initial_cash=self.initial_cash
        )
        tradebook = TradeBook()

        # 2) 准备 TickFeed
        #    V1 用 BarToTickFeed
        feed = BarToTickFeed(
            data=data
        )

        # 3) 准备 equity / timestamps
        equity_curve = []
        equity_ts = []
        last_prices: Dict[str, float] = {}
        tick_counter = 0
        n_ticks_total = 0

        # 4) 主循环
        for tick in feed.stream():

            n_ticks_total += 1

            # 4.1) 更新 last_prices
            last_prices[tick.symbol] = (
                tick.last_price
            )

            # 4.2) 撮合历史 pending orders
            pending_fills = (
                self.pending_orders.match(
                    tick
                )
            )

            for fill in pending_fills:
                self._apply_fill(
                    portfolio,
                    tradebook,
                    fill,
                )

            # 4.3) 触发 strategy
            #     用 last_prices 当作 ctx
            if self.strategy is not None:

                weights = self._run_strategy(
                    tick.timestamp,
                    last_prices,
                )

                if weights:

                    orders = (
                        self._generate_orders(
                            portfolio,
                            weights,
                            last_prices,
                            timestamp=(
                                tick.timestamp
                            ),
                        )
                    )

                    # 4.4) 新 order 立即撮合
                    for order in orders:

                        fill = (
                            self
                            .intrabar_execution
                            .execute(
                                order, tick
                            )
                        )

                        self._apply_fill(
                            portfolio,
                            tradebook,
                            fill,
                        )

            # 4.5) 更新 portfolio
            portfolio.record(
                tick.timestamp,
                last_prices,
            )

            # 4.6) snapshot
            tick_counter += 1
            if (
                tick_counter
                % self.snapshot_interval
                == 0
            ):

                equity_curve.append(
                    portfolio.equity()
                )
                equity_ts.append(
                    tick.timestamp
                )

        # 5) 收尾：
        #    如果最后没记上
        #    补一次
        if (
            equity_ts
            and equity_ts[-1]
            != tick.timestamp
        ):
            equity_curve.append(
                portfolio.equity()
            )
            equity_ts.append(tick.timestamp)

        elif not equity_ts:
            # 0 记录（n_ticks_total < snapshot_interval）
            equity_curve.append(
                portfolio.equity()
            )
            equity_ts.append(tick.timestamp)

        # 6) 算指标
        return self._build_result(
            equity_curve=equity_curve,
            timestamps=equity_ts,
            tradebook=tradebook,
            portfolio=portfolio,
            n_ticks=n_ticks_total,
            data=data,
            params=params,
        )

    # ----------------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------------

    def _run_strategy(
        self,
        timestamp,
        last_prices: Dict[str, float],
    ) -> Dict[str, float]:

        # 调 strategy.signal()
        #
        # 复用 strategy
        # V1 简化：
        #   直接调 strategy.signal(ctx)
        #   ctx 是个 dict-like
        #   包含 last_prices / timestamp
        #
        # 注意：
        #   StrategyContext(data, cache)
        #   完整签名
        #   V1 简化传 dict-like 也行
        #   strategy 内部读
        #     ctx['last_prices'] / ctx['timestamp']
        #
        # 进阶：
        #   V2 让 strategy 接受 Tick 流
        #   V1 不做

        if self.strategy is None:
            return {}

        # ---- 路径 1: 简单 dict-like ctx ----
        # 给简单 strategy 用
        # （直接 .signal(ctx) 读 ctx['last_prices']）
        try:

            ctx = {
                "timestamp": timestamp,
                "last_prices": last_prices,
            }

            signal = self.strategy.signal(
                ctx
            )

            if isinstance(signal, dict):
                return signal

            if isinstance(
                signal, pd.DataFrame
            ):

                last = signal.iloc[-1]
                return last.to_dict()

        except Exception:

            pass

        return {}

    def _generate_orders(
        self,
        portfolio: Portfolio,
        weights: Dict[str, float],
        prices: Dict[str, float],
        timestamp: Any = None,
    ) -> List[Order]:

        # 把 weights 喂 execution
        #
        # 复用 TargetWeightExecution
        # 需要 TargetPortfolio 对象
        from ..portfolio_construction.target_portfolio import (
            TargetPortfolio,
        )

        target = TargetPortfolio(
            timestamp=(
                timestamp
                or pd.Timestamp.utcnow()
            ),
            weights=weights,
        )

        return self.execution.generate_orders(
            portfolio=portfolio,
            target_portfolio=target,
            prices=prices,
        )

    def _apply_fill(
        self,
        portfolio: Portfolio,
        tradebook: TradeBook,
        fill: Fill,
    ):

        # 把 fill 应用到 portfolio
        # 复用 portfolio.apply_fill
        # 复用 tradebook.record_fill
        try:

            portfolio.apply_fill(
                symbol=fill.symbol,
                quantity=fill.quantity,
                price=fill.price,
                commission=(
                    fill.commission
                ),
                timestamp=(
                    fill.timestamp
                ),
            )
        except Exception:

            # 兼容：apply_fill 接口可能不同
            # 兜底直接调
            self._apply_fill_fallback(
                portfolio,
                fill,
            )

        try:
            tradebook.record_fill(fill)
        except Exception:
            pass

    def _apply_fill_fallback(
        self,
        portfolio: Portfolio,
        fill: Fill,
    ):

        # 兜底
        # 直接修改 position + cash
        pos = portfolio.get_or_create(
            fill.symbol
        )
        pos.qty += fill.quantity
        if pos.avg_price == 0:
            pos.avg_price = (
                fill.price
            )
        else:
            # 简化平均
            pos.avg_price = (
                pos.avg_price
                + fill.price
            ) / 2

        portfolio.cash -= (
            fill.quantity
            * fill.price
        )
        portfolio.cash -= (
            fill.commission
        )

    def _build_result(
        self,
        equity_curve,
        timestamps,
        tradebook,
        portfolio,
        n_ticks,
        data,
        params,
    ) -> BacktestResult:

        # 算 sharpe / max_dd / total_return
        from ..analytics import (
            sharpe_ratio,
            max_drawdown,
            total_return,
        )

        if equity_curve:

            eq_arr = np.array(
                equity_curve,
                dtype=float,
            )

            rets = np.diff(eq_arr) / eq_arr[:-1]

            sharpe = float(
                sharpe_ratio(rets)
            ) if len(rets) > 1 else 0.0
            mdd = float(
                max_drawdown(eq_arr)
            )
            tr = float(
                total_return(eq_arr)
            )
            final_eq = float(eq_arr[-1])
        else:

            sharpe = 0.0
            mdd = 0.0
            tr = 0.0
            final_eq = float(
                self.initial_cash
            )

        # 收集 fills
        fills_list = []
        if hasattr(
            tradebook, "fills"
        ):
            fills_list = list(
                tradebook.fills
            )
        elif hasattr(
            tradebook, "all_fills"
        ):
            fills_list = list(
                tradebook.all_fills()
            )

        return BacktestResult(
            equity_curve=equity_curve,
            total_return=tr,
            sharpe=sharpe,
            max_drawdown=mdd,
            trade_count=len(fills_list),
            win_rate=0.0,
            final_equity=final_eq,
            source="tick",
            raw={
                "n_ticks": n_ticks,
                "n_snapshots": len(
                    equity_curve
                ),
                "snapshot_interval": (
                    self.snapshot_interval
                ),
                "tick_size": (
                    self.tick_size
                ),
            },
            fills=fills_list,
            tradebook=tradebook,
            portfolio=portfolio,
            position_qty={
                s: p.qty
                for s, p
                in portfolio.positions.items()
            },
            signal=None,
            timestamps=timestamps,
        )
