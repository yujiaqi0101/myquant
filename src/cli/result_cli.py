"""
回测结果管理 CLI 模块
=====================

提供回测结果列表、查看、导出、删除、HTML报告生成等功能。

子命令：
    python main.py result --list
    python main.py result --show reports/backtest_0001_2024-01-01_2024-12-31
    python main.py result --html reports/backtest_0001_2024-01-01_2024-12-31
"""

import argparse
import json
import shutil
from pathlib import Path


def setup_result_parser(parser: argparse.ArgumentParser) -> None:
    """注册 result 子命令参数。"""
    parser.add_argument("--list", "-l", action="store_true", help="列出已有回测结果")
    parser.add_argument("--show", metavar="RESULT_PATH", help="查看回测结果摘要")
    parser.add_argument("--export", metavar="RESULT_PATH", help="导出回测结果交易记录")
    parser.add_argument("--output", "-o", help="导出文件路径")
    parser.add_argument("--delete", metavar="RESULT_PATH", help="删除回测结果")
    parser.add_argument("--html", metavar="RESULT_PATH", help="生成 HTML 报告")


def run_result_command(args: argparse.Namespace) -> None:
    """执行回测结果管理命令。"""
    reports_dir = Path("reports")

    # 1. 列出所有结果
    if args.list:
        _list_results(reports_dir)
        return

    # 2. 查看结果摘要
    if args.show:
        _show_result(reports_dir, args.show)
        return

    # 3. 导出交易记录
    if args.export:
        _export_result(reports_dir, args.export, args.output)
        return

    # 4. 生成 HTML 报告
    if args.html:
        _generate_html(reports_dir, args.html)
        return

    # 5. 删除结果
    if args.delete:
        _delete_result(reports_dir, args.delete)
        return

    # 无参数时显示帮助
    print("\n回测结果管理命令")
    print("=" * 60)
    print("\n可用选项：")
    print("  --list, -l          列出已有回测结果")
    print("  --show <路径>       查看回测结果摘要")
    print("  --export <路径>     导出交易记录（CSV）")
    print("  --html <路径>       生成 HTML 报告")
    print("  --delete <路径>     删除回测结果")
    print("\n示例：")
    print("  python main.py result --list")
    print("  python main.py result --show reports/backtest_0001_2024-01-01_2024-12-31")
    print("=" * 60)


def _list_results(reports_dir: Path) -> None:
    """列出所有回测结果。"""
    if not reports_dir.exists():
        print("暂无回测结果")
        return

    results = []
    for result_dir in reports_dir.rglob("*"):
        if result_dir.is_dir():
            perf_file = result_dir / "performance.json"
            if perf_file.exists():
                try:
                    with open(perf_file, "r", encoding="utf-8") as f:
                        perf = json.load(f)
                    results.append({
                        "path": str(result_dir),
                        "strategy": perf.get("strategy_name", "unknown"),
                        "start_date": perf.get("start_date", ""),
                        "end_date": perf.get("end_date", ""),
                        "total_return": perf.get("total_return", 0),
                        "sharpe": perf.get("sharpe", perf.get("sharpe_ratio", 0)),
                        "max_dd": perf.get("max_drawdown", 0),
                    })
                except Exception:
                    continue

    if not results:
        print("暂无回测结果")
        return

    print("\n已有回测结果：")
    print("=" * 100)
    print(f"{'策略':<20} {'回测区间':<24} {'总收益':>10} {'夏普':>8} {'最大回撤':>10}")
    print("-" * 100)
    for r in sorted(results, key=lambda x: x["start_date"], reverse=True):
        print(
            f"{r['strategy']:<20} {r['start_date']} ~ {r['end_date']:<10} "
            f"{r['total_return']:>9.2f}% {r['sharpe']:>8.2f} {r['max_dd']:>9.2f}%"
        )
    print("=" * 100)
    print(f"共 {len(results)} 条记录")


def _show_result(reports_dir: Path, name: str) -> None:
    """查看回测结果摘要。"""
    result_path = Path(name)
    if not result_path.exists():
        result_path = reports_dir / name
        if not result_path.exists():
            print(f"错误：找不到回测结果 '{name}'")
            return

    perf_file = result_path / "performance.json"
    if not perf_file.exists():
        print(f"错误：'{name}' 不是有效的回测结果目录")
        return

    with open(perf_file, "r", encoding="utf-8") as f:
        perf = json.load(f)

    print(f"\n【回测结果摘要】")
    print("=" * 60)
    print(f"策略: {perf.get('strategy_name', 'unknown')}")
    print(f"回测区间: {perf.get('start_date', '')} ~ {perf.get('end_date', '')}")
    print(f"初始资金: {perf.get('initial_capital', 0):,.2f}")
    print(f"最终资产: {perf.get('final_equity', perf.get('final_value', 0)):,.2f}")
    print(f"总收益率: {perf.get('total_return', 0):.2f}%")
    print(f"年化收益: {perf.get('annual_return', 0):.2f}%")
    print(f"夏普比率: {perf.get('sharpe', perf.get('sharpe_ratio', 0)):.3f}")
    print(f"最大回撤: {perf.get('max_drawdown', 0):.2f}%")
    print(f"卡尔玛比率: {perf.get('calmar', perf.get('calmar_ratio', 0)):.3f}")
    print(f"胜率: {perf.get('win_rate', 0):.2f}%")
    print(f"交易次数: {perf.get('trade_count', 0)}")
    print(f"交易天数: {perf.get('trading_days', 0)}")
    print(f"基准: {perf.get('benchmark_code', '')}")
    print(f"超额收益: {perf.get('excess_return', 0):.2f}%")
    print(f"Beta: {perf.get('beta', 0):.3f}")
    print(f"Alpha: {perf.get('alpha', 0):.2f}%")
    print(f"信息比率: {perf.get('information_ratio', 0):.3f}")
    print("=" * 60)
    print(f"\n结果路径: {result_path}")


def _export_result(reports_dir: Path, name: str, output: str) -> None:
    """导出交易记录为 CSV。"""
    import pandas as pd

    result_path = Path(name)
    if not result_path.exists():
        result_path = reports_dir / name

    trades_file = result_path / "trades.json"
    if not trades_file.exists():
        print(f"错误：'{name}' 无交易记录")
        return

    with open(trades_file, "r", encoding="utf-8") as f:
        trades = json.load(f)

    output_path = output or "trades_export.csv"
    df = pd.DataFrame(trades)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"交易记录已导出: {output_path} ({len(df)} 条)")


def _generate_html(reports_dir: Path, name: str) -> None:
    """生成 HTML 报告。"""
    result_path = Path(name)
    if not result_path.exists():
        result_path = reports_dir / name

    if not result_path.exists():
        print(f"错误：找不到回测结果 '{name}'")
        return

    try:
        from src.report import generate_html_report
        html_path = generate_html_report(str(result_path))
        print(f"HTML 报告已生成: {html_path}")
    except Exception as e:
        print(f"生成失败: {e}")


def _delete_result(reports_dir: Path, name: str) -> None:
    """删除回测结果。"""
    result_path = Path(name)
    if not result_path.exists():
        result_path = reports_dir / name

    if not result_path.exists():
        print(f"错误：找不到回测结果 '{name}'")
        return

    shutil.rmtree(result_path)
    print(f"已删除: {result_path}")
