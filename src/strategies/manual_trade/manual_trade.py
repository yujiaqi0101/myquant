"""
自由买卖策略（手动交易入口）
================================

作为手动买卖股票的操作入口，通过参数指定目标股票、买卖方向和数量，
在收到首个 BarEvent 时执行一次交易指令后即完成。

参数：
    - symbol: 目标股票代码（如 600519.SH）
    - action: 操作方向（buy/sell）
    - volume: 交易数量（股）
    - price_type: 价格类型（market/limit，默认 market）

用法：
    python main.py paper run --account acc_001 --strategy manual_trade \
        --date 2024-06-28 \
        --param symbol=600519.SH --param action=buy --param volume=100

    python main.py paper run --account acc_001 --strategy manual_trade \
        --date 2024-06-28 \
        --param symbol=600519.SH --param action=sell --param volume=100
"""

import logging
from typing import Any, Dict, Optional

from src.core.context import Context
from src.core.events import Event, EventType
from src.core.strategy import Strategy, register_strategy

logger = logging.getLogger(__name__)


@register_strategy("manual_trade")
class ManualTradeStrategy(Strategy):
    """自由买卖策略（手动交易入口）。

    通过参数指定股票代码、买卖方向和数量，在首个 BarEvent 时执行交易。

    Parameters
    ----------
    symbol : str
        目标股票代码（如 600519.SH）
    action : str
        操作方向：buy（买入）/ sell（卖出）
    volume : int
        交易数量（股，买入须为 100 的倍数）
    price_type : str
        价格类型：market（市价）/ limit（限价），默认 market
    """

    name = "manual_trade"

    def __init__(self, params: Optional[Dict] = None) -> None:
        super().__init__(params)
        # 目标股票代码
        self.symbol: str = str(self.params.get("symbol", ""))
        # 操作方向
        self.action: str = str(self.params.get("action", "buy")).lower()
        # 交易数量
        self.volume: int = int(self.params.get("volume", 0))
        # 价格类型
        self.price_type: str = str(self.params.get("price_type", "market"))
        # 是否已执行
        self._executed: bool = False

    # ------------------------------------------------------------------
    # 生命周期回调
    # ------------------------------------------------------------------

    def on_init(self, context: Context) -> None:
        """初始化：校验参数。"""
        # 参数校验
        if not self.symbol:
            context.log("error", "自由买卖策略缺少 symbol 参数")
            return

        if self.action not in ("buy", "sell"):
            context.log("error", "action 参数无效，仅支持 buy/sell", action=self.action)
            return

        if self.volume <= 0:
            context.log("error", "volume 参数无效，必须大于 0", volume=self.volume)
            return

        if self.action == "buy" and self.volume % 100 != 0:
            context.log("warning", "买入数量非 100 的倍数，风控可能拒绝",
                        volume=self.volume)

        context.log("info", "自由买卖策略初始化",
                    symbol=self.symbol,
                    action=self.action,
                    volume=self.volume,
                    price_type=self.price_type)

    def on_event(self, event: Event, context: Context) -> None:
        """收到 BarEvent 时执行交易指令（仅执行一次）。"""
        if self._executed:
            return

        if event.type is not EventType.BAR:
            return

        # 参数校验失败时不执行
        if not self.symbol or self.action not in ("buy", "sell") or self.volume <= 0:
            return

        # 风险提示
        context.log("warning", "即将执行手动交易",
                    symbol=self.symbol,
                    action=self.action,
                    volume=self.volume)

        # 提交订单
        order_id = context.submit_order(
            symbol=self.symbol,
            direction=self.action,
            volume=self.volume,
            price_type=self.price_type,
        )

        self._executed = True
        context.log("info", "手动交易指令已提交",
                    order_id=order_id,
                    symbol=self.symbol,
                    action=self.action,
                    volume=self.volume)

    def on_stop(self, context: Context) -> None:
        """策略停止。"""
        if not self._executed:
            context.log("warning", "自由买卖策略未执行任何交易（可能参数缺失或无 BarEvent）")
        else:
            context.log("info", "自由买卖策略执行完毕")
