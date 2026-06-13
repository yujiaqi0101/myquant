"""
quantlab_adapters — myquant ↔ quantlab 适配层。

Phase 4: 引擎切换基础设施。
    - DataAdapter   myquant MultiIndex DataFrame → quantlab Dict[symbol, DataFrame]
    - ResultAdapter quantlab BacktestResult → myquant BacktestResult
    - registry      SignalStrategy 自己的策略注册表（v2 策略）

Phase 6: 实验跟踪桥接。
    - tracker_adapter  MyquantTracker 把 quantlab 实验写入 myquant aquant.db
"""

from .data_adapter import (
    to_quantlab_dict,
    from_quantlab_db,
)
from .result_adapter import (
    to_myquant_result,
)
from .strategy_registry import (
    SignalStrategyRegistry,
    register_signal_strategy,
    discover_v2_strategies,
)
from .tracker_adapter import (
    MyquantTracker,
)


__all__ = [
    # DataAdapter
    "to_quantlab_dict",
    "from_quantlab_db",
    # ResultAdapter
    "to_myquant_result",
    # SignalStrategy 注册表
    "SignalStrategyRegistry",
    "register_signal_strategy",
    "discover_v2_strategies",
    # Phase 6 桥接
    "MyquantTracker",
]
