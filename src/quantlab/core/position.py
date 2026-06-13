"""
Position：单个标的持仓
Portfolio 按 symbol 持有 Position
Position 记录 qty + avg_price + realized_pnl
"""

from dataclasses import (
    dataclass,
    field,
)


@dataclass(slots=True)
class Position:

    symbol: str

    qty: int = 0

    avg_price: float = 0.0

    realized_pnl: float = 0.0

    def update(
        self,
        qty_change: int,
        price: float
    ):

        if qty_change == 0:
            return

        # 空仓

        if self.qty == 0:

            self.qty = qty_change
            self.avg_price = price

            return

        # 同方向

        if self.qty * qty_change > 0:

            total_qty = (
                abs(self.qty)
                + abs(qty_change)
            )

            self.avg_price = (
                abs(self.qty)
                * self.avg_price
                +
                abs(qty_change)
                * price
            ) / total_qty

            self.qty += qty_change

            return

        # 平仓或反手

        closing_qty = min(
            abs(self.qty),
            abs(qty_change)
        )

        if self.qty > 0:

            pnl = (
                price
                - self.avg_price
            ) * closing_qty

        else:

            pnl = (
                self.avg_price
                - price
            ) * closing_qty

        self.realized_pnl += pnl

        self.qty += qty_change

        if self.qty == 0:

            self.avg_price = 0

        elif abs(qty_change) > closing_qty:

            self.avg_price = price
