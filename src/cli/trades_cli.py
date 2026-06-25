"""
交易记录管理 CLI 模块
=====================

提供历史交易记录的导入、验证、报表生成功能。

支持交互式和命令式两种使用方式：
- 交互式: python main.py trades
- 命令式: python main.py trades import --file xxx.csv
"""

import argparse
from pathlib import Path

from .interactive import InteractiveMenu, prompt_input, prompt_confirm


def _get_db():
    """获取数据库管理器"""
    from src.data.database import DatabaseManager
    from config.config import DATABASE_CONFIG
    return DatabaseManager(DATABASE_CONFIG['path'])


def _run_import(file_path: str, broker: str = None, skip_validate: bool = False):
    """执行 CSV 导入"""
    from src.trades.csv_parser import TradeCSVParser
    from src.trades.validator import TradeValidator
    from src.trades.repository import TradeRepository

    path = Path(file_path)
    if not path.exists():
        print(f"✗ 文件不存在: {file_path}")
        return

    print(f"\n[导入交易记录]")
    print(f"  文件: {file_path}")

    # 1. 解析 CSV
    try:
        parser = TradeCSVParser()
        records, detected_broker, warnings = parser.parse(file_path, broker=broker)
    except Exception as e:
        print(f"✗ CSV 解析失败: {e}")
        return

    print(f"  识别券商: {detected_broker.display_name}")
    print(f"  解析记录: {len(records)} 条")

    if warnings:
        print(f"  解析警告: {len(warnings)} 条")
        for w in warnings[:5]:
            print(f"    - {w}")
        if len(warnings) > 5:
            print(f"    ... 还有 {len(warnings) - 5} 条")

    if not records:
        print("✗ 没有有效的交易记录")
        return

    # 2. 数据验证
    if not skip_validate:
        print(f"\n[数据验证]")
        validator = TradeValidator()
        result = validator.validate(records)
        print(result.summary())

        if not result.is_valid:
            print(f"\n✗ 发现 {result.invalid_count} 条无效记录")
            if not prompt_confirm("是否仍要导入有效记录？", default=False):
                print("已取消导入")
                return
            # 过滤无效记录
            invalid_indices = {err.row_index for err in result.errors}
            records = [r for i, r in enumerate(records) if i not in invalid_indices]
            print(f"  过滤后剩余: {len(records)} 条")

    # 3. 写入数据库
    print(f"\n[写入数据库]")
    db = _get_db()
    repo = TradeRepository(db)
    inserted, skipped = repo.insert_records(records, source_file=path.name)

    print(f"  ✓ 导入成功: {inserted} 条")
    if skipped > 0:
        print(f"  - 跳过(重复/失败): {skipped} 条")

    # 4. 显示统计
    summary = repo.get_summary()
    print(f"\n[数据库统计]")
    print(f"  总记录数: {summary['total_records']}")
    print(f"  买入笔数: {summary['buy_count']}")
    print(f"  卖出笔数: {summary['sell_count']}")
    print(f"  买入总额: ¥{summary['total_buy_amount']:,.2f}")
    print(f"  卖出总额: ¥{summary['total_sell_amount']:,.2f}")
    print(f"  总手续费: ¥{summary['total_fee']:,.2f}")
    print(f"  日期范围: {summary['date_range']}")


def _run_report(
    broker: str = None,
    start_date: str = None,
    end_date: str = None,
    output_dir: str = None,
):
    """生成交易报表"""
    from src.trades.reporter import TradeReporter

    db = _get_db()
    reporter = TradeReporter(db)

    # 检查是否有数据
    summary = reporter.repo.get_summary()
    if summary['total_records'] == 0:
        print("✗ 数据库中没有交易记录，请先导入")
        return

    if output_dir is None:
        from config.config import REPORT_DIR
        output_dir = str(REPORT_DIR / 'trades')

    print(f"\n[生成报表]")
    print(f"  数据范围: {summary['date_range']}")
    print(f"  记录数: {summary['total_records']}")

    try:
        html_path = reporter.generate_report(
            output_dir=output_dir,
            broker=broker,
            start_date=start_date,
            end_date=end_date,
        )
        print(f"\n✓ 报表已生成: {html_path}")
        print(f"  可在浏览器中打开查看")
    except Exception as e:
        print(f"✗ 报表生成失败: {e}")


def _run_list(broker: str = None, limit: int = 20):
    """查看交易记录列表"""
    from src.trades.repository import TradeRepository

    db = _get_db()
    repo = TradeRepository(db)

    df = repo.get_records(broker=broker)
    if df.empty:
        print("没有交易记录")
        return

    print(f"\n[交易记录] 共 {len(df)} 条")
    print("-" * 100)
    print(f"{'日期':<12} {'代码':<12} {'名称':<10} {'操作':<6} "
          f"{'价格':>8} {'数量':>10} {'金额':>12} {'费用':>10}")
    print("-" * 100)

    for _, row in df.head(limit).iterrows():
        action = "买入" if row['trade_type'] == 'buy' else "卖出"
        print(f"{row['trade_date']:<12} {row['stock_code']:<12} {str(row.get('stock_name', ''))[:8]:<10} "
              f"{action:<6} {row['price']:>8.3f} {row['quantity']:>10,.0f} "
              f"¥{row['amount']:>11,.2f} ¥{row.get('total_fee', 0):>9,.2f}")

    if len(df) > limit:
        print(f"... 还有 {len(df) - limit} 条记录")


def _run_validate(broker: str = None):
    """验证已导入的交易记录"""
    from src.trades.repository import TradeRepository
    from src.trades.validator import TradeValidator
    from src.trades.models import TradeRecord

    db = _get_db()
    repo = TradeRepository(db)
    df = repo.get_records(broker=broker)

    if df.empty:
        print("没有交易记录")
        return

    # 转换为 TradeRecord 列表
    records = []
    for _, row in df.iterrows():
        records.append(TradeRecord(
            trade_date=row['trade_date'],
            stock_code=row['stock_code'],
            stock_name=row.get('stock_name', ''),
            trade_type=row['trade_type'],
            price=row['price'],
            quantity=row['quantity'],
            amount=row['amount'],
            commission=row.get('commission', 0),
            stamp_tax=row.get('stamp_tax', 0),
            transfer_fee=row.get('transfer_fee', 0),
            other_fee=row.get('other_fee', 0),
            broker=row.get('broker', ''),
        ))

    validator = TradeValidator()
    result = validator.validate(records)
    print(result.summary())


def _run_clear(broker: str = None):
    """清空交易记录"""
    if not prompt_confirm(f"确定要清空{'券商 ' + broker if broker else '全部'}的交易记录吗？", default=False):
        print("已取消")
        return

    from src.trades.repository import TradeRepository
    db = _get_db()
    repo = TradeRepository(db)
    deleted = repo.delete_all(broker=broker)
    print(f"✓ 已删除 {deleted} 条记录")


def _run_summary():
    """查看统计摘要"""
    from src.trades.repository import TradeRepository
    db = _get_db()
    repo = TradeRepository(db)
    summary = repo.get_summary()

    print(f"\n{'=' * 50}")
    print("[交易记录统计]")
    print(f"{'=' * 50}")
    print(f"  总记录数: {summary['total_records']}")
    print(f"  买入笔数: {summary['buy_count']}")
    print(f"  卖出笔数: {summary['sell_count']}")
    print(f"  买入总额: ¥{summary['total_buy_amount']:,.2f}")
    print(f"  卖出总额: ¥{summary['total_sell_amount']:,.2f}")
    print(f"  总手续费: ¥{summary['total_fee']:,.2f}")
    print(f"  日期范围: {summary['date_range']}")
    print(f"  交易股票: {summary['stock_count']} 只")
    if summary['brokers']:
        print(f"  数据来源: {', '.join(summary['brokers'])}")
    print(f"{'=' * 50}")


# ============================================================
# 交互式菜单
# ============================================================

def run_trades_interactive():
    """运行交易记录管理交互式菜单"""
    menu = InteractiveMenu("交易记录管理")
    menu.add_option('1', '导入 CSV 交易记录', _interactive_import)
    menu.add_option('2', '查看交易记录列表', lambda: _run_list())
    menu.add_option('3', '查看统计摘要', _run_summary)
    menu.add_option('4', '验证数据完整性', lambda: _run_validate())
    menu.add_option('5', '生成报表', _interactive_report)
    menu.add_option('6', '清空交易记录', lambda: _run_clear())
    menu.run()


def _interactive_import():
    """交互式导入"""
    file_path = prompt_input("CSV 文件路径")
    if not file_path:
        print("未输入文件路径")
        return

    broker = prompt_input("券商格式 (huatai/citic/guojin/eastmoney/tonghuashun/generic，留空自动识别)")
    _run_import(file_path, broker=broker or None)


def _interactive_report():
    """交互式生成报表"""
    broker = prompt_input("券商筛选 (留空=全部)")
    start_date = prompt_input("起始日期 (YYYY-MM-DD，留空=不限)")
    end_date = prompt_input("结束日期 (YYYY-MM-DD，留空=不限)")
    _run_report(
        broker=broker or None,
        start_date=start_date or None,
        end_date=end_date or None,
    )


# ============================================================
# argparse 集成
# ============================================================

def setup_trades_parser(parser: argparse.ArgumentParser) -> None:
    """配置 trades 子命令的参数"""
    subparsers = parser.add_subparsers(dest='trades_command', help='交易记录管理子命令')

    # import 子命令
    import_parser = subparsers.add_parser('import', help='导入 CSV 交易记录')
    import_parser.add_argument('--file', '-f', required=True, help='CSV 文件路径')
    import_parser.add_argument('--broker', '-b', default=None,
                               choices=['huatai', 'citic', 'guojin', 'eastmoney', 'tonghuashun', 'generic'],
                               help='指定券商格式（不指定则自动识别）')
    import_parser.add_argument('--skip-validate', action='store_true', help='跳过数据验证')

    # report 子命令
    report_parser = subparsers.add_parser('report', help='生成交易报表')
    report_parser.add_argument('--broker', '-b', default=None, help='按券商筛选')
    report_parser.add_argument('--start-date', default=None, help='起始日期 (YYYY-MM-DD)')
    report_parser.add_argument('--end-date', default=None, help='结束日期 (YYYY-MM-DD)')
    report_parser.add_argument('--output-dir', '-o', default=None, help='报表输出目录')

    # list 子命令
    list_parser = subparsers.add_parser('list', help='查看交易记录列表')
    list_parser.add_argument('--broker', '-b', default=None, help='按券商筛选')
    list_parser.add_argument('--limit', '-n', type=int, default=20, help='显示条数 (默认20)')

    # validate 子命令
    validate_parser = subparsers.add_parser('validate', help='验证交易记录')
    validate_parser.add_argument('--broker', '-b', default=None, help='按券商筛选')

    # summary 子命令
    subparsers.add_parser('summary', help='查看统计摘要')

    # clear 子命令
    clear_parser = subparsers.add_parser('clear', help='清空交易记录')
    clear_parser.add_argument('--broker', '-b', default=None, help='按券商清空')


def run_trades_command(args) -> None:
    """执行 trades 命令"""
    if not hasattr(args, 'trades_command') or not args.trades_command:
        run_trades_interactive()
        return

    cmd = args.trades_command
    if cmd == 'import':
        _run_import(args.file, broker=args.broker, skip_validate=args.skip_validate)
    elif cmd == 'report':
        _run_report(
            broker=args.broker,
            start_date=args.start_date,
            end_date=args.end_date,
            output_dir=args.output_dir,
        )
    elif cmd == 'list':
        _run_list(broker=args.broker, limit=args.limit)
    elif cmd == 'validate':
        _run_validate(broker=args.broker)
    elif cmd == 'summary':
        _run_summary()
    elif cmd == 'clear':
        _run_clear(broker=args.broker)
