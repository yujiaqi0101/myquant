"""
实盘 CLI 模块
==============

基于新版统一引擎 LiveEngine 的实盘命令（占位实现）。

子命令：
    python main.py live run --strategy small_cap --account acc_small_cap_live

实盘特性：
    - 实时行情：LiveDataFeed 订阅实时 bar 推送
    - 实盘下单：LiveExecution 调用券商 API
    - DB 持久化：account_info / account_positions / account_orders / account_fills / account_snapshots
    - 异步事件循环：EventEngine(mode="live")

注意：当前为占位实现，券商 API 适配完成前 live run 仅打印状态。
"""

import argparse


def setup_live_parser(subparsers) -> None:
    """注册 live 子命令及其子动作。

    Args:
        subparsers: 顶层 argparse 的 subparsers 对象
    """
    parser = subparsers.add_parser("live", help="实盘交易（Live Trading）")
    sub = parser.add_subparsers(dest="live_action", help="实盘子动作")

    # run: 启动实盘（占位）
    p_run = sub.add_parser("run", help="启动实盘交易")
    p_run.add_argument("--strategy", required=True, help="策略名")
    p_run.add_argument("--account", required=True, help="账户ID")
    p_run.add_argument("--initial-capital", type=float, default=1_000_000.0, help="初始资金（仅首次创建账户时使用）")

    # status: 查看实盘账户
    sub.add_parser("status", help="查看实盘账户状态")


def run_live_subcommand(args: argparse.Namespace) -> None:
    """分发 live 子动作。"""
    action = getattr(args, "live_action", None)
    if action is None:
        print("用法: python main.py live --help")
        return

    if action == "run":
        _run_run(args)
    elif action == "status":
        _run_status(args)
    else:
        print(f"未知子动作: {action}")


def _run_run(args: argparse.Namespace) -> None:
    """启动实盘交易（占位实现）。"""
    print(f"\n[实盘交易] 当前为占位实现，券商 API 适配尚未完成")
    print(f"  策略: {args.strategy}")
    print(f"  账户: {args.account}")
    print(f"  初始资金: {args.initial_capital:,.2f}")
    print(f"\n  LiveEngine 框架已就绪，等待券商 API 接入后即可启用")
    print(f"  当前可用的实盘准备工作：")
    print(f"    1. 完成券商 API 适配（LiveExecution 实现）")
    print(f"    2. 完成实时行情接入（LiveDataFeed 实现）")
    print(f"    3. 在模拟盘验证策略稳定性后切换为实盘")


def _run_status(args: argparse.Namespace) -> None:
    """查看实盘账户状态（占位）。"""
    print("\n[实盘状态] 当前无实盘账户运行")
    print("  提示：实盘功能待券商 API 适配完成后启用")
