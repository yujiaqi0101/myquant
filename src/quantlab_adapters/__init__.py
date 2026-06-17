"""
QuantLab 适配器模块
==================

提供策略元数据管理、最佳表现自动提炼等功能。
"""

from .data_adapter import from_quantlab_db, to_quantlab_dict
from .strategy_registry import SignalStrategyRegistry, discover_v2_strategies
from .best_perf_updater import BestPerfUpdater, ensure_best_perf_fresh
from .result_adapter import to_myquant_result
from .tracker_adapter import MyquantTracker

# 兼容旧测试中的 register_signal_strategy 导入
register_signal_strategy = SignalStrategyRegistry.register
