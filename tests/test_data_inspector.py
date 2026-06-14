"""
DataInspector 单元测试
======================

验证：
- inspect() 正确识别 missing/partial 标的
- _find_gaps() 正确找到缺失日期
- 多种数据表（stock_daily / etf_daily / index_daily）路由正确
- 空数据库 / 无交易日历边界条件
- _normalize_date() 处理 YYYYMMDD 和 YYYY-MM-DD 两种格式
"""
import os
import sys
import tempfile
import unittest

# 项目根加入 path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data.database import DatabaseManager
from src.data.inspector import DataInspector, DataInspector as DI


def _seed_calendar(db, dates):
    """把日期灌入 trade_calendar 表。"""
    with db.get_connection() as conn:
        for d in dates:
            conn.execute(
                "INSERT OR IGNORE INTO trade_calendar (trade_date) VALUES (?)",
                (d,),
            )


def _seed_stock_daily(db, code, dates):
    """给某股票在 dates 上插入一条最小记录。"""
    with db.get_connection() as conn:
        for d in dates:
            conn.execute(
                """
                INSERT INTO stock_daily
                    (trade_date, stock_code, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (d, code, 10.0, 11.0, 9.5, 10.5, 1000),
            )


def _seed_etf_daily(db, code, dates):
    with db.get_connection() as conn:
        for d in dates:
            conn.execute(
                """
                INSERT INTO etf_daily
                    (trade_date, etf_code, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (d, code, 1.0, 1.1, 0.95, 1.05, 5000),
            )


def _seed_index_daily(db, code, dates):
    with db.get_connection() as conn:
        for d in dates:
            conn.execute(
                """
                INSERT INTO index_daily
                    (trade_date, index_code, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (d, code, 3000.0, 3050.0, 2950.0, 3020.0, 1_000_000),
            )


class TestNormalizeDate(unittest.TestCase):
    def test_yyyymmdd_to_dash(self):
        self.assertEqual(DataInspector._normalize_date('20240105'), '2024-01-05')

    def test_dash_unchanged(self):
        self.assertEqual(DataInspector._normalize_date('2024-01-05'), '2024-01-05')

    def test_with_time(self):
        self.assertEqual(DataInspector._normalize_date('2024-01-05 09:30:00'), '2024-01-05')


class TestInspectStockDaily(unittest.TestCase):
    """核心：stock_daily 表的 inspect 行为。"""

    def setUp(self):
        f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        f.close()
        self.db_path = f.name
        self.db = DatabaseManager(self.db_path)
        self.inspector = DataInspector(self.db)

    def tearDown(self):
        # 解除 DatabaseManager 路径缓存，便于删除临时文件
        DatabaseManager._initialized_paths.discard(
            str(self.db.db_path.resolve())
        )
        os.unlink(self.db_path)

    def test_all_complete_no_missing(self):
        """全部标的完整覆盖 → 0 missing, 0 partial"""
        dates = ['2024-01-01', '2024-01-02', '2024-01-03']
        _seed_calendar(self.db, dates)
        _seed_stock_daily(self.db, 'SHSE.600000', dates)
        _seed_stock_daily(self.db, 'SHSE.600001', dates)

        result = self.inspector.inspect(
            symbols=['SHSE.600000', 'SHSE.600001'],
            start_date='2024-01-01', end_date='2024-01-03',
            table='stock_daily',
        )
        self.assertEqual(result['missing_symbols'], [])
        self.assertEqual(result['partial_symbols'], [])
        self.assertEqual(result['total_symbols'], 2)

    def test_full_missing_detected(self):
        """完全没数据 → missing_symbols"""
        dates = ['2024-01-01', '2024-01-02']
        _seed_calendar(self.db, dates)
        _seed_stock_daily(self.db, 'SHSE.600000', dates)
        # SHSE.600001 完全没有

        result = self.inspector.inspect(
            symbols=['SHSE.600000', 'SHSE.600001'],
            start_date='2024-01-01', end_date='2024-01-02',
            table='stock_daily',
        )
        self.assertIn('SHSE.600001', result['missing_symbols'])
        self.assertNotIn('SHSE.600000', result['missing_symbols'])

    def test_partial_detected(self):
        """部分日期缺失 → partial_symbols + gaps"""
        dates = ['2024-01-01', '2024-01-02', '2024-01-03']
        _seed_calendar(self.db, dates)
        # 600000 缺 01-02
        _seed_stock_daily(self.db, 'SHSE.600000', ['2024-01-01', '2024-01-03'])

        result = self.inspector.inspect(
            symbols=['SHSE.600000'],
            start_date='2024-01-01', end_date='2024-01-03',
            table='stock_daily',
        )
        self.assertEqual(result['missing_symbols'], [])
        self.assertEqual(len(result['partial_symbols']), 1)
        self.assertEqual(result['partial_symbols'][0][0], 'SHSE.600000')
        self.assertIn('2024-01-02', result['gaps']['SHSE.600000'])

    def test_no_symbols_no_calendar_returns_message(self):
        """无交易日历时给提示信息而不崩溃。"""
        result = self.inspector.inspect(
            symbols=['SHSE.600000'],
            start_date='2024-01-01', end_date='2024-01-03',
            table='stock_daily',
        )
        self.assertIn('message', result)
        self.assertEqual(result['missing_symbols'], [])

    def test_explicit_empty_symbols(self):
        """显式传空 symbols → 不崩溃"""
        result = self.inspector.inspect(
            symbols=[],
            start_date='2024-01-01', end_date='2024-01-03',
            table='stock_daily',
        )
        self.assertEqual(result['total_symbols'], 0)

    def test_none_symbols_lists_from_db(self):
        """symbols=None → 从数据库取全部 distinct"""
        dates = ['2024-01-01']
        _seed_calendar(self.db, dates)
        _seed_stock_daily(self.db, 'SHSE.600000', dates)
        _seed_stock_daily(self.db, 'SHSE.600001', dates)

        result = self.inspector.inspect(
            symbols=None,
            start_date='2024-01-01', end_date='2024-01-01',
            table='stock_daily',
        )
        self.assertEqual(result['total_symbols'], 2)

    def test_yyyymmdd_trade_date_compatibility(self):
        """trade_date 存为 YYYYMMDD 也能正确识别完整。"""
        dates_dash = ['2024-01-01', '2024-01-02']
        dates_compact = ['20240101', '20240102']
        _seed_calendar(self.db, dates_dash)
        _seed_stock_daily(self.db, 'SHSE.600000', dates_compact)

        result = self.inspector.inspect(
            symbols=['SHSE.600000'],
            start_date='2024-01-01', end_date='2024-01-02',
            table='stock_daily',
        )
        self.assertEqual(result['missing_symbols'], [])


class TestInspectOtherTables(unittest.TestCase):
    """非 stock_daily 表的路由（etf_daily / index_daily）。"""

    def setUp(self):
        f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        f.close()
        self.db_path = f.name
        self.db = DatabaseManager(self.db_path)
        self.inspector = DataInspector(self.db)

    def tearDown(self):
        DatabaseManager._initialized_paths.discard(
            str(self.db.db_path.resolve())
        )
        os.unlink(self.db_path)

    def test_etf_daily_table(self):
        dates = ['2024-02-01', '2024-02-02']
        _seed_calendar(self.db, dates)
        _seed_etf_daily(self.db, 'SHSE.510300', dates)

        result = self.inspector.inspect(
            symbols=['SHSE.510300'],
            start_date='2024-02-01', end_date='2024-02-02',
            table='etf_daily',
        )
        self.assertEqual(result['missing_symbols'], [])

    def test_index_daily_table(self):
        dates = ['2024-03-01', '2024-03-02']
        _seed_calendar(self.db, dates)
        _seed_index_daily(self.db, 'SHSE.000300', dates)
        # 给定 symbols + start/end，应当按 index_code 列查询
        result = self.inspector.inspect(
            symbols=['SHSE.000300'],
            start_date='2024-03-01', end_date='2024-03-02',
            table='index_daily',
        )
        self.assertEqual(result['missing_symbols'], [])


if __name__ == '__main__':
    unittest.main()
