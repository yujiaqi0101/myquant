"""
V2.5 Risk — Limits

V1 限额的"数据类"
RiskCheck 用这些对象判断是否超限

不做：
    - 动态限额
    - 跨账户 / 跨策略
    - 监管层限额
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class MaxPositionLimit:
    """
    单 symbol 最大持仓（绝对量）
    例：
        MaxPositionLimit(symbol="AAPL", max_qty=1000)
    """

    symbol: str
    max_qty: int

    def check(self, current_qty: int, new_qty: int) -> bool:
        return abs(new_qty) <= self.max_qty


@dataclass
class MaxDailyLoss:
    """
    当日最大亏损限额
    触发后：
        - 拒掉新单
        - Kill Switch 接管
    """

    max_loss: float  # 负数
    current_pnl: float = 0.0

    def check(self) -> bool:
        return self.current_pnl >= self.max_loss

    def update(self, pnl_change: float) -> None:
        self.current_pnl += pnl_change


@dataclass
class MaxLeverage:
    """
    最大杠杆
    abs(position_value) / equity <= max_leverage
    """

    max_leverage: float

    def check(
        self,
        equity: float,
        gross_position_value: float,
    ) -> bool:
        if equity <= 0:
            return False
        return (
            abs(gross_position_value) / equity
            <= self.max_leverage
        )


@dataclass
class MaxOrderSize:
    """
    单笔最大下单量
    """

    max_qty: int

    def check(self, qty: int) -> bool:
        return abs(qty) <= self.max_qty
