"""
Order：Execution 输出
撮合器把 TargetPortfolio 转成 Order 列表
由 BarEngine 统一执行
quantity > 0 → 买入
quantity < 0 → 卖出
"""

from dataclasses import (
    dataclass,
)


@dataclass(slots=True)
class Order:

    symbol: str

    quantity: int
