"""
V2.5 Live — PaperBroker

不接交易所
按实时行情本地模拟成交

价值：
    1) 提前暴露数据缺失 / 时区 / 交易日问题
    2) 验证 OrderManager / RiskManager 闭环
    3) 跑策略的"实盘替身"做冒烟

注意：
    PaperBroker 不是撮合引擎
    它只是按 last_price 即时成交
    不做 L2 盘口撮合
"""

from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
)

from ..core.order import Order
from ..core.fill import Fill
from .broker import (
    AccountState,
    BrokerAdapter,
)
from .market_data import MarketDataAdapter
from ..execution.tick_slippage import TickSlippage


class PaperBroker(BrokerAdapter):
    """
    本地模拟 broker
    收到 Order 后：
        - 调 market_data 拿最新价
        - 加 0.5 tick 滑点
        - 生成 Fill
        - 调 on_fill 回调
    """

    name = "PAPER"

    def __init__(
        self,
        market_data: MarketDataAdapter,
        tick_size: float = 0.01,
        commission_rate: float = 0.0003,
        initial_cash: float = 100000.0,
    ):
        self.market_data = market_data
        self.slippage = TickSlippage(tick_size=tick_size)
        self.commission_rate = commission_rate
        self.cash = initial_cash
        self.positions: Dict[str, int] = {}
        self.avg_prices: Dict[str, float] = {}
        self._order_seq = 0
        self._last_prices: Dict[str, float] = {}
        self._last_ts: Dict[str, Any] = {}
        self._connected = False
        self._fill_cb: Optional[Callable] = None
        self.trade_log: List[Fill] = []

    # ----------------
    # 连接
    # ----------------
    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    # ----------------
    # 下单
    # ----------------
    def submit_order(self, order: Order) -> str:
        if not self._connected:
            raise RuntimeError("PaperBroker not connected")

        self._order_seq += 1
        broker_id = f"P{self._order_seq:06d}"

        # 拿最新价
        last = self._last_prices.get(
            order.symbol
        )
        if last is None:
            # 兜底：尝试订阅最新
            last = 100.0

        side = "BUY" if order.quantity > 0 else "SELL"
        fill_price = self.slippage.apply(
            last, side
        )

        notional = (
            abs(order.quantity) * fill_price
        )
        commission = (
            notional * self.commission_rate
        )

        fill = Fill(
            symbol=order.symbol,
            timestamp=self._last_ts.get(
                order.symbol
            ),
            quantity=order.quantity,
            price=fill_price,
            commission=commission,
        )

        # 更新本地仓位
        self._apply_fill(fill)
        self.trade_log.append(fill)

        # 触发回调
        if self._fill_cb is not None:
            try:
                self._fill_cb(fill)
            except Exception:
                pass

        return broker_id

    def cancel_order(self, order_id: str) -> bool:
        # V1 Paper: 没撮合队列
        # 已成交无法撤
        return False

    def on_fill(self, callback: Callable) -> None:
        self._fill_cb = callback

    # ----------------
    # 推送行情
    # ----------------
    def push_tick(
        self,
        symbol: str,
        price: float,
        timestamp: Any = None,
    ) -> None:
        # 外部把实时 tick 喂进来
        self._last_prices[symbol] = price
        if timestamp is not None:
            self._last_ts[symbol] = timestamp

    # ----------------
    # 查询
    # ----------------
    def get_positions(self) -> Dict[str, int]:
        return dict(self.positions)

    def get_account(self) -> AccountState:
        market_value = sum(
            self.positions[s]
            * self._last_prices.get(s, 0.0)
            for s in self.positions
        )
        return AccountState(
            cash=self.cash,
            equity=self.cash + market_value,
            margin_used=0.0,
            buying_power=self.cash,
        )

    # ----------------
    # 内部
    # ----------------
    def _apply_fill(self, fill: Fill) -> None:
        prev_qty = self.positions.get(
            fill.symbol, 0
        )
        new_qty = prev_qty + fill.quantity
        self.positions[fill.symbol] = new_qty

        if new_qty == 0:
            self.avg_prices.pop(
                fill.symbol, None
            )
        elif prev_qty == 0 or (
            prev_qty * fill.quantity > 0
        ):
            # 开仓 / 加仓：更新均价
            old_v = (
                abs(prev_qty)
                * self.avg_prices.get(
                    fill.symbol, fill.price
                )
            )
            new_v = (
                abs(fill.quantity) * fill.price
            )
            total = abs(prev_qty) + abs(
                fill.quantity
            )
            self.avg_prices[fill.symbol] = (
                (old_v + new_v) / total
                if total > 0
                else fill.price
            )
        elif new_qty * prev_qty < 0:
            # 反手：均价按新开仓价
            self.avg_prices[fill.symbol] = (
                fill.price
            )

        # 扣现金 + 佣金
        self.cash -= (
            fill.quantity * fill.price
        )
        self.cash -= fill.commission
