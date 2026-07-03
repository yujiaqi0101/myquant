"""
src/core/strategy.py
====================

策略抽象基类与注册表模块。

本模块定义新版统一引擎的策略接口：
    - _STRATEGY_REGISTRY 全局注册表
    - register_strategy(name) 装饰器：注册策略类
    - get_strategy_class(name) 函数：按名取策略类
    - list_strategies() 函数：列出已注册策略名
    - auto_discover(package_path) 函数：扫描 src/strategies/ 下子目录自动导入触发注册
    - Strategy ABC 抽象基类：3 个生命周期回调

设计要点（设计文档 3.2 节）：
    1. 策略只通过 context 与引擎交互，不直接访问引擎内部
    2. 策略不感知运行模式（回测/模拟盘/实盘），context 由引擎注入
    3. 策略通过 context.submit_order() 主动下单，不返回订单列表
    4. 统一 on_event(event, context) 入口，通过 event.type 分发

策略生命周期：
    on_init(context)              → 初始化（订阅数据、设置定时器、预计算）
    on_event(event, context) × N  → 处理事件（BAR/TICK/ORDER/TRADE/TIMER/ACCOUNT）
    on_stop(context)              → 结束清理

新版本控制已彻底删除（设计文档 6.4 节），策略目录结构：
    src/strategies/<策略名>/<策略名>.py
"""

import importlib
import pkgutil
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Type

from src.core.context import Context
from src.core.events import Event


# ---------------------------------------------------------------------------
# 全局注册表
# ---------------------------------------------------------------------------

# 策略名 → 策略类 的全局映射。模块级单例，进程内共享。
# 装饰器 @register_strategy 在策略类定义时写入，auto_discover 触发导入后即可查询。
_STRATEGY_REGISTRY: Dict[str, Type["Strategy"]] = {}


def register_strategy(name: str):
    """策略注册装饰器。

    将策略类注册到全局注册表。策略类的 name 属性应与注册名一致。

    用法：
        @register_strategy("small_cap")
        class SmallCapStrategy(Strategy):
            name = "small_cap"
            ...

    Args:
        name: 策略名（唯一标识，用于 CLI --strategy 参数）

    Returns:
        装饰器函数

    Raises:
        ValueError: 策略名已注册（重复注册禁止）
    """

    def decorator(cls: Type["Strategy"]) -> Type["Strategy"]:
        # 校验：必须是 Strategy 子类
        if not issubclass(cls, Strategy):
            raise TypeError(f"@register_strategy 只能用于 Strategy 子类，收到 {cls}")
        # 校验：策略名唯一
        if name in _STRATEGY_REGISTRY:
            existing = _STRATEGY_REGISTRY[name]
            raise ValueError(
                f"策略名 '{name}' 已被 {existing.__module__}.{existing.__name__} 注册，"
                f"不允许重复注册"
            )
        _STRATEGY_REGISTRY[name] = cls
        # 同步设置 name 属性，确保装饰器与类属性一致
        cls.name = name
        return cls

    return decorator


def get_strategy_class(name: str) -> Optional[Type["Strategy"]]:
    """按名取策略类。

    Args:
        name: 策略名

    Returns:
        策略类，未注册时返回 None
    """
    return _STRATEGY_REGISTRY.get(name)


def list_strategies() -> List[str]:
    """列出所有已注册策略名（按字典序，便于 CLI 展示）。"""
    return sorted(_STRATEGY_REGISTRY.keys())


def auto_discover(package_path: str = "src.strategies") -> List[str]:
    """自动发现并注册策略。

    扫描指定包下所有子目录，导入其中所有 .py 文件，触发 @register_strategy 装饰器
    完成注册。新版本控制已删除，扫描规则简化为：
        src/strategies/<策略名>/<任意>.py

    导入过程会跳过以下文件：
        - __init__.py（包初始化，通常无策略定义）
        - 以 _ 开头的文件（私有模块）

    Args:
        package_path: 策略包的导入路径，默认 "src.strategies"

    Returns:
        本次发现后已注册的全部策略名列表

    Raises:
        ImportError: 包不存在时抛出
    """
    # 导入策略包，触发其 __init__.py（可放显式导入）
    package = importlib.import_module(package_path)

    # 遍历包下所有子模块/子包
    # walk_packages 会递归遍历子包，对每个模块调用 importer.find_module
    for module_info in pkgutil.walk_packages(
        path=package.__path__,
        prefix=package.__name__ + ".",
    ):
        module_name = module_info.name
        # 跳过 __init__ 和私有模块
        short_name = module_name.rsplit(".", 1)[-1]
        if short_name == "__init__" or short_name.startswith("_"):
            continue
        try:
            # 导入模块，触发 @register_strategy 装饰器执行
            importlib.import_module(module_name)
        except Exception:
            # 单个策略导入失败不影响其他策略发现，向上层抛出会导致整次启动失败
            # 这里采用"吞掉异常 + 继续扫描"的策略，详细错误由调用方通过日志排查
            # 注意：开发期应通过单元测试覆盖，避免策略文件本身有导入错误
            import logging

            logging.getLogger(__name__).exception(
                "策略模块导入失败，已跳过: %s", module_name
            )

    return list_strategies()


# ---------------------------------------------------------------------------
# Strategy 抽象基类
# ---------------------------------------------------------------------------


class Strategy(ABC):
    """策略抽象基类。

    所有策略必须继承本类并实现 3 个生命周期回调：
        on_init  : 初始化（订阅数据、设置定时器、预计算）
        on_event : 统一事件处理（通过 event.type 分发 BAR/TICK/ORDER/...）
        on_stop  : 结束清理

    核心原则：
        1. 策略只通过 context 与引擎交互，不直接访问引擎内部
        2. 策略不感知运行模式（回测/模拟盘/实盘），context 由引擎注入
        3. 策略不直接访问数据库，数据通过 context.history() 获取
        4. 策略通过 context.submit_order() 主动下单，不返回订单列表

    子类应设置类属性 name（与 @register_strategy 装饰器参数一致）。
    """

    # 策略名：子类应覆盖；装饰器注册时会强制同步该属性
    name: str = ""

    def __init__(self, params: Optional[Dict] = None) -> None:
        """策略构造。

        Args:
            params: 策略参数字典（由 CLI/配置传入，引擎不解释其内容）
        """
        # 策略参数：默认空字典，子类按需读取
        self.params: Dict = dict(params) if params else {}

    # ----- 生命周期回调（必须实现） -----

    @abstractmethod
    def on_init(self, context: Context) -> None:
        """初始化回调。

        引擎启动时调用一次。典型用途：
            - context.subscribe(symbols) 订阅行情
            - context.add_timer(name, rule) 注册调仓定时器
            - 预计算因子、加载股票池

        Args:
            context: 策略上下文（由引擎注入）
        """
        raise NotImplementedError

    @abstractmethod
    def on_event(self, event: Event, context: Context) -> None:
        """统一事件处理回调。

        引擎每推送一个事件调用一次。策略通过 event.type 分发：
            if event.type is EventType.BAR: ...
            elif event.type is EventType.TIMER: ...

        Args:
            event: 事件对象（BarEvent/TickEvent/OrderEvent/TradeEvent/TimerEvent/AccountEvent）
            context: 策略上下文
        """
        raise NotImplementedError

    @abstractmethod
    def on_stop(self, context: Context) -> None:
        """结束回调。

        引擎停止时调用一次。典型用途：
            - 释放资源
            - 输出统计信息
            - 持久化策略私有状态

        Args:
            context: 策略上下文
        """
        raise NotImplementedError

    # ----- 便捷方法 -----

    def __repr__(self) -> str:
        return f"<Strategy {self.name} params={self.params}>"
