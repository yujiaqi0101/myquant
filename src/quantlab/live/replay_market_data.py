"""
V2.5 Live — ReplayMarketData

把历史 Bar/Tick 数据当作行情源
给 LiveEngine / PaperBroker 喂数据

用法：
    md = ReplayMarketData(data)
    md.subscribe(["AAPL", "MSFT"])
    for tick in md.stream():
        broker.push_tick(...)
"""

from typing import (
    Dict,
    Iterator,
    List,
)

from ..core.tick import Tick
from .market_data import MarketDataAdapter


class ReplayMarketData(MarketDataAdapter):
    """
    历史回放行情
    V1 把 Bar 当作 Tick：
        每个 bar.close 推一条 tick
    顺序：按 (timestamp, symbol) 排序
    """

    name = "REPLAY"

    def __init__(self, data: Dict[str, "pd.DataFrame"]):
        self.data = data
        self._subscribed: List[str] = []

    def subscribe(self, symbols: List[str]) -> None:
        for s in symbols:
            if s not in self._subscribed:
                self._subscribed.append(s)

    def unsubscribe(self, symbol: str) -> None:
        if symbol in self._subscribed:
            self._subscribed.remove(symbol)

    def stream(self) -> Iterator[Tick]:
        # 按时间合并多 symbol 的 bar
        events = []
        for sym in self._subscribed:
            df = self.data.get(sym)
            if df is None:
                continue
            for ts, row in df.iterrows():
                events.append((
                    ts,
                    sym,
                    float(row["close"]),
                    int(row.get("volume", 0)),
                ))

        events.sort(key=lambda x: (x[0], x[1]))

        for ts, sym, price, vol in events:
            yield Tick(
                timestamp=ts,
                symbol=sym,
                price=price,
                volume=vol,
            )
