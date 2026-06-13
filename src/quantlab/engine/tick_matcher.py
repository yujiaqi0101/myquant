"""
V2.4 TickEngine — TickMatcher

Tick 级撮合：
  - 输入：Order + Tick
  - 输出：Fill 或 None

V1 简化：
  - 不做盘口
  - 不做部分成交
  - 限价单：tick.last_price 触及 limit_price 即成交
  - 市价单：当前 tick 立即成交
  - target weight 类 order（V1 主力）：
      quantity > 0 → 视为市价买单
      quantity < 0 → 视为市价卖单
      用 tick.last_price + TickSlippage 成交

V2 增强（不做）：
  - bid/ask 撮合
  - 撮合队列
  - 部分成交
  - 委托排队
"""


from typing import Optional

from ..core.tick import Tick
from ..core.fill import Fill
from ..core.order import Order
from ..execution.tick_slippage import (
    TickSlippage,
)


class TickMatcher:

    # V1：last price tick 撮合
    #
    # 流程：
    #   1) 拿 order 想要的成交价
    #      V1 简化为 tick.last_price
    #   2) 应用 TickSlippage
    #   3) 构造 Fill

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

    def match(
        self,
        order: Order,
        tick: Tick,
    ) -> Optional[Fill]:

        # 撮合一次
        #
        # V1 简化：
        #   不管 order 有没有 limit price
        #   都按 tick.last_price 成交
        #
        # V2 增强：
        #   order.limit_price 限价
        #   tick.last_price 触发判断

        if order.quantity == 0:
            return None

        # 应用滑点
        if order.quantity > 0:
            side = "BUY"
        else:
            side = "SELL"

        fill_price = (
            self.slippage.apply(
                tick.last_price, side
            )
        )

        # 成交额
        notional = (
            abs(order.quantity)
            * fill_price
        )

        # 佣金
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


class TickPendingOrders:

    # Pending Orders
    # V1 简化版
    #
    # 流程：
    #   1) submit(order) 加入队列
    #   2) match(tick) 尝试撮合
    #      撮合成功的从队列移出
    #      未撮合的保留
    #
    # V1 不做：
    #   - 限价单撮合判定
    #   - 部分成交
    #   - 撤单
    #   - 过期

    def __init__(
        self,
        matcher: TickMatcher = None,
    ):

        self.matcher = (
            matcher or TickMatcher()
        )

        self._orders = []

    def submit(self, order: Order):

        self._orders.append(order)

    def match(
        self, tick: Tick
    ) -> list:

        # 尝试撮合所有 pending
        # 返回 Fill 列表
        fills = []

        remaining = []

        for order in self._orders:

            fill = self.matcher.match(
                order, tick
            )

            if fill is None:
                # 保留
                remaining.append(order)
            else:
                fills.append(fill)

        self._orders = remaining

        return fills

    def __len__(self):

        return len(self._orders)
