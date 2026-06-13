"""
V2.5 Live — BrokerAdapter

实盘 / Paper 共用同一接口
策略层不感知底层是 IBKR / Binance / CTP / Paper

V1 接口：
    connect()
    disconnect()
    submit_order(order) -> order_id
    cancel_order(order_id)
    get_positions() -> Dict[symbol, Position]
    get_account() -> AccountState
    on_fill(callback)  # 异步成交回报
"""

from abc import (
    ABC,
    abstractmethod,
)
from dataclasses import dataclass
from typing import (
    Callable,
    Dict,
    Optional,
)


@dataclass
class AccountState:
    cash: float = 0.0
    equity: float = 0.0
    margin_used: float = 0.0
    buying_power: float = 0.0


class BrokerAdapter(ABC):
    """
    所有 broker 都实现这个 ABC
    策略只调 ABC 方法
    换 broker 不动策略代码
    """

    name: str = "BASE"

    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def submit_order(self, order) -> str:
        # 返回 broker 内部 order_id
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        ...

    @abstractmethod
    def get_positions(self) -> Dict:
        # Dict[symbol, qty]
        ...

    @abstractmethod
    def get_account(self) -> AccountState:
        ...

    def on_fill(self, callback: Callable) -> None:
        # 异步回报注册
        # V1 简化：同步也可
        self._fill_callback = callback
