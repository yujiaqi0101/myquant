"""
Event Bus
把 BarEngine 从"直接调用"
改成"事件驱动"
这是接 TickEngine / 实时行情的关键

事件流：
MarketEvent
   ↓
SignalEvent
   ↓
OrderEvent
   ↓
FillEvent
"""

from .event_types import (
    MarketEvent,
    SignalEvent,
    OrderEvent,
    FillEvent,
    EVENT_TYPES,
)

from .event_bus import (
    EventBus,
    event_bus,
)


__all__ = [
    "MarketEvent",
    "SignalEvent",
    "OrderEvent",
    "FillEvent",
    "EVENT_TYPES",
    "EventBus",
    "event_bus",
]
