"""
V2.5 Live — OrderManager

订单状态机
状态：
    NEW      - 已提交未成交
    PARTIAL  - 部分成交（V1 简化：仍当 FILLED 处理）
    FILLED   - 全部成交
    CANCELLED- 已撤单
    REJECTED - 拒单

V1 责任：
    1) 收 execution.generate_orders() 的 Order
    2) 调 risk_manager.check(order)  通过才下发
    3) 调 broker.submit_order(order)
    4) 跟踪状态：NEW → FILLED
    5) 收到成交回报 → 回调给 Portfolio / TradeBook

不做：
    - 复杂撮合队列
    - 拆单 / 改单
    - 跨 broker 路由
"""

from dataclasses import (
    dataclass,
    field,
)
from datetime import datetime
from enum import Enum
from typing import (
    Callable,
    Dict,
    List,
    Optional,
)

from ..core.order import Order
from ..core.fill import Fill
from .broker import BrokerAdapter


class OrderState(str, Enum):
    NEW = "NEW"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class ManagedOrder:
    """
    OrderManager 跟踪的订单
    区别于裸 Order：
        - state       状态
        - broker_id   交易所 ID
        - filled_qty  已成交数量
        - created_at  本地时间戳
        - updated_at  最后更新时间
    """

    order: Order
    state: OrderState = OrderState.NEW
    broker_id: str = ""
    filled_qty: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    reject_reason: str = ""


class OrderManager:
    """
    V1 简化：
        - 提交后立即按市价处理（同步成交）
        - 不做异步轮询
        - 也不做事件驱动

    真实 broker：
        - 接 on_fill 回填 broker_id
        - 更新 state / filled_qty
    """

    def __init__(self, broker: BrokerAdapter):
        self.broker = broker
        self._orders: Dict[str, ManagedOrder] = {}
        self._order_seq = 0
        self._fill_callbacks: List[Callable] = []

    # ----------------
    # 回调注册
    # ----------------
    def on_fill(self, callback: Callable) -> None:
        # 注册成交回报
        self._fill_callbacks.append(callback)

    # ----------------
    # 提交
    # ----------------
    def submit(self, order: Order) -> Optional[ManagedOrder]:
        """
        1) 生成本地 ID
        2) 调 broker.submit_order
        3) 返回 ManagedOrder
        4) V1 简化：同步转给 broker 立即成交
        """
        self._order_seq += 1
        local_id = f"L{self._order_seq:06d}"

        mo = ManagedOrder(
            order=order,
            state=OrderState.NEW,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        try:
            broker_id = self.broker.submit_order(order)
            mo.broker_id = broker_id
        except Exception as e:
            mo.state = OrderState.REJECTED
            mo.reject_reason = str(e)
            self._orders[local_id] = mo
            return mo

        self._orders[local_id] = mo
        return mo

    def cancel(self, local_id: str) -> bool:
        mo = self._orders.get(local_id)
        if mo is None:
            return False
        if mo.state in (
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
        ):
            return False

        ok = self.broker.cancel_order(mo.broker_id)
        if ok:
            mo.state = OrderState.CANCELLED
            mo.updated_at = datetime.utcnow()
        return ok

    # ----------------
    # 成交回报
    # ----------------
    def report_fill(
        self,
        local_id: str,
        fill: Fill,
    ) -> None:
        """
        broker 报来成交后调用
        V1 简化：
            qty 全成 → FILLED
        """
        mo = self._orders.get(local_id)
        if mo is None:
            return

        mo.filled_qty = fill.quantity
        mo.updated_at = datetime.utcnow()
        mo.state = (
            OrderState.PARTIAL
            if abs(fill.quantity)
            < abs(mo.order.quantity)
            else OrderState.FILLED
        )

        for cb in self._fill_callbacks:
            try:
                cb(fill, mo)
            except Exception:
                pass

    # ----------------
    # 查询
    # ----------------
    def get(self, local_id: str) -> Optional[ManagedOrder]:
        return self._orders.get(local_id)

    def all(self) -> List[ManagedOrder]:
        return list(self._orders.values())

    def open(self) -> List[ManagedOrder]:
        return [
            mo for mo in self._orders.values()
            if mo.state == OrderState.NEW
        ]

    def __len__(self) -> int:
        return len(self._orders)
