"""
quantlab_cli — quantlab 统一 CLI 入口
======================================

Phase 6 实施：6 个子命令

可用子命令（python main.py quantlab <subcmd> ...）：
    run          单次回测（多引擎选择：bar / event / vbt / tick）
    compare      多引擎对比（同一策略跑多个引擎并对比指标）
    optimize     参数网格搜索（基于 quantlab.Optimizer）
    walkforward  Walk-Forward 验证（基于 quantlab.research.WalkForwardRunner）
    track        实验跟踪（list / show / leaderboard / search / delete）
    quintile     多因子 5 分位分层回测（基于 quantlab_quintile.QuintileExperiment）

设计上：
    - 每个子命令都是函数：run_quantlab_command / compare_quantlab_command / ...
    - 共享 setup_common_args(parser) 注入公共参数（--strategy / --pool / ...）
    - 数据加载复用 myquant backtest_cli._run_quantlab_backtest 中的逻辑
    - 入库复用 quantlab.research.database / repository / tracker
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# myquant 路径与公共组件
from src.cli.backtest_cli import (
    _get_db_path,
    _resolve_engine_choice,
    _is_v2_strategy,
)
from src.quantlab_adapters import (
    from_quantlab_db,
    SignalStrategyRegistry,
    discover_v2_strategies,
)


# ============================================================
# 公共工具
# ============================================================

def _setup_pool_args(parser: argparse.ArgumentParser) -> None:
    """注入 --pool / --stocks 公共参数。"""
    parser.add_argument(
        "--pool", metavar="POOL_NAME",
        help="使用股票池",
    )
    parser.add_argument(
        "--stocks", metavar="CODES",
        help="股票代码列表，逗号分隔",
    )


def _setup_date_args(
    parser: argparse.ArgumentParser,
    default_start: str = "2024-01-01",
    default_end: str = "2024-12-31",
) -> None:
    """注入 --start-date / --end-date。"""
    parser.add_argument("--start-date", default=default_start)
    parser.add_argument("--end-date", default=default_end)


def _setup_engine_args(parser: argparse.ArgumentParser) -> None:
    """注入 --engine / --no-risk-check / --no-execution-cost。"""
    parser.add_argument(
        "--engine", type=str, default="bar",
        choices=["auto", "bar", "event", "vbt", "tick", "myquant"],
        help="回测引擎（默认 bar）",
    )
    parser.add_argument(
        "--no-risk-check", action="store_true",
        help="禁用 A 股 RiskCheck",
    )
    parser.add_argument(
        "--no-execution-cost", action="store_true",
        help="禁用佣金和滑点",
    )


def _setup_output_args(parser: argparse.ArgumentParser) -> None:
    """注入 --initial-capital / --output-dir / --name。"""
    parser.add_argument(
        "--initial-capital", type=float, default=1_000_000,
        help="初始资金",
    )
    parser.add_argument(
        "--output-dir", default="reports/quantlab",
        help="报告输出目录",
    )
    parser.add_argument(
        "--name", default="",
        help="报告名称（默认自动生成）",
    )


def _resolve_stock_codes(args: argparse.Namespace) -> tuple:
    """
    解析 --pool / --stocks，返回 (stock_codes, pool_name)。
    """
    if getattr(args, "pool", None) and getattr(args, "stocks", None):
        raise ValueError("--pool 和 --stocks 不能同时使用")

    stock_codes = None
    pool_name = None

    if getattr(args, "pool", None):
        from src.data.database import DatabaseManager
        db = DatabaseManager(_get_db_path())
        stock_codes = db.get_stock_pool_members(args.pool)
        if not stock_codes:
            raise ValueError(f"股票池 '{args.pool}' 不存在或为空")
        pool_name = args.pool

    if getattr(args, "stocks", None):
        stock_codes = [s.strip() for s in args.stocks.split(",")]

    return stock_codes, pool_name


def _load_quantlab_data(
    args: argparse.Namespace,
    stock_codes: Optional[list],
    warmup_days: int = 60,
) -> Dict[str, pd.DataFrame]:
    """
    加载 quantlab 格式的 Dict[symbol, DataFrame] 数据。
    """
    start_dt = pd.Timestamp(args.start_date)
    warmup_start = (
        start_dt - timedelta(days=int(warmup_days * 1.5 + 10))
    ).strftime("%Y-%m-%d")

    data = from_quantlab_db(
        db_path=_get_db_path(),
        start_date=warmup_start,
        end_date=args.end_date,
        stock_codes=stock_codes,
    )
    if not data:
        raise ValueError("未加载到任何数据，请检查日期范围与股票池")

    return data


# ============================================================
# quantlab_engine factory
# ============================================================

def _get_strategy_params(strategy) -> dict:
    """
    从 v2 SignalStrategy 实例中提取参数。
    v2 策略一般把参数存在 self.xxx，没有统一的 params 字典。
    这里取所有非私有、非方法、非下划线的 int/float/bool/str 属性。
    """
    params = {}
    for k, v in vars(strategy).items():
        if k.startswith("_"):
            continue
        if callable(v):
            continue
        if isinstance(v, (int, float, bool, str)):
            params[k] = v
    # 也兼容 v1 BaseStrategy.params
    if hasattr(strategy, "params") and isinstance(
        getattr(strategy, "params", None), dict
    ):
        for k, v in strategy.params.items():
            params.setdefault(k, v)
    return params


def _build_quantlab_engine(engine_choice: str, strategy, initial_capital: float):
    """构造 quantlab 引擎实例（与 backtest_cli 共用）。"""
    from src.quantlab.execution import (
        PercentageCommission,
        PercentageSlippage,
    )
    from src.quantlab.portfolio_construction.top_n import TopN
    from src.quantlab_extras import build_ashare_execution

    params = _get_strategy_params(strategy)
    top_n = int(params.get("top_n", 30))
    if top_n == 30:
        for key in ("n_positions", "top_pct", "max_positions"):
            if key in params:
                v = params[key]
                if isinstance(v, int) and 0 < v < 1000:
                    top_n = v
                    break
    constructor = TopN(n=top_n)
    execution = build_ashare_execution(
        commission_rate=0.00025,
        slippage_rate=0.0001,
        lot_size=100,
    )

    if engine_choice == "bar":
        from src.quantlab.engine import BarEngine
        return BarEngine(
            strategy=strategy,
            portfolio_constructor=constructor,
            execution_model=execution,
            commission_model=PercentageCommission(rate=0.00025),
            slippage_model=PercentageSlippage(rate=0.0001),
            initial_cash=initial_capital,
        )

    if engine_choice == "event":
        from src.quantlab.event_engine import EventEngine
        return EventEngine(
            strategy=strategy,
            portfolio_constructor=constructor,
            execution_model=execution,
            commission_model=PercentageCommission(rate=0.00025),
            slippage_model=PercentageSlippage(rate=0.0001),
            initial_cash=initial_capital,
        )

    if engine_choice == "vbt":
        from src.quantlab.adapters.vectorbt_adapter import VectorBTAdapter
        return VectorBTAdapter(
            constructor=constructor,
            fees=0.00025,
            slippage=0.0001,
            init_cash=initial_capital,
        )

    if engine_choice == "tick":
        from src.quantlab.engine.tick_engine import TickEngine
        return TickEngine(
            strategy=strategy,
            initial_cash=initial_capital,
        )

    raise ValueError(f"未知引擎: {engine_choice}")


# ============================================================
# sub-command: run
# ============================================================

def setup_run_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strategy", "-s", required=True,
        help="策略名（v2 策略：xxx_v2）",
    )
    _setup_pool_args(parser)
    _setup_date_args(parser)
    _setup_engine_args(parser)
    _setup_output_args(parser)
    parser.add_argument(
        "--track", action="store_true",
        help="把本次回测作为 experiment 写入 research.db",
    )
    parser.add_argument(
        "--tag", default="cli_run",
        help="experiment 标签（与 --track 配合）",
    )
    parser.add_argument(
        "--note", default="",
        help="experiment 备注（与 --track 配合）",
    )


def run_quantlab_command(args: argparse.Namespace) -> None:
    """执行 quantlab run 子命令。"""
    # 1) 加载 v2 策略
    discover_v2_strategies("src.strategies")
    strategy_class = SignalStrategyRegistry.get(args.strategy)
    if strategy_class is None:
        print(f"错误：未知 v2 策略 '{args.strategy}'")
        print(
            "可用 v2 策略:",
            ", ".join(s["name"] for s in SignalStrategyRegistry.list_strategies()),
        )
        return

    # 2) 解析引擎
    engine_choice = _resolve_engine_choice(args.strategy, args.engine)

    # 3) 股票范围
    try:
        stock_codes, pool_name = _resolve_stock_codes(args)
    except ValueError as e:
        print(f"错误: {e}")
        return

    # 4) 加载数据
    print(f"[quantlab/{engine_choice}] 数据加载...")
    print(f"  起始: {args.start_date}  结束: {args.end_date}")
    if pool_name:
        print(f"  股票池: {pool_name} ({len(stock_codes)} 只)")
    elif stock_codes:
        print(f"  股票列表: {len(stock_codes)} 只")

    try:
        data = _load_quantlab_data(args, stock_codes)
    except ValueError as e:
        print(f"错误: {e}")
        return
    print(f"  加载完成: {len(data)} 个 symbol")

    # 5) 构造策略 + 引擎
    strategy = strategy_class()
    engine = _build_quantlab_engine(
        engine_choice=engine_choice,
        strategy=strategy,
        initial_capital=args.initial_capital,
    )

    # 6) 跑回测
    print(f"\n开始回测 [引擎={engine_choice}, 策略={args.strategy}]...")
    t0 = time.time()
    strategy_params = _get_strategy_params(strategy)
    ql_result = engine.run(
        strategy=strategy, data=data, params=strategy_params,
    )
    elapsed = time.time() - t0
    print(f"  回测耗时: {elapsed:.1f}s")
    if hasattr(ql_result, "error") and ql_result.error:
        print(f"[错误] {ql_result.error}")
        return

    # 7) 打印结果
    print(f"\n=== 回测结果 ===")
    print(f"  引擎:    {ql_result.source}")
    print(f"  总收益:  {ql_result.total_return:.2%}")
    print(f"  夏普:    {ql_result.sharpe:.3f}")
    print(f"  最大回撤:{ql_result.max_drawdown:.2%}")
    print(f"  胜率:    {ql_result.win_rate:.2%}")
    print(f"  交易次数:{ql_result.trade_count}")

    # 8) 写库（如果 --track）
    if args.track:
        try:
            from src.quantlab.research.tracker import (
                ExperimentTracker, ExperimentRecord,
            )
            from src.quantlab.research.database import Database

            record = ExperimentRecord(
                name=args.name or f"cli_run_{args.strategy}",
                strategy_name=args.strategy,
                params=strategy_params,
                tag=args.tag,
                note=args.note,
            )
            tracker = ExperimentTracker(db_path=Database().db_path)
            tracker.register_strategy(args.strategy, strategy_class)
            tracker.run(record=record, engine=engine, data=data)
            print(f"\n  [TRACK] experiment_id={record.id} 已写入 research.db")
        except Exception as e:
            print(f"  [TRACK] 写入失败: {e}")


# ============================================================
# sub-command: compare
# ============================================================

def setup_compare_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strategy", "-s", required=True,
        help="策略名（v2 策略）",
    )
    _setup_pool_args(parser)
    _setup_date_args(parser)
    _setup_output_args(parser)
    parser.add_argument(
        "--engines", default="bar,event",
        help="要对比的引擎列表，逗号分隔（默认 bar,event）",
    )


def compare_quantlab_command(args: argparse.Namespace) -> None:
    """多引擎对比：同一策略在多个引擎上跑，对比核心指标。"""
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]

    # 加载 v2 策略
    discover_v2_strategies("src.strategies")
    strategy_class = SignalStrategyRegistry.get(args.strategy)
    if strategy_class is None:
        print(f"错误：未知 v2 策略 '{args.strategy}'")
        return

    # 股票范围
    try:
        stock_codes, pool_name = _resolve_stock_codes(args)
    except ValueError as e:
        print(f"错误: {e}")
        return

    # 数据（只加载一次，复用）
    try:
        data = _load_quantlab_data(args, stock_codes)
    except ValueError as e:
        print(f"错误: {e}")
        return

    print(f"\n=== 多引擎对比 [{args.strategy}] ===")
    print(f"  引擎: {engines}")
    print(f"  股票: {len(stock_codes) if stock_codes else '全市场'}")

    results = []
    for engine_choice in engines:
        # 每次重建 strategy + engine（避免 state 污染）
        strategy = strategy_class()
        try:
            engine = _build_quantlab_engine(
                engine_choice=engine_choice,
                strategy=strategy,
                initial_capital=args.initial_capital,
            )
        except Exception as e:
            print(f"  [{engine_choice}] 引擎构造失败: {e}")
            continue

        t0 = time.time()
        try:
            strategy_params = _get_strategy_params(strategy)
            ql_result = engine.run(
                strategy=strategy, data=data, params=strategy_params,
            )
            elapsed = time.time() - t0
            if hasattr(ql_result, "error") and ql_result.error:
                print(f"  [{engine_choice}] 回测失败: {ql_result.error}")
                continue

            results.append({
                "engine": engine_choice,
                "total_return": ql_result.total_return,
                "sharpe": ql_result.sharpe,
                "max_drawdown": ql_result.max_drawdown,
                "trade_count": ql_result.trade_count,
                "win_rate": ql_result.win_rate,
                "elapsed_s": elapsed,
            })
        except Exception as e:
            print(f"  [{engine_choice}] 异常: {e}")

    if not results:
        print("\n所有引擎都失败，无可对比结果。")
        return

    # 打印对比表
    print(f"\n=== 对比结果 ===")
    print(f"{'引擎':<10} {'总收益':>10} {'夏普':>8} {'最大回撤':>10} "
          f"{'胜率':>8} {'交易数':>8} {'耗时(s)':>8}")
    print("-" * 70)
    for r in results:
        print(
            f"{r['engine']:<10} "
            f"{r['total_return']:>9.2%} "
            f"{r['sharpe']:>8.3f} "
            f"{r['max_drawdown']:>9.2%} "
            f"{r['win_rate']:>7.2%} "
            f"{r['trade_count']:>8d} "
            f"{r['elapsed_s']:>8.2f}"
        )

    # 落盘
    output_dir = Path(args.output_dir) / "compare"
    output_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or f"compare_{args.strategy}_{int(time.time())}"
    out_file = output_dir / f"{name}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "strategy": args.strategy,
            "engines": engines,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "results": results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n  对比结果已保存: {out_file}")


# ============================================================
# sub-command: optimize
# ============================================================

def setup_optimize_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strategy", "-s", required=True,
        help="策略名（v2 策略）",
    )
    _setup_pool_args(parser)
    _setup_date_args(parser)
    _setup_engine_args(parser)
    _setup_output_args(parser)
    parser.add_argument(
        "--param-space", required=True,
        help="参数空间 JSON 字符串，如 '{\"top_n\":[10,20],\"min_amount\":[200,500]}'",
    )
    parser.add_argument(
        "--scorer", default="sharpe",
        choices=["sharpe", "return", "calmar"],
        help="评分函数（默认 sharpe）",
    )
    parser.add_argument(
        "--top-k", type=int, default=10,
        help="保留 Top K 个结果（默认 10）",
    )
    parser.add_argument(
        "--parallel", type=int, default=1,
        help="并行 worker 数（默认 1 串行）",
    )


def optimize_quantlab_command(args: argparse.Namespace) -> None:
    """参数网格搜索。"""
    discover_v2_strategies("src.strategies")
    strategy_class = SignalStrategyRegistry.get(args.strategy)
    if strategy_class is None:
        print(f"错误：未知 v2 策略 '{args.strategy}'")
        return

    # 解析参数空间
    try:
        param_space = json.loads(args.param_space)
    except json.JSONDecodeError as e:
        print(f"错误: --param-space 解析失败: {e}")
        return
    if not isinstance(param_space, dict) or not param_space:
        print("错误: --param-space 必须是 dict，如 '{\"top_n\":[10,20]}'")
        return

    # 股票范围
    try:
        stock_codes, _ = _resolve_stock_codes(args)
    except ValueError as e:
        print(f"错误: {e}")
        return

    # 数据
    try:
        data = _load_quantlab_data(args, stock_codes)
    except ValueError as e:
        print(f"错误: {e}")
        return

    # 引擎
    engine_choice = _resolve_engine_choice(args.strategy, args.engine)
    strategy = strategy_class()
    engine = _build_quantlab_engine(
        engine_choice=engine_choice,
        strategy=strategy,
        initial_capital=args.initial_capital,
    )

    # 评分器
    from src.quantlab.statistics import sharpe_score
    from src.quantlab.analytics import total_return

    if args.scorer == "sharpe":
        scorer = sharpe_score
    elif args.scorer == "return":
        scorer = lambda eq: total_return(eq) if eq else 0.0
    elif args.scorer == "calmar":
        from src.quantlab.analytics import max_drawdown
        def scorer(eq):
            tr = total_return(eq) if eq else 0.0
            mdd = max_drawdown(eq) if eq else 1.0
            return tr / abs(mdd) if mdd != 0 else 0.0
    else:
        scorer = sharpe_score

    # Optimizer
    from src.quantlab.optimizer import Optimizer

    n_combos = 1
    for v in param_space.values():
        n_combos *= len(v)
    print(f"\n=== 参数优化 [{args.strategy}] ===")
    print(f"  引擎: {engine_choice}")
    print(f"  评分: {args.scorer}")
    print(f"  参数空间: {param_space}")
    print(f"  组合数: {n_combos}")
    print(f"  Top K: {args.top_k}")

    optimizer = Optimizer(
        strategy_cls=strategy_class,
        engine=engine,
        scorer=scorer,
    )

    t0 = time.time()
    result_df = optimizer.run(data=data, param_space=param_space)
    elapsed = time.time() - t0
    print(f"  优化耗时: {elapsed:.1f}s")

    if result_df is None or result_df.empty:
        print("  优化无结果。")
        return

    # 输出 Top K
    if "score" in result_df.columns:
        result_df = result_df.sort_values("score", ascending=False)
    top_k_df = result_df.head(args.top_k)
    print(f"\n=== Top {args.top_k} ===")
    cols = [c for c in top_k_df.columns if c not in ("error",)]
    print(top_k_df[cols].to_string(index=False))

    # 落盘
    output_dir = Path(args.output_dir) / "optimize"
    output_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or f"optimize_{args.strategy}_{int(time.time())}"
    out_file = output_dir / f"{name}.csv"
    result_df.to_csv(out_file, index=False, encoding="utf-8-sig")
    print(f"\n  全部结果已保存: {out_file}")


# ============================================================
# sub-command: walkforward
# ============================================================

def setup_walkforward_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strategy", "-s", required=True,
        help="策略名（v2 策略）",
    )
    _setup_pool_args(parser)
    _setup_date_args(parser)
    _setup_engine_args(parser)
    _setup_output_args(parser)
    parser.add_argument(
        "--param-space", required=True,
        help="参数空间 JSON 字符串",
    )
    parser.add_argument(
        "--train-years", type=int, default=3,
        help="训练窗口年数（默认 3）",
    )
    parser.add_argument(
        "--test-years", type=int, default=1,
        help="测试窗口年数（默认 1）",
    )
    parser.add_argument(
        "--top-train", type=int, default=5,
        help="Train 阶段选 Top N（默认 5）",
    )
    parser.add_argument(
        "--report-html", action="store_true",
        help="生成 HTML 报告",
    )


def walkforward_quantlab_command(args: argparse.Namespace) -> None:
    """Walk-Forward 验证。"""
    discover_v2_strategies("src.strategies")
    strategy_class = SignalStrategyRegistry.get(args.strategy)
    if strategy_class is None:
        print(f"错误：未知 v2 策略 '{args.strategy}'")
        return

    try:
        param_space = json.loads(args.param_space)
    except json.JSONDecodeError as e:
        print(f"错误: --param-space 解析失败: {e}")
        return

    try:
        stock_codes, _ = _resolve_stock_codes(args)
    except ValueError as e:
        print(f"错误: {e}")
        return

    try:
        data = _load_quantlab_data(args, stock_codes)
    except ValueError as e:
        print(f"错误: {e}")
        return

    # 引擎
    engine_choice = _resolve_engine_choice(args.strategy, args.engine)
    strategy = strategy_class()
    engine = _build_quantlab_engine(
        engine_choice=engine_choice,
        strategy=strategy,
        initial_capital=args.initial_capital,
    )

    print(f"\n=== Walk-Forward 验证 [{args.strategy}] ===")
    print(f"  训练/测试窗口: {args.train_years}/{args.test_years} 年")
    print(f"  参数空间: {param_space}")

    # 走 quantlab.research.walk_forward 的 V2.2 runner
    # 因为它需要 optimizer / validation_runner / event_engine 三个
    # 为了简化，这里走 V1（直接基于 Optimizer）
    from src.quantlab.research.walk_forward import WalkForward

    wf = WalkForward(
        train_bars=args.train_years * 240,  # 粗略 240 bar/年
        test_bars=args.test_years * 240,
    )
    wf.set_engine_template(engine)

    t0 = time.time()
    try:
        wf_result = wf.run(
            strategy_cls=strategy_class,
            param_space=param_space,
            data=data,
        )
    except Exception as e:
        print(f"  Walk-Forward 失败: {e}")
        import traceback
        traceback.print_exc()
        return
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.1f}s")

    # 输出
    print(f"\n=== Walk-Forward 结果 ===")
    print(f"  窗口数:        {len(wf_result.windows)}")
    print(f"  平均测试夏普:  {wf_result.avg_test_sharpe:.3f}")
    print(f"  平均测试收益:  {wf_result.avg_test_return:.2f}%")
    print(f"  拼接夏普:      {wf_result.summary.get('n_windows', 0)} 个窗口")

    for i, w in enumerate(wf_result.windows, 1):
        bp = ", ".join(f"{k}={v}" for k, v in w.best_params.items())
        print(
            f"  Window {i}: "
            f"train={w.train_period} test={w.test_period} "
            f"sharpe={w.train_score:.3f} | "
            f"params={bp}"
        )

    # 落盘
    output_dir = Path(args.output_dir) / "walkforward"
    output_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or f"wf_{args.strategy}_{int(time.time())}"
    out_file = output_dir / f"{name}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "strategy": args.strategy,
            "n_windows": len(wf_result.windows),
            "avg_test_sharpe": wf_result.avg_test_sharpe,
            "avg_test_return": wf_result.avg_test_return,
            "windows": [
                {
                    "train_period": w.train_period,
                    "test_period": w.test_period,
                    "best_params": w.best_params,
                    "train_score": w.train_score,
                }
                for w in wf_result.windows
            ],
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  结果已保存: {out_file}")


# ============================================================
# sub-command: track
# ============================================================

def setup_track_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="track_action", help="track 子动作")

    # list
    p_list = sub.add_parser("list", help="列出所有 experiment")
    p_list.add_argument("--limit", type=int, default=20)

    # show
    p_show = sub.add_parser("show", help="查看 experiment 详情")
    p_show.add_argument("--id", required=True, help="experiment id")

    # leaderboard
    p_lb = sub.add_parser("leaderboard", help="排行榜")
    p_lb.add_argument(
        "--sort-by", default="sharpe",
        choices=["sharpe", "return", "max_drawdown", "stability"],
    )
    p_lb.add_argument("--top", type=int, default=20)

    # search
    p_search = sub.add_parser("search", help="条件搜索")
    p_search.add_argument("--strategy", default=None)
    p_search.add_argument("--sharpe-min", type=float, default=None)
    p_search.add_argument("--max-dd-max", type=float, default=None)
    p_search.add_argument("--return-min", type=float, default=None)
    p_search.add_argument("--tag", default=None)
    p_search.add_argument("--limit", type=int, default=20)

    # delete
    p_del = sub.add_parser("delete", help="删除 experiment")
    p_del.add_argument("--id", required=True)


def track_quantlab_command(args: argparse.Namespace) -> None:
    """实验跟踪：list / show / leaderboard / search / delete。"""
    from src.quantlab.research.repository import ExperimentRepository
    from src.quantlab.research.database import Database

    db = Database()
    repo = ExperimentRepository(db=db)

    if args.track_action == "list":
        df = repo.list_all(limit=args.limit)
        if df.empty:
            print("暂无 experiment。")
            return
        print(f"\n=== Experiment 列表 (limit={args.limit}) ===")
        cols = [
            "id", "name", "strategy",
            "sharpe", "total_return", "max_drawdown",
            "trade_count", "created_at",
        ]
        cols = [c for c in cols if c in df.columns]
        print(df[cols].to_string(index=False))

    elif args.track_action == "show":
        row = repo.get(args.id)
        if row is None:
            print(f"未找到 experiment: {args.id}")
            return
        print(f"\n=== Experiment 详情 ===")
        for k, v in row.items():
            print(f"  {k}: {v}")

        # 读 equity curve
        eq_df = repo.get_equity_curve(args.id)
        if not eq_df.empty:
            print(f"\n  Equity 曲线: {len(eq_df)} 根 bar")
            print(f"    起点: equity={eq_df['equity'].iloc[0]:.2f}")
            print(f"    终点: equity={eq_df['equity'].iloc[-1]:.2f}")
            print(f"    最大回撤: {eq_df['drawdown'].min():.2%}")

    elif args.track_action == "leaderboard":
        df = repo.leaderboard(sort_by=args.sort_by, top=args.top)
        if df.empty:
            print("暂无 experiment。")
            return
        print(f"\n=== Leaderboard (sort_by={args.sort_by}, top={args.top}) ===")
        cols = [
            "id", "name", "strategy",
            "sharpe", "total_return", "max_drawdown",
        ]
        cols = [c for c in cols if c in df.columns]
        print(df[cols].to_string(index=False))

    elif args.track_action == "search":
        df = repo.search(
            strategy=args.strategy,
            sharpe_min=args.sharpe_min,
            max_dd_max=args.max_dd_max,
            return_min=args.return_min,
            tag=args.tag,
            limit=args.limit,
        )
        if df.empty:
            print("无匹配 experiment。")
            return
        print(f"\n=== 搜索结果 (limit={args.limit}) ===")
        cols = [
            "id", "name", "strategy",
            "sharpe", "total_return", "max_drawdown",
        ]
        cols = [c for c in cols if c in df.columns]
        print(df[cols].to_string(index=False))

    elif args.track_action == "delete":
        repo.delete(args.id)
        print(f"已删除 experiment: {args.id}")

    else:
        print("请指定 track 子动作: list / show / leaderboard / search / delete")


# ============================================================
# sub-command: quintile
# ============================================================

def setup_quintile_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--factor-csv", required=True,
        help="因子数据 CSV 路径（index=date, columns=symbol）",
    )
    _setup_pool_args(parser)
    _setup_date_args(parser)
    _setup_output_args(parser)
    parser.add_argument(
        "--n-quantiles", type=int, default=5,
        help="分位数量（默认 5）",
    )
    parser.add_argument(
        "--rebalance-freq", type=int, default=5,
        help="调仓频率（默认 5）",
    )
    parser.add_argument(
        "--long-quantile", type=int, default=None,
        help="做多分位（默认 n_quantiles）",
    )
    parser.add_argument(
        "--short-quantile", type=int, default=None,
        help="做空分位（默认 1）",
    )
    parser.add_argument(
        "--long-direction", default="high",
        choices=["high", "low"],
        help="Q_n 因子值最大 → 多头（默认 high）",
    )
    parser.add_argument(
        "--ic-lag", type=int, default=1,
        help="IC 计算时用未来多少 bar 的收益（默认 1）",
    )
    parser.add_argument(
        "--commission-rate", type=float, default=0.00025,
    )
    parser.add_argument(
        "--slippage-rate", type=float, default=0.0001,
    )
    parser.add_argument(
        "--min-factor-count", type=int, default=10,
        help="单截面最少非空因子值数（默认 10）",
    )
    parser.add_argument(
        "--report-html", action="store_true",
        help="生成 HTML 报告",
    )


def quintile_quantlab_command(args: argparse.Namespace) -> None:
    """多因子 5 分位分层回测。"""
    from src.quantlab_quintile import QuintileExperiment

    # 1) 读因子数据
    factor_path = Path(args.factor_csv)
    if not factor_path.exists():
        print(f"错误: 因子文件不存在: {args.factor_csv}")
        return
    factor_data = pd.read_csv(factor_path, index_col=0, parse_dates=True)
    print(f"  因子数据: {factor_data.shape[0]} 行 x {factor_data.shape[1]} 列")

    # 2) 股票范围
    try:
        stock_codes, _ = _resolve_stock_codes(args)
    except ValueError as e:
        print(f"错误: {e}")
        return

    # 3) 加载价格数据
    try:
        data = _load_quantlab_data(args, stock_codes)
    except ValueError as e:
        print(f"错误: {e}")
        return
    print(f"  价格数据: {len(data)} 个 symbol")

    # 4) 默认 long/short quintile
    long_q = args.long_quantile or args.n_quantiles
    short_q = args.short_quantile if args.short_quantile else None

    # 5) 跑分位实验
    exp = QuintileExperiment(
        n_quantiles=args.n_quantiles,
        rebalance_freq=args.rebalance_freq,
        initial_cash=args.initial_capital,
        commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate,
        long_direction=args.long_direction,
        ic_lag=args.ic_lag,
        factor_name=factor_path.stem,
        min_factor_count=args.min_factor_count,
    )

    print(f"\n=== 多因子分层回测 [{factor_path.stem}] ===")
    print(f"  分位数: {args.n_quantiles}")
    print(f"  调仓频率: 每 {args.rebalance_freq} 根 bar")
    print(f"  long quintile: Q{long_q}, short quintile: Q{short_q}")

    t0 = time.time()
    result = exp.run(
        factor_data=factor_data,
        data=data,
        long_quantile=long_q,
        short_quantile=short_q,
    )
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.1f}s")

    # 6) 输出
    print(f"\n=== 分位结果 ===")
    print(f"{'分位':<8} {'总收益':>10} {'夏普':>8} {'最大回撤':>10}")
    print("-" * 40)
    for q in range(1, args.n_quantiles + 1):
        m = result.quintile_metrics.get(q, {})
        print(
            f"Q{q:<7} "
            f"{m.get('total_return', 0):>9.2%} "
            f"{m.get('sharpe', 0):>8.3f} "
            f"{m.get('max_drawdown', 0):>9.2%}"
        )

    ls_m = result.long_short_metrics
    print(f"\n  多空对冲 ({'Q{} - Q{}'.format(long_q, short_q) if short_q else 'long only'}):")
    print(f"    总收益: {ls_m.get('total_return', 0):.2%}")
    print(f"    夏普:   {ls_m.get('sharpe', 0):.3f}")
    print(f"    最大回撤: {ls_m.get('max_drawdown', 0):.2%}")

    print(f"\n  IC: mean={result.ic_mean:.4f}, std={result.ic_std:.4f}, IR={result.ir:.4f}")

    # 7) 落盘
    output_dir = Path(args.output_dir) / "quintile"
    output_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or f"quintile_{factor_path.stem}_{int(time.time())}"
    out_file = output_dir / f"{name}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "factor": factor_path.stem,
            "n_quantiles": args.n_quantiles,
            "long_quantile": long_q,
            "short_quantile": short_q,
            "quintile_metrics": result.quintile_metrics,
            "long_short_metrics": result.long_short_metrics,
            "ic_mean": result.ic_mean,
            "ic_std": result.ic_std,
            "ir": result.ir,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  结果已保存: {out_file}")


# ============================================================
# setup_quantlab_parser：注册到主 parser
# ============================================================

def setup_quantlab_parser(subparsers) -> None:
    """注册 quantlab 子命令到 argparse。"""
    parser = subparsers.add_parser(
        "quantlab", help="quantlab 回测框架（run/compare/optimize/walkforward/track/quintile）",
    )
    sub = parser.add_subparsers(dest="quantlab_action", help="子动作")

    # run
    p_run = sub.add_parser("run", help="单次回测（多引擎）")
    setup_run_parser(p_run)

    # compare
    p_cmp = sub.add_parser("compare", help="多引擎对比")
    setup_compare_parser(p_cmp)

    # optimize
    p_opt = sub.add_parser("optimize", help="参数网格搜索")
    setup_optimize_parser(p_opt)

    # walkforward
    p_wf = sub.add_parser("walkforward", help="Walk-Forward 验证")
    setup_walkforward_parser(p_wf)

    # track
    p_tk = sub.add_parser("track", help="实验跟踪")
    setup_track_parser(p_tk)

    # quintile
    p_q5 = sub.add_parser("quintile", help="多因子分层回测")
    setup_quintile_parser(p_q5)


def run_quantlab_subcommand(args: argparse.Namespace) -> None:
    """dispatch 到具体子命令。"""
    action = getattr(args, "quantlab_action", None)
    if action is None:
        print("请指定 quantlab 子动作: run / compare / optimize / walkforward / track / quintile")
        print("使用 'python main.py quantlab <subcmd> --help' 查看具体用法")
        return

    dispatch = {
        "run": run_quantlab_command,
        "compare": compare_quantlab_command,
        "optimize": optimize_quantlab_command,
        "walkforward": walkforward_quantlab_command,
        "track": track_quantlab_command,
        "quintile": quintile_quantlab_command,
    }
    fn = dispatch.get(action)
    if fn is None:
        print(f"未知 quantlab 子动作: {action}")
        return
    fn(args)
