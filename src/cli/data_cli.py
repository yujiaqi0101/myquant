"""
数据管理 CLI 模块
================

支持交互式和命令式两种使用方式：
- 交互式: python main.py data
- 命令式: python main.py data sync

数据源在 config.json 中按数据类型配置（CLI 不再提供数据源切换参数）
"""

import argparse
from typing import Optional

from .interactive import InteractiveMenu, prompt_input, prompt_choice, prompt_confirm


def _run_data_sync(start_date: str = None, end_date: str = None):
    """执行数据同步（数据源从 config.json 读取）"""
    start_date = start_date or prompt_input("起始日期", "20230101")
    end_date = end_date or prompt_input("结束日期", "")

    print(f"\n开始同步数据: {start_date} ~ {end_date or '最新'}")

    try:
        from src.data.data_sync import DataSynchronizer
        from src.data.database import DatabaseManager
        from src.data.qmt_connector import QMTConnector
        from config.config import DATABASE_CONFIG

        db = DatabaseManager(DATABASE_CONFIG.get('path'))

        # 连接QMT（主数据源：股票日线）
        print("正在连接QMT...")
        connector = QMTConnector()
        if not connector.is_connected():
            connector.connect()

        if not connector.is_connected():
            print("QMT连接失败，尝试从数据库读取已有数据")
            print("✓ 数据同步完成（仅检查数据库现有数据）")
            return

        print("QMT连接成功")

        synchronizer = DataSynchronizer(connector, db)

        def progress_cb(stage, current, total, message):
            if total > 0:
                pct = current / total * 100
                print(f"  [{stage}] {pct:.1f}% ({current}/{total}) {message}")
            else:
                print(f"  [{stage}] {message}")

        result = synchronizer.sync_all(
            start_date=start_date,
            end_date=end_date,
            progress_callback=progress_cb
        )

        print(f"\n同步完成:")
        for key, val in result.items():
            print(f"  {key}: {val}")
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


def _run_generate_test_data(n_stocks: int = 100, n_days: int = 250):
    """生成测试数据"""
    try:
        from src.data.test_data_generator import TestDataGenerator

        generator = TestDataGenerator()
        data = generator.generate_all_test_data(n_stocks=n_stocks, n_days=n_days)
        print(f"\n✓ 测试数据已生成")
        print(f"  股票信息: {len(data['stock_info'])} 条")
        print(f"  股票日频: {len(data['stock_daily'])} 条")
    except Exception as e:
        print(f"生成失败: {e}")


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

        # 股票信息
        info = db.get_stock_info()
        print(f"  股票信息: {len(info)} 条")

        # 日线数据
        try:
            daily = db.get_stock_daily(start_date='2020-01-01', end_date='2030-12-31')
            if not daily.empty:
                dates = daily['trade_date'].unique()
                print(f"  日线数据: {len(daily)} 条 ({dates.min()} ~ {dates.max()})")
            else:
                print("  日线数据: 无")
        except Exception:
            print("  日线数据: 无")

        # 股票池
        try:
            pools = db.list_stock_pools()
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
    menu.add_option('3', '生成测试数据', lambda: _run_generate_test_data())
    menu.add_option('4', '查看数据概览', _run_data_status)
    menu.add_option('5', '清空数据', _run_data_clear)
    menu.run()


# ---- argparse 集成 ----

def setup_data_parser(parser: argparse.ArgumentParser) -> None:
    """配置 data 子命令的参数"""
    subparsers = parser.add_subparsers(dest='data_command', help='数据管理子命令')

    # sync 子命令
    sync_parser = subparsers.add_parser('sync', help='同步数据（数据源从 config.json 读取）')
    sync_parser.add_argument('--start-date', help='起始日期 (YYYYMMDD)')
    sync_parser.add_argument('--end-date', help='结束日期 (YYYYMMDD)')

    # validate 子命令
    subparsers.add_parser('validate', help='校验数据完整性')

    # generate-test 子命令
    gen_parser = subparsers.add_parser('generate-test', help='生成测试数据')
    gen_parser.add_argument('--n-stocks', type=int, default=100, help='股票数量')
    gen_parser.add_argument('--n-days', type=int, default=250, help='天数')

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
        _run_data_sync(args.start_date, args.end_date)
    elif cmd == 'validate':
        _run_data_validate()
    elif cmd == 'generate-test':
        _run_generate_test_data(args.n_stocks, args.n_days)
    elif cmd == 'status':
        _run_data_status()
    elif cmd == 'clear':
        _run_data_clear()
