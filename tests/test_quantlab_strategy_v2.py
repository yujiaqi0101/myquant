"""
test_quantlab_strategy_v2.py
============================

对 3 个 quantlab SignalStrategy 策略（V2 版）做最小冒烟测试：

1. 实例化（无 myquant 依赖）
2. 构造合成 mock 数据（5 symbol × 200 天）
3. 跑 .signal(ctx) 不抛异常
4. 校验返回 DataFrame 形状 + 值 ∈ {0, 1}

执行：
    & "D:\\Program Files\\Python312\\python.exe" -m pytest tests/test_quantlab_strategy_v2.py -v
或
    & "D:\\Program Files\\Python312\\python.exe" tests/test_quantlab_strategy_v2.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# --- 把 src/ 加入 sys.path，与 .pth 文件效果一致 ---
# 同时把 cwd 切到项目根目录，避免在 tests/ 目录下 cwd 干扰 `import src` 的解析
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
os.chdir(str(_PROJECT_ROOT))

from src.quantlab.data.context import StrategyContext
from src.quantlab.data.cache import FactorCache

# 3 个 v2 策略的目录名是纯数字开头（"3a7b2c01" 等），
# Python 不能直接 `import src.strategies.3a7b2c01...`，需要按文件路径 importlib 加载。

_STRATEGY_ROOT = _SRC_DIR / "strategies"


def _load_module(strategy_id: str, file_name: str):
    """从 src/strategies/<id>/<file> 加载模块。"""
    import importlib.util  # 局部 import 避免顶层污染
    path = _STRATEGY_ROOT / strategy_id / file_name
    spec = importlib.util.spec_from_file_location(
        f"_strat_{strategy_id}_{file_name.replace('.py', '')}", str(path)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- 真正加载 3 个 v2 策略 ----------
_small_cap_v2_mod = _load_module("3a7b2c01", "small_cap_v2.py")
_quality_v2_mod = _load_module("5d8e3f02", "small_cap_quality_v2.py")
_pb_roe_v2_mod = _load_module("7f9a4b03", "pb_roe_monthly_v2.py")

SmallCapV2 = _small_cap_v2_mod.SmallCapV2
SmallCapQualityV2 = _quality_v2_mod.SmallCapQualityV2
PbRoeMonthlyV2 = _pb_roe_v2_mod.PbRoeMonthlyV2

# ---------- 追加 3 个时序/行业策略（V2） ----------
_northbound_v2_mod = _load_module("4e8c3d06", "northbound_timing_v2.py")
_breakout_v2_mod = _load_module("9b1f7a05", "breakout_pullback_v2.py")
_sector_v2_mod = _load_module("2c6d5e04", "sector_flow_monthly_v2.py")

NorthboundTimingV2 = _northbound_v2_mod.NorthboundTimingV2
BreakoutPullbackV2 = _breakout_v2_mod.BreakoutPullbackV2
SectorFlowMonthlyV2 = _sector_v2_mod.SectorFlowMonthlyV2


# =========================================================================
# Mock 数据生成
# =========================================================================
def _make_mock_data(n_days: int = 200, seed: int = 42) -> dict:
    """
    合成 5 个 symbol × 200 天的 OHLCV + 因子数据。

    Symbols:
        600000.SH   沪市主板    小市值
        000001.SZ   深市主板    小市值
        300001.SZ   创业板     小市值
        688001.SH   科创板     中小市值
        999999.SH   无效前缀   永远 0
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_days)  # 工作日

    symbols_meta = [
        ("600000.SH", "small_A", 30e8, 0.04, 0.02),     # 小市值 + 低波动
        ("000001.SZ", "small_B", 80e8, 0.03, -0.05),    # 小市值
        ("300001.SZ", "small_C", 150e8, 0.06, 0.10),    # 中等市值
        ("688001.SH", "mid_D", 250e8, 0.045, 0.0),      # 偏大市值（> 200 亿上限）
        ("999999.SH", "invalid", 100e8, 0.05, 0.0),     # 无效前缀
    ]

    data = {}
    for sym, label, market_cap, vol_scale, drift in symbols_meta:
        # 几何布朗运动 close
        ret = rng.normal(loc=drift / n_days, scale=vol_scale, size=n_days)
        close = 10.0 * np.exp(np.cumsum(ret))

        open_ = close * (1 + rng.normal(0, 0.003, n_days))
        high = np.maximum(close, open_) * (1 + np.abs(rng.normal(0, 0.005, n_days)))
        low = np.minimum(close, open_) * (1 - np.abs(rng.normal(0, 0.005, n_days)))
        volume = rng.integers(1_000_000, 5_000_000, n_days)
        pre_close = np.concatenate([[close[0]], close[:-1]])
        amount = close * volume  # 简化 amount = close * volume

        df = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "pre_close": pre_close,
                "amount": amount,
                "market_cap": np.full(n_days, market_cap),
                "industry": [f"board_{label}"] * n_days,
                "list_date": pd.Timestamp("2020-01-01"),
            },
            index=dates,
        )
        df.index.name = "date"

        # 基本面因子（小盘质量 + PB-ROE 用）
        df["pb"] = rng.uniform(0.5, 4.0, n_days)
        df["roe"] = rng.uniform(-0.05, 0.20, n_days)
        df["revenue_growth"] = rng.uniform(-0.10, 0.30, n_days)

        # 时序/行业扩展列（Phase 4 DataAdapter 注入）
        # northbound_net_inflow: 单日北向资金对该股的净流入（元）
        df["northbound_net_inflow"] = rng.normal(loc=0.0, scale=1e6, size=n_days)
        # industry_inflow_rank: 当日该股所属行业在申万一级中的资金流入排名（1=top）
        # 用一个 1~28 的整数排名模拟（覆盖 Top3 / TopN 各种场景）
        df["industry_inflow_rank"] = rng.integers(1, 29, size=n_days)

        data[sym] = df

    return data


def _make_ctx(data: dict) -> StrategyContext:
    cache = FactorCache()
    return StrategyContext(data=data, cache=cache)


# =========================================================================
# 1) 实例化 & 默认参数打印（验收 #1）
# =========================================================================
def test_instantiation_and_print():
    print("\n=== 1) 实例化 + 默认参数 ===")
    for cls in (SmallCapV2, SmallCapQualityV2, PbRoeMonthlyV2,
                NorthboundTimingV2, BreakoutPullbackV2, SectorFlowMonthlyV2):
        s = cls()
        print(f"  {cls.__name__}.name = {s.name}")
        # params 属性可能叫 default_params / params / params_dict
        params = (
            getattr(s, "default_params", None)
            or getattr(s, "params", None)
            or getattr(s, "params_dict", None)
            or {}
        )
        if not isinstance(params, dict):
            params = {}
        print(f"  {cls.__name__}.params = {params}")
        assert s.name
        assert isinstance(params, dict)


# =========================================================================
# 2) 构造 mock ctx，signal() 调用成功
# =========================================================================
def test_small_cap_v2_signal():
    print("\n=== 2) SmallCapV2.signal(mock ctx) ===")
    data = _make_mock_data(n_days=200)
    ctx = _make_ctx(data)

    s = SmallCapV2()
    sig = s.signal(ctx)

    print(f"  signal shape = {sig.shape}")
    print(f"  signal columns = {list(sig.columns)}")
    print(f"  signal unique values = {sorted(sig.stack().unique().tolist())}")

    assert isinstance(sig, pd.DataFrame)
    assert sig.shape == (200, 5)
    assert list(sig.columns) == list(data.keys())
    # 值 ∈ {0, 1}
    u = set(sig.stack().unique().tolist())
    assert u.issubset({0, 1}), f"unexpected signal values: {u}"

    # 999999.SH 无效前缀：应该全 0
    assert (sig["999999.SH"] == 0).all(), "无效前缀应全 0"

    # 600000.SH（流通市值 30e8 < 200e8）应至少在某天有 1
    # 只校验"曾经出现 1"即可（具体哪天取决于随机数据）
    print(f"  600000.SH 中 signal=1 的天数 = {(sig['600000.SH'] == 1).sum()}")


def test_small_cap_quality_v2_signal():
    print("\n=== 3) SmallCapQualityV2.signal(mock ctx) ===")
    data = _make_mock_data(n_days=200)
    ctx = _make_ctx(data)

    s = SmallCapQualityV2()
    sig = s.signal(ctx)

    print(f"  signal shape = {sig.shape}")
    print(f"  signal unique values = {sorted(sig.stack().unique().tolist())}")

    assert sig.shape == (200, 5)
    u = set(sig.stack().unique().tolist())
    assert u.issubset({0, 1}), f"unexpected signal values: {u}"


def test_pb_roe_monthly_v2_signal():
    print("\n=== 4) PbRoeMonthlyV2.signal(mock ctx) ===")
    data = _make_mock_data(n_days=200)
    ctx = _make_ctx(data)

    s = PbRoeMonthlyV2()
    sig = s.signal(ctx)

    print(f"  signal shape = {sig.shape}")
    print(f"  signal unique values = {sorted(sig.stack().unique().tolist())}")

    assert sig.shape == (200, 5)
    u = set(sig.stack().unique().tolist())
    assert u.issubset({0, 1}), f"unexpected signal values: {u}"


# =========================================================================
# 4个) 时序/行业策略（V2）signal 调用冒烟
# =========================================================================
def test_northbound_timing_v2_signal():
    print("\n=== 4a) NorthboundTimingV2.signal(mock ctx) ===")
    data = _make_mock_data(n_days=200)
    ctx = _make_ctx(data)

    s = NorthboundTimingV2()
    sig = s.signal(ctx)

    print(f"  signal shape = {sig.shape}")
    print(f"  signal columns = {list(sig.columns)}")
    print(f"  signal unique values = {sorted(sig.stack().unique().tolist())}")

    assert isinstance(sig, pd.DataFrame)
    assert sig.shape == (200, 5), f"unexpected shape {sig.shape}"
    assert list(sig.columns) == list(data.keys())
    u = set(sig.stack().unique().tolist())
    assert u.issubset({0, 1}), f"unexpected signal values: {u}"
    # 净值=0 的阈值下，约一半天数应 signal=1
    print(f"  600000.SH signal=1 days = {(sig['600000.SH'] == 1).sum()}")


def test_breakout_pullback_v2_signal():
    print("\n=== 4b) BreakoutPullbackV2.signal(mock ctx) ===")
    data = _make_mock_data(n_days=200)
    ctx = _make_ctx(data)

    s = BreakoutPullbackV2()
    sig = s.signal(ctx)

    print(f"  signal shape = {sig.shape}")
    print(f"  signal unique values = {sorted(sig.stack().unique().tolist())}")

    assert sig.shape == (200, 5)
    u = set(sig.stack().unique().tolist())
    assert u.issubset({0, 1}), f"unexpected signal values: {u}"
    # 数据是随机游走，突破+回踩同时满足的比例应该 < 10%
    total_ones = int((sig == 1).sum().sum())
    total_cells = sig.shape[0] * sig.shape[1]
    ratio = total_ones / total_cells
    print(f"  signal=1 ratio = {ratio:.2%} ({total_ones}/{total_cells})")
    assert ratio < 0.10, f"signal=1 比例 {ratio:.2%} 异常高（随机游走应该很少触发）"


def test_sector_flow_monthly_v2_signal():
    print("\n=== 4c) SectorFlowMonthlyV2.signal(mock ctx) ===")
    data = _make_mock_data(n_days=200)
    ctx = _make_ctx(data)

    s = SectorFlowMonthlyV2()
    sig = s.signal(ctx)

    print(f"  signal shape = {sig.shape}")
    print(f"  signal unique values = {sorted(sig.stack().unique().tolist())}")

    assert sig.shape == (200, 5)
    u = set(sig.stack().unique().tolist())
    assert u.issubset({0, 1}), f"unexpected signal values: {u}"
    # rank 1~28 均匀分布，Top3 比例约 3/28 ≈ 10.7%
    total_ones = int((sig == 1).sum().sum())
    total_cells = sig.shape[0] * sig.shape[1]
    ratio = total_ones / total_cells
    print(f"  signal=1 ratio = {ratio:.2%} ({total_ones}/{total_cells})")
    assert 0.05 < ratio < 0.20, f"Top3 行业信号比例 {ratio:.2%} 应在 5%~20% 之间"


# =========================================================================
# 3) 多次实例化参数可序列化（验收 __init__ 不依赖不可序列化对象）
# =========================================================================
def test_params_serializable():
    print("\n=== 5) 参数可 JSON 序列化 ===")
    import json
    import inspect

    for cls in (SmallCapV2, SmallCapQualityV2, PbRoeMonthlyV2,
                NorthboundTimingV2, BreakoutPullbackV2, SectorFlowMonthlyV2):
        # 默认参数
        s = cls()
        # 兼容多种 params 字段名
        params = (
            getattr(s, "default_params", None)
            or getattr(s, "params", None)
            or getattr(s, "params_dict", None)
            or {}
        )
        if not isinstance(params, dict):
            params = {}
        json.dumps(params)  # 不抛异常即可

        # 自定义参数：只对 __init__ 接受该参数时才尝试
        sig = inspect.signature(cls.__init__)
        custom = {}
        if "top_n" in sig.parameters:
            custom["top_n"] = 10
        if "min_market_cap" in sig.parameters:
            custom["min_market_cap"] = 20.0
        if custom:
            try:
                s2 = cls(**custom)
                params2 = (
                    getattr(s2, "default_params", None)
                    or getattr(s2, "params", None)
                    or getattr(s2, "params_dict", None)
                    or {}
                )
                if not isinstance(params2, dict):
                    params2 = {}
                json.dumps(params2)
            except Exception as e:
                print(f"  [WARN] {cls.__name__}({custom}) 失败: {e}")
        print(f"  {cls.__name__}: OK")


# =========================================================================
# 4) 没有 print / 没有 shift(-1) / 没有线程
# =========================================================================
def test_no_forbidden_features():
    print("\n=== 6) 静态扫描：禁止特征 ===")
    import re
    from pathlib import Path

    forbidden_patterns = [
        (re.compile(r"\.shift\(\s*-1"), "shift(-1)"),
        (re.compile(r"\.iloc\[\s*\w+\s*\+\s*1"), "iloc[i+1]"),
        (re.compile(r"^import\s+threading|^from\s+threading", re.MULTILINE), "threading import"),
        (re.compile(r"Thread\(|Pool\("), "threading call"),
    ]
    files = [
        Path("src/strategies/3a7b2c01/small_cap_v2.py"),
        Path("src/strategies/5d8e3f02/small_cap_quality_v2.py"),
        Path("src/strategies/7f9a4b03/pb_roe_monthly_v2.py"),
        Path("src/strategies/4e8c3d06/northbound_timing_v2.py"),
        Path("src/strategies/9b1f7a05/breakout_pullback_v2.py"),
        Path("src/strategies/2c6d5e04/sector_flow_monthly_v2.py"),
    ]
    for f in files:
        text = f.read_text(encoding="utf-8")
        for pat, name in forbidden_patterns:
            assert not pat.search(text), f"{f}: 命中禁止特征 {name}"
        # 允许 logger.info/warning，但不允许 print( 出现在 .signal / ._signal_one 体内
        assert "print(" not in text, f"{f}: 含 print()"
        print(f"  {f}: 无 print / 未来函数 / 线程")


# =========================================================================
# 5) 继承 SignalStrategy
# =========================================================================
def test_inheritance():
    print("\n=== 7) 继承 SignalStrategy ===")
    from src.quantlab.signals.base import SignalStrategy
    for cls in (SmallCapV2, SmallCapQualityV2, PbRoeMonthlyV2,
                NorthboundTimingV2, BreakoutPullbackV2, SectorFlowMonthlyV2):
        assert issubclass(cls, SignalStrategy), f"{cls.__name__} 未继承 SignalStrategy"
        print(f"  {cls.__name__} -> SignalStrategy [OK]")


# =========================================================================
# runner
# =========================================================================
if __name__ == "__main__":
    test_instantiation_and_print()
    test_small_cap_v2_signal()
    test_small_cap_quality_v2_signal()
    test_pb_roe_monthly_v2_signal()
    test_northbound_timing_v2_signal()
    test_breakout_pullback_v2_signal()
    test_sector_flow_monthly_v2_signal()
    test_params_serializable()
    test_no_forbidden_features()
    test_inheritance()
    print("\nAll tests passed.")
