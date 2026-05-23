"""
区间回踩策略 - 基于新回测框架

策略逻辑：
1. 识别震荡区间（过去N天的最高/最低价）
2. 检测突破信号（价格突破区间上沿）
3. 检测回踩信号（突破后价格回到区间上沿附近）
4. 回踩时开仓做多
5. 出场由引擎级规则管理（止损/ATR跟踪止盈/超时）

这是一个【买入基于策略，卖出基于引擎规则】的示例。
仅支持做多（A股）。
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from enum import Enum

from src.engine import BaseStrategy, register_strategy
from src.engine.types import Order, Direction, Context


class SignalType(Enum):
    """信号类型"""
    NONE = 0
    LONG = 1   # 做多信号
    SHORT = 2  # 做空信号


@register_strategy
class BreakoutPullbackStrategyV2(BaseStrategy):
    """
    区间回踩策略
    
    买入逻辑：突破震荡区间后回踩边界时开仓
    卖出逻辑：引擎级出场检查（止损/止盈/动态止盈/超时）
    
    参数：
    - consolidation_window: 震荡区间识别窗口（默认20天）
    - breakout_threshold: 突破确认阈值（默认1%）
    - pullback_threshold: 回踩确认阈值（默认1%）
    - atr_window: ATR计算窗口（默认14天）
    """
    
    name = "breakout_pullback"
    description = "震荡突破回踩策略 - 突破后回踩边界时开仓"
    
    default_params = {
        **BaseStrategy.default_params,
        'consolidation_window': 20,     # 震荡区间识别窗口
        'breakout_threshold': 0.01,     # 突破确认阈值
        'pullback_threshold': 0.01,     # 回踩确认阈值
        'atr_window': 14,               # ATR计算窗口
    }
    
    def on_init(self, context: Context):
        """
        预计算震荡区间和信号
        
        使用 context.full_data（含预热期的完整数据）预计算指标
        """
        # 获取策略参数
        window = self.params['consolidation_window']
        
        # 使用完整数据（含预热期）预计算指标
        full_data = context.full_data
        if full_data is None or full_data.empty:
            print("警告：没有预热数据，指标计算可能不准确")
            self.consolidation_zones = {}
            self.breakout_history = {}
            self.signals = {}
            return
        
        # 预计算所有股票的震荡区间
        self.consolidation_zones = self._calculate_zones(full_data, window)
        
        # 检测突破历史
        self.breakout_history = self._detect_breakouts(full_data, window)
        
        # 生成信号
        self.signals = self._generate_signals(full_data)
        
        print(f"策略初始化完成：计算了 {len(self.consolidation_zones)} 只股票的震荡区间")
    
    def on_bar(self, context: Context) -> List[Order]:
        """
        每日交易逻辑
        
        买入条件：
        1. 历史上曾向上突破
        2. 当前价格回踩到上沿附近
        
        卖出条件：
        1. 箱体下沿止损（跌破震荡区间下沿）
        2. 引擎级出场检查（止损/ATR跟踪止盈/超时）
        """
        orders = []
        date = context.date
        
        # 先检查持仓是否需要止损（箱体下沿止损）
        for stock_code, position in context.positions.items():
            if stock_code in context.market_data:
                close = context.market_data[stock_code].get('close', 0)
                if close > 0 and self._should_sell(stock_code, date, close):
                    # 用相反方向平仓（多头持仓用 SHORT 方向平仓）
                    orders.append(Order(
                        stock_code=stock_code,
                        direction=Direction.SHORT,  # 与 LONG 相反，表示平仓
                        quantity=position.quantity,
                        reason="箱体下沿止损"
                    ))
        
        # 检查买入信号
        max_positions = self.params.get('max_positions', 0)
        current_positions = len(context.positions)
        new_buy_orders = 0  # 已生成的开仓订单数
        
        for stock_code, data in context.market_data.items():
            close = data.get('close', 0)
            if close <= 0:
                continue
            
            # 检查是否已有持仓（避免重复开仓）
            if stock_code in context.positions:
                continue
            
            # 检查持仓上限（当前持仓 + 已生成订单）
            if max_positions > 0 and current_positions + new_buy_orders >= max_positions:
                break  # 已达持仓上限，停止开仓
            
            # 检查买入信号
            signal = self._should_buy(stock_code, date, close)
            
            if signal == SignalType.LONG:
                # 计算开仓数量
                alloc = context.cash * self.params['position_size']
                qty = int(alloc / close / 100) * 100
                
                if qty >= 100:
                    orders.append(Order(
                        stock_code=stock_code,
                        direction=Direction.LONG,
                        quantity=qty,
                        reason="回踩做多"
                    ))
                    new_buy_orders += 1  # 计数
        
        return orders
    
    def _calculate_zones(self, data: pd.DataFrame, window: int) -> Dict:
        """计算震荡区间（使用含预热期的完整数据）"""
        zones = {}
        
        try:
            stock_codes = data.index.get_level_values('stock_code').unique()
        except:
            # 如果索引结构不同，尝试其他方式获取股票代码
            stock_codes = data['stock_code'].unique() if 'stock_code' in data.columns else []
        
        for stock_code in stock_codes:
            try:
                # 获取单只股票数据
                if isinstance(data.index, pd.MultiIndex):
                    stock_data = data.xs(stock_code, level='stock_code')
                else:
                    stock_data = data[data['stock_code'] == stock_code].copy()
                    if stock_data.empty:
                        continue
                    stock_data = stock_data.set_index('trade_date')
                
                if len(stock_data) < window:
                    continue
                
                # 计算滚动最高/最低价
                stock_data = stock_data.copy()
                stock_data['high_max'] = stock_data['high'].rolling(window=window, min_periods=1).max().shift(1)
                stock_data['low_min'] = stock_data['low'].rolling(window=window, min_periods=1).min().shift(1)
                
                # 保存区间数据
                zones[stock_code] = stock_data[['high_max', 'low_min']].to_dict('index')
            except Exception as e:
                # 跳过计算失败的股票
                continue
        
        return zones
    
    def _detect_breakouts(self, data: pd.DataFrame, window: int) -> Dict:
        """检测突破历史"""
        breakouts = {}
        
        try:
            stock_codes = data.index.get_level_values('stock_code').unique()
        except:
            stock_codes = data['stock_code'].unique() if 'stock_code' in data.columns else []
        
        threshold = self.params['breakout_threshold']
        
        for stock_code in stock_codes:
            try:
                # 获取单只股票数据
                if isinstance(data.index, pd.MultiIndex):
                    stock_data = data.xs(stock_code, level='stock_code')
                else:
                    stock_data = data[data['stock_code'] == stock_code].copy()
                    if stock_data.empty:
                        continue
                    stock_data = stock_data.set_index('trade_date')
                
                if len(stock_data) < window:
                    continue
                
                # 计算区间
                stock_data = stock_data.copy()
                stock_data['high_max'] = stock_data['high'].rolling(window=window, min_periods=1).max().shift(1)
                stock_data['low_min'] = stock_data['low'].rolling(window=window, min_periods=1).min().shift(1)
                
                # 检测突破
                stock_data['breakout_up'] = stock_data['close'] > stock_data['high_max'] * (1 + threshold)
                stock_data['breakout_down'] = stock_data['close'] < stock_data['low_min'] * (1 - threshold)
                
                # 记录突破日期
                breakout_dates = {
                    'up': stock_data[stock_data['breakout_up']].index.tolist(),
                    'down': stock_data[stock_data['breakout_down']].index.tolist(),
                }
                
                breakouts[stock_code] = breakout_dates
            except Exception as e:
                continue
        
        return breakouts
    
    def _generate_signals(self, data: pd.DataFrame) -> Dict:
        """生成交易信号（向量化实现）"""
        signals = {}
        
        window = self.params['consolidation_window']
        pullback_threshold = self.params['pullback_threshold']
        threshold = self.params['breakout_threshold']
        
        try:
            stock_codes = data.index.get_level_values('stock_code').unique()
        except:
            stock_codes = data['stock_code'].unique() if 'stock_code' in data.columns else []
        
        for stock_code in stock_codes:
            try:
                # 获取单只股票数据
                if isinstance(data.index, pd.MultiIndex):
                    stock_data = data.xs(stock_code, level='stock_code')
                else:
                    stock_data = data[data['stock_code'] == stock_code].copy()
                    if stock_data.empty:
                        continue
                    stock_data = stock_data.set_index('trade_date')
                
                if len(stock_data) < window * 2:
                    continue
                
                # 计算区间
                stock_data = stock_data.copy()
                stock_data['high_max'] = stock_data['high'].rolling(window=window, min_periods=1).max().shift(1)
                
                # 检测向上突破
                stock_data['breakout_up'] = stock_data['close'] > stock_data['high_max'] * (1 + threshold)
                
                # 向量化：使用滚动窗口检查历史突破
                lookback = window * 2
                stock_data['has_breakout_up'] = stock_data['breakout_up'].shift(1).rolling(lookback, min_periods=1).max().fillna(0).astype(bool)
                
                # 回踩做多：曾向上突破 + 当前未突破 + 价格在上沿附近
                long_cond = (
                    stock_data['has_breakout_up'] &
                    ~stock_data['breakout_up'] &
                    (stock_data['close'] >= stock_data['high_max'] * (1 - pullback_threshold)) &
                    (stock_data['close'] <= stock_data['high_max'] * (1 + pullback_threshold))
                )
                
                # 生成信号字典（仅做多）
                stock_signals = {}
                for date in stock_data.index:
                    if long_cond.get(date, False):
                        stock_signals[date] = SignalType.LONG
                    else:
                        stock_signals[date] = SignalType.NONE
                
                signals[stock_code] = stock_signals
            except Exception as e:
                continue
        
        return signals
    
    def _should_buy(self, stock_code: str, date: pd.Timestamp, close: float) -> SignalType:
        """检查是否应该买入"""
        if stock_code not in self.signals:
            return SignalType.NONE
        
        stock_signals = self.signals[stock_code]
        
        # 查找最近的信号
        # 由于date可能不在预计算的日期中，找最近的一天
        available_dates = [d for d in stock_signals.keys() if d <= date]
        if not available_dates:
            return SignalType.NONE
        
        latest_date = max(available_dates)
        return stock_signals.get(latest_date, SignalType.NONE)
    
    def _should_sell(self, stock_code: str, date: pd.Timestamp, close: float) -> bool:
        """
        检查是否应该卖出（箱体下沿止损）
        
        逻辑：如果价格跌破震荡区间下沿，止损离场
        """
        # 获取该股票在当日的震荡区间
        if stock_code not in self.consolidation_zones:
            return False
        
        stock_zones = self.consolidation_zones[stock_code]
        
        # 查找当日或最近的区间数据
        if date in stock_zones:
            zone = stock_zones[date]
        else:
            # 找最近的日期
            available_dates = [d for d in stock_zones.keys() if d <= date]
            if not available_dates:
                return False
            latest_date = max(available_dates)
            zone = stock_zones[latest_date]
        
        low_min = zone.get('low_min', 0)
        if low_min <= 0:
            return False
        
        # 跌破箱体下沿则止损
        return close < low_min
