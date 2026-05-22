"""
策略模块

包含所有可用的交易策略。

使用方式：
    from src.strategies import BreakoutPullbackStrategyV2
    
    strategy = BreakoutPullbackStrategyV2(
        stop_loss=0.07,
        take_profit=0.20,
        consolidation_window=20,
    )
"""

# 自动导入所有策略（触发 @register_strategy 装饰器）
from . import breakout_pullback_v2

# 导出策略
from .breakout_pullback_v2 import BreakoutPullbackStrategyV2

__all__ = [
    'BreakoutPullbackStrategyV2',
]
