"""
src/core/execution/live.py
==========================

LiveExecution 实盘执行层（券商真实下单）。

将订单转发给券商适配器（broker_adapter）真实下单，订单状态由券商异步回报。
本类不负责撮合逻辑，仅负责：
    - 调用 broker_adapter.submit_order / cancel_order
    - 推送订单状态事件到 EventEngine

broker_adapter 需实现的接口（实盘接入时由具体券商SDK适配器实现）：
    - submit_order(order: Order) -> None
    - cancel_order(order_id: str) -> None

设计说明（设计文档 4.2 节）：
    实盘撮合由券商端完成，Pending 订单、T+1 校验等均由券商/交易所处理。
    本类 process_pending_orders 为空实现，成交回报由券商异步推送后由
    LiveEngine 转换为 TradeEvent。

用法：
    from src.core.execution.live import LiveExecution
    exec_ = LiveExecution(portfolio, event_engine, broker_adapter=broker)
    exec_.submit(order, current_price=10.0, current_time=clock)
"""

import logging
from datetime import datetime
from typing import Any, Dict

from src.core.event_engine import EventEngine
from src.core.execution.base import Execution
from src.core.types import Order, OrderStatus

logger = logging.getLogger(__name__)


class LiveExecution(Execution):
    """实盘执行层。

    Attributes:
        _broker: 券商适配器，提供 submit_order/cancel_order 接口
    """

    def __init__(self, portfolio: Any, event_engine: EventEngine, broker_adapter: Any) -> None:
        """初始化实盘执行层。

        Args:
            portfolio: Portfolio 实例（阶段4实现）
            event_engine: 事件总线实例
            broker_adapter: 券商适配器，需实现 submit_order/cancel_order
        """
        super().__init__(portfolio, event_engine)
        # 券商适配器（东财掘金实盘SDK或其他券商SDK）
        self._broker = broker_adapter

    def submit(self, order: Order, current_price: float, current_time: datetime) -> None:
        """提交订单到券商。

        直接转发给 broker_adapter，订单状态由券商异步回报。
        本地立即推送 SUBMITTED 事件，便于策略更新本地订单簿。

        Args:
            order: 订单对象
            current_price: 当前市价（实盘仅供参考，券商按价格类型撮合）
            current_time: 当前时间
        """
        # 转发券商下单（current_price 实盘由券商撮合时使用，此处仅透传）
        self._broker.submit_order(order)
        # 本地标记为已提交
        order.status = OrderStatus.SUBMITTED
        # 推送订单状态事件
        self._emit_order_event(order, current_time, OrderStatus.SUBMITTED, reason="已提交券商")

    def cancel(self, order_id: str) -> bool:
        """撤销券商订单。

        Args:
            order_id: 订单ID

        Returns:
            是否成功发送撤单请求（实际撤销结果由券商异步回报）
        """
        # 转发券商撤单
        self._broker.cancel_order(order_id)
        logger.info("撤单请求已发送至券商：order_id=%s", order_id)
        return True

    def process_pending_orders(self, current_time: datetime, open_prices: Dict[str, float]) -> None:
        """处理 Pending 订单。

        实盘由券商端处理 Pending 订单（如 next_open 类型），此处空实现。
        成交回报由券商异步推送，LiveEngine 负责转换为 TradeEvent。

        Args:
            current_time: 当前时间
            open_prices: 当日开盘价字典（实盘不使用）
        """
        # 实盘 Pending 订单由券商端处理，无需本地撮合
        pass
