"""
src/core/__init__.py
====================

引擎统一重构 - 核心数据结构与接口包。

本包是新版统一引擎的内核，取代旧的 src/engine/、src/quantlab/、src/paper_trading/ 三套并行结构。
设计文档详见 docs/plans/引擎统一重构设计文档.md。

已实现阶段：
    - 阶段1：types/events/strategy/context/event_engine（核心数据结构与接口）
    - 阶段2：datafeed/execution（数据流与执行层抽象）
    - 阶段3：risk + risk_checks（风控管线）
    - 阶段4：portfolio/result/persistence（持仓管理与持久化）
    - 阶段5：engine（Backtest/Paper/Live 三种引擎）

模块清单：
    - types.py          统一数据结构（Order/Fill/Trade/Position + 4个枚举）
    - events.py         事件类型定义（EventType枚举 + Event基类 + 8个具体事件类）
    - strategy.py       Strategy 抽象基类 + 注册表 + 自动发现
    - context.py        Context 策略上下文抽象基类（7大职责）
    - event_engine.py   EventEngine 事件总线（支持 backtest/paper/live 三模式）
    - portfolio.py      Portfolio 持仓管理状态机（现金/持仓/成交/FIFO配对）
    - result.py         BacktestResult + 22项绩效指标 + BenchmarkProvider
    - persistence/      模拟盘/实盘持久化（account_* 5张表）
    - engine/           三种引擎（Backtest/Paper/Live）+ 对应 Context

为避免循环导入，本 __init__.py 只做轻量导出，需要时直接从子模块导入。
"""

# 导出最常用的符号，保持导入路径稳定
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
# 阶段4：持仓管理与绩效
from src.core.portfolio import AccountInfo, Portfolio
from src.core.result import (
    BacktestResult,
    BenchmarkProvider,
    PerformanceCalculator,
)
from src.core.persistence import PersistenceRepository
# 阶段5：三种引擎
from src.core.engine import (
    BacktestContext,
    BacktestEngine,
    LiveContext,
    LiveEngine,
    PaperContext,
    PaperEngine,
)

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
    # portfolio & result
    "AccountInfo",
    "Portfolio",
    "BacktestResult",
    "BenchmarkProvider",
    "PerformanceCalculator",
    "PersistenceRepository",
    # engine
    "BacktestContext",
    "BacktestEngine",
    "PaperContext",
    "PaperEngine",
    "LiveContext",
    "LiveEngine",
]
