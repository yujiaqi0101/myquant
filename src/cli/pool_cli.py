"""
股票池管理 CLI 模块
==================

提供股票池的创建、查询、成员管理、从指数/CSV导入等功能。

子命令：
    python main.py pool --list
    python main.py pool --create tech_pool --desc '科技股精选'
    python main.py pool --add tech_pool --stocks 000001.SZ,600000.SH
    python main.py pool --show tech_pool
    python main.py pool --create CSI300 --import-index 000300.SH
    python main.py pool --delete tech_pool
"""

import argparse
from pathlib import Path


def _get_db_path() -> str:
    """获取数据库路径。"""
    return str(Path(__file__).parent.parent.parent / "data" / "aquant.db")


def setup_pool_parser(parser: argparse.ArgumentParser) -> None:
    """注册 pool 子命令参数。"""
    parser.add_argument("--list", "-l", action="store_true", help="列出所有股票池")
    parser.add_argument("--create", metavar="POOL_NAME", help="创建股票池")
    parser.add_argument("--code", metavar="CODE", help="股票池代码（与 --create 配合）")
    parser.add_argument("--desc", metavar="DESCRIPTION", help="股票池描述（与 --create 配合）")
    parser.add_argument("--show", metavar="POOL_NAME", help="查看股票池详情")
    parser.add_argument("--delete", metavar="POOL_NAME", help="删除股票池")
    parser.add_argument("--add", metavar="POOL_NAME", help="向股票池添加股票（配合 --stocks）")
    parser.add_argument("--remove", metavar="POOL_NAME", help="从股票池移除股票（配合 --stocks）")
    parser.add_argument("--stocks", metavar="CODES", help="股票代码列表，逗号分隔")
    parser.add_argument("--import-csv", metavar="CSV_PATH", help="从CSV导入（配合 --add）")
    parser.add_argument("--import-index", metavar="INDEX_CODE", help="从指数成分股创建（配合 --create）")


def run_pool_command(args: argparse.Namespace) -> None:
    """执行股票池管理命令。"""
    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())

    # 1. 列出所有股票池
    if args.list:
        _list_pools(db)
        return

    # 2. 创建股票池
    if args.create:
        _create_pool(db, args)
        return

    # 3. 查看详情
    if args.show:
        _show_pool(db, args.show)
        return

    # 4. 删除
    if args.delete:
        _delete_pool(db, args.delete)
        return

    # 5. 添加成员
    if args.add:
        _add_members(db, args)
        return

    # 6. 移除成员
    if args.remove:
        _remove_members(db, args)
        return

    # 无参数显示帮助
    print("\n股票池管理命令")
    print("=" * 60)
    print("\n可用选项：")
    print("  --list, -l                  列出所有股票池")
    print("  --create <名称>             创建股票池")
    print("  --code <代码>               股票池代码（与 --create 配合）")
    print("  --desc <描述>               股票池描述（与 --create 配合）")
    print("  --show <名称>               查看股票池详情和成员列表")
    print("  --delete <名称>             删除股票池")
    print("  --add <名称> --stocks <代码>   添加股票到池")
    print("  --remove <名称> --stocks <代码> 从池移除股票")
    print("  --import-csv <路径>         从CSV导入（与 --add 配合）")
    print("  --import-index <指数代码>   从指数成分股创建（与 --create 配合）")
    print("\n示例：")
    print("  python main.py pool --list")
    print("  python main.py pool --create tech_pool --desc '科技股精选'")
    print("  python main.py pool --add tech_pool --stocks 000001.SZ,600000.SH")
    print("  python main.py pool --show tech_pool")
    print("  python main.py pool --create CSI300 --import-index 000300.SH")
    print("=" * 60)


def _list_pools(db) -> None:
    """列出所有股票池。"""
    pools = db.list_stock_pools()
    if not pools:
        print("\n暂无股票池")
        return

    print("\n股票池列表：")
    print("=" * 80)
    print(f"{'名称':<20} {'代码':<15} {'成员数':>8}  {'描述':<25} {'创建时间'}")
    print("-" * 80)
    for p in pools:
        desc = (p["description"] or "")[:24]
        print(f"{p['pool_name']:<20} {(p['pool_code'] or ''):<15} {p['member_count']:>8}  {desc:<25} {p['created_at']}")
    print("=" * 80)
    print(f"共 {len(pools)} 个股票池")


def _create_pool(db, args) -> None:
    """创建股票池。"""
    if args.import_index:
        count = db.import_index_as_pool(args.import_index, args.create, args.desc)
        if count == -1:
            print(f"错误：指数 {args.import_index} 无成分股数据")
        else:
            print(f"已从指数 {args.import_index} 创建股票池 '{args.create}'，导入 {count} 只股票")
        return

    pool_id = db.create_stock_pool(args.create, args.code, args.desc)
    if pool_id == -1:
        print(f"错误：股票池 '{args.create}' 已存在")
    else:
        print(f"已创建股票池: {args.create}")
        if args.code:
            print(f"  代码: {args.code}")
        if args.desc:
            print(f"  描述: {args.desc}")


def _show_pool(db, pool_name: str) -> None:
    """查看股票池详情。"""
    info = db.get_stock_pool_info(pool_name)
    if not info:
        print(f"错误：股票池 '{pool_name}' 不存在")
        return

    members = db.get_stock_pool_members(pool_name)
    print(f"\n股票池: {pool_name}")
    print("=" * 60)
    if info.get("pool_code"):
        print(f"  代码: {info['pool_code']}")
    if info.get("description"):
        print(f"  描述: {info['description']}")
    print(f"  创建时间: {info['created_at']}")
    print(f"  当前成员数: {len(members)}")

    if members:
        print(f"\n成员列表（共 {len(members)} 只）：")
        for i in range(0, len(members), 8):
            print("  " + ", ".join(members[i:i + 8]))
    else:
        print("\n  （空股票池）")
    print("=" * 60)


def _delete_pool(db, pool_name: str) -> None:
    """删除股票池。"""
    if db.delete_stock_pool(pool_name):
        print(f"已删除股票池: {pool_name}")
    else:
        print(f"错误：股票池 '{pool_name}' 不存在")


def _add_members(db, args) -> None:
    """添加成员到股票池。"""
    if args.import_csv:
        csv_path = args.import_csv
        if not Path(csv_path).exists():
            print(f"错误：文件不存在 '{csv_path}'")
            return
        count = db.import_csv_as_pool(csv_path, args.add)
        if count == -1:
            print("导入失败")
        else:
            print(f"已从CSV导入 {count} 只股票到股票池 '{args.add}'")
        return

    if not args.stocks:
        print("错误：请通过 --stocks 指定股票代码列表")
        return

    stock_codes = [s.strip() for s in args.stocks.split(",")]
    count = db.add_to_stock_pool(args.add, stock_codes)
    if count == 0:
        info = db.get_stock_pool_info(args.add)
        if info is None:
            print(f"错误：股票池 '{args.add}' 不存在，请先创建")
        else:
            print(f"所有股票已存在于 '{args.add}' 中，无需重复添加")
    else:
        print(f"已向 '{args.add}' 添加 {count} 只股票（跳过已存在的）")


def _remove_members(db, args) -> None:
    """从股票池移除成员。"""
    if not args.stocks:
        print("错误：请通过 --stocks 指定要移除的股票代码列表")
        return

    stock_codes = [s.strip() for s in args.stocks.split(",")]
    count = db.remove_from_stock_pool(args.remove, stock_codes)
    print(f"已从 '{args.remove}' 移除 {count} 只股票")
