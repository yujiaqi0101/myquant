"""
模拟交易 CLI 子命令

提供以下子动作（嵌套子命令模式，参考 quantlab_cli.py）：
    python main.py paper run [--date YYYY-MM-DD] [--strategy NAME] [--price-type close|next_open]
    python main.py paper status
    python main.py paper positions --strategy NAME
    python main.py paper reset [--strategy NAME]
    python main.py paper adjust-cash --strategy NAME --amount N

输出统一使用 print + f-string 表格（项目不依赖 Rich）。
"""

import argparse
from pathlib import Path
from typing import Optional


def _get_db_path() -> str:
    """获取数据库路径（与 backtest_cli 保持一致）"""
    return str(Path(__file__).parent.parent.parent / 'data' / 'aquant.db')


def setup_paper_parser(subparsers) -> None:
    """注册 paper 子命令及其子动作"""
    parser = subparsers.add_parser('paper', help='模拟交易（Paper Trading）')
    sub = parser.add_subparsers(dest='paper_action', help='模拟交易子动作')

    # run: 执行每日模拟交易
    p_run = sub.add_parser('run', help='执行每日模拟交易')
    p_run.add_argument('--date', default=None, help='交易日 (YYYY-MM-DD)，默认今天')
    p_run.add_argument('--strategy', default=None, help='只运行指定策略（默认全部活跃策略）')
    p_run.add_argument('--price-type', default='close', choices=['close', 'next_open'],
                       help='撮合价格模式（默认 close）')

    # status: 查看所有策略账户状态
    sub.add_parser('status', help='查看所有策略账户状态')

    # positions: 查看特定策略持仓
    p_pos = sub.add_parser('positions', help='查看特定策略持仓明细')
    p_pos.add_argument('--strategy', required=True, help='策略名或策略ID')

    # reset: 清空模拟交易历史
    p_reset = sub.add_parser('reset', help='清空模拟交易历史')
    p_reset.add_argument('--strategy', default=None, help='只清空指定策略（默认全部）')
    p_reset.add_argument('--yes', action='store_true', help='跳过确认提示')

    # adjust-cash: 手动调整账户现金
    p_cash = sub.add_parser('adjust-cash', help='手动调整账户现金（充值/提取）')
    p_cash.add_argument('--strategy', required=True, help='策略名或策略ID')
    p_cash.add_argument('--amount', required=True, type=float, help='金额（正=充值，负=提取）')


def run_paper_subcommand(args: argparse.Namespace) -> None:
    """分发 paper 子动作"""
    action = getattr(args, 'paper_action', None)
    if action is None:
        print("用法: python main.py paper --help")
        return

    dispatch = {
        'run': _run_run,
        'status': _run_status,
        'positions': _run_positions,
        'reset': _run_reset,
        'adjust-cash': _run_adjust_cash,
    }
    fn = dispatch.get(action)
    if fn is None:
        print(f"未知子动作: {action}")
        return
    fn(args)


# ----------------------------------------------------------------------
# 子动作实现
# ----------------------------------------------------------------------

def _run_run(args: argparse.Namespace) -> None:
    """执行每日模拟交易"""
    from src.paper_trading.orchestrator import PaperTradingOrchestrator
    from datetime import datetime

    trade_date = args.date or datetime.now().strftime('%Y-%m-%d')
    orch = PaperTradingOrchestrator(
        db_path=_get_db_path(),
        price_type=args.price_type,
    )
    orch.run_daily_process(trade_date, strategy_name=args.strategy)


def _run_status(args: argparse.Namespace) -> None:
    """查看所有策略账户状态"""
    from src.data.database import DatabaseManager
    db = DatabaseManager(_get_db_path())
    accounts = db.get_all_paper_accounts()

    if not accounts:
        print("\n暂无模拟交易账户")
        print("提示：运行 'python main.py paper run --date YYYY-MM-DD' 初始化账户")
        return

    print("\n" + "=" * 110)
    print(f"{'策略名':<20} {'版本':<8} {'初始资金':>14} {'可用现金':>14} {'冻结资金':>12} {'持仓市值':>14} {'总资产':>14}")
    print("-" * 110)

    for acc in accounts:
        position_value = acc['total_value'] - acc['cash'] - acc['frozen_cash']
        print(
            f"{acc['strategy_name']:<20} {acc['version']:<8} "
            f"{acc['initial_capital']:>14.2f} {acc['cash']:>14.2f} "
            f"{acc['frozen_cash']:>12.2f} {position_value:>14.2f} {acc['total_value']:>14.2f}"
        )

    print("=" * 110)

    # 显示最近一日收益率与最大回撤
    print("\n最近净值快照：")
    print("-" * 80)
    print(f"{'策略名':<20} {'最近交易日':<14} {'总资产':>14} {'日收益率':>10} {'最大回撤':>10}")
    print("-" * 80)
    for acc in accounts:
        snapshots = db.get_paper_snapshots(acc['strategy_id'])
        if snapshots:
            last = snapshots[-1]
            print(
                f"{acc['strategy_name']:<20} {last['trade_date']:<14} "
                f"{last['total_value']:>14.2f} {last['daily_return']:>9.2%} {last['max_drawdown']:>9.2%}"
            )
        else:
            print(f"{acc['strategy_name']:<20} {'(无快照)':<14}")
    print("-" * 80)


def _run_positions(args: argparse.Namespace) -> None:
    """查看特定策略持仓明细"""
    from src.data.database import DatabaseManager
    db = DatabaseManager(_get_db_path())

    strategy_id = _resolve_strategy_id(db, args.strategy)
    if strategy_id is None:
        print(f"未找到策略 '{args.strategy}'")
        return

    account = db.get_paper_account(strategy_id)
    if account is None:
        print(f"策略 '{args.strategy}' 无模拟交易账户")
        return

    positions = db.get_paper_positions(strategy_id)

    print(f"\n策略: {account['strategy_name']} ({account['version']})")
    print(f"可用现金: {account['cash']:.2f}  冻结资金: {account['frozen_cash']:.2f}  总资产: {account['total_value']:.2f}")

    if not positions:
        print("\n当前无持仓")
        return

    print("\n" + "=" * 100)
    print(f"{'股票代码':<14} {'方向':<8} {'持仓数':>10} {'开仓价':>10} {'现价':>10} {'市值':>14} {'浮动盈亏':>14}")
    print("-" * 100)

    total_value = 0.0
    total_pnl = 0.0
    for pos in positions:
        pnl = (pos['current_price'] - pos['entry_price']) * pos['quantity']
        total_value += pos['value']
        total_pnl += pnl
        pnl_str = f"{pnl:>+13.2f}" if pnl >= 0 else f"{pnl:>+13.2f}"
        print(
            f"{pos['stock_code']:<14} {pos['direction']:<8} {pos['quantity']:>10} "
            f"{pos['entry_price']:>10.2f} {pos['current_price']:>10.2f} "
            f"{pos['value']:>14.2f} {pnl_str}"
        )

    print("-" * 100)
    print(f"{'合计':<14} {'':<8} {'':>10} {'':>10} {'':>10} {total_value:>14.2f} {total_pnl:>+13.2f}")
    print("=" * 100)


def _run_reset(args: argparse.Namespace) -> None:
    """清空模拟交易历史"""
    from src.data.database import DatabaseManager
    db = DatabaseManager(_get_db_path())

    strategy_id = None
    if args.strategy:
        strategy_id = _resolve_strategy_id(db, args.strategy)
        if strategy_id is None:
            print(f"未找到策略 '{args.strategy}'")
            return

    # 确认提示
    if not args.yes:
        target = f"策略 '{args.strategy}'" if strategy_id else "全部策略"
        confirm = input(f"确认清空 {target} 的模拟交易历史？(y/N): ")
        if confirm.lower() != 'y':
            print("已取消")
            return

    db.reset_paper_trading(strategy_id)
    print("模拟交易历史已清空")


def _run_adjust_cash(args: argparse.Namespace) -> None:
    """手动调整账户现金"""
    from src.data.database import DatabaseManager
    db = DatabaseManager(_get_db_path())

    strategy_id = _resolve_strategy_id(db, args.strategy)
    if strategy_id is None:
        print(f"未找到策略 '{args.strategy}'")
        return

    result = db.adjust_paper_cash(strategy_id, args.amount)
    if result is None:
        print(f"调整失败：账户不存在或提取金额超过可用现金")
    else:
        action = "充值" if args.amount >= 0 else "提取"
        print(
            f"已{action} {abs(args.amount):.2f} 元"
            f" → 当前可用现金: {result['cash']:.2f}  总资产: {result['total_value']:.2f}"
        )


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------

def _resolve_strategy_id(db, strategy: str) -> Optional[str]:
    """
    将策略名或策略ID解析为 strategy_id。

    优先匹配 paper_accounts.strategy_name，其次匹配 strategy_id 本身。
    """
    # 先匹配已存在的模拟账户
    accounts = db.get_all_paper_accounts()
    for acc in accounts:
        if acc['strategy_id'] == strategy or acc['strategy_name'] == strategy:
            return acc['strategy_id']

    # 再匹配活跃策略
    active = db.get_active_strategies()
    if not active.empty:
        for _, row in active.iterrows():
            if row['strategy_id'] == strategy or row['strategy_name'] == strategy:
                return row['strategy_id']

    return None
