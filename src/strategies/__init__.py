"""
策略模块

支持两种目录结构：
1. 旧版（平铺）：src/strategies/<策略名>.py
2. 新版（ID目录）：src/strategies/<策略ID>/<策略名>_<版本>.py

每个策略ID目录包含：
- <策略名>_<版本>.py  : 策略文件
- 策略路径.md         : 策略说明和版本历史
- __init__.py         : Python包标记

数据库表 strategy_versions 记录策略名、版本号、文件路径、活跃状态。
程序运行时根据 is_active=1 加载对应的策略版本。
"""

import json
import os
from pathlib import Path

_STRATEGIES_DIR = Path(__file__).parent


def get_strategy_ids() -> dict:
    """获取策略名-to-ID映射"""
    map_file = _STRATEGIES_DIR / '_strategy_map.json'
    if map_file.exists():
        with open(map_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def init_strategy_registry():
    """
    初始化数据库策略注册表

    扫描所有ID目录，将策略版本信息写入 strategy_versions 表。
    如果表中有活跃版本记录，则跳过（保留用户设置）。
    如果是全新数据库，则默认激活每个策略的最新版本。
    """
    from src.data.database import DatabaseManager
    from config.config import DATABASE_CONFIG

    db = DatabaseManager(DATABASE_CONFIG.get('path', 'data/aquant.db'))

    # 检查是否已有活跃策略
    existing = db.get_active_strategies()
    if not existing.empty:
        # 已有活跃策略，跳过自动注册
        return

    # 扫描ID目录注册策略
    for item in _STRATEGIES_DIR.iterdir():
        if not item.is_dir() or item.name.startswith('_'):
            continue
        if item.name.startswith('__'):
            continue

        strategy_id = item.name
        # 查找版本化策略文件
        py_files = sorted(item.glob('*_v*.py'))
        if not py_files:
            continue

        # 取最高版本
        latest = py_files[-1]
        stem = latest.stem  # 例如: small_cap_v1
        # 分离策略名和版本号
        if '_v' in stem:
            parts = stem.rsplit('_v', 1)
            strategy_name = parts[0]
            version = 'v' + parts[1]
        else:
            strategy_name = stem
            version = 'v1'

        # 读取描述（从策略路径.md）
        desc = ''
        md_file = item / '策略路径.md'
        if md_file.exists():
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and not line.startswith('|'):
                            desc = line
                            break
            except Exception:
                pass

        rel_path = f"src/strategies/{strategy_id}/{latest.name}"
        db.register_strategy_version(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            version=version,
            file_path=rel_path,
            description=desc,
            is_active=1,
        )

    print(f"策略注册表初始化完成")


# 自动发现并注册所有策略（兼容新旧两种目录结构）
from src.engine.base_strategy import StrategyRegistry
StrategyRegistry.auto_discover('src.strategies')
