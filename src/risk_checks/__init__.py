"""
src/risk_checks/__init__.py
===========================

A 股法定风控 Check 包初始化模块（迁移自 src/quantlab_extras/）。

统一导出所有 A 股风控 Check 与工厂函数：
    - 5 个迁移 Check（法定风控）：
        LimitUpCheck / LimitDownCheck  涨跌停过滤
        STFilterCheck                  ST/退市股过滤
        TPlusOneCheck                  T+1 可卖量检查
        NewStockCheck                  新股过滤（上市<60天）
        SuspendCheck                   停牌过滤
    - 5 个新增 Check（订单级 + 组合级，定义在 factory.py）：
        MaxOrderQtyCheck               单笔最大下单量
        LotSizeCheck                   lot_size 整数倍
        MaxPositionPctCheck            单持仓仓位上限
        MaxPositionsCheck              持仓数量上限
        DailyStopLossCheck             日亏急停
    - 工厂函数：
        build_ashare_risk_manager      一键构造 A 股默认 RiskManager

所有 Check 适配新版统一引擎的 RiskCheck 基类（src/core/risk/checks.py），
由 RiskManager 串联执行。

用法：
    from src.risk_checks import build_ashare_risk_manager, LimitUpCheck
    rm = build_ashare_risk_manager()
"""

from src.risk_checks.factory import (
    DailyStopLossCheck,
    LotSizeCheck,
    MaxOrderQtyCheck,
    MaxPositionPctCheck,
    MaxPositionsCheck,
    build_ashare_risk_manager,
)
from src.risk_checks.limit_filter import LimitDownCheck, LimitUpCheck
from src.risk_checks.new_stock import NewStockCheck
from src.risk_checks.st_filter import STFilterCheck
from src.risk_checks.suspend import SuspendCheck
from src.risk_checks.t_plus_one import TPlusOneCheck

__all__ = [
    # 法定风控（迁移自 quantlab_extras）
    "LimitUpCheck",
    "LimitDownCheck",
    "STFilterCheck",
    "TPlusOneCheck",
    "NewStockCheck",
    "SuspendCheck",
    # 订单级 + 组合级 Check（factory.py 内定义）
    "MaxOrderQtyCheck",
    "LotSizeCheck",
    "MaxPositionPctCheck",
    "MaxPositionsCheck",
    "DailyStopLossCheck",
    # 工厂函数
    "build_ashare_risk_manager",
]
