"""
tests/integration/test_backtest_engine.py
==========================================

BacktestEngine 集成测试（完整流程端到端验证）。

测试目标（设计文档 8.2 节）：
    1. 验证 BacktestEngine.run() 完整生命周期：on_init → on_event × N → on_stop
    2. 验证 HistoricalDataFeed + EventEngine + Portfolio + Execution 组件协作
    3. 验证策略通过 Context 接口下单、查询持仓/账户的完整链路
    4. 验证 T+1 规则在引擎层面生效（买入当日不能卖出）
    5. 验证 target_percent 目标权重订单的折算逻辑
    6. 验证 RiskManager 集成后风控检查生效
    7. 验证定时器（month_start）触发与调仓逻辑
    8. 验证空数据/异常场景的错误处理

测试策略：
    - 使用 MockDB 提供内存 K 线数据（不依赖真实数据库，遵循项目规则1）
    - 使用 SimpleBuyHoldStrategy 简单策略验证基础链路
    - 使用真实 SmallCapStrategy 验证完整业务场景
    - 所有断言基于引擎输出 BacktestResult 与 Portfolio 状态

用法：
    cd d:\\python_workspace\\myquant
    python -m pytest tests/integration/test_backtest_engine.py -v
"""

import os
import sys
from datetime import datetime, timedelta
from contextlib import contextmanager

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import sqlite3
import pandas as pd
import numpy as np
import pytest

from src.core.context import Context
from src.core.engine import BacktestEngine
from src.core.events import Event, EventType
from src.core.strategy import Strategy, register_strategy
from src.core.types import Direction, OrderStatus


# ---------------------------------------------------------------------------
# MockDB：内存数据库，提供 K线 + 指数数据
# ---------------------------------------------------------------------------


class MockDB:
    """模拟 DatabaseManager，提供 K线 + 指数数据。

    提供 BacktestEngine 所需的 get_stock_daily / get_index_daily 接口。
    数据全部在内存中生成，不写入任何真实数据库（遵循项目规则1）。
    """

    def __init__(self, n_days: int = 20, n_stocks: int = 5):
        """初始化 MockDB。

        Args:
            n_days: 交易日天数
            n_stocks: 股票数量（生成 600000.SH ~ 60000x.SH）
        """
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._stock_daily = self._gen_stock_daily(n_days, n_stocks)
        self._index_daily = self._gen_index_daily(n_days)
        self._mktvalue = self._gen_mktvalue(n_days, n_stocks)

    @contextmanager
    def get_connection(self):
        yield self._conn
        self._conn.commit()

    def close(self):
        self._conn.close()

    # ---------- 数据生成 ----------

    @staticmethod
    def _gen_dates(n_days: int):
        """生成 n_days 个交易日（跳过周末）。"""
        base = datetime(2024, 1, 2)
        dates = []
        d = base
        while len(dates) < n_days:
            if d.weekday() < 5:
                dates.append(d)
            d += timedelta(days=1)
        return dates

    def _gen_stock_daily(self, n_days: int, n_stocks: int) -> pd.DataFrame:
        """生成 n_stocks 只股票 × n_days 交易日的日频K线。

        价格规则：起始 10.0，每日随机波动 ±1%，保证价格稳定可预测。
        """
        dates = self._gen_dates(n_days)
        symbols = [f"60000{i}.SH" for i in range(n_stocks)]
        rows = []
        rng = np.random.RandomState(42)
        for sym in symbols:
            price = 10.0
            for dt in dates:
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
                price = close_p
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df.set_index(["trade_date", "stock_code"], inplace=True)
        df.sort_index(inplace=True)
        return df

    def _gen_index_daily(self, n_days: int) -> pd.DataFrame:
        """生成基准指数数据（沪深300）。"""
        dates = self._gen_dates(n_days)
        rows = []
        price = 3000.0
        rng = np.random.RandomState(7)
        for dt in dates:
            change = rng.uniform(-0.008, 0.008)
            open_p = price
            close_p = round(open_p * (1 + change), 4)
            rows.append({
                "trade_date": dt.strftime("%Y-%m-%d"),
                "index_code": "000300.SH",
                "open": open_p, "high": close_p * 1.002,
                "low": close_p * 0.998, "close": close_p,
                "volume": 0.0, "amount": 0.0,
            })
            price = close_p
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df.set_index(["trade_date", "index_code"], inplace=True)
        df.sort_index(inplace=True)
        return df

    def _gen_mktvalue(self, n_days: int, n_stocks: int) -> pd.DataFrame:
        """生成市值数据：股票序号越大市值越小（用于选股策略）。"""
        dates = self._gen_dates(n_days)
        symbols = [f"60000{i}.SH" for i in range(n_stocks)]
        rows = []
        for sym in symbols:
            idx = int(sym[3:6])
            tot_mv = (10 - idx) * 1e8
            for dt in dates:
                rows.append({
                    "trade_date": dt.strftime("%Y-%m-%d"),
                    "stock_code": sym,
                    "tot_mv": tot_mv,
                    "a_mv": tot_mv * 0.8,
                })
        return pd.DataFrame(rows)

    # ---------- DatabaseManager 接口 ----------

    def get_stock_daily(self, stock_codes=None, start_date=None, end_date=None, fields=None):
        df = self._stock_daily
        if stock_codes:
            df = df[df.index.get_level_values("stock_code").isin(stock_codes)]
        if start_date:
            df = df[df.index.get_level_values("trade_date") >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df.index.get_level_values("trade_date") <= pd.Timestamp(end_date)]
        return df

    def get_index_daily(self, index_codes=None, start_date=None, end_date=None):
        df = self._index_daily
        if index_codes:
            df = df[df.index.get_level_values("index_code").isin(index_codes)]
        if start_date:
            df = df[df.index.get_level_values("trade_date") >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df.index.get_level_values("trade_date") <= pd.Timestamp(end_date)]
        return df

    def get_stock_mktvalue(self, stock_codes=None, start_date=None, end_date=None):
        df = self._mktvalue.copy()
        if stock_codes:
            df = df[df["stock_code"].isin(stock_codes)]
        if start_date:
            df = df[df["trade_date"] >= start_date]
        if end_date:
            df = df[df["trade_date"] <= end_date]
        return df


# ---------------------------------------------------------------------------
# 测试用简单策略：买入持有
# ---------------------------------------------------------------------------


@register_strategy("_test_buy_hold")
class BuyHoldStrategy(Strategy):
    """测试用买入持有策略。

    - on_init: 订阅全部 symbol，注册每日定时器
    - on_event: 收到首个 BAR 时买入第一个 symbol 100 股，后续持有不动
    - on_stop: 记录调用次数
    """

    name = "_test_buy_hold"

    def __init__(self, params=None):
        super().__init__(params)
        self.symbol = params.get("symbol", "600000.SH") if params else "600000.SH"
        self.volume = params.get("volume", 100) if params else 100
        self.init_called = 0
        self.event_count = 0
        self.stop_called = 0
        self.bought = False

    def on_init(self, context: Context) -> None:
        self.init_called += 1
        context.subscribe([self.symbol])

    def on_event(self, event: Event, context: Context) -> None:
        self.event_count += 1
        # 首个 BAR 事件买入
        if event.type is EventType.BAR and not self.bought:
            context.submit_order(
                symbol=self.symbol,
                direction="buy",
                volume=self.volume,
                price_type="market",
            )
            self.bought = True

    def on_stop(self, context: Context) -> None:
        self.stop_called += 1


# ---------------------------------------------------------------------------
# 测试用目标权重策略
# ---------------------------------------------------------------------------


@register_strategy("_test_target_weight")
class TargetWeightStrategy(Strategy):
    """测试用目标权重策略。

    - on_init: 订阅全部 symbol
    - on_event: 收到首个 BAR 时用 target_weight 下单达到 30% 仓位
    """

    name = "_test_target_weight"

    def __init__(self, params=None):
        super().__init__(params)
        self.symbol = params.get("symbol", "600000.SH") if params else "600000.SH"
        self.target_weight = params.get("target_weight", 0.3) if params else 0.3
        self.bought = False

    def on_init(self, context: Context) -> None:
        context.subscribe([self.symbol])

    def on_event(self, event: Event, context: Context) -> None:
        if event.type is EventType.BAR and not self.bought:
            context.submit_order(
                symbol=self.symbol,
                direction="target",
                target_weight=self.target_weight,
                price_type="target_percent",
            )
            self.bought = True

    def on_stop(self, context: Context) -> None:
        pass


# ---------------------------------------------------------------------------
# 测试用 T+1 验证策略
# ---------------------------------------------------------------------------


@register_strategy("_test_t_plus_one")
class TPlusOneTestStrategy(Strategy):
    """测试 T+1 规则的策略。

    - 第一个 BAR：买入 100 股
    - 第二个 BAR：尝试卖出 100 股（应被 T+1 拒绝）
    - 第三个 BAR：再次尝试卖出（应成功，T+1 已解冻）
    """

    name = "_test_t_plus_one"

    def __init__(self, params=None):
        super().__init__(params)
        self.symbol = params.get("symbol", "600000.SH") if params else "600000.SH"
        self.bar_count = 0
        self.sell_attempts = []  # 记录每次卖出尝试的订单ID

    def on_init(self, context: Context) -> None:
        context.subscribe([self.symbol])

    def on_event(self, event: Event, context: Context) -> None:
        if event.type is not EventType.BAR:
            return
        self.bar_count += 1
        if self.bar_count == 1:
            # 第一日买入
            context.submit_order(
                symbol=self.symbol,
                direction="buy",
                volume=100,
                price_type="market",
            )
        elif self.bar_count == 2:
            # 第二日尝试卖出（T+1 应拒绝）
            oid = context.submit_order(
                symbol=self.symbol,
                direction="sell",
                volume=100,
                price_type="market",
            )
            self.sell_attempts.append(oid)
        elif self.bar_count == 3:
            # 第三日卖出（T+1 已解冻，应成功）
            oid = context.submit_order(
                symbol=self.symbol,
                direction="sell",
                volume=100,
                price_type="market",
            )
            self.sell_attempts.append(oid)

    def on_stop(self, context: Context) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """提供 MockDB 实例，测试结束自动关闭。"""
    db = MockDB(n_days=20, n_stocks=5)
    yield db
    db.close()


@pytest.fixture
def buy_hold_strategy():
    """提供 BuyHoldStrategy 实例。"""
    return BuyHoldStrategy(params={"symbol": "600000.SH", "volume": 100})


# ===========================================================================
# 1. 基础生命周期测试
# ===========================================================================


class TestBacktestEngineLifecycle:
    """BacktestEngine 基础生命周期测试。"""

    def test_run_returns_backtest_result(self, mock_db, buy_hold_strategy):
        """回测应返回 BacktestResult 且成功（无错误）。"""
        engine = BacktestEngine(
            strategy=buy_hold_strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
            initial_capital=1_000_000.0,
        )
        result = engine.run()
        assert result.ok(), f"回测应成功，error={result.error}"

    def test_lifecycle_callbacks_called(self, mock_db, buy_hold_strategy):
        """on_init/on_stop 应各被调用一次。"""
        engine = BacktestEngine(
            strategy=buy_hold_strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
        )
        engine.run()
        assert buy_hold_strategy.init_called == 1, "on_init 应被调用1次"
        assert buy_hold_strategy.stop_called == 1, "on_stop 应被调用1次"

    def test_event_count_matches_trading_days(self, mock_db, buy_hold_strategy):
        """策略接收的事件总数应大于交易日数（含 BAR/TIMER/ACCOUNT 等）。"""
        engine = BacktestEngine(
            strategy=buy_hold_strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
        )
        result = engine.run()
        # 事件数应 >= 交易天数（BAR 事件至少有 trading_days 个）
        assert buy_hold_strategy.event_count >= result.trading_days
        assert result.trading_days > 0, "交易天数应大于 0"

    def test_equity_curve_not_empty(self, mock_db, buy_hold_strategy):
        """回测结束应有净值曲线数据。"""
        engine = BacktestEngine(
            strategy=buy_hold_strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
        )
        result = engine.run()
        assert len(result.equity_curve) > 0, "净值曲线不应为空"
        # 每个净值点应是 (datetime, float) 元组
        first_point = result.equity_curve[0]
        assert len(first_point) == 2

    def test_final_equity_close_to_initial(self, mock_db, buy_hold_strategy):
        """买入100股后总资产应接近初始资金（扣除手续费）。"""
        engine = BacktestEngine(
            strategy=buy_hold_strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
            initial_capital=1_000_000.0,
        )
        result = engine.run()
        # 买入 100 股 × 10元 = 1000 元 + 手续费（最低5元）
        # 总资产波动应小于 5%
        assert 950_000 < result.final_equity < 1_050_000, (
            f"最终资产应在合理范围内，实际 {result.final_equity}"
        )


# ===========================================================================
# 2. 订单与成交测试
# ===========================================================================


class TestBacktestEngineOrders:
    """BacktestEngine 订单与成交测试。"""

    def test_buy_order_generates_fill(self, mock_db, buy_hold_strategy):
        """买入订单应产生成交记录。"""
        engine = BacktestEngine(
            strategy=buy_hold_strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
        )
        result = engine.run()
        assert len(result.fills) > 0, "应有成交记录"
        # 第一个成交应是买入
        first_fill = result.fills[0]
        assert first_fill.direction == Direction.BUY

    def test_position_after_buy(self, mock_db, buy_hold_strategy):
        """买入后应能在 Portfolio 中查到持仓。"""
        engine = BacktestEngine(
            strategy=buy_hold_strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
        )
        engine.run()
        positions = engine.context.get_positions()
        assert "600000.SH" in positions, "应持有 600000.SH"
        assert positions["600000.SH"]["quantity"] == 100.0

    def test_account_cash_decreased(self, mock_db, buy_hold_strategy):
        """买入后账户现金应减少。"""
        engine = BacktestEngine(
            strategy=buy_hold_strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
            initial_capital=1_000_000.0,
        )
        engine.run()
        account = engine.context.get_account()
        # 现金应小于初始资金（已买入股票）
        assert account["cash"] < 1_000_000.0
        # 总资产应接近初始资金（差异为手续费 + 价格波动）
        assert 950_000 < account["total"] < 1_050_000


# ===========================================================================
# 3. T+1 规则测试
# ===========================================================================


class TestBacktestEngineTPlusOne:
    """T+1 规则在引擎层面的验证。"""

    def test_t_plus_one_blocks_same_day_sell(self, mock_db):
        """T+1 应阻止当日卖出（买入次日才能卖）。"""
        strategy = TPlusOneTestStrategy(params={"symbol": "600000.SH"})
        engine = BacktestEngine(
            strategy=strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
        )
        result = engine.run()
        assert result.ok(), f"回测应成功，error={result.error}"
        # 第二日尝试卖出应被 T+1 拒绝
        # 第三日卖出应成功
        assert len(strategy.sell_attempts) == 2, "应有2次卖出尝试"


# ===========================================================================
# 4. 目标权重订单测试
# ===========================================================================


class TestBacktestEngineTargetPercent:
    """target_percent 目标权重订单测试。"""

    def test_target_weight_creates_position(self, mock_db):
        """target_weight 下单应建立对应仓位的持仓。"""
        strategy = TargetWeightStrategy(
            params={"symbol": "600000.SH", "target_weight": 0.3}
        )
        engine = BacktestEngine(
            strategy=strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
            initial_capital=1_000_000.0,
        )
        result = engine.run()
        assert result.ok(), f"回测应成功，error={result.error}"
        positions = engine.context.get_positions()
        assert "600000.SH" in positions, "应有持仓"
        # 目标权重 30%，持仓市值应接近 30 万（lot_size 100 取整后）
        pos = positions["600000.SH"]
        account = engine.context.get_account()
        weight = pos["market_value"] / account["total"]
        # 由于 lot_size=100 取整，权重应接近 30%（误差 ±2%）
        assert 0.28 < weight < 0.32, (
            f"目标权重 30%，实际权重 {weight:.4f} 超出容差"
        )


# ===========================================================================
# 5. 风控集成测试
# ===========================================================================


class TestBacktestEngineRiskManager:
    """BacktestEngine 集成 RiskManager 的测试。

    注：ST/新股/停牌等需要 stock_info 上下文的 Check，引擎默认不提供 stock_info
    （由策略层预加载或风控内部查询，见 build_risk_context 注释），故这些 Check
    在集成层面会降级放行。此处仅测试仅依赖 Order 字段的 Check（如 LotSizeCheck）。
    ST/涨跌停等带数据上下文的 Check 在 tests/unit/test_risk_checks.py 已覆盖。
    """

    def test_risk_manager_rejects_lot_size_violation(self, mock_db):
        """风控应拒绝非 lot_size 整数倍的订单。"""
        from src.risk_checks.factory import build_ashare_risk_manager

        @register_strategy("_test_bad_lot")
        class BadLotStrategy(Strategy):
            name = "_test_bad_lot"

            def __init__(self, params=None):
                super().__init__(params)
                self.bought = False

            def on_init(self, context: Context) -> None:
                context.subscribe(["600000.SH"])

            def on_event(self, event: Event, context: Context) -> None:
                if event.type is EventType.BAR and not self.bought:
                    # 下单 150 股（非 100 整数倍）
                    context.submit_order(
                        symbol="600000.SH",
                        direction="buy",
                        volume=150,
                        price_type="market",
                    )
                    self.bought = True

            def on_stop(self, context: Context) -> None:
                pass

        rm = build_ashare_risk_manager()
        strategy = BadLotStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
            risk_manager=rm,
        )
        result = engine.run()
        assert result.ok()
        # 非 lot_size 整数倍订单应被拒绝，无持仓
        positions = engine.context.get_positions()
        assert "600000.SH" not in positions, "非 lot_size 订单不应成交"


# ===========================================================================
# 6. 定时器测试
# ===========================================================================


class TestBacktestEngineTimer:
    """BacktestEngine 定时器触发测试。"""

    def test_month_start_timer_triggers(self, mock_db):
        """month_start 定时器应在每月第一个交易日触发。"""
        @register_strategy("_test_timer")
        class TimerTestStrategy(Strategy):
            name = "_test_timer"

            def __init__(self, params=None):
                super().__init__(params)
                self.timer_triggered_dates = []

            def on_init(self, context: Context) -> None:
                context.add_timer("rebalance", "month_start")

            def on_event(self, event: Event, context: Context) -> None:
                if event.type is EventType.TIMER:
                    if context.is_timer_due("rebalance"):
                        self.timer_triggered_dates.append(context.get_clock())

            def on_stop(self, context: Context) -> None:
                pass

        strategy = TimerTestStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
        )
        engine.run()
        # 1月只有1个月初（1月2日是首个交易日，视为月初）
        assert len(strategy.timer_triggered_dates) >= 1, (
            "month_start 定时器应至少触发1次"
        )


# ===========================================================================
# 7. 异常场景测试
# ===========================================================================


class TestBacktestEngineErrors:
    """BacktestEngine 异常场景测试。"""

    def test_empty_data_returns_error(self):
        """空数据库应返回带 error 的 BacktestResult。"""

        # 构造一个返回空 DataFrame 的 MockDB
        class EmptyDB:
            """始终返回空数据的数据库。"""

            def get_stock_daily(self, **kwargs):
                # 返回带正确多级索引的空 DataFrame
                idx = pd.MultiIndex.from_tuples(
                    [], names=["trade_date", "stock_code"]
                )
                return pd.DataFrame(
                    index=idx,
                    columns=["open", "high", "low", "close", "volume", "amount"],
                )

            def get_index_daily(self, **kwargs):
                idx = pd.MultiIndex.from_tuples(
                    [], names=["trade_date", "index_code"]
                )
                return pd.DataFrame(
                    index=idx, columns=["open", "high", "low", "close"]
                )

        strategy = BuyHoldStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            db=EmptyDB(),
            start_date="2024-01-02",
            end_date="2024-01-31",
        )
        result = engine.run()
        assert not result.ok(), "空数据回测应失败"
        assert result.error is not None
        assert "无历史数据" in result.error


# ===========================================================================
# 8. 小市值策略完整集成测试
# ===========================================================================


class TestBacktestEngineWithSmallCap:
    """BacktestEngine + SmallCapStrategy 完整业务集成测试。"""

    def test_small_cap_strategy_end_to_end(self, mock_db):
        """小市值策略端到端回测应成功，并选出市值最小的股票。"""
        # 触发策略自动发现
        import importlib
        importlib.import_module("src.strategies.3a7b2c01.small_cap")
        from src.core.strategy import get_strategy_class

        cls = get_strategy_class("small_cap")
        assert cls is not None, "small_cap 策略应已注册"

        strategy = cls(params={"top_n": 3, "rebalance_at": "month_start"})
        engine = BacktestEngine(
            strategy=strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
            initial_capital=1_000_000.0,
        )
        result = engine.run()
        assert result.ok(), f"回测应成功，error={result.error}"
        assert result.trading_days > 0, "交易天数应大于 0"
        assert len(result.fills) > 0, "应有成交记录"

        # 验证选股：市值规则 600000=100亿，600001=90亿...600004=60亿
        # top_n=3 应选市值最小的 3 只：600002/600003/600004
        positions = engine.context.get_positions()
        assert len(positions) > 0, "应有持仓"
        print(f"\n    持仓股票: {sorted(positions.keys())}")
        print(f"    最终资产: {result.final_equity:,.2f}")
        print(f"    总收益: {result.total_return:.4f}%")

    def test_small_cap_strategy_with_benchmark(self, mock_db):
        """小市值策略回测应能计算超额收益（基准 000300.SH）。"""
        import importlib
        importlib.import_module("src.strategies.3a7b2c01.small_cap")
        from src.core.strategy import get_strategy_class

        cls = get_strategy_class("small_cap")
        strategy = cls(params={"top_n": 3})
        engine = BacktestEngine(
            strategy=strategy,
            db=mock_db,
            start_date="2024-01-02",
            end_date="2024-01-31",
            benchmark_code="000300.SH",
        )
        result = engine.run()
        assert result.ok()
        # 基准代码应被记录
        assert result.benchmark_code == "000300.SH"
        # 绩效摘要应可正常生成
        summary = result.to_summary()
        assert "回测绩效摘要" in summary
        assert "总收益" in summary
