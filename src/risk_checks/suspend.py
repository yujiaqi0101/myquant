"""
src/risk_checks/suspend.py
==========================

A 股停牌过滤 Check（迁移自 src/quantlab_extras/suspend.py）。

停牌期间无法撮合，所有买入/卖出都要拒绝。
判断规则（按优先级）：
    1. stock_info.is_suspended 字段为 True   -> 拒单（首选，数据源直接标注）
    2. stock_info.suspend_flag 字段非 0       -> 拒单（兼容旧字段名）
    3. bar.volume == 0                        -> 拒单（兜底，停牌当日无成交）

适配新版统一引擎：
    - 输入：Order + context_data（dict）
    - 输出：RiskCheckResult（passed/reason）
    - 数据来源：context_data["stock_info"]（is_suspended/suspend_flag）
              + context_data["bar"].volume（成交量）

买入和卖出都检查（停牌期间买卖都不应成交）。

用法：
    from src.risk_checks.suspend import SuspendCheck
    rm.add_check(SuspendCheck())
"""

import logging
from typing import Any, Dict

from src.core.risk.checks import RiskCheck, RiskCheckResult, get_field
from src.core.types import Order


logger = logging.getLogger(__name__)


class SuspendCheck(RiskCheck):
    """停牌期间禁止交易（买入和卖出都拒绝）。

    优先用 stock_info.is_suspended 字段判断；
    缺失时降级用 stock_info.suspend_flag 字段（兼容旧数据）；
    仍缺失时用 bar.volume == 0 兜底判断（停牌当日无成交量）。
    """

    def __init__(self, name: str = "SuspendCheck") -> None:
        super().__init__(name)

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查订单目标股票是否停牌。"""
        # 停牌对买入和卖出都拒绝（买卖双方都无法成交）

        # ----- 1. 优先用 stock_info 的停牌标志判断 -----
        stock_info = context_data.get("stock_info")
        if stock_info is not None:
            # 首选 is_suspended 字段（bool，新版数据源标注）
            is_suspended = get_field(stock_info, "is_suspended", None)
            # is_suspended 缺失时降级用 suspend_flag 字段（旧版数据源，0=正常/非0=停牌）
            if is_suspended is None:
                suspend_flag = get_field(stock_info, "suspend_flag", 0) or 0
                is_suspended = bool(suspend_flag)

            # 停牌 -> 拒单
            if is_suspended:
                logger.info(
                    "SuspendCheck 拒单 %s：stock_info 标记停牌（is_suspended=%s）",
                    order.symbol,
                    is_suspended,
                )
                return RiskCheckResult.rejected(
                    self.name,
                    f"{order.symbol} 停牌拒单：stock_info 标记为停牌状态",
                )

        # ----- 2. 兜底：用 bar.volume == 0 判断停牌 -----
        # 停牌当日无成交量（volume=0），正常交易股票 volume > 0
        bar = context_data.get("bar")
        if bar is not None:
            volume = get_field(bar, "volume", None)
            # volume 为 0 且明确存在（非 None）时判定停牌
            # 注意：volume 为 None 时不判定（数据缺失，降级放行）
            if volume is not None and float(volume) == 0:
                logger.info(
                    "SuspendCheck 拒单 %s：bar.volume=0 判定停牌",
                    order.symbol,
                )
                return RiskCheckResult.rejected(
                    self.name,
                    f"{order.symbol} 停牌拒单：当日成交量 volume=0",
                )

        # 数据齐全且未触发停牌条件 -> 放行
        return RiskCheckResult.passed_result(self.name)
