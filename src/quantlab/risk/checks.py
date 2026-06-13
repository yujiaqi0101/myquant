"""
V2.5 Risk — Checks

每个 Check 是一个独立的检查单元
RiskManager 串联多个 Check

V1 内置：
    PositionLimitCheck
    DailyLossCheck
    LeverageCheck
    OrderSizeCheck
"""

from abc import (
    ABC,
    abstractmethod,
)
from typing import (
    Dict,
    List,
)

from ..core.order import Order
from .limits import (
    MaxDailyLoss,
    MaxLeverage,
    MaxOrderSize,
    MaxPositionLimit,
)


class RiskCheck(ABC):

    name: str = "BASE_CHECK"

    @abstractmethod
    def check(
        self,
        order: Order,
        context: Dict,
    ) -> bool:
        # True  = 通过
        # False = 拒单
        ...


class PositionLimitCheck(RiskCheck):

    name = "POSITION_LIMIT"

    def __init__(self, limits: List[MaxPositionLimit]):
        self.limits = {
            lim.symbol: lim for lim in limits
        }

    def check(self, order: Order, context: Dict) -> bool:
        lim = self.limits.get(order.symbol)
        if lim is None:
            return True

        positions = context.get("positions", {})
        current = positions.get(order.symbol, 0)
        new = current + order.quantity
        return lim.check(current, new)


class OrderSizeCheck(RiskCheck):

    name = "ORDER_SIZE"

    def __init__(self, limit: MaxOrderSize):
        self.limit = limit

    def check(self, order: Order, context: Dict) -> bool:
        return self.limit.check(order.quantity)


class DailyLossCheck(RiskCheck):

    name = "DAILY_LOSS"

    def __init__(self, limit: MaxDailyLoss):
        self.limit = limit

    def check(self, order: Order, context: Dict) -> bool:
        return self.limit.check()


class LeverageCheck(RiskCheck):

    name = "LEVERAGE"

    def __init__(self, limit: MaxLeverage):
        self.limit = limit

    def check(self, order: Order, context: Dict) -> bool:
        equity = context.get("equity", 0.0)
        gross = context.get("gross_position_value", 0.0)
        return self.limit.check(equity, gross)
