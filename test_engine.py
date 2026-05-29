"""
通用回测引擎测试脚本
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 测试1: 导入测试
print("=" * 60)
print("测试1: 模块导入")
print("=" * 60)
try:
    from src.engine import BaseStrategy, BacktestEngine, StrategyRegistry, register_strategy
    from src.engine.types import Order, Direction, Context, BacktestResult, Position
    print("✓ 引擎模块导入成功")
except Exception as e:
    print(f"✗ 导入失败: {e}")
    sys.exit(1)

# 测试2: 创建简单策略
print("\n" + "=" * 60)
print("测试2: 创建测试策略")
print("=" * 60)

@register_strategy
class TestStrategy(BaseStrategy):
    """测试策略 - 每日随机买入一只股票，持有1天卖出"""
    
    name = "test_strategy"
    description = "测试策略 - 每日买入第一只股票"
    
    default_params = {
        **BaseStrategy.default_params,
        'buy_threshold': 0,
    }
    
    def on_init(self, context):
        """初始化"""
        print(f"  策略初始化: 共 {len(context.full_data) if context.full_data is not None else 0} 条数据")
    
    def on_bar(self, context):
        """每日交易逻辑 - 隔日交易：有持仓就卖，没持仓就买"""
        orders = []
        
        # 如果有持仓，卖出（使用相反方向表示平仓）
        for stock_code, position in list(context.positions.items()):
            # 平仓订单：方向与持仓相反
            exit_direction = Direction.SHORT if position.direction == Direction.LONG else Direction.LONG
            orders.append(Order(
                stock_code=stock_code,
                direction=exit_direction,  # 相反方向表示平仓
                quantity=position.quantity,
                reason="测试卖出"
            ))
        
        # 如果没有持仓，买入第一只
        if not context.positions and context.market_data:
            first_stock = list(context.market_data.keys())[0]
            price = context.market_data[first_stock].get('close', 0)
            if price > 0:
                qty = int(context.cash * 0.1 / price / 100) * 100
                if qty >= 100:
                    orders.append(Order(
                        stock_code=first_stock,
                        direction=Direction.LONG,
                        quantity=qty,
                        reason="测试买入"
                    ))
        
        return orders

print("✓ 测试策略创建成功")

# 测试3: 创建模拟数据
print("\n" + "=" * 60)
print("测试3: 创建模拟数据")
print("=" * 60)

# 创建模拟价格数据
dates = pd.date_range('2024-01-01', '2024-01-31', freq='B')  # 工作日
stock_codes = ['000001.SZ', '000002.SZ', '000003.SZ']

price_data = []
for date in dates:
    for code in stock_codes:
        base_price = 10.0 if code == '000001.SZ' else 20.0 if code == '000002.SZ' else 30.0
        # 添加随机波动
        price = base_price * (1 + np.random.randn() * 0.02)
        price_data.append({
            'trade_date': date,
            'stock_code': code,
            'open': price * 0.99,
            'high': price * 1.02,
            'low': price * 0.98,
            'close': price,
            'volume': np.random.randint(100000, 1000000),
        })

price_df = pd.DataFrame(price_data)
price_df.set_index(['trade_date', 'stock_code'], inplace=True)

print(f"✓ 创建模拟数据: {len(price_df)} 条记录")
print(f"  日期范围: {dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}")
print(f"  股票数量: {len(stock_codes)}")

# 测试4: 运行回测
print("\n" + "=" * 60)
print("测试4: 运行回测")
print("=" * 60)

try:
    strategy = TestStrategy(
        stop_loss=0.05,
        take_profit=0.10,
        position_size=0.1,
    )
    
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=1_000_000,
        enable_engine_exit=True,
    )
    
    result = engine.run(price_df)
    
    print(f"✓ 回测完成")
    print(f"  策略: {result.strategy_name}")
    print(f"  回测区间: {result.start_date} ~ {result.end_date}")
    print(f"  初始资金: {result.initial_capital:,.2f}")
    print(f"  最终资产: {result.final_value:,.2f}")
    print(f"  总收益率: {result.total_return:.2%}")
    print(f"  交易次数: {len(result.trades)}")
    
except Exception as e:
    print(f"✗ 回测失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试5: 测试逐日检查功能
print("\n" + "=" * 60)
print("测试5: 逐日检查功能")
print("=" * 60)

try:
    # 测试 get_daily_cashflow
    cashflow = result.get_daily_cashflow('2024-01-02')
    print(f"✓ 2024-01-02 现金流查询成功")
    print(f"  可用现金: {cashflow.get('cash', 0):,.2f}")
    
    # 测试 get_daily_positions
    positions = result.get_daily_positions('2024-01-15')
    print(f"✓ 2024-01-15 持仓查询成功")
    print(f"  持仓数量: {len(positions)}")
    
    # 测试 get_trade_history
    trades = result.get_trade_history()
    print(f"✓ 交易历史查询成功")
    print(f"  总交易数: {len(trades)}")
    
except Exception as e:
    print(f"✗ 逐日检查功能测试失败: {e}")
    import traceback
    traceback.print_exc()

# 测试6: 测试策略注册表
print("\n" + "=" * 60)
print("测试6: 策略注册表")
print("=" * 60)

try:
    StrategyRegistry.auto_discover('src.strategies')
    strategies = StrategyRegistry.list_strategies()
    print(f"✓ 策略自动发现成功")
    print(f"  发现策略数: {len(strategies)}")
    for s in strategies:
        print(f"    - {s['name']}: {s['description'][:40]}")
    
    # 获取策略类
    strategy_class = StrategyRegistry.get('test_strategy')
    if strategy_class:
        print(f"✓ 策略获取成功: {strategy_class.__name__}")
    
except Exception as e:
    print(f"✗ 策略注册表测试失败: {e}")
    import traceback
    traceback.print_exc()

# 测试7: 测试出场检查器
print("\n" + "=" * 60)
print("测试7: 出场检查器")
print("=" * 60)

try:
    from src.engine import ExitChecker
    
    # 创建模拟持仓
    test_position = Position(
        stock_code='000001.SZ',
        direction=Direction.LONG,
        quantity=1000,
        entry_price=10.0,
        entry_date=pd.Timestamp('2024-01-01'),
    )
    
    # 创建模拟上下文（价格跌至9.0，触发止损）
    test_context = Context(
        date=pd.Timestamp('2024-01-02'),
        market_data={
            '000001.SZ': {'close': 9.0}  # 下跌10%，触发止损
        },
        positions={'000001.SZ': test_position},
        cash=900000,
        total_value=990000,
    )
    
    exit_checker = ExitChecker({'stop_loss': 0.07, 'take_profit': 0.20})
    result_check = exit_checker.check_all(test_context, test_position)
    
    if result_check.should_exit:
        print(f"✓ 止损检查成功")
        print(f"  触发原因: {result_check.reason}")
    else:
        print(f"✗ 止损检查失败 - 应该触发但未触发")
    
except Exception as e:
    print(f"✗ 出场检查器测试失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成!")
print("=" * 60)
