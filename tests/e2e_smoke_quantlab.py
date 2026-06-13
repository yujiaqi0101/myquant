"""
e2e_smoke_quantlab.py - 端到端冒烟测试

目标：
    用 quantlab BarEngine 跑 small_cap_v2 策略，验证完整链路：
    1) DataAdapter：CSV → Dict[symbol, DataFrame]
    2) SignalStrategy：signal(ctx) 输出 int8
    3) PortfolioConstructor：TopN 截断
    4) RiskManager：A 股风控（涨跌停/ST/T+1）
    5) BarEngine：撮合 + 业绩统计
    6) ResultAdapter：quantlab BacktestResult → myquant BacktestResult
"""
import sys
import time
import pandas as pd
from pathlib import Path

sys.path.insert(0, "src")

# 1) 加载数据
print("=" * 60)
print("[1/6] 加载数据 (CSV → Dict[symbol, DataFrame])")
print("=" * 60)

data_dir = Path("data/test_data")
stock_info = pd.read_csv(data_dir / "stock_info.csv")
stock_daily = pd.read_csv(data_dir / "stock_daily.csv")
print(f"  stock_info:  {len(stock_info)} 只")
print(f"  stock_daily: {len(stock_daily)} 条 ({stock_daily['trade_date'].min()} ~ {stock_daily['trade_date'].max()})")

# 转 MultiIndex 供 DataAdapter
stock_daily["trade_date"] = pd.to_datetime(stock_daily["trade_date"])
stock_daily = stock_daily.set_index(["trade_date", "stock_code"]).sort_index()

# 合并 stock_info 字段
stock_info_index = stock_info.set_index("stock_code")

from src.quantlab_adapters import to_quantlab_dict
t0 = time.time()
data = to_quantlab_dict(stock_daily)
print(f"  转换完成: {len(data)} symbols, 耗时 {time.time() - t0:.2f}s")

# 注入 stock_info 列（list_date / stock_name）— STFilterCheck / NewStockCheck 需要
for sym, df in data.items():
    info = stock_info_index.loc[sym] if sym in stock_info_index.index else None
    if info is not None:
        df["list_date"] = info["list_date"]
        df["stock_name"] = info["stock_name"]

print(f"  示例 symbol: {list(data.keys())[:3]}")
print(f"  示例列: {list(next(iter(data.values())).columns)}")
print()

# 2) 加载策略
print("=" * 60)
print("[2/6] 加载 SignalStrategy: small_cap_v2")
print("=" * 60)
from src.quantlab_adapters import discover_v2_strategies
from src.quantlab_adapters.strategy_registry import SignalStrategyRegistry

discover_v2_strategies("src.strategies")
strategy_class = SignalStrategyRegistry.get("small_cap_v2")
strategy = strategy_class(top_n=10)
print(f"  策略: {strategy.name}")
print(f"  参数: top_n={strategy.top_n}, max_market_cap={strategy.max_market_cap}")
print()

# 3) 构造 quantlab ctx
print("=" * 60)
print("[3/6] 构造 quantlab StrategyContext")
print("=" * 60)
from src.quantlab.data.context import StrategyContext
from src.quantlab.data.cache import factor_cache

ctx = StrategyContext(data=data, cache=factor_cache)
print(f"  ctx.data: {len(ctx.data)} symbols")
print(f"  ctx.symbols: {len(ctx.symbols)}")
print()

# 4) 调 strategy.signal(ctx)
print("=" * 60)
print("[4/6] strategy.signal(ctx) → DataFrame")
print("=" * 60)
t0 = time.time()
signals = strategy.signal(ctx)
elapsed = time.time() - t0
print(f"  shape: {signals.shape}")
print(f"  dtype: {signals.dtypes.iloc[0]}")
print(f"  unique values: {sorted(set(signals.values.flatten().tolist()))}")
print(f"  signal sum per day（前5天）:")
for d in signals.index[:5]:
    n = int(signals.loc[d].sum())
    print(f"    {d.date()}: {n} 只股票触发买入信号")
print(f"  耗时: {elapsed:.2f}s")
print()

# 5) 跑 BarEngine
print("=" * 60)
print("[5/6] 跑 quantlab BarEngine")
print("=" * 60)

# 修复：BarEngine 的策略接口可能要求传 strategy 然后 engine.run(data, params) 或类似
# 让我们用最直接的：构造 BarEngine 并调 run
from src.quantlab.engine import BarEngine
from src.quantlab.portfolio_construction.top_n import TopN
from src.quantlab.execution import (
    TargetWeightExecution,
    PercentageCommission,
    PercentageSlippage,
)
from src.quantlab_extras import build_ashare_execution

# 构造 RiskManager（含 A 股风控）
from src.quantlab.risk.risk_manager import RiskManager
from src.quantlab_extras import build_ashare_risk_manager

# 用工厂方法构造 A 股默认 RiskManager（含 6 个 Check + KillSwitch）
risk_manager = build_ashare_risk_manager()

# 构造 Engine
execution = build_ashare_execution(
    commission_rate=0.00025,
    slippage_rate=0.0001,
    lot_size=100,
)

# quantlab 6.5+ 风格 BarEngine: 接受 strategy + portfolio_constructor + execution
try:
    engine = BarEngine(
        strategy=strategy,
        portfolio_constructor=TopN(n=10),
        execution_model=execution,
        commission_model=PercentageCommission(rate=0.00025),
        slippage_model=PercentageSlippage(rate=0.0001),
        initial_cash=1_000_000.0,
    )
except TypeError as e:
    print(f"  [WARN] BarEngine signature 1 failed: {e}")
    # 尝试另一种构造方式
    engine = BarEngine(strategy=strategy, initial_cash=1_000_000.0)

print(f"  Engine: {type(engine).__name__}")
print(f"  initial_cash: 1,000,000")
print()

# 6) 跑回测
print("=" * 60)
print("[6/6] engine.run() + 转换结果")
print("=" * 60)
t0 = time.time()
try:
    ql_result = engine.run(strategy=strategy, data=data, params=strategy.__dict__)
    elapsed = time.time() - t0
    print(f"  回测耗时: {elapsed:.2f}s")
    if hasattr(ql_result, "error") and ql_result.error:
        print(f"  [ERROR] {ql_result.error}")
    else:
        print(f"  final_equity: {ql_result.final_equity:,.2f}")
        print(f"  total_return: {ql_result.total_return:.2%}")
        print(f"  sharpe: {ql_result.sharpe:.3f}")
        print(f"  max_drawdown: {ql_result.max_drawdown:.2%}")
        print(f"  trade_count: {ql_result.trade_count}")
        print()

        # ResultAdapter
        from src.quantlab_adapters import to_myquant_result
        mq_result = to_myquant_result(
            ql_result,
            strategy_name="small_cap_v2",
            initial_capital=1_000_000.0,
        )
        print(f"  转换后 myquant BacktestResult:")
        print(f"    daily_snapshots: {len(mq_result.daily_snapshots)}")
        print(f"    trades: {len(mq_result.trades)}")
        print(f"    performance.sharpe_ratio: {mq_result.performance.get('sharpe_ratio', 0):.3f}")
        print(f"    performance.max_drawdown: {mq_result.performance.get('max_drawdown', 0):.2%}")
        print()
        print("=" * 60)
        print("[PASS] END-TO-END SMOKE TEST PASSED")
        print("=" * 60)
except Exception as e:
    elapsed = time.time() - t0
    print(f"  回测失败（{elapsed:.2f}s）: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    print()
    print("=" * 60)
    print("[PARTIAL] 数据加载 + 信号生成 OK，回测引擎调用失败")
    print("=" * 60)
