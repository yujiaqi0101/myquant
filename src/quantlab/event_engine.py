"""
EventEngine：事件驱动版回测引擎
保留 BarEngine 不变
EventEngine 作为"完全解耦"的版本

事件流：
  MarketEvent      引擎发
    ↓
  SignalEvent      StrategyHandler 发
    ↓
  OrderEvent       PortfolioConstructionHandler 发
    ↓
  FillEvent        MatcherHandler 发
  FillEvent        触发 Portfolio/TradeBook 更新

优势：
- 加新模块（比如 RiskManager）只需订阅 / 发送事件
- 接 TickEngine：发 MarketEvent(type="TICK", ...)
- 接实盘：把 MarketEvent 推上 EventBus
"""

from typing import Dict, List

import pandas as pd

from .core.portfolio import Portfolio
from .core.fill import Fill
from .core.tradebook import TradeBook
from .core.position import Position
from .core.base_engine import (
    BaseBacktestEngine,
)
from .core.backtest_result import (
    BacktestResult,
)

from .data.cache import factor_cache
from .data.context import StrategyContext

from .event.event_types import (
    MarketEvent,
    SignalEvent,
    OrderEvent,
    FillEvent,
)
from .event.event_bus import EventBus

from .portfolio_construction.target_portfolio import (
    TargetPortfolio,
)


class EventEngine(BaseBacktestEngine):

    # 事件驱动版回测引擎
    # 与 BarEngine 等价（同样的回测结果）
    # 但每个模块都是 EventBus 订阅者
    # 通过事件解耦

    def run(
        self,
        strategy=None,
        data: Dict = None,
        params: Dict = None,
    ) -> BacktestResult:

        # BaseBacktestEngine 协议
        # strategy 可传可不传（兼容老用法：
        #   engine = EventEngine(strategy=..., ...)
        #   engine.run(data)
        # 和新用法：
        #   engine.run(strategy=strat, data=data)
        # 都行）
        if strategy is not None:

            self.strategy = strategy

        raw = self._run_legacy(data)

        return BacktestResult.from_event_dict(
            raw
        )

    def __init__(
        self,
        strategy,
        portfolio_constructor,
        execution_model,
        commission_model,
        slippage_model,
        initial_cash=100000,
        bus: EventBus = None,
    ):

        self.strategy = strategy
        self.portfolio_constructor = (
            portfolio_constructor
        )
        self.execution_model = (
            execution_model
        )
        self.commission_model = (
            commission_model
        )
        self.slippage_model = (
            slippage_model
        )
        self.initial_cash = initial_cash

        # EventBus：可注入（方便单测）
        self.bus = bus or EventBus()

        # 共享 state（订阅者通过 self 访问）
        self.portfolio = Portfolio(
            initial_cash
        )
        self.tradebook = TradeBook()
        self.fills: List[Fill] = []
        self.signal_df = None

        # 每根 bar 后每 symbol 的持仓 qty
        # Experiment 用它算 exposure
        self.position_qty: Dict = {}

        # 内部缓存：当前 bar 价格 / 时间戳
        self._cur_prices: Dict = {}
        self._cur_open: Dict = {}
        self._cur_ts = None

        # 注册订阅者
        self._setup_listeners()

    def _setup_listeners(self):

        # 信号：监听 MARKET，发 SIGNAL
        self.bus.subscribe(
            "MARKET",
            self._on_market,
        )
        # 撮合：监听 ORDER，发 FILL
        self.bus.subscribe(
            "ORDER",
            self._on_order,
        )
        # 记账：监听 FILL，更新 portfolio
        self.bus.subscribe(
            "FILL",
            self._on_fill,
        )

    def _on_market(self, event: MarketEvent):

        i = event.payload["i"]
        symbols = event.payload["symbols"]
        data = event.payload["data"]
        self._cur_prices = event.payload["bar_close"]
        self._cur_open = event.payload["bar_open"]
        self._cur_ts = event.payload["timestamp"]

        # i=0: 初始化权益记录
        if i == 0:

            self.portfolio.record(
                self._cur_ts,
                self._cur_prices
            )

            # 全发空 signal（首根 bar 不调仓）
            for sym in symbols:

                self.bus.publish(
                    SignalEvent(
                        timestamp=(
                            self._cur_ts
                        ),
                        symbol=sym,
                        direction=0,
                        score=0.0,
                    )
                )

            return

        # i>=1: 调 strategy.signal
        # 与 BarEngine 一致：取前一根 bar 的 score
        prev_scores = (
            self.signal_df
            .iloc[i - 1]
            .to_dict()
        )

        # 对每个 symbol 发 SignalEvent
        for sym in symbols:

            score = prev_scores.get(
                sym, 0
            )
            direction = (
                1 if score > 0 else 0
            )

            self.bus.publish(
                SignalEvent(
                    timestamp=self._cur_ts,
                    symbol=sym,
                    direction=direction,
                    score=score,
                )
            )

    def _on_signal(
        self, event: SignalEvent
    ):
        # 收集 signal（Portfolio Construction 需要）
        # V1：直接用 score 处理
        pass

    def _on_order(self, event: OrderEvent):

        sym = event.symbol
        q = event.quantity

        if sym not in self._cur_open:

            return

        price = self._cur_open[sym]

        # 滑点
        fill_price = (
            self.slippage_model.apply(
                q, price
            )
        )

        # 佣金
        commission = (
            self.commission_model.calculate(
                q, fill_price
            )
        )

        cost = (
            q * fill_price + commission
        )

        # 现金不足：自动降仓
        if (
            q > 0
            and cost > self.portfolio.cash
        ):

            affordable = (
                self.portfolio.cash
                - commission
            )

            if affordable <= 0:

                q = 0
            else:

                q = int(
                    affordable / fill_price
                )
                cost = (
                    q * fill_price
                    + commission
                )

        if q == 0:

            return

        # 扣现金
        self.portfolio.cash -= cost

        # 更新 Position
        position = (
            self.portfolio.get_or_create(sym)
        )
        position.update(q, fill_price)

        # 记录 Fill → 发 FillEvent
        fill = Fill(
            symbol=sym,
            timestamp=self._cur_ts,
            quantity=q,
            price=fill_price,
            commission=commission
        )

        self.bus.publish(
            FillEvent(
                timestamp=self._cur_ts,
                symbol=sym,
                quantity=q,
                price=fill_price,
                commission=commission,
            )
        )

    def _on_fill(self, event: FillEvent):

        # 重建 Fill 对象给 TradeBook
        fill = Fill(
            symbol=event.symbol,
            timestamp=event.timestamp,
            quantity=event.quantity,
            price=event.price,
            commission=event.commission
        )

        self.fills.append(fill)
        self.tradebook.on_fill(fill)

    def _build_orders_from_signals(
        self, scores, timestamp
    ):

        # 跟 BarEngine 一致：
        # 1) portfolio_constructor.construct(scores, ts)
        # 2) execution_model.generate_orders(portfolio, target, bar_open)
        # 3) 发 OrderEvent（每个 order 一个）

        target = (
            self.portfolio_constructor.construct(
                scores, timestamp
            )
        )

        orders = self.execution_model.generate_orders(
            self.portfolio,
            target,
            self._cur_open,
        )

        for o in orders:

            self.bus.publish(
                OrderEvent(
                    timestamp=timestamp,
                    symbol=o.symbol,
                    quantity=o.quantity,
                )
            )

    def _run_legacy(self, data: Dict) -> Dict:

        symbols = list(data.keys())
        first_df = data[symbols[0]]
        n_bars = len(first_df)

        # 初始化 position_qty 跟踪
        for sym in symbols:

            self.position_qty[sym] = []

        # 1) 一次性算全 signal
        ctx = StrategyContext(
            data, factor_cache
        )
        self.signal_df = (
            self.strategy.signal(ctx)
        )

        # 2) 主循环：每根 bar 发 MarketEvent
        for i in range(n_bars):

            payload = {
                "i": i,
                "symbols": symbols,
                "data": data,
                "bar_open": {
                    sym: data[sym].iloc[i]["open"]
                    for sym in symbols
                },
                "bar_close": {
                    sym: data[sym].iloc[i]["close"]
                    for sym in symbols
                },
                "timestamp": first_df.index[i],
            }

            # 发 MarketEvent
            # 订阅者：_on_market
            # 内部会发出 SignalEvent
            self.bus.publish(
                MarketEvent(
                    timestamp=first_df.index[i],
                    payload=payload
                )
            )

            # i>=1: 用 signal → portfolio_constructor
            #       → execution → 发 OrderEvent
            if i > 0:

                prev_scores = (
                    self.signal_df
                    .iloc[i - 1]
                    .to_dict()
                )

                # NaN 信号契约：全 NaN 表示"不操作，继续持有"
                # （与 BarEngine / VectorBTAdapter 保持一致）
                # 若不加此判断，TopN 会把 NaN 视为不达标 → 返回空 weights
                # → matcher 把所有持仓按 target_w=0 卖光 → 每天清仓
                valid_scores = [
                    v for v in prev_scores.values()
                    if v is not None
                    and not (
                        isinstance(v, float)
                        and pd.isna(v)
                    )
                ]
                if not valid_scores:
                    # 全 NaN → 不调仓，仓位继续持有
                    # 权益 record 和 position_qty 在循环末尾统一处理
                    pass
                else:
                    self._build_orders_from_signals(
                        prev_scores,
                        first_df.index[i],
                    )

            # 收尾：每根 bar 收盘记一次权益
            # （与 BarEngine 一致：每根 bar 收完单后 record）
            if i > 0 or i == 0:

                # 实际上 BarEngine 在 i=0 就 record
                # 之后每根 bar record 一次
                # 我们让 _on_market 内部 i=0 record 一次
                # 然后每根 bar 在这里 record
                pass

            if i > 0:

                self.portfolio.record(
                    first_df.index[i],
                    payload["bar_close"],
                )

            # 每根 bar 结束记录每个 symbol 的 qty
            for sym in symbols:

                self.position_qty[sym].append(
                    self.portfolio
                    .get_or_create(sym)
                    .qty
                )

        # 3) 重建 closed_trades
        self.tradebook.rebuild()

        return {
            "portfolio": self.portfolio,
            "fills": self.fills,
            "tradebook": self.tradebook,
            "position_qty": self.position_qty,
            "signal": self.signal_df,
        }
