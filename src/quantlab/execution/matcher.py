"""
Matcher：撮合器
把 TargetPortfolio 转成 Order 列表
不做：现金检查 / 滑点 / Fill 记录（BarEngine 处理）
"""

from typing import Dict, List

from ..portfolio_construction.target_portfolio import (
    TargetPortfolio,
)

from .order import Order


class TargetWeightExecution:

    def __init__(
        self,

        lot_size=1,

        position_tolerance=0.02
    ):

        self.lot_size = lot_size

        self.position_tolerance = (
            position_tolerance
        )

    def generate_orders(
        self,
        portfolio,
        target_portfolio: TargetPortfolio,
        prices: Dict[str, float]
    ) -> List[Order]:

        orders = []

        total_equity = portfolio.equity()

        # 出现在 target 或当前持仓的 symbol 都要处理
        all_symbols = (
            set(target_portfolio.weights.keys())
            | set(portfolio.positions.keys())
        )

        for sym in all_symbols:

            target_w = (
                target_portfolio
                .weights
                .get(sym, 0.0)
            )

            if sym not in prices:

                # 没价格 → 跳过（不调仓）
                continue

            price = prices[sym]

            target_value = total_equity * target_w

            position = (
                portfolio
                .positions
                .get(sym)
            )
            current_value = (
                position.qty * price
                if position is not None
                else 0.0
            )

            target_qty = target_value / price

            current_qty = current_value / price

            # 容忍度过滤：调仓比例太小就跳过
            ref = max(abs(target_qty), 1)

            if (

                abs(target_qty - current_qty)
                / ref
                < self.position_tolerance
            ):

                continue

            delta_value = target_value - current_value

            raw_qty = int(delta_value / price)

            # 取整到 lot_size
            qty = (
                raw_qty
                // self.lot_size
            ) * self.lot_size

            if qty != 0:

                orders.append(
                    Order(
                        symbol=sym,
                        quantity=qty
                    )
                )

        return orders
