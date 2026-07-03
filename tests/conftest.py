"""
tests/conftest.py
=================

pytest 共享 fixtures（事件驱动内核测试公用对象）。

提供以下 fixtures：
    - initial_capital / sample_symbol / sample_symbol_kcb  基础常量
    - portfolio              空 Portfolio（指定初始资金）
    - event_engine           同步 EventEngine（backtest 模式）
    - make_order             工厂 fixture，按参数构造 Order
    - make_fill              工厂 fixture，按参数构造 Fill

设计原则：
    1. 不依赖数据库/外部 API，纯内存对象
    2. 工厂 fixture 返回构造函数，测试按需调用，避免状态污染
    3. 不写入任何数据到数据库（遵循项目规则1）

用法：
    def test_xxx(portfolio, make_order):
        order = make_order(symbol="600000.SH", direction="buy", volume=100)
        ...
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pytest

# 将项目根目录加入 sys.path（确保 src.* 可导入）
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.event_engine import EventEngine
from src.core.portfolio import Portfolio
from src.core.types import Direction, Fill, Order, OrderStatus


# ---------------------------------------------------------------------------
# 常量 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def initial_capital() -> float:
    """默认初始资金 100 万。"""
    return 1_000_000.0


@pytest.fixture
def sample_symbol() -> str:
    """主板股票代码（用于 lot_size=100 测试）。"""
    return "600000.SH"


@pytest.fixture
def sample_symbol_kcb() -> str:
    """科创板股票代码（用于 lot_size=200 测试）。"""
    return "688001.SH"


@pytest.fixture
def sample_symbol_cyb() -> str:
    """创业板股票代码（用于涨跌停 20% 测试）。"""
    return "300001.SZ"


# ---------------------------------------------------------------------------
# 核心 fixtures：Portfolio / EventEngine
# ---------------------------------------------------------------------------


@pytest.fixture
def portfolio(initial_capital: float) -> Portfolio:
    """空 Portfolio 实例（无持仓、无订单），初始资金 100 万。"""
    return Portfolio(initial_capital=initial_capital)


@pytest.fixture
def event_engine() -> EventEngine:
    """同步 EventEngine（backtest 模式）。

    backtest 模式下事件同步分发，便于测试断言。
    """
    return EventEngine(mode="backtest")


# ---------------------------------------------------------------------------
# 工厂 fixtures：Order / Fill
# ---------------------------------------------------------------------------


@pytest.fixture
def make_order() -> Callable[..., Order]:
    """Order 工厂 fixture。

    用法：
        order = make_order(symbol="600000.SH", direction="buy", volume=100, price_type="market")
    """

    def _make(
        order_id: str = "test_o1",
        symbol: str = "600000.SH",
        direction: str = "buy",
        volume: float = 100.0,
        target_weight: float = None,
        price_type: str = "market",
        price: float = None,
        status: OrderStatus = OrderStatus.PENDING,
    ) -> Order:
        return Order(
            order_id=order_id,
            symbol=symbol,
            direction=Direction(direction),
            volume=float(volume),
            target_weight=target_weight,
            price_type=price_type,
            price=price,
            status=status,
            created_time=datetime(2024, 6, 1, 9, 30, 0),
        )

    return _make


@pytest.fixture
def make_fill() -> Callable[..., Fill]:
    """Fill 工厂 fixture。

    用法：
        fill = make_fill(symbol="600000.SH", direction="buy", volume=100, price=10.0)
    """

    def _make(
        fill_id: str = "test_f1",
        order_id: str = "test_o1",
        symbol: str = "600000.SH",
        direction: str = "buy",
        volume: float = 100.0,
        price: float = 10.0,
        commission: float = 5.0,
        stamp_tax: float = 0.0,
        transfer_fee: float = 0.02,
        fill_time: datetime = None,
    ) -> Fill:
        return Fill(
            fill_id=fill_id,
            order_id=order_id,
            symbol=symbol,
            direction=Direction(direction),
            volume=float(volume),
            price=float(price),
            commission=commission,
            stamp_tax=stamp_tax,
            transfer_fee=transfer_fee,
            fill_time=fill_time or datetime(2024, 6, 1, 10, 0, 0),
        )

    return _make
