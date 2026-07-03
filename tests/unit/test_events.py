"""
tests/unit/test_events.py
=========================

事件类型单元测试（src/core/events.py）。

覆盖：
    1. EventType 8 个枚举值
    2. Event 基类 timestamp 字段
    3. BarEvent 默认值与 extra 字段
    4. 各事件类的 type 类变量（ClassVar 覆盖）

运行：
    python -m pytest tests/unit/test_events.py -v
"""

from datetime import datetime

from src.core.events import (
    AccountEvent,
    BarEvent,
    Event,
    EventType,
    InitEvent,
    OrderEvent,
    StopEvent,
    TickEvent,
    TimerEvent,
    TradeEvent,
)


# ---------------------------------------------------------------------------
# 1. EventType 枚举
# ---------------------------------------------------------------------------


def test_event_type_has_8_types() -> None:
    """EventType 应有 8 个事件类型。"""
    expected = {"init", "bar", "tick", "order", "trade", "timer", "account", "stop"}
    actual = {e.value for e in EventType}
    assert actual == expected


# ---------------------------------------------------------------------------
# 2. Event 基类
# ---------------------------------------------------------------------------


def test_event_base_has_timestamp() -> None:
    """Event 基类必须有 timestamp 字段。"""
    ts = datetime(2024, 6, 1, 9, 30)
    e = Event(timestamp=ts)
    assert e.timestamp == ts


# ---------------------------------------------------------------------------
# 3. 各事件类的 type ClassVar
# ---------------------------------------------------------------------------


def test_init_event_type() -> None:
    """InitEvent.type 应为 INIT。"""
    e = InitEvent(timestamp=datetime.now())
    assert e.type is EventType.INIT


def test_bar_event_type_and_defaults() -> None:
    """BarEvent.type 为 BAR，默认值合理。"""
    bar = BarEvent(timestamp=datetime.now())
    assert bar.type is EventType.BAR
    assert bar.symbol == ""
    assert bar.open == 0.0
    assert bar.frequency == "1d"
    assert bar.extra == {}


def test_bar_event_with_extra() -> None:
    """BarEvent 可携带 extra 字典（如全市场数据）。"""
    bar = BarEvent(
        timestamp=datetime.now(),
        symbol="600000.SH",
        close=10.0,
        extra={"trade_date": "2024-06-01", "symbols_bars": {"600000.SH": {"close": 10.0}}},
    )
    assert bar.symbol == "600000.SH"
    assert bar.close == 10.0
    assert bar.extra["trade_date"] == "2024-06-01"
    assert "600000.SH" in bar.extra["symbols_bars"]


def test_tick_event_type() -> None:
    """TickEvent.type 应为 TICK。"""
    e = TickEvent(timestamp=datetime.now())
    assert e.type is EventType.TICK


def test_order_event_type() -> None:
    """OrderEvent.type 应为 ORDER。"""
    e = OrderEvent(timestamp=datetime.now())
    assert e.type is EventType.ORDER


def test_trade_event_type() -> None:
    """TradeEvent.type 应为 TRADE。"""
    e = TradeEvent(timestamp=datetime.now())
    assert e.type is EventType.TRADE


def test_timer_event_type() -> None:
    """TimerEvent.type 应为 TIMER。"""
    e = TimerEvent(timestamp=datetime.now())
    assert e.type is EventType.TIMER


def test_account_event_type() -> None:
    """AccountEvent.type 应为 ACCOUNT。"""
    e = AccountEvent(timestamp=datetime.now())
    assert e.type is EventType.ACCOUNT


def test_stop_event_type() -> None:
    """StopEvent.type 应为 STOP。"""
    e = StopEvent(timestamp=datetime.now())
    assert e.type is EventType.STOP
