"""
tests/unit/test_risk_checks.py
==============================

A 股风控 Check 单元测试。

覆盖：
    1. LimitUpCheck 涨停买入过滤（主板10%/创业板20%/科创板20%/北交所30%）
    2. LimitDownCheck 跌停卖出过滤
    3. LotSizeCheck lot_size 整数倍（科创板200/其他100）
    4. MaxOrderQtyCheck 单笔最大量
    5. MaxPositionPctCheck 单持仓仓位上限
    6. MaxPositionsCheck 持仓数量上限
    7. DailyStopLossCheck 日亏急停
    8. build_ashare_risk_manager 工厂：11 个 Check 顺序
    9. RiskManager 短路逻辑

运行：
    python -m pytest tests/unit/test_risk_checks.py -v
"""

from typing import Any, Dict

import pytest

from src.core.risk.checks import RiskCheckResult, get_field
from src.core.risk.manager import RiskManager
from src.core.types import Direction, Order, OrderStatus
from src.risk_checks.factory import (
    DailyStopLossCheck,
    LotSizeCheck,
    MaxOrderQtyCheck,
    MaxPositionPctCheck,
    MaxPositionsCheck,
    build_ashare_risk_manager,
)
from src.risk_checks.limit_filter import LimitDownCheck, LimitUpCheck
from src.risk_checks.st_filter import STFilterCheck


# ---------------------------------------------------------------------------
# 1. LimitUpCheck 涨停过滤
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("symbol,prev_close,upper_ratio", [
    ("600000.SH", 10.0, 1.10),    # 主板 10%
    ("000001.SZ", 10.0, 1.10),    # 深市主板 10%
    ("300001.SZ", 10.0, 1.20),    # 创业板 20%
    ("688001.SH", 10.0, 1.20),    # 科创板 20%
])
def test_limit_up_check_rejects_at_limit(
    symbol: str, prev_close: float, upper_ratio: float
) -> None:
    """涨停价买入应被拒绝。"""
    check = LimitUpCheck()
    limit_price = prev_close * upper_ratio
    order = Order(
        order_id="o1", symbol=symbol,
        direction=Direction.BUY, volume=100, price_type="market",
    )
    ctx = {
        "bar": {"prev_close": prev_close},
        "current_price": limit_price,  # 恰好触及涨停价
    }
    result = check.check(order, ctx)
    assert result.passed is False
    assert "涨停" in result.reason


def test_limit_up_check_passes_below_limit() -> None:
    """未触及涨停价的买入应放行。"""
    check = LimitUpCheck()
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    ctx = {"bar": {"prev_close": 10.0}, "current_price": 10.5}
    result = check.check(order, ctx)
    assert result.passed is True


def test_limit_up_check_ignores_sell_order() -> None:
    """卖出订单不检查涨停（仅买）。"""
    check = LimitUpCheck()
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.SELL, volume=100,
    )
    ctx = {"bar": {"prev_close": 10.0}, "current_price": 11.0}  # 涨停价
    result = check.check(order, ctx)
    assert result.passed is True


def test_limit_up_check_degrades_when_no_prev_close() -> None:
    """bar 缺少 prev_close 时安全降级放行。"""
    check = LimitUpCheck()
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    ctx = {"bar": {}, "current_price": 11.0}
    result = check.check(order, ctx)
    assert result.passed is True


# ---------------------------------------------------------------------------
# 2. LimitDownCheck 跌停过滤
# ---------------------------------------------------------------------------


def test_limit_down_check_rejects_at_limit() -> None:
    """跌停价卖出应被拒绝。"""
    check = LimitDownCheck()
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.SELL, volume=100,
    )
    ctx = {"bar": {"prev_close": 10.0}, "current_price": 9.0}  # 跌停价
    result = check.check(order, ctx)
    assert result.passed is False
    assert "跌停" in result.reason


def test_limit_down_check_ignores_buy_order() -> None:
    """买入订单不检查跌停（仅卖）。"""
    check = LimitDownCheck()
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    ctx = {"bar": {"prev_close": 10.0}, "current_price": 9.0}
    result = check.check(order, ctx)
    assert result.passed is True


# ---------------------------------------------------------------------------
# 3. LotSizeCheck lot_size 整数倍
# ---------------------------------------------------------------------------


def test_lot_size_check_passes_main_board_100() -> None:
    """主板 100 股整数倍放行。"""
    check = LotSizeCheck()
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    result = check.check(order, {})
    assert result.passed is True


def test_lot_size_check_rejects_main_board_150() -> None:
    """主板 150 股非整数倍拒绝。"""
    check = LotSizeCheck()
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=150,
    )
    result = check.check(order, {})
    assert result.passed is False
    assert "100" in result.reason


def test_lot_size_check_passes_kcb_200() -> None:
    """科创板 200 股整数倍放行。"""
    check = LotSizeCheck()
    order = Order(
        order_id="o1", symbol="688001.SH",
        direction=Direction.BUY, volume=200,
    )
    result = check.check(order, {})
    assert result.passed is True


def test_lot_size_check_rejects_kcb_100() -> None:
    """科创板 100 股非整数倍拒绝（必须 200 倍数）。"""
    check = LotSizeCheck()
    order = Order(
        order_id="o1", symbol="688001.SH",
        direction=Direction.BUY, volume=100,
    )
    result = check.check(order, {})
    assert result.passed is False
    assert "200" in result.reason


# ---------------------------------------------------------------------------
# 4. MaxOrderQtyCheck 单笔最大量
# ---------------------------------------------------------------------------


def test_max_order_qty_check_rejects_over_limit() -> None:
    """超过单笔上限拒绝。"""
    check = MaxOrderQtyCheck(max_qty=10000)
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=20000,
    )
    result = check.check(order, {})
    assert result.passed is False


def test_max_order_qty_check_passes_under_limit() -> None:
    """未超上限放行。"""
    check = MaxOrderQtyCheck(max_qty=10000)
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=5000,
    )
    result = check.check(order, {})
    assert result.passed is True


# ---------------------------------------------------------------------------
# 5. MaxPositionPctCheck 单持仓仓位上限
# ---------------------------------------------------------------------------


def test_max_position_pct_check_rejects_over_pct() -> None:
    """买入后仓位占比超限拒绝。"""
    check = MaxPositionPctCheck(max_pct=0.30)
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=40000,  # 40000 × 10 = 40万，占比 40%
    )
    ctx = {
        "current_price": 10.0,
        "account": {"total": 1_000_000.0},
        "position": {"quantity": 0},
    }
    result = check.check(order, ctx)
    assert result.passed is False


def test_max_position_pct_check_passes_under_pct() -> None:
    """买入后仓位占比未超限放行。"""
    check = MaxPositionPctCheck(max_pct=0.30)
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=20000,  # 20万，占比 20%
    )
    ctx = {
        "current_price": 10.0,
        "account": {"total": 1_000_000.0},
        "position": {"quantity": 0},
    }
    result = check.check(order, ctx)
    assert result.passed is True


# ---------------------------------------------------------------------------
# 6. MaxPositionsCheck 持仓数量上限
# ---------------------------------------------------------------------------


def test_max_positions_check_rejects_new_position_when_full() -> None:
    """已达持仓上限时买入新股票拒绝。"""
    check = MaxPositionsCheck(max_count=2)
    order = Order(
        order_id="o1", symbol="600000.SH",  # 新股票
        direction=Direction.BUY, volume=100,
    )
    # 当前已持 2 只
    ctx = {
        "portfolio": {
            "000001.SZ": {"quantity": 100},
            "000002.SZ": {"quantity": 200},
        },
        "position": None,  # 600000.SH 无持仓（新开仓）
    }
    result = check.check(order, ctx)
    assert result.passed is False


def test_max_positions_check_passes_adding_to_existing() -> None:
    """加仓已有股票不受持仓数量限制。"""
    check = MaxPositionsCheck(max_count=2)
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    ctx = {
        "portfolio": {
            "600000.SH": {"quantity": 100},  # 已持有
            "000001.SZ": {"quantity": 100},
        },
        "position": {"quantity": 100},  # 已有持仓
    }
    result = check.check(order, ctx)
    assert result.passed is True


# ---------------------------------------------------------------------------
# 7. DailyStopLossCheck 日亏急停
# ---------------------------------------------------------------------------


def test_daily_stop_loss_check_rejects_when_loss_exceeds() -> None:
    """当日亏损超阈值拒绝。"""
    check = DailyStopLossCheck(threshold=-0.05)
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    ctx = {"account": {"daily_pnl_pct": -0.06}}  # 亏 6%
    result = check.check(order, ctx)
    assert result.passed is False


def test_daily_stop_loss_check_passes_when_profit() -> None:
    """当日盈利时放行。"""
    check = DailyStopLossCheck(threshold=-0.05)
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    ctx = {"account": {"daily_pnl_pct": 0.02}}  # 盈 2%
    result = check.check(order, ctx)
    assert result.passed is True


# ---------------------------------------------------------------------------
# 8. STFilterCheck ST 过滤
# ---------------------------------------------------------------------------


def test_st_filter_check_rejects_st_stock() -> None:
    """ST 股票买入拒绝。"""
    check = STFilterCheck()
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    ctx = {"stock_info": {"is_st": 1}}
    result = check.check(order, ctx)
    assert result.passed is False


def test_st_filter_check_passes_normal_stock() -> None:
    """正常股票放行。"""
    check = STFilterCheck()
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    ctx = {"stock_info": {"is_st": 0}}
    result = check.check(order, ctx)
    assert result.passed is True


# ---------------------------------------------------------------------------
# 9. RiskManager 短路逻辑
# ---------------------------------------------------------------------------


def test_risk_manager_short_circuits_on_first_failure() -> None:
    """任一 Check 不通过即短路返回，不再执行后续。"""
    rm = RiskManager()
    rm.add_check(LimitUpCheck())
    rm.add_check(LotSizeCheck())

    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    ctx = {
        "bar": {"prev_close": 10.0},
        "current_price": 11.0,  # 涨停
    }
    result = rm.check_order(order, ctx)
    assert result.passed is False
    assert result.check_name == "LimitUpCheck"


def test_risk_manager_passes_all_checks() -> None:
    """所有 Check 通过返回 passed=True。"""
    rm = RiskManager()
    rm.add_check(LotSizeCheck())
    order = Order(
        order_id="o1", symbol="600000.SH",
        direction=Direction.BUY, volume=100,
    )
    result = rm.check_order(order, {})
    assert result.passed is True


def test_risk_manager_no_checks_passes() -> None:
    """无 Check 时直接放行。"""
    rm = RiskManager()
    order = Order(order_id="o1", symbol="600000.SH")
    result = rm.check_order(order, {})
    assert result.passed is True


# ---------------------------------------------------------------------------
# 10. build_ashare_risk_manager 工厂
# ---------------------------------------------------------------------------


def test_build_ashare_risk_manager_has_11_checks() -> None:
    """默认工厂应添加 11 个 Check。"""
    rm = build_ashare_risk_manager()
    assert len(rm) == 11
    names = rm.get_check_names()
    # 包含全部 11 个 Check 名
    assert "LimitUpCheck" in names
    assert "LimitDownCheck" in names
    assert "STFilterCheck" in names
    assert "NewStockCheck" in names
    assert "SuspendCheck" in names
    assert "TPlusOneCheck" in names
    assert "MaxOrderQtyCheck" in names
    assert "LotSizeCheck" in names
    assert "MaxPositionPctCheck" in names
    assert "MaxPositionsCheck" in names
    assert "DailyStopLossCheck" in names


def test_build_ashare_risk_manager_disable_portfolio_check() -> None:
    """禁用组合级 Check 后应为 8 个 Check（6法定+2订单）。"""
    rm = build_ashare_risk_manager(enable_portfolio_check=False)
    assert len(rm) == 8
    names = rm.get_check_names()
    assert "MaxPositionPctCheck" not in names
    assert "MaxPositionsCheck" not in names
    assert "DailyStopLossCheck" not in names


def test_get_field_helper_dict() -> None:
    """get_field 兼容 dict。"""
    assert get_field({"a": 1}, "a") == 1
    assert get_field({"a": 1}, "b", "default") == "default"


def test_get_field_helper_object() -> None:
    """get_field 兼容对象属性。"""

    class Obj:
        x = 10

    assert get_field(Obj(), "x") == 10
    assert get_field(Obj(), "y", "default") == "default"


def test_get_field_helper_none() -> None:
    """get_field 处理 None。"""
    assert get_field(None, "x", "default") == "default"
