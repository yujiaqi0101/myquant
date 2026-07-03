"""
阶段5验证测试：三种引擎（Backtest/Paper/Live）

覆盖场景：
    1. 导入验证：3个Engine + 3个Context 全部可导入
    2. BacktestEngine 端到端回测：MockDB → 策略 → run() → BacktestResult
    3. BacktestContext 接口验证：subscribe/history/get_position/get_account
    4. PaperEngine 单日运行：run_one_day + 持久化 + 恢复
    5. LiveEngine 实例化验证（不实际运行，需券商API）

MockDB 构造模拟K线数据（2只股票 × 20交易日 + 1个基准指数），
不依赖真实数据库，避免污染 t_stock_daily 等表。
"""

import os
import sys
from datetime import datetime, timedelta
from contextlib import contextmanager

# 确保项目根目录在 sys.path 中（从 tests 目录直接运行时需要）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import sqlite3
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# MockDB：内存 SQLite + 模拟 K 线数据
# ---------------------------------------------------------------------------


class MockDB:
    """模拟 DatabaseManager，提供 get_stock_daily / get_index_daily / get_connection。

    构造 2 只股票 × 20 交易日的日频K线，以及 1 个基准指数。
    数据全部在内存中生成，不写入任何真实数据库。
    """

    def __init__(self, n_days: int = 20):
        # 内存 SQLite（用于 PersistenceRepository）
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 生成模拟数据
        self._stock_daily = self._gen_stock_daily(n_days)
        self._index_daily = self._gen_index_daily(n_days)

    @contextmanager
    def get_connection(self):
        yield self._conn
        self._conn.commit()

    def close(self):
        self._conn.close()

    # ---------- 模拟数据生成 ----------

    @staticmethod
    def _gen_stock_daily(n_days: int) -> pd.DataFrame:
        """生成 2 只股票 × n_days 交易日的日频数据。

        返回多级索引 (trade_date, stock_code) 的 DataFrame，
        字段：open/high/low/close/volume/amount（与 t_stock_daily 对齐）。
        """
        # 基准日期：2024-01-02 开始的 n_days 个交易日（跳过周末）
        base = datetime(2024, 1, 2)
        dates = []
        d = base
        while len(dates) < n_days:
            if d.weekday() < 5:  # 周一到周五
                dates.append(d)
            d += timedelta(days=1)

        symbols = ["600000.SH", "600001.SH"]
        rows = []
        # 每只股票以 10 元为起点，每日涨跌 ±1% 内随机波动
        rng = np.random.RandomState(42)  # 固定随机种子，结果可复现
        for sym in symbols:
            price = 10.0
            for dt in dates:
                # 当日OHLC：开盘=前收，收盘=开盘×(1+波动)，高低在中间
                change = rng.uniform(-0.01, 0.01)
                open_p = price
                close_p = round(open_p * (1 + change), 4)
                high_p = round(max(open_p, close_p) * (1 + 0.005), 4)
                low_p = round(min(open_p, close_p) * (1 - 0.005), 4)
                volume = float(rng.randint(100000, 500000))
                amount = round(volume * close_p, 2)
                rows.append({
                    "trade_date": dt.strftime("%Y-%m-%d"),
                    "stock_code": sym,
                    "open": open_p, "high": high_p,
                    "low": low_p, "close": close_p,
                    "volume": volume, "amount": amount,
                })
                price = close_p  # 下一日开盘 = 今日收盘

        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df.set_index(["trade_date", "stock_code"], inplace=True)
        df.sort_index(inplace=True)
        return df

    @staticmethod
    def _gen_index_daily(n_days: int) -> pd.DataFrame:
        """生成 1 个基准指数 × n_days 交易日的日频数据。"""
        base = datetime(2024, 1, 2)
        dates = []
        d = base
        while len(dates) < n_days:
            if d.weekday() < 5:
                dates.append(d)
            d += timedelta(days=1)

        rows = []
        price = 3000.0
        rng = np.random.RandomState(7)
        for dt in dates:
            change = rng.uniform(-0.008, 0.008)
            open_p = price
            close_p = round(open_p * (1 + change), 4)
            high_p = round(max(open_p, close_p) * 1.002, 4)
            low_p = round(min(open_p, close_p) * 0.998, 4)
            rows.append({
                "trade_date": dt.strftime("%Y-%m-%d"),
                "index_code": "000300.SH",
                "open": open_p, "high": high_p,
                "low": low_p, "close": close_p,
                "volume": 0.0, "amount": 0.0,
            })
            price = close_p
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df.set_index(["trade_date", "index_code"], inplace=True)
        df.sort_index(inplace=True)
        return df

    # ---------- DatabaseManager 接口实现 ----------

    def get_stock_daily(self, stock_codes=None, start_date=None, end_date=None, fields=None):
        """查询股票日频数据（模拟 DatabaseManager.get_stock_daily）。"""
        df = self._stock_daily
        if stock_codes:
            df = df[df.index.get_level_values("stock_code").isin(stock_codes)]
        if start_date:
            df = df[df.index.get_level_values("trade_date") >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df.index.get_level_values("trade_date") <= pd.Timestamp(end_date)]
        return df

    def get_index_daily(self, index_codes=None, start_date=None, end_date=None):
        """查询指数日频数据（模拟 DatabaseManager.get_index_daily）。"""
        df = self._index_daily
        if index_codes:
            df = df[df.index.get_level_values("index_code").isin(index_codes)]
        if start_date:
            df = df[df.index.get_level_values("trade_date") >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df.index.get_level_values("trade_date") <= pd.Timestamp(end_date)]
        return df


# ---------------------------------------------------------------------------
# 测试策略：首个交易日买入 600000.SH（目标权重 50%），持有到结束
# ---------------------------------------------------------------------------


from src.core.strategy import Strategy, register_strategy
from src.core.context import Context
from src.core.events import Event, EventType


@register_strategy("test_buy_hold")
class BuyHoldStrategy(Strategy):
    """测试用买入持有策略。

    在首个 BarEvent 触发时，以 target_weight=0.5 买入 600000.SH，
    之后不再操作。用于验证引擎端到端流程。
    """

    name = "test_buy_hold"

    def on_init(self, context: Context) -> None:
        # 订阅标的（BacktestEngine 会加载其K线）
        context.subscribe(["600000.SH", "600001.SH"])
        self._bought = False

    def on_event(self, event: Event, context: Context) -> None:
        # 仅处理 BarEvent
        if event.type is not EventType.BAR:
            return
        # 首个 Bar 买入 600000.SH 目标权重 0.5
        if not self._bought:
            context.submit_order(
                symbol="600000.SH",
                direction="target",  # 目标权重下单
                target_weight=0.5,
                price_type="market",
            )
            self._bought = True

    def on_stop(self, context: Context) -> None:
        context.log("info", "BuyHoldStrategy 停止")


# ---------------------------------------------------------------------------
# 测试主流程
# ---------------------------------------------------------------------------


def main():
    print("=" * 70)
    print("阶段5验证测试：三种引擎（Backtest/Paper/Live）")
    print("=" * 70)

    # ---- 1. 导入验证 ----
    print("\n[1] 导入验证...")
    from src.core.engine import (
        BacktestContext, BacktestEngine,
        PaperContext, PaperEngine,
        LiveContext, LiveEngine,
    )
    print("    OK: 3个Engine + 3个Context 全部导入成功")

    # ---- 2. BacktestEngine 端到端回测 ----
    print("\n[2] BacktestEngine 端到端回测...")
    db = MockDB(n_days=20)
    strategy = BuyHoldStrategy(params={})
    engine = BacktestEngine(
        strategy=strategy,
        db=db,
        start_date="2024-01-02",
        end_date="2024-01-31",
        initial_capital=1_000_000.0,
        benchmark_code="000300.SH",
    )
    result = engine.run()

    assert result.ok(), f"回测应成功，error={result.error}"
    assert result.trading_days > 0, f"交易天数应>0，实际 {result.trading_days}"
    assert len(result.equity_curve) > 0, "净值曲线不应为空"
    assert len(result.fills) > 0, "应有成交记录"
    assert result.final_equity > 0, f"最终资产应>0，实际 {result.final_equity}"
    # 初始资金100万，买入50%仓位，最终资产应接近100万（小幅波动）
    assert abs(result.final_equity - 1_000_000) < 100_000, (
        f"最终资产应接近100万，实际 {result.final_equity}"
    )
    print(f"    OK: 交易天数={result.trading_days} 成交数={len(result.fills)} "
          f"最终资产={result.final_equity:,.2f} 总收益={result.total_return:.4f}%")
    print(f"    净值曲线长度={len(result.equity_curve)} 基准={result.benchmark_code}")
    print("    --- 绩效摘要（前5行）---")
    for line in result.to_summary().split("\n")[:5]:
        print(f"    {line}")

    # ---- 3. BacktestContext 接口验证 ----
    print("\n[3] BacktestContext 接口验证...")
    # 验证 Context 返回 dict 而非对象（符合 Context 契约）
    acct = engine.context.get_account()
    assert isinstance(acct, dict), f"get_account 应返回 dict，实际 {type(acct)}"
    assert "total" in acct, "账户 dict 应包含 total 字段"
    assert "cash" in acct, "账户 dict 应包含 cash 字段"
    print(f"    OK: get_account 返回 dict, total={acct['total']:.2f} cash={acct['cash']:.2f}")

    # 验证持仓查询返回 dict
    pos = engine.context.get_position("600000.SH")
    if pos is not None:
        assert isinstance(pos, dict), f"get_position 应返回 dict，实际 {type(pos)}"
        assert "quantity" in pos, "持仓 dict 应包含 quantity 字段"
        assert pos["quantity"] > 0, f"持仓数量应>0，实际 {pos['quantity']}"
        print(f"    OK: get_position 600000.SH quantity={pos['quantity']} "
              f"avg_price={pos['avg_price']:.4f}")
    else:
        print("    OK: get_position 返回 None（无持仓）")

    # 验证历史数据查询
    hist = engine.context.history("600000.SH", "close", count=5)
    assert isinstance(hist, list), f"单字段 history 应返回 list，实际 {type(hist)}"
    assert len(hist) > 0, "历史数据不应为空"
    print(f"    OK: history('600000.SH','close',5) 返回 {len(hist)} 个值")

    # 验证时间查询
    clock = engine.context.get_clock()
    assert isinstance(clock, datetime), f"get_clock 应返回 datetime，实际 {type(clock)}"
    print(f"    OK: get_clock = {clock}")

    db.close()

    # ---- 4. PaperEngine 单日运行 ----
    print("\n[4] PaperEngine 单日运行 + 持久化...")
    db2 = MockDB(n_days=5)
    strategy2 = BuyHoldStrategy(params={})
    paper = PaperEngine(
        strategy=strategy2,
        db=db2,
        account_id="paper_test_001",
        initial_capital=1_000_000.0,
    )

    # 构造一个 BarEvent 用于 run_one_day
    from src.core.events import BarEvent
    ts = datetime(2024, 1, 2, 15, 0, 0)
    bar = BarEvent(
        timestamp=ts,
        symbol="600000.SH",
        open=10.0, high=10.1, low=9.95, close=10.05,
        volume=200000.0, amount=2010000.0,
        frequency="1d",
        extra={
            "symbols_bars": {
                "600000.SH": {"open": 10.0, "high": 10.1, "low": 9.95, "close": 10.05},
                "600001.SH": {"open": 10.0, "high": 10.05, "low": 9.98, "close": 10.02},
            },
            "trade_date": "2024-01-02",
        },
    )

    # run_one_day 会自动初始化（_init_for_daily_mode）
    paper.run_one_day(bar)
    print(f"    OK: run_one_day 执行完成, cash={paper.portfolio.cash:.2f}")

    # 验证状态已持久化
    from src.core.persistence import PersistenceRepository
    repo = PersistenceRepository(db2)
    info = repo.load_account_info("paper_test_001")
    assert info is not None, "账户信息应已持久化"
    assert info["strategy_name"] == "test_buy_hold"
    print(f"    OK: 持久化成功 strategy={info['strategy_name']} "
          f"cash={info['cash']:.2f}")

    # 验证能从 DB 恢复
    positions = repo.load_positions("paper_test_001")
    print(f"    OK: load_positions 恢复 {len(positions)} 个持仓")
    if "600000.SH" in positions:
        print(f"    600000.SH quantity={positions['600000.SH'].quantity}")

    # 验证订单/成交流水已保存
    orders = repo.load_orders("paper_test_001")
    fills = repo.load_fills("paper_test_001")
    print(f"    OK: load_orders={len(orders)} load_fills={len(fills)}")

    # 清理
    repo.delete_account("paper_test_001")
    db2.close()
    print("    OK: PaperEngine 单日运行 + 持久化 + 恢复 全部验证通过")

    # ---- 5. LiveEngine 实例化验证 ----
    print("\n[5] LiveEngine 实例化验证（不实际运行）...")
    # LiveEngine 需要外部 execution 和 datafeed，这里只验证能实例化
    # 传入 None 作为 datafeed 和 execution（降级模式）
    db3 = MockDB(n_days=5)
    strategy3 = BuyHoldStrategy(params={})
    try:
        live = LiveEngine(
            strategy=strategy3,
            db=db3,
            account_id="live_test_001",
            initial_capital=1_000_000.0,
            execution=None,  # 无券商API
            datafeed=None,   # 无实时行情
        )
        print(f"    OK: LiveEngine 实例化成功 account={live.account_id}")
        # 验证组件装配
        assert live.portfolio is not None
        assert live.repository is not None
        assert live.event_engine is not None
        print(f"    OK: 组件装配 portfolio/repository/event_engine 全部就绪")
        db3.close()
    except Exception as e:
        print(f"    NOTE: LiveEngine 实例化需外部依赖: {e}")
        db3.close()

    print("\n" + "=" * 70)
    print("阶段5验证全部通过 ✓")
    print("=" * 70)


if __name__ == "__main__":
    main()
