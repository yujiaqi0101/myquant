"""
tests/unit/test_types.py
========================

核心数据结构单元测试（src/core/types.py）。

覆盖：
    1. Direction / OrderStatus / PositionDirection 枚举值
    2. Order 的 remaining_volume / is_active 状态判断
    3. Fill 的 turnover / total_cost 计算
    4. get_lot_size 板块规则（科创板 200 / 其他 100）
    5. Position 的 T+1 处理：
       - 买入后 today_bought 增加、available 不变
       - 卖出校验 available、超出抛 ValueError
       - settle_new_day 后 today_bought 清零、available 解冻
       - 均价加权计算
       - 卖出后清零逻辑

运行：
    python -m pytest tests/unit/test_types.py -v
"""

import pytest

from src.core.types import (
    Direction,
    Fill,
    OpenClose,
    Order,
    OrderStatus,
    Position,
    PositionDirection,
    get_lot_size,
)


# ---------------------------------------------------------------------------
# 1. 枚举值
# ---------------------------------------------------------------------------


def test_direction_enum_values() -> None:
    """Direction 枚举应有 buy/sell/target 三个值。"""
    assert Direction.BUY.value == "buy"
    assert Direction.SELL.value == "sell"
    assert Direction.TARGET.value == "target"


def test_order_status_enum_values() -> None:
    """OrderStatus 枚举应有 6 个状态。"""
    expected = {"pending", "submitted", "partial", "filled", "cancelled", "rejected"}
    actual = {s.value for s in OrderStatus}
    assert actual == expected


# ---------------------------------------------------------------------------
# 2. Order 状态判断
# ---------------------------------------------------------------------------


def test_order_remaining_volume() -> None:
    """remaining_volume = volume - filled_volume。"""
    order = Order(order_id="o1", volume=100.0, filled_volume=30.0)
    assert order.remaining_volume == 70.0


def test_order_is_active_pending() -> None:
    """PENDING/SUBMITTED/PARTIAL 状态视为活跃。"""
    for status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL):
        order = Order(order_id="o1", status=status)
        assert order.is_active is True


def test_order_is_active_terminated() -> None:
    """FILLED/CANCELLED/REJECTED 状态视为终结。"""
    for status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
        order = Order(order_id="o1", status=status)
        assert order.is_active is False


# ---------------------------------------------------------------------------
# 3. Fill 费用计算
# ---------------------------------------------------------------------------


def test_fill_turnover() -> None:
    """turnover = volume × price。"""
    fill = Fill(volume=100.0, price=10.0)
    assert fill.turnover == 1000.0


def test_fill_total_cost() -> None:
    """total_cost = commission + stamp_tax + transfer_fee。"""
    fill = Fill(volume=100.0, price=10.0, commission=5.0, stamp_tax=0.5, transfer_fee=0.02)
    assert fill.total_cost == 5.52


# ---------------------------------------------------------------------------
# 4. get_lot_size 板块规则
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("symbol,expected", [
    ("688001.SH", 200),      # 科创板
    ("SHSE.688001", 200),    # 科创板东财格式
    ("688001", 200),         # 科创板纯数字
    ("600000.SH", 100),      # 沪市主板
    ("000001.SZ", 100),      # 深市主板
    ("300001.SZ", 100),      # 创业板（不是科创板，100）
    ("002001.SZ", 100),      # 中小板
])
def test_get_lot_size(symbol: str, expected: int) -> None:
    """lot_size：688 开头 200，其他 100。"""
    assert get_lot_size(symbol) == expected


# ---------------------------------------------------------------------------
# 5. Position T+1 处理
# ---------------------------------------------------------------------------


def test_position_buy_today_bought_frozen() -> None:
    """买入后 today_bought 增加，available 不变（T+1 冻结）。"""
    pos = Position(symbol="600000.SH")
    pos.update_on_fill(Direction.BUY, 100, 10.0)
    # 数量、成本、均价正确
    assert pos.quantity == 100
    assert pos.avg_price == 10.0
    assert pos.cost == 1000.0
    # T+1：今日买入冻结，available 仍为 0
    assert pos.today_bought == 100
    assert pos.available == 0


def test_position_sell_exceeds_available_raises() -> None:
    """T+1 约束：卖出超过 available 抛 ValueError。"""
    pos = Position(symbol="600000.SH")
    pos.update_on_fill(Direction.BUY, 100, 10.0)
    # available=0，卖出应抛异常
    with pytest.raises(ValueError, match="卖出数量"):
        pos.update_on_fill(Direction.SELL, 100, 11.0)


def test_position_settle_new_day_unfreezes() -> None:
    """settle_new_day 后 today_bought 转入 available，可卖。"""
    pos = Position(symbol="600000.SH")
    pos.update_on_fill(Direction.BUY, 100, 10.0)
    assert pos.available == 0
    pos.settle_new_day()
    assert pos.today_bought == 0
    assert pos.available == 100
    # 解冻后可卖出
    pos.update_on_fill(Direction.SELL, 100, 11.0)
    assert pos.quantity == 0


def test_position_avg_price_weighted() -> None:
    """多次买入后均价为加权平均。"""
    pos = Position(symbol="600000.SH")
    pos.settle_new_day()  # 让第一次买入也可卖
    pos.update_on_fill(Direction.BUY, 100, 10.0)
    pos.update_on_fill(Direction.BUY, 100, 12.0)
    # 均价 = (100*10 + 100*12) / 200 = 11.0
    assert pos.quantity == 200
    assert pos.avg_price == 11.0
    assert pos.cost == 2200.0


def test_position_sell_clears_when_zero() -> None:
    """卖出后数量为 0 时，均价和成本清零（便于重新建仓）。"""
    pos = Position(symbol="600000.SH")
    # 先买入（today_bought=100, available=0）
    pos.update_on_fill(Direction.BUY, 100, 10.0)
    # T+1 解冻后才能卖出
    pos.settle_new_day()
    pos.update_on_fill(Direction.SELL, 100, 11.0)
    assert pos.quantity == 0
    assert pos.avg_price == 0.0
    assert pos.cost == 0.0


def test_position_update_market_price() -> None:
    """update_market_price 更新市值/盈亏。"""
    pos = Position(symbol="600000.SH")
    pos.settle_new_day()
    pos.update_on_fill(Direction.BUY, 100, 10.0)
    pos.update_market_price(12.0)
    assert pos.market_price == 12.0
    assert pos.market_value == 1200.0
    assert pos.pnl == 200.0           # 1200 - 1000
    assert pos.pnl_pct == 0.2         # 200 / 1000


def test_position_to_dict_serializable() -> None:
    """to_dict 返回完整字段。"""
    pos = Position(symbol="600000.SH")
    pos.settle_new_day()
    pos.update_on_fill(Direction.BUY, 100, 10.0)
    d = pos.to_dict()
    assert d["symbol"] == "600000.SH"
    assert d["quantity"] == 100
    assert d["avg_price"] == 10.0
    assert "today_bought" in d
    assert "available" in d
