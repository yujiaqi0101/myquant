"""
src/core/engine/__init__.py
===========================

引擎实现模块包导出。

三种引擎共享 Strategy 基类和核心数据结构，通过依赖注入切换 DataFeed/Execution/持久化：
    - BacktestEngine: 回测（HistoricalDataFeed + SimulatedExecution + 内存）
    - PaperEngine:    模拟盘（LiveDataFeed + SimulatedExecution + DB 持久化）
    - LiveEngine:     实盘（LiveDataFeed + LiveExecution + DB + 券商）

阶段5（设计文档第 7.2 节）实现三种引擎与对应 Context。
"""

from src.core.engine.backtest import BacktestContext, BacktestEngine
from src.core.engine.paper import PaperContext, PaperEngine
from src.core.engine.live import LiveContext, LiveEngine

__all__ = [
    "BacktestContext",
    "BacktestEngine",
    "PaperContext",
    "PaperEngine",
    "LiveContext",
    "LiveEngine",
]
