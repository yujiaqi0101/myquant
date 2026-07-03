"""
src/risk_checks/limit_filter.py
===============================

A 股涨跌停过滤 Check（迁移自 src/quantlab_extras/limit_filter.py）。

按板块设置涨跌幅阈值：
    - 主板 / 中小板 (60/00/002/603/605 开头)：±10%   -> 涨 1.10 / 跌 0.90
    - 创业板 (30 开头)                  ：±20%   -> 涨 1.20 / 跌 0.80
    - 科创板 (688 开头)                 ：±20%   -> 涨 1.20 / 跌 0.80
    - 北交所 (8/92/43 开头)             ：±30%   -> 涨 1.30 / 跌 0.70

包含两个 Check：
    - LimitUpCheck   涨停日拒买（买入订单当前价 >= 涨停价时拒绝）
    - LimitDownCheck 跌停日拒卖（卖出订单当前价 <= 跌停价时拒绝）

适配新版统一引擎：
    - 输入：Order（含 direction/volume/symbol）+ context_data（dict）
    - 输出：RiskCheckResult（passed/reason）
    - 数据来源：context_data["bar"].prev_close（前收盘）+ context_data["current_price"]（当前价）

prev_close 获取兼容两种 bar 形态：
    - dict 形态：bar["prev_close"]（实盘/API 返回）
    - BarEvent 形态：bar.extra["prev_close"]（回测，BarEvent 无 prev_close 字段）

用法：
    from src.risk_checks.limit_filter import LimitUpCheck, LimitDownCheck
    rm.add_check(LimitUpCheck())
    rm.add_check(LimitDownCheck())
"""

import logging
from typing import Any, Dict, Optional, Tuple

from src.core.risk.checks import RiskCheck, RiskCheckResult, get_field
from src.core.types import Direction, Order


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 板块涨跌幅阈值表
# ---------------------------------------------------------------------------


def _threshold_for_symbol(symbol: str) -> Tuple[float, float]:
    """返回 (涨停价比例, 跌停价比例)。

    涨停价 = prev_close × upper_ratio
    跌停价 = prev_close × lower_ratio

    规则：
        - 北交所 (8/92/43 开头)：±30%
        - 创业板 (30 开头) / 科创板 (688 开头)：±20%
        - 其他（主板/中小板）：±10%

    Args:
        symbol: 标的代码，兼容 "688001.SH" / "SHSE.688001" / "688001" 等格式

    Returns:
        (upper_ratio, lower_ratio)，如 (1.10, 0.90)
    """
    # 取 symbol 中的数字部分做前缀判断，兼容多种代码格式
    digits = "".join(ch for ch in str(symbol) if ch.isdigit())

    # 北交所 30%（8/92/43 开头）
    if digits.startswith(("8", "92", "43")):
        return 1.30, 0.70
    # 创业板 / 科创板 20%
    if digits.startswith(("30", "688")):
        return 1.20, 0.80
    # 主板 / 中小板 10%（60/00/002/603/605 等）
    return 1.10, 0.90


def _get_prev_close(bar: Any) -> Optional[float]:
    """从 bar 数据中获取前收盘价，兼容 dict 与 BarEvent 两种形态。

    BarEvent（见 src/core/events.py）没有 prev_close 字段，
    回测时需将 prev_close 放入 bar.extra 字典；
    实盘/API 返回的 bar 通常是 dict，可直接取 bar["prev_close"]。

    Args:
        bar: bar 数据（dict 或 BarEvent，可为 None）

    Returns:
        前收盘价（float）；缺失时返回 None
    """
    if bar is None:
        return None
    # 优先直接取 prev_close 字段（bar 为 dict 时）
    prev = get_field(bar, "prev_close", None)
    if prev is not None:
        return float(prev)
    # 其次从 extra 字典取（bar 为 BarEvent 时，prev_close 放在 extra 里）
    extra = get_field(bar, "extra", None)
    if extra is not None:
        prev = get_field(extra, "prev_close", None)
        if prev is not None:
            return float(prev)
    return None


# ---------------------------------------------------------------------------
# 涨停买入过滤
# ---------------------------------------------------------------------------


class LimitUpCheck(RiskCheck):
    """涨停日拒买。

    买入订单当前价 >= 涨停价（prev_close × upper_ratio）时拒绝。
    卖出订单不检查（跌停不影响卖出，由 LimitDownCheck 单独处理）。
    """

    def __init__(self, name: str = "LimitUpCheck") -> None:
        super().__init__(name)

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查买入订单是否触及涨停价。"""
        # 仅买入订单限制（TARGET 模式由引擎折算成 BUY/SELL 后再走风控，这里放行）
        if order.direction is not Direction.BUY:
            return RiskCheckResult.passed_result(self.name)

        # 取前收盘价（缺失时安全降级放行，避免阻塞无数据订单）
        bar = context_data.get("bar")
        prev_close = _get_prev_close(bar)
        if prev_close is None or prev_close <= 0:
            logger.warning(
                "LimitUpCheck 跳过 %s：bar 缺少 prev_close，放行",
                order.symbol,
            )
            return RiskCheckResult.passed_result(self.name)

        # 取当前价（缺失时降级放行）
        current_price = context_data.get("current_price")
        if current_price is None or current_price <= 0:
            logger.warning(
                "LimitUpCheck 跳过 %s：缺少 current_price，放行",
                order.symbol,
            )
            return RiskCheckResult.passed_result(self.name)

        # 计算涨停价
        upper_ratio, _ = _threshold_for_symbol(order.symbol)
        limit_up_price = prev_close * upper_ratio

        # 当前价 >= 涨停价 -> 涨停拒买
        if current_price >= limit_up_price:
            return RiskCheckResult.rejected(
                self.name,
                f"{order.symbol} 涨停拒买：当前价 {current_price:.4f} >= "
                f"涨停价 {limit_up_price:.4f}（prev_close={prev_close:.4f}, "
                f"上限={upper_ratio}）",
            )
        return RiskCheckResult.passed_result(self.name)


# ---------------------------------------------------------------------------
# 跌停卖出过滤
# ---------------------------------------------------------------------------


class LimitDownCheck(RiskCheck):
    """跌停日拒卖。

    卖出订单当前价 <= 跌停价（prev_close × lower_ratio）时拒绝。
    买入订单不检查（涨停不影响买入，由 LimitUpCheck 单独处理）。
    """

    def __init__(self, name: str = "LimitDownCheck") -> None:
        super().__init__(name)

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查卖出订单是否触及跌停价。"""
        # 仅卖出订单限制
        if order.direction is not Direction.SELL:
            return RiskCheckResult.passed_result(self.name)

        # 取前收盘价
        bar = context_data.get("bar")
        prev_close = _get_prev_close(bar)
        if prev_close is None or prev_close <= 0:
            logger.warning(
                "LimitDownCheck 跳过 %s：bar 缺少 prev_close，放行",
                order.symbol,
            )
            return RiskCheckResult.passed_result(self.name)

        # 取当前价
        current_price = context_data.get("current_price")
        if current_price is None or current_price <= 0:
            logger.warning(
                "LimitDownCheck 跳过 %s：缺少 current_price，放行",
                order.symbol,
            )
            return RiskCheckResult.passed_result(self.name)

        # 计算跌停价
        _, lower_ratio = _threshold_for_symbol(order.symbol)
        limit_down_price = prev_close * lower_ratio

        # 当前价 <= 跌停价 -> 跌停拒卖
        if current_price <= limit_down_price:
            return RiskCheckResult.rejected(
                self.name,
                f"{order.symbol} 跌停拒卖：当前价 {current_price:.4f} <= "
                f"跌停价 {limit_down_price:.4f}（prev_close={prev_close:.4f}, "
                f"下限={lower_ratio}）",
            )
        return RiskCheckResult.passed_result(self.name)
