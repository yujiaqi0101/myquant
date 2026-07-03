"""
模拟盘 CLI 模块
================

基于新版统一引擎 PaperEngine 实现的模拟盘命令。

子命令：
    python main.py paper run --strategy small_cap --date 2024-06-28
    python main.py paper status
    python main.py paper positions --account acc_small_cap
    python main.py paper reset --account acc_small_cap
    python main.py paper adjust-cash --account acc_small_cap --amount 500000

模拟盘特性：
    - 每日模式：run_one_day(bar) 由调度器定时调用
    - DB 持久化：account_info / account_positions / account_orders / account_fills / account_snapshots
    - 跨日恢复：load_state 从 DB 读取上日账户状态
    - T+1 撮合：当日订单次日开盘撮合（next_open 价类型）
"""

import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional


def _get_db_path() -> str:
    """获取数据库路径。"""
    return str(Path(__file__).parent.parent.parent / "data" / "aquant.db")


def setup_paper_parser(subparsers) -> None:
    """注册 paper 子命令及其子动作。

    Args:
        subparsers: 顶层 argparse 的 subparsers 对象
    """
    parser = subparsers.add_parser("paper", help="模拟盘（Paper Trading）")
    sub = parser.add_subparsers(dest="paper_action", help="模拟盘子动作")

    # run: 执行单日模拟交易
    p_run = sub.add_parser("run", help="执行单日模拟交易")
    p_run.add_argument("--strategy", required=True, help="策略名（如 small_cap）")
    p_run.add_argument("--date", default=None, help="交易日 YYYY-MM-DD（默认今天）")
    p_run.add_argument("--account", default=None, help="账户ID（默认 acc_<strategy>）")
    p_run.add_argument("--initial-capital", type=float, default=1_000_000.0, help="初始资金（仅首次创建账户时使用）")
    p_run.add_argument("--no-risk-check", action="store_true", help="禁用 A 股风控")

    # status: 查看所有账户状态
    sub.add_parser("status", help="查看所有模拟盘账户状态")

    # positions: 查看账户持仓
    p_pos = sub.add_parser("positions", help="查看账户持仓明细")
    p_pos.add_argument("--account", required=True, help="账户ID")

    # reset: 清空账户历史
    p_reset = sub.add_parser("reset", help="清空模拟盘账户历史")
    p_reset.add_argument("--account", required=True, help="账户ID")
    p_reset.add_argument("--yes", action="store_true", help="跳过确认提示")

    # adjust-cash: 调整账户现金
    p_cash = sub.add_parser("adjust-cash", help="调整账户现金（充值/提取）")
    p_cash.add_argument("--account", required=True, help="账户ID")
    p_cash.add_argument("--amount", required=True, type=float, help="金额（正=充值，负=提取）")


def run_paper_subcommand(args: argparse.Namespace) -> None:
    """分发 paper 子动作。"""
    action = getattr(args, "paper_action", None)
    if action is None:
        print("用法: python main.py paper --help")
        return

    dispatch = {
        "run": _run_run,
        "status": _run_status,
        "positions": _run_positions,
        "reset": _run_reset,
        "adjust-cash": _run_adjust_cash,
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
    """执行单日模拟交易。"""
    # 延迟导入
    import src.strategies  # noqa: F401 触发 auto_discover
    from src.core.engine import PaperEngine
    from src.core.events import BarEvent
    from src.core.strategy import get_strategy_class, list_strategies
    from src.data.database import DatabaseManager
    from src.risk_checks.factory import build_ashare_risk_manager

    # 1. 取策略类
    strategy_class = get_strategy_class(args.strategy)
    if strategy_class is None:
        print(f"错误：未知策略 '{args.strategy}'")
        print(f"可用策略: {', '.join(list_strategies())}")
        return

    # 2. 确定账户ID和交易日
    account_id = args.account or f"acc_{args.strategy}"
    trade_date = args.date or datetime.now().strftime("%Y-%m-%d")

    # 3. 实例化策略与数据库
    strategy = strategy_class(params={})
    db = DatabaseManager(_get_db_path())

    # 4. 风控
    risk_manager = None if args.no_risk_check else build_ashare_risk_manager()

    # 5. 构造 PaperEngine（每日模式 datafeed=None）
    engine = PaperEngine(
        strategy=strategy,
        db=db,
        account_id=account_id,
        initial_capital=args.initial_capital,
        datafeed=None,
        risk_manager=risk_manager,
    )

    # 6. 从 DB 读取当日 bar（全市场收盘价）
    bar = _load_daily_bar(db, trade_date)
    if bar is None:
        print(f"错误：交易日 {trade_date} 无数据，请检查 t_stock_daily 表")
        return

    # 7. 运行单日
    print(f"\n运行模拟盘 [策略={args.strategy}, 账户={account_id}, 日期={trade_date}]...")
    try:
        engine.run_one_day(bar)
        print(f"  单日运行完成")
    finally:
        engine.stop()

    # 8. 打印账户摘要
    acct = engine.portfolio.get_account()
    print(f"\n账户摘要:")
    print(f"  现金: {acct.cash:,.2f}")
    print(f"  冻结: {acct.frozen:,.2f}")
    print(f"  持仓市值: {acct.market_value:,.2f}")
    print(f"  总资产: {acct.total:,.2f}")
    print(f"  当日盈亏: {acct.daily_pnl:,.2f} ({acct.daily_pnl_pct:.2%})")


def _run_status(args: argparse.Namespace) -> None:
    """查看所有模拟盘账户状态。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    # 直接查 account_info 表
    import sqlite3
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("SELECT * FROM account_info ORDER BY account_id")
        rows = [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

    if not rows:
        print("\n暂无模拟盘账户")
        print("提示：运行 'python main.py paper run --strategy small_cap' 初始化账户")
        return

    print("\n" + "=" * 100)
    print(f"{'账户ID':<24} {'策略名':<20} {'初始资金':>14} {'当前现金':>14} {'总资产':>14} {'更新时间'}")
    print("-" * 100)
    for r in rows:
        print(
            f"{r.get('account_id', ''):<24} {r.get('strategy_name', ''):<20} "
            f"{r.get('initial_capital', 0):>14.2f} {r.get('cash', 0):>14.2f} "
            f"{r.get('total', 0):>14.2f} {r.get('updated_at', '')}"
        )
    print("=" * 100)


def _run_positions(args: argparse.Namespace) -> None:
    """查看账户持仓明细。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    # 取账户信息
    acct = repo.load_account_info(args.account)
    if acct is None:
        print(f"错误：账户 '{args.account}' 不存在")
        return

    # 取持仓
    positions = repo.load_positions(args.account)

    print(f"\n账户: {args.account}  策略: {acct.get('strategy_name', '')}")
    print(f"现金: {acct.get('cash', 0):,.2f}  总资产: {acct.get('total', 0):,.2f}")

    if not positions:
        print("\n当前无持仓")
        return

    print("\n" + "=" * 100)
    print(f"{'股票代码':<14} {'持仓数':>12} {'开仓价':>12} {'现价':>12} {'市值':>14}")
    print("-" * 100)
    for sym, pos in positions.items():
        value = pos.quantity * pos.current_price
        print(
            f"{sym:<14} {pos.quantity:>12} {pos.entry_price:>12.2f} "
            f"{pos.current_price:>12.2f} {value:>14.2f}"
        )
    print("=" * 100)


def _run_reset(args: argparse.Namespace) -> None:
    """清空模拟盘账户历史。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    if not args.yes:
        confirm = input(f"确认清空账户 '{args.account}' 的全部历史？(y/N): ")
        if confirm.lower() != "y":
            print("已取消")
            return

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)
    repo.delete_account(args.account)
    print(f"已删除账户 '{args.account}' 的全部历史")


def _run_adjust_cash(args: argparse.Namespace) -> None:
    """调整账户现金（充值/提取）。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    acct = repo.load_account_info(args.account)
    if acct is None:
        print(f"错误：账户 '{args.account}' 不存在")
        return

    new_cash = acct.get("cash", 0) + args.amount
    if new_cash < 0:
        print(f"错误：提取金额超过可用现金（当前 {acct.get('cash', 0):.2f}）")
        return

    # 更新账户信息
    repo.save_account_info(
        account_id=args.account,
        strategy_name=acct.get("strategy_name", ""),
        initial_capital=acct.get("initial_capital", 0),
        cash=new_cash,
        frozen=acct.get("frozen", 0),
        market_value=acct.get("market_value", 0),
        total=acct.get("total", 0) + args.amount,
    )

    action = "充值" if args.amount >= 0 else "提取"
    print(
        f"已{action} {abs(args.amount):.2f} 元"
        f" → 当前现金: {new_cash:.2f}  总资产: {acct.get('total', 0) + args.amount:.2f}"
    )


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------


def _load_daily_bar(db, trade_date: str) -> Optional[object]:
    """从 DB 加载单日全市场 bar，构造 BarEvent。

    Args:
        db: DatabaseManager 实例
        trade_date: 交易日 YYYY-MM-DD

    Returns:
        BarEvent 或 None（无数据时）
    """
    from src.core.events import BarEvent

    # 从 t_stock_daily 读取当日全市场数据
    df = db.get_stock_daily(start_date=trade_date, end_date=trade_date)
    if df.empty:
        return None

    # 构造 symbols_bars: {symbol: {open/high/low/close/volume}}
    symbols_bars = {}
    for _, row in df.iterrows():
        sym = row.get("stock_code") or row.get("symbol")
        if not sym:
            continue
        symbols_bars[sym] = {
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "close": float(row.get("close", 0)),
            "volume": float(row.get("volume", 0)),
        }

    if not symbols_bars:
        return None

    # 构造 BarEvent
    # BarEvent 单 symbol 字段保留为空（引擎使用 extra["symbols_bars"] 处理全市场）
    ts = datetime.strptime(trade_date, "%Y-%m-%d")
    return BarEvent(
        timestamp=ts,
        symbol="",
        extra={"trade_date": trade_date, "symbols_bars": symbols_bars},
    )
