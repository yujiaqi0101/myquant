"""
TradeBook：fill 收集器
on_fill() 收集 fill
rebuild() 把 fills 按 symbol 分组 → TradeBuilder.build → ClosedTrade

V1.9：暴露 closed_trades_by_symbol / pnl_by_symbol
"""


from typing import Dict, List

from .fill import Fill
from .trade import (
    TradeBuilder,
    ClosedTrade
)


class TradeBook:

    # V2: 多标的
    # fills 是混合所有 symbol 的成交流水
    # rebuild() 按 symbol 分组
    # 各自跑 TradeBuilder.build(symbol, fills_of_symbol)
    # 合并得到全部 closed_trades

    def __init__(self):

        self.fills = []

        self.closed_trades: List[ClosedTrade] = []

        # V1.9: 按 symbol 分组的 closed_trades
        # 例：{"AAPL": [trade1, trade2, ...], "MSFT": [...]}
        self.closed_trades_by_symbol: Dict[
            str, List[ClosedTrade]
        ] = {}

    def on_fill(self, fill: Fill):

        self.fills.append(fill)

    def rebuild(self):

        builder = TradeBuilder()

        # 按 symbol 分组 fills
        grouped = {}
        for f in self.fills:

            grouped.setdefault(
                f.symbol,
                []
            ).append(f)

        all_closed = []
        by_symbol: Dict[
            str, List[ClosedTrade]
        ] = {}

        for sym, sym_fills in grouped.items():

            closed = builder.build(
                sym,
                sym_fills
            )
            by_symbol[sym] = closed
            all_closed.extend(closed)

        self.closed_trades = all_closed
        self.closed_trades_by_symbol = by_symbol

    def pnl_by_symbol(self) -> Dict[str, float]:
        # V1.9 新增
        # 统计每个 symbol 的累计已实现盈亏
        # 必须先 rebuild()
        result: Dict[str, float] = {}

        for sym, trades in (
            self.closed_trades_by_symbol.items()
        ):

            result[sym] = sum(
                t.pnl for t in trades
            )

        return result

    def trade_count_by_symbol(
        self
    ) -> Dict[str, int]:
        # 每个 symbol 的平仓笔数
        return {
            sym: len(trades)
            for sym, trades
            in self.closed_trades_by_symbol.items()
        }
