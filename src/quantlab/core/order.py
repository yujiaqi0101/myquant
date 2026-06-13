"""
Order：下单
撮合器生成 Order 列表
由 BarEngine 统一执行 → 产生 Fill

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
