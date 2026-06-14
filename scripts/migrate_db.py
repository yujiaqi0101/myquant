"""
数据库迁移脚本
==============

提供已建库的 schema 升级能力：
- 增量添加新表（spec Task 8 中新增的 4 张表）
- 幂等：可重复运行，IF NOT EXISTS / OR IGNORE 保护
- 自动备份原库

使用
----
    python scripts/migrate_db.py
    python scripts/migrate_db.py --db /path/to/aquant.db
    python scripts/migrate_db.py --no-backup

设计原则
--------
- 不删除旧表 / 不删列（兼容现有数据）
- 新字段使用默认值或可空
- 输出迁移前后的表清单
"""
import argparse
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.config import DATABASE_CONFIG
from src.data.database import DatabaseManager

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def list_tables(db: DatabaseManager) -> list:
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [r[0] for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser(description='数据库迁移工具')
    ap.add_argument('--db', default=None, help='数据库路径（默认读 DATABASE_CONFIG）')
    ap.add_argument('--no-backup', action='store_true', help='不备份原库')
    args = ap.parse_args()

    db_path = args.db or DATABASE_CONFIG['path']
    if not os.path.exists(db_path):
        logger.info(f"数据库不存在: {db_path}，将新建空库并初始化所有表")
        # 不需要迁移，直接初始化
        db = DatabaseManager(db_path)
        tables = list_tables(db)
        logger.info(f"初始化完成，共 {len(tables)} 张表: {tables}")
        return

    # 备份
    if not args.no_backup:
        backup_dir = os.path.join(os.path.dirname(db_path), 'backup')
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'{os.path.basename(db_path)}.{ts}.bak')
        shutil.copy2(db_path, backup_path)
        logger.info(f"已备份原库到: {backup_path}")

    # 记录迁移前表清单
    db = DatabaseManager(db_path)
    before = set(list_tables(db))
    logger.info(f"迁移前共 {len(before)} 张表")

    # DatabaseManager.__init__ 已经会执行 init_db()，
    # 内部的 CREATE TABLE IF NOT EXISTS 会幂等地添加新表
    # 重新执行一次 init
    db._init_db()
    after = set(list_tables(db))
    logger.info(f"迁移后共 {len(after)} 张表")

    new = sorted(after - before)
    if new:
        logger.info(f"新增 {len(new)} 张表: {new}")
    else:
        logger.info("没有新增表（数据库已是最新）")

    # 输出 spec Task 8 关键表的存在性
    required = {
        'etf_info', 'etf_daily', 'etf_constituent',
        'index_info', 'index_daily', 'index_constituent',
        'sector_info', 'sector_constituent',
        'valuation_data',
        'factor_registry', 'factor_execution_log', 'factor_combination', 'factor_exposure',
        'strategy_info', 'strategy_tag', 'strategy_best_perf', 'strategy_versions',
    }
    missing = required - after
    if missing:
        logger.warning(f"以下 spec Task 8 要求的表仍缺失: {missing}")
    else:
        logger.info("spec Task 8 全部表已就绪")


if __name__ == '__main__':
    main()
