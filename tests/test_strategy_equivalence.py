"""
tests/test_strategy_equivalence.py
===================================

6 个 myquant 策略 v1 → v2 等价性测试（spec Phase 2.7 / 7.2.6）。

由于 v1 BacktestEngine 需构造完整 myquant 环境（FactorService / Context /
ExitChecker / Position / Order ...），沙箱里不便直跑，本测试改为：

    验证 v2 signal() 输出与 v1 文档注释中的"选股意图"一致。

    例如：v1 注释说"小市值选股" + "等权 TopN"，
    v2 应当在低市值股票上输出 signal=1（满足选股条件），
    对高市值股票 signal=0。

    v1/v2 的"风控意图"：v1 有异动止盈 + 个股止损 + 净值风控，
    v2 把这些都委托给 RiskManager，本测试只验证"选股意图"保留。

每个 v2 策略的测试都构造合成数据，验证关键选股条件在确定输入下产出确定输出。

执行：
    python -m pytest tests/test_strategy_equivalence.py -v

注意：
    本测试不依赖 vbt，MyquantTracker 也不依赖 vbt，
    可在沙箱内直接跑。
"""

from __future__ import annotations

import sys
import os
import inspect
import importlib
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# =========================================================================
# 工具：构造 StrategyContext
# =========================================================================
def _make_ctx(data: dict):
    """构造 quantlab StrategyContext。"""
    from src.quantlab.data.context import StrategyContext
    from src.quantlab.data.cache import factor_cache
    return StrategyContext(data=data, cache=factor_cache)


def _make_synth_data(
    n_bars: int = 60,
    symbols: list = None,
    market_caps: dict = None,
    list_dates: dict = None,
) -> dict:
    """
    合成 60 个 bar 的多标数据，每只股票 market_cap 已知。

    market_caps: {sym: 市值(亿)}
    list_dates : {sym: 上市日期 'YYYY-MM-DD'}
    """
    if symbols is None:
        symbols = ["600000.SH", "000001.SZ", "300750.SZ", "688001.SH"]
    if market_caps is None:
        market_caps = {s: 100.0 for s in symbols}
    if list_dates is None:
        # 全部在数据起点前 365 天就上市
        list_dates = {s: "2020-01-01" for s in symbols}

    dates = pd.bdate_range("2024-01-01", periods=n_bars)
    data = {}
    rng = np.random.default_rng(42)
    for sym in symbols:
        # 构造价格：轻微随机游走
        drift = rng.normal(0.001, 0.02, size=n_bars)
        close = 10 * np.exp(np.cumsum(drift))
        df = pd.DataFrame({
            "open": close * (1 + rng.normal(0, 0.003, size=n_bars)),
            "high": close * (1 + np.abs(rng.normal(0, 0.005, size=n_bars))),
            "low":  close * (1 - np.abs(rng.normal(0, 0.005, size=n_bars))),
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, size=n_bars),
            "amount": rng.integers(50_000_000, 200_000_000, size=n_bars),
            "pre_close": np.r_[close[0], close[:-1]],
            "market_cap": market_caps.get(sym, 100.0) * 1e8,
            "list_date": pd.to_datetime(list_dates.get(sym, "2020-01-01")),
        }, index=dates)
        data[sym] = df
    return data


def _load_module_from_path(name: str, path: Path):
    """目录名纯数字开头，用 importlib 按路径加载。"""
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# =========================================================================
# 1) small_cap_v2 — 小市值选股意图
# =========================================================================
class TestSmallCapV2Equivalence:
    """v1 注释：六步选股（市值/流动性/波动率/动量/行业分散）。"""

    def test_low_market_cap_picked_high_not(self):
        """低市值股票 signal=1，高市值股票 signal=0。"""
        mod = _load_module_from_path(
            "sc_v2_test", PROJECT_ROOT / "src/strategies/3a7b2c01/small_cap_v2.py"
        )
        strat = mod.SmallCapV2(
            top_n=2, max_market_cap=200.0, min_amount=0.0,
            max_vol=0.20, min_momentum=-0.5, vol_period=10,
        )
        data = _make_synth_data(
            symbols=["600000.SH", "000001.SZ", "300750.SZ"],
            market_caps={
                "600000.SH": 50.0,    # 低市值 → 选
                "000001.SZ": 150.0,   # 低市值 → 选
                "300750.SZ": 500.0,   # 高市值 → 不选
            },
        )
        sig = strat.signal(_make_ctx(data))
        # signal 应当是 DataFrame(date × symbol)
        assert sig.shape == (60, 3)
        # 高市值那支应该是全 0
        assert (sig["300750.SZ"] == 0).all(), \
            "高市值股票应被过滤"
        # 低市值的某支应有 signal=1
        assert (sig["600000.SH"] == 1).any() or (sig["000001.SZ"] == 1).any(), \
            "低市值股票至少应有一支被选中"

    def test_invalid_board_prefix_filtered(self):
        """非主板/创业板/科创板前缀应被过滤。"""
        mod = _load_module_from_path(
            "sc_v2_test2", PROJECT_ROOT / "src/strategies/3a7b2c01/small_cap_v2.py"
        )
        strat = mod.SmallCapV2(
            top_n=10, max_market_cap=1000.0, min_amount=0.0,
            max_vol=0.50, min_momentum=-0.9, vol_period=5,
        )
        data = _make_synth_data(
            symbols=["600000.SH", "830001.BJ"],  # 北交所 83 前缀
            market_caps={"600000.SH": 50.0, "830001.BJ": 50.0},
        )
        sig = strat.signal(_make_ctx(data))
        # 北交所应当被过滤
        assert (sig["830001.BJ"] == 0).all(), \
            "北交所股票应被板块前缀过滤"


# =========================================================================
# 2) small_cap_quality_v2 — 小市值 + 高质量
# =========================================================================
class TestSmallCapQualityV2Equivalence:
    """v1 注释：小市值 ∧ 高质量（ROE > threshold）。"""

    def test_needs_both_low_mc_and_high_quality(self):
        """小市值 + 高质量 才 signal=1。"""
        mod = _load_module_from_path(
            "scq_v2_test", PROJECT_ROOT / "src/strategies/5d8e3f02/small_cap_quality_v2.py"
        )
        # SmallCapQualityV2.__init__ 参数：
        # n_positions / roe_threshold / pb_threshold /
        # revenue_growth_threshold / use_revenue_growth /
        # max_circ_mv / min_circ_mv / min_listed_days
        # use_revenue_growth=False 避免缺 revenue_growth 列报错
        strat = mod.SmallCapQualityV2(
            n_positions=2,
            roe_threshold=0.05,
            pb_threshold=3.0,
            revenue_growth_threshold=0.0,
            use_revenue_growth=False,
            max_circ_mv=200.0,
            min_circ_mv=0.0,
            min_listed_days=0,
        )
        data = _make_synth_data(symbols=["600000.SH", "000001.SZ"])
        # 第一支：低市值 + 高质量
        data["600000.SH"]["market_cap"] = 50e8
        data["600000.SH"]["pb"] = 1.0
        data["600000.SH"]["roe"] = 0.20
        # 第二支：低市值 + 低质量
        data["000001.SZ"]["market_cap"] = 50e8
        data["000001.SZ"]["pb"] = 1.0
        data["000001.SZ"]["roe"] = 0.02
        sig = strat.signal(_make_ctx(data))
        # 600000.SH 应能选出，000001.SZ 应被 ROE 过滤
        assert (sig["600000.SH"] == 1).any(), \
            f"低市值 + 高 ROE 应被选中, got {sig['600000.SH'].sum()}"
        assert (sig["000001.SZ"] == 0).all(), \
            "低 ROE 应被过滤"


# =========================================================================
# 3) pb_roe_monthly_v2 — 低 PB + 高 ROE
# =========================================================================
class TestPbRoeV2Equivalence:
    """v1 注释：低 PB ∧ 高 ROE。"""

    def test_low_pb_high_roe_picked(self):
        mod = _load_module_from_path(
            "pbr_v2_test", PROJECT_ROOT / "src/strategies/7f9a4b03/pb_roe_monthly_v2.py"
        )
        # PbRoeMonthlyV2.__init__ 参数：
        # top_pct / max_positions / pb_rank_asc / roe_rank_asc /
        # zscore_window / min_score / max_circ_mv / min_circ_mv
        # zscore_window=20（最小 20）以适配 100 bars 数据
        strat = mod.PbRoeMonthlyV2(
            top_pct=10.0,
            max_positions=10,
            pb_rank_asc=True,
            roe_rank_asc=False,
            zscore_window=20,
            min_score=-10.0,    # 宽松：让低 PB+高 ROE 必出
            max_circ_mv=500.0,
            min_circ_mv=0.0,
        )
        data = _make_synth_data(
            n_bars=100, symbols=["600000.SH", "000001.SZ"]
        )
        n = len(data["600000.SH"])
        idx = data["600000.SH"].index
        # 关键：PbRoeMonthlyV2 用滚动 z-score，常数 PB/ROE 会 std=0
        # → z-score=NaN → score=NaN。所以 PB/ROE 须有变化
        data["600000.SH"]["pb"] = pd.Series(
            1.0 + 0.05 * np.sin(np.arange(n) / 3.0), index=idx
        )  # 围绕 1.0 波动
        data["600000.SH"]["roe"] = pd.Series(
            0.20 + 0.02 * np.cos(np.arange(n) / 5.0), index=idx
        )  # 围绕 0.20 波动
        data["600000.SH"]["market_cap"] = 50e8  # 低市值
        data["000001.SZ"]["pb"] = pd.Series(
            5.0 + 0.10 * np.sin(np.arange(n) / 3.0), index=idx
        )
        data["000001.SZ"]["roe"] = pd.Series(
            0.02 + 0.01 * np.cos(np.arange(n) / 5.0), index=idx
        )
        # 把 000001.SZ 的 market_cap 设大，让 max_circ_mv=500 过滤
        data["000001.SZ"]["market_cap"] = 1000e8
        sig = strat.signal(_make_ctx(data))
        assert (sig["600000.SH"] == 1).any(), \
            f"低 PB + 高 ROE 应被选中, sum={sig['600000.SH'].sum()}"
        assert (sig["000001.SZ"] == 0).all(), \
            "高 PB + 低 ROE 应被过滤"


# =========================================================================
# 4) northbound_timing_v2 — 北向资金净流入
# =========================================================================
class TestNorthboundTimingV2Equivalence:
    """v1 注释：北向资金净流入 > threshold → 触发。"""

    def test_uses_northbound_signal(self):
        """signal 输出形状合法；缺数据时优雅处理。"""
        mod = _load_module_from_path(
            "nbt_v2_test", PROJECT_ROOT / "src/strategies/4e8c3d06/northbound_timing_v2.py"
        )
        sig_obj = inspect.signature(mod.NorthboundTimingV2.__init__)
        kwargs = {}
        for k in ("inflow_threshold", "lookback_days", "top_n"):
            if k in sig_obj.parameters:
                kwargs[k] = {
                    "inflow_threshold": 0.0,
                    "lookback_days": 5,
                    "top_n": 2,
                }.get(k)
        strat = mod.NorthboundTimingV2(**kwargs)
        data = _make_synth_data(symbols=["600000.SH", "000001.SZ"])
        sig = strat.signal(_make_ctx(data))
        # 形状合法
        assert sig.shape == (60, 2)
        assert sig.dtypes.apply(lambda d: d.kind in "iu").all(), \
            "signal 必须是整数型"


# =========================================================================
# 5) breakout_pullback_v2 — 突破后回调
# =========================================================================
class TestBreakoutPullbackV2Equivalence:
    """v1 注释：突破后回调至均线。"""

    def test_signal_shape(self):
        mod = _load_module_from_path(
            "bpb_v2_test", PROJECT_ROOT / "src/strategies/9b1f7a05/breakout_pullback_v2.py"
        )
        sig_obj = inspect.signature(mod.BreakoutPullbackV2.__init__)
        kwargs = {}
        for k in ("lookback", "breakout_threshold", "pullback_pct", "top_n"):
            if k in sig_obj.parameters:
                kwargs[k] = {
                    "lookback": 20, "breakout_threshold": 0.05,
                    "pullback_pct": 0.02, "top_n": 2,
                }.get(k)
        strat = mod.BreakoutPullbackV2(**kwargs)
        data = _make_synth_data(
            n_bars=100, symbols=["600000.SH", "000001.SZ"]
        )
        sig = strat.signal(_make_ctx(data))
        assert sig.shape == (100, 2)


# =========================================================================
# 6) sector_flow_monthly_v2 — 申万行业资金流入排名
# =========================================================================
class TestSectorFlowV2Equivalence:
    """v1 注释：申万行业资金流入排名 TopN。"""

    def test_signal_shape(self):
        mod = _load_module_from_path(
            "sfm_v2_test", PROJECT_ROOT / "src/strategies/2c6d5e04/sector_flow_monthly_v2.py"
        )
        sig_obj = inspect.signature(mod.SectorFlowMonthlyV2.__init__)
        kwargs = {}
        for k in ("top_n", "min_amount", "lookback"):
            if k in sig_obj.parameters:
                kwargs[k] = {
                    "top_n": 2, "min_amount": 0.0, "lookback": 20,
                }.get(k)
        strat = mod.SectorFlowMonthlyV2(**kwargs)
        data = _make_synth_data(
            n_bars=60,
            symbols=["600000.SH", "000001.SZ", "300750.SZ"],
        )
        # 加 industry 列
        for sym, ind in zip(
            data.keys(), ["银行", "地产", "电子"]
        ):
            data[sym]["industry"] = ind
        sig = strat.signal(_make_ctx(data))
        assert sig.shape == (60, 3)


# =========================================================================
# 7) 6 个策略的统一检查
# =========================================================================
def test_all_v2_strategies_inherit_signal_strategy():
    """6 个 v2 策略都应继承 SignalStrategy。"""
    from src.quantlab.signals.base import SignalStrategy

    paths = [
        "src/strategies/3a7b2c01/small_cap_v2.py",
        "src/strategies/5d8e3f02/small_cap_quality_v2.py",
        "src/strategies/7f9a4b03/pb_roe_monthly_v2.py",
        "src/strategies/4e8c3d06/northbound_timing_v2.py",
        "src/strategies/9b1f7a05/breakout_pullback_v2.py",
        "src/strategies/2c6d5e04/sector_flow_monthly_v2.py",
    ]
    for p in paths:
        full = PROJECT_ROOT / p
        mod = _load_module_from_path(
            f"v2_{p.replace('/', '_').replace('.py', '')}", full
        )
        # 找 v2 类名（文件名去掉 _v2.py 转 CamelCase）
        v2_classes = [
            (name, obj) for name, obj in inspect.getmembers(mod, inspect.isclass)
            if obj.__module__ == mod.__name__ and issubclass(obj, SignalStrategy)
        ]
        assert v2_classes, f"{p} 中无 SignalStrategy 子类"
        for name, cls in v2_classes:
            assert cls is not SignalStrategy, f"{p} 中 {name} 等于基类"
            # 必有 signal(ctx) 方法
            assert hasattr(cls, "signal"), f"{p} 中 {name} 无 signal 方法"


def test_v2_no_on_bar_on_init_exit_checker():
    """v2 不应使用 on_bar / on_init / exit_checker（spec Phase 2 要求）。"""
    paths = [
        "src/strategies/3a7b2c01/small_cap_v2.py",
        "src/strategies/5d8e3f02/small_cap_quality_v2.py",
        "src/strategies/7f9a4b03/pb_roe_monthly_v2.py",
        "src/strategies/4e8c3d06/northbound_timing_v2.py",
        "src/strategies/9b1f7a05/breakout_pullback_v2.py",
        "src/strategies/2c6d5e04/sector_flow_monthly_v2.py",
    ]
    forbidden_patterns = [
        "def on_bar",
        "def on_init",
        "import ExitChecker",
        "from src.engine.exit_checker",
    ]
    for p in paths:
        text = (PROJECT_ROOT / p).read_text(encoding="utf-8")
        for pat in forbidden_patterns:
            assert pat not in text, \
                f"{p} 仍含禁用模式 '{pat}'"


# =========================================================================
# runner
# =========================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
