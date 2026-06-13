"""
A 股新股过滤。

上市未满 N 个交易日的股票波动剧烈、容易破发，策略上一般回避。
默认阈值 60 天（≈3 个月），可通过 min_days 调整。
"""

import logging
from datetime import date, datetime
from typing import Dict, Union

from src.quantlab.core.order import Order
from src.quantlab.risk.checks import RiskCheck


logger = logging.getLogger(__name__)


def _to_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value).date()
    raise TypeError(f"unsupported date type: {type(value)}")


class NewStockCheck(RiskCheck):
    """上市 N 日内禁买。"""

    name = "NEW_STOCK"

    def __init__(self, min_days: int = 60):
        self.min_days = int(min_days)

    def check(self, order: Order, context: Dict) -> bool:
        if order.quantity <= 0:
            return True

        market = context.get("market_data", {})
        info = market.get(order.symbol)
        if not info:
            return True

        list_date_raw = info.get("list_date")
        if not list_date_raw:
            return True

        try:
            list_date = _to_date(list_date_raw)
        except (TypeError, ValueError):
            return True

        current_date_raw = context.get("current_date")
        if current_date_raw is None:
            return True

        try:
            current_date = _to_date(current_date_raw)
        except (TypeError, ValueError):
            return True

        listed_days = (current_date - list_date).days
        if listed_days < self.min_days:
            logger.info(
                "NewStock reject %s (listed %s days < %s)",
                order.symbol,
                listed_days,
                self.min_days,
            )
            return False
        return True
