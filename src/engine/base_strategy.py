"""
通用回测引擎 - 策略基类和策略注册表

定义了策略的标准接口和自动发现机制：
- BaseStrategy: 策略抽象基类，所有策略必须继承
- StrategyRegistry: 策略注册表，用于CLI发现和加载策略
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import inspect


class BaseStrategy(ABC):
    """
    策略基类 - 所有策略必须继承此类
    
    用户只需实现 on_init 和 on_bar 两个方法即可运行回测。
    
    支持的可配置参数（通过CLI或构造函数传入）：
    - stop_loss: float = 0.07           # 止损比例
    - take_profit: float = 0.20         # 止盈比例  
    - trailing_stop: int = 3            # 动态止盈均线窗口
    - max_holding_days: int = 20        # 最大持仓天数
    - position_size: float = 0.10       # 单次开仓资金比例
    - commission_rate: float = 0.0003   # 佣金费率
    - slippage: float = 0.0001          # 滑点
    
    框架保证调用顺序：on_init -> [on_bar 循环] -> on_stop
    """

    # 策略名称（用于CLI选择和报告）
    name: str = ""
    
    # 策略描述
    description: str = ""
    
    # 默认参数（子类覆盖）
    default_params: Dict[str, Any] = {
        'stop_loss': 0.07,
        'take_profit': 0.20,
        'trailing_stop': 3,
        'max_holding_days': 20,
        'position_size': 0.10,
        'max_positions': 30,  # 最大持仓数量
        'commission_rate': 0.0003,
        'slippage': 0.0001,
    }

    def __init__(self, **kwargs):
        """
        初始化策略
        
        参数优先级：kwargs > default_params
        """
        # 合并默认参数和用户传入参数
        self.params = {**self.default_params, **kwargs}
        
        # 运行时状态（策略可自由使用）
        self.state: Dict[str, Any] = {}

    @classmethod
    def get_param_schema(cls) -> Dict[str, Dict]:
        """
        获取参数模式（用于CLI参数解析和验证）
        
        Returns
        -------
        Dict[str, Dict]
            参数名 -> {type, default, description, min, max}
        """
        schema = {}
        for name, default in cls.default_params.items():
            param_type = type(default).__name__
            schema[name] = {
                'type': param_type,
                'default': default,
                'description': cls._get_param_description(name),
            }
            # 添加数值范围限制
            if 'loss' in name or 'profit' in name or 'size' in name or 'rate' in name or 'slippage' in name:
                schema[name]['min'] = 0.0
                schema[name]['max'] = 1.0
            elif 'days' in name or 'window' in name or 'stop' in name:
                schema[name]['min'] = 1
                schema[name]['max'] = 252
        return schema
    
    @classmethod
    def _get_param_description(cls, name: str) -> str:
        """获取参数描述"""
        descriptions = {
            'stop_loss': '止损比例，如0.07表示亏损7%止损',
            'take_profit': '止盈比例，如0.20表示盈利20%止盈',
            'trailing_stop': '动态止盈均线窗口，如3表示跌破3日均线止盈',
            'max_holding_days': '最大持仓天数，超时强制平仓',
            'position_size': '单次开仓资金比例，如0.10表示使用10%资金',
            'commission_rate': '佣金费率，如0.0003表示万三',
            'slippage': '滑点比例，如0.0001表示万分之一',
        }
        return descriptions.get(name, f'参数 {name}')

    @abstractmethod
    def on_init(self, context: 'Context'):
        """
        策略初始化（回测开始前调用一次）
        
        用途：预计算指标、初始化状态、加载因子数据等
        
        Parameters
        ----------
        context : Context
            策略上下文，包含 params 和 full_data（含预热期的完整数据）
        """
        ...

    @abstractmethod
    def on_bar(self, context: 'Context') -> List['Order']:
        """
        每个交易日调用，返回订单列表
        
        这是策略的核心方法。框架传入当日市场数据和账户状态，
        策略返回想要执行的订单列表（可以为空）。
        
        买卖逻辑完全由策略决定：
        - 可以是【买入基于因子，卖出基于策略】
        - 可以是【买入基于策略，卖出基于因子】
        - 可以是任何其他组合
        
        Parameters
        ----------
        context : Context
            当日上下文，包含 market_data, positions, cash, history 等
            
        Returns
        -------
        List[Order]
            当日要执行的订单列表（买入或卖出）
        """
        ...

    # ---- 以下为可选方法（有默认空实现）----

    def on_start(self, context: 'Context'):
        """回测开始时调用（on_init 之后）"""
        pass

    def on_stop(self, context: 'Context'):
        """回测结束时调用"""
        pass

    def on_order_filled(self, context: 'Context', trade: 'TradeRecord'):
        """订单成交回调"""
        pass

    def on_order_rejected(self, context: 'Context', order: 'Order', reason: str):
        """订单被拒绝回调（如资金不足）"""
        pass
    
    def on_exit_triggered(self, context: 'Context', position: 'Position', reason: str) -> Optional['Order']:
        """
        出场触发回调（当引擎级出场规则触发时）
        
        策略可在此回调中决定是否接受引擎的出场建议，
        或返回一个新的出场订单。
        
        Parameters
        ----------
        context : Context
        position : Position
            触发出场的持仓
        reason : str
            出场原因（如"止损：亏损 -7.00%"）
            
        Returns
        -------
        Optional[Order]
            返回出场订单则执行，返回 None 则忽略此次出场
        """
        return None  # 默认接受引擎建议


# ---- 策略注册表 ----

class StrategyRegistry:
    """策略注册表 - 用于CLI发现和加载策略"""
    
    _strategies: Dict[str, type] = {}
    
    @classmethod
    def register(cls, strategy_class: type):
        """注册策略"""
        if not issubclass(strategy_class, BaseStrategy):
            raise ValueError(f"策略必须继承 BaseStrategy: {strategy_class}")
        
        name = strategy_class.name or strategy_class.__name__
        cls._strategies[name] = strategy_class
        return strategy_class
    
    @classmethod
    def get(cls, name: str) -> Optional[type]:
        """获取策略类"""
        return cls._strategies.get(name)
    
    @classmethod
    def list_strategies(cls) -> List[Dict]:
        """列出所有已注册策略"""
        return [
            {
                'name': name,
                'class': strategy_class.__name__,
                'description': strategy_class.description or '',
                'params': list(strategy_class.default_params.keys()),
            }
            for name, strategy_class in cls._strategies.items()
        ]
    
    @classmethod
    def auto_discover(cls, package_path: str = 'src.strategies'):
        """自动发现策略目录下的所有策略"""
        import importlib
        import pkgutil
        
        try:
            package = importlib.import_module(package_path)
            for _, name, is_pkg in pkgutil.iter_modules(package.__path__):
                if not is_pkg and not name.startswith('_'):
                    try:
                        module = importlib.import_module(f"{package_path}.{name}")
                        # 模块导入时会自动执行 @StrategyRegistry.register 装饰器
                    except Exception as e:
                        print(f"加载策略模块 {name} 失败: {e}")
        except ImportError as e:
            print(f"导入策略包 {package_path} 失败: {e}")


# 装饰器语法糖
register_strategy = StrategyRegistry.register
