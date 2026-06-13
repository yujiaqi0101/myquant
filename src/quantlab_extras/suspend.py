"""
A 股停牌过滤。

停牌期间无法撮合，所有买入/卖出都要拒掉。
suspend_flag 来自 context['market_data'][symbol]['suspend_flag']
    0 = 正常交易
    非 0 = 停牌
"""

import logging
from typing import Dict

from src.quantlab.core.order import Order
from src.quantlab.risk.checks import RiskCheck


logger = logging.getLogger(__name__)


class SuspendCheck(RiskCheck):
    """停牌期间禁止交易。"""

    name = "SUSPEND"

    def check(self, order: Order, context: Dict) -> bool:
        market = context.get("market_data", {})
        info = market.get(order.symbol)
        if not info:
            return True

        suspend_flag = info.get("suspend_flag", 0)
        if suspend_flag and suspend_flag != 0:
            logger.info(
                "Suspend reject %s (flag=%s)",
                order.symbol,
                suspend_flag,
            )
            return False
        return True
