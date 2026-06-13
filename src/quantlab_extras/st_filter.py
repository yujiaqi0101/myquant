"""
A 股 ST / *ST / 退市股过滤。

约定：
    - 股票名含 "ST"   -> 拒单
    - 股票名含 "*ST"  -> 拒单
    - 股票名前 1 字符为 "退" -> 拒单
"""

import logging
from typing import Dict

from src.quantlab.core.order import Order
from src.quantlab.risk.checks import RiskCheck


logger = logging.getLogger(__name__)


class STFilterCheck(RiskCheck):
    """拒绝买入或卖出 ST/*ST/退市股。"""

    name = "ST_FILTER"

    @staticmethod
    def _is_st(name: str) -> bool:
        if not name:
            return False
        if "ST" in name.upper():
            return True
        if name.startswith("退"):
            return True
        return False

    def check(self, order: Order, context: Dict) -> bool:
        stock_info = context.get("stock_info", {})
        info = stock_info.get(order.symbol)
        if not info:
            return True

        name = info.get("name", "")
        if self._is_st(name):
            logger.info(
                "STFilter reject %s (name=%s)",
                order.symbol,
                name,
            )
            return False
        return True
