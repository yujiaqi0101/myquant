"""
通用回测引擎

提供灵活的、可扩展的量化回测框架，支持：
- 所有策略在同一框架下运行
- 买卖逻辑完全由策略决定
- 引擎级出场检查（止损/止盈/ATR动态止盈/超时）
- 完整的每日账户记录（支持逐日检查）
- CLI策略选择和结果管理

示例：
    from src.engine import BaseStrategy, BacktestEngine, register_strategy
    from src.engine.types import Order, Direction
    
    @register_strategy
    class MyStrategy(BaseStrategy):
        name = "my_strategy"
        description = "我的策略"
        
        def on_init(self, context):
            # 预计算指标
            pass
        
        def on_bar(self, context):
            # 返回订单列表
            return []
    
    # 运行回测
    engine = BacktestEngine(strategy=MyStrategy())
    result = engine.run(price_data)
"""

from .types import (
    Order, TradeRecord, Position, DailySnapshot,
    BacktestResult, Context, Direction, OrderType
)
from .base_strategy import BaseStrategy, StrategyRegistry, register_strategy
from .exit_checker import ExitChecker, ExitCheckResult
from .backtest_engine import BacktestEngine

__all__ = [
    # 数据类型
    'Order', 'TradeRecord', 'Position', 'DailySnapshot',
    'BacktestResult', 'Context', 'Direction', 'OrderType',
    # 策略基类
    'BaseStrategy', 'StrategyRegistry', 'register_strategy',
    # 出场检查
    'ExitChecker', 'ExitCheckResult',
    # 回测引擎
    'BacktestEngine',
]
