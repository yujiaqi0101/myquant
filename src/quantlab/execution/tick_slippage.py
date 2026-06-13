"""
V2.4 TickEngine — TickSlippage

Tick 级滑点模型：
  买：成交价 = last_price + 0.5 * tick_size
  卖：成交价 = last_price - 0.5 * tick_size

为什么是 0.5 tick：
  - 实际撮合在 bid/ask 之间
  - 保守估计取中点 + 一半 tick
  - 期货 0.01 / 股票 0.01

跟 PercentageSlippage 的区别：
  - PercentageSlippage 按比例
    （0.0002 = 2 bps）
  - TickSlippage 按 tick_size
    （固定价差）
  - TickEngine 配 TickSlippage
    BarEngine 配 PercentageSlippage
"""


class TickSlippage:

    def __init__(
        self,
        tick_size: float = 0.01,
    ):

        # tick_size
        #   最小价格变动单位
        #   期货 0.01（指数）
        #   期货 1.0（中证 1000）
        #   股票 0.01
        self.tick_size = tick_size

    def apply(
        self,
        price: float,
        side: str,
    ) -> float:

        # 应用滑点
        #
        # side:
        #   "BUY"  → price + 0.5 tick
        #   "SELL" → price - 0.5 tick
        #
        # 返回最终成交价

        half = self.tick_size / 2.0

        if side == "BUY":
            return price + half

        elif side == "SELL":
            return price - half

        return price

    def apply_order(
        self,
        order_price: float,
        order_qty: int,
    ) -> float:

        # 兼容 Order（quantity 正负）
        # 跟 PercentageSlippage 同接口

        if order_qty > 0:
            side = "BUY"
        elif order_qty < 0:
            side = "SELL"
        else:
            return order_price

        return self.apply(
            order_price, side
        )
