"""
V2.4 TickEngine — Tick 数据类

Tick = 市场微观事件
V1 只用 last price + volume
不做盘口（L2/Bid/Ask）
不做部分成交

注意：
  BarEngine 跑 bar
  TickEngine 跑 tick
  Strategy / Execution / Portfolio / TradeBook
  全部复用
"""


from dataclasses import (
    dataclass,
    field,
)


@dataclass(slots=True)
class Tick:

    # 单条 tick
    #
    # 字段：
    #   timestamp 时间戳
    #   symbol    合约代码
    #   price     最新成交价
    #   volume    成交量
    #
    # 例子：
    #   Tick(
    #       timestamp=...,
    #       symbol="IF2406",
    #       price=3821.4,
    #       volume=12
    #   )

    timestamp: object

    symbol: str

    price: float

    volume: int = 0

    # 可选：用于 OrderBook 扩展
    # V1 不读
    bid: float = 0.0

    ask: float = 0.0

    def __post_init__(self):

        # 防御
        # price < 0 异常
        if self.price < 0:

            raise ValueError(
                f"tick price < 0: "
                f"{self.price} "
                f"({self.symbol})"
            )

    @property
    def last_price(self) -> float:

        # 撮合层用的接口
        return self.price
