"""
震荡突破回踩策略
================

策略逻辑（严格按用户描述实现）：
1. 震荡区间识别：基于近期N天的最高价和最低价确定震荡区间上下沿
2. 突破确认：价格脱离（超过上沿 或 跌破下沿）震荡区间
3. 回踩开仓：突破后价格回踩到震荡区间边界附近时做多或做空
4. 止损：标的再次脱离震荡区间且方向与持仓方向相反
5. 动态止盈：当天收盘价跌破（多头）或超过（空头）3天内平均真实价格

作者：量化交易系统
日期：2026-05-22
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import warnings
warnings.filterwarnings('ignore')


class SignalType(Enum):
    """信号类型"""
    NONE = 0
    LONG = 1       # 做多信号（向上突破后回踩）
    SHORT = 2      # 做空信号（向下突破后回踩）


@dataclass
class Position:
    """持仓信息"""
    stock_code: str
    direction: int       # 1: 多头, -1: 空头
    entry_price: float
    entry_date: pd.Timestamp
    quantity: int
    atr_at_entry: float  # 开仓时的ATR，用于记录
    margin: float = 0.0  # 占用的保证金（空头时需要）


class BreakoutPullbackStrategy:
    """
    震荡突破回踩策略

    参数说明：
    -----------
    consolidation_window : int
        震荡区间识别窗口（默认20天），用过去N天的最高/最低价作为区间上下沿
    breakout_threshold : float
        突破确认阈值，价格需要超过区间边界的比例（默认0.01即1%）
        向上突破：close > upper * (1 + threshold)
        向下突破：close < lower * (1 - threshold)
    pullback_threshold : float
        回踩确认阈值，价格回到区间边界的比例（默认0.01即1%）
        回踩上沿做多：close 在 upper * (1 - threshold) ~ upper * (1 + threshold) 范围内
        回踩下沿做空：close 在 lower * (1 - threshold) ~ lower * (1 + threshold) 范围内
    atr_window : int
        ATR计算窗口（默认14天）
    ma_window : int
        动态止盈用的均线窗口（默认3天），用户描述为"3天内平均真实价格"
    max_holding_days : int
        最大持仓天数（默认20天），超时强制平仓
    position_size : float
        单次开仓资金比例（默认0.1即10%）
    commission_rate : float
        佣金费率（默认万三）
    slippage : float
        滑点（默认万分之一）
    """

    def __init__(
        self,
        consolidation_window: int = 20,
        breakout_threshold: float = 0.01,
        pullback_threshold: float = 0.01,
        atr_window: int = 14,
        ma_window: int = 3,
        max_holding_days: int = 20,
        position_size: float = 0.1,
        commission_rate: float = 0.0003,
        slippage: float = 0.0001,
    ):
        self.consolidation_window = consolidation_window
        self.breakout_threshold = breakout_threshold
        self.pullback_threshold = pullback_threshold
        self.atr_window = atr_window
        self.ma_window = ma_window
        self.max_holding_days = max_holding_days
        self.position_size = position_size
        self.commission_rate = commission_rate
        self.slippage = slippage

        # 运行时状态（每次 run_backtest 重置）
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Dict] = []
        self.daily_values: List[Dict] = []
        self.capital: float = 0.0
        self.initial_capital: float = 0.0

    # ================================================================
    # 因子计算
    # ================================================================

    def calculate_atr(
        self, high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14
    ) -> pd.Series:
        """
        计算平均真实波幅(ATR)

        TR = max(high - low, |high - prev_close|, |low - prev_close|)
        ATR = TR 的 EWM(alpha=1/window) 均值
        """
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / window, min_periods=window).mean()
        return atr

    def identify_consolidation_zone(
        self, high: pd.Series, low: pd.Series, window: int = 20
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        识别震荡区间

        使用 shift(1) 确保不包含当天数据（避免未来函数）。
        upper = 过去 window 天的最高价
        lower = 过去 window 天的最低价
        """
        upper_band = high.rolling(window=window, min_periods=window).max().shift(1)
        lower_band = low.rolling(window=window, min_periods=window).min().shift(1)
        middle_band = (upper_band + lower_band) / 2
        return upper_band, lower_band, middle_band

    # ================================================================
    # 信号检测
    # ================================================================

    def detect_breakout(
        self, close: pd.Series, upper: pd.Series, lower: pd.Series, threshold: float
    ) -> Tuple[pd.Series, pd.Series]:
        """
        检测突破信号

        向上突破：close > upper * (1 + threshold)
        向下突破：close < lower * (1 - threshold)
        """
        valid = upper.notna() & lower.notna() & close.notna()
        breakout_up = (close > upper * (1 + threshold)) & valid
        breakout_down = (close < lower * (1 - threshold)) & valid
        return breakout_up, breakout_down

    def detect_pullback(
        self,
        close: pd.Series,
        upper: pd.Series,
        lower: pd.Series,
        breakout_up: pd.Series,
        breakout_down: pd.Series,
        threshold: float,
    ) -> Tuple[pd.Series, pd.Series]:
        """
        检测回踩信号

        回踩做多：历史上曾经向上突破过，且当前价格回落到上沿附近
        回踩做空：历史上曾经向下突破过，且当前价格回升到下沿附近
        """
        # 历史上是否曾经突破（不含当天，用 shift(1)）
        # 使用滚动窗口避免远古突破信号持续生效
        lookback = self.consolidation_window * 2
        ever_breakout_up = (
            breakout_up.astype(float)
            .rolling(window=lookback, min_periods=1)
            .max()
            .shift(1)
            .fillna(0)
            .astype(bool)
        )
        ever_breakout_down = (
            breakout_down.astype(float)
            .rolling(window=lookback, min_periods=1)
            .max()
            .shift(1)
            .fillna(0)
            .astype(bool)
        )

        valid = upper.notna() & lower.notna() & close.notna() & (upper > 0) & (lower > 0)

        # 回踩做多：曾经向上突破 + 当前价格在上沿附近
        pullback_long = (
            ever_breakout_up
            & (close >= upper * (1 - threshold))
            & (close <= upper * (1 + threshold))
            & valid
        )

        # 回踩做空：曾经向下突破 + 当前价格在下沿附近
        pullback_short = (
            ever_breakout_down
            & (close >= lower * (1 - threshold))
            & (close <= lower * (1 + threshold))
            & valid
        )

        return pullback_long, pullback_short

    # ================================================================
    # 信号生成（单只股票）
    # ================================================================

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        为单只股票生成交易信号

        输入 df 需包含列：open, high, low, close, volume
        输出 df 额外包含列：
            consolidation_upper, consolidation_lower, consolidation_middle
            atr, ma_{ma_window}
            breakout_up, breakout_down
            pullback_long, pullback_short
            signal (0=无, 1=做多, 2=做空)
        """
        df = df.copy()

        # 1. 震荡区间
        upper, lower, middle = self.identify_consolidation_zone(
            df['high'], df['low'], self.consolidation_window
        )
        df['consolidation_upper'] = upper
        df['consolidation_lower'] = lower
        df['consolidation_middle'] = middle

        # 2. ATR
        df['atr'] = self.calculate_atr(df['high'], df['low'], df['close'], self.atr_window)

        # 3. 动态止盈用的均线（3天内平均真实价格 = 3日收盘均线）
        df[f'ma_{self.ma_window}'] = df['close'].rolling(window=self.ma_window, min_periods=self.ma_window).mean()

        # 4. 突破检测
        breakout_up, breakout_down = self.detect_breakout(
            df['close'], upper, lower, self.breakout_threshold
        )
        df['breakout_up'] = breakout_up
        df['breakout_down'] = breakout_down

        # 5. 回踩检测
        pullback_long, pullback_short = self.detect_pullback(
            df['close'], upper, lower,
            breakout_up, breakout_down, self.pullback_threshold
        )
        df['pullback_long'] = pullback_long
        df['pullback_short'] = pullback_short

        # 6. 最终信号
        df['signal'] = SignalType.NONE.value
        df.loc[pullback_long, 'signal'] = SignalType.LONG.value
        df.loc[pullback_short, 'signal'] = SignalType.SHORT.value

        return df

    # ================================================================
    # 回测引擎
    # ================================================================

    def run_backtest(
        self,
        price_data: pd.DataFrame,
        initial_capital: float = 1_000_000,
        stock_codes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        运行回测

        Parameters
        ----------
        price_data : pd.DataFrame
            多只股票的价格数据，MultiIndex (trade_date, stock_code)
            需包含列：open, high, low, close, volume
        initial_capital : float
            初始资金
        stock_codes : List[str], optional
            指定回测的股票列表，None 则使用所有股票

        Returns
        -------
        Dict[str, Any]
            回测结果（含 values_df, trades_df, 绩效指标等）
        """
        # 重置状态
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.positions = {}
        self.trade_history = []
        self.daily_values = []

        # ---- 数据准备 ----
        if not isinstance(price_data.index, pd.MultiIndex):
            raise ValueError("price_data 必须是 MultiIndex (trade_date, stock_code)")

        all_dates = price_data.index.get_level_values('trade_date').unique().sort_values()
        if stock_codes is None:
            stock_codes = price_data.index.get_level_values('stock_code').unique().tolist()

        # ---- 预计算每只股票的信号 ----
        stock_signals: Dict[str, pd.DataFrame] = {}
        for code in stock_codes:
            try:
                stock_df = price_data.xs(code, level='stock_code').copy()
                if len(stock_df) < self.consolidation_window + self.ma_window + 5:
                    continue
                stock_signals[code] = self.generate_signals(stock_df)
            except Exception as e:
                print(f"[警告] 处理股票 {code} 时出错: {e}")
                continue

        print(f"[回测] 有效股票: {len(stock_codes)} 只, 预计算完成: {len(stock_signals)} 只")
        print(f"[回测] 日期范围: {all_dates[0].date()} ~ {all_dates[-1].date()}, 共 {len(all_dates)} 个交易日")

        # ---- 逐日回测 ----
        for date in all_dates:
            daily_positions_value = 0.0

            for code in stock_codes:
                if code not in stock_signals:
                    continue
                sig_df = stock_signals[code]
                if date not in sig_df.index:
                    continue

                row = sig_df.loc[date]
                # 如果同一日期有多行（理论上不会），取第一行
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]

                price = float(row['close'])
                signal = int(row['signal'])
                atr = float(row['atr']) if not np.isnan(row['atr']) else 0.0
                upper = float(row['consolidation_upper']) if not np.isnan(row['consolidation_upper']) else 0.0
                lower = float(row['consolidation_lower']) if not np.isnan(row['consolidation_lower']) else 0.0
                ma_col = f'ma_{self.ma_window}'
                ma_val = float(row[ma_col]) if not np.isnan(row[ma_col]) else 0.0

                # ---- 已有持仓：检查平仓条件 ----
                if code in self.positions:
                    pos = self.positions[code]
                    should_close = False
                    close_reason = ""

                    # 条件1：止损 — 标的再次脱离震荡区间且方向与持仓方向相反
                    if pos.direction == 1 and upper > 0:
                        # 多头持仓：价格跌破震荡区间下沿
                        if price < lower * (1 - self.breakout_threshold):
                            should_close = True
                            close_reason = "止损：价格向下突破震荡区间下沿"
                    elif pos.direction == -1 and upper > 0:
                        # 空头持仓：价格突破震荡区间上沿
                        if price > upper * (1 + self.breakout_threshold):
                            should_close = True
                            close_reason = "止损：价格向上突破震荡区间上沿"

                    # 条件2：动态离场 — 当天收盘价跌破/超过3天内平均真实价格
                    if not should_close and ma_val > 0:
                        if pos.direction == 1:
                            # 多头：收盘价跌破3日均线 → 离场
                            if price < ma_val:
                                should_close = True
                                close_reason = "动态离场：收盘价跌破3日均线"
                        elif pos.direction == -1:
                            # 空头：收盘价超过3日均线 → 离场
                            if price > ma_val:
                                should_close = True
                                close_reason = "动态离场：收盘价超过3日均线"

                    # 条件3：超时平仓（按交易日计算，日历天 * 5/7 近似）
                    if not should_close:
                        holding_days = (date - pos.entry_date).days * 5 // 7
                        if holding_days >= self.max_holding_days:
                            should_close = True
                            close_reason = f"超时平仓：持仓{holding_days}天"

                    # 执行平仓
                    if should_close:
                        self._close_position(code, date, price, pos.quantity, close_reason)

                # ---- 无持仓：检查开仓信号 ----
                if code not in self.positions:
                    if signal == SignalType.LONG.value or signal == SignalType.SHORT.value:
                        alloc = self.capital * self.position_size
                        qty = int(alloc / price / 100) * 100  # 整手
                        if qty >= 100:
                            direction = 1 if signal == SignalType.LONG.value else -1
                            self._open_position(code, date, price, qty, direction, atr)

                # ---- 统计当日持仓市值 ----
                if code in self.positions:
                    pos = self.positions[code]
                    daily_positions_value += price * pos.quantity

            # 记录每日净值
            # 总净值 = 可用现金(capital) + 所有冻结的保证金
            # 这样空头持仓的市值变化不会影响每日净值，只有平仓时才实现盈亏
            frozen_margin = sum(pos.margin for pos in self.positions.values())
            total_value = self.capital + frozen_margin
            self.daily_values.append({
                'date': date,
                'capital': self.capital,
                'position_value': daily_positions_value,
                'total_value': total_value,
                'n_positions': len(self.positions),
            })

        return self._calculate_results()

    # ================================================================
    # 交易执行
    # ================================================================

    def _open_position(
        self, stock_code: str, date: pd.Timestamp,
        price: float, quantity: int, direction: int, atr: float,
    ):
        """开仓 - 使用保证金制度"""
        trade_value = price * quantity
        cost = trade_value * (self.commission_rate + self.slippage)

        if direction == 1:
            # 多头开仓（买入）：支出全额资金
            total_cost = trade_value + cost
            if total_cost > self.capital:
                return  # 资金不足，放弃
            self.capital -= total_cost
            margin = trade_value  # 多头占用资金等于市值
        else:
            # 空头开仓（卖出）：冻结保证金（100%），收到卖出资金
            margin = trade_value  # 冻结保证金
            if margin > self.capital:
                return  # 资金不足，放弃
            # 冻结保证金，同时收到卖出资金（净效果：capital不变，但冻结了margin）
            self.capital += trade_value - cost  # 收到卖出资金
            self.capital -= margin  # 冻结保证金

        self.positions[stock_code] = Position(
            stock_code=stock_code,
            direction=direction,
            entry_price=price,
            entry_date=date,
            quantity=quantity,
            atr_at_entry=atr,
            margin=margin,
        )

        self.trade_history.append({
            'date': date, 'stock_code': stock_code,
            'action': '买入开仓' if direction == 1 else '卖出开仓',
            'direction': direction,
            'price': price, 'quantity': quantity,
            'value': trade_value, 'cost': cost,
            'reason': '突破回踩信号',
        })

    def _close_position(
        self, stock_code: str, date: pd.Timestamp,
        price: float, quantity: int, reason: str,
    ):
        """平仓 - 释放保证金"""
        pos = self.positions[stock_code]
        trade_value = price * quantity
        cost = trade_value * (self.commission_rate + self.slippage)

        if pos.direction == 1:
            # 多头平仓（卖出）：收到资金
            self.capital += trade_value - cost
        else:
            # 空头平仓（买回）：释放保证金，支出买回资金
            self.capital += pos.margin  # 释放冻结的保证金
            self.capital -= trade_value + cost  # 支出买回资金

        # 盈亏 = (平仓价 - 开仓价) * 数量 * 方向 - 平仓手续费 - 开仓手续费
        open_cost = pos.entry_price * pos.quantity * (self.commission_rate + self.slippage)
        pnl = (price - pos.entry_price) * quantity * pos.direction - cost - open_cost

        self.trade_history.append({
            'date': date, 'stock_code': stock_code,
            'action': '卖出平仓' if pos.direction == 1 else '买入平仓',
            'direction': pos.direction,
            'price': price, 'quantity': quantity,
            'value': trade_value, 'cost': cost,
            'pnl': pnl, 'reason': reason,
        })

        del self.positions[stock_code]

    # ================================================================
    # 绩效计算
    # ================================================================

    def _calculate_results(self) -> Dict[str, Any]:
        """计算回测绩效指标"""
        if not self.daily_values:
            return {}

        values_df = pd.DataFrame(self.daily_values).set_index('date')
        values_df['returns'] = values_df['total_value'].pct_change()

        total_return = values_df['total_value'].iloc[-1] / self.initial_capital - 1
        n_days = len(values_df)
        annual_return = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 else 0
        annual_vol = values_df['returns'].std() * np.sqrt(252)
        rf = 0.03
        sharpe = (annual_return - rf) / annual_vol if annual_vol > 0 else 0

        # 最大回撤
        cummax = values_df['total_value'].cummax()
        drawdown = (values_df['total_value'] - cummax) / cummax
        max_dd = drawdown.min()
        calmar = annual_return / abs(max_dd) if max_dd != 0 else 0

        win_rate = (values_df['returns'] > 0).mean()
        pos_ret = values_df['returns'][values_df['returns'] > 0]
        neg_ret = values_df['returns'][values_df['returns'] < 0]
        pl_ratio = pos_ret.mean() / abs(neg_ret.mean()) if len(neg_ret) > 0 and len(pos_ret) > 0 else 0

        # 交易统计
        trades_df = pd.DataFrame(self.trade_history)
        n_open = n_close = trade_win_rate = avg_pnl = total_pnl = 0
        if not trades_df.empty:
            n_open = int(trades_df['action'].str.contains('开仓').sum())
            close_df = trades_df[trades_df['action'].str.contains('平仓')]
            n_close = len(close_df)
            if 'pnl' in close_df.columns and len(close_df) > 0:
                trade_win_rate = float((close_df['pnl'] > 0).mean())
                avg_pnl = float(close_df['pnl'].mean())
                total_pnl = float(close_df['pnl'].sum())

        return {
            'values_df': values_df,
            'trades_df': trades_df,
            'total_return': total_return,
            'annual_return': annual_return,
            'annual_volatility': annual_vol,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'calmar_ratio': calmar,
            'win_rate': win_rate,
            'profit_loss_ratio': pl_ratio,
            'n_trades': n_open,
            'n_close': n_close,
            'trade_win_rate': trade_win_rate,
            'avg_pnl': avg_pnl,
            'total_pnl': total_pnl,
            'initial_capital': self.initial_capital,
            'final_value': float(values_df['total_value'].iloc[-1]),
        }
