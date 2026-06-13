"""
V2.4 TickEngine — IntrabarExecution

核心：把 BarEngine 的"close 成交"换成"tick 价成交"

BarEngine：
  策略 signal → 调仓
  execution.generate_orders() → Order
  engine 用 bar.close 立即成交

TickEngine：
  策略 signal → 调仓（每 tick 都触发）
  execution.generate_orders() → Order
  engine 用 **tick.last_price + TickSlippage** 成交

精度差异：
  Bar：close=102
       突破 100 → 成交 102
  Tick：99 / 99.5 / 100 / 100.1
        突破 100 → 成交 100.05（含滑点）
"""


from ..core.tick import Tick
from ..core.order import Order
from ..core.fill import Fill
from ..execution.tick_slippage import (
    TickSlippage,
)


class IntrabarExecution:

    # V1：
    #   - 接收 Order + Tick
    #   - 用 tick.price 替代 close
    #   - 应用 TickSlippage
    #   - 产 Fill
    #
    # V2（不做）：
    #   - 限价单（带 limit price）
    #   - 盘口撮合
    #   - 部分成交

    def __init__(
        self,
        tick_size: float = 0.01,
        commission_rate: float = 0.0003,
    ):

        self.slippage = TickSlippage(
            tick_size=tick_size
        )

        self.commission_rate = (
            commission_rate
        )

    def execute(
        self,
        order: Order,
        tick: Tick,
    ) -> Fill:

        # 立即以 tick 价格成交
        if order.quantity > 0:
            side = "BUY"
        else:
            side = "SELL"

        fill_price = self.slippage.apply(
            tick.last_price, side
        )

        notional = (
            abs(order.quantity)
            * fill_price
        )

        commission = (
            notional
            * self.commission_rate
        )

        return Fill(
            symbol=order.symbol,
            timestamp=tick.timestamp,
            quantity=order.quantity,
            price=fill_price,
            commission=commission,
        )
