"""
数据库表名迁移脚本
将旧表名重命名为带 t_ 前缀的新表名，保留已有数据。

映射关系：
  stock_daily        -> t_stock_daily
  index_daily        -> t_index_daily
  index_info         -> t_index_info
  stock_info         -> t_stock_info
  index_constituent  -> t_stock_in_index
  etf_info           -> t_etf_info
  etf_daily          -> t_etf_daily
  sector_info        -> t_sector_info
  sector_constituent -> t_stock_list_in_sector
  stock_pool         -> t_stock_pool
  stock_pool_member  -> t_stock_in_stock_pool
  data_sync_log      -> t_data_sync
  trade_calendar     -> t_trading_date
  dividend           -> t_dividend_date
  qmt_instrument     -> (删除)
"""

import sqlite3
import sys
from pathlib import Path

# 表名映射：旧名 -> 新名
TABLE_RENAMES = {
    'stock_daily': 't_stock_daily',
    'index_daily': 't_index_daily',
    'index_info': 't_index_info',
    'stock_info': 't_stock_info',
    'index_constituent': 't_stock_in_index',
    'etf_info': 't_etf_info',
    'etf_daily': 't_etf_daily',
    'sector_info': 't_sector_info',
    'sector_constituent': 't_stock_list_in_sector',
    'stock_pool': 't_stock_pool',
    'stock_pool_member': 't_stock_in_stock_pool',
    'data_sync_log': 't_data_sync',
    'trade_calendar': 't_trading_date',
    'dividend': 't_dividend_date',
}

# 需要删除的表
TABLES_TO_DROP = ['qmt_instrument']


def migrate_db(db_path: str, dry_run: bool = False):
    """迁移数据库表名"""
    print(f"数据库: {db_path}")

    if not Path(db_path).exists():
        print(f"错误: 数据库文件不存在: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 获取现有表名
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    existing_tables = {row[0] for row in cursor.fetchall()}
    print(f"现有表: {sorted(existing_tables)}")

    # 删除表
    for table in TABLES_TO_DROP:
        if table in existing_tables:
            print(f"  删除表: {table}")
            if not dry_run:
                cursor.execute(f"DROP TABLE IF EXISTS [{table}]")

    # 重命名表
    renamed = 0
    for old_name, new_name in TABLE_RENAMES.items():
        if old_name in existing_tables and new_name not in existing_tables:
            print(f"  重命名: {old_name} -> {new_name}")
            if not dry_run:
                cursor.execute(f"ALTER TABLE [{old_name}] RENAME TO [{new_name}]")
            renamed += 1
        elif old_name in existing_tables and new_name in existing_tables:
            print(f"  跳过: {old_name} (新表 {new_name} 已存在)")
        elif old_name not in existing_tables:
            print(f"  跳过: {old_name} (旧表不存在)")

    if not dry_run:
        conn.commit()
        print(f"\n迁移完成! 重命名了 {renamed} 个表。")

        # 验证
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        final_tables = [row[0] for row in cursor.fetchall()]
        print(f"迁移后表: {final_tables}")
    else:
        print(f"\n[DRY RUN] 将重命名 {renamed} 个表。")

    conn.close()


if __name__ == '__main__':
    db_path = str(Path(__file__).parent / 'data' / 'aquant.db')

    # 支持 --dry-run 参数
    dry_run = '--dry-run' in sys.argv

    # 支持指定数据库路径
    for arg in sys.argv[1:]:
        if arg != '--dry-run' and not arg.startswith('-'):
            db_path = arg

    if dry_run:
        print("=== DRY RUN 模式（不会实际修改） ===\n")

    migrate_db(db_path, dry_run=dry_run)
