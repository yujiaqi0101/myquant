"""
Fill：成交记录
撮合器 + BarEngine 产出
由 TradeBook 收集 → 生成 ClosedTrade
"""

from dataclasses import (
    dataclass,
)


@dataclass(slots=True)
class Fill:

    symbol: str

    timestamp: object

    quantity: int

    price: float

    commission: float
