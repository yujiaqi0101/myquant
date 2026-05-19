"""
WorldQuant 101 因子库
====================

实现WorldQuant 101 Alphas因子。
参考：101 Formulaic Alphas by Zura Kakushadze

因子说明：
- 因子编号从001到101
- 使用标准数学运算和时间序列运算
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from .calculator import (
    ts_sum, ts_mean, ts_std, ts_max, ts_min, ts_rank, ts_delta, ts_delay,
    ts_corr, ts_scale, rank, scale, sign, abs_func, log, decay_linear, ind_neutralize
)


class WorldQuantFactors:
    """
    WorldQuant 101因子计算器
    
    实现101个短周期量价因子。
    """
    
    def __init__(self, calculator):
        """
        初始化因子计算器
        
        Parameters
        ----------
        calculator : FactorCalculator
            因子计算器实例
        """
        self.calculator = calculator
        self._factors = {}
    
    def _get_price_data(self):
        """获取价格数据"""
        return self.calculator.price_data
    
    def _close(self) -> pd.Series:
        return self.calculator.close()
    
    def _open(self) -> pd.Series:
        return self.calculator.open()
    
    def _high(self) -> pd.Series:
        return self.calculator.high()
    
    def _low(self) -> pd.Series:
        return self.calculator.low()
    
    def _volume(self) -> pd.Series:
        return self.calculator.volume()
    
    def _amount(self) -> pd.Series:
        return self.calculator.amount()
    
    def _vwap(self) -> pd.Series:
        return self.calculator.vwap()
    
    def _returns(self, period: int = 1) -> pd.Series:
        return self.calculator.returns(period)
    
    def _apply_ts(self, series: pd.Series, func, window: int) -> pd.Series:
        """应用时间序列函数到每个股票"""
        return series.groupby(level='stock_code').transform(lambda x: func(x, window))
    
    def _apply_corr(self, x: pd.Series, y: pd.Series, window: int) -> pd.Series:
        """按股票分组计算滚动相关系数，避免groupby transform中引用外部Series的index对齐问题"""
        # 确保 index names 一致
        if x.index.names != y.index.names:
            y = y.copy()
            y.index.names = x.index.names
        
        results = []
        stock_level_idx = 1 if len(x.index.names) > 1 else 0
        stock_level_name = x.index.names[stock_level_idx] if x.index.names else 'stock_code'
        
        for stock_code in x.index.get_level_values(stock_level_idx).unique():
            mask = x.index.get_level_values(stock_level_idx) == stock_code
            x_group = x[mask]
            y_group = y[mask]
            if len(x_group) < 2:
                continue
            corr_result = x_group.rolling(window=window, min_periods=1).corr(y_group)
            results.append(corr_result)
        if results:
            return pd.concat(results)
        return pd.Series(dtype=float)
    
    def _group_rank(self, series: pd.Series) -> pd.Series:
        """截面排名"""
        return series.groupby(level='trade_date').rank(pct=True)
    
    def _group_scale(self, series: pd.Series) -> pd.Series:
        """截面标准化"""
        return series.groupby(level='trade_date').transform(
            lambda x: (x - x.mean()) / (x.std() + 1e-10)
        )
    
    # ==================== 因子定义 ====================
    
    def alpha_001(self) -> pd.Series:
        """
        Alpha#1: (rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5)
        """
        returns = self._returns()
        close = self._close()
        
        # 条件判断
        condition = returns < 0
        std_returns = self._apply_ts(returns, ts_std, 20)
        
        # 条件选择
        value = pd.Series(np.where(condition, std_returns, close), index=close.index)
        
        # SignedPower
        signed_power = sign(value) * (abs_func(value) ** 2)
        
        # Ts_ArgMax
        argmax = self._apply_ts(signed_power, lambda x, w: x.rolling(w).apply(lambda y: w - 1 - np.argmax(y) if len(y) > 0 else np.nan), 5)
        
        # Rank
        return self._group_rank(argmax) - 0.5
    
    def alpha_002(self) -> pd.Series:
        """
        Alpha#2: (-1 * correlation(rank(delta(log(volume), 2)), rank(((close - open) / open)), 6))
        """
        volume = self._volume()
        close = self._close()
        open_price = self._open()
        
        log_volume = log(volume)
        delta_log_volume = self._apply_ts(log_volume, ts_delta, 2)
        rank_delta = self._group_rank(delta_log_volume)
        
        price_change = (close - open_price) / open_price
        rank_price = self._group_rank(price_change)
        
        # 计算相关性
        corr = self._apply_corr(rank_delta, rank_price, 6)
        
        return -1 * corr
    
    def alpha_003(self) -> pd.Series:
        """
        Alpha#3: (-1 * correlation(rank(open), rank(volume), 10))
        """
        open_price = self._open()
        volume = self._volume()
        
        rank_open = self._group_rank(open_price)
        rank_volume = self._group_rank(volume)
        
        corr = self._apply_corr(rank_open, rank_volume, 10)
        
        return -1 * corr
    
    def alpha_004(self) -> pd.Series:
        """
        Alpha#4: (-1 * Ts_Rank(rank(low), 9))
        """
        low = self._low()
        rank_low = self._group_rank(low)
        ts_rank_low = self._apply_ts(rank_low, ts_rank, 9)
        
        return -1 * ts_rank_low
    
    def alpha_005(self) -> pd.Series:
        """
        Alpha#5: (rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))
        """
        open_price = self._open()
        close = self._close()
        vwap = self._vwap()
        
        sum_vwap = self._apply_ts(vwap, ts_sum, 10)
        avg_vwap = sum_vwap / 10
        
        diff1 = open_price - avg_vwap
        rank_diff1 = self._group_rank(diff1)
        
        diff2 = close - vwap
        rank_diff2 = self._group_rank(diff2)
        
        return rank_diff1 * (-1 * abs_func(rank_diff2))
    
    def alpha_006(self) -> pd.Series:
        """
        Alpha#6: (-1 * correlation(open, volume, 10))
        """
        open_price = self._open()
        volume = self._volume()
        
        corr = self._apply_corr(open_price, volume, 10)
        
        return -1 * corr
    
    def alpha_007(self) -> pd.Series:
        """
        Alpha#7: ((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : (-1 * 1))
        """
        close = self._close()
        volume = self._volume()
        amount = self._amount()
        
        # 计算adv20
        adv20 = amount.groupby(level='stock_code').transform(
            lambda x: x.rolling(20).mean()
        )
        
        delta_close = self._apply_ts(close, ts_delta, 7)
        abs_delta = abs_func(delta_close)
        ts_rank_abs = self._apply_ts(abs_delta, ts_rank, 60)
        sign_delta = sign(delta_close)
        
        condition = adv20 < volume
        
        return pd.Series(
            np.where(condition, -1 * ts_rank_abs * sign_delta, -1),
            index=close.index
        )
    
    def alpha_008(self) -> pd.Series:
        """
        Alpha#8: (-1 * rank(((sum(open, 5) * sum(returns, 5)) - delay((sum(open, 5) * sum(returns, 5)), 10))))
        """
        open_price = self._open()
        returns = self._returns()
        
        sum_open = self._apply_ts(open_price, ts_sum, 5)
        sum_returns = self._apply_ts(returns, ts_sum, 5)
        
        product = sum_open * sum_returns
        delay_product = self._apply_ts(product, ts_delay, 10)
        
        diff = product - delay_product
        
        return -1 * self._group_rank(diff)
    
    def alpha_009(self) -> pd.Series:
        """
        Alpha#9: ((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : ((ts_max(delta(close, 1), 5) < 0) ? delta(close, 1) : (-1 * delta(close, 1))))
        """
        close = self._close()
        delta_close = self._apply_ts(close, ts_delta, 1)
        ts_min_delta = self._apply_ts(delta_close, ts_min, 5)
        ts_max_delta = self._apply_ts(delta_close, ts_max, 5)
        
        condition1 = ts_min_delta > 0
        condition2 = ts_max_delta < 0
        
        result = np.where(condition1, delta_close,
                         np.where(condition2, delta_close, -1 * delta_close))
        
        return pd.Series(result, index=close.index)
    
    def alpha_010(self) -> pd.Series:
        """
        Alpha#10: rank(((0 < ts_min(delta(close, 1), 4)) ? delta(close, 1) : ((ts_max(delta(close, 1), 4) < 0) ? delta(close, 1) : (-1 * delta(close, 1)))))
        """
        close = self._close()
        delta_close = self._apply_ts(close, ts_delta, 1)
        ts_min_delta = self._apply_ts(delta_close, ts_min, 4)
        ts_max_delta = self._apply_ts(delta_close, ts_max, 4)
        
        condition1 = ts_min_delta > 0
        condition2 = ts_max_delta < 0
        
        result = np.where(condition1, delta_close,
                         np.where(condition2, delta_close, -1 * delta_close))
        
        return self._group_rank(pd.Series(result, index=close.index))
    
    def alpha_011(self) -> pd.Series:
        """
        Alpha#11: ((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - close), 3))) * rank(delta(volume, 3)))
        """
        vwap = self._vwap()
        close = self._close()
        volume = self._volume()
        
        diff = vwap - close
        ts_max_diff = self._apply_ts(diff, ts_max, 3)
        ts_min_diff = self._apply_ts(diff, ts_min, 3)
        
        delta_volume = self._apply_ts(volume, ts_delta, 3)
        
        return (self._group_rank(ts_max_diff) + self._group_rank(ts_min_diff)) * self._group_rank(delta_volume)
    
    def alpha_012(self) -> pd.Series:
        """
        Alpha#12: (sign(delta(volume, 1)) * (-1 * delta(close, 1)))
        """
        volume = self._volume()
        close = self._close()
        
        delta_volume = self._apply_ts(volume, ts_delta, 1)
        delta_close = self._apply_ts(close, ts_delta, 1)
        
        return sign(delta_volume) * (-1 * delta_close)
    
    def alpha_013(self) -> pd.Series:
        """
        Alpha#13: (-1 * rank(covariance(rank(close), rank(volume), 5)))
        """
        close = self._close()
        volume = self._volume()
        
        rank_close = self._group_rank(close)
        rank_volume = self._group_rank(volume)
        
        cov = self._apply_corr(rank_close, rank_volume, 5)
        
        return -1 * self._group_rank(cov)
    
    def alpha_014(self) -> pd.Series:
        """
        Alpha#14: ((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10))
        """
        returns = self._returns()
        open_price = self._open()
        volume = self._volume()
        
        delta_returns = self._apply_ts(returns, ts_delta, 3)
        rank_delta = self._group_rank(delta_returns)
        
        corr = self._apply_corr(open_price, volume, 10)
        
        return (-1 * rank_delta) * corr
    
    def alpha_015(self) -> pd.Series:
        """
        Alpha#15: (-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))
        """
        high = self._high()
        volume = self._volume()
        
        rank_high = self._group_rank(high)
        rank_volume = self._group_rank(volume)
        
        corr = self._apply_corr(rank_high, rank_volume, 3)
        
        rank_corr = self._group_rank(corr)
        sum_rank = self._apply_ts(rank_corr, ts_sum, 3)
        
        return -1 * sum_rank
    
    def alpha_016(self) -> pd.Series:
        """
        Alpha#16: (-1 * rank(covariance(rank(high), rank(volume), 5)))
        """
        high = self._high()
        volume = self._volume()
        
        rank_high = self._group_rank(high)
        rank_volume = self._group_rank(volume)
        
        cov = self._apply_corr(rank_high, rank_volume, 5)
        
        return -1 * self._group_rank(cov)
    
    def alpha_017(self) -> pd.Series:
        """
        Alpha#17: (((-1 * rank(ts_rank(close, 10))) * rank(delta(delta(close, 1), 1))) * rank(ts_rank((volume / adv20), 5)))
        """
        close = self._close()
        volume = self._volume()
        amount = self._amount()
        
        ts_rank_close = self._apply_ts(close, ts_rank, 10)
        rank_ts_rank = self._group_rank(ts_rank_close)
        
        delta_close = self._apply_ts(close, ts_delta, 1)
        delta_delta = self._apply_ts(delta_close, ts_delta, 1)
        rank_delta = self._group_rank(delta_delta)
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        vol_ratio = volume / adv20
        ts_rank_vol = self._apply_ts(vol_ratio, ts_rank, 5)
        rank_vol = self._group_rank(ts_rank_vol)
        
        return (-1 * rank_ts_rank) * rank_delta * rank_vol
    
    def alpha_018(self) -> pd.Series:
        """
        Alpha#18: (-1 * rank(((stddev(abs((close - open)), 5) + (close - open)) + correlation(close, open, 10))))
        """
        close = self._close()
        open_price = self._open()
        
        diff = abs_func(close - open_price)
        std_diff = self._apply_ts(diff, ts_std, 5)
        
        price_diff = close - open_price
        
        corr = self._apply_corr(close, open_price, 10)
        
        value = std_diff + price_diff + corr
        
        return -1 * self._group_rank(value)
    
    def alpha_019(self) -> pd.Series:
        """
        Alpha#19: ((-1 * sign(((close - delay(close, 7)) + delta(close, 7)))) * (1 + rank((1 + sum(returns, 250)))))
        """
        close = self._close()
        returns = self._returns()
        
        delay_close = self._apply_ts(close, ts_delay, 7)
        delta_close = self._apply_ts(close, ts_delta, 7)
        
        sign_value = sign((close - delay_close) + delta_close)
        
        sum_returns = self._apply_ts(returns, ts_sum, 250)
        rank_sum = self._group_rank(1 + sum_returns)
        
        return (-1 * sign_value) * (1 + rank_sum)
    
    def alpha_020(self) -> pd.Series:
        """
        Alpha#20: (((-1 * rank((open - delay(high, 1)))) * rank((open - delay(close, 1)))) * rank((open - delay(low, 1))))
        """
        open_price = self._open()
        high = self._high()
        close = self._close()
        low = self._low()
        
        delay_high = self._apply_ts(high, ts_delay, 1)
        delay_close = self._apply_ts(close, ts_delay, 1)
        delay_low = self._apply_ts(low, ts_delay, 1)
        
        rank1 = self._group_rank(open_price - delay_high)
        rank2 = self._group_rank(open_price - delay_close)
        rank3 = self._group_rank(open_price - delay_low)
        
        return (-1 * rank1) * rank2 * rank3
    
    # ==================== Alpha#21 ~ Alpha#101 ====================
    # 注：行业中性化因子(48,56,58,59,63,66,67,69,70,76,79,80,82,84,87,89,90,91,93,97,100)需要IndNeutralize，暂未实现
    
    def alpha_021(self) -> pd.Series:
        """
        Alpha#21: 布林带-成交量策略
        """
        close = self._close()
        volume = self._volume()
        amount = self._amount()
        
        # 计算布林带
        mean_8 = self._apply_ts(close, ts_mean, 8)
        std_8 = self._apply_ts(close, ts_std, 8)
        mean_2 = self._apply_ts(close, ts_mean, 2)
        
        # adv20
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        
        # 布林带条件
        upper = mean_8 + std_8
        lower = mean_8 - std_8
        
        condition1 = upper < mean_2
        condition2 = mean_2 < lower
        condition3 = volume > adv20
        
        result = np.where(condition1, -1,
                          np.where(condition2, 1,
                                   np.where(condition3, 1, -1)))
        return pd.Series(result, index=close.index)
    
    def alpha_022(self) -> pd.Series:
        """
        Alpha#22: 量价相关变化-波动率
        """
        close = self._close()
        high = self._high()
        volume = self._volume()
        
        # correlation(high, volume, 5)
        corr = self._apply_corr(high, volume, 5)
        delta_corr = self._apply_ts(corr, ts_delta, 5)
        std_close = self._apply_ts(close, ts_std, 20)
        
        return -1 * delta_corr * self._group_rank(std_close)
    
    def alpha_023(self) -> pd.Series:
        """
        Alpha#23: 价格突破逻辑
        """
        high = self._high()
        mean_high = self._apply_ts(high, ts_mean, 20)
        delta_high = self._apply_ts(high, ts_delta, 2)
        
        condition = mean_high < high
        result = np.where(condition, -1 * delta_high, 0)
        return pd.Series(result, index=high.index)
    
    def alpha_024(self) -> pd.Series:
        """
        Alpha#24: 长期均值回归
        """
        close = self._close()
        mean_100 = self._apply_ts(close, ts_mean, 100)
        delta_mean = self._apply_ts(mean_100, ts_delta, 100)
        delay_close = self._apply_ts(close, ts_delay, 100)
        
        change_rate = delta_mean / delay_close
        ts_min_close = self._apply_ts(close, ts_min, 100)
        delta_close_3 = self._apply_ts(close, ts_delta, 3)
        
        condition = (change_rate < 0.05) | (change_rate == 0.05)
        result = np.where(condition, -1 * (close - ts_min_close), -1 * delta_close_3)
        return pd.Series(result, index=close.index)
    
    def alpha_025(self) -> pd.Series:
        """
        Alpha#25: 多因子乘积
        """
        close = self._close()
        high = self._high()
        vwap = self._vwap()
        returns = self._returns()
        amount = self._amount()
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        value = (-1 * returns) * adv20 * vwap * (high - close)
        return self._group_rank(value)
    
    def alpha_026(self) -> pd.Series:
        """
        Alpha#26: 量价时序相关
        """
        high = self._high()
        volume = self._volume()
        
        ts_rank_vol = self._apply_ts(volume, ts_rank, 5)
        ts_rank_high = self._apply_ts(high, ts_rank, 5)
        
        corr = self._apply_corr(ts_rank_vol, ts_rank_high, 5)
        max_corr = self._apply_ts(corr, ts_max, 3)
        return -1 * max_corr
    
    def alpha_027(self) -> pd.Series:
        """
        Alpha#27: 量价相关性阈值
        """
        volume = self._volume()
        vwap = self._vwap()
        
        rank_vol = self._group_rank(volume)
        rank_vwap = self._group_rank(vwap)
        
        corr = self._apply_corr(rank_vol, rank_vwap, 6)
        sum_corr = self._apply_ts(corr, ts_sum, 2)
        rank_sum = self._group_rank(sum_corr / 2.0)
        
        result = np.where(rank_sum > 0.5, -1, 1)
        return pd.Series(result, index=volume.index)
    
    def alpha_028(self) -> pd.Series:
        """
        Alpha#28: 均价-收盘价偏离
        """
        close = self._close()
        high = self._high()
        low = self._low()
        amount = self._amount()
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        corr = self._apply_corr(adv20, low, 5)
        mid = (high + low) / 2
        value = corr + mid - close
        return self._group_scale(value)
    
    def alpha_029(self) -> pd.Series:
        """
        Alpha#29: 深层嵌套-动量反转 (简化实现)
        """
        close = self._close()
        returns = self._returns()
        
        delta_close = self._apply_ts(close, ts_delta, 5)
        rank_delta = self._group_rank(-1 * delta_close)
        
        delay_returns = self._apply_ts(-1 * returns, ts_delay, 6)
        ts_rank_ret = self._apply_ts(delay_returns, ts_rank, 5)
        
        return self._group_rank(rank_delta) + ts_rank_ret
    
    def alpha_030(self) -> pd.Series:
        """
        Alpha#30: 价格方向一致性-成交量
        """
        close = self._close()
        volume = self._volume()
        
        delay1 = self._apply_ts(close, ts_delay, 1)
        delay2 = self._apply_ts(close, ts_delay, 2)
        delay3 = self._apply_ts(close, ts_delay, 3)
        
        sign1 = sign(close - delay1)
        sign2 = sign(delay1 - delay2)
        sign3 = sign(delay2 - delay3)
        
        sign_sum = sign1 + sign2 + sign3
        rank_sign = self._group_rank(sign_sum)
        
        sum_vol_5 = self._apply_ts(volume, ts_sum, 5)
        sum_vol_20 = self._apply_ts(volume, ts_sum, 20)
        
        return (1 - rank_sign) * sum_vol_5 / sum_vol_20
    
    def alpha_031(self) -> pd.Series:
        """
        Alpha#31: 多因子组合
        """
        close = self._close()
        low = self._low()
        amount = self._amount()
        
        delta_close = self._apply_ts(close, ts_delta, 10)
        rank_delta = self._group_rank(self._group_rank(delta_close))
        decay = self._apply_ts(-1 * rank_delta, decay_linear, 10)
        
        result = self._group_rank(self._group_rank(self._group_rank(decay)))
        result += self._group_rank(-1 * self._apply_ts(close, ts_delta, 3))
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        corr = self._apply_corr(adv20, low, 12)
        result += sign(self._group_scale(corr))
        
        return result
    
    def alpha_032(self) -> pd.Series:
        """
        Alpha#32: 均线偏离-量价相关
        """
        close = self._close()
        vwap = self._vwap()
        
        mean_7 = self._apply_ts(close, ts_mean, 7)
        deviation = mean_7 - close
        
        delay_close = self._apply_ts(close, ts_delay, 5)
        corr = self._apply_corr(vwap, delay_close, 230)
        
        return self._group_scale(deviation) + 20 * self._group_scale(corr)
    
    def alpha_033(self) -> pd.Series:
        """
        Alpha#33: 日内涨跌幅
        """
        close = self._close()
        open_price = self._open()
        
        ratio = open_price / close
        value = 1 - ratio
        return self._group_rank(-1 * value)
    
    def alpha_034(self) -> pd.Series:
        """
        Alpha#34: 波动率比率-价格变化
        """
        close = self._close()
        returns = self._returns()
        
        std_2 = self._apply_ts(returns, ts_std, 2)
        std_5 = self._apply_ts(returns, ts_std, 5)
        ratio = std_2 / std_5
        
        delta_close = self._apply_ts(close, ts_delta, 1)
        
        return self._group_rank(1 - self._group_rank(ratio)) + self._group_rank(1 - self._group_rank(delta_close))
    
    def alpha_035(self) -> pd.Series:
        """
        Alpha#35: 多因子时序排名
        """
        close = self._close()
        high = self._high()
        low = self._low()
        volume = self._volume()
        returns = self._returns()
        
        ts_rank_vol = self._apply_ts(volume, ts_rank, 32)
        ts_rank_price = self._apply_ts(close + high - low, ts_rank, 16)
        ts_rank_ret = self._apply_ts(returns, ts_rank, 32)
        
        return ts_rank_vol * (1 - ts_rank_price) * (1 - ts_rank_ret)
    
    def alpha_036(self) -> pd.Series:
        """
        Alpha#36: 加权多因子
        """
        close = self._close()
        open_price = self._open()
        volume = self._volume()
        vwap = self._vwap()
        returns = self._returns()
        amount = self._amount()
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        delay_vol = self._apply_ts(volume, ts_delay, 1)
        
        corr1 = (close - open_price).groupby(level='stock_code').transform(
            lambda x: x.rolling(15).corr(delay_vol)
        )
        
        delay_ret = self._apply_ts(-1 * returns, ts_delay, 6)
        ts_rank_ret = self._apply_ts(delay_ret, ts_rank, 5)
        
        corr2 = self._apply_corr(vwap, adv20, 6)
        
        mean_200 = self._apply_ts(close, ts_mean, 200)
        
        result = 2.21 * self._group_rank(corr1)
        result += 0.7 * self._group_rank(open_price - close)
        result += 0.73 * self._group_rank(ts_rank_ret)
        result += self._group_rank(abs_func(corr2))
        result += 0.6 * self._group_rank((mean_200 - open_price) * (close - open_price))
        
        return result
    
    def alpha_037(self) -> pd.Series:
        """
        Alpha#37: 滞后量价相关-日内变化
        """
        close = self._close()
        open_price = self._open()
        
        delay_diff = self._apply_ts(open_price - close, ts_delay, 1)
        corr = self._apply_corr(delay_diff, close, 200)
        
        return self._group_rank(corr) + self._group_rank(open_price - close)
    
    def alpha_038(self) -> pd.Series:
        """
        Alpha#38: 价格时序排名-日内比率
        """
        close = self._close()
        open_price = self._open()
        
        ts_rank_close = self._apply_ts(close, ts_rank, 10)
        ratio = close / open_price
        
        return -1 * self._group_rank(ts_rank_close) * self._group_rank(ratio)
    
    def alpha_039(self) -> pd.Series:
        """
        Alpha#39: 价格动量-成交量衰减
        """
        close = self._close()
        volume = self._volume()
        returns = self._returns()
        amount = self._amount()
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        vol_ratio = volume / adv20
        decay_vol = self._apply_ts(vol_ratio, decay_linear, 9)
        
        delta_close = self._apply_ts(close, ts_delta, 7)
        sum_returns = self._apply_ts(returns, ts_sum, 250)
        
        return -1 * self._group_rank(delta_close * (1 - self._group_rank(decay_vol))) * (1 + self._group_rank(sum_returns))
    
    def alpha_040(self) -> pd.Series:
        """
        Alpha#40: 波动率-量价相关
        """
        high = self._high()
        volume = self._volume()
        
        std_high = self._apply_ts(high, ts_std, 10)
        corr = self._apply_corr(high, volume, 10)
        
        return -1 * self._group_rank(std_high) * corr
    
    def alpha_041(self) -> pd.Series:
        """
        Alpha#41: 几何均价-VWAP偏离
        """
        high = self._high()
        low = self._low()
        vwap = self._vwap()
        
        geo_mean = np.sqrt(high * low)
        return geo_mean - vwap
    
    def alpha_042(self) -> pd.Series:
        """
        Alpha#42: VWAP偏离比率
        """
        close = self._close()
        vwap = self._vwap()
        
        return self._group_rank(vwap - close) / self._group_rank(vwap + close)
    
    def alpha_043(self) -> pd.Series:
        """
        Alpha#43: 相对成交量-价格动量
        """
        close = self._close()
        volume = self._volume()
        amount = self._amount()
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        vol_ratio = volume / adv20
        
        ts_rank_vol = self._apply_ts(vol_ratio, ts_rank, 20)
        delta_close = self._apply_ts(close, ts_delta, 7)
        ts_rank_delta = self._apply_ts(-1 * delta_close, ts_rank, 8)
        
        return ts_rank_vol * ts_rank_delta
    
    def alpha_044(self) -> pd.Series:
        """
        Alpha#44: 价格-成交量排名相关
        """
        high = self._high()
        volume = self._volume()
        
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(high, rank_vol, 5)
        return -1 * corr
    
    def alpha_045(self) -> pd.Series:
        """
        Alpha#45: 三因子乘积
        """
        close = self._close()
        volume = self._volume()
        
        delay_close = self._apply_ts(close, ts_delay, 5)
        sum_delay = self._apply_ts(delay_close, ts_sum, 20)
        mean_delay = sum_delay / 20
        
        corr1 = self._apply_corr(close, volume, 2)
        
        sum_5 = self._apply_ts(close, ts_sum, 5)
        sum_20 = self._apply_ts(close, ts_sum, 20)
        corr2 = self._apply_corr(sum_5, sum_20, 2)
        
        return -1 * self._group_rank(mean_delay) * corr1 * self._group_rank(corr2)
    
    def alpha_046(self) -> pd.Series:
        """
        Alpha#46: 趋势判断因子
        """
        close = self._close()
        
        delay_20 = self._apply_ts(close, ts_delay, 20)
        delay_10 = self._apply_ts(close, ts_delay, 10)
        delay_1 = self._apply_ts(close, ts_delay, 1)
        
        trend1 = (delay_20 - delay_10) / 10
        trend2 = (delay_10 - close) / 10
        
        condition1 = trend1 - trend2 > 0.25
        condition2 = trend1 - trend2 < 0
        
        result = np.where(condition1, -1,
                          np.where(condition2, 1, -1 * (close - delay_1)))
        return pd.Series(result, index=close.index)
    
    def alpha_047(self) -> pd.Series:
        """
        Alpha#47: 复合排名因子
        """
        close = self._close()
        high = self._high()
        volume = self._volume()
        vwap = self._vwap()
        amount = self._amount()
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        sum_high = self._apply_ts(high, ts_sum, 5)
        
        rank_inv_close = self._group_rank(1 / close)
        rank_high_close = self._group_rank(high - close)
        
        delay_vwap = self._apply_ts(vwap, ts_delay, 5)
        
        result = (rank_inv_close * volume / adv20) * (high * rank_high_close / (sum_high / 5))
        result -= self._group_rank(vwap - delay_vwap)
        return result
    
    def alpha_049(self) -> pd.Series:
        """
        Alpha#49: 趋势判断因子变体
        """
        close = self._close()
        
        delay_20 = self._apply_ts(close, ts_delay, 20)
        delay_10 = self._apply_ts(close, ts_delay, 10)
        delay_1 = self._apply_ts(close, ts_delay, 1)
        
        trend1 = (delay_20 - delay_10) / 10
        trend2 = (delay_10 - close) / 10
        
        condition = trend1 - trend2 < -0.1
        
        result = np.where(condition, 1, -1 * (close - delay_1))
        return pd.Series(result, index=close.index)
    
    def alpha_050(self) -> pd.Series:
        """
        Alpha#50: 量价相关性极值
        """
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        
        rank_vol = self._group_rank(volume)
        rank_vwap = self._group_rank(vwap)
        
        corr = self._apply_corr(rank_vol, rank_vwap, 5)
        rank_corr = self._group_rank(corr)
        max_rank = self._apply_ts(rank_corr, ts_max, 3)
        
        return -1 * max_rank
    
    def alpha_051(self) -> pd.Series:
        """
        Alpha#51: 低价时序最小排名
        """
        low = self._low()
        rank_low = self._group_rank(low)
        min_rank = self._apply_ts(rank_low, ts_min, 9)
        return -1 * min_rank
    
    def alpha_052(self) -> pd.Series:
        """
        Alpha#52: 量价复合因子
        """
        close = self._close()
        open_price = self._open()
        volume = self._volume()
        returns = self._returns()
        
        delta_diff = self._apply_ts(close - open_price, ts_delta, 5)
        corr = self._apply_corr(returns, volume, 5)
        delta_close = self._apply_ts(close, ts_delta, 5)
        
        return -1 * delta_diff * self._group_rank(corr) * sign(delta_close)
    
    def alpha_053(self) -> pd.Series:
        """
        Alpha#53: K线形态变化
        """
        close = self._close()
        high = self._high()
        low = self._low()
        
        position = (close - high) / (high - low + 0.001)
        delta_pos = self._apply_ts(position, ts_delta, 9)
        return -1 * delta_pos
    
    def alpha_054(self) -> pd.Series:
        """
        Alpha#54: K线形态-价格加权
        """
        close = self._close()
        open_price = self._open()
        high = self._high()
        low = self._low()
        
        numerator = -1 * (low - close) * (open_price ** 5)
        denominator = (low - high) * (close ** 5) + 0.001
        return numerator / denominator
    
    def alpha_055(self) -> pd.Series:
        """
        Alpha#55: 开盘价偏离因子
        """
        close = self._close()
        open_price = self._open()
        
        sum_close = self._apply_ts(close, ts_sum, 10)
        value = (open_price - sum_close) * (open_price - close)
        return -1 * self._group_rank(value) / open_price
    
    def alpha_057(self) -> pd.Series:
        """
        Alpha#57: 条件动量因子
        """
        close = self._close()
        
        delta_close = self._apply_ts(close, ts_delta, 1)
        min_delta = self._apply_ts(delta_close, ts_min, 4)
        max_delta = self._apply_ts(delta_close, ts_max, 4)
        
        condition1 = min_delta > 0
        condition2 = max_delta < 0
        
        result = np.where(condition1, delta_close,
                          np.where(condition2, delta_close, -1 * delta_close))
        return pd.Series(result, index=close.index)
    
    def alpha_060(self) -> pd.Series:
        """
        Alpha#60: 量价方向因子
        """
        close = self._close()
        volume = self._volume()
        
        delta_vol = self._apply_ts(volume, ts_delta, 1)
        delta_close = self._apply_ts(close, ts_delta, 1)
        
        return sign(delta_vol) * (-1 * delta_close)
    
    def alpha_061(self) -> pd.Series:
        """
        Alpha#61: VWAP动量相关
        """
        close = self._close()
        vwap = self._vwap()
        
        min_vwap = self._apply_ts(vwap, ts_min, 16)
        delay_close = self._apply_ts(close, ts_delay, 3)
        
        corr = self._apply_corr(vwap, delay_close, 17)
        
        return self._group_rank(vwap - min_vwap) * self._group_rank(corr)
    
    def alpha_062(self) -> pd.Series:
        """
        Alpha#62: 多相关性组合
        """
        close = self._close()
        open_price = self._open()
        volume = self._volume()
        vwap = self._vwap()
        
        sum_close = self._apply_ts(close, ts_sum, 5)
        corr1 = self._apply_corr(vwap, sum_close, 6)
        
        rank_open = self._group_rank(open_price)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_open, rank_vol, 5)
        
        return (self._group_rank(corr1) ** 1.16) * self._group_rank(corr2)
    
    def alpha_064(self) -> pd.Series:
        """
        Alpha#64: 加权价格相关性
        """
        close = self._close()
        open_price = self._open()
        low = self._low()
        volume = self._volume()
        vwap = self._vwap()
        amount = self._amount()
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        weighted_price = open_price * 0.178 + low * 0.533
        sum_adv = self._apply_ts(adv20, ts_sum, 26)
        
        corr1 = self._apply_corr(weighted_price, sum_adv, 5)
        
        rank_vwap = self._group_rank(vwap)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_vwap, rank_vol, 7)
        
        return self._group_rank(corr1) * self._group_rank(corr2)
    
    def alpha_065(self) -> pd.Series:
        """
        Alpha#65: 开盘价成交量相关性
        """
        close = self._close()
        open_price = self._open()
        volume = self._volume()
        amount = self._amount()
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        sum_adv = self._apply_ts(adv20, ts_sum, 16)
        
        corr1 = self._apply_corr(open_price, sum_adv, 9)
        
        rank_close = self._group_rank(close)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_close, rank_vol, 10)
        
        return self._group_rank(corr1) * self._group_rank(corr2)
    
    def alpha_068(self) -> pd.Series:
        """
        Alpha#68: 高价量相关性时序排名
        """
        high = self._high()
        volume = self._volume()
        
        rank_high = self._group_rank(high)
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(rank_high, rank_vol, 3)
        ts_rank_corr = self._apply_ts(corr, ts_rank, 3)
        
        corr2 = self._apply_corr(high, volume, 3)
        
        return -1 * ts_rank_corr * self._group_rank(corr2)
    
    def alpha_071(self) -> pd.Series:
        """
        Alpha#71: VWAP偏离极值
        """
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        
        diff = vwap - close
        max_diff = self._apply_ts(diff, ts_max, 3)
        min_diff = self._apply_ts(diff, ts_min, 3)
        delta_vol = self._apply_ts(volume, ts_delta, 3)
        
        return (self._group_rank(max_diff) + self._group_rank(min_diff)) * self._group_rank(delta_vol)
    
    def alpha_072(self) -> pd.Series:
        """
        Alpha#72: 衰减相关性差值
        """
        close = self._close()
        low = self._low()
        volume = self._volume()
        vwap = self._vwap()
        
        corr1 = self._apply_corr(vwap, volume, 4)
        decay1 = self._apply_ts(corr1, decay_linear, 16)
        
        rank_low = self._group_rank(low)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_low, rank_vol, 6)
        decay2 = self._apply_ts(corr2, decay_linear, 3)
        
        return self._group_rank(decay1) - self._group_rank(decay2)
    
    def alpha_073(self) -> pd.Series:
        """
        Alpha#73: 动量与排名最大值
        """
        close = self._close()
        
        delta_close = self._apply_ts(close, ts_delta, 7)
        ts_rank_close = self._apply_ts(close, ts_rank, 15)
        
        return np.maximum(-1 * self._group_rank(delta_close), self._group_rank(ts_rank_close))
    
    def alpha_074(self) -> pd.Series:
        """
        Alpha#74: 收盘价成交量相关性
        """
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        amount = self._amount()
        
        adv20 = amount.groupby(level='stock_code').transform(lambda x: x.rolling(20).mean())
        sum_adv = self._apply_ts(adv20, ts_sum, 26)
        
        corr1 = self._apply_corr(close, sum_adv, 5)
        
        rank_vwap = self._group_rank(vwap)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_vwap, rank_vol, 7)
        
        return self._group_rank(corr1) * self._group_rank(corr2)
    
    def alpha_075(self) -> pd.Series:
        """
        Alpha#75: VWAP成交量相关性
        """
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        
        corr1 = self._apply_corr(vwap, volume, 4)
        
        rank_close = self._group_rank(close)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_close, rank_vol, 4)
        
        return self._group_rank(corr1) * self._group_rank(corr2)
    
    def alpha_077(self) -> pd.Series:
        """
        Alpha#77: 衰减动量相关性
        """
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        
        delta_close = self._apply_ts(close, ts_delta, 2)
        decay = self._apply_ts(delta_close, decay_linear, 8)
        
        corr = self._apply_corr(vwap, volume, 7)
        
        return self._group_rank(decay) * self._group_rank(corr)
    
    def alpha_078(self) -> pd.Series:
        """
        Alpha#78: 收盘量相关性组合
        """
        close = self._close()
        volume = self._volume()
        
        corr1 = self._apply_corr(close, volume, 3)
        
        rank_close = self._group_rank(close)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_close, rank_vol, 7)
        
        return self._group_rank(corr1) * self._group_rank(corr2)
    
    def alpha_081(self) -> pd.Series:
        """
        Alpha#81: VWAP变化极值相关性
        """
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        
        delta_vwap = self._apply_ts(vwap, ts_delta, 3)
        max_delta = self._apply_ts(delta_vwap, ts_max, 5)
        
        corr = self._apply_corr(vwap, volume, 10)
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_083(self) -> pd.Series:
        """
        Alpha#83: 开盘价偏离排名
        """
        close = self._close()
        open_price = self._open()
        
        sum_close = self._apply_ts(close, ts_sum, 10)
        value = (open_price - sum_close) * (open_price - close)
        
        return -1 * self._group_rank(value) / open_price
    
    def alpha_085(self) -> pd.Series:
        """
        Alpha#85: VWAP量相关性组合
        """
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        
        corr1 = self._apply_corr(vwap, volume, 6)
        
        rank_close = self._group_rank(close)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_close, rank_vol, 6)
        
        return self._group_rank(corr1) * self._group_rank(corr2)
    
    def alpha_086(self) -> pd.Series:
        """
        Alpha#86: 高价量相关性时序排名
        """
        high = self._high()
        volume = self._volume()
        
        rank_high = self._group_rank(high)
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(rank_high, rank_vol, 3)
        ts_rank_corr = self._apply_ts(corr, ts_rank, 3)
        
        corr2 = self._apply_corr(high, volume, 3)
        
        return -1 * ts_rank_corr * self._group_rank(corr2)
    
    def alpha_088(self) -> pd.Series:
        """
        Alpha#88: 价格回撤相关性
        """
        close = self._close()
        open_price = self._open()
        volume = self._volume()
        
        min_close = self._apply_ts(close, ts_min, 12)
        ratio = (close - min_close) / (min_close + 0.001)
        
        rank_open = self._group_rank(open_price)
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(rank_open, rank_vol, 5)
        
        return self._group_rank(ratio) * self._group_rank(corr)
    
    def alpha_092(self) -> pd.Series:
        """
        Alpha#92: 高价量相关性衰减时序排名
        """
        high = self._high()
        volume = self._volume()
        
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(high, rank_vol, 4)
        decay = self._apply_ts(corr, decay_linear, 9)
        decay_ts_rank = self._apply_ts(decay, ts_rank, 16)
        
        return -1 * decay_ts_rank
    
    def alpha_094(self) -> pd.Series:
        """
        Alpha#94: 开盘价偏离排名
        """
        close = self._close()
        open_price = self._open()
        
        sum_close = self._apply_ts(close, ts_sum, 10)
        value = (open_price - sum_close) * (open_price - close)
        
        return -1 * self._group_rank(value) / open_price
    
    def alpha_095(self) -> pd.Series:
        """
        Alpha#95: VWAP变化相关性
        """
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        
        delta_vwap = self._apply_ts(vwap, ts_delta, 3)
        max_delta = self._apply_ts(delta_vwap, ts_max, 5)
        
        rank_close = self._group_rank(close)
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(rank_close, rank_vol, 7)
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_096(self) -> pd.Series:
        """
        Alpha#96: 收盘价变化相关性
        """
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        
        delta_close = self._apply_ts(close, ts_delta, 2)
        max_delta = self._apply_ts(delta_close, ts_max, 3)
        
        rank_vwap = self._group_rank(vwap)
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(rank_vwap, rank_vol, 4)
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_098(self) -> pd.Series:
        """
        Alpha#98: VWAP衰减相关性
        """
        close = self._close()
        open_price = self._open()
        volume = self._volume()
        vwap = self._vwap()
        
        corr1 = self._apply_corr(vwap, volume, 4)
        decay = self._apply_ts(corr1, decay_linear, 16)
        
        rank_open = self._group_rank(open_price)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_open, rank_vol, 5)
        
        return self._group_rank(decay) * self._group_rank(corr2)
    
    def alpha_099(self) -> pd.Series:
        """
        Alpha#99: 收盘价变化相关性
        """
        close = self._close()
        volume = self._volume()
        
        delta_close = self._apply_ts(close, ts_delta, 2)
        max_delta = self._apply_ts(delta_close, ts_max, 3)
        
        rank_close = self._group_rank(close)
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(rank_close, rank_vol, 7)
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_101(self) -> pd.Series:
        """
        Alpha#101: 日内价格位置
        """
        close = self._close()
        open_price = self._open()
        high = self._high()
        low = self._low()
        
        return (close - open_price) / (high - low + 0.001)
    
    # ==================== 行业中性化因子 (Alpha#48, #56, #58, #59, #63, #66, #67, #69, #70, #76, #79, #80, #82, #84, #87, #89, #90, #91, #93, #97, #100) ====================
    
    def alpha_048(self) -> pd.Series:
        """
        Alpha#48: 加权动量-成交量行业中性化
        公式：(-1 * ((rank(ts_rank(close, 10)) - rank(delta(delay(close, 1), 10))) * rank(delta(delay(close, 1), 10))))
        """
        close = self._close()
        volume = self._volume()
        
        ts_rank_close = self._apply_ts(close, ts_rank, 10)
        delay_close = self._apply_ts(close, ts_delay, 1)
        delta_delay = self._apply_ts(delay_close, ts_delta, 10)
        
        return -1 * (self._group_rank(ts_rank_close) - self._group_rank(delta_delay)) * self._group_rank(delta_delay)
    
    def alpha_056(self) -> pd.Series:
        """
        Alpha#56: 价格动量-行业成交量相关性
        公式：(rank(decay_linear(delta(close, 2), 8)) - rank(decay_linear(correlation(IndNeutralize(volume, IndClass.sector), close, 10), 6)))
        """
        close = self._close()
        volume = self._volume()
        
        delta_close = self._apply_ts(close, ts_delta, 2)
        decay_price = self._apply_ts(delta_close, decay_linear, 8)
        
        # 行业中性化成交量
        neutral_vol = ind_neutralize(volume)
        corr = neutral_vol.groupby(level='trade_date').transform(
            lambda x: x.rolling(10).corr(close)
        )
        decay_corr = self._apply_ts(corr, decay_linear, 6)
        
        return self._group_rank(decay_price) - self._group_rank(decay_corr)
    
    def alpha_058(self) -> pd.Series:
        """
        Alpha#58: 行业VWAP成交量相关性时序排名
        公式：(-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.sector), volume, 4), 8), 6))
        """
        vwap = self._vwap()
        volume = self._volume()
        
        # 行业中性化VWAP
        neutral_vwap = ind_neutralize(vwap)
        corr = neutral_vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(4).corr(volume)
        )
        decay = self._apply_ts(corr, decay_linear, 8)
        
        return -1 * self._apply_ts(decay, ts_rank, 6)
    
    def alpha_059(self) -> pd.Series:
        """
        Alpha#59: 行业收盘价成交量相关性时序排名
        公式：(-1 * ts_rank(decay_linear(correlation(IndNeutralize(close, IndClass.subindustry), volume, 4), 16), 6))
        """
        close = self._close()
        volume = self._volume()
        
        # 行业中性化收盘价
        neutral_close = ind_neutralize(close)
        corr = neutral_close.groupby(level='trade_date').transform(
            lambda x: x.rolling(4).corr(volume)
        )
        decay = self._apply_ts(corr, decay_linear, 16)
        
        return -1 * self._apply_ts(decay, ts_rank, 6)
    
    def alpha_063(self) -> pd.Series:
        """
        Alpha#63: 价格突破-行业收盘价成交量相关性
        公式：(-1 * rank(sum((close - ts_min(close, 12)) / ts_min(close, 12), 20)) * rank(correlation(IndNeutralize(close, IndClass.subindustry), volume, 7)))
        """
        close = self._close()
        volume = self._volume()
        
        min_close = self._apply_ts(close, ts_min, 12)
        ratio = (close - min_close) / (min_close + 0.001)
        sum_ratio = self._apply_ts(ratio, ts_sum, 20)
        
        # 行业中性化收盘价
        neutral_close = ind_neutralize(close)
        corr = neutral_close.groupby(level='trade_date').transform(
            lambda x: x.rolling(7).corr(volume)
        )
        
        return -1 * self._group_rank(sum_ratio) * self._group_rank(corr)
    
    def alpha_066(self) -> pd.Series:
        """
        Alpha#66: 价格时序排名-行业VWAP成交量相关性
        公式：((-1 * rank(ts_rank(close, 10))) * rank(correlation(IndNeutralize(vwap, IndClass.industry), volume, 7)))
        """
        close = self._close()
        vwap = self._vwap()
        volume = self._volume()
        
        ts_rank_close = self._apply_ts(close, ts_rank, 10)
        
        # 行业中性化VWAP
        neutral_vwap = ind_neutralize(vwap)
        corr = neutral_vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(7).corr(volume)
        )
        
        return -1 * self._group_rank(ts_rank_close) * self._group_rank(corr)
    
    def alpha_067(self) -> pd.Series:
        """
        Alpha#67: 价格极值偏离-行业成交量收盘价相关性
        公式：((rank((close - ts_max(close, 15))^1.2) * rank(correlation(IndNeutralize(volume, IndClass.subindustry), close, 11)))
        """
        close = self._close()
        volume = self._volume()
        
        max_close = self._apply_ts(close, ts_max, 15)
        deviation = np.power(close - max_close + 0.001, 1.2)
        
        # 行业中性化成交量
        neutral_vol = ind_neutralize(volume)
        corr = neutral_vol.groupby(level='trade_date').transform(
            lambda x: x.rolling(11).corr(close)
        )
        
        return self._group_rank(deviation) * self._group_rank(corr)
    
    def alpha_069(self) -> pd.Series:
        """
        Alpha#69: VWAP变化极值-行业收盘价成交量相关性
        公式：((rank(ts_max(delta(vwap, 3), 5))^1) * rank(correlation(IndNeutralize(close, IndClass.subindustry), volume, 9)))
        """
        close = self._close()
        vwap = self._vwap()
        volume = self._volume()
        
        delta_vwap = self._apply_ts(vwap, ts_delta, 3)
        max_delta = self._apply_ts(delta_vwap, ts_max, 5)
        
        # 行业中性化收盘价
        neutral_close = ind_neutralize(close)
        corr = neutral_close.groupby(level='trade_date').transform(
            lambda x: x.rolling(9).corr(volume)
        )
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_070(self) -> pd.Series:
        """
        Alpha#70: 价格变化极值-行业VWAP成交量相关性
        公式：((rank(ts_max(delta(close, 2), 3))^1) * rank(correlation(IndNeutralize(vwap, IndClass.subindustry), volume, 5)))
        """
        close = self._close()
        vwap = self._vwap()
        volume = self._volume()
        
        delta_close = self._apply_ts(close, ts_delta, 2)
        max_delta = self._apply_ts(delta_close, ts_max, 3)
        
        # 行业中性化VWAP
        neutral_vwap = ind_neutralize(vwap)
        corr = neutral_vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(5).corr(volume)
        )
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_076(self) -> pd.Series:
        """
        Alpha#76: 行业收盘价成交量相关性衰减
        公式：(-1 * rank(decay_linear(IndNeutralize(correlation(close, volume, 10), IndClass.subindustry), 10)))
        """
        close = self._close()
        volume = self._volume()
        
        # 先计算相关性，再进行行业中性化
        corr = close.groupby(level='trade_date').transform(
            lambda x: x.rolling(10).corr(volume)
        )
        neutral_corr = ind_neutralize(corr)
        decay = self._apply_ts(neutral_corr, decay_linear, 10)
        
        return -1 * self._group_rank(decay)
    
    def alpha_079(self) -> pd.Series:
        """
        Alpha#79: 价格变化极值-行业VWAP成交量相关性
        公式：(rank(ts_max(delta(close, 1), 3))^1) * rank(correlation(IndNeutralize(vwap, IndClass.subindustry), volume, 6)))
        """
        close = self._close()
        vwap = self._vwap()
        volume = self._volume()
        
        delta_close = self._apply_ts(close, ts_delta, 1)
        max_delta = self._apply_ts(delta_close, ts_max, 3)
        
        # 行业中性化VWAP
        neutral_vwap = ind_neutralize(vwap)
        corr = neutral_vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(6).corr(volume)
        )
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_080(self) -> pd.Series:
        """
        Alpha#80: 价格时序排名-行业开盘价成交量相关性
        公式：(-1 * rank(ts_rank(close, 10)) * rank(correlation(IndNeutralize(open, IndClass.sector), volume, 8)))
        """
        close = self._close()
        open_price = self._open()
        volume = self._volume()
        
        ts_rank_close = self._apply_ts(close, ts_rank, 10)
        
        # 行业中性化开盘价
        neutral_open = ind_neutralize(open_price)
        corr = neutral_open.groupby(level='trade_date').transform(
            lambda x: x.rolling(8).corr(volume)
        )
        
        return -1 * self._group_rank(ts_rank_close) * self._group_rank(corr)
    
    def alpha_082(self) -> pd.Series:
        """
        Alpha#82: 行业最高价成交量相关性衰减
        公式：(-1 * rank(decay_linear(correlation(IndNeutralize(high, IndClass.subindustry), volume, 4), 9)))
        """
        high = self._high()
        volume = self._volume()
        
        # 行业中性化最高价
        neutral_high = ind_neutralize(high)
        corr = neutral_high.groupby(level='trade_date').transform(
            lambda x: x.rolling(4).corr(volume)
        )
        decay = self._apply_ts(corr, decay_linear, 9)
        
        return -1 * self._group_rank(decay)
    
    def alpha_084(self) -> pd.Series:
        """
        Alpha#84: 价格突破-行业VWAP成交量相关性
        公式：(rank(ts_rank((close - ts_min(close, 12)) / ts_min(close, 12), 20))^1) * rank(correlation(IndNeutralize(vwap, IndClass.subindustry), volume, 6)))
        """
        close = self._close()
        vwap = self._vwap()
        volume = self._volume()
        
        min_close = self._apply_ts(close, ts_min, 12)
        ratio = (close - min_close) / (min_close + 0.001)
        ts_rank_ratio = self._apply_ts(ratio, ts_rank, 20)
        
        # 行业中性化VWAP
        neutral_vwap = ind_neutralize(vwap)
        corr = neutral_vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(6).corr(volume)
        )
        
        return self._group_rank(ts_rank_ratio) * self._group_rank(corr)
    
    def alpha_087(self) -> pd.Series:
        """
        Alpha#87: VWAP成交量相关性-行业收盘价成交量相关性
        公式：(rank(decay_linear(correlation(vwap, volume, 4), 16))^1) * rank(correlation(IndNeutralize(close, IndClass.subindustry), volume, 6)))
        """
        close = self._close()
        vwap = self._vwap()
        volume = self._volume()
        
        corr1 = vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(4).corr(volume)
        )
        decay1 = self._apply_ts(corr1, decay_linear, 16)
        
        # 行业中性化收盘价
        neutral_close = ind_neutralize(close)
        corr2 = neutral_close.groupby(level='trade_date').transform(
            lambda x: x.rolling(6).corr(volume)
        )
        
        return self._group_rank(decay1) * self._group_rank(corr2)
    
    def alpha_089(self) -> pd.Series:
        """
        Alpha#89: 价格动量-行业VWAP成交量相关性
        公式：(-1 * (rank(ts_rank(close, 10)) - rank(decay_linear(close, 6))) * rank(correlation(IndNeutralize(vwap, IndClass.subindustry), volume, 6)))
        """
        close = self._close()
        vwap = self._vwap()
        volume = self._volume()
        
        ts_rank_close = self._apply_ts(close, ts_rank, 10)
        decay_close = self._apply_ts(close, decay_linear, 6)
        
        # 行业中性化VWAP
        neutral_vwap = ind_neutralize(vwap)
        corr = neutral_vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(6).corr(volume)
        )
        
        return -1 * (self._group_rank(ts_rank_close) - self._group_rank(decay_close)) * self._group_rank(corr)
    
    def alpha_090(self) -> pd.Series:
        """
        Alpha#90: 价格变化极值-行业VWAP成交量相关性
        公式：(rank(ts_max(delta(close, 1), 3))^1) * rank(correlation(IndNeutralize(vwap, IndClass.subindustry), volume, 5)))
        """
        close = self._close()
        vwap = self._vwap()
        volume = self._volume()
        
        delta_close = self._apply_ts(close, ts_delta, 1)
        max_delta = self._apply_ts(delta_close, ts_max, 3)
        
        # 行业中性化VWAP
        neutral_vwap = ind_neutralize(vwap)
        corr = neutral_vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(5).corr(volume)
        )
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_091(self) -> pd.Series:
        """
        Alpha#91: 价格变化极值-行业收盘价成交量相关性
        公式：(rank(ts_max(delta(close, 2), 3))^1) * rank(correlation(IndNeutralize(close, IndClass.subindustry), volume, 5)))
        """
        close = self._close()
        volume = self._volume()
        
        delta_close = self._apply_ts(close, ts_delta, 2)
        max_delta = self._apply_ts(delta_close, ts_max, 3)
        
        # 行业中性化收盘价
        neutral_close = ind_neutralize(close)
        corr = neutral_close.groupby(level='trade_date').transform(
            lambda x: x.rolling(5).corr(volume)
        )
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_093(self) -> pd.Series:
        """
        Alpha#93: 价格变化极值-行业VWAP成交量相关性
        公式：((rank(ts_max(delta(close, 1), 3))^1) * rank(correlation(IndNeutralize(vwap, IndClass.subindustry), volume, 6)))
        """
        close = self._close()
        vwap = self._vwap()
        volume = self._volume()
        
        delta_close = self._apply_ts(close, ts_delta, 1)
        max_delta = self._apply_ts(delta_close, ts_max, 3)
        
        # 行业中性化VWAP
        neutral_vwap = ind_neutralize(vwap)
        corr = neutral_vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(6).corr(volume)
        )
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_097(self) -> pd.Series:
        """
        Alpha#97: 价格变化极值-行业VWAP成交量相关性
        公式：(rank(ts_max(delta(close, 1), 3))^1) * rank(correlation(IndNeutralize(vwap, IndClass.subindustry), volume, 5)))
        """
        close = self._close()
        vwap = self._vwap()
        volume = self._volume()
        
        delta_close = self._apply_ts(close, ts_delta, 1)
        max_delta = self._apply_ts(delta_close, ts_max, 3)
        
        # 行业中性化VWAP
        neutral_vwap = ind_neutralize(vwap)
        corr = neutral_vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(5).corr(volume)
        )
        
        return self._group_rank(max_delta) * self._group_rank(corr)
    
    def alpha_100(self) -> pd.Series:
        """
        Alpha#100: 行业VWAP成交量相关性衰减
        公式：(-1 * rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.subindustry), volume, 4), 16)))
        """
        vwap = self._vwap()
        volume = self._volume()
        
        # 行业中性化VWAP
        neutral_vwap = ind_neutralize(vwap)
        corr = neutral_vwap.groupby(level='trade_date').transform(
            lambda x: x.rolling(4).corr(volume)
        )
        decay = self._apply_ts(corr, decay_linear, 16)
        
        return -1 * self._group_rank(decay)
    
    # ==================== 批量计算 ====================
    
    def calculate_all(self) -> Dict[str, pd.Series]:
        """
        计算所有因子
        
        Returns
        -------
        Dict[str, pd.Series]
            因子名称到因子值的映射
        """
        # 获取所有alpha方法
        alpha_methods = [name for name in dir(self) if name.startswith('alpha_')]
        alpha_methods.sort()
        
        for method_name in alpha_methods:
            try:
                # 从方法名提取因子编号
                factor_num = int(method_name.split('_')[1])
                factor_name = f'WQ_{factor_num:03d}'
                
                method = getattr(self, method_name)
                self._factors[factor_name] = method()
                print(f"已计算因子: {factor_name}")
            except Exception as e:
                print(f"计算因子 {method_name} 时出错: {e}")
        
        return self._factors
    
    def calculate_factor(self, factor_id: int) -> pd.Series:
        """
        计算指定因子
        
        Parameters
        ----------
        factor_id : int
            因子编号 (1-101)
        
        Returns
        -------
        pd.Series
            因子值
        """
        method_name = f'alpha_{factor_id:03d}'
        if hasattr(self, method_name):
            return getattr(self, method_name)()
        else:
            raise ValueError(f"因子 {factor_id} 尚未实现")
    
    def get_factor_list(self) -> List[str]:
        """获取已实现的因子列表"""
        return [name for name in dir(self) if name.startswith('alpha_')]
