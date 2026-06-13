"""
V2.5 Live — LiveEngine

与 BarEngine / TickEngine 的对比：

  BarEngine.run()   for bar in data
  TickEngine.run()  for tick in feed.stream()
  LiveEngine.run()  while True:
                        market_data
                        ↓
                        strategy
                        ↓
                        portfolio_construction
                        ↓
                        execution
                        ↓
                        risk_manager
                        ↓
                        order_manager
                        ↓
                        broker

V1 流程：

  1) while loop:
  2)   tick = market_data.stream() / subscribe 回调
  3)   broker.push_tick(...)
  4)   weights = strategy.signal(ctx)
  5)   target  = TargetPortfolio(weights, ts)
  6)   orders  = execution.generate_orders(...)
  7)   for order in orders:
  8)     if not risk_manager.check(order, ctx): 拒
  9)     else: order_manager.submit(order)
  10)  fills = order_manager.drain_fills()
  11)  for fill in fills: portfolio.apply_fill(...)
  12)  portfolio.record(tick.timestamp, prices)
  13)  kill_switch.update_pnl(daily_pnl)
  14)  if kill_switch.stop: break

不做：
  - 真实多线程 / 异步 I/O
  - broker 长连接维护
  - 心跳检测
"""

from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
)

from ..core.base_engine import BaseBacktestEngine
from ..core.backtest_result import BacktestResult
from ..core.fill import Fill
from ..core.order import Order
from ..core.portfolio import Portfolio
from ..core.tradebook import TradeBook
from ..core.tick import Tick
from ..portfolio_construction.target_portfolio import (
    TargetPortfolio,
)
from .broker import BrokerAdapter
from .market_data import MarketDataAdapter
from .order_manager import (
    OrderManager,
    OrderState,
)
from ..risk.risk_manager import RiskManager
from ..risk.kill_switch import (
    EmergencyStop,
    KillSwitch,
)
from .logger import (
    LiveLogger,
)


class LiveEngine(BaseBacktestEngine):
    """
    V1 Live 回测引擎
    复用：
        - Strategy
        - Execution
        - Portfolio
        - TradeBook
        - RiskManager（新增串联层）
        - OrderManager（新增串联层）
        - BrokerAdapter（新增抽象）
    """

    def __init__(
        self,
        strategy: Any = None,
        execution: Any = None,
        market_data: MarketDataAdapter = None,
        broker: BrokerAdapter = None,
        risk_manager: Optional[RiskManager] = None,
        order_manager: Optional[OrderManager] = None,
        emergency_stop: Optional[EmergencyStop] = None,
        initial_cash: float = 100000.0,
        log_dir: str = "logs",
    ):
        self.strategy = strategy
        self.execution = execution
        self.market_data = market_data
        self.broker = broker
        self.risk_manager = (
            risk_manager or RiskManager()
        )
        self.order_manager = (
            order_manager
            or OrderManager(
                broker
                or self._placeholder_broker()
            )
        )
        self.emergency_stop = (
            emergency_stop
            or EmergencyStop(threshold=-0.05)
        )
        # 把 KillSwitch 串进 risk_manager
        self.risk_manager.add_check(
            KillSwitch(self.emergency_stop)
        )
        self.initial_cash = initial_cash
        self.logger = LiveLogger(log_dir=log_dir)

        # 状态
        self.last_prices: Dict[str, float] = {}
        self.equity_curve: List[float] = []
        self.equity_ts: List[Any] = []
        self._running = False

    # ----------------
    # 主入口
    # ----------------
    def run(
        self,
        strategy: Any = None,
        data: Any = None,
        params: Optional[Dict] = None,
    ) -> BacktestResult:
        """
        入口签名与 BarEngine/TickEngine 一致
        V1 Live 的特殊点：
            - data 仍是 Dict[symbol, DataFrame]
              由 market_data 内部消费
            - 不死循环
              跑一遍 data 即停（冒烟）
              真实 Live 用 while True 外部驱动
        """
        if strategy is not None:
            self.strategy = strategy

        # 连 broker / 订阅
        self.broker.connect()
        if data is not None:
            self.market_data.subscribe(
                list(data.keys())
            )

        portfolio = Portfolio(
            initial_cash=self.initial_cash
        )
        tradebook = TradeBook()
        self.emergency_stop.set_initial_equity(
            self.initial_cash
        )

        self._running = True

        # 主循环
        for tick in self.market_data.stream():

            if not self._running:
                break

            self._on_tick(
                tick, portfolio, tradebook
            )

            # kill switch
            if self.emergency_stop.stop:
                self.logger.error(
                    f"[KILL] daily_pnl="
                    f"{self.emergency_stop.daily_pnl:.2f}"
                )
                break

        self.broker.disconnect()

        return self._build_result(
            portfolio, tradebook
        )

    def stop(self) -> None:
        self._running = False

    # ----------------
    # 内部：每个 tick
    # ----------------
    def _on_tick(
        self,
        tick: Tick,
        portfolio: Portfolio,
        tradebook: TradeBook,
    ) -> None:
        # 1) 把最新价喂 broker
        #    PaperBroker 需要这个来撮合
        if hasattr(self.broker, "push_tick"):
            self.broker.push_tick(
                tick.symbol,
                tick.last_price,
                timestamp=tick.timestamp,
            )

        # 2) 更新本地 last_prices
        self.last_prices[tick.symbol] = (
            tick.last_price
        )

        # 3) 撮合历史挂单
        #    V1 简化：PaperBroker 即时成交
        #    OrderManager 收新单
        #    已成交的不需要再 match

        # 4) 跑策略
        if self.strategy is None:
            return

        weights = self._run_strategy(
            tick.timestamp, self.last_prices
        )
        if not weights:
            return

        # 5) 调仓
        target = TargetPortfolio(
            timestamp=tick.timestamp,
            weights=weights,
        )

        orders = self.execution.generate_orders(
            portfolio=portfolio,
            target_portfolio=target,
            prices=self.last_prices,
        )

        # 6) 风险检查 + 下单
        ctx = {
            "positions": (
                self.broker.get_positions()
                if self.broker
                else {}
            ),
            "equity": (
                self.broker.get_account().equity
                if self.broker
                else self.initial_cash
            ),
            "gross_position_value": sum(
                abs(q) * self.last_prices.get(s, 0.0)
                for s, q in (
                    self.broker.get_positions().items()
                    if self.broker
                    else {}
                )
            ),
        }

        for order in orders:
            self._submit_order(
                order, ctx, tick.timestamp
            )

        # 7) 把 broker 已成的成交倒给 portfolio
        self._drain_fills(
            portfolio, tradebook
        )

        # 8) record
        portfolio.record(
            tick.timestamp, self.last_prices
        )
        self.equity_curve.append(
            portfolio.equity()
        )
        self.equity_ts.append(tick.timestamp)

        # 9) kill switch
        daily_pnl = (
            portfolio.equity() - self.initial_cash
        )
        self.emergency_stop.update_pnl(daily_pnl)

    def _submit_order(
        self,
        order: Order,
        ctx: Dict,
        timestamp: Any,
    ) -> None:
        # 风险检查
        if not self.risk_manager.check(
            order, ctx
        ):
            self.logger.reject(
                symbol=order.symbol,
                qty=order.quantity,
                reason=str(
                    self.risk_manager.rejects[-1]
                ),
            )
            return

        # 下单
        mo = self.order_manager.submit(order)
        if mo is None:
            return

        if mo.state == OrderState.REJECTED:
            self.logger.reject(
                symbol=order.symbol,
                qty=order.quantity,
                reason=mo.reject_reason,
            )
        else:
            self.logger.order(
                local_id=mo.broker_id,
                symbol=order.symbol,
                qty=order.quantity,
                ts=timestamp,
            )

    def _drain_fills(
        self,
        portfolio: Portfolio,
        tradebook: TradeBook,
    ) -> None:
        # V1 简化：PaperBroker 同步成交
        # 直接从 broker.trade_log 拉新成交
        if not hasattr(self.broker, "trade_log"):
            return

        for fill in self.broker.trade_log:
            try:
                portfolio.apply_fill(
                    symbol=fill.symbol,
                    quantity=fill.quantity,
                    price=fill.price,
                    commission=fill.commission,
                    timestamp=fill.timestamp,
                )
            except Exception:
                pass
            try:
                tradebook.record_fill(fill)
            except Exception:
                pass
            self.logger.trade(
                symbol=fill.symbol,
                qty=fill.quantity,
                price=fill.price,
                ts=fill.timestamp,
            )
        # 清空已处理
        self.broker.trade_log.clear()

    # ----------------
    # 策略
    # ----------------
    def _run_strategy(
        self,
        timestamp: Any,
        last_prices: Dict[str, float],
    ) -> Dict[str, float]:
        if self.strategy is None:
            return {}
        try:
            ctx = {
                "timestamp": timestamp,
                "last_prices": last_prices,
            }
            signal = self.strategy.signal(ctx)
            if isinstance(signal, dict):
                return signal
        except Exception:
            pass
        return {}

    # ----------------
    # 占位 broker
    # ----------------
    def _placeholder_broker(self):
        from .broker import BrokerAdapter

        class _NoopBroker(BrokerAdapter):
            name = "NOOP"

            def connect(self):
                pass

            def disconnect(self):
                pass

            def submit_order(self, order):
                return ""

            def cancel_order(self, oid):
                return False

            def get_positions(self):
                return {}

            def get_account(self):
                from .broker import AccountState
                return AccountState()

        return _NoopBroker()

    # ----------------
    # 产出
    # ----------------
    def _build_result(
        self,
        portfolio: Portfolio,
        tradebook: TradeBook,
    ) -> BacktestResult:
        return BacktestResult(
            equity_curve=self.equity_curve,
            total_return=(
                (self.equity_curve[-1]
                 - self.initial_cash)
                / self.initial_cash
                if self.equity_curve
                else 0.0
            ),
            sharpe=0.0,
            max_drawdown=0.0,
            trade_count=len(tradebook.fills)
            if hasattr(tradebook, "fills")
            else 0,
            win_rate=0.0,
            final_equity=(
                self.equity_curve[-1]
                if self.equity_curve
                else self.initial_cash
            ),
            source="live",
            raw={
                "n_ticks": len(self.equity_curve),
                "n_orders": len(self.order_manager),
                "n_rejects": len(
                    self.risk_manager.rejects
                ),
            },
            fills=list(
                tradebook.fills
            ) if hasattr(tradebook, "fills") else [],
            tradebook=tradebook,
            portfolio=portfolio,
            position_qty={
                s: p.qty
                for s, p in portfolio.positions.items()
            },
            signal=None,
            timestamps=self.equity_ts,
        )
