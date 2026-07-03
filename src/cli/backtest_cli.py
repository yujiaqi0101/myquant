"""
回测 CLI 模块
=============

提供基于新版统一引擎（src/core）的回测命令。

子命令：
    python main.py backtest --strategy small_cap --start-date 2024-01-01 --end-date 2024-06-30

回测引擎：BacktestEngine（事件驱动内核）
数据来源：本地 SQLite 数据库（t_stock_daily / t_index_daily）
风控管线：build_ashare_risk_manager（A 股法定风控 11 个 Check）

输出：
    - 控制台绩效摘要
    - reports/backtest_<log_id>_<start>_<end>/performance.json
    - reports/backtest_<log_id>_<start>_<end>/trades.json
    - reports/backtest_<log_id>_<start>_<end>/snapshots.json
    - HTML 报告（可选）
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def setup_backtest_parser(parser: argparse.ArgumentParser) -> None:
    """注册 backtest 子命令参数。"""
    # 策略（必需）
    parser.add_argument(
        "--strategy", "-s",
        required=True,
        help="策略名称（通过 strategy --list 查看可用策略）",
    )
    # 时间范围
    parser.add_argument(
        "--start-date",
        default="2024-01-01",
        help="回测开始日期 YYYY-MM-DD（默认 2024-01-01）",
    )
    parser.add_argument(
        "--end-date",
        default="2024-12-31",
        help="回测结束日期 YYYY-MM-DD（默认 2024-12-31）",
    )
    # 资金
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=1_000_000.0,
        help="初始资金（默认 1,000,000）",
    )
    # 基准
    parser.add_argument(
        "--benchmark",
        default="000300.SH",
        help="基准指数代码（默认 000300.SH 沪深300）",
    )
    # 风控
    parser.add_argument(
        "--no-risk-check",
        action="store_true",
        help="禁用 A 股风控（涨跌停/ST/T+1/新股/停牌 + 组合级检查）",
    )
    parser.add_argument(
        "--max-position-pct",
        type=float,
        default=0.30,
        help="单持仓仓位上限（默认 0.30）",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=10,
        help="最多持仓股票数（默认 10）",
    )
    parser.add_argument(
        "--daily-stop-loss",
        type=float,
        default=-0.05,
        help="日亏急停阈值（默认 -0.05 即亏损 5%% 急停）",
    )
    # 策略参数（自由 KV，传给策略 params）
    parser.add_argument(
        "--param",
        action="append",
        metavar="KEY=VALUE",
        default=[],
        help="策略参数，可多次指定，如 --param top_n=5 --param rebalance_at=month_start",
    )
    # 输出
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="报告输出目录（默认 reports）",
    )
    parser.add_argument(
        "--name",
        default="",
        help="报告名称（默认自动生成）",
    )


def _get_db_path() -> str:
    """获取数据库路径。"""
    return str(Path(__file__).parent.parent.parent / "data" / "aquant.db")


def _parse_strategy_params(param_list) -> Dict[str, Any]:
    """解析 --param KEY=VALUE 列表为字典。

    自动尝试将值转为 int/float/bool，失败则保留字符串。
    """
    params: Dict[str, Any] = {}
    for item in param_list:
        if "=" not in item:
            logger.warning("忽略无效参数（缺少=）：%s", item)
            continue
        key, raw_value = item.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        # 尝试类型转换
        try:
            if "." in raw_value:
                params[key] = float(raw_value)
            else:
                params[key] = int(raw_value)
        except ValueError:
            if raw_value.lower() in ("true", "false"):
                params[key] = raw_value.lower() == "true"
            else:
                params[key] = raw_value
    return params


def run_backtest_command(args: argparse.Namespace) -> None:
    """执行回测命令。"""
    # 延迟导入，避免顶层依赖
    from src.core.engine import BacktestEngine
    from src.core.strategy import get_strategy_class, list_strategies
    from src.data.database import DatabaseManager
    from src.risk_checks.factory import build_ashare_risk_manager

    # 1. 解析策略参数
    strategy_params = _parse_strategy_params(args.param)

    # 2. 取策略类（依赖 src.strategies 包导入时自动注册）
    strategy_class = get_strategy_class(args.strategy)
    if strategy_class is None:
        print(f"错误：未知策略 '{args.strategy}'")
        print(f"可用策略: {', '.join(list_strategies())}")
        return

    # 3. 实例化策略
    strategy = strategy_class(params=strategy_params)

    # 4. 数据库管理器
    db = DatabaseManager(_get_db_path())

    # 5. 风控管理器
    if args.no_risk_check:
        risk_manager = None
        print("[警告] 已禁用 A 股风控，回测结果仅供参考")
    else:
        risk_manager = build_ashare_risk_manager(
            max_position_pct=args.max_position_pct,
            max_positions=args.max_positions,
            daily_stop_loss=args.daily_stop_loss,
        )

    # 6. 构造引擎
    engine = BacktestEngine(
        strategy=strategy,
        db=db,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        benchmark_code=args.benchmark,
        risk_manager=risk_manager,
        config={"strategy_params": strategy_params},
    )

    # 7. 运行回测
    print(f"\n开始回测 [策略={args.strategy}, 区间={args.start_date} ~ {args.end_date}]...")
    import time
    t0 = time.time()
    result = engine.run()
    elapsed = time.time() - t0
    print(f"  回测耗时: {elapsed:.1f}s")

    if not result.ok():
        print(f"[错误] 回测失败: {result.error}")
        return

    # 8. 打印绩效摘要
    print(result.to_summary())

    # 9. 持久化结果到 reports 目录
    _save_backtest_result(
        result=result,
        strategy_name=args.strategy,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        output_dir=args.output_dir,
        name=args.name,
        extra_info={"strategy_params": strategy_params},
    )


def _save_backtest_result(
    result: Any,
    strategy_name: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    output_dir: str,
    name: str,
    extra_info: Optional[Dict[str, Any]] = None,
) -> None:
    """保存回测结果到 reports 目录，并写执行日志。"""
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())

    # 写执行日志（获取 log_id）
    log_id = db.log_execution(
        execution_type="backtest",
        factor_name=strategy_name,
        start_date=start_date,
        end_date=end_date,
        n_stocks=0,
        total_return=result.total_return,
        annual_return=result.annual_return,
        sharpe_ratio=result.sharpe,
        max_drawdown=result.max_drawdown,
        win_rate=result.win_rate,
        calmar_ratio=result.calmar,
        volatility=0.0,
        params_json=json.dumps(extra_info or {}, ensure_ascii=False),
    )

    # 创建报告目录
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    if name:
        report_name = name
    else:
        report_name = f"backtest_{log_id:04d}_{start_date}_{end_date}"
    result_dir = output_root / report_name
    result_dir.mkdir(parents=True, exist_ok=True)

    # 保存绩效
    perf_data = {
        "log_id": log_id,
        "strategy_name": strategy_name,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "final_equity": result.final_equity,
        "total_return": result.total_return,
        "annual_return": result.annual_return,
        "sharpe": result.sharpe,
        "calmar": result.calmar,
        "max_drawdown": result.max_drawdown,
        "win_rate": result.win_rate,
        "trade_count": result.trade_count,
        "trading_days": result.trading_days,
        "benchmark_code": result.benchmark_code,
        "excess_return": result.excess_return,
        "beta": result.beta,
        "alpha": result.alpha,
        "information_ratio": result.information_ratio,
        **(extra_info or {}),
    }
    with open(result_dir / "performance.json", "w", encoding="utf-8") as f:
        json.dump(perf_data, f, indent=2, ensure_ascii=False)

    # 保存交易记录
    trades_data = []
    for t in result.trades:
        # Trade 对象可能为 dataclass 或 dict，统一处理
        if hasattr(t, "__dict__"):
            t_dict = {
                k: (v.strftime("%Y-%m-%d %H:%M:%S") if hasattr(v, "strftime") else v)
                for k, v in t.__dict__.items()
            }
        elif isinstance(t, dict):
            t_dict = dict(t)
        else:
            t_dict = {"repr": repr(t)}
        trades_data.append(t_dict)
    with open(result_dir / "trades.json", "w", encoding="utf-8") as f:
        json.dump(trades_data, f, indent=2, ensure_ascii=False, default=str)

    # 保存净值曲线
    snapshots_data = []
    for ts, value in result.equity_curve:
        ts_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)
        snapshots_data.append({"date": ts_str, "total_value": float(value)})
    with open(result_dir / "snapshots.json", "w", encoding="utf-8") as f:
        json.dump(snapshots_data, f, indent=2, ensure_ascii=False)

    # 生成 HTML 报告（可选）
    try:
        from src.report import generate_html_report
        html_path = generate_html_report(str(result_dir))
        print(f"\n  HTML报告: {html_path}")
    except Exception as e:
        print(f"\n  HTML报告生成失败: {e}")

    print(f"\n回测完成！")
    print(f"  日志ID: {log_id}")
    print(f"  报告目录: {result_dir}")
