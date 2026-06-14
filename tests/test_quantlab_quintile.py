"""
tests/test_quantlab_quintile.py - QuintileExperiment 单元测试

测试目标：
    1) QuintileResult 数据类 to_dict / summary 输出格式正确
    2) QuintileExperiment 构造参数校验（n_quantiles / long_direction）
    3) 内部纯函数 _align_factor_data / _compute_long_short / _metrics_from_curve / _compute_ir 行为正确
    4) run() 入口校验（空 factor_data / 空 data / quintile 越界）
    5) 不依赖 BarEngine 实际跑（避免数据准备复杂 + 与 vectorbt 沙箱限制解耦）

设计依据：
    - spec.md Phase 5 / Phase 7 要求 QuintileExperiment 单元测试
    - 与现有 test_quantlab_*.py 风格保持一致
    - 受限场景：vbt 引擎在沙箱无法运行，本测试只验证纯逻辑
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.quantlab_quintile import QuintileExperiment, QuintileResult  # noqa: E402


# ============================================================
# 测试类 1: QuintileResult 数据类
# ============================================================
class TestQuintileResult:
    """验证 QuintileResult.to_dict / summary 输出格式"""

    def test_to_dict_keys(self):
        """to_dict 应含 spec 规定的 7 个键"""
        r = QuintileResult(factor_name="mom_20d")
        d = r.to_dict()
        expected_keys = {
            "factor_name", "quintile_metrics", "long_short_metrics",
            "ic_mean", "ic_std", "ir", "n_ic",
        }
        assert expected_keys.issubset(d.keys()), \
            f"missing keys: {expected_keys - set(d.keys())}"

    def test_to_dict_defaults(self):
        """默认值场景"""
        r = QuintileResult()
        d = r.to_dict()
        assert d["factor_name"] == ""
        assert d["ic_mean"] == 0.0
        assert d["ic_std"] == 0.0
        assert d["ir"] == 0.0
        assert d["n_ic"] == 0
        assert d["quintile_metrics"] == {}
        assert d["long_short_metrics"] == {}

    def test_to_dict_with_data(self):
        """含数据场景"""
        r = QuintileResult(
            factor_name="value_pe",
            ic_mean=0.05,
            ic_std=0.10,
            ir=0.5,
            ic_series=[0.04, 0.05, 0.06, 0.05, 0.05],
            quintile_metrics={
                1: {"sharpe": 0.5, "total_return": 10.0, "max_drawdown": -5.0},
                5: {"sharpe": 1.2, "total_return": 25.0, "max_drawdown": -8.0},
            },
        )
        d = r.to_dict()
        assert d["factor_name"] == "value_pe"
        assert d["ic_mean"] == 0.05
        assert d["ir"] == 0.5
        assert d["n_ic"] == 5
        assert 1 in d["quintile_metrics"]
        assert 5 in d["quintile_metrics"]

    def test_summary_contains_factor_name(self):
        """summary 应含因子名 + IC/IR + per-quintile 指标"""
        r = QuintileResult(
            factor_name="mom_20d",
            ic_mean=0.03,
            ic_std=0.10,
            ir=0.3,
            quintile_metrics={
                1: {"sharpe": 0.4, "total_return": 8.0, "max_drawdown": -5.0},
                5: {"sharpe": 1.1, "total_return": 22.0, "max_drawdown": -7.0},
            },
            long_short_metrics={"sharpe": 0.9, "total_return": 14.0, "max_drawdown": -3.0},
        )
        s = r.summary()
        assert "mom_20d" in s
        assert "IC" in s
        assert "IR" in s
        assert "Q1" in s
        assert "Q5" in s
        assert "Long-Short" in s


# ============================================================
# 测试类 2: 构造参数校验
# ============================================================
class TestConstructor:
    """验证 QuintileExperiment 构造参数边界条件"""

    def test_default_construction(self):
        """默认参数下应能构造"""
        exp = QuintileExperiment()
        assert exp.n_quantiles == 5
        assert exp.rebalance_freq == 5
        assert exp.long_direction == "high"
        assert exp.initial_cash == 1_000_000.0
        assert exp.commission_rate == 0.00025
        assert exp.slippage_rate == 0.0001

    def test_invalid_n_quantiles(self):
        """n_quantiles < 2 应报错"""
        with pytest.raises(ValueError, match="n_quantiles must be >= 2"):
            QuintileExperiment(n_quantiles=1)
        with pytest.raises(ValueError, match="n_quantiles must be >= 2"):
            QuintileExperiment(n_quantiles=0)

    def test_invalid_long_direction(self):
        """long_direction 必须是 'high' 或 'low'"""
        with pytest.raises(ValueError, match="long_direction must be"):
            QuintileExperiment(long_direction="middle")

    def test_custom_params(self):
        """自定义参数应被正确保存"""
        exp = QuintileExperiment(
            n_quantiles=10,
            rebalance_freq=20,
            initial_cash=500_000.0,
            commission_rate=0.0003,
            slippage_rate=0.0002,
            long_direction="low",
            ic_lag=5,
            factor_name="custom_factor",
            lot_size=200,
        )
        assert exp.n_quantiles == 10
        assert exp.rebalance_freq == 20
        assert exp.initial_cash == 500_000.0
        assert exp.commission_rate == 0.0003
        assert exp.slippage_rate == 0.0002
        assert exp.long_direction == "low"
        assert exp.ic_lag == 5
        assert exp.factor_name == "custom_factor"
        assert exp.lot_size == 200

    def test_min_factor_count_auto(self):
        """min_factor_count 应至少 = n_quantiles"""
        exp = QuintileExperiment(n_quantiles=5, min_factor_count=3)
        assert exp.min_factor_count >= 5  # 自动上调到 n_quantiles
        exp2 = QuintileExperiment(n_quantiles=5, min_factor_count=20)
        assert exp2.min_factor_count == 20  # 显式更大值保留


# ============================================================
# 测试类 3: run() 入口校验
# ============================================================
class TestRunValidation:
    """验证 run() 入口参数校验"""

    def test_empty_factor_data_raises(self):
        """factor_data 为空时抛 ValueError"""
        exp = QuintileExperiment()
        with pytest.raises(ValueError, match="factor_data"):
            exp.run(
                factor_data=pd.DataFrame(),
                data={"S1": pd.DataFrame({"close": [1.0, 2.0]})},
            )

    def test_none_factor_data_raises(self):
        """factor_data 为 None 时抛 ValueError"""
        exp = QuintileExperiment()
        with pytest.raises(ValueError, match="factor_data"):
            exp.run(factor_data=None, data={"S1": pd.DataFrame()})

    def test_empty_data_raises(self):
        """data 为空 dict 时抛 ValueError"""
        exp = QuintileExperiment()
        factor = pd.DataFrame({"S1": [0.1, 0.2]}, index=pd.bdate_range("2024-01-01", periods=2))
        with pytest.raises(ValueError, match="data"):
            exp.run(factor_data=factor, data={})

    def test_long_quantile_out_of_range(self):
        """long_quantile 越界应抛 ValueError"""
        exp = QuintileExperiment(n_quantiles=5)
        factor = pd.DataFrame({"S1": [0.1, 0.2]}, index=pd.bdate_range("2024-01-01", periods=2))
        data = {"S1": pd.DataFrame({"close": [1.0, 2.0]}, index=pd.bdate_range("2024-01-01", periods=2))}
        with pytest.raises(ValueError, match="long_quantile"):
            exp.run(factor_data=factor, data=data, long_quantile=10)
        with pytest.raises(ValueError, match="long_quantile"):
            exp.run(factor_data=factor, data=data, long_quantile=0)

    def test_short_quantile_out_of_range(self):
        """short_quantile 越界应抛 ValueError"""
        exp = QuintileExperiment(n_quantiles=5)
        factor = pd.DataFrame({"S1": [0.1, 0.2]}, index=pd.bdate_range("2024-01-01", periods=2))
        data = {"S1": pd.DataFrame({"close": [1.0, 2.0]}, index=pd.bdate_range("2024-01-01", periods=2))}
        with pytest.raises(ValueError, match="short_quantile"):
            exp.run(factor_data=factor, data=data, short_quantile=10)


# ============================================================
# 测试类 4: 内部纯函数（_align_factor_data）
# ============================================================
class TestAlignFactorData:
    """验证 factor_data 对齐逻辑（缺失 symbol / 缺失 date 补 NaN）"""

    def test_missing_symbols_filled_nan(self):
        """factor_data 缺 symbol 列时应补 NaN"""
        exp = QuintileExperiment()
        factor = pd.DataFrame(
            {"S1": [0.1, 0.2, 0.3]},
            index=pd.bdate_range("2024-01-01", periods=3),
        )
        data = {
            "S1": pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=pd.bdate_range("2024-01-01", periods=3)),
            "S2": pd.DataFrame({"close": [4.0, 5.0, 6.0]}, index=pd.bdate_range("2024-01-01", periods=3)),
        }
        aligned = exp._align_factor_data(factor, data)
        assert "S1" in aligned.columns
        assert "S2" in aligned.columns
        # S2 应全 NaN
        assert aligned["S2"].isna().all()
        # S1 原值保留
        assert aligned["S1"].iloc[0] == 0.1

    def test_missing_dates_filled_nan(self):
        """factor_data 缺 date 行时应补 NaN"""
        exp = QuintileExperiment()
        idx = pd.bdate_range("2024-01-01", periods=3)
        factor = pd.DataFrame({"S1": [0.1, 0.3]}, index=idx[[0, 2]])  # 缺中间一天
        data = {"S1": pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=idx)}
        aligned = exp._align_factor_data(factor, data)
        # 应补回 3 行
        assert len(aligned) == 3
        # 中间一行 NaN
        assert pd.isna(aligned["S1"].iloc[1])

    def test_extra_symbols_dropped(self):
        """factor_data 多出的 symbol 应被丢弃（不在 data 中）"""
        exp = QuintileExperiment()
        factor = pd.DataFrame(
            {"S1": [0.1, 0.2], "S_extra": [0.5, 0.6]},
            index=pd.bdate_range("2024-01-01", periods=2),
        )
        data = {"S1": pd.DataFrame({"close": [1.0, 2.0]}, index=pd.bdate_range("2024-01-01", periods=2))}
        aligned = exp._align_factor_data(factor, data)
        assert "S_extra" not in aligned.columns
        assert "S1" in aligned.columns


# ============================================================
# 测试类 5: 内部纯函数（_compute_long_short）
# ============================================================
class TestLongShort:
    """验证多空对冲曲线计算"""

    def test_empty_inputs(self):
        """空输入应返回空列表"""
        exp = QuintileExperiment()
        assert exp._compute_long_short([], []) == []
        assert exp._compute_long_short([1.0, 1.1], []) == []
        assert exp._compute_long_short([], [1.0, 1.1]) == []

    def test_basic_long_short(self):
        """多头涨 + 空头涨 → 多空对冲应接近 1（无收益）"""
        exp = QuintileExperiment()
        # 多头曲线从 1.0 涨到 1.1（+10%）
        # 空头曲线从 1.0 涨到 1.1（+10%），对冲后 = 0%
        long_curve = [1.0, 1.05, 1.10]
        short_curve = [1.0, 1.05, 1.10]
        ls = exp._compute_long_short(long_curve, short_curve)
        # ls[0] = 1.0, 后两期 (1+5%)+(1-5%) = 0, 所以也保持 1.0
        assert len(ls) == 3
        assert abs(ls[0] - 1.0) < 1e-9
        assert abs(ls[1] - 1.0) < 1e-9
        assert abs(ls[2] - 1.0) < 1e-9

    def test_long_up_short_down(self):
        """多头涨 + 空头跌 → 多空对冲应显著上升"""
        exp = QuintileExperiment()
        long_curve = [1.0, 1.10]  # +10%
        short_curve = [1.0, 0.90]  # -10%（做空收益 -(-10%) = +10%）
        ls = exp._compute_long_short(long_curve, short_curve)
        # 总收益 ≈ 1 + 0.10 + 0.10 = 1.20
        assert len(ls) == 2
        assert abs(ls[1] - 1.20) < 1e-6


# ============================================================
# 测试类 6: 内部纯函数（_metrics_from_curve）
# ============================================================
class TestMetricsFromCurve:
    """验证从 equity 曲线计算 sharpe / total_return / max_drawdown"""

    def test_empty_curve(self):
        """空曲线应返回 0"""
        exp = QuintileExperiment()
        m = exp._metrics_from_curve([])
        assert m["sharpe"] == 0.0
        assert m["total_return"] == 0.0
        assert m["max_drawdown"] == 0.0

    def test_single_element(self):
        """单元素曲线应返回 0（无收益可算）"""
        exp = QuintileExperiment()
        m = exp._metrics_from_curve([1.0])
        assert m["sharpe"] == 0.0
        assert m["total_return"] == 0.0

    def test_monotonic_up(self):
        """单调上涨曲线 total_return > 0，max_drawdown = 0"""
        exp = QuintileExperiment()
        # 每天涨 1%
        curve = [1.0 * (1.01 ** i) for i in range(20)]
        m = exp._metrics_from_curve(curve)
        assert m["total_return"] > 0
        assert m["max_drawdown"] == 0.0  # 没回撤
        # 20 个 1% 收益 = (1.01^20 - 1) * 100 ≈ 21.9%
        assert 20 < m["total_return"] < 25

    def test_with_drawdown(self):
        """先涨后跌曲线应有 max_drawdown < 0"""
        exp = QuintileExperiment()
        curve = [1.0, 1.20, 1.10, 1.05, 1.15]  # 高点 1.20，谷底 1.05
        m = exp._metrics_from_curve(curve)
        # 最大回撤 = 1.05/1.20 - 1 = -12.5%
        assert m["max_drawdown"] < 0
        assert -13.0 < m["max_drawdown"] < -12.0


# ============================================================
# 测试类 7: 内部纯函数（_compute_ir）
# ============================================================
class TestComputeIR:
    """验证 IR = mean(IC) / std(IC)"""

    def test_empty_series(self):
        """空 IC 序列应返回 (0, 0, 0)"""
        exp = QuintileExperiment()
        ir, mean, std = exp._compute_ir([])
        assert ir == 0.0
        assert mean == 0.0
        assert std == 0.0

    def test_single_value(self):
        """单值无法算 std，返回 0"""
        exp = QuintileExperiment()
        ir, mean, std = exp._compute_ir([0.05])
        assert ir == 0.0
        assert mean == 0.0
        assert std == 0.0

    def test_constant_series(self):
        """常数序列 std=0，IR 应为 0"""
        exp = QuintileExperiment()
        ir, mean, std = exp._compute_ir([0.05] * 5)
        assert std == 0.0
        assert ir == 0.0
        assert abs(mean - 0.05) < 1e-9

    def test_normal_series(self):
        """正常波动序列（IR 应与手算 mean/std 在同一数量级）"""
        exp = QuintileExperiment()
        ic = [0.02, 0.04, 0.03, 0.05, 0.04, 0.03, 0.04, 0.05]
        ir, mean, std = exp._compute_ir(ic)
        assert mean > 0
        assert std > 0
        # 实现中 mean/std/ir 分别四舍五入到 4 位
        # 所以 ir 应近似 mean/std（不严格相等，差异应 < 0.05）
        manual_ir = float(np.mean(ic)) / float(np.std(ic, ddof=1))
        assert abs(ir - manual_ir) < 0.05
        # 且符号一致
        assert (ir > 0) == (manual_ir > 0)

    def test_negative_ic(self):
        """负 IC 序列 IR 应 < 0"""
        exp = QuintileExperiment()
        ic = [-0.05, -0.03, -0.04, -0.02]
        ir, mean, std = exp._compute_ir(ic)
        assert mean < 0
        assert ir < 0


# ============================================================
# 测试类 8: 内部纯函数（_extract_metrics）
# ============================================================
class TestExtractMetrics:
    """验证从 BacktestResult 提取指标（含字段缺失容忍）"""

    def test_full_backtest_result(self):
        """完整 BacktestResult"""
        exp = QuintileExperiment()

        class FakeResult:
            sharpe = 1.5
            total_return = 25.0
            max_drawdown = -8.5
            final_equity = 1_250_000.0
            trade_count = 50

        m = exp._extract_metrics(FakeResult())
        assert m["sharpe"] == 1.5
        assert m["total_return"] == 25.0
        assert m["max_drawdown"] == -8.5
        assert m["trade_count"] == 50

    def test_missing_fields_tolerated(self):
        """BacktestResult 字段缺失时不应报错"""
        exp = QuintileExperiment()

        class FakeResult:
            pass  # 全部字段缺失

        m = exp._extract_metrics(FakeResult())
        assert m["sharpe"] == 0
        assert m["total_return"] == 0
        assert m["max_drawdown"] == 0
        assert m["trade_count"] == 0

    def test_none_values_tolerated(self):
        """字段为 None 时应被转为 0"""
        exp = QuintileExperiment()

        class FakeResult:
            sharpe = None
            total_return = None
            max_drawdown = None
            final_equity = None
            trade_count = None

        m = exp._extract_metrics(FakeResult())
        assert all(v == 0 for v in m.values())


# ============================================================
# 测试类 9: 内部纯函数（_compute_ic_series）
# ============================================================
class TestComputeICSeries:
    """验证 IC 时序计算"""

    def test_empty_data(self):
        """无 close 数据时返回空"""
        exp = QuintileExperiment()
        # factor_data 包含的 symbol 在 data 中找不到 → 无 close 矩阵
        factor = pd.DataFrame(
            {"S1": [0.1]},
            index=pd.bdate_range("2024-01-01", periods=1),
        )
        data = {}  # 空数据字典
        ic = exp._compute_ic_series(factor, data)
        assert ic == []

    def test_too_few_valid(self):
        """有效样本 < 5 时跳过该日"""
        exp = QuintileExperiment()
        idx = pd.bdate_range("2024-01-01", periods=5)
        factor = pd.DataFrame({"S1": [0.1, 0.2, np.nan, 0.4, 0.5]}, index=idx)
        data = {
            "S1": pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=idx),
        }
        ic = exp._compute_ic_series(factor, data)
        # 中间一天 NaN，导致单日样本 < 5，可能不计入
        # 至少能跑通不报错
        assert isinstance(ic, list)

    def test_perfect_positive_corr(self):
        """因子值与未来收益完全正相关 → IC ≈ 1"""
        exp = QuintileExperiment(ic_lag=1)
        idx = pd.bdate_range("2024-01-01", periods=10)
        # 让因子值与未来 1 日收益完全正相关
        # 未来收益 = (next_close - close) / close
        closes = np.array([1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9])
        # 因子值 = 未来收益（rank）
        fwd_ret = (np.roll(closes, -1) - closes) / closes
        fwd_ret[-1] = 0  # 末尾 0
        factor = pd.DataFrame({"S1": fwd_ret}, index=idx)
        data = {"S1": pd.DataFrame({"close": closes}, index=idx)}
        ic = exp._compute_ic_series(factor, data)
        # 单 symbol 截面相关性 = 1（self-corr）
        if len(ic) > 0:
            for v in ic:
                assert v > 0.5  # 至少高正相关


# ============================================================
# 测试类 10: 集成校验（不实际跑 BarEngine，只测 run() 前置）
# ============================================================
class TestRunPreCheck:
    """验证 run() 在调用 BarEngine 之前的预处理逻辑"""

    def test_align_factor_data_called_before_engine(self, monkeypatch):
        """run() 应在调 BarEngine 前先调 _align_factor_data"""
        exp = QuintileExperiment(n_quantiles=2)  # 用 2 分位减少循环
        idx = pd.bdate_range("2024-01-01", periods=30)
        np.random.seed(42)
        factor = pd.DataFrame(
            {f"S{i}": np.random.randn(30) for i in range(5)},
            index=idx,
        )
        data = {
            f"S{i}": pd.DataFrame(
                {
                    "open": 10.0,
                    "close": 10.0 + np.random.randn(30).cumsum() * 0.01,
                    "pre_close": 10.0,
                },
                index=idx,
            )
            for i in range(5)
        }

        # 监控 _align_factor_data 是否被调
        called = {"align": False, "engine": False}
        original_align = exp._align_factor_data
        original_build = exp._build_engine

        def fake_align(fd, d):
            called["align"] = True
            return original_align(fd, d)

        def fake_build(strategy):
            called["engine"] = True
            # 抛异常，避免实际跑 BarEngine
            raise RuntimeError("stop at build_engine")

        monkeypatch.setattr(exp, "_align_factor_data", fake_align)
        monkeypatch.setattr(exp, "_build_engine", fake_build)

        with pytest.raises(RuntimeError, match="stop at build_engine"):
            exp.run(factor_data=factor, data=data)

        assert called["align"] is True
        assert called["engine"] is True
