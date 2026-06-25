"""
历史交易记录导入与报表生成功能测试
====================================

测试内容：
1. 各券商 CSV 格式解析（华泰/中信/国金/东方财富/同花顺）
2. 券商格式自动识别
3. 数据验证（格式/范围/业务规则）
4. 数据库导入与查询
5. 报表生成
6. 性能测试（大文件）

运行方式：
    python -m pytest tests/test_trades_import.py -v
    python tests/test_trades_import.py
"""

import os
import sys
import csv
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# 添加项目根路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.trades.models import TradeRecord, BrokerFormat, normalize_stock_code, normalize_trade_type
from src.trades.csv_parser import TradeCSVParser
from src.trades.validator import TradeValidator
from src.trades.repository import TradeRepository
from src.trades.reporter import TradeReporter


# ============================================================
# 测试数据生成
# ============================================================

# 华泰证券 CSV 模板
HUATAI_CSV = """成交日期,成交时间,证券代码,证券名称,操作,成交均价,成交数量,成交金额,手续费,印花税,过户费,其他费用,资金账号
2024-01-15,09:35:12,000001,平安银行,买入,11.250,1000,11250.00,5.63,0.00,0.00,0.00,A12345
2024-02-20,10:15:30,000001,平安银行,卖出,11.800,1000,11800.00,5.90,5.90,0.00,0.00,A12345
2024-03-05,14:22:45,600000,浦发银行,买入,7.450,2000,14900.00,7.45,0.00,0.00,0.00,A12345
2024-04-10,11:05:20,600000,浦发银行,卖出,7.620,2000,15240.00,7.62,7.62,0.00,0.00,A12345
"""

# 中信证券 CSV 模板
CITIC_CSV = """交易日期,证券代码,证券名称,买卖方向,成交价格,成交数量,成交金额,手续费,印花税,过户费,其他费用,成交时间,资金账号
2024-01-15,000002,万科A,买入,9.350,2000,18700.00,9.35,0.00,0.00,0.00,09:30:15,B67890
2024-02-20,000002,万科A,卖出,9.800,2000,19600.00,9.80,9.80,0.00,0.00,10:05:30,B67890
"""

# 国金证券 CSV 模板
GUOJIN_CSV = """委托日期,证券代码,证券名称,操作方向,成交价格,成交数量,成交金额,手续费,印花税,过户费,其他费用,成交时间
20240315,600519,贵州茅台,买入,1685.50,100,168550.00,50.00,0.00,0.00,0.00,09:35:00
20240420,600519,贵州茅台,卖出,1750.20,100,175020.00,50.00,87.51,0.00,0.00,14:25:00
"""

# 东方财富 CSV 模板
EASTMONEY_CSV = """交易日,证券代码,证券名称,交易类型,成交均价,成交数量,成交金额,手续费,印花税,过户费,其他费用,成交时间
2024/01/15,300750,宁德时代,买入,185.60,100,18560.00,9.28,0.00,0.00,0.00,09:35:00
2024/02/20,300750,宁德时代,卖出,195.30,100,19530.00,9.77,9.77,0.00,0.00,10:15:30
"""

# 同花顺 CSV 模板
TONGHUASHUN_CSV = """发生日期,证券代码,证券简称,业务名称,成交价格,成交数量,成交金额,手续费,印花税,过户费,其他费用,成交时间
2024年01月15日,000858,五粮液,证券买入,156.80,100,15680.00,7.84,0.00,0.00,0.00,09:30:00
2024年02月20日,000858,五粮液,证券卖出,162.50,100,16250.00,8.13,8.13,0.00,0.00,10:20:00
"""

# 含错误数据的 CSV（用于验证测试）
INVALID_CSV = """成交日期,证券代码,证券名称,操作,成交均价,成交数量,成交金额,手续费,印花税,过户费,其他费用
2024-01-15,000001,平安银行,买入,11.250,1000,11250.00,5.63,0.00,0.00,0.00
2099-12-31,000002,万科A,买入,0,1000,99999.00,0.00,0.00,0.00,0.00
2024-02-20,000001,平安银行,卖出,11.800,1000,50000.00,5.90,5.90,0.00,0.00
invalid,600000,浦发银行,买入,7.450,-100,14900.00,7.45,0.00,0.00,0.00
"""


def write_temp_csv(content: str, filename: str = 'test.csv') -> str:
    """写入临时 CSV 文件，返回路径"""
    tmp_dir = Path(tempfile.gettempdir()) / 'trades_test'
    tmp_dir.mkdir(exist_ok=True)
    file_path = tmp_dir / filename
    with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(content)
    return str(file_path)


# ============================================================
# 测试用例
# ============================================================

class TestModels:
    """数据模型测试"""

    def test_normalize_stock_code(self):
        assert normalize_stock_code('000001') == '000001.SZ'
        assert normalize_stock_code('600000') == '600000.SH'
        assert normalize_stock_code('000001.SZ') == '000001.SZ'
        assert normalize_stock_code('SZ000001') == '000001.SZ'
        assert normalize_stock_code('300750') == '300750.SZ'
        assert normalize_stock_code('688981') == '688981.SH'

    def test_normalize_trade_type(self):
        assert normalize_trade_type('买入') == 'buy'
        assert normalize_trade_type('卖出') == 'sell'
        assert normalize_trade_type('证券买入') == 'buy'
        assert normalize_trade_type('证券卖出') == 'sell'
        assert normalize_trade_type('B') == 'buy'
        assert normalize_trade_type('S') == 'sell'
        assert normalize_trade_type('未知') == ''

    def test_trade_record_calc(self):
        record = TradeRecord(
            trade_date='2024-01-15',
            stock_code='000001.SZ',
            stock_name='平安银行',
            trade_type='buy',
            price=11.25,
            quantity=1000,
            amount=11250.0,
            commission=5.63,
        )
        assert record.total_fee == 5.63
        # 买入净额 = -金额 - 费用
        assert record.net_amount == -11255.63

        sell = TradeRecord(
            trade_date='2024-02-20',
            stock_code='000001.SZ',
            stock_name='平安银行',
            trade_type='sell',
            price=11.80,
            quantity=1000,
            amount=11800.0,
            commission=5.90,
            stamp_tax=5.90,
        )
        assert sell.total_fee == 11.80
        # 卖出净额 = 金额 - 费用
        assert sell.net_amount == 11788.20


class TestCSVParser:
    """CSV 解析器测试"""

    def test_parse_huatai(self):
        """测试华泰证券格式"""
        file_path = write_temp_csv(HUATAI_CSV, 'huatai.csv')
        parser = TradeCSVParser()
        records, broker, warnings = parser.parse(file_path)

        assert broker == BrokerFormat.HUATAI
        assert len(records) == 4
        assert records[0].stock_code == '000001.SZ'
        assert records[0].trade_type == 'buy'
        assert records[0].price == 11.25
        assert records[0].quantity == 1000
        assert records[0].broker == 'huatai'

    def test_parse_citic(self):
        """测试中信证券格式"""
        file_path = write_temp_csv(CITIC_CSV, 'citic.csv')
        parser = TradeCSVParser()
        records, broker, warnings = parser.parse(file_path)

        assert broker == BrokerFormat.CITIC
        assert len(records) == 2
        assert records[0].stock_code == '000002.SZ'
        assert records[1].trade_type == 'sell'

    def test_parse_guojin(self):
        """测试国金证券格式（YYYYMMDD日期格式）"""
        file_path = write_temp_csv(GUOJIN_CSV, 'guojin.csv')
        parser = TradeCSVParser()
        records, broker, warnings = parser.parse(file_path)

        assert broker == BrokerFormat.GUOJIN
        assert len(records) == 2
        assert records[0].trade_date == '2024-03-15'
        assert records[0].stock_code == '600519.SH'

    def test_parse_eastmoney(self):
        """测试东方财富格式（YYYY/MM/DD日期格式）"""
        file_path = write_temp_csv(EASTMONEY_CSV, 'eastmoney.csv')
        parser = TradeCSVParser()
        records, broker, warnings = parser.parse(file_path)

        assert broker == BrokerFormat.EASTMONEY
        assert len(records) == 2
        assert records[0].trade_date == '2024-01-15'
        assert records[0].stock_code == '300750.SZ'

    def test_parse_tonghuashun(self):
        """测试同花顺格式（YYYY年MM月DD日日期格式）"""
        file_path = write_temp_csv(TONGHUASHUN_CSV, 'tonghuashun.csv')
        parser = TradeCSVParser()
        records, broker, warnings = parser.parse(file_path)

        assert broker == BrokerFormat.TONGHUASHUN
        assert len(records) == 2
        assert records[0].trade_date == '2024-01-15'
        assert records[0].stock_name == '五粮液'

    def test_detect_broker(self):
        """测试券商格式自动识别"""
        parser = TradeCSVParser()
        # 华泰特征：成交日期、操作、成交均价
        cols = ['成交日期', '证券代码', '证券名称', '操作', '成交均价', '成交数量', '成交金额', '手续费']
        broker = parser.detect_broker(cols)
        assert broker == BrokerFormat.HUATAI

    def test_specified_broker(self):
        """测试指定券商格式"""
        file_path = write_temp_csv(HUATAI_CSV, 'specified.csv')
        parser = TradeCSVParser()
        records, broker, _ = parser.parse(file_path, broker='huatai')
        assert broker == BrokerFormat.HUATAI
        assert len(records) == 4


class TestValidator:
    """数据验证器测试"""

    def test_valid_records(self):
        """测试有效记录"""
        records = [
            TradeRecord(
                trade_date='2024-01-15', stock_code='000001.SZ', stock_name='平安银行',
                trade_type='buy', price=11.25, quantity=1000, amount=11250.0,
            ),
            TradeRecord(
                trade_date='2024-02-20', stock_code='000001.SZ', stock_name='平安银行',
                trade_type='sell', price=11.80, quantity=1000, amount=11800.0,
            ),
        ]
        validator = TradeValidator()
        result = validator.validate(records)
        assert result.is_valid
        assert result.valid_count == 2
        assert result.invalid_count == 0

    def test_invalid_records(self):
        """测试无效记录"""
        records = [
            # 价格为0
            TradeRecord(
                trade_date='2024-01-15', stock_code='000001.SZ', stock_name='平安银行',
                trade_type='buy', price=0, quantity=1000, amount=0,
            ),
            # 日期格式错误
            TradeRecord(
                trade_date='invalid', stock_code='000001.SZ', stock_name='平安银行',
                trade_type='buy', price=11.25, quantity=1000, amount=11250.0,
            ),
            # 金额不一致
            TradeRecord(
                trade_date='2024-01-15', stock_code='600000.SH', stock_name='浦发银行',
                trade_type='buy', price=7.45, quantity=2000, amount=50000.0,
            ),
            # 未来日期
            TradeRecord(
                trade_date='2099-12-31', stock_code='600000.SH', stock_name='浦发银行',
                trade_type='sell', price=7.62, quantity=2000, amount=15240.0,
            ),
        ]
        validator = TradeValidator()
        result = validator.validate(records)
        assert not result.is_valid
        assert result.invalid_count == 4
        assert result.valid_count == 0
        # 检查错误类型
        error_types = {e.error_type for e in result.errors}
        assert 'range' in error_types
        assert 'format' in error_types
        assert 'business' in error_types

    def test_parse_invalid_csv(self):
        """测试含错误数据的CSV解析"""
        file_path = write_temp_csv(INVALID_CSV, 'invalid.csv')
        parser = TradeCSVParser()
        records, broker, warnings = parser.parse(file_path)
        # 应该跳过无法解析的行
        assert len(records) > 0
        assert len(warnings) > 0


class TestRepository:
    """数据库仓储测试"""

    def _get_test_db(self):
        """获取测试数据库"""
        from src.data.database import DatabaseManager
        tmp_dir = Path(tempfile.gettempdir()) / 'trades_test_db'
        tmp_dir.mkdir(exist_ok=True)
        db_path = str(tmp_dir / 'test.db')
        # 删除旧数据库
        if os.path.exists(db_path):
            os.remove(db_path)
        return DatabaseManager(db_path)

    def test_insert_and_query(self):
        """测试插入和查询"""
        db = self._get_test_db()
        repo = TradeRepository(db)

        records = [
            TradeRecord(
                trade_date='2024-01-15', stock_code='000001.SZ', stock_name='平安银行',
                trade_type='buy', price=11.25, quantity=1000, amount=11250.0,
                commission=5.63, broker='huatai',
            ),
            TradeRecord(
                trade_date='2024-02-20', stock_code='000001.SZ', stock_name='平安银行',
                trade_type='sell', price=11.80, quantity=1000, amount=11800.0,
                commission=5.90, stamp_tax=5.90, broker='huatai',
            ),
        ]

        inserted, skipped = repo.insert_records(records, source_file='test.csv')
        assert inserted == 2
        assert skipped == 0

        # 查询验证
        df = repo.get_records()
        assert len(df) == 2
        assert df.iloc[0]['stock_code'] == '000001.SZ'

        # 统计
        summary = repo.get_summary()
        assert summary['total_records'] == 2
        assert summary['buy_count'] == 1
        assert summary['sell_count'] == 1
        assert summary['total_buy_amount'] == 11250.0
        assert summary['total_sell_amount'] == 11800.0

    def test_duplicate_skip(self):
        """测试重复记录跳过"""
        db = self._get_test_db()
        repo = TradeRepository(db)

        record = TradeRecord(
            trade_date='2024-01-15', stock_code='000001.SZ', stock_name='平安银行',
            trade_type='buy', price=11.25, quantity=1000, amount=11250.0,
        )

        # 第一次插入
        inserted, skipped = repo.insert_records([record])
        assert inserted == 1

        # 第二次插入（重复）
        inserted, skipped = repo.insert_records([record])
        assert inserted == 0
        assert skipped == 1


class TestReporter:
    """报表生成器测试"""

    def test_generate_report(self):
        """测试报表生成"""
        from src.data.database import DatabaseManager
        tmp_dir = Path(tempfile.gettempdir()) / 'trades_report_test'
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir()

        db_path = str(tmp_dir / 'test.db')
        db = DatabaseManager(db_path)
        repo = TradeRepository(db)
        reporter = TradeReporter(db)

        # 插入测试数据
        records = [
            TradeRecord(
                trade_date='2024-01-15', stock_code='000001.SZ', stock_name='平安银行',
                trade_type='buy', price=11.25, quantity=1000, amount=11250.0,
                commission=5.63, broker='huatai',
            ),
            TradeRecord(
                trade_date='2024-02-20', stock_code='000001.SZ', stock_name='平安银行',
                trade_type='sell', price=11.80, quantity=1000, amount=11800.0,
                commission=5.90, stamp_tax=5.90, broker='huatai',
            ),
        ]
        repo.insert_records(records, source_file='test.csv')

        # 生成报表
        output_dir = str(tmp_dir / 'report')
        html_path = reporter.generate_report(output_dir=output_dir)

        assert os.path.exists(html_path)

        # 验证 JSON 文件
        import json
        with open(Path(output_dir) / 'performance.json', 'r', encoding='utf-8') as f:
            perf = json.load(f)
        assert perf['total_trades'] == 2
        assert perf['buy_count'] == 1
        assert perf['sell_count'] == 1

        # 验证 HTML 内容
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
        assert '历史交易记录报表' in html
        assert '平安银行' in html


class TestPerformance:
    """性能测试"""

    def test_large_file(self):
        """测试大文件解析性能（10000行）"""
        # 生成大文件
        lines = ['成交日期,证券代码,证券名称,操作,成交均价,成交数量,成交金额,手续费,印花税,过户费,其他费用']
        for i in range(10000):
            date = f'2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}'
            code = f'{(i % 10):06d}'
            name = f'股票{i % 10}'
            action = '买入' if i % 2 == 0 else '卖出'
            price = 10.0 + (i % 100) * 0.1
            qty = 100 * ((i % 50) + 1)
            amount = price * qty
            fee = amount * 0.0003
            lines.append(f'{date},{code},{name},{action},{price:.3f},{qty},{amount:.2f},{fee:.2f},0.00,0.00,0.00')

        file_path = write_temp_csv('\n'.join(lines), 'large.csv')

        start = datetime.now()
        parser = TradeCSVParser()
        records, broker, warnings = parser.parse(file_path)
        elapsed = (datetime.now() - start).total_seconds()

        assert len(records) == 10000
        print(f"\n大文件解析: {len(records)} 行, 耗时 {elapsed:.2f}s")
        assert elapsed < 10.0  # 应在10秒内完成


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("历史交易记录导入功能测试")
    print("=" * 60)

    test_classes = [
        TestModels(),
        TestCSVParser(),
        TestValidator(),
        TestRepository(),
        TestReporter(),
        TestPerformance(),
    ]

    total = 0
    passed = 0
    failed = 0

    for test_class in test_classes:
        class_name = test_class.__class__.__name__
        print(f"\n[{class_name}]")
        methods = [m for m in dir(test_class) if m.startswith('test_')]
        for method_name in methods:
            total += 1
            try:
                getattr(test_class, method_name)()
                print(f"  ✓ {method_name}")
                passed += 1
            except Exception as e:
                print(f"  ✗ {method_name}: {e}")
                import traceback
                traceback.print_exc()
                failed += 1

    print(f"\n{'=' * 60}")
    print(f"测试结果: {passed}/{total} 通过, {failed} 失败")
    print(f"{'=' * 60}")
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
