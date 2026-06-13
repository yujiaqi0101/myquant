"""
V2.4 TickEngine — TickFeed

统一接口：
  feed.stream() -> Iterable[Tick]

V1 提供：
  - TickFeed         抽象基类
  - BarToTickFeed    把 bar 数据合成 tick
                     默认每个 bar 生成 1 tick
                     用 close 作为 price

不做：
  - L2 行情
  - 真实 tick replay
  - 撮合队列

为什么先做 BarToTickFeed：
  - 沙箱/单元测试友好
  - 跟 BarEngine 共享同一份 bar 数据
  - 后续接真实 tick 数据源
    （CTP / 仿真 / 盘后数据）
    只需新写一个 TickFeed 实现
"""


from typing import (
    Dict,
    Iterable,
    Iterator,
)

import pandas as pd

from ..core.tick import Tick


class TickFeed:

    # 抽象基类
    #
    # 子类必须实现：
    #   stream() -> Iterator[Tick]

    def stream(self) -> Iterator[Tick]:

        raise NotImplementedError

    def __iter__(self) -> Iterator[Tick]:

        return self.stream()


class BarToTickFeed:

    # 把 bar DataFrame 转成 tick 流
    #
    # 简化：
    #   每个 bar 生成 1 tick
    #   tick.price = bar.close
    #   tick.volume = bar.volume
    #
    # 进阶（后续）：
    #   每个 bar 拆 N tick
    #   价格在 OHLC 之间游走
    #   （random walk / linear interp）

    def __init__(
        self,
        data: Dict[str, pd.DataFrame],
        ticks_per_bar: int = 1,
    ):

        self.data = data

        # V1 简化为 1
        # 大于 1 时
        # 在 OHLC 之间 random walk
        self.ticks_per_bar = ticks_per_bar

    def stream(self) -> Iterator[Tick]:

        # 按时间排序
        # 多 symbol 合并
        #
        # 输出顺序：
        #   (ts1, S0) -> (ts1, S1) -> (ts1, S2)
        #   -> (ts2, S0) -> (ts2, S1) -> ...
        #
        # V1 单 symbol 顺序
        # V1 多 symbol 同 ts 顺序出

        for sym, df in self.data.items():

            for ts, row in df.iterrows():

                # 简化：
                # 每个 bar 1 tick
                # price = close
                yield Tick(
                    timestamp=ts,
                    symbol=sym,
                    price=float(row["close"]),
                    volume=int(
                        row.get(
                            "volume", 0
                        )
                    ),
                )


class MultiSymbolBarFeed:

    # 多 symbol 合并 tick 流
    # 按时间排序
    # 同 ts 多 symbol 顺序出
    #
    # 例子：
    #   data = {"AAPL": df, "MSFT": df2}
    #   feed = MultiSymbolBarFeed(data)
    #   for tick in feed.stream():
    #       ...

    def __init__(
        self,
        data: Dict[str, pd.DataFrame],
    ):

        self.data = data

    def stream(self) -> Iterator[Tick]:

        # 先按 symbol 拆
        # 然后按 ts 合并
        for sym, df in self.data.items():

            for ts, row in df.iterrows():

                yield Tick(
                    timestamp=ts,
                    symbol=sym,
                    price=float(
                        row["close"]
                    ),
                    volume=int(
                        row.get(
                            "volume", 0
                        )
                    ),
                )
