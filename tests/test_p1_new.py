"""
测试 P1 阶段新增功能：DataInspector / DataCleaner / FactorRegistry
"""
import sys, os, tempfile
import pandas as pd
import numpy as np
sys.path.insert(0, '.')
from src.data.database import DatabaseManager
from src.data.inspector import DataInspector
from src.data.cleaner import DataCleaner
from src.factors.factor_registry import (
    register_factor, get_factor_info, list_factors,
    FactorCategory, FactorSource, FACTOR_REGISTRY
)


def make_db_with_data():
    """构造一个含测试数据的临时数据库"""
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    fp = f.name
    f.close()
    db = DatabaseManager(fp)

    # 填充 trade_calendar
    dates = pd.date_range('2024-01-01', '2024-01-10').strftime('%Y-%m-%d').tolist()
    with db.get_connection() as conn:
        conn.executemany(
            'INSERT OR IGNORE INTO trade_calendar (trade_date) VALUES (?)',
            [(d,) for d in dates]
        )
        # 3 只股票
        conn.executemany(
            '''INSERT OR IGNORE INTO stock_info (stock_code, stock_name) VALUES (?, ?)''',
            [('SHSE.600000', 'A'), ('SHSE.600001', 'B'), ('SHSE.600002', 'C')]
        )
        # A 缺 1-05（除权除息日），B 缺 1-05/1-06，C 完全缺失
        rows = []
        for sym, present in [
            ('SHSE.600000', [d for d in dates if d != '2024-01-05']),
            ('SHSE.600001', [d for d in dates if d not in ('2024-01-05', '2024-01-06')])
        ]:
            for d in present:
                rows.append((d, sym, 10.0, 11.0, 9.5, 10.5, 1000.0, 0))
        conn.executemany(
            '''INSERT INTO stock_daily (trade_date, stock_code, open, high, low, close, volume, suspend_flag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            rows
        )
        # dividend_date 数据（A 在 1-05 除权除息）
        conn.executemany(
            '''INSERT INTO dividend_date (stock_code, ex_date) VALUES (?, ?)''',
            [('SHSE.600000', '2024-01-05')]
        )
        conn.commit()
    return db, fp


def test_inspector_missing():
    db, fp = make_db_with_data()
    try:
        inspector = DataInspector(db)
        result = inspector.inspect(
            symbols=['SHSE.600000', 'SHSE.600001', 'SHSE.600002'],
            start_date='2024-01-01',
            end_date='2024-01-10',
        )
        print(f'inspect: total={result["total_symbols"]}, missing={result["missing_symbols"]}, partial={len(result["partial_symbols"])}')
        assert result['total_symbols'] == 3
        assert 'SHSE.600002' in result['missing_symbols']
        assert any(s == 'SHSE.600001' for s, _, _ in result['partial_symbols'])
        assert 'SHSE.600001' in result['gaps']
        assert set(result['gaps']['SHSE.600001']) == {'2024-01-05', '2024-01-06'}
        print('Inspector: OK')
    finally:
        os.unlink(fp)


def test_cleaner():
    db, fp = make_db_with_data()
    try:
        cleaner = DataCleaner(db)
        result = cleaner.clean_stock_daily(
            symbols=['SHSE.600000', 'SHSE.600001'],
            start_date='2024-01-01',
            end_date='2024-01-10',
        )
        print(f'clean: {result}')
        assert result['symbols_processed'] == 2
        # A 有除权除息 1-05，应识别为需重新拉取
        assert result['ex_dividend_refetched'] >= 1
        print('Cleaner: OK')
    finally:
        os.unlink(fp)


def test_factor_registry():
    # 内置因子
    assert 'pb' in FACTOR_REGISTRY
    assert get_factor_info('pb') is not None

    # 注册新因子
    register_factor(
        name='custom_test_factor',
        field='test_field',
        source=FactorSource.VALUATION,
        category=FactorCategory.VALUATION,
        description='测试因子',
        default_ascending=True,
        data_sources=['eastmoney'],
    )
    assert 'custom_test_factor' in FACTOR_REGISTRY
    info = get_factor_info('custom_test_factor')
    assert info['field'] == 'test_field'
    assert info['category'] == FactorCategory.VALUATION

    # list_factors 分类
    val_factors = list_factors(category=FactorCategory.VALUATION)
    assert 'pb' in val_factors
    assert 'custom_test_factor' in val_factors
    print('FactorRegistry: OK')


def test_new_tables():
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    fp = f.name
    f.close()
    db = DatabaseManager(fp)
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            for tbl in ['strategy_best_perf', 'factor_execution_log', 'valuation_data']:
                cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}'")
                assert cur.fetchone() is not None, f'missing {tbl}'
        print('New tables: OK')
    finally:
        os.unlink(fp)


def test_constituents():
    """成分股统一接口"""
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    fp = f.name
    f.close()
    db = DatabaseManager(fp)
    try:
        from src.data.constituents import get_etf_constituents, get_index_constituents, get_sector_constituents
        with db.get_connection() as conn:
            conn.executemany(
                "INSERT INTO index_constituent (index_code, stock_code, weight) VALUES (?, ?, ?)",
                [
                    ('SHSE.000300', 'SHSE.600000', 0.1),
                    ('SHSE.000300', 'SHSE.600001', 0.2),
                    ('SHSE.000300', 'SHSE.600002', 0.3),
                ]
            )
            conn.executemany(
                "INSERT INTO sector_constituent (sector_code, stock_code, trade_date) VALUES (?, ?, ?)",
                [
                    ('银行', 'SHSE.600000', '2024-01-01'),
                    ('银行', 'SHSE.600001', '2024-01-01'),
                ]
            )
            conn.executemany(
                "INSERT INTO etf_constituent (etf_code, stock_code, trade_date) VALUES (?, ?, ?)",
                [
                    ('SHSE.512130', 'SHSE.600000', '2024-01-01'),
                    ('SHSE.512130', 'SHSE.600001', '2024-01-01'),
                    ('SHSE.512130', 'SHSE.600002', '2024-01-01'),
                ]
            )
            conn.execute(
                "INSERT INTO etf_info (etf_code, etf_name) VALUES (?, ?)",
                ('SHSE.512130', '测试 ETF')
            )
            conn.commit()

        etf_const = get_etf_constituents(db, 'SHSE.512130')
        assert etf_const == ['SHSE.600000', 'SHSE.600001', 'SHSE.600002'], etf_const

        idx_const = get_index_constituents(db, 'SHSE.000300')
        assert len(idx_const) == 3

        sec_const = get_sector_constituents(db, '银行')
        assert sec_const == ['SHSE.600000', 'SHSE.600001']

        assert get_etf_constituents(db, 'UNKNOWN') == []
        assert get_index_constituents(db, 'UNKNOWN') == []
        assert get_sector_constituents(db, 'UNKNOWN') == []
        print('Constituents: OK')
    finally:
        os.unlink(fp)


if __name__ == '__main__':
    test_new_tables()
    test_factor_registry()
    test_inspector_missing()
    test_cleaner()
    test_constituents()
    print('\n所有 P1 新功能测试通过')
