"""
src/risk_checks/t_plus_one.py
=============================

A 股 T+1 规则检查 Check（迁移自 src/quantlab_extras/t_plus_one.py）。

A 股市场规则：当日买入的股票，下一交易日才能卖出（T+1）。
Position 数据结构（src/core/types.py）已内置 T+1 处理：
    - 买入：today_bought += volume（available 不变，当日买入不可卖）
    - 次日开盘：settle_new_day() 将 today_bought 转入 available

本 Check 在卖出订单提交前校验：order.volume 是否 <= position.available。
若 available 不足（含当日买入冻结的部分），拒绝卖出订单。

适配新版统一引擎：
    - 输入：Order + context_data（dict）
    - 输出：RiskCheckResult（passed/reason）
    - 数据来源：context_data["position"].available（可卖数量）

与旧版差异：
    旧版自行维护 _last_buy_date 字典记录买入日期；新版直接用 Position.available，
    因为 Position 已内置 T+1 冻结/解冻逻辑，无需在 Check 中重复维护状态。

用法：
    from src.risk_checks.t_plus_one import TPlusOneCheck
    rm.add_check(TPlusOneCheck())
"""

import logging
from typing import Any, Dict

from src.core.risk.checks import RiskCheck, RiskCheckResult, get_field
from src.core.types import Direction, Order


logger = logging.getLogger(__name__)


class TPlusOneCheck(RiskCheck):
    """A 股 T+1：卖出数量不得超过可卖数量。

    依赖 Position.available 字段（已扣除当日买入冻结量）。
    可卖数量不足时拒绝卖出，避免成交后无法交收。
    """

    def __init__(self, name: str = "TPlusOneCheck") -> None:
        super().__init__(name)

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查卖出订单是否违反 T+1 规则。"""
        # 只对卖出做限制；买入/TARGET 放行
        if order.direction is not Direction.SELL:
            return RiskCheckResult.passed_result(self.name)

        # 取当前持仓（缺失时降级放行，由 Execution 层兜底校验）
        position = context_data.get("position")
        if position is None:
            # 无持仓信息时无法校验，放行（空持仓卖出会在撮合层失败）
            return RiskCheckResult.passed_result(self.name)

        # 取可卖数量（Position.available，已扣除 today_bought 冻结量）
        available = get_field(position, "available", 0.0) or 0.0

        # 卖出量超过可卖量 -> 拒绝（T+1 约束）
        if order.volume > available + 1e-9:
            logger.info(
                "TPlusOneCheck 拒卖 %s：卖出 %s > 可用 %s",
                order.symbol,
                order.volume,
                available,
            )
            return RiskCheckResult.rejected(
                self.name,
                f"{order.symbol} T+1 约束：卖出量 {order.volume} > "
                f"可卖量 {available}（含当日买入冻结）",
            )
        return RiskCheckResult.passed_result(self.name)
