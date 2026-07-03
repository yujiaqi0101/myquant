"""
src/core/__init__.py
====================

引擎统一重构 - 核心数据结构与接口包。

本包是新版统一引擎的内核，取代旧的 src/engine/、src/quantlab/、src/paper_trading/ 三套并行结构。
设计文档详见 docs/plans/引擎统一重构设计文档.md。

阶段1仅包含核心抽象（数据结构、事件、策略基类、上下文、事件总线）：
    - types.py          统一数据结构（Order/Fill/Trade/Position + 4个枚举）
    - events.py         事件类型定义（EventType枚举 + Event基类 + 8个具体事件类）
    - strategy.py       Strategy 抽象基类 + 注册表 + 自动发现
    - context.py        Context 策略上下文抽象基类（7大职责）
    - event_engine.py   EventEngine 事件总线（支持 backtest/paper/live 三模式）

后续阶段（datafeed/execution/risk/portfolio/engine 等）将以本包为基础增量实现。
为避免循环导入，本 __init__.py 只做轻量导出，需要时直接从子模块导入。
"""

# 仅导出阶段1最常用的符号，保持导入路径稳定
from src.core.types import (
    Direction,
    OpenClose,
    Order,
    OrderStatus,
    Fill,
    Position,
    PositionDirection,
    Trade,
)
from src.core.events import (
    AccountEvent,
    BarEvent,
    Event,
    EventType,
    InitEvent,
    OrderEvent,
    StopEvent,
    TickEvent,
    TimerEvent,
    TradeEvent,
)
from src.core.strategy import (
    Strategy,
    auto_discover,
    get_strategy_class,
    list_strategies,
    register_strategy,
)
from src.core.context import Context
from src.core.event_engine import EventEngine

__all__ = [
    # types
    "Direction",
    "OpenClose",
    "Order",
    "OrderStatus",
    "Fill",
    "Position",
    "PositionDirection",
    "Trade",
    # events
    "AccountEvent",
    "BarEvent",
    "Event",
    "EventType",
    "InitEvent",
    "OrderEvent",
    "StopEvent",
    "TickEvent",
    "TimerEvent",
    "TradeEvent",
    # strategy
    "Strategy",
    "auto_discover",
    "get_strategy_class",
    "list_strategies",
    "register_strategy",
    # context & engine
    "Context",
    "EventEngine",
]
