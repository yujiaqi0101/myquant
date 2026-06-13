"""
通用 SOP 跑法（6 stage）
====================

按 [STRATEGY_DEV_GUIDE.md §1] 的推荐顺序，对**任意**继承
`quantlab.signals.SignalStrategy` 的策略类跑完整流水线：

  1. 单次回测             BarEngine
  2. 双引擎一致性验证     VBT (fast) vs BarEngine (precise)
  3. 网格搜索             ParallelOptimizer (fast)
  4. Walk-Forward V2.2    按日历年切窗 + Stability + Drift + HTML
  5. 入库                 ExperimentTracker (SQLite)
  6. 翻向信号 sanity check  反例对照

调用：
    from examples.run_pipeline import run_sop

    run_sop(
        strategy_cls=RSIStrategy,
        param_space=RSI_PARAM_SPACE,
        base_params={
            "period": 14, "oversold": 30, "overbought": 70,
            "use_trend_filter": False, "trend_period": 200,
        },
    )

薄壳写法（每个策略一个文件）:
    # examples/run_rsi.py
    from examples.run_pipeline import run_sop
    from quantlab.signals import (
        RSIStrategy, RSI_PARAM_SPACE,
    )

    if __name__ == "__main__":
        run_sop(
            strategy_cls=RSIStrategy,
            param_space=RSI_PARAM_SPACE,
            base_params={
                "period": 14, "oversold": 30, "overbought": 70,
                "use_trend_filter": False, "trend_period": 200,
            },
        )

返回值:
    dict[str, Any]  6 个 stage 的结果
    {
        "stage1": ExperimentResult,    # 基线回测
        "stage2": ValidationResult,    # 双引擎一致性
        "stage3": pd.DataFrame,        # 网格搜索 top_k
        "stage4": WalkForwardResultV2 | None,   # WF（数据不足时 None）
        "stage5": ExperimentRecordResult,       # 入库结果
        "stage6": ExperimentResult,    # 翻向反例
    }
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Type

import pandas as pd

# 让脚本无论从项目根还是 examples/ 子目录直接跑都能找到 quantlab 包
_PKG_PARENT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

from quantlab.signals.base import SignalStrategy  # noqa: E402


# ---------------------------------------------------------------------- #
# VBT 沙箱环境：必须早于 vectorbt/numba 任何 import
# ---------------------------------------------------------------------- #
def _setup_sandbox_env():
    """
    VBT 偶发崩溃 + matplotlib headless + 不写 cache
    在 import 任何东西前调用
    """
    os.environ.setdefault("NUMBA_DISABLE_JIT", "1")
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("VECTORBT_NO_CACHING", "1")


# ---------------------------------------------------------------------- #
# Engine Builder（精确版 BarEngine + 快版 VectorBTAdapter）
# ---------------------------------------------------------------------- #
def build_precise_engine(
    strategy: SignalStrategy,
    initial_cash: float = 100000.0,
):
    """
    精确版（precise）走 BarEngine：
      多标的 + 组合构建层 + 真实佣金/滑点
    用于：单次回测、WalkForward 的 test 段
    """
    from quantlab.engine import BarEngine
    from quantlab.execution import (
        PercentageCommission,
        PercentageSlippage,
        TargetWeightExecution,
    )
    from quantlab.portfolio_construction import TopN

    return BarEngine(
        strategy=strategy,
        portfolio_constructor=TopN(n=2),
        execution_model=TargetWeightExecution(
            lot_size=1,
            position_tolerance=0.02,
        ),
        commission_model=PercentageCommission(
            rate=0.0003
        ),
        slippage_model=PercentageSlippage(
            rate=0.0002
        ),
        initial_cash=initial_cash,
    )


def build_fast_engine():
    """
    快引擎走 VectorBTAdapter：
      用于：网格搜索（粗筛）+ ValidationRunner 的 fast 端
    """
    from quantlab.adapters import VectorBTAdapter
    from quantlab.portfolio_construction import TopN

    return VectorBTAdapter(
        constructor=TopN(n=2),
        fees=0.0003,
        slippage=0.0002,
        init_cash=100000,
    )


# ---------------------------------------------------------------------- #
# 数据加载
# ---------------------------------------------------------------------- #
def load_data(
    symbols: Optional[List[str]] = None,
    data_dir: str = "data",
) -> Dict[str, pd.DataFrame]:
    if symbols is None:
        symbols = ["AAPL", "MSFT", "NVDA"]
    out = {}
    for sym in symbols:
        df = pd.read_csv(
            f"{data_dir}/{sym}.csv",
            parse_dates=True,
            index_col=0,
        )
        # 显式只保留必需列，类型规整
        df = df[[
            "open", "high", "low", "close", "volume"
        ]].astype(float)
        out[sym] = df
    return out


# ---------------------------------------------------------------------- #
# Stage 1：单次回测
# ---------------------------------------------------------------------- #
def stage1_single_run(strategy_cls, base_params, data):
    """
    目标：拿到基线
    """
    from quantlab.research import Experiment, Report

    print("\n" + "=" * 60)
    print("  [Stage 1] 单次回测 —— baseline")
    print("=" * 60)

    strategy = strategy_cls(**base_params)
    engine = build_precise_engine(strategy)

    result = Experiment(name="baseline").run(
        strategy=strategy,
        engine=engine,
        data=data,
        params=base_params,
    )

    print(Report(result).generate())
    return result


# ---------------------------------------------------------------------- #
# Stage 2：双引擎一致性（ValidationRunner）
# ---------------------------------------------------------------------- #
def stage2_validation(strategy_cls, base_params, data):
    """
    目标：确保 VectorBT 快速引擎和 BarEngine 精确引擎
         在同一组参数上 Sharpe 差距 < 20%
         consistency < 0.8 ⇒ 参数组直接淘汰
    """
    from quantlab.research import ValidationRunner

    print("\n" + "=" * 60)
    print("  [Stage 2] 双引擎一致性验证")
    print("=" * 60)

    runner = ValidationRunner(
        fast_engine=build_fast_engine(),
        precise_engine=build_precise_engine(
            strategy_cls(**base_params)
        ),
        consistency_threshold=0.8,
    )

    vr = runner.validate(
        strategy_cls=strategy_cls,
        params=base_params,
        data=data,
    )
    print(f"  fast    sharpe = {vr.fast_sharpe:.4f}")
    print(f"  precise sharpe = {vr.precise_sharpe:.4f}")
    # 字段名是 consistency_score（不是 consistency）
    print(f"  consistency    = {vr.consistency_score:.4f}")
    print(f"  threshold      = {runner.consistency_threshold}")
    # passed = consistency_score >= threshold
    status = "OK" if vr.passed else "ELIMINATED"
    print(f"  status         = {status}")
    if not vr.passed:
        print(
            "  [WARN] 本组参数一致性不足，已被 ValidationRunner 淘汰"
        )
    return vr


# ---------------------------------------------------------------------- #
# Stage 3：网格搜索（ParallelOptimizer）
# ---------------------------------------------------------------------- #
def stage3_grid(
    strategy_cls,
    param_space,
    data,
    top_k: int = 5,
):
    """
    目标：从 param_space 里挑 Sharpe top_k 组
    内存提示：< 50 组别用 ParallelOptimizer（进程开销 > 计算）
    """
    from quantlab.parallel_optimizer import (
        ParallelOptimizer,
    )
    from quantlab.data.cache import factor_cache

    print("\n" + "=" * 60)
    print("  [Stage 3] 网格搜索（ParallelOptimizer）")
    print("=" * 60)

    opt = ParallelOptimizer(
        strategy_cls=strategy_cls,
        engine_spec=(
            "vectorbt",
            {
                "fees": 0.0003,
                "slippage": 0.0002,
                "init_cash": 100000,
            },
        ),
        max_workers=4,
        top_k=top_k,
        early_split=0.3,
    )

    factor_cache.clear()    # 跨 Engine 自己清一次（双保险）
    df = opt.run(
        data=data,
        param_space=param_space,
    )

    print(df.head(top_k).to_string(index=False))
    return df


# ---------------------------------------------------------------------- #
# Stage 4：Walk-Forward V2.2
# ---------------------------------------------------------------------- #
def stage4_walkforward(
    strategy_cls,
    base_params,
    data,
    train_years: int = 2,
    test_years: int = 1,
):
    """
    目标：
      avg_test_sharpe >= 0.5
      avg_test_max_dd  <= 0.3
      stability_score  >= 0.6
      parameter_drift  <= 0.3
    """
    from quantlab.research.walk_forward import (
        WalkForwardRunner,
        WalkForwardReport,
    )

    print("\n" + "=" * 60)
    print("  [Stage 4] WalkForward V2.2")
    print("=" * 60)

    # ---- 0) 预检：数据跨度 vs train_years + test_years ----
    # WindowGenerator 是按日历年切，不是按 bar
    # 数据跨度必须 >= train_years + test_years 才能生成 1 个窗口
    first_sym = list(data.keys())[0]
    full_index = data[first_sym].index
    span_years = (
        full_index[-1].year
        - full_index[0].year
        + 1
    )
    n_bars = len(full_index)
    required = train_years + test_years
    print(
        f"  data span = "
        f"{full_index[0].date()} ~ "
        f"{full_index[-1].date()} "
        f"({n_bars} bars, {span_years} year(s))"
    )
    print(
        f"  required   = {required} year(s) "
        f"for train={train_years} + test={test_years}"
    )
    if span_years < required:
        print(
            f"  [SKIP] 数据不足 {required} 年，"
            f"WindowGenerator 会生成 0 个窗口"
        )
        print(
            f"         解决：换更长数据 (>= {required} 年)，"
            f"或临时把 train_years=0 test_years=1 "
            f"(会退化为单窗口 in-sample split)"
        )
        return None

    wf = WalkForwardRunner(
        optimizer=None,           # V2.2 简化：单组参数直接 OOS 评估
        validation_runner=None,
        event_engine=build_precise_engine(
            strategy_cls(**base_params)
        ),
        train_years=train_years,
        test_years=test_years,
        top_train=3,
        top_val=1,
    )

    result = wf.run(
        data=data,
        param_space=base_params,   # 单组：策略入参 dict
    )

    print(f"  n_windows          = {len(result.windows)}")
    print(f"  avg_test_sharpe    = {result.avg_test_sharpe:.4f}")
    print(f"  avg_test_max_dd    = {result.avg_test_max_dd:.4f}")
    print(f"  stability_score    = {result.stability_score:.4f}")
    print(f"  parameter_drift    = {result.parameter_drift:.4f}")

    # HTML 报告
    out_html = "reports/wf_report.html"
    os.makedirs("reports", exist_ok=True)
    WalkForwardReport(result).to_html(out_html)
    print(f"  HTML report -> {out_html}")
    return result


# ---------------------------------------------------------------------- #
# Stage 5：入库（ExperimentTracker）
# ---------------------------------------------------------------------- #
def stage5_tracker(
    strategy_cls,
    base_params,
    data,
    strategy_name: Optional[str] = None,
    tag: str = "default",
    note: str = "",
    db_path: str = "storage/research.db",
):
    """
    目标：把这次实验的元数据 + 指标写进 SQLite
         后续 leaderboard / search 可以直接读

    strategy_name:
        Tracker 里注册的名字
        None = 用 strategy_cls.__name__
    """
    from quantlab.research.tracker import (
        ExperimentRecord,
        ExperimentTracker,
    )

    if strategy_name is None:
        strategy_name = strategy_cls.__name__

    print("\n" + "=" * 60)
    print("  [Stage 5] ExperimentTracker（SQLite）")
    print("=" * 60)

    tracker = ExperimentTracker(
        strategy_registry={
            strategy_name: strategy_cls,
        },
        db_path=db_path,
    )

    record = ExperimentRecord(
        name=(
            f"{strategy_name.lower()}_v1_"
            f"p{base_params.get('period', 0)}_"
            f"o{base_params.get('oversold', 0)}"
        ),
        strategy_name=strategy_name,
        params=base_params,
        tag=tag,
        note=note,
    )

    res = tracker.run(
        record=record,
        engine=build_precise_engine(
            strategy_cls(**base_params)
        ),
        data=data,
    )
    print(f"  inserted id = {res.experiment.id}")
    print(f"  metrics     = {res.metrics()}")

    print("\n  Leaderboard (top 5 by sharpe):")
    print(
        tracker.leaderboard(
            sort_by="sharpe", top=5
        ).to_string(index=False)
    )
    return res


# ---------------------------------------------------------------------- #
# Stage 6：翻向信号 sanity check（反例）
# ---------------------------------------------------------------------- #
def stage6_reverse_signal(
    strategy_cls,
    base_params,
    data,
):
    """
    把信号取反（伪多 ⇒ 伪空）
    收益应该显著变差
    如果不变差 ⇒ 数据 / 框架有 bug
    """
    from quantlab.research import Experiment, Report

    print("\n" + "=" * 60)
    print("  [Stage 6] 反向信号 sanity check")
    print("=" * 60)

    class _ReverseStrategy(strategy_cls):
        """继承原策略类把信号取反，用于反例测试
        取值 ∈ {0, 1} 时 1 - df 也是 {0, 1}
        若原策略输出 {-1, 0, 1}，需要子类重写 __neg__
        """
        def signal(self, ctx):
            df = super().signal(ctx)
            return 1 - df

    strategy = _ReverseStrategy(**base_params)
    engine = build_precise_engine(strategy)

    result = Experiment(name="reverse_signal").run(
        strategy=strategy,
        engine=engine,
        data=data,
        params=base_params,
    )
    print(Report(result).generate())
    return result


# ---------------------------------------------------------------------- #
# 总入口
# ---------------------------------------------------------------------- #
def run_sop(
    strategy_cls: Type[SignalStrategy],
    param_space: Dict,
    base_params: Dict,
    data: Optional[Dict[str, pd.DataFrame]] = None,
    symbols: Optional[List[str]] = None,
    top_k: int = 5,
    train_years: int = 2,
    test_years: int = 1,
    strategy_name: Optional[str] = None,
    tag: str = "default",
    note: str = "",
    skip_stages: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    跑完整的 6 stage SOP。

    Parameters
    ----------
    strategy_cls : Type[SignalStrategy]
        策略类（必须继承 SignalStrategy，__init__ 可 JSON 序列化）
    param_space : Dict
        参数网格（dict[str, list]，传给 ParallelOptimizer）
    base_params : Dict
        baseline 参数（dict[str, value]，传给单次回测 + WF + Tracker）
    data : Dict[symbol, DataFrame] | None
        OHLCV 数据；None 时自动从 data/ 加载 AAPL/MSFT/NVDA
    symbols : List[str] | None
        data=None 时生效，指定要加载哪些 symbol
    top_k : int
        Stage 3 网格搜索保留 top 几
    train_years / test_years : int
        Stage 4 WalkForward 窗口大小
    strategy_name : str | None
        Stage 5 Tracker 注册名；None = strategy_cls.__name__
    tag / note : str
        Stage 5 入库标签 / 备注
    skip_stages : List[int] | None
        跳过的 stage 编号（[1,2,3,4,5,6]）
        例：[4, 6] 跳过 WF 和反向信号

    Returns
    -------
    Dict[str, Any]
        {
            "stage1": ExperimentResult | None,
            "stage2": ValidationResult | None,
            "stage3": pd.DataFrame | None,
            "stage4": WalkForwardResultV2 | None,
            "stage5": ExperimentRecordResult | None,
            "stage6": ExperimentResult | None,
        }
    """
    # 沙箱环境必须在任何 vectorbt/numba 导入之前
    _setup_sandbox_env()

    skip = set(skip_stages or [])

    # ---- 0) 数据 ----
    if data is None:
        data = load_data(symbols=symbols)
    print(
        f"  symbols        = {list(data.keys())}"
    )
    print(
        f"  bars per sym   = "
        f"{len(next(iter(data.values())))}"
    )

    results: Dict[str, Any] = {
        "stage1": None,
        "stage2": None,
        "stage3": None,
        "stage4": None,
        "stage5": None,
        "stage6": None,
    }

    # ---- Stage 1 ----
    if 1 not in skip:
        try:
            results["stage1"] = stage1_single_run(
                strategy_cls, base_params, data
            )
        except Exception as e:
            print(
                f"  [Stage 1] skipped: "
                f"{type(e).__name__}: {e}"
            )

    # ---- Stage 2 ----
    # VBTAdapter 在某些环境会 SIGABRT
    if 2 not in skip:
        try:
            results["stage2"] = stage2_validation(
                strategy_cls, base_params, data
            )
        except Exception as e:
            print(
                f"  [Stage 2] skipped: "
                f"{type(e).__name__}: {e}"
            )

    # ---- Stage 3 ----
    if 3 not in skip:
        try:
            results["stage3"] = stage3_grid(
                strategy_cls,
                param_space,
                data,
                top_k=top_k,
            )
        except Exception as e:
            print(
                f"  [Stage 3] skipped: "
                f"{type(e).__name__}: {e}"
            )

    # ---- Stage 4 ----
    if 4 not in skip:
        try:
            results["stage4"] = stage4_walkforward(
                strategy_cls,
                base_params,
                data,
                train_years=train_years,
                test_years=test_years,
            )
        except Exception as e:
            print(
                f"  [Stage 4] skipped: "
                f"{type(e).__name__}: {e}"
            )

    # ---- Stage 5 ----
    if 5 not in skip:
        try:
            results["stage5"] = stage5_tracker(
                strategy_cls,
                base_params,
                data,
                strategy_name=strategy_name,
                tag=tag,
                note=note,
            )
        except Exception as e:
            print(
                f"  [Stage 5] skipped: "
                f"{type(e).__name__}: {e}"
            )

    # ---- Stage 6 ----
    if 6 not in skip:
        try:
            results["stage6"] = (
                stage6_reverse_signal(
                    strategy_cls, base_params, data
                )
            )
        except Exception as e:
            print(
                f"  [Stage 6] skipped: "
                f"{type(e).__name__}: {e}"
            )

    print("\n  [OK] SOP 跑完")
    return results
