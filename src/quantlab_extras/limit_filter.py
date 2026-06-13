"""
A 股涨跌停过滤。

按板块设置涨跌幅阈值：
    - 主板/中小板 (60/00 开头)：10%   -> 上 1.10 / 下 0.90
    - 创业板   (30 开头)      ：20%   -> 上 1.20 / 下 0.80
    - 科创板   (688 开头)     ：20%   -> 上 1.20 / 下 0.80
    - 北交所   (8/92 开头)    ：30%   -> 上 1.30 / 下 0.70

LimitUpCheck   : 涨停日拒买
LimitDownCheck : 跌停日拒卖
"""

import logging
from typing import Dict

from src.quantlab.core.order import Order
from src.quantlab.risk.checks import RiskCheck


logger = logging.getLogger(__name__)


# A 股板块涨跌幅阈值表
def _threshold_for_symbol(symbol: str) -> tuple:
    """
    返回 (upper_threshold, lower_threshold)；
    默认按主板 10% 处理。
    """
    code = str(symbol)

    if code.startswith(("8", "92", "43")):
        # 北交所 30%
        return 1.30, 0.70

    if code.startswith(("30", "688")):
        # 创业板 / 科创板 20%
        return 1.20, 0.80

    # 主板 / 中小板 10%（60/00/002/603/605 等）
    return 1.10, 0.90


class LimitUpCheck(RiskCheck):
    """涨停不买。"""

    name = "LIMIT_UP"

    def check(self, order: Order, context: Dict) -> bool:
        if order.quantity <= 0:
            # 卖出 / 平仓不限制
            return True

        market = context.get("market_data", {})
        info = market.get(order.symbol)
        if not info:
            logger.warning(
                "Limit check skipped, no pre_close for %s",
                order.symbol,
            )
            return True

        pre_close = info.get("pre_close")
        cur_close = info.get("close")
        if pre_close is None or cur_close is None:
            logger.warning(
                "Limit check skipped, no pre_close for %s",
                order.symbol,
            )
            return True

        upper, _ = _threshold_for_symbol(order.symbol)
        if cur_close >= pre_close * upper:
            return False  # 涨停 -> 拒买
        return True


class LimitDownCheck(RiskCheck):
    """跌停不卖。"""

    name = "LIMIT_DOWN"

    def check(self, order: Order, context: Dict) -> bool:
        if order.quantity >= 0:
            # 买入 / 开仓不限制
            return True

        market = context.get("market_data", {})
        info = market.get(order.symbol)
        if not info:
            logger.warning(
                "Limit check skipped, no pre_close for %s",
                order.symbol,
            )
            return True

        pre_close = info.get("pre_close")
        cur_close = info.get("close")
        if pre_close is None or cur_close is None:
            logger.warning(
                "Limit check skipped, no pre_close for %s",
                order.symbol,
            )
            return True

        _, lower = _threshold_for_symbol(order.symbol)
        if cur_close <= pre_close * lower:
            return False  # 跌停 -> 拒卖
        return True
