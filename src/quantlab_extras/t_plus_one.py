"""
A 股 T+1 规则检查。

A 股市场规则：当日买入的股票，下一交易日才能卖出（T+1）。
本 Check 维护每个 symbol 的最近一次"买入日期"，
若当日尝试卖出当日买入的持仓，拒单。
"""

import logging
from typing import Dict

from src.quantlab.core.order import Order
from src.quantlab.risk.checks import RiskCheck


logger = logging.getLogger(__name__)


class TPlusOneCheck(RiskCheck):
    """A 股 T+1：当日买入当日不可卖。"""

    name = "T_PLUS_ONE"

    def __init__(self):
        # symbol -> 最近一次买入日期（字符串，ISO 格式）
        self._last_buy_date: Dict[str, str] = {}

    def check(self, order: Order, context: Dict) -> bool:
        # 只对卖出做限制
        if order.quantity >= 0:
            return True

        current_date = context.get("current_date")
        if current_date is None:
            # 没有日期信息 -> 不限制
            return True

        # 统一为字符串比较（兼容 date / datetime / str）
        current_date_str = str(current_date)
        last_buy = self._last_buy_date.get(order.symbol)

        if last_buy is not None and last_buy == current_date_str:
            logger.info(
                "T+1 reject sell %s (last_buy=%s, current=%s)",
                order.symbol,
                last_buy,
                current_date_str,
            )
            return False

        return True

    def update_after_fill(self, fill, context: Dict) -> None:
        """
        RiskManager 在每次 fill 之后调用。

        fill.quantity > 0 -> 记录最近一次买入日期
        fill.quantity < 0 -> 清理记录
        """
        current_date = context.get("current_date")
        if current_date is None:
            return

        current_date_str = str(current_date)
        symbol = getattr(fill, "symbol", None)
        if symbol is None:
            return

        qty = getattr(fill, "quantity", 0)
        if qty > 0:
            self._last_buy_date[symbol] = current_date_str
        elif qty < 0:
            # 卖出后清理（持仓已减少）
            if self._last_buy_date.get(symbol) == current_date_str:
                self._last_buy_date.pop(symbol, None)

    def reset(self) -> None:
        self._last_buy_date.clear()
