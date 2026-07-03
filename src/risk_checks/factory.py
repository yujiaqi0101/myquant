"""
src/risk_checks/factory.py
==========================

A 股默认 RiskManager 工厂 + 5 个订单/组合级风控 Check。

本模块提供：
    1. build_ashare_risk_manager() 工厂函数：一键构造 A 股默认风控管线
    2. 5 个新增 Check（订单级 + 组合级）：
       - MaxOrderQtyCheck     单笔最大下单量
       - LotSizeCheck         lot_size 整数倍（科创板200/其他100）
       - MaxPositionPctCheck  单持仓仓位上限（占总资产比例）
       - MaxPositionsCheck    持仓数量上限（最多持N只）
       - DailyStopLossCheck   日亏急停（当日亏损超过阈值停止交易）

风控三层架构（设计文档 5.1 节）：
    Layer 1 法定风控（必执行）：涨跌停 / ST / 新股 / 停牌 / T+1
    Layer 2 订单级检查        ：单笔最大量 / lot_size 整数倍
    Layer 3 组合级检查（可选） ：单持仓仓位上限 / 持仓数量上限 / 日亏急停

工厂函数默认按上述三层顺序添加 11 个 Check，任一不通过即拒绝订单。

适配新版统一引擎：
    - 5 个迁移 Check 来自本包其他模块（limit_filter/st_filter/...）
    - 5 个新增 Check 定义在本文件内
    - 统一从 src.core.risk 导入 RiskCheck / RiskCheckResult / RiskManager
    - 统一从 src.core.types 导入 Order / Direction / get_lot_size

用法：
    from src.risk_checks.factory import build_ashare_risk_manager
    rm = build_ashare_risk_manager()
    rm.set_context_provider(my_provider)
    result = rm.check_order(order)
"""

import logging
from typing import Any, Dict, List, Union

from src.core.risk.checks import RiskCheck, RiskCheckResult, get_field
from src.core.risk.manager import RiskManager
from src.core.types import Direction, Order, get_lot_size

from src.risk_checks.limit_filter import LimitDownCheck, LimitUpCheck
from src.risk_checks.new_stock import NewStockCheck
from src.risk_checks.st_filter import STFilterCheck
from src.risk_checks.suspend import SuspendCheck
from src.risk_checks.t_plus_one import TPlusOneCheck


logger = logging.getLogger(__name__)


# ===========================================================================
# 第一部分：5 个新增 Check（订单级 + 组合级）
# ===========================================================================


class MaxOrderQtyCheck(RiskCheck):
    """单笔最大下单量检查。

    检查 order.volume 是否超过 max_qty，超过则拒绝。
    对买入和卖出都检查（防止异常大单）。
    """

    def __init__(self, max_qty: int = 1_000_000, name: str = "MaxOrderQtyCheck") -> None:
        """初始化单笔最大量检查。

        Args:
            max_qty: 单笔最大下单股数，默认 100 万股
            name: Check 名称
        """
        super().__init__(name)
        # 强制 int，避免 float 比较异常
        self.max_qty = int(max_qty)

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查订单数量是否超过单笔上限。"""
        # 买入和卖出都检查（防止异常大单）
        if order.volume > self.max_qty:
            return RiskCheckResult.rejected(
                self.name,
                f"{order.symbol} 单笔量超限：{order.volume} > 上限 {self.max_qty}",
            )
        return RiskCheckResult.passed_result(self.name)


class LotSizeCheck(RiskCheck):
    """lot_size 整数倍检查。

    A 股交易规则：下单量必须是 lot_size 的整数倍。
        - 688 开头（科创板）：200 股/手
        - 其他：100 股/手

    使用 src.core.types.get_lot_size(symbol) 获取每手股数。
    下单量不是 lot_size 整数倍时拒绝（避免废单）。
    """

    def __init__(self, name: str = "LotSizeCheck") -> None:
        super().__init__(name)

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查订单数量是否为 lot_size 整数倍。"""
        # 获取该 symbol 的每手股数（688=200，其他=100）
        lot_size = get_lot_size(order.symbol)
        if lot_size <= 0:
            # 理论不会发生，防御性处理
            return RiskCheckResult.passed_result(self.name)

        # order.volume 是 float，需转换为整数比较
        # 用 round 处理浮点精度（如 99.99999999 应视为 100）
        vol_int = int(round(order.volume))
        if vol_int <= 0:
            # 数量非正，交给其他 Check / Execution 处理
            return RiskCheckResult.passed_result(self.name)

        # 不是 lot_size 的整数倍 -> 拒绝
        if vol_int % lot_size != 0:
            return RiskCheckResult.rejected(
                self.name,
                f"{order.symbol} 手数不对：{vol_int} 不是 {lot_size} "
                f"的整数倍（应为 {lot_size} 的倍数）",
            )
        return RiskCheckResult.passed_result(self.name)


class MaxPositionPctCheck(RiskCheck):
    """单持仓仓位上限检查（组合级，可选）。

    计算下单后该 symbol 占总资产的比例，超过 max_pct 则拒绝。
    仅对买入订单检查（卖出会降低仓位，无需限制）。

    计算公式：
        新仓位市值 = (当前持仓量 + 买入量) × 当前价
        仓位占比 = 新仓位市值 / 总资产
        占比 > max_pct -> 拒绝
    """

    def __init__(
        self,
        max_pct: float = 0.30,
        name: str = "MaxPositionPctCheck",
    ) -> None:
        """初始化单持仓仓位上限检查。

        Args:
            max_pct: 单持仓占总资产比例上限，默认 0.30（30%）
            name: Check 名称
        """
        super().__init__(name)
        self.max_pct = float(max_pct)

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查买入后该 symbol 仓位占比是否超限。"""
        # 仅买入订单检查（卖出降低仓位，无需限制）
        if order.direction is not Direction.BUY:
            return RiskCheckResult.passed_result(self.name)

        # 取当前价（缺失时降级放行）
        current_price = context_data.get("current_price")
        if current_price is None or current_price <= 0:
            return RiskCheckResult.passed_result(self.name)

        # 取总资产（缺失时降级放行）
        account = context_data.get("account")
        total = get_field(account, "total", 0.0) or 0.0
        if total <= 0:
            # 总资产为 0 或缺失，无法计算占比，降级放行
            return RiskCheckResult.passed_result(self.name)

        # 取当前持仓量（无持仓时为 0）
        position = context_data.get("position")
        current_qty = get_field(position, "quantity", 0.0) or 0.0

        # 计算下单后该 symbol 的仓位占比
        new_value = (current_qty + order.volume) * current_price
        pct = new_value / total

        # 占比超限 -> 拒绝
        if pct > self.max_pct:
            return RiskCheckResult.rejected(
                self.name,
                f"{order.symbol} 仓位超限：下单后占比 {pct:.2%} > "
                f"上限 {self.max_pct:.2%}（新市值={new_value:.2f}, "
                f"总资产={total:.2f}）",
            )
        return RiskCheckResult.passed_result(self.name)


class MaxPositionsCheck(RiskCheck):
    """持仓数量上限检查（组合级，可选）。

    买入"新股票"时检查当前持仓数量是否已达上限。
    已有持仓的股票加仓不限制（不算开新仓）。
    仅对买入订单检查。

    portfolio 数据形态兼容：
        - dict: {symbol: Position, ...}
        - list: [Position, ...]
    只统计 quantity > 0 的持仓。
    """

    def __init__(
        self,
        max_count: int = 10,
        name: str = "MaxPositionsCheck",
    ) -> None:
        """初始化持仓数量上限检查。

        Args:
            max_count: 最多持仓股票数量，默认 10 只
            name: Check 名称
        """
        super().__init__(name)
        self.max_count = int(max_count)

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查买入新股票时持仓数量是否超限。"""
        # 仅买入订单检查
        if order.direction is not Direction.BUY:
            return RiskCheckResult.passed_result(self.name)

        # 取当前持仓（缺失时降级放行）
        position = context_data.get("position")
        current_qty = get_field(position, "quantity", 0.0) or 0.0
        # 已有持仓的股票加仓不算开新仓，直接放行
        if current_qty > 0:
            return RiskCheckResult.passed_result(self.name)

        # 取全部持仓（portfolio），统计当前持仓股票数量
        portfolio = context_data.get("portfolio")
        if portfolio is None:
            # 无 portfolio 信息，无法校验，降级放行
            return RiskCheckResult.passed_result(self.name)

        # 兼容 dict 和 list 两种形态，统计 quantity > 0 的持仓数
        current_count = _count_positions(portfolio)

        # 持仓数已达上限 -> 拒绝开新仓
        if current_count >= self.max_count:
            return RiskCheckResult.rejected(
                self.name,
                f"{order.symbol} 持仓数超限：当前 {current_count} 只 "
                f">= 上限 {self.max_count} 只，不可开新仓",
            )
        return RiskCheckResult.passed_result(self.name)


class DailyStopLossCheck(RiskCheck):
    """日亏急停检查（组合级，可选）。

    检查 account.daily_pnl_pct（当日盈亏百分比）是否低于 threshold。
    低于阈值时拒绝所有新订单（停止交易，避免亏损扩大）。

    注意：threshold 为负数（如 -0.05 表示当日亏损 5% 急停）。
    对买入和卖出都检查（急停后停止一切交易）。
    """

    def __init__(
        self,
        threshold: float = -0.05,
        name: str = "DailyStopLossCheck",
    ) -> None:
        """初始化日亏急停检查。

        Args:
            threshold: 当日亏损百分比阈值，默认 -0.05（亏损 5% 急停）
                       注意是负数，daily_pnl_pct < threshold 时触发
            name: Check 名称
        """
        super().__init__(name)
        self.threshold = float(threshold)

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查当日亏损是否触发急停。"""
        # 取账户信息（缺失时降级放行）
        account = context_data.get("account")
        if account is None:
            return RiskCheckResult.passed_result(self.name)

        # 取当日盈亏百分比（缺失时降级放行）
        daily_pnl_pct = get_field(account, "daily_pnl_pct", None)
        if daily_pnl_pct is None:
            # 兼容旧字段名 daily_loss_pct
            daily_pnl_pct = get_field(account, "daily_loss_pct", 0.0)
        daily_pnl_pct = float(daily_pnl_pct or 0.0)

        # 当日亏损超过阈值 -> 急停拒单
        if daily_pnl_pct < self.threshold:
            return RiskCheckResult.rejected(
                self.name,
                f"{order.symbol} 日亏急停：当日盈亏 {daily_pnl_pct:.2%} < "
                f"阈值 {self.threshold:.2%}，停止交易",
            )
        return RiskCheckResult.passed_result(self.name)


# ---------------------------------------------------------------------------
# 辅助函数：统计持仓数量
# ---------------------------------------------------------------------------


def _count_positions(portfolio: Union[Dict[str, Any], List[Any]]) -> int:
    """统计 portfolio 中 quantity > 0 的持仓数量。

    兼容两种 portfolio 数据形态：
        - dict: {symbol: Position, ...}，遍历 values()
        - list: [Position, ...]，直接遍历

    Args:
        portfolio: 全部持仓（dict 或 list）

    Returns:
        有效持仓数量（quantity > 0）
    """
    count = 0
    if isinstance(portfolio, dict):
        # dict 形态：遍历 values
        for pos in portfolio.values():
            qty = get_field(pos, "quantity", 0.0) or 0.0
            if qty > 0:
                count += 1
    elif isinstance(portfolio, (list, tuple)):
        # list 形态：直接遍历
        for pos in portfolio:
            qty = get_field(pos, "quantity", 0.0) or 0.0
            if qty > 0:
                count += 1
    return count


# ===========================================================================
# 第二部分：A 股默认 RiskManager 工厂函数
# ===========================================================================


def build_ashare_risk_manager(
    enable_portfolio_check: bool = True,
    max_position_pct: float = 0.30,
    max_positions: int = 10,
    max_order_qty: int = 1_000_000,
    daily_stop_loss: float = -0.05,
) -> RiskManager:
    """构造 A 股默认 RiskManager。

    按风控三层架构顺序添加 11 个 Check：
        Layer 1 法定风控（必执行，6 个）：
            1. LimitUpCheck          涨停买入过滤
            2. LimitDownCheck        跌停卖出过滤
            3. STFilterCheck         ST/退市股过滤
            4. NewStockCheck         新股过滤（上市<60天）
            5. SuspendCheck          停牌过滤
            6. TPlusOneCheck         T+1 可卖量检查
        Layer 2 订单级检查（必执行，2 个）：
            7. MaxOrderQtyCheck      单笔最大量
            8. LotSizeCheck          lot_size 整数倍
        Layer 3 组合级检查（可选，enable_portfolio_check 控制，3 个）：
            9.  MaxPositionPctCheck  单持仓仓位上限
            10. MaxPositionsCheck    持仓数量上限
            11. DailyStopLossCheck   日亏急停

    任一 Check 不通过即拒绝订单（短路返回）。

    Args:
        enable_portfolio_check: 是否启用组合级检查（Layer 3），默认 True
        max_position_pct:  单持仓占总资产比例上限，默认 0.30（30%）
        max_positions:     最多持仓股票数量，默认 10 只
        max_order_qty:     单笔最大下单股数，默认 100 万股
        daily_stop_loss:   日亏急停阈值，默认 -0.05（亏损 5% 急停）

    Returns:
        RiskManager 实例（已添加 8~11 个 Check）

    用法：
        rm = build_ashare_risk_manager()
        rm.set_context_provider(my_context_provider)
        result = rm.check_order(order)
    """
    rm = RiskManager()

    # ----- Layer 1: 法定风控（必执行） -----
    # 涨跌停过滤
    rm.add_check(LimitUpCheck())
    rm.add_check(LimitDownCheck())
    # ST/退市股过滤
    rm.add_check(STFilterCheck())
    # 新股过滤（上市<60天）
    rm.add_check(NewStockCheck(min_days=60))
    # 停牌过滤
    rm.add_check(SuspendCheck())
    # T+1 可卖量检查
    rm.add_check(TPlusOneCheck())

    # ----- Layer 2: 订单级检查（必执行） -----
    # 单笔最大下单量
    rm.add_check(MaxOrderQtyCheck(max_qty=max_order_qty))
    # lot_size 整数倍（科创板200/其他100）
    rm.add_check(LotSizeCheck())

    # ----- Layer 3: 组合级检查（可选） -----
    if enable_portfolio_check:
        # 单持仓仓位上限
        rm.add_check(MaxPositionPctCheck(max_pct=max_position_pct))
        # 持仓数量上限
        rm.add_check(MaxPositionsCheck(max_count=max_positions))
        # 日亏急停
        rm.add_check(DailyStopLossCheck(threshold=daily_stop_loss))

    logger.info(
        "build_ashare_risk_manager 已添加 %d 个 Check: %s",
        len(rm),
        rm.get_check_names(),
    )
    return rm
