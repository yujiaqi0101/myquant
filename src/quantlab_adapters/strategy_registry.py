"""
SignalStrategyRegistry — quantlab SignalStrategy 的注册与发现。

为什么要单独的注册表：
    - 现有 src.engine.StrategyRegistry 强制要求继承 BaseStrategy（on_bar 模式）
    - Phase 2 重写的 v2 策略继承 SignalStrategy（signal() 模式）
    - 两套体系不能合并（v1 + v2 会在同一 CLI 列出，但走不同引擎）
    - 通过按文件路径发现 + 显式 @register_signal_strategy 装饰器支持

版本规则：
    - 版本号 v1/v2/v3... 表示策略改造次数，与使用哪个引擎无关
    - 同一策略名只注册最新版本（或数据库 is_active=1 指定的版本）
    - 策略类的 name 属性不带版本后缀（如 "small_cap"，不是 "small_cap_v2"）

发现规则：
    - 扫描 src/strategies/*/ 目录
    - 加载所有 *_v*.py 文件
    - 找出所有 SignalStrategy 子类，按版本号选择最新版本注册
    - 重复名（同策略名）→ 高版本覆盖低版本
"""

from __future__ import annotations

import importlib.util
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Type

logger = logging.getLogger(__name__)

# 匹配文件名中的版本号：xxx_v1.py, xxx_v2.py, ...
_VERSION_PATTERN = re.compile(r'^(.+)_v(\d+)\.py$')


class SignalStrategyRegistry:
    """SignalStrategy 注册表（与 BaseStrategy Registry 平行）。"""

    _strategies: Dict[str, type] = {}

    @classmethod
    def register(cls, strategy_class: type) -> type:
        """
        注册一个 SignalStrategy 子类。
        自动按 class.name 注册；如未设置 name，则用 class.__name__。
        注意：如果已有同名策略，新版本会覆盖旧版本（实现最新版本优先）。
        """
        from src.quantlab.signals.base import SignalStrategy

        if not isinstance(strategy_class, type) or not issubclass(
            strategy_class, SignalStrategy
        ):
            raise TypeError(
                f"SignalStrategyRegistry.register 要求继承 SignalStrategy，"
                f"got {strategy_class!r}"
            )

        name = getattr(strategy_class, "name", None) or strategy_class.__name__
        # 策略名不应该带版本后缀，这里做一次清洗
        if name and '_v' in name:
            cleaned = name.rsplit('_v', 1)[0]
            if cleaned:
                name = cleaned
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
                "params": list(getattr(sc, "default_params", {}).keys()) if hasattr(sc, 'default_params') else list(getattr(sc, "__init__", lambda: {}).keys()) if False else [],
            }
            for name, sc in cls._strategies.items()
        ]

    @classmethod
    def clear(cls) -> None:
        cls._strategies.clear()


# 装饰器语法糖
register_signal_strategy = SignalStrategyRegistry.register


def _extract_version(filename: str) -> Optional[tuple[str, int]]:
    """
    从文件名提取策略名和版本号。
    例如：small_cap_v2.py -> ("small_cap", 2)
    如果不匹配版本模式，返回 None。
    """
    m = _VERSION_PATTERN.match(filename)
    if m:
        return (m.group(1), int(m.group(2)))
    return None


def _load_active_versions() -> dict:
    """从数据库加载活跃策略版本映射 {strategy_name: version}（与v1注册表共用同一数据源）"""
    try:
        from src.data.database import DatabaseManager
        from config.config import DATABASE_CONFIG
        db = DatabaseManager(DATABASE_CONFIG.get('path', 'data/aquant.db'))
        active = db.get_active_strategies()
        if active is not None and not active.empty:
            return dict(zip(active['strategy_name'], active['version']))
    except Exception:
        pass
    return {}


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


def discover_v2_strategies(
    package_path: str = "src.strategies",
    strategy_name: Optional[str] = None,
) -> List[str]:
    """
    扫描 src/strategies/*/ 目录，加载 *_v*.py，
    把其中的 SignalStrategy 子类按版本选择后注册到 SignalStrategyRegistry。

    版本选择逻辑（与v1 StrategyRegistry一致）：
    1. 查询数据库 strategy_versions 表，优先加载 is_active=1 指定的版本
    2. 如果数据库无记录，则自动选择最高版本（文件名排序，v3 > v2 > v1）
    3. 同一策略名只保留一个版本（最新版本或指定版本）

    Parameters
    ----------
    package_path : str
        策略包路径，默认 "src.strategies"
    strategy_name : Optional[str]
        若指定，则只加载该名称的策略（按需加载，加速启动）；
        若为 None，则加载所有策略（用于 --list 等场景）。

    Returns
    -------
    list[str]
        实际加载的策略文件路径列表
    """
    base = Path(package_path.replace(".", "/"))
    if not base.is_dir():
        logger.warning("策略目录不存在: %s", base)
        return []

    # 如果指定了单个策略且已注册过，直接返回（避免重复加载）
    if strategy_name is not None and SignalStrategyRegistry.get(strategy_name) is not None:
        return []

    # 从数据库获取活跃版本配置
    active_versions = _load_active_versions()

    # 确定要扫描的目录列表
    if strategy_name is not None:
        # 按需加载：通过 _strategy_map.json 定位目录，或扫描目录查找
        map_file = base / "_strategy_map.json"
        target_dir = None
        if map_file.is_file():
            import json as _json
            try:
                with open(map_file, "r", encoding="utf-8") as f:
                    smap = _json.load(f)
                dir_id = smap.get(strategy_name)
                if dir_id:
                    candidate = base / dir_id
                    if candidate.is_dir():
                        target_dir = candidate
            except Exception:
                pass
        # 如果映射文件找不到，遍历目录查找包含目标策略文件的子目录
        if target_dir is None:
            for item in sorted(base.iterdir()):
                if not item.is_dir() or item.name.startswith("_") or item.name.startswith("__"):
                    continue
                for py_file in item.glob(f"{strategy_name}_v*.py"):
                    target_dir = item
                    break
                if target_dir is not None:
                    break
        if target_dir is None:
            logger.debug("策略 %s 未找到对应目录", strategy_name)
            return []
        dirs_to_scan = [target_dir]
    else:
        dirs_to_scan = [
            item for item in sorted(base.iterdir())
            if item.is_dir() and not item.name.startswith("_") and not item.name.startswith("__")
        ]

    loaded: list = []
    for item in dirs_to_scan:

        # 查找所有版本化策略文件 (*_v*.py)
        all_version_files = []
        for py_file in sorted(item.glob("*_v*.py")):
            ver_info = _extract_version(py_file.name)
            if ver_info:
                strategy_name, version_num = ver_info
                all_version_files.append((strategy_name, version_num, py_file))

        if not all_version_files:
            continue

        # 按策略名分组
        strategy_groups: Dict[str, List[tuple[int, Path]]] = {}
        for s_name, v_num, py_file in all_version_files:
            if s_name not in strategy_groups:
                strategy_groups[s_name] = []
            strategy_groups[s_name].append((v_num, py_file))

        # 对每个策略选择要加载的版本
        for strategy_name, versions in strategy_groups.items():
            # 按版本号排序
            versions.sort(key=lambda x: x[0])

            target_file = None
            # 1. 优先使用数据库指定的活跃版本
            if active_versions:
                target_version_str = active_versions.get(strategy_name)
                if target_version_str:
                    # 版本号格式可能是 "v2" 或 "2"
                    target_v_num = int(target_version_str.lstrip('v'))
                    for v_num, py_file in versions:
                        if v_num == target_v_num:
                            target_file = py_file
                            break
                    if target_file is None:
                        logger.warning(f"策略 {strategy_name} 活跃版本 {target_version_str} 文件不存在，使用最新版本")

            # 2. 无数据库配置或指定版本不存在 → 使用最高版本
            if target_file is None:
                target_file = versions[-1][1]  # 最高版本的文件

            # 加载选定的文件
            module_name = (
                f"src_strategies_{item.name}_{target_file.stem}".replace(".", "_")
            )
            spec = importlib.util.spec_from_file_location(module_name, str(target_file))
            if spec is None or spec.loader is None:
                continue
            try:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                # 自动发现 SignalStrategy 子类并注册
                _auto_register_signal_strategies(module)
                loaded.append(str(target_file))
                logger.info(f"加载策略 {strategy_name} 版本 v{versions[-1][0]}: {target_file.name}")
            except Exception as e:
                logger.warning("加载策略 %s 失败: %s", target_file, e)

    return loaded


__all__ = [
    "SignalStrategyRegistry",
    "register_signal_strategy",
    "discover_v2_strategies",
]
