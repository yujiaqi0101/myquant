"""
QuantLab 12 Stage 集成验证 Demo
===============================
复制自 quantlab/main.py 并改名为 _main_demo.py 以避免与 myquant/main.py 冲突。

为了让 `from quantlab.X` 与 `from src.quantlab.X` 两种导入方式都能工作：
1. 将 myquant/src 加入 sys.path，使 `import quantlab` 等价于 `import src.quantlab`
2. cwd 默认就是 myquant 根目录，`from src.quantlab.X` 自然可用
"""

import os
import sys

# 让 `from quantlab.X` 和 `from src.quantlab.X` 都能解析
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_THIS_DIR)  # myquant/src
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)  # myquant

# 关键：Python 运行脚本时会把脚本所在目录加到 sys.path[0]，
# 而 quantlab/ 目录下有 signal.py / strategy.py / portfolio.py 等顶层模块，
# 会与 stdlib 的 signal 等模块冲突。
# 这里先清掉脚本目录，再加上我们真正需要的路径。
if _THIS_DIR in sys.path:
    sys.path.remove(_THIS_DIR)
sys.path = [p for p in sys.path if p not in ("", _THIS_DIR)]

# src/ 在前 → `quantlab` 解析为 src/quantlab
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
# 项目根 → `src.quantlab.X` 可解析
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 把工作目录切到 demo 期望的位置（quantlab 项目结构）
# 但这里我们保留 myquant cwd，仅切换数据目录前缀
os.environ.setdefault("QUANTLAB_DEMO_CWD", _PROJECT_ROOT)

import numpy as np
import pandas as pd

from quantlab.strategy import (
    MACrossStrategy
)

from quantlab.execution import (
    PercentageCommission,
    PercentageSlippage,
    TargetWeightExecution
)

from quantlab.portfolio_construction import (
    TopN
)

from quantlab.engine import (
    BarEngine
)

from quantlab.event_engine import (
    EventEngine
)

from quantlab.research import (
    Experiment,
    Report,
    WalkForward,
    ValidationRunner
)


# --------------------------------
# 1. 多标的数据
# --------------------------------

# 数据源：使用绝对路径读取 quantlab 项目的 demo 数据，
# 不依赖 cwd，myquant 根目录运行也 OK
_DATA_DIR = os.path.join(
    os.environ.get("QUANTLAB_DEMO_CWD", _PROJECT_ROOT),
    "..", "quantlab", "data"
)
_DATA_DIR = os.path.abspath(_DATA_DIR)

if __name__ == '__main__':
    symbols = ["AAPL", "MSFT", "NVDA"]

    data = {}
    for sym in symbols:

        data[sym] = pd.read_csv(
            os.path.join(_DATA_DIR, f"{sym}.csv"),
            parse_dates=True,
            index_col=0
        )


    # --------------------------------
    # 2. 公共 Engine Builder
    # --------------------------------

    def build_engine():

        return BarEngine(
            strategy=MACrossStrategy(
                fast=20,
                slow=60
            ),
            portfolio_constructor=TopN(n=2),
            execution_model=(
                TargetWeightExecution(
                    lot_size=1,
                    position_tolerance=0.02
                )
            ),
            commission_model=(
                PercentageCommission(
                    rate=0.0003
                )
            ),
            slippage_model=(
                PercentageSlippage(
                    rate=0.0002
                )
            ),
            initial_cash=100000
        )


    # --------------------------------
    # 3. 一次实验：Experiment
    # --------------------------------

    print()
    print("=" * 50)
    print("  [1] Experiment：单次实验")
    print("=" * 50)

    exp = Experiment(
        name="ma_cross_v1"
    )

    result = exp.run(
        strategy=MACrossStrategy(
            fast=20,
            slow=60
        ),
        engine=build_engine(),
        data=data,
        params={"fast": 20, "slow": 60}
    )

    print(Report(result).generate())


    # --------------------------------
    # 4. Report
    # --------------------------------

    print()
    print("=" * 50)
    print("  [2] Report：报告生成")
    print("=" * 50)

    print("  to_dict():")
    print(
        "    "
        + str(result.to_dict())[:200]
        + " ..."
    )

    print()
    print("  to_html() length:",
          len(
              Report(result).to_html()
          ),
          "chars")


    # --------------------------------
    # 5. Walk Forward
    # --------------------------------

    print()
    print("=" * 50)
    print("  [3] WalkForward：滚动训练/测试")
    print("=" * 50)

    wf = WalkForward(
        train_bars=200,
        test_bars=80,
        step_bars=80
    )
    wf.set_engine_template(build_engine())

    wf_result = wf.run(

        strategy_cls=MACrossStrategy,

        param_space={
            "fast": [10, 20, 30],
            "slow": [40, 60, 80]
        },

        data=data
    )

    print(
        f"  Windows       : {len(wf_result.windows)}"
    )
    print(
        f"  Avg Test Sharpe: "
        f"{wf_result.avg_test_sharpe:.3f}"
    )
    print(
        f"  Avg Test Return: "
        f"{wf_result.avg_test_return:.2f}%"
    )
    print()
    print("  Best Params by Window:")
    for i, w in enumerate(wf_result.windows):

        print(
            f"    Window {i + 1}: "
            f"train {str(w.train_start)[:10]} "
            f"-> {str(w.train_end)[:10]} | "
            f"test {str(w.test_start)[:10]} "
            f"-> {str(w.test_end)[:10]} | "
            f"params={w.best_params} "
            f"score={w.train_score:.3f}"
        )


    # --------------------------------
    # 6. Validation（双引擎对比）
    # --------------------------------

    print()
    print("=" * 50)
    print("  [4] ValidationRunner：双引擎对比")
    print("=" * 50)

    try:

        from quantlab.adapters import (
            VectorBTAdapter
        )

        fast_engine = VectorBTAdapter()
        precise_engine = build_engine()

        runner = ValidationRunner(
            fast_engine=fast_engine,
            precise_engine=precise_engine,
            consistency_threshold=0.8
        )

        vr = runner.validate(
            strategy_cls=MACrossStrategy,
            params={"fast": 20, "slow": 60},
            data=data,
        )

        print(
            f"  fast_sharpe={vr.fast_sharpe:.3f}\n"
            f"  precise_sharpe={vr.precise_sharpe:.3f}\n"
            f"  return_diff={vr.return_diff:.2f}\n"
            f"  sharpe_diff={vr.sharpe_diff:.3f}\n"
            f"  trade_diff={vr.trade_diff}\n"
            f"  consistency={vr.consistency_score:.4f}\n"
            f"  passed={vr.passed}"
        )

    except Exception as e:

        print(
            f"  [Validation] 跳过（VectorBT 不可用）: {e}"
        )


    # --------------------------------
    # 7. EventEngine 对比：验证 EventBus 流水线结果等价
    # --------------------------------

    print()
    print("=" * 50)
    print("  [5] EventEngine：事件驱动版")
    print("=" * 50)


    def build_event_engine():

        return EventEngine(
            strategy=MACrossStrategy(
                fast=20,
                slow=60
            ),
            portfolio_constructor=TopN(n=2),
            execution_model=(
                TargetWeightExecution(
                    lot_size=1,
                    position_tolerance=0.02
                )
            ),
            commission_model=(
                PercentageCommission(
                    rate=0.0003
                )
            ),
            slippage_model=(
                PercentageSlippage(
                    rate=0.0002
                )
            ),
            initial_cash=100000
        )


    ev_result = exp.run(
        strategy=MACrossStrategy(
            fast=20,
            slow=60
        ),
        engine=build_event_engine(),
        data=data,
        params={"fast": 20, "slow": 60}
    )

    print(Report(ev_result).generate())

    # 跟 BarEngine 跑同一个，对比
    bar_result = exp.run(
        strategy=MACrossStrategy(
            fast=20,
            slow=60
        ),
        engine=build_engine(),
        data=data,
        params={"fast": 20, "slow": 60}
    )

    print()
    print("  -- 等价性校验（BarEngine vs EventEngine）--")

    m_bar = result.metrics
    m_ev = ev_result.metrics

    for k in [
        "final_equity",
        "total_return",
        "sharpe",
        "max_drawdown",
    ]:

        a = m_bar[k]
        b = m_ev[k]
        diff = (
            abs(a - b) / abs(a)
            if a not in (0, None)
            else 0
        )

        print(
            f"  {k:18s}: "
            f"Bar={a:>12.4f}  "
            f"Event={b:>12.4f}  "
            f"diff={diff:.2%}"
        )


    # --------------------------------
    # 8. FastOptimizer + ValidationRunner.validate_top_n
    # --------------------------------

    print()
    print("=" * 50)
    print("  [6] Fast→Precise 双引擎优化（TopN 验证）")
    print("=" * 50)

    try:

        from quantlab.adapters import (
            VectorBTAdapter
        )

        from quantlab.optimizer import (
            Optimizer
        )

        # 1) Fast stage
        #    VectorBT 跑全网格（16 组）
        fast_engine = VectorBTAdapter()

        fast_opt = Optimizer(
            strategy_cls=MACrossStrategy,
            engine=fast_engine,
        )
        fast_df = fast_opt.run(
            data=data,
            param_space={
                "fast": [5, 10, 20, 30],
                "slow": [30, 60, 90, 120]
            }
        )

        print(
            f"  Fast stage: "
            f"{len(fast_df)} 组参数"
        )
        if not fast_df.empty:

            best = fast_df.iloc[0]
            print(
                f"    best fast: "
                f"score={best['score']:.3f} "
                f"sharpe={best.get('sharpe', 0):.3f}"
            )

        # 2) Precise stage
        #    ValidationRunner 验证 top 10
        precise_engine = build_event_engine()

        runner = ValidationRunner(
            fast_engine=fast_engine,
            precise_engine=precise_engine,
            consistency_threshold=0.8,
        )

        print()
        print("  Precise stage: TopN 验证")

        val_df = runner.validate_top_n(
            optimizer_result=fast_df,
            strategy_cls=MACrossStrategy,
            data=data,
            top_n=10,
            param_keys=["fast", "slow"],
            output_csv="reports/validation_report.csv",
        )

        print(runner.summary(val_df))

        # 3) 落盘 + 统计
        n_pass = (
            (val_df["passed"] == "OK").sum()
            if not val_df.empty else 0
        )
        n_elim = (
            (val_df["passed"] == "ELIMINATED").sum()
            if not val_df.empty else 0
        )
        print(
            f"  通过: {n_pass}  淘汰: {n_elim}\n"
            f"  报告: reports/validation_report.csv"
        )

    except Exception as e:

        import traceback
        traceback.print_exc()
        print(
            f"  [Fast→Precise] 跳过: {e}"
        )


    # --------------------------------
    # 9. V1.9 Multi Asset / Portfolio Construction
    # --------------------------------

    print()
    print("=" * 50)
    print("  [7] V1.9 Multi-Asset 接口验证")
    print("=" * 50)

    # a) ctx.symbols
    from quantlab.data.context import (
        StrategyContext
    )
    from quantlab.data.cache import factor_cache

    ctx = StrategyContext(
        data=data,
        cache=factor_cache
    )
    print(f"  ctx.symbols: {ctx.symbols}")

    # b) Portfolio.get_position()
    print(
        f"  Portfolio.get_position() 已支持"
    )

    # c) TradeBook.pnl_by_symbol()
    #    拿刚才 [1] 跑出的 TradeBook
    exp_v19 = Experiment(
        name="v19_check"
    )
    res_v19 = exp_v19.run(
        strategy=MACrossStrategy(
            fast=20,
            slow=60
        ),
        engine=build_engine(),
        data=data,
    )
    tb = res_v19.tradebook
    if tb is not None:

        pnl_by_sym = tb.pnl_by_symbol()
        count_by_sym = tb.trade_count_by_symbol()

        print(
            f"  pnl_by_symbol:\n"
            f"    {pnl_by_sym}"
        )
        print(
            f"  trade_count_by_symbol:\n"
            f"    {count_by_sym}"
        )
        print(
            f"  closed_trades_by_symbol keys: "
            f"{list(tb.closed_trades_by_symbol.keys())}"
        )

    # d) PortfolioSnapshot（已 import 可用）
    from quantlab.core import PortfolioSnapshot
    snap = PortfolioSnapshot(
        timestamp="2024-01-01",
        equity=100000.0,
        cash=50000.0,
        weights={"AAPL": 0.3, "MSFT": 0.2},
    )
    print(
        f"  PortfolioSnapshot: invested_weight="
        f"{snap.invested_weight:.2%}"
    )


    # --------------------------------
    # 10. V2.0 VectorBTAdapter 正式版（from_orders + constructor）
    # --------------------------------

    print()
    print("=" * 50)
    print("  [8] V2.0 VectorBTAdapter：组合权重策略")
    print("=" * 50)

    try:

        from quantlab.adapters import (
            VectorBTAdapter
        )
        from quantlab.portfolio_construction import (
            TopN,
        )

        # constructor 通过实例注入
        # 不再硬编码"signal → 1/0 仓位"
        # 而是 signal → scores → weights_df → from_orders
        fast_engine = VectorBTAdapter(
            constructor=TopN(n=2),
            fees=0.0003,
            slippage=0.0002,
            init_cash=100000,
        )

        result = fast_engine.run(
            strategy=MACrossStrategy(
                fast=20,
                slow=60
            ),
            data=data,
        )

        print(
            f"  source:     {result.source}\n"
            f"  sharpe:     {result.sharpe}\n"
            f"  total_ret:  {result.total_return}%\n"
            f"  max_dd:     {result.max_drawdown}%\n"
            f"  trades:     {result.trade_count}\n"
            f"  final_eq:   {result.final_equity}\n"
            f"  weights_df shape: "
            f"{result.weights_df.shape if result.weights_df is not None else 'None'}"
        )

    except Exception as e:

        import traceback
        traceback.print_exc()
        print(
            f"  [V2.0] 跳过: {e}"
        )


    # --------------------------------
    # 11. V2.1 ParallelOptimizer（多进程）
    # --------------------------------

    print()
    print("=" * 50)
    print("  [9] V2.1 ParallelOptimizer：多进程网格搜索")
    print("=" * 50)

    try:

        from quantlab.parallel_optimizer import (
            ParallelOptimizer,
        )

        # V2.1.1 三档优化：
        #   - initializer 全局 data
        #   - early_filter 早死
        #   - top_k 内存上限
        #
        # engine_spec 是 (type, kwargs) 元组
        # 避免 pickling 闭包
        popt = ParallelOptimizer(
            strategy_cls=MACrossStrategy,
            engine_spec=(
                "vectorbt",
                {
                    "fees": 0.0003,
                    "slippage": 0.0002,
                },
            ),
            max_workers=4,
            top_k=10,
            early_split=0.3,
        )

        import time

        t0 = time.time()
        par_df = popt.run(
            data=data,
            param_space={
                "fast": [5, 10, 20],
                "slow": [60, 80, 100],
            }
        )
        elapsed = time.time() - t0

        # 统计
        n_total = len(par_df)
        n_early_kill = (
            int(par_df["early_kill"].sum())
            if (
                "early_kill" in par_df.columns
                and n_total > 0
            )
            else 0
        )
        n_full = max(n_total - n_early_kill, 0)

        if n_total > 0:

            early_pct = (
                f"{n_early_kill/n_total*100:.0f}%"
            )

        else:

            early_pct = "N/A"

        print(
            f"  Tested:  {n_total} 组\n"
            f"  Workers: {popt.max_workers}\n"
            f"  Early:   {n_early_kill} 早死 ({early_pct})\n"
            f"  Full:    {n_full} 跑全\n"
            f"  Time:    {elapsed:.2f}s\n"
            f"  Top {min(5, n_total)}:\n"
        )

        if not par_df.empty:

            # 排除指标列
            show_cols = [
                c for c
                in par_df.columns
                if c not in (
                    "source",
                    "total_return",
                    "sharpe",
                    "max_drawdown",
                )
            ]
            print(
                par_df[show_cols]
                .head(10)
                .to_string(index=False)
            )

        # 写 CSV
        reports_dir = "reports"
        os.makedirs(
            reports_dir, exist_ok=True
        )
        par_csv = os.path.join(
            reports_dir,
            "parallel_grid.csv"
        )
        par_df.to_csv(
            par_csv, index=False
        )
        print(
            f"\n  报告: {par_csv}"
        )

    except Exception as e:

        import traceback
        traceback.print_exc()
        print(
            f"  [V2.1] 跳过: {e}"
        )
        # raise  # for debug


    # --------------------------------
    # 11.5 V2.2 WalkForwardEngine 正式版
    # --------------------------------

    print()
    print("=" * 50)
    print("  [10] V2.2 WalkForwardEngine 正式版")
    print("=" * 50)

    try:

        import numpy as np
        import pandas as pd

        # V2.2 里 VBT 走多进程在沙箱内 SIGABRT
        # 切 ThreadPool（numba 内部释放 GIL）
        os.environ["PARALLEL_USE_THREAD"] = "1"

        from quantlab.research.walk_forward import (
            WalkForwardRunner,
            WalkForwardReport,
        )

        # V2.2 需要按年切分
        # 现有 data 是 300 bars（2024-01~2024-10）
        # 不够
        # 这里合成 5 年（1825 bars）多标的数据
        # 与原 data 隔离

        n_years = 5
        bars_per_year = 252
        n_bars = n_years * bars_per_year

        wf_symbols = ["AAPL", "MSFT", "NVDA"]
        wf_data = {}

        rng = np.random.default_rng(seed=42)

        base_dates = pd.date_range(
            start="2020-01-01",
            periods=n_bars,
            freq="B",
        )

        for sym in wf_symbols:

            drift = rng.normal(
                0.0003, 0.015, size=n_bars
            )
            close = 100 * np.exp(
                np.cumsum(drift)
            )
            wf_data[sym] = pd.DataFrame({
                "close": close,
                "open": close
                * (1 + rng.normal(
                    0, 0.003, size=n_bars
                )),
                "high": close
                * (1 + np.abs(rng.normal(
                    0, 0.005, size=n_bars
                ))),
                "low": close
                * (1 - np.abs(rng.normal(
                    0, 0.005, size=n_bars
                ))),
                "volume": rng.integers(
                    1_000_000,
                    5_000_000,
                    size=n_bars,
                ),
            }, index=base_dates)

        print(
            f"  data: {len(wf_symbols)} symbols, "
            f"{n_bars} bars "
            f"({base_dates[0].date()} ~ "
            f"{base_dates[-1].date()})"
        )

        # 构造 V2.1 ParallelOptimizer
        # 复用 stage 9 的设置
        from quantlab.parallel_optimizer import (
            ParallelOptimizer,
        )

        wf_popt = ParallelOptimizer(
            strategy_cls=MACrossStrategy,
            engine_spec=(
                "vectorbt",
                {
                    "fees": 0.0003,
                    "slippage": 0.0002,
                },
            ),
            max_workers=4,
            top_k=5,
            early_split=0.3,
        )

        # 构造 ValidationRunner
        # V2.2 需要 fast + precise 两个引擎
        # fast = VectorBT 适配器（V2.0）
        # precise = EventEngine
        from quantlab.adapters.vectorbt_adapter import (
            VectorBTAdapter,
        )
        from quantlab.portfolio_construction import (
            EqualWeight,
        )

        fast_engine = VectorBTAdapter(
            constructor=EqualWeight(),
        )

        # EventEngine 复用 stage 1 的 build_engine
        precise_engine = build_engine()

        wf_val = ValidationRunner(
            fast_engine=fast_engine,
            precise_engine=precise_engine,
            consistency_threshold=0.8,
        )

        # 构造 WalkForwardRunner
        # train=2年 test=1年
        # 5年数据 → 3 个窗口
        wf_runner = WalkForwardRunner(
            optimizer=wf_popt,
            validation_runner=wf_val,
            event_engine=precise_engine,
            train_years=2,
            test_years=1,
            top_train=3,
            top_val=1,
        )

        import time

        t0 = time.time()
        wf_v2 = wf_runner.run(
            data=wf_data,
            param_space={
                "fast": [10, 20],
                "slow": [60, 80],
            },
        )
        wf_elapsed = time.time() - t0

        print()
        print(
            f"  Windows    : {len(wf_v2.windows)}"
        )
        print(
            f"  Train      : "
            f"{wf_runner.train_years} years"
        )
        print(
            f"  Test       : "
            f"{wf_runner.test_years} year"
        )
        print(
            f"  Avg Sharpe : "
            f"{wf_v2.avg_test_sharpe:.3f}"
        )
        print(
            f"  Avg Return : "
            f"{wf_v2.avg_test_return:.2f}%"
        )
        print(
            f"  Avg MaxDD  : "
            f"{wf_v2.avg_test_max_dd:.2f}%"
        )
        print(
            f"  Stitched   : "
            f"{len(wf_v2.stitched_equity_curve)} bars"
        )

        sm = wf_v2.stitched_metrics
        print(
            f"  Stitched Sharpe  : "
            f"{sm.get('sharpe', 0)}"
        )
        print(
            f"  Stitched Return  : "
            f"{sm.get('total_return', 0)}%"
        )
        print(
            f"  Stitched MaxDD   : "
            f"{sm.get('max_drawdown', 0)}%"
        )

        print(
            f"  Stability  : "
            f"{wf_v2.stability_score}"
        )
        print(
            f"  Drift      : "
            f"{wf_v2.parameter_drift}"
        )
        print(
            f"  Time       : "
            f"{wf_elapsed:.2f}s"
        )

        print()
        print("  Best Params by Window:")
        for i, w in enumerate(wf_v2.windows):

            print(
                f"    W{i + 1}: "
                f"train {w.train_period} "
                f"-> test {w.test_period} | "
                f"params={w.best_params} | "
                f"ret={w.test_return:.2f}% "
                f"sharpe={w.test_sharpe:.3f}"
            )

        print()
        print("  Params Frequency:")
        for k, v in (
            wf_v2.best_params_freq.items()
        ):
            print(
                f"    {v}x: {k}"
            )

        # ---- HTML 报告 ----
        import os
        os.makedirs("reports", exist_ok=True)

        html_path = (
            "reports/wf_report.html"
        )
        WalkForwardReport(wf_v2).to_html(
            output_path=html_path
        )
        print()
        print(
            f"  HTML 报告: {html_path} "
            f"({os.path.getsize(html_path)} bytes)"
        )

    except Exception as e:

        import traceback
        traceback.print_exc()
        print(
            f"  [V2.2] 跳过: {e}"
        )


    # --------------------------------
    # 12. 收尾
    # --------------------------------

    # ============================================================
    # V2.3 Experiment Tracking
    #
    # 这一次不依赖 VBT
    # 用 BarEngine（已有 build_engine）
    # 跑 4 次实验 + 入库 + search + leaderboard
    # ============================================================
    print()
    print("=" * 50)
    print("  [11] V2.3 Experiment Tracking")
    print("=" * 50)

    try:

        import shutil
        from quantlab.research.tracker import (
            ExperimentRecord,
            ExperimentTracker,
        )

        # 清旧 db
        # 每次 stage 11 重新开始
        db_path = "storage/research.db"
        if os.path.exists(db_path):

            try:
                os.remove(db_path)
                print(
                    f"  [reset] 删旧 db: "
                    f"{db_path}"
                )
            except Exception:
                pass

        # 构造 Tracker
        # strategy registry：strategy_name -> class
        tracker = ExperimentTracker(
            strategy_registry={
                "MACross": MACrossStrategy,
            },
            db_path=db_path,
        )
        print(
            f"  Tracker    : "
            f"db={db_path}"
        )

        # 合成数据
        # 1260 bars
        # 跟 stage 10 一致
        n_bars = 252 * 2
        n_symbols = 3
        rng = np.random.default_rng(seed=7)
        base_dates = pd.date_range(
            start="2023-01-01",
            periods=n_bars,
            freq="B",
        )
        track_data = {}
        for i in range(n_symbols):

            sym = f"S{i}"
            drift = rng.normal(
                0.0004, 0.012, size=n_bars
            )
            close = 100 * np.exp(
                np.cumsum(drift)
            )
            track_data[sym] = pd.DataFrame({
                "close": close,
                "open": close
                * (1 + rng.normal(
                    0, 0.003, size=n_bars
                )),
                "high": close
                * (1 + np.abs(rng.normal(
                    0, 0.005, size=n_bars
                ))),
                "low": close
                * (1 - np.abs(rng.normal(
                    0, 0.005, size=n_bars
                ))),
                "volume": rng.integers(
                    1_000_000,
                    5_000_000,
                    size=n_bars,
                ),
            }, index=base_dates)

        # BarEngine
        # 复用 build_engine()
        engine_v23 = build_engine()

        # 跑 4 次实验
        # 不同 fast / slow
        # 注入到 db
        experiments = [
            ExperimentRecord(
                name="ma_v1_fast",
                strategy_name="MACross",
                params={
                    "fast": 10, "slow": 60
                },
                tag="trend",
            ),
            ExperimentRecord(
                name="ma_v2_balanced",
                strategy_name="MACross",
                params={
                    "fast": 20, "slow": 60
                },
                tag="trend",
            ),
            ExperimentRecord(
                name="ma_v3_slow",
                strategy_name="MACross",
                params={
                    "fast": 20, "slow": 100
                },
                tag="trend",
            ),
            ExperimentRecord(
                name="ma_v4_aggressive",
                strategy_name="MACross",
                params={
                    "fast": 5, "slow": 30
                },
                tag="mean_revert",
            ),
        ]

        print(
            f"  Experiments: {len(experiments)}"
        )
        for rec in experiments:

            # 跑 + 自动入库
            r = tracker.run(
                record=rec,
                engine=engine_v23,
                data=track_data,
            )
            br = r.backtest_result
            m = r.metrics()
            print(
                f"    [{rec.id}] "
                f"{rec.name} | "
                f"params={rec.params} | "
                f"return={m.get('total_return', 0):.2f}% "
                f"sharpe={m.get('sharpe', 0):.3f} "
                f"max_dd={m.get('max_drawdown', 0):.2f}% "
                f"trades={m.get('trade_count', 0)}"
            )

        # ---- Search API 测试 ----
        print()
        print("  [Search] 全部")
        df_all = tracker.search()
        print(
            f"    rows={len(df_all)} | "
            f"cols={list(df_all.columns)}"
        )

        print()
        print(
            "  [Search] strategy=MACross, "
            "sharpe_min=0.0"
        )
        df_search = tracker.search(
            strategy="MACross",
            sharpe_min=0.0,
        )
        print(
            f"    rows={len(df_search)}"
        )
        for _, row in df_search.iterrows():
            print(
                f"      {row['name']} | "
                f"sharpe={row['sharpe']:.3f} "
                f"return={row['total_return']:.2f}%"
            )

        print()
        print(
            "  [Search] tag=mean_revert"
        )
        df_tag = tracker.search(
            tag="mean_revert"
        )
        print(
            f"    rows={len(df_tag)}"
        )
        for _, row in df_tag.iterrows():
            print(
                f"      {row['name']} | "
                f"tag={row['tag']} | "
                f"sharpe={row['sharpe']:.3f}"
            )

        # ---- Leaderboard ----
        print()
        print("  [Leaderboard] Top by Sharpe")
        lb = tracker.leaderboard(
            sort_by="sharpe", top=3
        )
        for i, row in lb.iterrows():
            print(
                f"    #{i + 1} {row['name']} | "
                f"sharpe={row['sharpe']:.3f} "
                f"return={row['total_return']:.2f}%"
            )

        print()
        print("  [Leaderboard] Top by MaxDD (小的好)")
        lb_dd = tracker.leaderboard(
            sort_by="max_drawdown", top=3
        )
        for i, row in lb_dd.iterrows():
            print(
                f"    #{i + 1} {row['name']} | "
                f"max_dd={row['max_drawdown']:.2f}%"
            )

        # ---- DB 文件 size ----
        size = os.path.getsize(db_path)
        print()
        print(
            f"  DB size    : "
            f"{size} bytes"
        )

        print()
        print("  V2.3 PASS")

    except Exception as e:

        import traceback
        traceback.print_exc()
        print(f"  [V2.3] 跳过: {e}")


    # --------------------------------
    # 7. Live Trading Adapter (V2.5)
    # --------------------------------

    print()
    print("=" * 50)
    print("  [5] LiveTrading (V2.5): Paper + Replay")
    print("=" * 50)

    try:

        from quantlab.live import (
            LiveEngine,
            PaperBroker,
            ReplayMarketData,
        )
        from quantlab.risk import (
            EmergencyStop,
            KillSwitch,
            MaxOrderSize,
            MaxPositionLimit,
            OrderSizeCheck,
            PositionLimitCheck,
            RiskManager,
        )

        # 用小数据集做冒烟
        n_live = 20
        rng = np.random.default_rng(seed=7)
        live_idx = pd.date_range(
            "2024-01-01",
            periods=n_live,
            freq="B"
        )
        live_data = {}
        for sym in ["AAPL", "MSFT"]:
            drift = rng.normal(
                0.0005, 0.01, size=n_live
            )
            close = 100 * np.exp(
                np.cumsum(drift)
            )
            live_data[sym] = pd.DataFrame({
                "close": close,
                "open": close,
                "high": close,
                "low": close,
                "volume": rng.integers(
                    1_000_000,
                    3_000_000,
                    size=n_live,
                ),
            }, index=live_idx)

        md = ReplayMarketData(live_data)
        md.subscribe(list(live_data.keys()))

        pb = PaperBroker(
            market_data=md,
            tick_size=0.01,
            initial_cash=100000,
        )
        pb.connect()

        rm = RiskManager()
        rm.add_check(
            OrderSizeCheck(MaxOrderSize(max_qty=10000))
        )
        rm.add_check(
            PositionLimitCheck([
                MaxPositionLimit(
                    symbol=s, max_qty=10000
                )
                for s in live_data
            ])
        )

        estop = EmergencyStop(threshold=-0.05)
        rm.add_check(KillSwitch(estop))

        live_strategy = MACrossStrategy(
            fast=5, slow=10
        )

        live_engine = LiveEngine(
            strategy=live_strategy,
            execution=(
                TargetWeightExecution(
                    lot_size=1,
                    position_tolerance=0.02
                )
            ),
            market_data=md,
            broker=pb,
            risk_manager=rm,
            emergency_stop=estop,
            initial_cash=100000,
            log_dir="logs",
        )

        live_br = live_engine.run(data=live_data)
        print(f"  source       : {live_br.source}")
        print(f"  n_ticks      : {live_br.raw['n_ticks']}")
        print(f"  n_orders     : {live_br.raw['n_orders']}")
        print(f"  n_rejects    : {live_br.raw['n_rejects']}")
        print(f"  final_eq     : {live_br.final_equity:.2f}")
        print(
            f"  total_return : "
            f"{live_br.total_return:.4f}"
        )

        # 验证日志
        import os
        for fn in (
            "orders.log",
            "trades.log",
            "errors.log",
        ):
            p = os.path.join("logs", fn)
            if os.path.exists(p):
                sz = os.path.getsize(p)
                print(f"  {fn:12s}: {sz} bytes")

        print()
        print("  V2.5 PASS")

    except Exception as e:

        import traceback
        traceback.print_exc()
        print(f"  [V2.5] 跳过: {e}")


    print()
    print("=" * 50)
    print("  Workflow Complete")
    print("=" * 50)
