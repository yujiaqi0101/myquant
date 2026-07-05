"""
模拟盘 CLI 模块（多策略子账户版）
================================

基于新版统一引擎 PaperEngine 实现的模拟盘命令，支持多策略子账户。

设计要点：
    - 主账户独立创建（init），可跨策略共享
    - 资金二级分配：先充值到主账户（deposit），再分配给子账户（add-strategy）
    - 子账户停用而非删除（disable-strategy），保留历史可查询
    - 一个主账户可同时运行多个策略，每个策略对应一个子账户

子命令分组：
    主账户管理：
        init              创建主账户
        deposit           主账户充值
        withdraw          主账户提取
        list-accounts     列出所有主账户

    子账户策略管理：
        add-strategy      为主账户添加策略子账户（含资金分配）
        remove-strategy   彻底删除子账户（含历史数据，资金回收）
        disable-strategy  停用子账户（保留历史，停止运行）
        enable-strategy   启用已停用的子账户
        list-strategies   列出主账户下的全部子账户

    运行与查询：
        run               执行单日模拟交易
        status            查看账户状态（主账户 + 子账户汇总）
        positions         查看持仓明细
        reset             重置子账户（清空历史，资金回到初始）
        adjust-cash       调整子账户资金（追加或回收）

典型流程：
    # 1. 创建主账户，充值 100 万
    python main.py paper init --account acc_001 --capital 1000000
    python main.py paper deposit --account acc_001 --amount 500000

    # 2. 添加两个策略子账户，各分配 30 万
    python main.py paper add-strategy --account acc_001 --strategy small_cap --capital 300000
    python main.py paper add-strategy --account acc_001 --strategy pb_roe --capital 300000

    # 3. 运行策略
    python main.py paper run --account acc_001 --strategy small_cap --date 2024-06-28

    # 4. 查看状态
    python main.py paper status --account acc_001
    python main.py paper list-strategies --account acc_001
    python main.py paper positions --account acc_001 --strategy small_cap
"""

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


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
            continue
        key, raw_value = item.split("=", 1)
        key = key.strip()
        if not key:
            continue
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


def setup_paper_parser(subparsers) -> None:
    """注册 paper 子命令及其子动作。

    Args:
        subparsers: 顶层 argparse 的 subparsers 对象
    """
    parser = subparsers.add_parser("paper", help="模拟盘（Paper Trading，多策略子账户）")
    sub = parser.add_subparsers(dest="paper_action", help="模拟盘子动作")

    # ----- 主账户管理 -----
    p_init = sub.add_parser("init", help="创建主账户（不绑定策略）")
    p_init.add_argument("--account", required=True, help="主账户ID（自定义，唯一）")
    p_init.add_argument("--capital", type=float, required=True, help="初始资金")

    p_deposit = sub.add_parser("deposit", help="主账户充值")
    p_deposit.add_argument("--account", required=True, help="主账户ID")
    p_deposit.add_argument("--amount", type=float, required=True, help="充值金额（正数）")

    p_withdraw = sub.add_parser("withdraw", help="主账户提取（仅限未分配现金）")
    p_withdraw.add_argument("--account", required=True, help="主账户ID")
    p_withdraw.add_argument("--amount", type=float, required=True, help="提取金额（正数）")

    sub.add_parser("list-accounts", help="列出所有主账户")

    # ----- 子账户策略管理 -----
    p_add = sub.add_parser("add-strategy", help="添加策略子账户（含资金分配）")
    p_add.add_argument("--account", required=True, help="主账户ID")
    p_add.add_argument("--strategy", required=True, help="策略名（如 small_cap）")
    p_add.add_argument("--capital", type=float, required=True, help="分配给该子账户的资金")

    p_rm = sub.add_parser("remove-strategy", help="彻底删除子账户（含历史数据，资金回收主账户）")
    p_rm.add_argument("--account", required=True, help="主账户ID")
    p_rm.add_argument("--strategy", required=True, help="子账户策略名")
    p_rm.add_argument("--yes", action="store_true", help="跳过确认提示")

    p_dis = sub.add_parser("disable-strategy", help="停用子账户（保留历史，停止运行）")
    p_dis.add_argument("--account", required=True, help="主账户ID")
    p_dis.add_argument("--strategy", required=True, help="子账户策略名")

    p_en = sub.add_parser("enable-strategy", help="启用已停用的子账户")
    p_en.add_argument("--account", required=True, help="主账户ID")
    p_en.add_argument("--strategy", required=True, help="子账户策略名")

    p_ls = sub.add_parser("list-strategies", help="列出主账户下的全部子账户")
    p_ls.add_argument("--account", required=True, help="主账户ID")
    p_ls.add_argument("--all", action="store_true", help="包含已停用的子账户")

    # ----- 运行与查询 -----
    p_run = sub.add_parser("run", help="执行单日模拟交易（不指定 --strategy 时运行该账户下所有启用的子账户）")
    p_run.add_argument("--account", required=True, help="主账户ID")
    p_run.add_argument("--strategy", default=None,
                       help="子账户策略名（省略时运行该账户下所有启用的子账户）")
    p_run.add_argument("--date", default=None, help="交易日 YYYY-MM-DD（默认今天）")
    p_run.add_argument("--initial-capital", type=float, default=1_000_000.0,
                       help="子账户初始资金（仅 --auto-create 创建新子账户时使用）")
    p_run.add_argument("--no-risk-check", action="store_true", help="禁用 A 股风控")
    p_run.add_argument("--auto-create", action="store_true",
                       help="子账户不存在时自动创建（需指定 --strategy 和 --initial-capital）")
    p_run.add_argument(
        "--param",
        action="append",
        metavar="KEY=VALUE",
        default=[],
        help="策略参数，可多次指定，如 --param symbol=600519.SH --param action=buy",
    )

    p_rr = sub.add_parser("run-range", help="批量执行区间内每日模拟交易")
    p_rr.add_argument("--account", required=True, help="主账户ID")
    p_rr.add_argument("--strategy", default=None,
                      help="子账户策略名（省略时运行该账户下所有启用的子账户）")
    p_rr.add_argument("--start-date", required=True, help="起始日期 YYYY-MM-DD")
    p_rr.add_argument("--end-date", required=True, help="结束日期 YYYY-MM-DD") 
    p_rr.add_argument("--no-risk-check", action="store_true", help="禁用 A 股风控")
    p_rr.add_argument(
        "--param",
        action="append",
        metavar="KEY=VALUE",
        default=[],
        help="策略参数，可多次指定，如 --param symbol=600519.SH --param action=buy",
    )

    p_status = sub.add_parser("status", help="查看账户状态")
    p_status.add_argument("--account", default=None, help="主账户ID（不指定则显示全部）")

    p_pos = sub.add_parser("positions", help="查看持仓明细")
    p_pos.add_argument("--account", required=True, help="主账户ID")
    p_pos.add_argument("--strategy", default=None, help="仅查看指定子账户（不指定则合并全部子账户）")

    p_trades = sub.add_parser("trades", help="查看成交记录")
    p_trades.add_argument("--account", required=True, help="主账户ID")
    p_trades.add_argument("--strategy", default=None, help="仅查看指定子账户（不指定则显示全部）")
    p_trades.add_argument("--start-date", default=None, help="起始日期 YYYY-MM-DD")
    p_trades.add_argument("--end-date", default=None, help="结束日期 YYYY-MM-DD")
    p_trades.add_argument("--limit", type=int, default=200, help="最多显示条数（默认 200）")

    p_reset = sub.add_parser("reset", help="重置子账户（清空历史，资金回到初始）")
    p_reset.add_argument("--account", required=True, help="主账户ID")
    p_reset.add_argument("--strategy", required=True, help="子账户策略名")
    p_reset.add_argument("--capital", type=float, default=None, help="重置后的资金（默认用原分配资金）")
    p_reset.add_argument("--yes", action="store_true", help="跳过确认提示")

    p_cash = sub.add_parser("adjust-cash", help="调整子账户资金（正=追加分配，负=回收）")
    p_cash.add_argument("--account", required=True, help="主账户ID")
    p_cash.add_argument("--strategy", required=True, help="子账户策略名")
    p_cash.add_argument("--amount", type=float, required=True, help="金额（正=追加，负=回收）")


def run_paper_subcommand(args: argparse.Namespace) -> None:
    """分发 paper 子动作。"""
    action = getattr(args, "paper_action", None)
    if action is None:
        print("用法: python main.py paper --help")
        return

    dispatch = {
        # 主账户管理
        "init": _run_init,
        "deposit": _run_deposit,
        "withdraw": _run_withdraw,
        "list-accounts": _run_list_accounts,
        # 子账户策略管理
        "add-strategy": _run_add_strategy,
        "remove-strategy": _run_remove_strategy,
        "disable-strategy": _run_disable_strategy,
        "enable-strategy": _run_enable_strategy,
        "list-strategies": _run_list_strategies,
        # 运行与查询
        "run": _run_run,
        "run-range": _run_run_range,
        "status": _run_status,
        "positions": _run_positions,
        "trades": _run_trades,
        "reset": _run_reset,
        "adjust-cash": _run_adjust_cash,
    }
    fn = dispatch.get(action)
    if fn is None:
        print(f"未知子动作: {action}")
        return
    fn(args)


# ----------------------------------------------------------------------
# 主账户管理
# ----------------------------------------------------------------------


def _run_init(args: argparse.Namespace) -> None:
    """创建主账户。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    ok = repo.init_main_account(args.account, args.capital)
    if ok:
        print(f"主账户创建成功: account={args.account}  初始资金={args.capital:,.2f}")
        print(f"提示：使用 'paper add-strategy' 添加策略子账户")
    else:
        print(f"错误：主账户 '{args.account}' 已存在")


def _run_deposit(args: argparse.Namespace) -> None:
    """主账户充值。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    ok = repo.deposit_main_account(args.account, args.amount)
    if ok:
        acct = repo.get_main_account(args.account)
        print(f"充值成功: +{args.amount:,.2f}")
        print(f"  当前现金: {acct['cash']:,.2f}")
        print(f"  已分配:   {acct['allocated_capital']:,.2f}")
        print(f"  可用:     {acct['available_capital']:,.2f}")
        print(f"  总资产:   {acct['total_value']:,.2f}")
    else:
        print(f"错误：账户不存在或金额非法（amount={args.amount}）")


def _run_withdraw(args: argparse.Namespace) -> None:
    """主账户提取。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    ok = repo.withdraw_main_account(args.account, args.amount)
    if ok:
        acct = repo.get_main_account(args.account)
        print(f"提取成功: -{args.amount:,.2f}")
        print(f"  当前现金: {acct['cash']:,.2f}")
        print(f"  已分配:   {acct['allocated_capital']:,.2f}")
        print(f"  可用:     {acct['available_capital']:,.2f}")
        print(f"  总资产:   {acct['total_value']:,.2f}")
    else:
        print(f"错误：账户不存在/金额非法/可用现金不足（amount={args.amount}）")
        acct = repo.get_main_account(args.account)
        if acct:
            print(f"  当前可用现金: {acct['available_capital']:,.2f}")


def _run_list_accounts(args: argparse.Namespace) -> None:
    """列出所有主账户。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)
    accounts = repo.list_main_accounts()

    if not accounts:
        print("\n暂无主账户")
        print("提示：运行 'python main.py paper init --account acc_001 --capital 1000000' 创建主账户")
        return

    print("\n" + "=" * 110)
    print(f"{'账户ID':<20} {'初始资金':>14} {'当前现金':>14} {'已分配':>14} {'可用':>14} {'总资产':>14}")
    print("-" * 110)
    for r in accounts:
        print(
            f"{r['account_id']:<20} "
            f"{r['initial_capital']:>14.2f} {r['cash']:>14.2f} "
            f"{r['allocated_capital']:>14.2f} {r['available_capital']:>14.2f} "
            f"{r['total_value']:>14.2f}"
        )
    print("=" * 110)


# ----------------------------------------------------------------------
# 子账户策略管理
# ----------------------------------------------------------------------


def _run_add_strategy(args: argparse.Namespace) -> None:
    """添加策略子账户。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    ok = repo.add_strategy(args.account, args.strategy, args.capital)
    if ok:
        print(f"子账户添加成功: account={args.account} strategy={args.strategy} 资金={args.capital:,.2f}")
        acct = repo.get_main_account(args.account)
        print(f"  主账户可用现金: {acct['available_capital']:,.2f}")
    else:
        acct = repo.get_main_account(args.account)
        if acct is None:
            print(f"错误：主账户 '{args.account}' 不存在")
        elif acct["available_capital"] < args.capital:
            print(f"错误：主账户可用现金不足（需要 {args.capital:,.2f}，可用 {acct['available_capital']:,.2f}）")
        else:
            print(f"错误：子账户 '{args.strategy}' 已存在")


def _run_remove_strategy(args: argparse.Namespace) -> None:
    """彻底删除子账户。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    if not args.yes:
        confirm = input(
            f"确认删除子账户 account={args.account} strategy={args.strategy}？\n"
            f"（含全部持仓/订单/成交/快照，资金回收主账户）(y/N): "
        )
        if confirm.lower() != "y":
            print("已取消")
            return

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)
    recovered = repo.remove_strategy(args.account, args.strategy)
    if recovered is None:
        print(f"错误：子账户 '{args.strategy}' 不存在")
    else:
        print(f"子账户已删除: account={args.account} strategy={args.strategy}")
        print(f"  回收资金: {recovered:,.2f}")


def _run_disable_strategy(args: argparse.Namespace) -> None:
    """停用子账户。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)
    ok = repo.disable_strategy(args.account, args.strategy)
    if ok:
        print(f"子账户已停用: account={args.account} strategy={args.strategy}")
        print(f"（历史数据保留，可查询；使用 enable-strategy 重新启用）")
    else:
        print(f"错误：子账户 '{args.strategy}' 不存在")


def _run_enable_strategy(args: argparse.Namespace) -> None:
    """启用子账户。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)
    ok = repo.enable_strategy(args.account, args.strategy)
    if ok:
        print(f"子账户已启用: account={args.account} strategy={args.strategy}")
    else:
        print(f"错误：子账户 '{args.strategy}' 不存在")


def _run_list_strategies(args: argparse.Namespace) -> None:
    """列出主账户下的全部子账户。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    # 先检查主账户
    main = repo.get_main_account(args.account)
    if main is None:
        print(f"错误：主账户 '{args.account}' 不存在")
        return

    strategies = repo.list_strategies(args.account, enabled_only=not args.all)

    print(f"\n主账户: {args.account}")
    print(f"  初始资金: {main['initial_capital']:,.2f}")
    print(f"  当前现金: {main['cash']:,.2f}")
    print(f"  已分配:   {main['allocated_capital']:,.2f}")
    print(f"  可用:     {main['available_capital']:,.2f}")
    print(f"  总资产:   {main['total_value']:,.2f}")

    if not strategies:
        print("\n暂无子账户")
        print("提示：运行 'python main.py paper add-strategy --account ... --strategy ... --capital ...' 添加子账户")
        return

    print(f"\n子账户列表 ({'全部' if args.all else '仅启用'}):")
    print("=" * 110)
    print(f"{'策略名':<20} {'分配资金':>14} {'当前现金':>14} {'总资产':>14} {'状态':>8} {'更新时间'}")
    print("-" * 110)
    for s in strategies:
        status = "启用" if s["enabled"] else "停用"
        print(
            f"{s['strategy_name']:<20} "
            f"{s['allocated_capital']:>14.2f} {s['cash']:>14.2f} "
            f"{s['total_value']:>14.2f} {status:>8} {s.get('updated_at', '')}"
        )
    print("=" * 110)


# ----------------------------------------------------------------------
# 运行与查询
# ----------------------------------------------------------------------


def _run_run(args: argparse.Namespace) -> None:
    """执行单日模拟交易。

    行为：
        - 指定 --strategy：只运行该子账户
        - 省略 --strategy：依次运行主账户下所有启用的子账户（一键多策略）
    """
    import src.strategies  # noqa: F401 触发 auto_discover
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    # 1. 主账户存在性检查
    main = repo.get_main_account(args.account)
    if main is None:
        print(f"错误：主账户 '{args.account}' 不存在")
        print(f"提示：运行 'python main.py paper init --account {args.account} --capital 1000000' 创建主账户")
        return

    # 2. 确定交易日
    trade_date = args.date or datetime.now().strftime("%Y-%m-%d")

    # 3. 分发：指定策略 → 单策略运行；省略 → 遍历所有启用子账户
    strategy_params = _parse_strategy_params(args.param)
    if args.strategy is not None:
        # 单策略模式
        ok = _run_single_strategy(
            repo, db, args.account, args.strategy, trade_date,
            no_risk_check=args.no_risk_check,
            auto_create=args.auto_create,
            initial_capital=args.initial_capital,
            strategy_params=strategy_params,
        )
        if not ok and args.auto_create:
            # _run_single_strategy 内部已处理自动创建，这里不需要额外动作
            pass
        return

    # 多策略模式：遍历所有启用的子账户
    strategies = repo.list_strategies(args.account, enabled_only=True)
    if not strategies:
        print(f"错误：主账户 '{args.account}' 下没有启用的子账户")
        print(f"提示：运行 'python main.py paper add-strategy --account {args.account} --strategy <策略名> --capital <资金>' 添加子账户")
        return

    print(f"\n=== 运行主账户 [{args.account}] 下 {len(strategies)} 个启用子账户 [日期={trade_date}] ===")
    results = []  # [(strategy_name, success, summary_dict)]
    for strat in strategies:
        sname = strat["strategy_name"]
        print(f"\n--- 子账户: {sname} ---")
        ok = _run_single_strategy(
            repo, db, args.account, sname, trade_date,
            no_risk_check=args.no_risk_check,
            auto_create=False,  # 多策略模式不自动创建
            strategy_params=strategy_params,
            initial_capital=args.initial_capital,
        )
        # 读取运行后状态用于汇总
        updated = repo.get_strategy(args.account, sname)
        results.append((sname, ok, updated))

    # 4. 汇总
    print(f"\n=== 汇总 [账户={args.account}, 日期={trade_date}] ===")
    print(f"{'策略':<20}{'状态':<8}{'现金':>15}{'总资产':>15}{'盈亏':>12}")
    print("-" * 70)
    total_value = 0.0
    for sname, ok, strat in results:
        if strat is None:
            print(f"{sname:<20}{'失败':<8}{'-':>15}{'-':>15}{'-':>12}")
            continue
        cash = strat["cash"]
        tv = strat["total_value"]
        allocated = strat["allocated_capital"]
        pnl = tv - allocated
        total_value += tv
        status = "成功" if ok else "失败"
        print(f"{sname:<20}{status:<8}{cash:>15,.2f}{tv:>15,.2f}{pnl:>12,.2f}")
    print("-" * 70)
    print(f"{'合计':<20}{'':<8}{'':>15}{total_value:>15,.2f}")
    # 主账户总资产 = 主账户现金 + 子账户合计
    print(f"\n主账户 [{args.account}]:")
    print(f"  主账户现金(未分配): {main['cash']:,.2f}")
    print(f"  已分配合计:         {main['allocated_capital']:,.2f}")
    print(f"  子账户总资产合计:   {total_value:,.2f}")
    print(f"  主账户总资产:       {main['cash'] + total_value:,.2f}")


def _run_run_range(args: argparse.Namespace) -> None:
    """批量执行区间内每日模拟交易。

    从 t_trading_date 读取 [start_date, end_date] 内的交易日，
    逐日调用 _run_single_strategy（单策略或多策略）。
    """
    import src.strategies  # noqa: F401 触发 auto_discover
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    # 1. 主账户存在性检查
    main = repo.get_main_account(args.account)
    if main is None:
        print(f"错误：主账户 '{args.account}' 不存在")
        return

    # 2. 从 t_trading_date 获取区间内交易日
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT trade_date FROM t_trading_date WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
            (args.start_date, args.end_date),
        ).fetchall()
    trade_dates = [r[0] for r in rows]

    if not trade_dates:
        print(f"错误：区间 [{args.start_date}, {args.end_date}] 内无交易日")
        return

    # 3. 确定子账户列表
    strategy_params = _parse_strategy_params(args.param)
    if args.strategy is not None:
        strategies = [{"strategy_name": args.strategy}]
    else:
        strategies = repo.list_strategies(args.account, enabled_only=True)
        if not strategies:
            print(f"错误：主账户 '{args.account}' 下没有启用的子账户")
            return

    print(f"\n=== 批量运行 [{args.account}] {len(strategies)} 个子账户 ===")
    print(f"区间: {args.start_date} ~ {args.end_date}  共 {len(trade_dates)} 个交易日")
    print("=" * 80)

    total_ok = 0
    total_fail = 0
    for i, trade_date in enumerate(trade_dates, 1):
        print(f"\n[{i}/{len(trade_dates)}] 交易日 {trade_date}")
        day_ok = 0
        day_fail = 0
        for strat in strategies:
            sname = strat["strategy_name"]
            ok = _run_single_strategy(
                repo, db, args.account, sname, trade_date,
                no_risk_check=args.no_risk_check,
                auto_create=False,
                strategy_params=strategy_params,
            )
            if ok:
                day_ok += 1
            else:
                day_fail += 1
        total_ok += day_ok
        total_fail += day_fail
        # 每日运行后输出当日简要汇总
        print(f"  当日结果: 成功 {day_ok} 个, 失败 {day_fail} 个")

    # 4. 总汇总
    print(f"\n=== 批量运行完成 ===")
    print(f"区间: {args.start_date} ~ {args.end_date}")
    print(f"交易日数: {len(trade_dates)}")
    print(f"总成功: {total_ok}  总失败: {total_fail}")

    # 5. 输出最终账户状态
    print(f"\n=== 最终账户状态 ===")
    updated_main = repo.get_main_account(args.account)
    if updated_main:
        print(f"主账户现金: {updated_main['cash']:,.2f}  总资产: {updated_main['total_value']:,.2f}")
    final_strats = repo.list_strategies(args.account, enabled_only=False)
    for s in final_strats:
        pnl = s["total_value"] - s["allocated_capital"]
        pnl_pct = pnl / s["allocated_capital"] if s["allocated_capital"] > 0 else 0.0
        last_date = s.get("last_trade_date") or "-"
        print(
            f"  {s['strategy_name']:<20} 现金={s['cash']:>12.2f} 总资产={s['total_value']:>12.2f} "
            f"盈亏={pnl:>+12.2f} ({pnl_pct:>+7.2%}) 末交易日={last_date}"
        )


def _run_single_strategy(
    repo,
    db,
    account_id: str,
    strategy_name: str,
    trade_date: str,
    no_risk_check: bool = False,
    auto_create: bool = False,
    initial_capital: float = 1_000_000.0,
    strategy_params: Optional[Dict[str, Any]] = None,
) -> bool:
    """运行单个子账户的单日模拟交易。

    Args:
        repo: PersistenceRepository 实例
        db: DatabaseManager 实例
        account_id: 主账户ID
        strategy_name: 子账户策略名
        trade_date: 交易日 YYYY-MM-DD
        no_risk_check: 是否禁用风控
        auto_create: 子账户不存在时是否自动创建
        initial_capital: auto_create 时的初始资金
        strategy_params: 策略参数字典（如 manual_trade 的 symbol/action/volume）

    Returns:
        True 表示运行成功，False 表示失败
    """
    from src.core.engine import PaperEngine
    from src.core.strategy import get_strategy_class, list_strategies

    # 1. 取策略类
    strategy_class = get_strategy_class(strategy_name)
    if strategy_class is None:
        print(f"错误：未知策略 '{strategy_name}'")
        print(f"可用策略: {', '.join(list_strategies())}")
        return False

    # 2. 检查子账户存在性
    strat = repo.get_strategy(account_id, strategy_name)
    if strat is None:
        if not auto_create:
            print(f"错误：子账户 '{strategy_name}' 不存在")
            print(f"提示：运行以下命令添加子账户：")
            print(f"  python main.py paper add-strategy --account {account_id} --strategy {strategy_name} --capital {initial_capital}")
            print(f"  或加 --auto-create 自动创建")
            return False
        # 自动创建子账户
        ok = repo.add_strategy(account_id, strategy_name, initial_capital)
        if not ok:
            print(f"错误：自动创建子账户失败（主账户可用现金不足？）")
            return False
        print(f"已自动创建子账户: strategy={strategy_name} 资金={initial_capital:,.2f}")
        strat = repo.get_strategy(account_id, strategy_name)

    if not strat["enabled"]:
        print(f"错误：子账户 '{strategy_name}' 已停用，请先启用")
        print(f"提示：python main.py paper enable-strategy --account {account_id} --strategy {strategy_name}")
        return False

    # 3. 风控
    risk_manager = None
    if not no_risk_check:
        from src.risk_checks.factory import build_ashare_risk_manager
        risk_manager = build_ashare_risk_manager()

    # 4. 实例化策略
    strategy = strategy_class(params=strategy_params or {})

    # 5. 构造 PaperEngine（每日模式 datafeed=None）
    #    使用子账户的实际分配资金作为 initial_capital（首次运行后从 DB 恢复）
    engine = PaperEngine(
        strategy=strategy,
        db=db,
        account_id=account_id,
        strategy_name=strategy_name,
        initial_capital=strat["allocated_capital"],
        datafeed=None,
        risk_manager=risk_manager,
    )

    # 6. 从 DB 读取当日 bar（全市场收盘价）
    bar = _load_daily_bar(db, trade_date)
    if bar is None:
        print(f"错误：交易日 {trade_date} 无数据，请检查 t_stock_daily 表")
        engine.stop()
        return False

    # 7. 运行单日（finally 统一释放引擎资源，避免重复 stop）
    print(f"运行模拟盘 [账户={account_id}, 策略={strategy_name}, 日期={trade_date}]...")
    success = False
    try:
        engine.run_one_day(bar)
        print(f"  单日运行完成")
        success = True
    except Exception as e:
        print(f"  运行失败: {e}")
    finally:
        try:
            engine.stop()
        except Exception:
            pass

    if not success:
        return False

    # 8. 打印子账户摘要
    acct = engine.portfolio.get_account()
    print(f"子账户摘要:")
    print(f"  现金: {acct.cash:,.2f}")
    print(f"  冻结: {acct.frozen:,.2f}")
    print(f"  持仓市值: {acct.market_value:,.2f}")
    print(f"  总资产: {acct.total:,.2f}")
    print(f"  当日盈亏: {acct.daily_pnl:,.2f} ({acct.daily_pnl_pct:.2%})")
    return True


def _run_status(args: argparse.Namespace) -> None:
    """查看账户状态（主账户 + 子账户汇总）。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    if args.account:
        # 显示单个主账户详情
        main = repo.get_main_account(args.account)
        if main is None:
            print(f"错误：主账户 '{args.account}' 不存在")
            return
        _print_account_detail(repo, main)
    else:
        # 显示全部主账户
        accounts = repo.list_main_accounts()
        if not accounts:
            print("\n暂无主账户")
            print("提示：运行 'python main.py paper init --account acc_001 --capital 1000000' 创建主账户")
            return
        for main in accounts:
            _print_account_detail(repo, main)
            print()


def _print_account_detail(repo, main: dict) -> None:
    """打印单个主账户详情（含子账户列表）。"""
    print("=" * 110)
    print(f"主账户: {main['account_id']}")
    print(f"  初始资金: {main['initial_capital']:,.2f}  当前现金: {main['cash']:,.2f}")
    print(f"  已分配:   {main['allocated_capital']:,.2f}  可用: {main['available_capital']:,.2f}")
    print(f"  总资产:   {main['total_value']:,.2f}  峰值: {main['peak_value']:,.2f}")

    strategies = repo.list_strategies(main["account_id"], enabled_only=False)
    if not strategies:
        print("  暂无子账户")
    else:
        print(f"  子账户 ({len(strategies)}):")
        for s in strategies:
            status = "启用" if s["enabled"] else "停用"
            pnl = s["total_value"] - s["allocated_capital"]
            pnl_pct = pnl / s["allocated_capital"] if s["allocated_capital"] > 0 else 0.0
            last_date = s.get("last_trade_date") or "-"
            print(
                f"    - {s['strategy_name']:<20} "
                f"分配={s['allocated_capital']:>12.2f} 总资产={s['total_value']:>12.2f} "
                f"盈亏={pnl:>+12.2f} ({pnl_pct:>+7.2%}) 末交易日={last_date} [{status}]"
            )
    print("=" * 110)


def _run_positions(args: argparse.Namespace) -> None:
    """查看持仓明细。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    # 取持仓（按 strategy 过滤或合并全部）
    positions = repo.load_positions(args.account, args.strategy)

    if args.strategy:
        strat = repo.get_strategy(args.account, args.strategy)
        if strat is None:
            print(f"错误：子账户 '{args.strategy}' 不存在")
            return
        print(f"\n账户: {args.account}  子账户: {args.strategy}")
        print(f"分配资金: {strat['allocated_capital']:,.2f}  当前现金: {strat['cash']:,.2f}  总资产: {strat['total_value']:,.2f}")
    else:
        main = repo.get_main_account(args.account)
        if main is None:
            print(f"错误：主账户 '{args.account}' 不存在")
            return
        print(f"\n账户: {args.account}  （全部子账户合并持仓）")
        print(f"总资产: {main['total_value']:,.2f}")

    if not positions:
        print("\n当前无持仓")
        return

    print("\n" + "=" * 110)
    print(f"{'股票代码':<14} {'持仓数':>12} {'开仓价':>12} {'现价':>12} {'市值':>14} {'盈亏':>14}")
    print("-" * 110)
    for sym, pos in positions.items():
        print(
            f"{sym:<14} {pos.quantity:>12.0f} {pos.avg_price:>12.2f} "
            f"{pos.market_price:>12.2f} {pos.market_value:>14.2f} {pos.pnl:>+14.2f}"
        )
    print("=" * 110)


def _run_trades(args: argparse.Namespace) -> None:
    """查看成交记录。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    # 加载全部成交（按 strategy 过滤或不指定）
    fills = repo.load_fills(args.account, args.strategy)

    # 按日期范围过滤
    if args.start_date:
        fills = [f for f in fills if (f.get("fill_time") or "") >= args.start_date]
    if args.end_date:
        fills = [f for f in fills if (f.get("fill_time") or "") <= args.end_date + " 23:59:59"]

    # 限制条数
    total = len(fills)
    if total > args.limit:
        fills = fills[-args.limit:]  # 显示最后 N 条（最近记录）
        print(f"共 {total} 条成交记录，仅显示最后 {args.limit} 条")

    if not fills:
        print(f"\n账户: {args.account}  无成交记录")
        return

    scope = args.strategy if args.strategy else "全部子账户"
    print(f"\n账户: {args.account}  子账户: {scope}  成交记录 ({len(fills)} 条)")
    print("=" * 130)
    print(
        f"{'成交时间':<20} {'子账户':<16} {'股票代码':<12} {'方向':<6} "
        f"{'成交价':>12} {'成交量':>12} {'成交额':>14} {'佣金':>10} {'印花税':>10}"
    )
    print("-" * 130)
    for f in fills:
        direction = "买入" if f.get("direction") == "buy" else "卖出"
        price = f.get("price", 0.0)
        volume = f.get("volume", 0.0)
        amount = price * volume
        print(
            f"{f.get('fill_time', '-'):<20} "
            f"{f.get('strategy_name', '-'):<16} "
            f"{f.get('symbol', '-'):<12} "
            f"{direction:<6} "
            f"{price:>12.2f} {volume:>12.0f} {amount:>14.2f} "
            f"{f.get('commission', 0.0):>10.2f} {f.get('stamp_tax', 0.0):>10.2f}"
        )
    print("=" * 130)


def _run_reset(args: argparse.Namespace) -> None:
    """重置子账户。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    if not args.yes:
        confirm = input(
            f"确认重置子账户 account={args.account} strategy={args.strategy}？\n"
            f"（清空全部持仓/订单/成交/快照，资金回到 {args.capital or '原分配金额'}）(y/N): "
        )
        if confirm.lower() != "y":
            print("已取消")
            return

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)
    ok = repo.reset_strategy(args.account, args.strategy, args.capital)
    if ok:
        strat = repo.get_strategy(args.account, args.strategy)
        print(f"子账户已重置: account={args.account} strategy={args.strategy}")
        print(f"  当前资金: {strat['cash']:,.2f}  总资产: {strat['total_value']:,.2f}")
    else:
        print(f"错误：子账户 '{args.strategy}' 不存在")


def _run_adjust_cash(args: argparse.Namespace) -> None:
    """调整子账户资金（追加或回收）。"""
    from src.core.persistence import PersistenceRepository
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())
    repo = PersistenceRepository(db)

    ok = repo.adjust_strategy_capital(args.account, args.strategy, args.amount)
    if ok:
        strat = repo.get_strategy(args.account, args.strategy)
        action = "追加分配" if args.amount >= 0 else "回收资金"
        print(f"子账户资金调整成功: {action} {abs(args.amount):,.2f}")
        print(f"  分配资金: {strat['allocated_capital']:,.2f}")
        print(f"  当前现金: {strat['cash']:,.2f}")
        print(f"  总资产:   {strat['total_value']:,.2f}")
        main = repo.get_main_account(args.account)
        print(f"  主账户可用现金: {main['available_capital']:,.2f}")
    else:
        print(f"错误：调整失败（子账户不存在/主账户可用资金不足/子账户现金不足）")
        main = repo.get_main_account(args.account)
        strat = repo.get_strategy(args.account, args.strategy)
        if main and strat:
            print(f"  主账户可用现金: {main['available_capital']:,.2f}")
            print(f"  子账户现金: {strat['cash']:,.2f}")


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

    # get_stock_daily 返回的 df 是以 (trade_date, stock_code) 为 MultiIndex 的
    df = df.reset_index()

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
