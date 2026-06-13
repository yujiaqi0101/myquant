"""
SignalStrategyRegistry — quantlab SignalStrategy 的注册与发现。

为什么要单独的注册表：
    - 现有 src.engine.StrategyRegistry 强制要求继承 BaseStrategy（on_bar 模式）
    - Phase 2 重写的 6 个 v2 策略继承 SignalStrategy（signal() 模式）
    - 两套体系不能合并（v1 + v2 会在同一 CLI 列出，但走不同引擎）
    - 通过按文件路径发现 + 显式 @register_signal_strategy 装饰器支持

发现规则：
    - 扫描 src/strategies/*/ 目录
    - 加载所有 *_v2.py 文件
    - 找出所有 SignalStrategy 子类，按 class.name 注册
    - 重复名 → 后加载的覆盖前加载的
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class SignalStrategyRegistry:
    """SignalStrategy 注册表（与 BaseStrategy Registry 平行）。"""

    _strategies: Dict[str, type] = {}

    @classmethod
    def register(cls, strategy_class: type) -> type:
        """
        注册一个 SignalStrategy 子类。
        自动按 class.name 注册；如未设置 name，则用 class.__name__。
        """
        # 延迟 import，避免循环依赖
        from src.quantlab.signals.base import SignalStrategy

        if not isinstance(strategy_class, type) or not issubclass(
            strategy_class, SignalStrategy
        ):
            raise TypeError(
                f"SignalStrategyRegistry.register 要求继承 SignalStrategy，"
                f"got {strategy_class!r}"
            )

        name = getattr(strategy_class, "name", None) or strategy_class.__name__
        cls._strategies[name] = strategy_class
        logger.debug("SignalStrategyRegistry 注册: %s -> %s", name, strategy_class)
        return strategy_class

    @classmethod
    def get(cls, name: str) -> Optional[type]:
        return cls._strategies.get(name)

    @classmethod
    def list_strategies(cls) -> List[Dict]:
        return [
            {
                "name": name,
                "class": sc.__name__,
                "description": getattr(sc, "description", "") or "",
                "params": list(getattr(sc, "default_params", {}).keys()),
            }
            for name, sc in cls._strategies.items()
        ]

    @classmethod
    def clear(cls) -> None:
        cls._strategies.clear()


# 装饰器语法糖
register_signal_strategy = SignalStrategyRegistry.register


def _auto_register_signal_strategies(module) -> List[str]:
    """
    扫描模块内所有 SignalStrategy 子类并自动注册。

    quantlab 风格：继承 SignalStrategy 即视为可注册策略，
    不强制使用 @register_signal_strategy 装饰器。
    但装饰器依然兼容（先扫一遍装饰器，再补漏自动发现）。
    """
    from src.quantlab.signals.base import SignalStrategy

    names: list = []
    for attr_name in dir(module):
        obj = getattr(module, attr_name, None)
        if not isinstance(obj, type):
            continue
        if obj is SignalStrategy:
            continue
        if not issubclass(obj, SignalStrategy):
            continue
        # 已注册过（来自装饰器）则跳过
        existing = SignalStrategyRegistry.get(
            getattr(obj, "name", None) or obj.__name__
        )
        if existing is obj:
            continue
        SignalStrategyRegistry.register(obj)
        names.append(getattr(obj, "name", None) or obj.__name__)
    return names


def discover_v2_strategies(package_path: str = "src.strategies") -> List[str]:
    """
    扫描 src/strategies/*/ 目录，加载所有 *_v2.py，
    把其中的 SignalStrategy 子类自动注册到 SignalStrategyRegistry。

    两种注册路径：
        1) @register_signal_strategy 装饰器（显式）
        2) 继承 SignalStrategy 的类（自动）

    Returns
    -------
    list[str]
        实际加载的策略文件名（含路径）
    """
    base = Path(package_path.replace(".", "/"))
    if not base.is_dir():
        logger.warning("策略目录不存在: %s", base)
        return []

    loaded: list = []
    for item in sorted(base.iterdir()):
        if not item.is_dir() or item.name.startswith("_") or item.name.startswith("__"):
            continue

        for py_file in sorted(item.glob("*_v2.py")):
            module_name = (
                f"src_strategies_{item.name}_{py_file.stem}".replace(".", "_")
            )
            spec = importlib.util.spec_from_file_location(module_name, str(py_file))
            if spec is None or spec.loader is None:
                continue
            try:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                # 自动发现 SignalStrategy 子类并注册
                _auto_register_signal_strategies(module)
                loaded.append(str(py_file))
            except Exception as e:
                logger.warning("加载策略 %s 失败: %s", py_file, e)
    return loaded


__all__ = [
    "SignalStrategyRegistry",
    "register_signal_strategy",
    "discover_v2_strategies",
]
