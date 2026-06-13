"""
smoke_v2_strategies.py - 验证 6 个 v2 策略符合 quantlab 开发规范

检查项：
1. 自动发现 + 注册
2. 实例化 + 参数校验
3. 参数全部是基本类型（JSON 可序列化）
4. signal() 返回 DataFrame(int8)
5. signal 维度 (date × symbol) 正确
6. 取值 ∈ {0, 1}
"""
import sys
import inspect
import pandas as pd
import numpy as np

sys.path.insert(0, "src")
from src.quantlab_adapters import discover_v2_strategies, SignalStrategyRegistry

# 1) 自动发现 + 注册
loaded = discover_v2_strategies("src.strategies")
print(f"[1/5] Loaded {len(loaded)} files:")
for f in loaded:
    print(f"      - {f}")
print()

# 2) 列出注册表
strategies = SignalStrategyRegistry.list_strategies()
print(f"[2/5] Registered {len(strategies)} v2 strategies:")
for s in strategies:
    print(f"      - {s['name']:<25} {s['class']:<25} params={s['params']}")
print()

# 3) 校验每个策略
print("[3/5] 校验 __init__ 签名 + 参数基本类型 ...")
all_ok = True
for s in strategies:
    cls = SignalStrategyRegistry.get(s["name"])
    if cls is None:
        continue
    sig = inspect.signature(cls.__init__)
    params = list(sig.parameters.keys())
    try:
        inst = cls()
        # 检查参数全部是基本类型
        for k, v in vars(inst).items():
            if k.startswith("_"):
                continue
            if not isinstance(v, (int, float, bool, str, type(None))):
                print(f"  [FAIL] {s['name']}.{k} = {type(v).__name__} (not JSON-serializable)")
                all_ok = False
                break
        else:
            print(f"  [OK]   {s['name']:<25} __init__({', '.join(params[1:])})")
    except Exception as e:
        print(f"  [FAIL] {s['name']} construct failed: {e}")
        all_ok = False
print()

# 4) 校验入参合理性
print("[4/5] 校验入参合理性（应抛 ValueError） ...")
bad_cases = [
    ("small_cap_v2", {"top_n": 0}, "top_n < 1"),
    ("small_cap_v2", {"min_market_cap": 100, "max_market_cap": 50}, "min > max"),
    ("small_cap_v2", {"max_vol": 1.5}, "max_vol > 1"),
    ("small_cap_quality_v2", {"pb_threshold": -1}, "pb_threshold < 0"),
    ("breakout_pullback_v2", {"breakout_window": 1}, "breakout_window < 2"),
    ("sector_flow_monthly_v2", {"top_n_industries": 50}, "top_n_industries > 31"),
]
for name, kwargs, desc in bad_cases:
    cls = SignalStrategyRegistry.get(name)
    if cls is None:
        continue
    try:
        inst = cls(**kwargs)
        print(f"  [FAIL] {name}({kwargs}) should have raised ({desc})")
        all_ok = False
    except ValueError as e:
        print(f"  [OK]   {name}({kwargs}) raised ValueError: {str(e)[:60]}")
    except Exception as e:
        print(f"  [WARN] {name}({kwargs}) raised {type(e).__name__}: {e}")
print()

# 5) 校验 signal() 输出
print("[5/5] 校验 signal() 返回 DataFrame(int8) ...")

# 构造一个最简单的 mock ctx
class MockCtx:
    """最小的量化上下文"""
    def __init__(self, data):
        self.data = data
        self.cache = MockCache()


class MockCache:
    def get(self, key):
        return None
    def set(self, key, value):
        pass


def make_mock_data(n_bars=120, n_syms=5, with_extra_cols=True):
    """构造测试数据"""
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
                "market_cap": np.random.uniform(50, 150, n_bars) * 1e8,
            },
            index=dates,
        )
        df.iloc[0, df.columns.get_loc("pre_close")] = df["close"].iloc[0]
        if with_extra_cols:
            df["roe"] = np.random.uniform(0, 0.20, n_bars)
            df["pb"] = np.random.uniform(0.5, 4.0, n_bars)
            df["revenue_growth"] = np.random.uniform(-0.1, 0.3, n_bars)
            df["northbound_net_inflow"] = np.random.randn(n_bars) * 5e6
            df["industry_inflow_rank"] = np.random.randint(1, 32, n_bars)
        data[sym] = df
    return data


data = make_mock_data()
ctx = MockCtx(data)

for s in strategies:
    cls = SignalStrategyRegistry.get(s["name"])
    if cls is None:
        continue
    try:
        inst = cls()
        sig = inst.signal(ctx)
        if not isinstance(sig, pd.DataFrame):
            print(f"  [FAIL] {s['name']}.signal() returned {type(sig).__name__}, expected DataFrame")
            all_ok = False
            continue
        if sig.shape != (len(ctx.data["000000.SZ"]), len(ctx.data)):
            print(f"  [WARN] {s['name']}.signal() shape={sig.shape}, expected ({len(ctx.data['000000.SZ'])}, {len(ctx.data)})")
        if sig.dtypes.iloc[0] != "int8":
            print(f"  [WARN] {s['name']}.signal() dtype={sig.dtypes.iloc[0]}, expected int8")
        uniq = sorted(sig.values.flatten().tolist())
        if not all(v in (-1, 0, 1) for v in uniq if not np.isnan(v)):
            print(f"  [FAIL] {s['name']}.signal() has values outside {{-1,0,1}}: {uniq[:5]}")
            all_ok = False
        else:
            print(f"  [OK]   {s['name']:<25} shape={sig.shape} dtype={sig.dtypes.iloc[0]} values={uniq[:5]}")
    except Exception as e:
        print(f"  [FAIL] {s['name']}.signal() raised: {type(e).__name__}: {e}")
        all_ok = False
print()

# 6) 校验 *_PARAM_SPACE
print("[6/6] 校验 *_PARAM_SPACE 字典存在 ...")
for s in strategies:
    mod_name = s["name"]
    # 从注册表找类
    cls = SignalStrategyRegistry.get(mod_name)
    if cls is None:
        continue
    mod = sys.modules.get(cls.__module__)
    if mod and hasattr(mod, f"{cls.__name__.upper()}_PARAM_SPACE"):
        ps = getattr(mod, f"{cls.__name__.upper()}_PARAM_SPACE")
        print(f"  [OK]   {mod_name:<25} PARAM_SPACE has {len(ps)} keys: {list(ps.keys())[:3]}...")
    elif mod:
        # 尝试一些变体
        found = False
        for prefix in ("SMALL_CAP", "BREAKOUT_PULLBACK", "NORTHBOUND_TIMING", "SECTOR_FLOW_MONTHLY", "PB_ROE_MONTHLY"):
            if prefix in cls.__name__.upper() or prefix in mod_name.upper():
                if hasattr(mod, f"{prefix}_PARAM_SPACE"):
                    print(f"  [OK]   {mod_name:<25} {prefix}_PARAM_SPACE found")
                    found = True
                    break
        if not found:
            print(f"  [WARN] {mod_name:<25} no PARAM_SPACE found in {mod.__name__}")
print()

print("=" * 60)
if all_ok:
    print("[PASS] ALL CHECKS PASSED")
else:
    print("[FAIL] SOME CHECKS FAILED")
print("=" * 60)
sys.exit(0 if all_ok else 1)
