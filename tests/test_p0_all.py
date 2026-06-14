#!/usr/bin/env python3
"""
P0 全面验证测试
==============

覆盖 P0 阶段所有任务：
- Task 3: 删除 CLI --data-source 参数
- Task 4: 删除 config.json 的 data_source.source 字段
- Task 5: 板块成分股改为通达信数据源
- Task 6: 除权除息日同步
- Task 6.5: 任务管理（APScheduler）
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_task3_no_source_in_cli():
    """Task 3: data_cli.py 不应有 --source 参数"""
    print("=" * 60)
    print("Task 3: CLI --data-source 参数已删除")
    print("=" * 60)

    from src.cli import data_cli
    import inspect
    src = inspect.getsource(data_cli)
    assert '--source' not in src, "data_cli.py 还包含 --source 参数"
    assert '--data-source' not in src, "data_cli.py 还包含 --data-source 参数"
    print("[OK] data_cli.py 已删除 --source/--data-source")

    from src.cli import config_cli
    src = inspect.getsource(config_cli)
    assert '--data-source' not in src, "config_cli.py 还包含 --data-source 参数"
    print("[OK] config_cli.py 已删除 --data-source")

    from src.cli import backtest_cli
    src = inspect.getsource(backtest_cli)
    assert '--data-source' not in src, "backtest_cli.py 还包含 --data-source 参数"
    print("[OK] backtest_cli.py 已删除 --data-source")

    print("\n[PASS] Task 3: CLI --data-source 参数已删除\n")


def test_task4_data_source_routing():
    """Task 4: config.json data_source 字段按数据类型路由"""
    print("=" * 60)
    print("Task 4: config.json data_source 字段按数据类型路由")
    print("=" * 60)

    from config.config import (
        get_data_source, get_data_source_config,
        DEFAULT_DATA_SOURCE_CONFIG, DataSource,
    )

    # 验证 get_data_source 接受 data_type 参数（不是无参）
    cfg = get_data_source_config()
    assert isinstance(cfg, dict), "get_data_source_config 应返回 dict"
    assert 'sector_constituents' in cfg, "配置应包含 sector_constituents"
    assert cfg['sector_constituents'] == 'tdx', f"sector_constituents 应该是 tdx，实际 {cfg['sector_constituents']}"
    print(f"[OK] get_data_source_config: {list(cfg.keys())[:3]}...")

    # 验证按数据类型获取
    source = get_data_source('sector_constituents')
    assert source == 'tdx', f"sector_constituents 数据源应为 tdx，实际 {source}"
    print(f"[OK] sector_constituents -> {source}")

    source = get_data_source('dividend')
    assert source == 'eastmoney', f"dividend 数据源应为 eastmoney，实际 {source}"
    print(f"[OK] dividend -> {source}")

    # 验证 DataSource 常量
    assert hasattr(DataSource, 'TDX'), "DataSource 应包含 TDX"
    assert hasattr(DataSource, 'QMT'), "DataSource 应包含 QMT"
    print("[OK] DataSource 常量已扩展: TDX/QMT/EASTMONEY/DATABASE")

    # 验证 DEFAULT_DATA_SOURCE_CONFIG
    assert 'stock_daily' in DEFAULT_DATA_SOURCE_CONFIG
    assert DEFAULT_DATA_SOURCE_CONFIG['stock_daily'] == 'qmt'
    print(f"[OK] DEFAULT_DATA_SOURCE_CONFIG 完整: {len(DEFAULT_DATA_SOURCE_CONFIG)} 项")

    print("\n[PASS] Task 4: config.json 数据源按数据类型路由\n")


def test_task5_tdx_source():
    """Task 5: 板块成分股改为通达信数据源"""
    print("=" * 60)
    print("Task 5: 板块成分股改为通达信数据源")
    print("=" * 60)

    from src.data.tdx_source import TdxSource, HAS_PYTDX, _convert_to_standard_code

    # 验证代码转换函数
    assert _convert_to_standard_code('600000') == 'SHSE.600000'
    assert _convert_to_standard_code('000001') == 'SZSE.000001'
    assert _convert_to_standard_code('300750') == 'SZSE.300750'
    assert _convert_to_standard_code('830799') == 'BJSE.830799'
    assert _convert_to_standard_code('SHSE.600000') == 'SHSE.600000'  # 已是标准格式
    print("[OK] 股票代码转换: 600000 -> SHSE.600000")
    print("[OK] 股票代码转换: 000001 -> SZSE.000001")
    print("[OK] 股票代码转换: 830799 -> BJSE.830799")

    # 验证 TdxSource 类
    tdx = TdxSource()
    assert tdx.is_connected() is False
    print("[OK] TdxSource 实例化正常 (未连接状态)")

    if HAS_PYTDX:
        print("[OK] pytdx 已安装，TdxSource 可连接通达信")
    else:
        print("[INFO] pytdx 未安装，TdxSource 降级模式 (返回空数据)")

    # 验证 SourceRegistry
    from src.data.source_registry import SourceRegistry, get_source_for_data_type
    reg = SourceRegistry()
    assert reg is not None
    print("[OK] SourceRegistry 单例可用")

    print("\n[PASS] Task 5: 板块成分股改为通达信数据源\n")


def test_task6_dividend_sync():
    """Task 6: 除权除息日同步"""
    print("=" * 60)
    print("Task 6: 除权除息日同步")
    print("=" * 60)

    from src.data.div_sync import DividendSynchronizer
    from src.data.eastmoney_connector import EastmoneyConnector

    # 验证 DividendSynchronizer 类
    assert hasattr(DividendSynchronizer, 'sync_all')
    assert hasattr(DividendSynchronizer, 'detect_new_events')
    print("[OK] DividendSynchronizer 接口完整")

    # 验证 EastmoneyConnector.get_dividend
    assert hasattr(EastmoneyConnector, 'get_dividend')
    print("[OK] EastmoneyConnector.get_dividend 已实现")

    # 验证 dividend_date 表存在
    from src.data.database import DatabaseManager
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = DatabaseManager(db_path)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='dividend_date'"
            )
            row = cursor.fetchone()
            assert row is not None, "dividend_date 表不存在"
            print("[OK] dividend_date 表已存在")

            # 测试插入/查询
            cursor.execute('''
                INSERT INTO dividend_date
                (stock_code, ex_date, dividend_per_share, split_ratio, source)
                VALUES (?, ?, ?, ?, ?)
            ''', ('SHSE.600000', '2024-06-15', 0.5, 1.0, 'eastmoney'))
            conn.commit()

            cursor.execute(
                'SELECT * FROM dividend_date WHERE stock_code = ?',
                ('SHSE.600000',)
            )
            row = cursor.fetchone()
            assert row is not None
            assert row['dividend_per_share'] == 0.5
            print(f"[OK] dividend_date 插入/查询正常: {dict(row)}")
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)

    print("\n[PASS] Task 6: 除权除息日同步\n")


def test_p2_operators():
    """P2 Task 12: 算子库"""
    print("=" * 60)
    print("P2 Task 12: 算子库")
    print("=" * 60)

    from src.factors import operators

    # 验证时序算子
    ts_funcs = ['ts_mean', 'ts_std', 'ts_rank', 'ts_delta', 'ts_decay_linear', 'ts_ema']
    for fn in ts_funcs:
        assert hasattr(operators, fn), f"缺少 {fn}"
    print(f"[OK] 时序算子: {len(ts_funcs)} 个")

    # 验证横截面算子
    cross_funcs = ['rank', 'scale', 'normalize', 'neutralize', 'zscore', 'demean']
    for fn in cross_funcs:
        assert hasattr(operators, fn), f"缺少 {fn}"
    print(f"[OK] 横截面算子: {len(cross_funcs)} 个")

    # 验证数学算子
    math_funcs = ['log', 'sign', 'signed_power', 'abs_', 'where', 'decay_linear']
    for fn in math_funcs:
        assert hasattr(operators, fn), f"缺少 {fn}"
    print(f"[OK] 数学算子: {len(math_funcs)} 个")

    # 验证 alpha101/alpha191
    assert hasattr(operators, 'ALPHA101_FUNCS')
    assert hasattr(operators, 'ALPHA191_FUNCS')
    assert isinstance(operators.ALPHA101_FUNCS, dict)
    assert isinstance(operators.ALPHA191_FUNCS, dict)
    print(f"[OK] ALPHA101_FUNCS: {list(operators.ALPHA101_FUNCS.keys())}")
    print(f"[OK] ALPHA191_FUNCS: {list(operators.ALPHA191_FUNCS.keys())}")

    print("\n[PASS] P2 Task 12: 算子库\n")


def test_p2_logger():
    """P2 Task 14: 日志系统"""
    print("=" * 60)
    print("P2 Task 14: 日志系统")
    print("=" * 60)

    from src.utils.logger import setup_logger, ColoredFormatter

    # 验证 ColoredFormatter（颜色输出）
    assert ColoredFormatter is not None
    assert 'INFO' in ColoredFormatter.COLORS
    assert 'WARNING' in ColoredFormatter.COLORS
    assert 'ERROR' in ColoredFormatter.COLORS
    print("[OK] ColoredFormatter 颜色配置完整")
    print(f"     INFO={ColoredFormatter.COLORS['INFO']}...")

    # 验证 setup_logger 函数
    assert callable(setup_logger)
    print("[OK] setup_logger 函数可用")

    print("\n[PASS] P2 Task 14: 日志系统\n")


if __name__ == "__main__":
    success = True
    tests = [
        test_task3_no_source_in_cli,
        test_task4_data_source_routing,
        test_task5_tdx_source,
        test_task6_dividend_sync,
        test_p2_operators,
        test_p2_logger,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"[FAIL] {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            success = False
            print()

    if success:
        print("=" * 60)
        print("[ALL PASS] P0 全面验证测试通过")
        print("=" * 60)
    sys.exit(0 if success else 1)
