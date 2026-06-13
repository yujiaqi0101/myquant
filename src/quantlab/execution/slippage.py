"""
Slippage：滑点模型
买入多付、卖出少收
按价格固定比例
"""


class PercentageSlippage:

    def __init__(self, rate=0.0002):

        self.rate = rate

    def apply(
        self,
        quantity: int,
        price: float
    ) -> float:

        # 买入多付、卖出少收
        if quantity > 0:

            return price * (1 + self.rate)

        return price * (1 - self.rate)
