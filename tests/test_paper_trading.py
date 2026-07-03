"""
模拟交易模块（Paper Trading）单元测试

覆盖范围：
1. 费用计算（佣金最低5元、万三、印花税、过户费）
2. 买入/卖出撮合（资金扣减、持仓建立/移除、盈亏计算）
3. Pending 订单次日撮合（资金冻结/解冻）
4. 每日结算（净值快照、回撤）
5. 数据库 CRUD 接口
6. 编排器驱动 mock 策略生成订单

运行命令:
    python -X utf8 -m pytest tests/test_paper_trading.py -v
    （需设置 PYTHONPATH=. ）
"""

import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd

from src.data.database import DatabaseManager
from src.engine.types import Order, Direction, Position
from src.paper_trading.engine import PaperTradingEngine
from src.paper_trading.config import PAPER_TRADING_CONFIG


# ----------------------------------------------------------------------
# 测试夹具：临时数据库
# ----------------------------------------------------------------------

@pytest.fixture
def tmp_db():
    """创建临时数据库（每个测试函数独立）"""
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    db = DatabaseManager(tmp.name)
    yield db
    # 清理
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


@pytest.fixture
def engine(tmp_db):
    """创建已加载账户的引擎"""
    eng = PaperTradingEngine(
        db=tmp_db,
        strategy_id='test_id',
        strategy_name='test_strategy',
        version='v1',
    )
    eng.load_or_init_account()
    return eng


# ----------------------------------------------------------------------
# 1. 费用计算测试
# ----------------------------------------------------------------------

class TestCostCalc:
    """测试买入成本与卖出费用计算"""

    def test_buy_cost_normal(self, engine):
        """正常买入成本：佣金=万三，过户费=万分之零点一"""
        # 10元 * 1000股 = 10000元
        cost = engine.calc_buy_cost(price=10.0, quantity=1000)
        assert cost['amount'] == 10000.0
        # 佣金 = 10000 * 0.0003 = 3.0，低于5元最低标准 → 取5元
        assert cost['commission'] == 5.0
        # 过户费 = 10000 * 0.00001 = 0.1
        assert cost['transfer_fee'] == pytest.approx(0.1)
        # 总成本 = 10000 + 5 + 0.1 = 10005.1
        assert cost['total_cost'] == pytest.approx(10005.1)

    def test_buy_cost_large(self, engine):
        """大额买入：佣金按万三计算（超过最低5元）"""
        # 10元 * 10000股 = 100000元
        cost = engine.calc_buy_cost(price=10.0, quantity=10000)
        assert cost['amount'] == 100000.0
        # 佣金 = 100000 * 0.0003 = 30元（超过5元最低）
        assert cost['commission'] == pytest.approx(30.0)
        assert cost['transfer_fee'] == pytest.approx(1.0)
        assert cost['total_cost'] == pytest.approx(100031.0)

    def test_sell_fee_normal(self, engine):
        """卖出费用：佣金+印花税+过户费"""
        # 10元 * 1000股 = 10000元
        fee = engine.calc_sell_fee(price=10.0, quantity=1000)
        assert fee['amount'] == 10000.0
        # 佣金 = 5元（最低）
        assert fee['commission'] == 5.0
        # 印花税 = 10000 * 0.001 = 10元
        assert fee['stamp_duty'] == pytest.approx(10.0)
        # 过户费 = 0.1
        assert fee['transfer_fee'] == pytest.approx(0.1)
        # 净收入 = 10000 - 5 - 10 - 0.1 = 9984.9
        assert fee['net_proceeds'] == pytest.approx(9984.9)


# ----------------------------------------------------------------------
# 2. 买入撮合测试
# ----------------------------------------------------------------------

class TestExecuteBuy:
    """测试买入撮合逻辑"""

    def test_buy_success(self, engine):
        """成功买入：资金扣减、持仓建立、成交记录"""
        success = engine.execute_buy(
            stock_code='600000.SH', quantity=1000, price=10.0,
            trade_date='2024-01-02', reason='选股信号',
        )
        assert success is True
        # 检查资金扣减
        cost = engine.calc_buy_cost(10.0, 1000)
        assert engine.cash == pytest.approx(1_000_000 - cost['total_cost'])
        # 检查持仓
        assert '600000.SH' in engine.positions
        pos = engine.positions['600000.SH']
        assert pos.quantity == 1000
        assert pos.entry_price == 10.0
        # 检查数据库持仓记录
        db_positions = engine.db.get_paper_positions('test_id')
        assert len(db_positions) == 1
        assert db_positions[0]['stock_code'] == '600000.SH'
        # 检查成交记录
        trades = engine.db.get_paper_trades('test_id')
        assert len(trades) == 1
        assert trades[0]['direction'] == 'long'

    def test_buy_insufficient_cash(self, engine):
        """资金不足拒绝买入"""
        # 100元 * 10000股 = 1,000,000 元，超过初始资金
        success = engine.execute_buy(
            stock_code='600000.SH', quantity=10000, price=100.0,
            trade_date='2024-01-02',
        )
        assert success is False
        assert engine.cash == 1_000_000  # 资金未变
        assert len(engine.positions) == 0

    def test_buy_invalid_quantity(self, engine):
        """非100整数倍拒绝"""
        success = engine.execute_buy(
            stock_code='600000.SH', quantity=150, price=10.0,
            trade_date='2024-01-02',
        )
        assert success is False

    def test_buy_duplicate_position(self, engine):
        """已有持仓不再加仓"""
        engine.execute_buy('600000.SH', 1000, 10.0, '2024-01-02')
        success = engine.execute_buy('600000.SH', 1000, 10.0, '2024-01-03')
        assert success is False
        assert engine.positions['600000.SH'].quantity == 1000


# ----------------------------------------------------------------------
# 3. 卖出撮合测试
# ----------------------------------------------------------------------

class TestExecuteSell:
    """测试卖出撮合逻辑"""

    def test_sell_success(self, engine):
        """成功卖出：持仓移除、资金增加、盈亏记录"""
        # 先买入
        engine.execute_buy('600000.SH', 1000, 10.0, '2024-01-02')
        cash_after_buy = engine.cash

        # 卖出（12元，盈利）
        success = engine.execute_sell(
            stock_code='600000.SH', quantity=1000, price=12.0,
            trade_date='2024-01-03', reason='止盈',
        )
        assert success is True
        # 检查持仓移除
        assert '600000.SH' not in engine.positions
        # 检查资金增加
        fee = engine.calc_sell_fee(12.0, 1000)
        assert engine.cash == pytest.approx(cash_after_buy + fee['net_proceeds'])
        # 检查成交记录（2笔：买+卖）
        trades = engine.db.get_paper_trades('test_id')
        assert len(trades) == 2
        assert trades[1]['direction'] == 'short'

    def test_sell_no_position(self, engine):
        """无持仓卖出拒绝"""
        success = engine.execute_sell('600000.SH', 1000, 10.0, '2024-01-02')
        assert success is False

    def test_sell_quantity_exceeds(self, engine):
        """卖出数量超过持仓拒绝"""
        engine.execute_buy('600000.SH', 1000, 10.0, '2024-01-02')
        success = engine.execute_sell('600000.SH', 2000, 10.0, '2024-01-03')
        assert success is False
        assert engine.positions['600000.SH'].quantity == 1000


# ----------------------------------------------------------------------
# 4. Pending 订单（next_open）测试
# ----------------------------------------------------------------------

class TestPendingOrder:
    """测试次日开盘订单的冻结与撮合"""

    def test_freeze_and_pending_buy(self, engine):
        """冻结买单资金 → 次日开盘撮合成交"""
        # 冻结资金（按 close 价预估）
        order_id = engine.freeze_for_buy(
            stock_code='600000.SH', quantity=1000, price=10.0,
            trade_date='2024-01-02', reason='选股',
        )
        assert order_id is not None
        # 检查资金冻结
        cost = engine.calc_buy_cost(10.0, 1000)
        assert engine.cash == pytest.approx(1_000_000 - cost['total_cost'])
        assert engine.frozen_cash == pytest.approx(cost['total_cost'])

        # 检查 pending 订单
        pending = engine.db.get_pending_orders('test_id')
        assert len(pending) == 1
        assert pending[0]['status'] == 'pending'

        # 次日开盘撮合（open 价 10.5）
        success = engine.execute_pending_buy(
            order_id=order_id, stock_code='600000.SH', quantity=1000,
            frozen_amount=cost['total_cost'], open_price=10.5,
            trade_date='2024-01-03',
        )
        assert success is True
        # 冻结资金已释放
        assert engine.frozen_cash == 0.0
        # 持仓建立，开仓价为 open 价
        assert engine.positions['600000.SH'].entry_price == 10.5
        # 订单状态更新为 filled
        pending = engine.db.get_pending_orders('test_id')
        assert len(pending) == 0  # pending 列表为空（已成交）

    def test_freeze_insufficient_cash(self, engine):
        """资金不足冻结失败"""
        order_id = engine.freeze_for_buy(
            stock_code='600000.SH', quantity=100000, price=100.0,
            trade_date='2024-01-02',
        )
        assert order_id is None
        assert engine.frozen_cash == 0.0


# ----------------------------------------------------------------------
# 5. 每日结算测试
# ----------------------------------------------------------------------

class TestSettleDaily:
    """测试每日结算与净值快照"""

    def test_settle_no_position(self, engine):
        """无持仓结算：总资产=现金"""
        result = engine.settle_daily('2024-01-02', {})
        assert result['total_value'] == pytest.approx(1_000_000)
        assert result['position_value'] == 0.0
        assert result['daily_return'] == 0.0

    def test_settle_with_position(self, engine):
        """有持仓结算：总资产=现金+持仓市值"""
        # 买入 1000股 @10元
        engine.execute_buy('600000.SH', 1000, 10.0, '2024-01-02')
        cash_after_buy = engine.cash

        # 结算：收盘价 11元
        result = engine.settle_daily('2024-01-02', {'600000.SH': 11.0})
        # 持仓市值 = 11 * 1000 = 11000
        assert result['position_value'] == pytest.approx(11000.0)
        # 总资产 = cash + 11000
        assert result['total_value'] == pytest.approx(cash_after_buy + 11000.0)

        # 检查快照写入
        snapshots = engine.db.get_paper_snapshots('test_id')
        assert len(snapshots) == 1
        assert snapshots[0]['trade_date'] == '2024-01-02'

    def test_settle_drawdown(self, engine):
        """回撤计算：资产下跌后回撤为正"""
        # 先结算一个高点
        engine.settle_daily('2024-01-02', {})
        # 调整现金模拟亏损（提取资金）
        engine.cash = 900_000
        engine._save_account()
        # 结算
        result = engine.settle_daily('2024-01-03', {})
        # 回撤 = (1M - 900K) / 1M = 10%
        assert result['max_drawdown'] == pytest.approx(0.1, abs=0.01)


# ----------------------------------------------------------------------
# 6. 数据库 CRUD 测试
# ----------------------------------------------------------------------

class TestDatabaseCRUD:
    """测试模拟交易数据库 CRUD 接口"""

    def test_account_upsert(self, tmp_db):
        """账户 upsert：重复保存更新而非报错"""
        tmp_db.save_paper_account({
            'strategy_id': 's1', 'strategy_name': 'test', 'version': 'v1',
            'initial_capital': 1_000_000, 'cash': 1_000_000, 'frozen_cash': 0,
            'total_value': 1_000_000, 'peak_value': 1_000_000,
        })
        # 再次保存（更新）
        tmp_db.save_paper_account({
            'strategy_id': 's1', 'strategy_name': 'test', 'version': 'v1',
            'initial_capital': 1_000_000, 'cash': 990_000, 'frozen_cash': 0,
            'total_value': 990_000, 'peak_value': 1_000_000,
        })
        acc = tmp_db.get_paper_account('s1')
        assert acc['cash'] == 990_000

    def test_position_upsert(self, tmp_db):
        """持仓 upsert"""
        tmp_db.save_paper_position({
            'strategy_id': 's1', 'stock_code': '600000.SH', 'direction': 'long',
            'quantity': 1000, 'entry_price': 10.0, 'entry_date': '2024-01-02',
            'current_price': 10.0, 'value': 10000.0,
        })
        # 更新现价
        tmp_db.save_paper_position({
            'strategy_id': 's1', 'stock_code': '600000.SH', 'direction': 'long',
            'quantity': 1000, 'entry_price': 10.0, 'entry_date': '2024-01-02',
            'current_price': 11.0, 'value': 11000.0,
        })
        positions = tmp_db.get_paper_positions('s1')
        assert len(positions) == 1
        assert positions[0]['current_price'] == 11.0

    def test_order_and_trade(self, tmp_db):
        """订单与成交记录"""
        order_id = tmp_db.insert_paper_order({
            'strategy_id': 's1', 'stock_code': '600000.SH', 'direction': 'long',
            'quantity': 1000, 'price_type': 'close', 'reason': '选股',
            'status': 'pending', 'created_date': '2024-01-02',
        })
        assert order_id > 0
        # 更新状态
        tmp_db.update_paper_order_status(order_id, 'filled')
        pending = tmp_db.get_pending_orders('s1')
        assert len(pending) == 0  # 已 filled，不在 pending 列表

        # 插入成交
        trade_id = tmp_db.insert_paper_trade({
            'order_id': order_id, 'strategy_id': 's1', 'stock_code': '600000.SH',
            'direction': 'long', 'quantity': 1000, 'price': 10.0, 'amount': 10000.0,
            'commission': 5.0, 'slippage': 0.1, 'trade_date': '2024-01-02',
        })
        assert trade_id > 0
        trades = tmp_db.get_paper_trades('s1')
        assert len(trades) == 1

    def test_snapshot_unique(self, tmp_db):
        """快照唯一约束：同一策略同一日期只保留一条"""
        tmp_db.insert_paper_snapshot({
            'strategy_id': 's1', 'trade_date': '2024-01-02', 'cash': 1_000_000,
            'position_value': 0, 'total_value': 1_000_000, 'daily_return': 0,
            'max_drawdown': 0,
        })
        # 同日再次插入（更新）
        tmp_db.insert_paper_snapshot({
            'strategy_id': 's1', 'trade_date': '2024-01-02', 'cash': 990_000,
            'position_value': 0, 'total_value': 990_000, 'daily_return': -0.01,
            'max_drawdown': 0.01,
        })
        snapshots = tmp_db.get_paper_snapshots('s1')
        assert len(snapshots) == 1
        assert snapshots[0]['cash'] == 990_000

    def test_reset(self, tmp_db):
        """重置功能"""
        # 插入数据
        tmp_db.save_paper_account({
            'strategy_id': 's1', 'strategy_name': 'test', 'version': 'v1',
            'initial_capital': 1_000_000, 'cash': 1_000_000, 'frozen_cash': 0,
            'total_value': 1_000_000, 'peak_value': 1_000_000,
        })
        tmp_db.insert_paper_snapshot({
            'strategy_id': 's1', 'trade_date': '2024-01-02', 'cash': 1_000_000,
            'position_value': 0, 'total_value': 1_000_000, 'daily_return': 0,
            'max_drawdown': 0,
        })
        # 重置
        tmp_db.reset_paper_trading('s1')
        assert tmp_db.get_paper_account('s1') is None
        assert len(tmp_db.get_paper_snapshots('s1')) == 0

    def test_adjust_cash(self, tmp_db):
        """手动调整现金"""
        tmp_db.save_paper_account({
            'strategy_id': 's1', 'strategy_name': 'test', 'version': 'v1',
            'initial_capital': 1_000_000, 'cash': 1_000_000, 'frozen_cash': 0,
            'total_value': 1_000_000, 'peak_value': 1_000_000,
        })
        # 充值
        acc = tmp_db.adjust_paper_cash('s1', 100_000)
        assert acc['cash'] == 1_100_000
        # 提取
        acc = tmp_db.adjust_paper_cash('s1', -50_000)
        assert acc['cash'] == 1_050_000
        # 提取超额
        acc = tmp_db.adjust_paper_cash('s1', -2_000_000)
        assert acc is None


# ----------------------------------------------------------------------
# 7. 编排器 mock 策略测试
# ----------------------------------------------------------------------

class TestOrchestrator:
    """测试编排器驱动 mock 策略"""

    def test_orchestrator_with_mock_strategy(self, tmp_db, monkeypatch):
        """用 mock 策略测试编排器基本流程"""
        from src.paper_trading.orchestrator import PaperTradingOrchestrator
        from src.engine.base_strategy import BaseStrategy, StrategyRegistry

        # 注册 mock 策略
        class MockStrategy(BaseStrategy):
            name = "mock_test"
            description = "测试用 mock 策略"
            default_params = {
                'position_size': 0.10,
                'max_positions': 5,
                'commission_rate': 0.0003,
                'slippage': 0.0,
                'db_path': '',
            }

            def on_init(self, context):
                pass

            def on_bar(self, context):
                # 第一天买入
                if str(context.date)[:10] == '2024-01-02':
                    return [Order(
                        stock_code='600000.SH',
                        direction=Direction.LONG,
                        quantity=1000,
                        reason='mock选股',
                    )]
                return []

        # 清理可能已注册的同名策略
        StrategyRegistry._strategies.pop('mock_test', None)
        StrategyRegistry.register(MockStrategy)

        # 在测试数据库中准备市场数据
        trade_date = '2024-01-02'
        df = pd.DataFrame([
            {
                'trade_date': trade_date, 'stock_code': '600000.SH',
                'open': 10.0, 'high': 10.5, 'low': 9.8, 'close': 10.2,
                'volume': 100000, 'amount': 1020000, 'pre_close': 10.0,
            }
        ])
        tmp_db.insert_stock_daily(df)

        # 注册策略版本到数据库
        tmp_db.register_strategy_version(
            strategy_id='mock_id', strategy_name='mock_test', version='v1',
            file_path='src/strategies/mock/mock_v1.py', description='测试',
            is_active=1,
        )

        # mock 编排器的数据库路径与策略加载
        orch = PaperTradingOrchestrator(db_path=None, price_type='close')
        # 替换数据库为测试数据库
        orch.db = tmp_db
        # mock auto_discover 为空操作（避免扫描真实策略目录）；
        # MockStrategy 已通过 register 注册到 StrategyRegistry，get 可直接返回
        monkeypatch.setattr(
            StrategyRegistry, 'auto_discover',
            classmethod(lambda cls, *a, **kw: None)
        )

        # 执行
        orch.run_daily_process(trade_date, strategy_name='mock_test')

        # 验证：账户已创建，持仓已建立
        account = tmp_db.get_paper_account('mock_id')
        assert account is not None
        assert account['strategy_name'] == 'mock_test'

        positions = tmp_db.get_paper_positions('mock_id')
        assert len(positions) == 1
        assert positions[0]['stock_code'] == '600000.SH'
        assert positions[0]['quantity'] == 1000

        # 验证快照
        snapshots = tmp_db.get_paper_snapshots('mock_id')
        assert len(snapshots) == 1
        assert snapshots[0]['trade_date'] == trade_date

        # 清理注册
        StrategyRegistry._strategies.pop('mock_test', None)
