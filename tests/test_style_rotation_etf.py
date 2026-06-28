"""
style_rotation_etf 策略单元测试 + 数据检查。
覆盖：from_etf_db / from_index_db / get_index_constituents / get_etf_constituents / 策略信号
"""
import sys
sys.path.insert(0, '.')

from config.config import DATABASE_CONFIG
from src.quantlab_adapters.data_adapter import (
    from_etf_db, from_index_db, from_mixed_db,
    get_index_constituents, get_etf_constituents,
)
from src.strategies.__init__ import *  # noqa
import sqlite3

DB_PATH = DATABASE_CONFIG['path']

def check_etf_data():
    """检查数据库中是否有 ETF 数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 检查 t_etf_daily 中是否有 3 只目标 ETF
    for code in ['510050.SH', '510300.SH', '510500.SH']:
        cursor.execute("SELECT COUNT(*) FROM t_etf_daily WHERE etf_code = ?", (code,))
        cnt = cursor.fetchone()[0]
        print(f"  t_etf_daily {code}: {cnt} 条")
    # 检查 t_etf_daily 总量
    cursor.execute("SELECT COUNT(*) FROM t_etf_daily")
    total = cursor.fetchone()[0]
    print(f"  t_etf_daily 总量: {total} 条")
    # 检查 etf_code 格式样本
    cursor.execute("SELECT DISTINCT etf_code FROM t_etf_daily LIMIT 5")
    samples = [r[0] for r in cursor.fetchall()]
    print(f"  etf_code 格式样本: {samples}")
    conn.close()


def test_from_etf_db():
    """测试 from_etf_db 数据加载"""
    print("\n=== test_from_etf_db ===")
    data = from_etf_db(
        db_path=DB_PATH,
        start_date="2024-01-01",
        end_date="2024-03-01",
        etf_codes=["510050.SH", "510300.SH", "510500.SH"],
    )
    print(f"  返回 {len(data)} 只 ETF")
    for sym, df in data.items():
        cols = list(df.columns)
        has_close = "close" in cols
        has_pre_close = "pre_close" in cols
        print(f"  {sym}: {len(df)} 行, 含 close={has_close}, pre_close={has_pre_close}, cols={cols[:8]}")
        assert has_close, f"{sym} 缺少 close 列"
    assert len(data) > 0, "未加载到 ETF 数据"
    print("  PASSED")


def test_from_index_db():
    """测试 from_index_db 数据加载"""
    print("\n=== test_from_index_db ===")
    data = from_index_db(
        db_path=DB_PATH,
        start_date="2024-01-01",
        end_date="2024-03-01",
        index_codes=["000300.SH"],
    )
    print(f"  返回 {len(data)} 个指数")
    for sym, df in data.items():
        print(f"  {sym}: {len(df)} 行, cols={list(df.columns)[:8]}")
    assert len(data) > 0, "未加载到指数数据"
    print("  PASSED")


def test_get_index_constituents():
    """测试指数成分股查询"""
    print("\n=== test_get_index_constituents ===")
    stocks = get_index_constituents("000300.SH", DB_PATH)
    print(f"  沪深300 成分股: {len(stocks)} 只")
    if stocks:
        print(f"  前5只: {stocks[:5]}")
    print("  PASSED")


def test_get_etf_constituents_empty():
    """测试 ETF 成分股查询（空表应返回空列表并警告）"""
    print("\n=== test_get_etf_constituents (空表) ===")
    stocks = get_etf_constituents("510050.SH", DB_PATH)
    print(f"  返回: {len(stocks)} 只（空表预期返回0）")
    assert stocks == [], "空表应返回空列表"
    print("  PASSED")


def test_strategy_signal():
    """测试策略信号生成"""
    print("\n=== test_strategy_signal ===")
    # 目录名 8b3c1d07 以数字开头，必须用 importlib 导入
    import importlib
    mod = importlib.import_module("src.strategies.8b3c1d07.style_rotation_etf_v1")
    StyleRotationEtfV1 = mod.StyleRotationEtfV1

    # 检查 asset_class 属性
    strategy = StyleRotationEtfV1(momentum_period=20, rebalance_at="month_start", top_n=1)
    assert strategy.asset_class == "etf", f"asset_class 应为 etf, 实际 {strategy.asset_class}"
    assert strategy.name == "style_rotation_etf"
    print(f"  name={strategy.name}, asset_class={strategy.asset_class}")
    print(f"  params={strategy.params}")
    print("  PASSED")


if __name__ == "__main__":
    print("=== 数据库 ETF 数据检查 ===")
    check_etf_data()
    test_from_etf_db()
    test_from_index_db()
    test_get_index_constituents()
    test_get_etf_constituents_empty()
    test_strategy_signal()
    print("\n=== 所有测试通过 ===")
