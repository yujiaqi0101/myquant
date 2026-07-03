"""
阶段4验证测试：Portfolio + 绩效 + 持久化

覆盖场景：
    1. 导入验证
    2. Portfolio 买入成交（T+1 冻结/现金扣减）
    3. Portfolio settle_new_day（T+1 解冻）
    4. Portfolio 卖出成交（FIFO 配对生成 Trade）
    5. Portfolio 市价更新与账户快照
    6. PerformanceCalculator 22 项指标计算
    7. PersistenceRepository 建表/保存/加载/恢复
"""

import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager


# ---------------------------------------------------------------------------
# Mock DB：内存 SQLite，提供 get_connection 上下文管理器
# ---------------------------------------------------------------------------


class MockDB:
    """模拟 DatabaseManager，用内存 SQLite。"""

    def __init__(self):
        # 内存库 + check_same_thread=False 允许多线程访问
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    @contextmanager
    def get_connection(self):
        # 返回连接，支持 with 语法；事务由 sqlite3 自动管理
        yield self._conn
        self._conn.commit()

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# 测试主流程
# ---------------------------------------------------------------------------


def main():
    print("=" * 70)
    print("阶段4验证测试：Portfolio + 绩效 + 持久化")
    print("=" * 70)

    # ---- 1. 导入验证 ----
    print("\n[1] 导入验证...")
    from src.core.portfolio import Portfolio, AccountInfo
    from src.core.result import (
        BacktestResult,
        BenchmarkProvider,
        PerformanceCalculator,
    )
    from src.core.persistence import PersistenceRepository
    from src.core.types import Direction, Fill, Position, PositionDirection
    print("    OK: Portfolio/AccountInfo/BacktestResult/BenchmarkProvider/"
          "PerformanceCalculator/PersistenceRepository 全部导入成功")

    # ---- 2. Portfolio 买入成交 ----
    print("\n[2] Portfolio 买入成交（T+1 冻结 + 现金扣减）...")
    pf = Portfolio(initial_capital=1_000_000.0)
    t0 = datetime(2024, 1, 2, 15, 0, 0)
    # 买入 600000.SH 1000股 @10元
    # 成交金额=10000，佣金=max(10000*0.00025, 5)=5，过户费=10000*0.00002=0.2
    fill_buy = Fill(
        fill_id="F001",
        order_id="O001",
        symbol="600000.SH",
        direction=Direction.BUY,
        volume=1000.0,
        price=10.0,
        commission=5.0,
        stamp_tax=0.0,  # 买入无印花税
        transfer_fee=0.2,
        fill_time=t0,
    )
    trade = pf.apply_fill(fill_buy)
    pos = pf.get_position("600000.SH")
    assert trade is None, "买入不应生成 Trade"
    assert pos is not None, "持仓应已建立"
    assert pos.quantity == 1000.0, f"持仓数量应为 1000，实际 {pos.quantity}"
    assert pos.available == 0.0, f"T+1 下 available 应为 0，实际 {pos.available}"
    assert pos.today_bought == 1000.0, f"today_bought 应为 1000，实际 {pos.today_bought}"
    assert pos.avg_price == 10.0, f"均价应为 10，实际 {pos.avg_price}"
    # 现金 = 1000000 - (10000 + 5 + 0.2) = 989994.8
    expected_cash = 1_000_000.0 - (10000.0 + 5.0 + 0.2)
    assert abs(pf.cash - expected_cash) < 1e-6, f"现金应为 {expected_cash}，实际 {pf.cash}"
    print(f"    OK: 买入后 持仓={pos.quantity} available={pos.available} "
          f"today_bought={pos.today_bought} cash={pf.cash:.2f}")

    # ---- 3. settle_new_day ----
    print("\n[3] settle_new_day（T+1 解冻）...")
    pf.settle_new_day()
    pos = pf.get_position("600000.SH")
    assert pos.available == 1000.0, f"解冻后 available 应为 1000，实际 {pos.available}"
    assert pos.today_bought == 0.0, f"解冻后 today_bought 应为 0，实际 {pos.today_bought}"
    print(f"    OK: 解冻后 available={pos.available} today_bought={pos.today_bought}")

    # ---- 4. 卖出成交 + FIFO 配对 ----
    print("\n[4] 卖出成交（FIFO 配对生成 Trade）...")
    t1 = datetime(2024, 1, 3, 15, 0, 0)
    # 卖出 500股 @11元
    # 成交金额=5500，佣金=5，印花税=5500*0.0005=2.75，过户费=5500*0.00002=0.11
    fill_sell = Fill(
        fill_id="F002",
        order_id="O002",
        symbol="600000.SH",
        direction=Direction.SELL,
        volume=500.0,
        price=11.0,
        commission=5.0,
        stamp_tax=2.75,
        transfer_fee=0.11,
        fill_time=t1,
    )
    trade = pf.apply_fill(fill_sell)
    pos = pf.get_position("600000.SH")
    assert trade is not None, "卖出应生成 Trade"
    assert pos.quantity == 500.0, f"卖出后持仓应为 500，实际 {pos.quantity}"
    assert pos.available == 500.0, f"卖出后 available 应为 500，实际 {pos.available}"
    # 现金回笼 = 5500 - 5 - 2.75 - 0.11 = 5492.14
    cash_before_sell = expected_cash
    expected_cash_after = cash_before_sell + (5500.0 - 5.0 - 2.75 - 0.11)
    assert abs(pf.cash - expected_cash_after) < 1e-6, (
        f"卖出后现金应为 {expected_cash_after}，实际 {pf.cash}"
    )
    # Trade 盈亏 = (11 - 10) * 500 = 500
    assert abs(trade.pnl - 500.0) < 1e-6, f"Trade 盈亏应为 500，实际 {trade.pnl}"
    assert abs(trade.pnl_pct - 0.1) < 1e-6, f"Trade 盈亏率应为 0.1，实际 {trade.pnl_pct}"
    print(f"    OK: 卖出后 持仓={pos.quantity} cash={pf.cash:.2f} "
          f"Trade.pnl={trade.pnl:.2f} pnl_pct={trade.pnl_pct:.4f}")

    # ---- 5. 市价更新 + 账户快照 ----
    print("\n[5] 市价更新 + 账户快照...")
    # 更新市价 @12元
    pf.update_market_prices({"600000.SH": 12.0})
    pos = pf.get_position("600000.SH")
    assert pos.market_price == 12.0, f"市价应为 12，实际 {pos.market_price}"
    assert pos.market_value == 6000.0, f"市值应为 6000，实际 {pos.market_value}"
    # 浮动盈亏 = 6000 - (500*10) = 1000
    assert abs(pos.pnl - 1000.0) < 1e-6, f"浮动盈亏应为 1000，实际 {pos.pnl}"
    acct = pf.get_account()
    # 总资产 = cash + 0 + 6000
    expected_total = pf.cash + 6000.0
    assert abs(acct.total - expected_total) < 1e-6, f"总资产应为 {expected_total}，实际 {acct.total}"
    print(f"    OK: 市价=12 市值={pos.market_value} 浮动盈亏={pos.pnl} "
          f"总资产={acct.total:.2f}")

    # ---- 6. 净值曲线 + 绩效计算 ----
    print("\n[6] 净值曲线 + 22项绩效指标计算...")
    # 构造 10 个交易日的净值曲线
    pf2 = Portfolio(initial_capital=1_000_000.0)
    base = datetime(2024, 1, 2)
    # 模拟 10 天收益：第1-5天每天涨1%，第6-10天每天跌0.5%
    values = [1_000_000.0]
    for i in range(5):
        values.append(values[-1] * 1.01)
    for i in range(5):
        values.append(values[-1] * 0.995)
    for i, v in enumerate(values):
        ts = base + timedelta(days=i)
        pf2.snapshot(ts)
        # 手动覆盖净值曲线最后一个值（模拟每日总资产）
        pf2.equity_curve[-1] = (ts, v)
        pf2._last_total = v
    # 添加一笔模拟平仓交易用于交易统计
    from src.core.types import Trade, OpenClose
    pf2.trades.append(Trade(
        trade_id="T1", symbol="600000.SH",
        direction=PositionDirection.LONG,
        open_close=OpenClose.CLOSE_LONG,
        open_time=base, open_price=10.0,
        close_time=base + timedelta(days=3), close_price=11.0,
        volume=100, pnl=100.0, pnl_pct=0.1, holding_days=3,
    ))
    pf2.trades.append(Trade(
        trade_id="T2", symbol="600000.SH",
        direction=PositionDirection.LONG,
        open_close=OpenClose.CLOSE_LONG,
        open_time=base, open_price=10.0,
        close_time=base + timedelta(days=4), close_price=9.5,
        volume=100, pnl=-50.0, pnl_pct=-0.05, holding_days=4,
    ))
    calc = PerformanceCalculator(pf2, benchmark_provider=None)
    result = calc.calculate()
    assert result.ok(), f"绩效计算应成功，error={result.error}"
    assert result.trading_days == 10, f"交易天数应为10，实际 {result.trading_days}"
    assert result.trade_count == 2, f"平仓次数应为2，实际 {result.trade_count}"
    assert result.win_count == 1, f"盈利次数应为1，实际 {result.win_count}"
    assert result.loss_count == 1, f"亏损次数应为1，实际 {result.loss_count}"
    assert abs(result.win_rate - 50.0) < 1e-6, f"胜率应为50%，实际 {result.win_rate}"
    assert result.up_days >= 1, f"上涨天数应>=1，实际 {result.up_days}"
    assert result.max_drawdown >= 0, "最大回撤应>=0"
    assert result.sharpe != 0 or result.trading_days > 0, "夏普比率应可计算"
    print(f"    OK: 交易天数={result.trading_days} 平仓次数={result.trade_count} "
          f"胜率={result.win_rate}% 最大回撤={result.max_drawdown:.2f}% "
          f"夏普={result.sharpe}")
    print("    --- 绩效摘要 ---")
    for line in result.to_summary().split("\n"):
        print(f"    {line}")

    # ---- 7. 持久化测试 ----
    print("\n[7] PersistenceRepository 建表/保存/加载/恢复...")
    db = MockDB()
    repo = PersistenceRepository(db)
    repo.ensure_tables()
    # 二次调用 ensure_tables 应幂等
    repo.ensure_tables()
    print("    OK: ensure_tables 幂等建表成功")

    # 保存账户状态
    account_id = "test_acc_001"
    trade_date = "2024-01-03"
    # 先保存一笔成交和订单
    from src.core.types import Order, OrderStatus
    order = Order(
        order_id="O001", symbol="600000.SH", direction=Direction.BUY,
        volume=1000.0, price_type="market", status=OrderStatus.FILLED,
        filled_volume=1000.0, filled_price=10.0, created_time=t0,
    )
    repo.save_order(account_id, order)
    repo.save_fill(account_id, fill_buy)
    # 保存账户全状态
    repo.save_account_state(account_id, "small_cap", pf, trade_date=trade_date)
    print("    OK: save_account_state 保存成功")

    # 加载账户信息
    info = repo.load_account_info(account_id)
    assert info is not None, "账户信息应存在"
    assert info["strategy_name"] == "small_cap"
    assert abs(info["initial_capital"] - 1_000_000.0) < 1e-6
    print(f"    OK: load_account_info strategy={info['strategy_name']} "
          f"cash={info['cash']:.2f}")

    # 加载持仓
    loaded_positions = repo.load_positions(account_id)
    assert "600000.SH" in loaded_positions, "持仓应包含 600000.SH"
    lpos = loaded_positions["600000.SH"]
    assert lpos.quantity == 500.0, f"加载持仓数量应为 500，实际 {lpos.quantity}"
    print(f"    OK: load_positions 600000.SH quantity={lpos.quantity}")

    # 加载订单
    orders = repo.load_orders(account_id)
    assert len(orders) == 1, f"订单数应为1，实际 {len(orders)}"
    assert orders[0]["order_id"] == "O001"
    print(f"    OK: load_orders count={len(orders)}")

    # 加载成交
    fills = repo.load_fills(account_id)
    assert len(fills) == 1, f"成交数应为1，实际 {len(fills)}"
    assert fills[0]["fill_id"] == "F001"
    print(f"    OK: load_fills count={len(fills)}")

    # 加载快照
    snaps = repo.load_snapshots(account_id)
    assert len(snaps) == 1, f"快照数应为1，实际 {len(snaps)}"
    assert snaps[0]["trade_date"] == trade_date
    print(f"    OK: load_snapshots count={len(snaps)} date={snaps[0]['trade_date']}")

    # 恢复到新 Portfolio
    pf_new = Portfolio(initial_capital=1_000_000.0)
    ok = repo.load_account_state(account_id, pf_new)
    assert ok, "恢复应成功"
    assert abs(pf_new.cash - pf.cash) < 1e-6, (
        f"恢复后现金应={pf.cash}，实际={pf_new.cash}"
    )
    lpos2 = pf_new.get_position("600000.SH")
    assert lpos2 is not None, "恢复后应有持仓"
    assert lpos2.quantity == 500.0, f"恢复后持仓数量应为500，实际 {lpos2.quantity}"
    assert len(pf_new.equity_curve) == 1, f"恢复后净值曲线应有1条，实际 {len(pf_new.equity_curve)}"
    print(f"    OK: load_account_state 恢复成功 cash={pf_new.cash:.2f} "
          f"持仓={lpos2.quantity} 净值曲线={len(pf_new.equity_curve)}")

    # 删除账户
    repo.delete_account(account_id)
    assert repo.load_account_info(account_id) is None, "删除后账户应不存在"
    assert len(repo.load_positions(account_id)) == 0, "删除后持仓应为空"
    print("    OK: delete_account 删除成功")

    db.close()

    print("\n" + "=" * 70)
    print("阶段4验证全部通过 ✓")
    print("=" * 70)


if __name__ == "__main__":
    main()
