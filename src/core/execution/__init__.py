"""
src/core/execution/__init__.py
==============================

执行层抽象包初始化模块。

统一导出 Execution 抽象基类及其两个实现：
    - SimulatedExecution：回测/模拟盘内存撮合
    - LiveExecution：实盘券商真实下单

设计文档第 4.2 节：Execution 是订单撮合的统一抽象，接收风控管线通过后的订单，
按价格类型（market/limit/next_open/target_percent）撮合或转发，并计算A股交易费用，
通过 EventEngine 推送 OrderEvent 和 TradeEvent。

用法：
    from src.core.execution import Execution, SimulatedExecution, LiveExecution
"""

from src.core.execution.base import Execution
from src.core.execution.live import LiveExecution
from src.core.execution.simulated import SimulatedExecution

__all__ = ["Execution", "SimulatedExecution", "LiveExecution"]
