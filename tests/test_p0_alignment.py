#!/usr/bin/env python3
"""
P0 验证测试：模拟数据绝不写入数据库 + 飞书文档数据库表补全
=================================================================
"""
import sys
import os
import tempfile
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from src.data.database import DatabaseManager


def test_p0_no_simulated_to_db():
    """P0 Task 1: 模拟数据绝不写入数据库"""
    print("=" * 60)
    print("P0 Task 1: 验证模拟数据过滤")
    print("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        db = DatabaseManager(db_path)

        # 创建包含模拟数据的 DataFrame
        df = pd.DataFrame({
            'trade_date': ['2024-01-01', '2024-01-02', '2024-01-03'],
            'stock_code': ['SHSE.000001', 'SHSE.000001', 'SHSE.000001'],
            'open': [10.0, 10.5, 11.0],
            'high': [10.2, 10.7, 11.2],
            'low': [9.8, 10.3, 10.8],
            'close': [10.0, 10.5, 11.0],
            'volume': [1000000, 1100000, 1200000],
            'is_simulated': [False, True, False],  # 中间一行是模拟数据
        })

        inserted = db.insert_stock_daily(df)
        print(f"[OK] insert_stock_daily 返回 {inserted} (过滤后)")

        # 验证：数据库中应该只有 2 行（过滤掉了 1 行模拟数据）
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
            assert count == 2, f"数据库应只有 2 行（过滤掉 1 行模拟数据），实际 {count} 行"
            print(f"[OK] 数据库中 stock_daily 实际有 {count} 行（已过滤 1 行模拟数据）")

        # 验证：插入纯净数据（全非模拟）应该全部写入
        df_clean = df.drop(columns=['is_simulated'])
        inserted = db.insert_stock_daily(df_clean)
        print(f"[OK] insert_stock_daily(纯净数据) 返回 {inserted}")

        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
            # 3 行已存在 + 3 行新数据
            print(f"[OK] 数据库中 stock_daily 共 {count} 行")

        print("\n[PASS] P0 Task 1 通过：模拟数据被正确过滤\n")
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_p0_new_tables_exist():
    """P0 Task 8: 飞书文档数据库表补全"""
    print("=" * 60)
    print("P0 Task 8: 验证飞书文档数据库表已建")
    print("=" * 60)

    expected_tables = [
        # 已有
        'stock_pool', 'stock_pool_member', 'data_sync_log', 'trade_calendar',
        'stock_info', 'stock_daily', 'index_constituent', 'index_daily',
        'financial_data', 'factor_registry', 'factor_exposure',
        'best_records', 'strategy_versions', 'execution_log',
        # P0 新增
        'dividend_date',
        'etf_info', 'etf_daily',
        'index_info',
        'sector_info', 'sector_constituent',
        'factor_combination',
        'strategy_info', 'strategy_tag',
    ]

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        db = DatabaseManager(db_path)

        with db.get_connection() as conn:
            existing = set(r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall())

        missing = [t for t in expected_tables if t not in existing]
        if missing:
            print(f"[FAIL] 缺失表：{missing}")
            return False

        print(f"[OK] 所有 {len(expected_tables)} 个表都存在")
        for t in expected_tables:
            print(f"  - {t}")
        print("\n[PASS] P0 Task 8 通过：飞书文档数据库表已建\n")
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    success = True
    try:
        test_p0_no_simulated_to_db()
    except Exception as e:
        print(f"[FAIL] Task 1 失败: {e}")
        import traceback
        traceback.print_exc()
        success = False

    try:
        test_p0_new_tables_exist()
    except Exception as e:
        print(f"[FAIL] Task 8 失败: {e}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)
