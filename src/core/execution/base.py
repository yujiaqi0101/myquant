"""
src/core/execution/base.py
==========================

Execution 执行层抽象基类模块。

Execution 是订单撮合的统一抽象，屏蔽回测/模拟盘/实盘三种模式的撮合差异：
    - 回测/模拟盘：SimulatedExecution 内存撮合
    - 实盘：LiveExecution 转发券商真实下单

核心职责（设计文档 4.2 节）：
    1. 接收风控管线通过后的订单并撮合/转发
    2. 计算A股交易费用（佣金/印花税/过户费）
    3. 通过 EventEngine 推送 OrderEvent 和 TradeEvent

A股费用规则（本基类内置默认费率）：
    - 佣金：双向，费率 0.025%，最低 5 元
    - 印花税：仅卖出，费率 0.05%
    - 过户费：双向，费率 0.002%
    - lot_size：按 symbol 判断（688 开头 200 股/手，其他 100 股/手），
      实际取值用 src.core.types.get_lot_size(symbol)，不在此硬编码

依赖（阶段4由 Portfolio 实现，本阶段仅调用接口）：
    - portfolio.get_account() -> dict（含 total 字段）
    - portfolio.get_position(symbol) -> Optional[dict]（含 quantity/available 字段）
    - portfolio.update_on_fill(order, fill_price, total_cost) -> Optional[Fill]

用法：
    from src.core.execution.simulated import SimulatedExecution
    exec_ = SimulatedExecution(portfolio, event_engine, mode="backtest")
    exec_.submit(order, current_price=10.0, current_time=clock)
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional

from src.core.event_engine import EventEngine
from src.core.events import OrderEvent, TradeEvent
from src.core.types import Direction, Fill, Order, OrderStatus


class Execution(ABC):
    """执行层抽象基类。

    子类必须实现 3 个抽象方法：submit / cancel / process_pending_orders。
    费用计算和事件推送为具体方法，子类直接复用。

    Attributes:
        _portfolio: Portfolio 实例（阶段4实现，提供账户/持仓查询与更新接口）
        _event_engine: 事件总线，用于推送 OrderEvent/TradeEvent
        commission_rate: 佣金费率（双向），默认 0.025%
        stamp_tax_rate: 印花税费率（仅卖出），默认 0.05%
        transfer_fee_rate: 过户费费率（双向），默认 0.002%
        min_commission: 佣金最低收费（元），默认 5.0
    """

    def __init__(self, portfolio: Any, event_engine: EventEngine) -> None:
        """初始化执行层。

        Args:
            portfolio: Portfolio 实例（阶段4实现）
            event_engine: 事件总线实例
        """
        # Portfolio 实例，提供 get_account/get_position/update_on_fill 接口
        self._portfolio = portfolio
        # 事件总线，推送订单/成交事件
        self._event_engine = event_engine

        # A股费用配置（默认值，子类可按需覆盖）
        self.commission_rate: float = 0.00025   # 佣金费率：双向 0.025%
        self.stamp_tax_rate: float = 0.0005     # 印花税费率：仅卖出 0.05%
        self.transfer_fee_rate: float = 0.00002 # 过户费费率：双向 0.002%
        self.min_commission: float = 5.0        # 佣金最低收费：5 元
        # 注：lot_size 按 symbol 判断，688开头200股/手，其他100股/手
        # 实际取值用 src.core.types.get_lot_size(symbol)，不在此处硬编码

    # ------------------------------------------------------------------
    # 抽象方法（子类必须实现）
    # ------------------------------------------------------------------

    @abstractmethod
    def submit(self, order: Order, current_price: float, current_time: datetime) -> None:
        """提交订单到撮合/券商。

        子类根据价格类型决定即时撮合或登记 Pending：
            - market/limit：即时撮合
            - next_open：登记 Pending，等待次日开盘
            - target_percent：折算为目标数量后转 buy/sell

        Args:
            order: 订单对象
            current_price: 当前市价（用于目标权重计算和市价撮合）
            current_time: 当前时间（事件时间戳）
        """
        raise NotImplementedError

    @abstractmethod
    def cancel(self, order_id: str) -> bool:
        """撤销订单。

        Args:
            order_id: 订单ID

        Returns:
            是否撤销成功
        """
        raise NotImplementedError

    @abstractmethod
    def process_pending_orders(self, current_time: datetime, open_prices: Dict[str, float]) -> None:
        """处理 Pending 订单（次日开盘撮合）。

        回测/模拟盘在每日开盘时调用，用开盘价撮合所有 next_open 类型的 Pending 订单。
        实盘由券商端处理，空实现。

        Args:
            current_time: 当前时间
            open_prices: 当日开盘价字典 {symbol: price}
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # A股费用计算（具体方法，子类复用）
    # ------------------------------------------------------------------

    def _calculate_cost(self, direction: Direction, volume: float, price: float) -> Dict[str, float]:
        """计算A股交易费用。

        规则：
            - 佣金：双向，按费率计算，最低 min_commission 元
            - 印花税：仅卖出，按费率计算
            - 过户费：双向，按费率计算

        Args:
            direction: 买卖方向（BUY/SELL）
            volume: 成交数量（股）
            price: 成交价

        Returns:
            费用字典：{commission, stamp_tax, transfer_fee, total_cost}
        """
        # 成交金额 = 数量 × 价格
        turnover = volume * price
        # 佣金：双向，最低 min_commission 元
        commission = max(turnover * self.commission_rate, self.min_commission)
        # 印花税：仅卖出
        stamp_tax = turnover * self.stamp_tax_rate if direction is Direction.SELL else 0.0
        # 过户费：双向
        transfer_fee = turnover * self.transfer_fee_rate
        # 费用合计
        total_cost = commission + stamp_tax + transfer_fee
        return {
            "commission": commission,
            "stamp_tax": stamp_tax,
            "transfer_fee": transfer_fee,
            "total_cost": total_cost,
        }

    # ------------------------------------------------------------------
    # 事件推送（具体方法，子类复用）
    # ------------------------------------------------------------------

    def _emit_order_event(
        self,
        order: Order,
        current_time: datetime,
        status: OrderStatus,
        reason: Optional[str] = None,
    ) -> None:
        """推送订单状态变化事件（OrderEvent）到事件总线。

        Args:
            order: 订单对象（状态已更新）
            current_time: 事件时间戳
            status: 订单状态
            reason: 拒绝/撤销原因（可选）
        """
        event = OrderEvent(
            timestamp=current_time,
            order_id=order.order_id,
            symbol=order.symbol,
            direction=order.direction.value,
            volume=order.volume,
            filled_volume=order.filled_volume,
            avg_fill_price=order.filled_price,
            status=status.value,
            reason=reason,
        )
        self._event_engine.publish(event)

    def _emit_trade_event(self, fill: Fill, current_time: datetime) -> None:
        """推送成交回报事件（TradeEvent）到事件总线。

        Args:
            fill: 成交记录（含费用明细）
            current_time: 事件时间戳
        """
        event = TradeEvent(
            timestamp=current_time,
            fill_id=fill.fill_id,
            order_id=fill.order_id,
            symbol=fill.symbol,
            direction=fill.direction.value,
            volume=fill.volume,
            price=fill.price,
            commission=fill.commission,
            stamp_tax=fill.stamp_tax,
            transfer_fee=fill.transfer_fee,
        )
        self._event_engine.publish(event)
