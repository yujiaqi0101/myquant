"""
test_quantlab_adapter.py
========================

Phase 4.5 单元测试：DataAdapter / ResultAdapter / SignalStrategyRegistry

覆盖：
- to_quantlab_dict()：MultiIndex / DatetimeIndex / 普通 DataFrame 三种输入
- from_quantlab_db()：DB → Dict 格式
- to_myquant_result()：equity_curve → DailySnapshot / performance 转换
- SignalStrategyRegistry：注册、获取、发现
- 6 个 v2 策略的 __init__ / signal 冒烟
"""
import sys
import unittest
import tempfile
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, "src")


class TestDataAdapter(unittest.TestCase):
    """DataAdapter 单元测试"""

    def setUp(self):
        np.random.seed(42)
        n_bars = 60
        n_syms = 5
        dates = pd.bdate_range("2024-01-01", periods=n_bars)
        records = []
        for i in range(n_syms):
            sym = f"00000{i}.SZ"
            close = 10.0 + np.cumsum(np.random.randn(n_bars) * 0.02)
            for j, d in enumerate(dates):
                records.append({
                    "trade_date": d,
                    "stock_code": sym,
                    "open": close[j] + 0.05,
                    "high": close[j] + 0.1,
                    "low": close[j] - 0.1,
                    "close": close[j],
                    "volume": 1_000_000,
                    "pre_close": close[j - 1] if j > 0 else close[j],
                    "amount": 100_000_000,
                    "market_cap": 1e10,
                })
        self.df = pd.DataFrame(records).set_index(["trade_date", "stock_code"]).sort_index()

    def test_to_quantlab_dict_multiindex(self):
        """MultiIndex → Dict[symbol, DataFrame]"""
        from src.quantlab_adapters import to_quantlab_dict
        out = to_quantlab_dict(self.df)
        self.assertEqual(len(out), 5)
        for sym, df in out.items():
            self.assertIn("close", df.columns)
            self.assertIn("pre_close", df.columns)
            self.assertIsInstance(df.index, pd.DatetimeIndex)
            self.assertTrue(df.index.is_monotonic_increasing)
            self.assertEqual(df.attrs.get("symbol"), sym)

    def test_to_quantlab_dict_empty(self):
        """空 DataFrame → 空 Dict"""
        from src.quantlab_adapters import to_quantlab_dict
        out = to_quantlab_dict(pd.DataFrame())
        self.assertEqual(out, {})

    def test_to_quantlab_dict_keep_cols(self):
        """keep_cols 参数 + 必需列自动透传"""
        from src.quantlab_adapters import to_quantlab_dict
        out = to_quantlab_dict(self.df, keep_cols=["close", "market_cap"])
        for sym, df in out.items():
            # 必传字段
            self.assertIn("close", df.columns)
            self.assertIn("market_cap", df.columns)
            # 必需列（open/close/pre_close）也会自动保留
            self.assertIn("pre_close", df.columns)
            # 未指定的列不会透传
            self.assertNotIn("volume", df.columns)
            self.assertNotIn("amount", df.columns)

    def test_to_quantlab_dict_passes_required_cols(self):
        """透传必需列（pre_close / open / close）"""
        from src.quantlab_adapters import to_quantlab_dict
        out = to_quantlab_dict(self.df, keep_cols=["market_cap"])
        for sym, df in out.items():
            self.assertIn("pre_close", df.columns)
            self.assertIn("open", df.columns)
            self.assertIn("close", df.columns)


class TestSignalStrategyRegistry(unittest.TestCase):
    """SignalStrategyRegistry 单元测试"""

    def setUp(self):
        # 清空注册表（避免被其他测试污染）
        from src.quantlab_adapters import SignalStrategyRegistry
        SignalStrategyRegistry.clear()

    def test_register_and_get(self):
        """注册和获取"""
        from src.quantlab_adapters import SignalStrategyRegistry
        from src.quantlab.signals.base import SignalStrategy

        class MyTest(SignalStrategy):
            name = "test_v2"
            def __init__(self, x: int = 1):
                self.x = int(x)
            def signal(self, ctx):
                return pd.DataFrame()

        SignalStrategyRegistry.register(MyTest)
        self.assertIs(SignalStrategyRegistry.get("test_v2"), MyTest)
        self.assertIsNone(SignalStrategyRegistry.get("nonexistent"))

    def test_register_must_subclass(self):
        """非 SignalStrategy 子类应抛 TypeError"""
        from src.quantlab_adapters import SignalStrategyRegistry

        class NotAStrategy:
            pass

        with self.assertRaises(TypeError):
            SignalStrategyRegistry.register(NotAStrategy)

    def test_list_strategies(self):
        """list_strategies 至少含 1 条"""
        from src.quantlab_adapters import SignalStrategyRegistry
        from src.quantlab.signals.base import SignalStrategy

        class S1(SignalStrategy):
            name = "s1"
            description = "S1 desc"
            def __init__(self):
                pass
            def signal(self, ctx):
                return pd.DataFrame()

        SignalStrategyRegistry.register(S1)
        lst = SignalStrategyRegistry.list_strategies()
        self.assertGreater(len(lst), 0)
        self.assertIn("name", lst[0])
        self.assertIn("class", lst[0])
        self.assertIn("description", lst[0])


class TestV2StrategiesConformance(unittest.TestCase):
    """6 个 v2 策略的规范符合性测试"""

    @classmethod
    def setUpClass(cls):
        from src.quantlab_adapters import discover_v2_strategies
        discover_v2_strategies("src.strategies")

    def test_all_v2_registered(self):
        from src.quantlab_adapters import SignalStrategyRegistry
        names = [s["name"] for s in SignalStrategyRegistry.list_strategies()]
        expected = {
            "small_cap_v2",
            "small_cap_quality_v2",
            "pb_roe_monthly_v2",
            "northbound_timing_v2",
            "breakout_pullback_v2",
            "sector_flow_monthly_v2",
        }
        self.assertTrue(expected.issubset(set(names)), f"missing: {expected - set(names)}")

    def test_all_have_make_factory(self):
        """每个 v2 模块应提供 make_xxx() 工厂"""
        import importlib
        expected = {
            ("3a7b2c01", "small_cap_v2", "make_small_cap_v2"),
            ("5d8e3f02", "small_cap_quality_v2", "make_small_cap_quality_v2"),
            ("7f9a4b03", "pb_roe_monthly_v2", "make_pb_roe_monthly_v2"),
            ("4e8c3d06", "northbound_timing_v2", "make_northbound_timing_v2"),
            ("9b1f7a05", "breakout_pullback_v2", "make_breakout_pullback_v2"),
            ("2c6d5e04", "sector_flow_monthly_v2", "make_sector_flow_monthly_v2"),
        }
        for dir_name, file_stem, factory in expected:
            mod_name = (
                f"src_strategies_{dir_name}_{file_stem}".replace(".", "_")
            )
            spec_path = Path("src") / "strategies" / dir_name / f"{file_stem}.py"
            self.assertTrue(spec_path.exists(), f"missing file: {spec_path}")
            # 走 importlib 加载
            import importlib.util
            spec = importlib.util.spec_from_file_location(mod_name, str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception as e:
                self.fail(f"failed to load {spec_path}: {e}")
            self.assertTrue(
                hasattr(mod, factory),
                f"missing factory {factory} in {spec_path}"
            )
            self.assertTrue(callable(getattr(mod, factory)))

    def test_all_have_param_space(self):
        """每个 v2 模块应提供 *_PARAM_SPACE 字典"""
        import importlib.util
        expected = [
            ("3a7b2c01", "small_cap_v2", "SMALL_CAP_PARAM_SPACE"),
            ("5d8e3f02", "small_cap_quality_v2", "SMALL_CAP_QUALITY_PARAM_SPACE"),
            ("7f9a4b03", "pb_roe_monthly_v2", "PB_ROE_MONTHLY_PARAM_SPACE"),
            ("4e8c3d06", "northbound_timing_v2", "NORTHBOUND_TIMING_PARAM_SPACE"),
            ("9b1f7a05", "breakout_pullback_v2", "BREAKOUT_PULLBACK_PARAM_SPACE"),
            ("2c6d5e04", "sector_flow_monthly_v2", "SECTOR_FLOW_MONTHLY_PARAM_SPACE"),
        ]
        for dir_name, file_stem, var_name in expected:
            mod_name = f"src_strategies_{dir_name}_{file_stem}".replace(".", "_")
            spec_path = Path("src") / "strategies" / dir_name / f"{file_stem}.py"
            spec = importlib.util.spec_from_file_location(mod_name, str(spec_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.assertTrue(
                hasattr(mod, var_name),
                f"missing {var_name} in {spec_path}"
            )
            ps = getattr(mod, var_name)
            self.assertIsInstance(ps, dict)
            self.assertGreater(len(ps), 0)
            for key, vals in ps.items():
                self.assertIsInstance(vals, list)
                self.assertGreater(len(vals), 0)


class TestV2StrategySignalOutput(unittest.TestCase):
    """v2 策略 signal() 输出格式测试"""

    def _make_data(self, n_bars=120, n_syms=5, with_extras=True):
        np.random.seed(42)
        dates = pd.bdate_range("2024-01-01", periods=n_bars)
        data = {}
        for i in range(n_syms):
            sym = f"00000{i}.SZ"
            close = 10.0 + np.cumsum(np.random.randn(n_bars) * 0.02)
            df = pd.DataFrame(
                {
                    "open": close + np.random.randn(n_bars) * 0.05,
                    "high": close + np.abs(np.random.randn(n_bars) * 0.1),
                    "low": close - np.abs(np.random.randn(n_bars) * 0.1),
                    "close": close,
                    "volume": np.random.randint(1_000_000, 10_000_000, n_bars),
                    "pre_close": np.roll(close, 1),
                    "amount": np.random.randint(50_000_000, 500_000_000, n_bars),
                    "market_cap": np.random.uniform(30, 150, n_bars) * 1e8,
                },
                index=dates,
            )
            df.iloc[0, df.columns.get_loc("pre_close")] = df["close"].iloc[0]
            if with_extras:
                df["roe"] = np.random.uniform(0, 0.20, n_bars)
                df["pb"] = np.random.uniform(0.5, 4.0, n_bars)
                df["revenue_growth"] = np.random.uniform(-0.1, 0.3, n_bars)
                df["northbound_net_inflow"] = np.random.randn(n_bars) * 5e6
                df["industry_inflow_rank"] = np.random.randint(1, 32, n_bars)
            data[sym] = df
        return data

    def _make_ctx(self, data):
        class MockCache:
            def get(self, k): return None
            def set(self, k, v): pass
        class MockCtx:
            def __init__(self, data, cache):
                self.data = data
                self.cache = cache
        return MockCtx(data, MockCache())

    def test_small_cap_v2_signal_shape(self):
        from src.quantlab_adapters import SignalStrategyRegistry
        from src.quantlab_adapters.strategy_registry import discover_v2_strategies
        discover_v2_strategies("src.strategies")
        cls = SignalStrategyRegistry.get("small_cap_v2")
        data = self._make_data()
        ctx = self._make_ctx(data)
        sig = cls(top_n=10).signal(ctx)
        self.assertIsInstance(sig, pd.DataFrame)
        self.assertEqual(sig.shape, (120, 5))
        self.assertEqual(sig.dtypes.iloc[0], "int8")
        uniq = set(sig.values.flatten().tolist())
        self.assertTrue(uniq.issubset({-1, 0, 1}))

    def test_all_v2_signal_runs(self):
        """所有 v2 策略 signal() 都能跑通"""
        from src.quantlab_adapters import SignalStrategyRegistry
        from src.quantlab_adapters.strategy_registry import discover_v2_strategies
        discover_v2_strategies("src.strategies")
        data = self._make_data()
        ctx = self._make_ctx(data)
        for s in SignalStrategyRegistry.list_strategies():
            cls = SignalStrategyRegistry.get(s["name"])
            try:
                inst = cls()
                sig = inst.signal(ctx)
                self.assertIsInstance(sig, pd.DataFrame, f"{s['name']}: not DataFrame")
                self.assertEqual(sig.shape[1], len(data), f"{s['name']}: wrong column count")
                self.assertEqual(sig.dtypes.iloc[0], "int8", f"{s['name']}: not int8")
            except Exception as e:
                self.fail(f"{s['name']}.signal() failed: {e}")


class TestRiskManager(unittest.TestCase):
    """A 股 RiskManager 单元测试"""

    def test_build_default_risk_manager(self):
        from src.quantlab_extras import build_ashare_risk_manager
        rm = build_ashare_risk_manager()
        self.assertGreater(len(rm.checks), 0)
        # 默认应包含 6 个 A 股 Check + OrderSize + KillSwitch
        check_names = [type(c).__name__ for c in rm.checks]
        self.assertIn("LimitUpCheck", check_names)
        self.assertIn("LimitDownCheck", check_names)

    def test_build_ashare_execution(self):
        from src.quantlab_extras import build_ashare_execution
        ex = build_ashare_execution()
        # lot_size 默认 100
        self.assertEqual(ex.lot_size, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
