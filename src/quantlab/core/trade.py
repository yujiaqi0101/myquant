"""
ClosedTrade + TradeBuilder
FIFO：先进先出
Fills → ClosedTrades
"""


from collections import deque

from dataclasses import (
    dataclass,
)


@dataclass(slots=True)
class ClosedTrade:

    symbol: str

    entry_time: object

    exit_time: object

    qty: int

    entry_price: float

    exit_price: float

    pnl: float

    return_pct: float


class TradeBuilder:

    # FIFO：先进先出
    # fills -> closed_trades
    # 不依赖任何仓位状态，只看成交序列

    def build(self, symbol, fills):

        closed = []

        # 维护两个 FIFO 队列
        long_lots = deque()

        short_lots = deque()

        for fill in fills:

            q = fill.quantity
            p = fill.price
            t = fill.timestamp

            if q > 0:

                # 买入：先平空头，再开多头
                remaining = q

                while (

                    remaining > 0
                    and short_lots
                ):

                    head = short_lots[0]
                    consume = min(
                        remaining,
                        head["qty"]
                    )

                    pnl = (

                        head["price"]
                        - p
                    ) * consume

                    return_pct = (

                        (head["price"] - p)
                        / head["price"]
                    )

                    closed.append(
                        ClosedTrade(
                            symbol=symbol,
                            entry_time=(
                                head["time"]
                            ),
                            exit_time=t,
                            qty=consume,
                            entry_price=(
                                head["price"]
                            ),
                            exit_price=p,
                            pnl=pnl,
                            return_pct=return_pct
                        )
                    )

                    remaining -= consume

                    if consume == head["qty"]:

                        short_lots.popleft()

                    else:

                        short_lots[0] = {

                            "qty": (
                                head["qty"]
                                - consume
                            ),
                            "price": (
                                head["price"]
                            ),
                            "time": (
                                head["time"]
                            )
                        }

                if remaining > 0:

                    long_lots.append({

                        "qty": remaining,

                        "price": p,

                        "time": t
                    })

            else:

                # 卖出：先平多头，再开空头
                remaining = -q

                while (

                    remaining > 0
                    and long_lots
                ):

                    head = long_lots[0]
                    consume = min(
                        remaining,
                        head["qty"]
                    )

                    pnl = (

                        p
                        - head["price"]
                    ) * consume

                    return_pct = (

                        (p - head["price"])
                        / head["price"]
                    )

                    closed.append(
                        ClosedTrade(
                            symbol=symbol,
                            entry_time=(
                                head["time"]
                            ),
                            exit_time=t,
                            qty=consume,
                            entry_price=(
                                head["price"]
                            ),
                            exit_price=p,
                            pnl=pnl,
                            return_pct=return_pct
                        )
                    )

                    remaining -= consume

                    if consume == head["qty"]:

                        long_lots.popleft()

                    else:

                        long_lots[0] = {

                            "qty": (
                                head["qty"]
                                - consume
                            ),
                            "price": (
                                head["price"]
                            ),
                            "time": (
                                head["time"]
                            )
                        }

                if remaining > 0:

                    short_lots.append({

                        "qty": remaining,

                        "price": p,

                        "time": t
                    })

        return closed
