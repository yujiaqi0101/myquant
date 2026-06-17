"""
数据管理 CLI 模块
================

支持交互式和命令式两种使用方式：
- 交互式: python main.py data
- 命令式: python main.py data sync
"""

import argparse
from typing import Optional

from .interactive import InteractiveMenu, prompt_input, prompt_confirm


def _run_data_sync(start_date: str = None, end_date: str = None):
    """执行数据同步（通过 SourceRegistry 自动路由数据源）"""
    start_date = start_date or prompt_input("起始日期", "20230101")
    end_date = end_date or prompt_input("结束日期", "")

    print(f"\n开始同步数据: {start_date} ~ {end_date or '最新'}")

    try:
        from src.data.database import DatabaseManager
        from src.data.data_sync import DataSynchronizer
        from config.config import DATABASE_CONFIG

        db_path = DATABASE_CONFIG.get('path')
        db = DatabaseManager(db_path)
        sync = DataSynchronizer(db)

        def progress_cb(step, current, total, msg=''):
            if msg:
                print(f"  [{step}] {current}/{total} - {msg}")
            else:
                print(f"  [{step}] {current}/{total}")

        sync.sync_all(start_date=start_date, end_date=end_date, progress_callback=progress_cb)
        print("\n✓ 数据同步完成")
    except Exception as e:
        print(f"同步失败: {e}")


def _run_data_validate():
    """校验数据完整性"""
    try:
        from src.data.database import DatabaseManager
        from config.config import DATABASE_CONFIG

        db = DatabaseManager(DATABASE_CONFIG.get('path'))
        validator = db.validate_data()
        print(f"\n✓ 数据校验完成")
    except Exception as e:
        print(f"校验失败: {e}")


def _run_data_status():
    """查看数据概览"""
    try:
        from src.data.database import DatabaseManager
        from config.config import DATABASE_CONFIG

        db = DatabaseManager(DATABASE_CONFIG.get('path'))

        print(f"\n{'=' * 50}")
        print("[数据概览]")
        print(f"{'=' * 50}")
        print(f"  数据库: {DATABASE_CONFIG.get('path')}")

        # 通用查询：统计各同步表记录数
        sync_tables = [
            ('t_trading_date', '交易日历'),
            ('t_stock_info', '股票基本信息'),
            ('t_stock_daily', '股票日频数据'),
            ('t_etf_info', 'ETF基本信息'),
            ('t_etf_daily', 'ETF日频数据'),
            ('t_index_info', '指数基本信息'),
            ('t_stock_in_index', '指数成分股'),
            ('t_index_daily', '指数日频数据'),
            ('t_sector_info', '板块基本信息'),
            ('t_stock_list_in_sector', '板块成分股'),
            ('financial_data', '财务数据'),
            ('t_valuation_data', '估值数据'),
            ('t_dividend_date', '除权除息'),
        ]

        with db.get_connection() as conn:
            cursor = conn.cursor()
            for table_name, display_name in sync_tables:
                try:
                    cursor.execute(f'SELECT COUNT(*) as cnt FROM {table_name}')
                    cnt = cursor.fetchone()['cnt']
                    print(f"  {display_name} ({table_name}): {cnt} 条")
                except Exception:
                    print(f"  {display_name} ({table_name}): 表不存在")

        # 股票池
        try:
            pools = db.list_stock_pools()
            if pools:
                print(f"  股票池: {len(pools)} 个")
                for pool in pools:
                    members = db.get_stock_pool_members(pool['pool_name'])
                    print(f"    - {pool['pool_name']}: {len(members)} 只")
        except Exception:
            pass

        print(f"{'=' * 50}")
    except Exception as e:
        print(f"获取数据概览失败: {e}")


def _run_data_clear():
    """清空数据"""
    if not prompt_confirm("确定要清空所有数据吗？此操作不可恢复", default=False):
        print("已取消")
        return

    try:
        from src.data.database import DatabaseManager
        from config.config import DATABASE_CONFIG

        db_path = DATABASE_CONFIG.get('path')
        if prompt_confirm(f"将删除 {db_path}，确认？", default=False):
            import os
            if os.path.exists(db_path):
                os.remove(db_path)
                print(f"✓ 数据库已删除: {db_path}")
            else:
                print("数据库文件不存在")
    except Exception as e:
        print(f"清空失败: {e}")


# ---- 交互式菜单 ----

def run_data_interactive():
    """运行数据管理交互式菜单"""
    menu = InteractiveMenu("数据管理")
    menu.add_option('1', '同步数据', lambda: _run_data_sync())
    menu.add_option('2', '校验数据完整性', _run_data_validate)
    menu.add_option('3', '查看数据概览', _run_data_status)
    menu.add_option('4', '清空数据', _run_data_clear)
    menu.run()


# ---- argparse 集成 ----

def setup_data_parser(parser: argparse.ArgumentParser) -> None:
    """配置 data 子命令的参数"""
    subparsers = parser.add_subparsers(dest='data_command', help='数据管理子命令')

    # sync 子命令
    sync_parser = subparsers.add_parser('sync', help='同步数据')
    sync_parser.add_argument('--start-date', help='起始日期 (YYYYMMDD)')
    sync_parser.add_argument('--end-date', help='结束日期 (YYYYMMDD)')

    # validate 子命令
    subparsers.add_parser('validate', help='校验数据完整性')

    # status 子命令
    subparsers.add_parser('status', help='查看数据概览')

    # clear 子命令
    subparsers.add_parser('clear', help='清空数据')


def run_data_command(args) -> None:
    """执行 data 命令"""
    if not hasattr(args, 'data_command') or not args.data_command:
        run_data_interactive()
        return

    cmd = args.data_command
    if cmd == 'sync':
        _run_data_sync(start_date=args.start_date, end_date=args.end_date)
    elif cmd == 'validate':
        _run_data_validate()
    elif cmd == 'status':
        _run_data_status()
    elif cmd == 'clear':
        _run_data_clear()
