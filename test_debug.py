"""
调试测试
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

from src.engine import BaseStrategy, BacktestEngine, register_strategy
from src.engine.types import Order, Direction, Context

@register_strategy
class DebugStrategy(BaseStrategy):
    name = "debug_strategy"
    description = "调试策略"
    
    def on_init(self, context):
        print(f"  on_init: full_data shape = {context.full_data.shape if context.full_data is not None else 'None'}")
    
    def on_bar(self, context):
        print(f"  on_bar: date={context.date.strftime('%Y-%m-%d')}, positions={len(context.positions)}, market_data keys={list(context.market_data.keys())[:3]}")
        
        orders = []
        
        # 卖出持仓
        for stock_code, position in list(context.positions.items()):
            print(f"    卖出: {stock_code}")
            exit_direction = Direction.SHORT if position.direction == Direction.LONG else Direction.LONG
            orders.append(Order(
                stock_code=stock_code,
                direction=exit_direction,
                quantity=position.quantity,
                reason="卖出"
            ))
        
        # 买入
        if not context.positions and context.market_data:
            first_stock = list(context.market_data.keys())[0]
            price = context.market_data[first_stock].get('close', 0)
            print(f"    尝试买入: {first_stock}, price={price}")
            if price > 0:
                qty = int(context.cash * 0.1 / price / 100) * 100
                print(f"    计算数量: {qty}")
                if qty >= 100:
                    orders.append(Order(
                        stock_code=first_stock,
                        direction=Direction.LONG,
                        quantity=qty,
                        reason="买入"
                    ))
                    print(f"    添加买入订单: {first_stock} x {qty}")
        
        return orders

# 创建模拟数据
dates = pd.date_range('2024-01-01', '2024-01-10', freq='B')
stock_codes = ['000001.SZ', '000002.SZ']

price_data = []
for date in dates:
    for code in stock_codes:
        price = 10.0 if code == '000001.SZ' else 20.0
        price_data.append({
            'trade_date': date,
            'stock_code': code,
            'open': price * 0.99,
            'high': price * 1.02,
            'low': price * 0.98,
            'close': price,
            'volume': 100000,
        })

price_df = pd.DataFrame(price_data)
price_df.set_index(['trade_date', 'stock_code'], inplace=True)

print(f"数据: {len(price_df)} 条")
print(f"日期: {dates[0]} ~ {dates[-1]}")

# 运行回测
strategy = DebugStrategy()
engine = BacktestEngine(strategy=strategy, initial_capital=1_000_000)

print("\n开始回测...")
result = engine.run(price_df)

print(f"\n回测结果:")
print(f"  交易次数: {len(result.trades)}")
for t in result.trades:
    print(f"    {t.date.strftime('%Y-%m-%d')}: {t.action} {t.stock_code} {t.quantity}股 @ {t.price:.2f}")
