"""
Portfolio + TradeBook
Portfolio：多 symbol 持仓 + 现金 + 权益曲线
TradeBook：fill 收集器 → 重建 ClosedTrade
"""

from typing import Dict

from dataclasses import (
    dataclass,
    field,
)

from .position import Position
from .trade import (
    TradeBuilder,
)
from .fill import Fill
from .order import Order


class Portfolio:

    # V2: 多标的
    # position (单) -> positions (Dict[symbol, Position])
    # equity() 接受多 symbol 价格
    # record() 接受多 symbol 价格

    def __init__(
        self,
        initial_cash=100000
    ):

        self.cash = initial_cash

        self.positions: Dict[str, Position] = {}

        # 记录每个 symbol 的最近一次价格
        # 用于 equity() 跨多 symbol 算总市值
        self.last_prices: Dict[str, float] = {}

        self.equity_curve = []

        self.timestamps = []

    def get_or_create(
        self,
        symbol
    ) -> Position:

        if symbol not in self.positions:

            self.positions[symbol] = (
                Position(symbol=symbol)
            )

        return self.positions[symbol]

    def get_position(
        self,
        symbol
    ) -> Position:
        # 拿持仓
        # 没有就返回 None（不创建）
        return self.positions.get(symbol)

    @property
    def symbols(self):
        # 当前持有过的所有 symbol
        return list(self.positions.keys())

    def equity(self):

        # 总权益 = 现金 + 所有 symbol 持仓市值
        # last_prices 由 record() 持续更新
        market_value = sum(

            self.positions[s].qty
            * self.last_prices.get(
                self.positions[s].symbol,
                self.positions[s].avg_price
                or 0
            )

            for s in self.positions
        )

        return (
            self.cash
            +
            market_value
        )

    def record(
        self,
        timestamp,
        prices: Dict[str, float]
    ):

        # 更新每个 symbol 的最近价格
        for sym, p in prices.items():

            self.last_prices[sym] = p

        self.timestamps.append(
            timestamp
        )

        self.equity_curve.append(
            self.equity()
        )
