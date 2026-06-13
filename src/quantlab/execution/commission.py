"""
Commission：佣金模型
按成交金额的固定比例收取
"""


class PercentageCommission:

    def __init__(self, rate=0.0003):

        self.rate = rate

    def calculate(
        self,
        quantity: int,
        price: float
    ) -> float:

        return abs(quantity) * price * self.rate
