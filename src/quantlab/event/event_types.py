"""
事件类型
所有事件都基于这个基类
未来加新事件：
   BarEvent / TickEvent / NewsEvent / ...
"""

from dataclasses import (
    dataclass,
    field,
)
from typing import Any


@dataclass(slots=True)
class Event:

    type: str

    timestamp: object = None

    payload: Any = None


# ----------------------------------------------------------------
# MarketEvent：市场行情
# V1 暂用 Bar 行情
# 未来 Tick 行情：
#   MarketEvent(type="TICK", payload={symbol, price, volume})
# 策略不需要改：监听 MarketEvent 即可
# ----------------------------------------------------------------


@dataclass(slots=True)
class MarketEvent(Event):

    type: str = "MARKET"

    symbol: str = ""

    data: Any = None


# ----------------------------------------------------------------
# SignalEvent：策略信号
# 策略监听 MarketEvent
# 产出 SignalEvent（direction/score）
# ----------------------------------------------------------------


@dataclass(slots=True)
class SignalEvent(Event):

    type: str = "SIGNAL"

    symbol: str = ""

    direction: int = 0

    score: float = 0.0


# ----------------------------------------------------------------
# OrderEvent：下单
# 组合构建器监听 SignalEvent
# 产出 OrderEvent（symbol, quantity）
# ----------------------------------------------------------------


@dataclass(slots=True)
class OrderEvent(Event):

    type: str = "ORDER"

    symbol: str = ""

    quantity: int = 0


# ----------------------------------------------------------------
# FillEvent：成交
# 撮合器监听 OrderEvent
# 撮合成功产出 FillEvent
# 仓位/资金监听 FillEvent 更新
# ----------------------------------------------------------------


@dataclass(slots=True)
class FillEvent(Event):

    type: str = "FILL"

    symbol: str = ""

    quantity: int = 0

    price: float = 0.0

    commission: float = 0.0


EVENT_TYPES = (
    MarketEvent,
    SignalEvent,
    OrderEvent,
    FillEvent,
)
