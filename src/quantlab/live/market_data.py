"""
V2.5 Live — MarketDataAdapter

统一行情接口
V1 只做 last price tick
不做 L2 盘口

V1 接口：
    subscribe(symbols)
    unsubscribe(symbol)
    stream() -> Iterator[Tick]
    on_tick(callback)
"""

from abc import (
    ABC,
    abstractmethod,
)
from typing import (
    Callable,
    Iterator,
    List,
)

from ..core.tick import Tick


class MarketDataAdapter(ABC):
    """
    所有行情源都实现这个 ABC
    例如：
        BinanceWS
        IBKRMarketData
        TushareRealtime
        CTP_md
    """

    name: str = "BASE_MD"

    @abstractmethod
    def subscribe(self, symbols: List[str]) -> None:
        ...

    @abstractmethod
    def unsubscribe(self, symbol: str) -> None:
        ...

    @abstractmethod
    def stream(self) -> Iterator[Tick]:
        ...

    def on_tick(self, callback: Callable) -> None:
        self._tick_callback = callback
