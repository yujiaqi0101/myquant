"""
tests/unit/test_portfolio.py
============================

Portfolio 持仓管理单元测试（src/core/portfolio.py）。

覆盖：
    1. 初始状态（现金/无持仓）
    2. apply_fill 买入：持仓 + 现金扣减 + FIFO OpenLot
    3. apply_fill 卖出：持仓减少 + 现金回笼 + FIFO 配对生成 Trade
    4. T+1 处理：settle_new_day 解冻
    5. update_market_prices 更新市值
    6. get_account 账户快照
    7. snapshot 净值曲线追加
    8. get_position / get_active_positions 查询

运行：
    python -m pytest tests/unit/test_portfolio.py -v
"""

from datetime import datetime

import pytest

from src.core.portfolio import AccountInfo, Portfolio
from src.core.types import Direction, Fill


# ---------------------------------------------------------------------------
# 1. 初始状态
# ---------------------------------------------------------------------------


def test_portfolio_initial_state(portfolio: Portfolio, initial_capital: float) -> None:
    """初始状态：现金=初始资金，无持仓，无订单。"""
    assert portfolio.cash == initial_capital
    assert portfolio.frozen == 0.0
    assert portfolio.market_value == 0.0
    assert portfolio.total_value == initial_capital
    assert portfolio.positions == {}
    assert portfolio.orders == []
    assert portfolio.fills == []
    assert portfolio.trades == []


# ---------------------------------------------------------------------------
# 2. apply_fill 买入
# ---------------------------------------------------------------------------


def test_apply_fill_buy_updates_position_and_cash(
    portfolio: Portfolio, make_fill: callable
) -> None:
    """买入成交：持仓增加，现金扣减（金额+费用）。"""
    fill = make_fill(
        symbol="600000.SH",
        direction="buy",
        volume=100,
        price=10.0,
        commission=5.0,
        stamp_tax=0.0,
        transfer_fee=0.02,
    )
    portfolio.apply_fill(fill)

    # 持仓
    pos = portfolio.get_position("600000.SH")
    assert pos is not None
    assert pos.quantity == 100
    assert pos.avg_price == 10.0
    assert pos.today_bought == 100   # T+1 冻结
    assert pos.available == 0

    # 现金扣减：100*10 + 5 + 0 + 0.02 = 1005.02
    assert portfolio.cash == pytest.approx(1_000_000 - 1005.02)

    # OpenLot 队列
    assert "600000.SH" in portfolio.open_lots
    assert len(portfolio.open_lots["600000.SH"]) == 1


def test_apply_fill_buy_no_trade_generated(
    portfolio: Portfolio, make_fill: callable
) -> None:
    """买入成交不生成 Trade（Trade 仅在平仓时生成）。"""
    fill = make_fill(direction="buy", volume=100, price=10.0)
    result = portfolio.apply_fill(fill)
    assert result is None
    assert portfolio.trades == []


# ---------------------------------------------------------------------------
# 3. apply_fill 卖出 + FIFO 配对
# ---------------------------------------------------------------------------


def test_apply_fill_sell_generates_trade(
    portfolio: Portfolio, make_fill: callable
) -> None:
    """卖出成交：持仓减少、现金回笼、生成 Trade（含盈亏）。"""
    # 先买入建仓
    buy_fill = make_fill(
        fill_id="f1", order_id="o1", symbol="600000.SH",
        direction="buy", volume=100, price=10.0,
        fill_time=datetime(2024, 6, 1, 10, 0),
    )
    portfolio.apply_fill(buy_fill)
    # T+1 解冻
    portfolio.settle_new_day()

    # 卖出平仓
    sell_fill = make_fill(
        fill_id="f2", order_id="o2", symbol="600000.SH",
        direction="sell", volume=100, price=11.0,
        commission=5.0, stamp_tax=0.05, transfer_fee=0.022,
        fill_time=datetime(2024, 6, 2, 10, 0),
    )
    trade = portfolio.apply_fill(sell_fill)

    # Trade 应已生成
    assert trade is not None
    assert trade.symbol == "600000.SH"
    assert trade.open_price == 10.0
    assert trade.close_price == 11.0
    assert trade.volume == 100
    # 盈亏 = (11 - 10) × 100 = 100
    assert trade.pnl == pytest.approx(100.0)
    assert trade.pnl_pct == pytest.approx(0.1)

    # 持仓清零
    pos = portfolio.get_position("600000.SH")
    assert pos.quantity == 0

    # 现金回笼：100*11 - 5 - 0.05 - 0.022 = 1094.928
    # 买入后现金 = 1_000_000 - 1000 - 5 - 0.02 = 998994.98
    # 卖出后现金 = 998994.98 + 1094.928 = 1000089.908
    assert portfolio.cash == pytest.approx(998994.98 + 1094.928, rel=1e-4)


def test_apply_fill_sell_without_position_returns_none(
    portfolio: Portfolio, make_fill: callable
) -> None:
    """无持仓卖出：返回 None（理论被风控拦截，Portfolio 保守忽略）。"""
    sell_fill = make_fill(direction="sell", volume=100, price=10.0)
    result = portfolio.apply_fill(sell_fill)
    assert result is None


# ---------------------------------------------------------------------------
# 4. T+1 处理
# ---------------------------------------------------------------------------


def test_settle_new_day_unfreezes_today_bought(
    portfolio: Portfolio, make_fill: callable
) -> None:
    """settle_new_day 后所有持仓 today_bought 解冻到 available。"""
    fill = make_fill(direction="buy", volume=100, price=10.0)
    portfolio.apply_fill(fill)
    pos = portfolio.get_position("600000.SH")
    assert pos.available == 0
    assert pos.today_bought == 100

    portfolio.settle_new_day()
    assert pos.today_bought == 0
    assert pos.available == 100


# ---------------------------------------------------------------------------
# 5. update_market_prices
# ---------------------------------------------------------------------------


def test_update_market_prices_updates_market_value(
    portfolio: Portfolio, make_fill: callable
) -> None:
    """update_market_prices 更新所有持仓的市值。"""
    fill = make_fill(direction="buy", volume=100, price=10.0)
    portfolio.apply_fill(fill)

    portfolio.update_market_prices({"600000.SH": 12.0})
    pos = portfolio.get_position("600000.SH")
    assert pos.market_price == 12.0
    assert pos.market_value == 1200.0
    assert pos.pnl == 200.0


def test_update_market_prices_ignores_unheld_symbol(portfolio: Portfolio) -> None:
    """无持仓的 symbol 被忽略。"""
    portfolio.update_market_prices({"999999.SZ": 100.0})
    assert "999999.SZ" not in portfolio.positions


# ---------------------------------------------------------------------------
# 6. get_account 账户快照
# ---------------------------------------------------------------------------


def test_get_account_returns_account_info(
    portfolio: Portfolio, initial_capital: float
) -> None:
    """get_account 返回 AccountInfo 对象，字段完整。"""
    acct = portfolio.get_account()
    assert isinstance(acct, AccountInfo)
    assert acct.cash == initial_capital
    assert acct.total == initial_capital
    assert acct.initial_capital == initial_capital
    assert acct.peak_value == initial_capital
    assert acct.pnl == 0.0
    assert acct.pnl_pct == 0.0


def test_get_account_updates_peak_value(
    portfolio: Portfolio, make_fill: callable
) -> None:
    """市值上涨时 peak_value 更新。"""
    fill = make_fill(direction="buy", volume=100, price=10.0)
    portfolio.apply_fill(fill)
    portfolio.update_market_prices({"600000.SH": 15.0})
    acct = portfolio.get_account()
    # 总资产 = 999000 + 1500 = 1_000_500
    assert acct.total == pytest.approx(1_000_500, rel=1e-4)
    assert acct.peak_value == acct.total


# ---------------------------------------------------------------------------
# 7. snapshot 净值曲线
# ---------------------------------------------------------------------------


def test_snapshot_appends_equity_curve(portfolio: Portfolio) -> None:
    """snapshot 追加净值曲线，长度+1。"""
    ts1 = datetime(2024, 6, 1)
    ts2 = datetime(2024, 6, 2)
    portfolio.snapshot(ts1)
    assert len(portfolio.equity_curve) == 1
    assert portfolio.equity_curve[0] == (ts1, 1_000_000)
    portfolio.snapshot(ts2)
    assert len(portfolio.equity_curve) == 2
    assert portfolio.trade_dates == [ts1, ts2]


# ---------------------------------------------------------------------------
# 8. 持仓查询
# ---------------------------------------------------------------------------


def test_get_position_returns_none_if_not_held(portfolio: Portfolio) -> None:
    """无持仓返回 None。"""
    assert portfolio.get_position("999999.SZ") is None


def test_get_active_positions_filters_zero(
    portfolio: Portfolio, make_fill: callable
) -> None:
    """get_active_positions 过滤 quantity=0 的持仓。"""
    fill = make_fill(direction="buy", volume=100, price=10.0)
    portfolio.apply_fill(fill)
    portfolio.settle_new_day()
    # 平仓
    sell_fill = make_fill(
        fill_id="f2", order_id="o2", direction="sell", volume=100, price=11.0
    )
    portfolio.apply_fill(sell_fill)
    # active 应为空
    assert portfolio.get_active_positions() == {}


# ---------------------------------------------------------------------------
# 9. record_order
# ---------------------------------------------------------------------------


def test_record_order_appends(portfolio: Portfolio, make_order: callable) -> None:
    """record_order 追加到订单流水。"""
    order = make_order(order_id="o1")
    portfolio.record_order(order)
    assert len(portfolio.orders) == 1
    assert portfolio.orders[0].order_id == "o1"
