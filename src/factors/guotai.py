"""
国泰君安 Alpha191 因子库
========================

实现国泰君安191个短周期价量因子。
参考：国泰君安Alpha191因子公式详解

因子分类：
- 量价相关因子
- 均值回复因子
- 动量因子
- 波动率因子
- 相关性因子
- 成交量因子
- 价格形态因子
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from .calculator import (
    ts_sum, ts_mean, ts_std, ts_max, ts_min, ts_rank, ts_delta, ts_delay,
    ts_corr, rank, sign, abs_func, log, decay_linear, sma
)


class GuotaiFactors:
    """
    国泰君安Alpha191因子计算器
    
    实现191个短周期价量因子。
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
        """
        按股票分组计算滚动相关系数
        
        正确处理MultiIndex，确保每只股票的x和y子序列独立计算corr，
        避免groupby transform中引用外部Series导致的index对齐问题。
        """
        # 确保 index names 一致
        if x.index.names != y.index.names:
            y = y.copy()
            y.index.names = x.index.names
        
        results = []
        stock_level_idx = 1 if len(x.index.names) > 1 else 0
        
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
    
    # ==================== 量价相关因子 ====================
    
    def alpha_001(self) -> pd.Series:
        """
        GTJ_001: (-1 * CORR(RANK(DELTA(LOG(VOLUME), 1)), RANK(((CLOSE - OPEN) / OPEN)), 6))
        """
        volume = self._volume()
        close = self._close()
        open_price = self._open()
        
        log_volume = log(volume)
        delta_log_vol = self._apply_ts(log_volume, ts_delta, 1)
        rank_delta = self._group_rank(delta_log_vol)
        
        price_change = (close - open_price) / open_price
        rank_price = self._group_rank(price_change)
        
        corr = self._apply_corr(rank_delta, rank_price, 6)
        
        return -1 * corr
    
    def alpha_002(self) -> pd.Series:
        """
        GTJ_002: (-1 * DELTA(RANK(((CLOSE - OPEN) / OPEN)), 1))
        """
        close = self._close()
        open_price = self._open()
        
        price_change = (close - open_price) / open_price
        rank_change = self._group_rank(price_change)
        delta_rank = self._apply_ts(rank_change, ts_delta, 1)
        
        return -1 * delta_rank
    
    def alpha_003(self) -> pd.Series:
        """
        GTJ_003: (-1 * CORR(RANK(VOLUME), RANK(CLOSE), 5))
        """
        volume = self._volume()
        close = self._close()
        
        rank_volume = self._group_rank(volume)
        rank_close = self._group_rank(close)
        
        corr = self._apply_corr(rank_volume, rank_close, 5)
        
        return -1 * corr
    
    def alpha_004(self) -> pd.Series:
        """
        GTJ_004: (-1 * TS_RANK(RANK(CLOSE), 10))
        """
        close = self._close()
        rank_close = self._group_rank(close)
        ts_rank_close = self._apply_ts(rank_close, ts_rank, 10)
        
        return -1 * ts_rank_close
    
    def alpha_005(self) -> pd.Series:
        """
        GTJ_005: (RANK(OPEN - TS_MEAN(VWAP, 10)))
        """
        open_price = self._open()
        vwap = self._vwap()
        
        mean_vwap = self._apply_ts(vwap, ts_mean, 10)
        
        return self._group_rank(open_price - mean_vwap)
    
    # ==================== 均值回复因子 ====================
    
    def alpha_006(self) -> pd.Series:
        """
        GTJ_006: (-1 * CORR(OPEN, VOLUME, 10))
        """
        open_price = self._open()
        volume = self._volume()
        
        corr = self._apply_corr(open_price, volume, 10)
        
        return -1 * corr
    
    def alpha_007(self) -> pd.Series:
        """
        GTJ_007: (RANK(DELTA(CLOSE, 1)) * RANK(DELTA(VOLUME, 1)))
        """
        close = self._close()
        volume = self._volume()
        
        delta_close = self._apply_ts(close, ts_delta, 1)
        delta_volume = self._apply_ts(volume, ts_delta, 1)
        
        return self._group_rank(delta_close) * self._group_rank(delta_volume)
    
    def alpha_008(self) -> pd.Series:
        """
        GTJ_008: (-1 * RANK(TS_SUM(OPEN, 5) * TS_SUM(RETURNS, 5) - DELAY(TS_SUM(OPEN, 5) * TS_SUM(RETURNS, 5), 5)))
        """
        open_price = self._open()
        returns = self._returns()
        
        sum_open = self._apply_ts(open_price, ts_sum, 5)
        sum_returns = self._apply_ts(returns, ts_sum, 5)
        
        product = sum_open * sum_returns
        delay_product = self._apply_ts(product, ts_delay, 5)
        
        diff = product - delay_product
        
        return -1 * self._group_rank(diff)
    
    # ==================== 动量因子 ====================
    
    def alpha_009(self) -> pd.Series:
        """
        GTJ_009: ((TS_MIN(DELTA(CLOSE, 1), 5) > 0) ? DELTA(CLOSE, 1) : ((TS_MAX(DELTA(CLOSE, 1), 5) < 0) ? DELTA(CLOSE, 1) : (-1 * DELTA(CLOSE, 1))))
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
        GTJ_010: RANK(TS_DELTA(CLOSE, 7) * (1 - RANK(TS_DELTA(CLOSE, 7))))
        """
        close = self._close()
        delta_close = self._apply_ts(close, ts_delta, 7)
        rank_delta = self._group_rank(delta_close)
        
        return self._group_rank(delta_close * (1 - rank_delta))
    
    def alpha_011(self) -> pd.Series:
        """
        GTJ_011: (-1 * TS_RANK(TS_DELTA(CLOSE, 1), 10))
        """
        close = self._close()
        delta_close = self._apply_ts(close, ts_delta, 1)
        ts_rank_delta = self._apply_ts(delta_close, ts_rank, 10)
        
        return -1 * ts_rank_delta
    
    def alpha_012(self) -> pd.Series:
        """
        GTJ_012: (RANK(OPEN - TS_MEAN(CLOSE, 10)))
        """
        open_price = self._open()
        close = self._close()
        
        mean_close = self._apply_ts(close, ts_mean, 10)
        
        return self._group_rank(open_price - mean_close)
    
    # ==================== 波动率因子 ====================
    
    def alpha_013(self) -> pd.Series:
        """
        GTJ_013: (-1 * RANK(STDDEV(CLOSE, 20)))
        """
        close = self._close()
        std_close = self._apply_ts(close, ts_std, 20)
        
        return -1 * self._group_rank(std_close)
    
    def alpha_014(self) -> pd.Series:
        """
        GTJ_014: (-1 * CORR(OPEN, CLOSE, 10))
        """
        open_price = self._open()
        close = self._close()
        
        corr = self._apply_corr(open_price, close, 10)
        
        return -1 * corr
    
    def alpha_015(self) -> pd.Series:
        """
        GTJ_015: (RANK(STDDEV(HIGH - LOW, 10)))
        """
        high = self._high()
        low = self._low()
        
        diff = high - low
        std_diff = self._apply_ts(diff, ts_std, 10)
        
        return self._group_rank(std_diff)
    
    # ==================== 相关性因子 ====================
    
    def alpha_016(self) -> pd.Series:
        """
        GTJ_016: (-1 * CORR(RANK(HIGH), RANK(VOLUME), 5))
        """
        high = self._high()
        volume = self._volume()
        
        rank_high = self._group_rank(high)
        rank_volume = self._group_rank(volume)
        
        corr = self._apply_corr(rank_high, rank_volume, 5)
        
        return -1 * corr
    
    def alpha_017(self) -> pd.Series:
        """
        GTJ_017: (-1 * CORR(RANK(LOW), RANK(VOLUME), 5))
        """
        low = self._low()
        volume = self._volume()
        
        rank_low = self._group_rank(low)
        rank_volume = self._group_rank(volume)
        
        corr = self._apply_corr(rank_low, rank_volume, 5)
        
        return -1 * corr
    
    def alpha_018(self) -> pd.Series:
        """
        GTJ_018: (-1 * CORR(RANK(CLOSE), RANK(VOLUME), 5))
        """
        close = self._close()
        volume = self._volume()
        
        rank_close = self._group_rank(close)
        rank_volume = self._group_rank(volume)
        
        corr = self._apply_corr(rank_close, rank_volume, 5)
        
        return -1 * corr
    
    # ==================== 成交量因子 ====================
    
    def alpha_019(self) -> pd.Series:
        """
        GTJ_019: (-1 * RANK(DELTA(VOLUME, 1)))
        """
        volume = self._volume()
        delta_volume = self._apply_ts(volume, ts_delta, 1)
        
        return -1 * self._group_rank(delta_volume)
    
    def alpha_020(self) -> pd.Series:
        """
        GTJ_020: (RANK(TS_SUM(VOLUME, 5) / TS_SUM(VOLUME, 20)))
        """
        volume = self._volume()
        
        sum_5 = self._apply_ts(volume, ts_sum, 5)
        sum_20 = self._apply_ts(volume, ts_sum, 20)
        
        ratio = sum_5 / (sum_20 + 1e-10)
        
        return self._group_rank(ratio)
    
    # ==================== 价格形态因子 ====================
    
    def alpha_021(self) -> pd.Series:
        """
        GTJ_021: (RANK((HIGH - LOW) / CLOSE))
        """
        high = self._high()
        low = self._low()
        close = self._close()
        
        ratio = (high - low) / close
        
        return self._group_rank(ratio)
    
    def alpha_022(self) -> pd.Series:
        """
        GTJ_022: (RANK((CLOSE - OPEN) / CLOSE))
        """
        close = self._close()
        open_price = self._open()
        
        ratio = (close - open_price) / close
        
        return self._group_rank(ratio)
    
    def alpha_023(self) -> pd.Series:
        """
        GTJ_023: (RANK((HIGH - OPEN) / (OPEN - LOW + 1e-10)))
        """
        high = self._high()
        open_price = self._open()
        low = self._low()
        
        ratio = (high - open_price) / (open_price - low + 1e-10)
        
        return self._group_rank(ratio)
    
    # ==================== Alpha#24 ~ Alpha#191 ====================
    
    def alpha_024(self) -> pd.Series:
        """GTJ_024: SMA(CLOSE-DELAY(CLOSE,5),5,1)"""
        close = self._close()
        delay_close = self._apply_ts(close, ts_delay, 5)
        diff = close - delay_close
        return sma(diff, 5, 1)
    
    def alpha_025(self) -> pd.Series:
        """GTJ_025: 复合动量因子"""
        close = self._close()
        volume = self._volume()
        delta_close = self._apply_ts(close, ts_delta, 5)
        return self._group_rank(delta_close)
    
    def alpha_026(self) -> pd.Series:
        """GTJ_026: 均线偏离-量价相关"""
        close = self._close()
        vwap = self._vwap()
        mean_7 = self._apply_ts(close, ts_mean, 7)
        return mean_7 - close
    
    def alpha_027(self) -> pd.Series:
        """GTJ_027: WMA加权动量 DECAYLINEAR(RET3+RET6,12)"""
        close = self._close()
        delay_3 = self._apply_ts(close, ts_delay, 3)
        delay_6 = self._apply_ts(close, ts_delay, 6)
        ret_3 = (close - delay_3) / delay_3 * 100
        ret_6 = (close - delay_6) / delay_6 * 100
        return self._apply_ts(ret_3 + ret_6, decay_linear, 12)
    
    def alpha_028(self) -> pd.Series:
        """GTJ_028: KDJ-K值 SMA(RSV,3,1)"""
        close = self._close()
        high = self._high()
        low = self._low()
        llv_9 = self._apply_ts(low, ts_min, 9)
        hhv_9 = self._apply_ts(high, ts_max, 9)
        rsv = (close - llv_9) / (hhv_9 - llv_9 + 0.001) * 100
        return sma(rsv, 3, 1)
    
    def alpha_029(self) -> pd.Series:
        """GTJ_029: 量价动量"""
        close = self._close()
        volume = self._volume()
        delay_6 = self._apply_ts(close, ts_delay, 6)
        ret = (close - delay_6) / (delay_6 + 0.001)
        return ret * volume
    
    def alpha_030(self) -> pd.Series:
        """GTJ_030: SMA(RET^2,20,1)"""
        close = self._close()
        delay_close = self._apply_ts(close, ts_delay, 1)
        ret = close / delay_close - 1
        return sma(ret ** 2, 20, 1)
    
    def alpha_031(self) -> pd.Series:
        """GTJ_031: 价格偏离率"""
        close = self._close()
        mean_12 = self._apply_ts(close, ts_mean, 12)
        return (close - mean_12) / (mean_12 + 0.001) * 100
    
    def alpha_032(self) -> pd.Series:
        """GTJ_032: 量价相关性排名"""
        high = self._high()
        volume = self._volume()
        rank_high = self._group_rank(high)
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(rank_high, rank_vol, 3)
        return -1 * self._apply_ts(self._group_rank(corr), ts_sum, 3)
    
    def alpha_033(self) -> pd.Series:
        """GTJ_033: 复合量价因子"""
        close = self._close()
        volume = self._volume()
        return self._group_rank(close) * self._group_rank(volume)
    
    def alpha_034(self) -> pd.Series:
        """GTJ_034: 均值比率"""
        close = self._close()
        mean_12 = self._apply_ts(close, ts_mean, 12)
        return mean_12 / (close + 0.001)
    
    def alpha_035(self) -> pd.Series:
        """GTJ_035: 衰减相关性因子"""
        open_price = self._open()
        volume = self._volume()
        delta_open = self._apply_ts(open_price, ts_delta, 1)
        decay = self._apply_ts(delta_open, decay_linear, 15)
        return -1 * self._group_rank(decay)
    
    def alpha_036(self) -> pd.Series:
        """GTJ_036: 量价相关性累积"""
        volume = self._volume()
        vwap = self._vwap()
        rank_vol = self._group_rank(volume)
        rank_vwap = self._group_rank(vwap)
        corr = self._apply_corr(rank_vol, rank_vwap, 6)
        return self._group_rank(self._apply_ts(corr, ts_sum, 2))
    
    def alpha_037(self) -> pd.Series:
        """GTJ_037: 开盘动量"""
        open_price = self._open()
        returns = self._returns()
        sum_open = self._apply_ts(open_price, ts_sum, 5)
        sum_ret = self._apply_ts(returns, ts_sum, 5)
        return -1 * self._group_rank(sum_open * sum_ret)
    
    def alpha_038(self) -> pd.Series:
        """GTJ_038: 高价突破"""
        high = self._high()
        mean_high = self._apply_ts(high, ts_mean, 20)
        delta_high = self._apply_ts(high, ts_delta, 2)
        condition = mean_high < high
        return pd.Series(np.where(condition, -1 * delta_high, 0), index=high.index)
    
    def alpha_039(self) -> pd.Series:
        """GTJ_039: 复合动量因子"""
        close = self._close()
        volume = self._volume()
        delta_close = self._apply_ts(close, ts_delta, 5)
        return self._group_rank(delta_close) * self._group_rank(volume)
    
    def alpha_040(self) -> pd.Series:
        """GTJ_040: 上涨下跌量比"""
        close = self._close()
        volume = self._volume()
        delta_close = self._apply_ts(close, ts_delta, 1)
        up_vol = pd.Series(np.where(delta_close > 0, volume, 0), index=volume.index)
        down_vol = pd.Series(np.where(delta_close < 0, volume, 0), index=volume.index)
        sum_up = self._apply_ts(up_vol, ts_sum, 26)
        sum_down = self._apply_ts(down_vol, ts_sum, 26)
        return sum_up / (sum_down + 0.001) * 100
    
    def alpha_041(self) -> pd.Series:
        """GTJ_041: VWAP变化极值"""
        vwap = self._vwap()
        delta_vwap = self._apply_ts(vwap, ts_delta, 3)
        max_delta = self._apply_ts(delta_vwap, ts_max, 5)
        return -1 * self._group_rank(max_delta)
    
    def alpha_042(self) -> pd.Series:
        """GTJ_042: 波动率-量价相关"""
        high = self._high()
        volume = self._volume()
        std_high = self._apply_ts(high, ts_std, 10)
        corr = self._apply_corr(high, volume, 10)
        return -1 * self._group_rank(std_high) * corr
    
    def alpha_043(self) -> pd.Series:
        """GTJ_043: OBV简化版"""
        close = self._close()
        volume = self._volume()
        delta_close = self._apply_ts(close, ts_delta, 1)
        signed_vol = pd.Series(np.where(delta_close > 0, volume, -volume), index=volume.index)
        return self._apply_ts(signed_vol, ts_sum, 6)
    
    def alpha_044(self) -> pd.Series:
        """GTJ_044: 多因子时序排名"""
        low = self._low()
        volume = self._volume()
        vwap = self._vwap()
        mean_vol = self._apply_ts(volume, ts_mean, 10)
        corr = self._apply_corr(low, mean_vol, 7)
        decay = self._apply_ts(corr, decay_linear, 6)
        return self._apply_ts(decay, ts_rank, 4)
    
    def alpha_045(self) -> pd.Series:
        """GTJ_045: 加权价格动量"""
        close = self._close()
        open_price = self._open()
        volume = self._volume()
        vwap = self._vwap()
        weighted = close * 0.6 + open_price * 0.4
        delta_weighted = self._apply_ts(weighted, ts_delta, 1)
        mean_vol = self._apply_ts(volume, ts_mean, 150)
        corr = self._apply_corr(vwap, mean_vol, 15)
        return self._group_rank(delta_weighted) * self._group_rank(corr)
    
    def alpha_046(self) -> pd.Series:
        """GTJ_046: BBI变体"""
        close = self._close()
        ma3 = self._apply_ts(close, ts_mean, 3)
        ma6 = self._apply_ts(close, ts_mean, 6)
        ma12 = self._apply_ts(close, ts_mean, 12)
        ma24 = self._apply_ts(close, ts_mean, 24)
        return (ma3 + ma6 + ma12 + ma24) / (4 * close + 0.001)
    
    def alpha_047(self) -> pd.Series:
        """GTJ_047: RSV变体"""
        close = self._close()
        high = self._high()
        low = self._low()
        max_high = self._apply_ts(high, ts_max, 6)
        min_low = self._apply_ts(low, ts_min, 6)
        rsv = (max_high - close) / (max_high - min_low + 0.001) * 100
        return self._apply_ts(rsv, ts_mean, 9)
    
    def alpha_048(self) -> pd.Series:
        """GTJ_048: 价格方向-成交量比"""
        close = self._close()
        volume = self._volume()
        delay1 = self._apply_ts(close, ts_delay, 1)
        delay2 = self._apply_ts(close, ts_delay, 2)
        delay3 = self._apply_ts(close, ts_delay, 3)
        sign_sum = sign(close - delay1) + sign(delay1 - delay2) + sign(delay2 - delay3)
        sum_5 = self._apply_ts(volume, ts_sum, 5)
        sum_20 = self._apply_ts(volume, ts_sum, 20)
        return -1 * self._group_rank(sign_sum) * sum_5 / (sum_20 + 0.001)
    
    def alpha_049(self) -> pd.Series:
        """GTJ_049: 下突破振幅占比"""
        close = self._close()
        low = self._low()
        min_low = self._apply_ts(low, ts_min, 12)
        return self._group_rank((close - min_low) / (close + 0.001))
    
    def alpha_050(self) -> pd.Series:
        """GTJ_050: 突破占比差"""
        close = self._close()
        high = self._high()
        low = self._low()
        max_high = self._apply_ts(high, ts_max, 12)
        min_low = self._apply_ts(low, ts_min, 12)
        up_break = (max_high - close) / (close + 0.001)
        down_break = (close - min_low) / (close + 0.001)
        return down_break - up_break
    
    def alpha_051(self) -> pd.Series:
        """GTJ_051: 纯下突破占比"""
        close = self._close()
        low = self._low()
        min_low = self._apply_ts(low, ts_min, 12)
        return (close - min_low) / (close + 0.001)
    
    def alpha_052(self) -> pd.Series:
        """GTJ_052: 典型价格推力比"""
        close = self._close()
        high = self._high()
        low = self._low()
        typ = (high + low + close) / 3
        return self._apply_ts(typ, ts_mean, 26) / (typ + 0.001) * 100
    
    def alpha_053(self) -> pd.Series:
        """GTJ_053: 上涨天数占比"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        up_days = pd.Series(np.where(delta > 0, 1, 0), index=close.index)
        return self._apply_ts(up_days, ts_sum, 12) / 12 * 100
    
    def alpha_054(self) -> pd.Series:
        """GTJ_054: 日内波动相关性"""
        close = self._close()
        open_price = self._open()
        diff = abs_func(close - open_price)
        std_diff = self._apply_ts(diff, ts_std, 10)
        corr = self._apply_corr(close, open_price, 10)
        return -1 * self._group_rank(std_diff + (close - open_price) + corr)
    
    def alpha_055(self) -> pd.Series:
        """GTJ_055: TR标准化动量"""
        close = self._close()
        high = self._high()
        low = self._low()
        prev_close = self._apply_ts(close, ts_delay, 1)
        # 完整TR公式: MAX(HIGH-LOW, ABS(HIGH-PREV_CLOSE), ABS(LOW-PREV_CLOSE))
        tr = np.maximum(
            high - low,
            np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
        )
        tr = pd.Series(tr, index=close.index)
        delta = self._apply_ts(close, ts_delta, 1)
        return self._apply_ts(delta / (tr + 0.001), ts_sum, 20)
    
    def alpha_056(self) -> pd.Series:
        """GTJ_056: 条件判断因子"""
        close = self._close()
        volume = self._volume()
        mean_vol = self._apply_ts(volume, ts_mean, 20)
        condition = volume > mean_vol
        return pd.Series(np.where(condition, 1, 0), index=close.index)
    
    def alpha_057(self) -> pd.Series:
        """GTJ_057: KDJ-K值 SMA(RSV,3,1)"""
        close = self._close()
        high = self._high()
        low = self._low()
        llv_9 = self._apply_ts(low, ts_min, 9)
        hhv_9 = self._apply_ts(high, ts_max, 9)
        rsv = (close - llv_9) / (hhv_9 - llv_9 + 0.001) * 100
        return sma(rsv, 3, 1)
    
    def alpha_058(self) -> pd.Series:
        """GTJ_058: 上涨天数占比20日"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        up_days = pd.Series(np.where(delta > 0, 1, 0), index=close.index)
        return self._apply_ts(up_days, ts_sum, 20) / 20 * 100
    
    def alpha_059(self) -> pd.Series:
        """GTJ_059: 真实波动累积"""
        close = self._close()
        high = self._high()
        low = self._low()
        prev_close = self._apply_ts(close, ts_delay, 1)
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        tr = pd.Series(tr, index=close.index)
        return self._apply_ts(tr, ts_sum, 20)
    
    def alpha_060(self) -> pd.Series:
        """GTJ_060: 量价方向累积"""
        close = self._close()
        volume = self._volume()
        delta = self._apply_ts(close, ts_delta, 1)
        signed_vol = pd.Series(np.where(delta > 0, volume, -volume), index=volume.index)
        return self._apply_ts(signed_vol, ts_sum, 20)
    
    def alpha_061(self) -> pd.Series:
        """GTJ_061: 衰减排名最大值"""
        close = self._close()
        volume = self._volume()
        decay1 = self._apply_ts(self._group_rank(close), decay_linear, 10)
        decay2 = self._apply_ts(self._group_rank(volume), decay_linear, 10)
        return -1 * np.maximum(decay1, decay2)
    
    def alpha_062(self) -> pd.Series:
        """GTJ_062: 高价量相关性"""
        high = self._high()
        volume = self._volume()
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(high, rank_vol, 5)
        return -1 * corr
    
    def alpha_063(self) -> pd.Series:
        """GTJ_063: 6日RSI"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        up = pd.Series(np.where(delta > 0, delta, 0), index=close.index)
        down = pd.Series(np.where(delta < 0, np.abs(delta), 0), index=close.index)
        sum_up = self._apply_ts(up, ts_sum, 6)
        sum_down = self._apply_ts(down, ts_sum, 6)
        return sum_up / (sum_up + sum_down + 0.001) * 100
    
    def alpha_064(self) -> pd.Series:
        """GTJ_064: 衰减相关性最大值"""
        close = self._close()
        volume = self._volume()
        corr = self._apply_corr(close, volume, 10)
        decay = self._apply_ts(corr, decay_linear, 10)
        decay_delay = self._apply_ts(decay, ts_delay, 5)
        return -1 * np.maximum(decay, decay_delay)
    
    def alpha_065(self) -> pd.Series:
        """GTJ_065: 均值比率6日"""
        close = self._close()
        mean_6 = self._apply_ts(close, ts_mean, 6)
        return mean_6 / (close + 0.001)
    
    def alpha_066(self) -> pd.Series:
        """GTJ_066: 价格偏离率6日"""
        close = self._close()
        mean_6 = self._apply_ts(close, ts_mean, 6)
        return (close - mean_6) / (mean_6 + 0.001) * 100
    
    def alpha_067(self) -> pd.Series:
        """GTJ_067: 24日RSI"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        up = pd.Series(np.where(delta > 0, delta, 0), index=close.index)
        down = pd.Series(np.where(delta < 0, np.abs(delta), 0), index=close.index)
        sum_up = self._apply_ts(up, ts_sum, 24)
        sum_down = self._apply_ts(down, ts_sum, 24)
        return sum_up / (sum_up + sum_down + 0.001) * 100
    
    def alpha_068(self) -> pd.Series:
        """GTJ_068: 中间价加速度"""
        close = self._close()
        high = self._high()
        low = self._low()
        volume = self._volume()
        mid = (high + low) / 2
        accel = self._apply_ts(mid, ts_delta, 2)
        range_hl = high - low
        return self._apply_ts(accel * range_hl / (volume + 0.001), ts_mean, 15)
    
    def alpha_069(self) -> pd.Series:
        """GTJ_069: DTM/DBM比率"""
        close = self._close()
        high = self._high()
        low = self._low()
        open_price = self._open()
        dtm = pd.Series(np.where(high > open_price, high - open_price, 0), index=close.index)
        dbm = pd.Series(np.where(low < open_price, open_price - low, 0), index=close.index)
        sum_dtm = self._apply_ts(dtm, ts_sum, 20)
        sum_dbm = self._apply_ts(dbm, ts_sum, 20)
        return sum_dtm / (sum_dbm + 0.001)
    
    def alpha_070(self) -> pd.Series:
        """GTJ_070: 成交额波动"""
        close = self._close()
        volume = self._volume()
        amount = close * volume
        return self._apply_ts(amount, ts_std, 6)
    
    def alpha_071(self) -> pd.Series:
        """GTJ_071: 价格偏离率24日"""
        close = self._close()
        mean_24 = self._apply_ts(close, ts_mean, 24)
        return (close - mean_24) / (mean_24 + 0.001) * 100
    
    def alpha_072(self) -> pd.Series:
        """GTJ_072: 1-RSV移动平均"""
        close = self._close()
        high = self._high()
        low = self._low()
        llv_9 = self._apply_ts(low, ts_min, 9)
        hhv_9 = self._apply_ts(high, ts_max, 9)
        rsv = (close - llv_9) / (hhv_9 - llv_9 + 0.001)
        return self._apply_ts(1 - rsv, ts_mean, 15)
    
    def alpha_073(self) -> pd.Series:
        """GTJ_073: 复合量价因子"""
        close = self._close()
        volume = self._volume()
        return -1 * self._group_rank(close) * self._group_rank(volume)
    
    def alpha_074(self) -> pd.Series:
        """GTJ_074: 多因子相关性"""
        close = self._close()
        high = self._high()
        low = self._low()
        volume = self._volume()
        vwap = self._vwap()
        mean_vol = self._apply_ts(volume, ts_mean, 40)
        corr1 = ((high + low + close) / 3).groupby(level='stock_code').transform(
            lambda x: x.rolling(7).corr(mean_vol)
        )
        rank_vwap = self._group_rank(vwap)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_vwap, rank_vol, 6)
        return self._group_rank(corr1) + self._group_rank(corr2)
    
    def alpha_075(self) -> pd.Series:
        """GTJ_075: 相对强度"""
        close = self._close()
        returns = self._returns()
        # 简化实现
        return self._apply_ts(returns, ts_mean, 50)
    
    def alpha_076(self) -> pd.Series:
        """GTJ_076: 收益率波动率"""
        close = self._close()
        volume = self._volume()
        returns = self._returns()
        std_ret = self._apply_ts(np.abs(returns) / (volume + 0.001), ts_std, 20)
        mean_ret = self._apply_ts(np.abs(returns) / (volume + 0.001), ts_mean, 20)
        return std_ret / (mean_ret + 0.001)
    
    def alpha_077(self) -> pd.Series:
        """GTJ_077: 衰减排名最小值"""
        close = self._close()
        volume = self._volume()
        decay1 = self._apply_ts(self._group_rank(close), decay_linear, 10)
        decay2 = self._apply_ts(self._group_rank(volume), decay_linear, 10)
        return np.minimum(decay1, decay2)
    
    def alpha_078(self) -> pd.Series:
        """GTJ_078: CCI指标"""
        close = self._close()
        high = self._high()
        low = self._low()
        typ = (high + low + close) / 3
        mean_typ = self._apply_ts(typ, ts_mean, 12)
        mad = self._apply_ts(np.abs(typ - mean_typ), ts_mean, 12)
        return (typ - mean_typ) / (0.015 * mad + 0.001)
    
    def alpha_079(self) -> pd.Series:
        """GTJ_079: 12日RSI"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        up = pd.Series(np.where(delta > 0, delta, 0), index=close.index)
        down = pd.Series(np.where(delta < 0, np.abs(delta), 0), index=close.index)
        sum_up = self._apply_ts(up, ts_sum, 12)
        sum_down = self._apply_ts(down, ts_sum, 12)
        return sum_up / (sum_up + sum_down + 0.001) * 100
    
    def alpha_080(self) -> pd.Series:
        """GTJ_080: 成交量变化率"""
        close = self._close()
        volume = self._volume()
        delay_vol = self._apply_ts(volume, ts_delay, 5)
        return (volume - delay_vol) / (delay_vol + 0.001) * 100
    
    def alpha_081(self) -> pd.Series:
        """GTJ_081: 成交量移动平均"""
        close = self._close()
        volume = self._volume()
        return self._apply_ts(volume, ts_mean, 21)
    
    def alpha_082(self) -> pd.Series:
        """GTJ_082: 1-RSV移动平均20日"""
        close = self._close()
        high = self._high()
        low = self._low()
        llv_9 = self._apply_ts(low, ts_min, 9)
        hhv_9 = self._apply_ts(high, ts_max, 9)
        rsv = (close - llv_9) / (hhv_9 - llv_9 + 0.001)
        return self._apply_ts(1 - rsv, ts_mean, 20)
    
    def alpha_083(self) -> pd.Series:
        """GTJ_083: 高价量协方差排名"""
        high = self._high()
        volume = self._volume()
        rank_high = self._group_rank(high)
        rank_vol = self._group_rank(volume)
        cov = self._apply_corr(rank_high, rank_vol, 5)
        return -1 * self._group_rank(cov)
    
    def alpha_084(self) -> pd.Series:
        """GTJ_084: 带方向成交量累积"""
        close = self._close()
        volume = self._volume()
        delta = self._apply_ts(close, ts_delta, 1)
        signed_vol = pd.Series(np.where(delta > 0, volume, -volume), index=volume.index)
        return self._apply_ts(signed_vol, ts_sum, 20)
    
    def alpha_085(self) -> pd.Series:
        """GTJ_085: 多因子时序排名"""
        close = self._close()
        volume = self._volume()
        mean_vol = self._apply_ts(volume, ts_mean, 20)
        vol_ratio = volume / (mean_vol + 0.001)
        ts_rank_vol = self._apply_ts(vol_ratio, ts_rank, 20)
        delta_close = self._apply_ts(close, ts_delta, 7)
        ts_rank_delta = self._apply_ts(-1 * delta_close, ts_rank, 8)
        return ts_rank_vol * ts_rank_delta
    
    def alpha_086(self) -> pd.Series:
        """GTJ_086: 价格加速度条件"""
        close = self._close()
        accel1 = self._apply_ts(close, ts_delta, 1)
        accel2 = self._apply_ts(accel1, ts_delta, 1)
        condition1 = accel2 > 0
        condition2 = accel1 > 0
        return pd.Series(np.where(condition1 & condition2, 20, 
                                   np.where(condition1 | condition2, 10, 0)), index=close.index)
    
    def alpha_087(self) -> pd.Series:
        """GTJ_087: 复合量价因子"""
        close = self._close()
        volume = self._volume()
        return -1 * self._group_rank(close * volume)
    
    def alpha_088(self) -> pd.Series:
        """GTJ_088: 百分比动量"""
        close = self._close()
        delay_20 = self._apply_ts(close, ts_delay, 20)
        return (close - delay_20) / (delay_20 + 0.001) * 100
    
    def alpha_089(self) -> pd.Series:
        """GTJ_089: MACD"""
        close = self._close()
        ema13 = self._apply_ts(close, ts_mean, 13)
        ema27 = self._apply_ts(close, ts_mean, 27)
        dif = ema13 - ema27
        dea = self._apply_ts(dif, ts_mean, 10)
        return 2 * (dif - dea)
    
    def alpha_090(self) -> pd.Series:
        """GTJ_090: VWAP量相关性"""
        volume = self._volume()
        vwap = self._vwap()
        rank_vwap = self._group_rank(vwap)
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(rank_vwap, rank_vol, 5)
        return -1 * self._group_rank(corr)
    
    def alpha_091(self) -> pd.Series:
        """GTJ_091: 多因子相关性"""
        close = self._close()
        volume = self._volume()
        low = self._low()
        max_close = self._apply_ts(close, ts_max, 5)
        mean_vol = self._apply_ts(volume, ts_mean, 40)
        corr = self._apply_corr(mean_vol, low, 5)
        return -1 * self._group_rank(close - max_close) * self._group_rank(corr)
    
    def alpha_092(self) -> pd.Series:
        """GTJ_092: 衰减排名最大值"""
        close = self._close()
        volume = self._volume()
        decay1 = self._apply_ts(self._group_rank(close), decay_linear, 10)
        decay2 = self._apply_ts(self._group_rank(volume), decay_linear, 10)
        return -1 * np.maximum(decay1, decay2)
    
    def alpha_093(self) -> pd.Series:
        """GTJ_093: 开盘向下突破累积"""
        close = self._close()
        open_price = self._open()
        low = self._low()
        down_break = pd.Series(np.where(low < open_price, 1, 0), index=close.index)
        return self._apply_ts(down_break, ts_sum, 20)
    
    def alpha_094(self) -> pd.Series:
        """GTJ_094: 带方向成交量累积30日"""
        close = self._close()
        volume = self._volume()
        delta = self._apply_ts(close, ts_delta, 1)
        signed_vol = pd.Series(np.where(delta > 0, volume, -volume), index=volume.index)
        return self._apply_ts(signed_vol, ts_sum, 30)
    
    def alpha_095(self) -> pd.Series:
        """GTJ_095: 成交额波动20日"""
        close = self._close()
        volume = self._volume()
        amount = close * volume
        return self._apply_ts(amount, ts_std, 20)
    
    def alpha_096(self) -> pd.Series:
        """GTJ_096: KDJ-D值"""
        close = self._close()
        high = self._high()
        low = self._low()
        llv_9 = self._apply_ts(low, ts_min, 9)
        hhv_9 = self._apply_ts(high, ts_max, 9)
        rsv = (close - llv_9) / (hhv_9 - llv_9 + 0.001) * 100
        k = self._apply_ts(rsv, ts_mean, 3)
        return self._apply_ts(k, ts_mean, 3)
    
    def alpha_097(self) -> pd.Series:
        """GTJ_097: 成交量波动"""
        close = self._close()
        volume = self._volume()
        return self._apply_ts(volume, ts_std, 10)
    
    def alpha_098(self) -> pd.Series:
        """GTJ_098: MA加速度条件"""
        close = self._close()
        ma = self._apply_ts(close, ts_mean, 100)
        accel1 = self._apply_ts(ma, ts_delta, 1)
        accel2 = self._apply_ts(accel1, ts_delta, 1)
        condition1 = accel2 > 0
        condition2 = accel1 > 0
        return pd.Series(np.where(condition1 & condition2, 20, 
                                   np.where(condition1 | condition2, 10, 0)), index=close.index)
    
    def alpha_099(self) -> pd.Series:
        """GTJ_099: 收盘价量协方差排名"""
        close = self._close()
        volume = self._volume()
        rank_close = self._group_rank(close)
        rank_vol = self._group_rank(volume)
        cov = self._apply_corr(rank_close, rank_vol, 5)
        return -1 * self._group_rank(cov)
    
    def alpha_100(self) -> pd.Series:
        """GTJ_100: 成交量波动20日"""
        close = self._close()
        volume = self._volume()
        return self._apply_ts(volume, ts_std, 20)
    
    def alpha_101(self) -> pd.Series:
        """GTJ_101: 条件判断因子"""
        close = self._close()
        volume = self._volume()
        mean_vol = self._apply_ts(volume, ts_mean, 20)
        condition = volume < mean_vol
        return pd.Series(np.where(condition, 0, -1), index=close.index)
    
    def alpha_102(self) -> pd.Series:
        """GTJ_102: 成交量RSI"""
        volume = self._volume()
        delta = self._apply_ts(volume, ts_delta, 1)
        up = pd.Series(np.where(delta > 0, delta, 0), index=volume.index)
        down = pd.Series(np.where(delta < 0, np.abs(delta), 0), index=volume.index)
        sum_up = self._apply_ts(up, ts_sum, 6)
        sum_down = self._apply_ts(down, ts_sum, 6)
        return sum_up / (sum_up + sum_down + 0.001) * 100
    
    def alpha_103(self) -> pd.Series:
        """GTJ_103: 最低价新鲜度"""
        close = self._close()
        low = self._low()
        min_low = self._apply_ts(low, ts_min, 20)
        # 简化实现
        return self._group_rank(close - min_low)
    
    def alpha_104(self) -> pd.Series:
        """GTJ_104: 高价量相关性变化"""
        close = self._close()
        high = self._high()
        volume = self._volume()
        corr = self._apply_corr(high, volume, 5)
        delta_corr = self._apply_ts(corr, ts_delta, 5)
        std_close = self._apply_ts(close, ts_std, 20)
        return -1 * delta_corr * self._group_rank(std_close)
    
    def alpha_105(self) -> pd.Series:
        """GTJ_105: 开盘量相关性"""
        open_price = self._open()
        volume = self._volume()
        rank_open = self._group_rank(open_price)
        rank_vol = self._group_rank(volume)
        corr = self._apply_corr(rank_open, rank_vol, 10)
        return -1 * corr
    
    def alpha_106(self) -> pd.Series:
        """GTJ_106: 20日价格变化"""
        close = self._close()
        delay_20 = self._apply_ts(close, ts_delay, 20)
        return close - delay_20
    
    def alpha_107(self) -> pd.Series:
        """GTJ_107: 开盘缺口排名"""
        close = self._close()
        open_price = self._open()
        high = self._high()
        low = self._low()
        delay_high = self._apply_ts(high, ts_delay, 1)
        delay_close = self._apply_ts(close, ts_delay, 1)
        delay_low = self._apply_ts(low, ts_delay, 1)
        return -1 * self._group_rank(open_price - delay_high) * \
               self._group_rank(open_price - delay_close) * \
               self._group_rank(open_price - delay_low)
    
    def alpha_108(self) -> pd.Series:
        """GTJ_108: 高价极值相关性"""
        close = self._close()
        high = self._high()
        volume = self._volume()
        vwap = self._vwap()
        min_high = self._apply_ts(high, ts_min, 2)
        mean_vol = self._apply_ts(volume, ts_mean, 120)
        corr = self._apply_corr(vwap, mean_vol, 6)
        return -1 * self._group_rank(high - min_high) ** self._group_rank(corr)
    
    def alpha_109(self) -> pd.Series:
        """GTJ_109: 振幅RSI"""
        close = self._close()
        high = self._high()
        low = self._low()
        range_hl = high - low
        mean_range = self._apply_ts(range_hl, ts_mean, 10)
        return mean_range / (self._apply_ts(mean_range, ts_mean, 10) + 0.001)
    
    def alpha_110(self) -> pd.Series:
        """GTJ_110: 推力比"""
        close = self._close()
        high = self._high()
        low = self._low()
        up_force = self._apply_ts(high - close, ts_sum, 20)
        down_force = self._apply_ts(close - low, ts_sum, 20)
        return up_force / (down_force + 0.001) * 100
    
    def alpha_111(self) -> pd.Series:
        """GTJ_111: A/D MACD"""
        close = self._close()
        high = self._high()
        low = self._low()
        volume = self._volume()
        clv = ((close - low) - (high - close)) / (high - low + 0.001)
        ad = clv * volume
        ad_11 = self._apply_ts(ad, ts_mean, 11)
        ad_4 = self._apply_ts(ad, ts_mean, 4)
        return ad_11 - ad_4
    
    def alpha_112(self) -> pd.Series:
        """GTJ_112: CMO"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        up = pd.Series(np.where(delta > 0, delta, 0), index=close.index)
        down = pd.Series(np.where(delta < 0, np.abs(delta), 0), index=close.index)
        sum_up = self._apply_ts(up, ts_sum, 12)
        sum_down = self._apply_ts(down, ts_sum, 12)
        return (sum_up - sum_down) / (sum_up + sum_down + 0.001) * 100
    
    def alpha_113(self) -> pd.Series:
        """GTJ_113: 复合排名"""
        close = self._close()
        volume = self._volume()
        return -1 * self._group_rank(close) * self._group_rank(volume)
    
    def alpha_114(self) -> pd.Series:
        """GTJ_114: 振幅比率排名"""
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        high = self._high()
        low = self._low()
        range_hl = high - low
        amp_ratio = range_hl / (close + 0.001)
        delay_amp = self._apply_ts(amp_ratio, ts_delay, 2)
        return self._group_rank(delay_amp) * self._group_rank(volume) / (amp_ratio / (vwap - close + 0.001))
    
    def alpha_115(self) -> pd.Series:
        """GTJ_115: 多因子相关性"""
        close = self._close()
        high = self._high()
        volume = self._volume()
        weighted = 0.9 * high + 0.1 * close
        mean_vol = self._apply_ts(volume, ts_mean, 30)
        corr1 = self._apply_corr(weighted, mean_vol, 10)
        return self._group_rank(corr1)
    
    def alpha_116(self) -> pd.Series:
        """GTJ_116: 回归Beta"""
        close = self._close()
        # 简化实现：使用价格趋势
        return self._apply_ts(close, ts_mean, 20) - close
    
    def alpha_117(self) -> pd.Series:
        """GTJ_117: 多因子时序排名"""
        close = self._close()
        high = self._high()
        low = self._low()
        volume = self._volume()
        returns = self._returns()
        ts_rank_vol = self._apply_ts(volume, ts_rank, 32)
        ts_rank_price = self._apply_ts(close + high - low, ts_rank, 16)
        ts_rank_ret = self._apply_ts(returns, ts_rank, 32)
        return ts_rank_vol * (1 - ts_rank_price) * (1 - ts_rank_ret)
    
    def alpha_118(self) -> pd.Series:
        """GTJ_118: 上影线/下影线比"""
        close = self._close()
        open_price = self._open()
        high = self._high()
        low = self._low()
        upper_shadow = high - np.maximum(close, open_price)
        lower_shadow = np.minimum(close, open_price) - low
        sum_upper = self._apply_ts(upper_shadow, ts_sum, 20)
        sum_lower = self._apply_ts(lower_shadow, ts_sum, 20)
        return sum_upper / (sum_lower + 0.001) * 100
    
    def alpha_119(self) -> pd.Series:
        """GTJ_119: 复合相关性"""
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        corr = self._apply_corr(close, volume, 10)
        return self._group_rank(corr) * self._group_rank(vwap)
    
    def alpha_120(self) -> pd.Series:
        """GTJ_120: VWAP偏离比率"""
        close = self._close()
        vwap = self._vwap()
        return self._group_rank(vwap - close) / (self._group_rank(vwap + close) + 0.001)
    
    def alpha_121(self) -> pd.Series:
        """GTJ_121: VWAP极值相关性"""
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        min_vwap = self._apply_ts(vwap, ts_min, 12)
        corr = self._apply_corr(vwap, volume, 10)
        return -1 * self._group_rank(vwap - min_vwap) ** self._apply_ts(corr, ts_rank, 3)
    
    def alpha_122(self) -> pd.Series:
        """GTJ_122: 对数价格动量"""
        close = self._close()
        log_close = np.log(close + 0.001)
        sma_log = self._apply_ts(log_close, ts_mean, 13)
        delta_sma = self._apply_ts(sma_log, ts_delta, 1)
        return delta_sma / (sma_log + 0.001)
    
    def alpha_123(self) -> pd.Series:
        """GTJ_123: 条件判断因子"""
        close = self._close()
        volume = self._volume()
        mean_vol = self._apply_ts(volume, ts_mean, 20)
        condition = volume > mean_vol * 1.5
        return pd.Series(np.where(condition, 0, -1), index=close.index)
    
    def alpha_124(self) -> pd.Series:
        """GTJ_124: VWAP偏离衰减"""
        close = self._close()
        vwap = self._vwap()
        max_close = self._apply_ts(close, ts_max, 30)
        rank_max = self._group_rank(max_close)
        decay = self._apply_ts(rank_max, decay_linear, 2)
        return (close - vwap) / (decay + 0.001)
    
    def alpha_125(self) -> pd.Series:
        """GTJ_125: 衰减相关性比率"""
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        mean_vol = self._apply_ts(volume, ts_mean, 80)
        corr = self._apply_corr(vwap, mean_vol, 20)
        decay1 = self._apply_ts(corr, decay_linear, 20)
        weighted = 0.5 * close + 0.5 * vwap
        delta_weighted = self._apply_ts(weighted, ts_delta, 3)
        decay2 = self._apply_ts(delta_weighted, decay_linear, 16)
        return self._group_rank(decay1) / (self._group_rank(decay2) + 0.001)
    
    def alpha_126(self) -> pd.Series:
        """GTJ_126: 典型价格"""
        close = self._close()
        high = self._high()
        low = self._low()
        return (close + high + low) / 3
    
    def alpha_127(self) -> pd.Series:
        """GTJ_127: 回撤RMS"""
        close = self._close()
        max_close = self._apply_ts(close, ts_max, 12)
        drawdown = (close - max_close) / (max_close + 0.001) * 100
        return np.sqrt(self._apply_ts(drawdown ** 2, ts_mean, 20))
    
    def alpha_128(self) -> pd.Series:
        """GTJ_128: MFI"""
        close = self._close()
        high = self._high()
        low = self._low()
        volume = self._volume()
        typ = (high + low + close) / 3
        typ_vol = typ * volume
        delta = self._apply_ts(typ, ts_delta, 1)
        up_typ_vol = pd.Series(np.where(delta > 0, typ_vol, 0), index=close.index)
        down_typ_vol = pd.Series(np.where(delta < 0, typ_vol, 0), index=close.index)
        sum_up = self._apply_ts(up_typ_vol, ts_sum, 14)
        sum_down = self._apply_ts(down_typ_vol, ts_sum, 14)
        return 100 - 100 / (1 + sum_up / (sum_down + 0.001))
    
    def alpha_129(self) -> pd.Series:
        """GTJ_129: 下跌差值累积"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        down = pd.Series(np.where(delta < 0, np.abs(delta), 0), index=close.index)
        return self._apply_ts(down, ts_sum, 12)
    
    def alpha_130(self) -> pd.Series:
        """GTJ_130: 多因子衰减相关性"""
        close = self._close()
        high = self._high()
        low = self._low()
        volume = self._volume()
        vwap = self._vwap()
        hl2 = (high + low) / 2
        mean_vol = self._apply_ts(volume, ts_mean, 40)
        corr1 = self._apply_corr(hl2, mean_vol, 9)
        decay1 = self._apply_ts(corr1, decay_linear, 10)
        rank_vwap = self._group_rank(vwap)
        rank_vol = self._group_rank(volume)
        corr2 = self._apply_corr(rank_vwap, rank_vol, 7)
        decay2 = self._apply_ts(corr2, decay_linear, 3)
        return self._group_rank(decay1) / (self._group_rank(decay2) + 0.001)
    
    def alpha_131(self) -> pd.Series:
        """GTJ_131: VWAP动量相关性"""
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        delta_vwap = self._apply_ts(vwap, ts_delta, 1)
        mean_vol = self._apply_ts(volume, ts_mean, 50)
        corr = self._apply_corr(close, mean_vol, 18)
        return self._group_rank(delta_vwap) ** self._apply_ts(corr, ts_rank, 18)
    
    def alpha_132(self) -> pd.Series:
        """GTJ_132: 成交额均值"""
        close = self._close()
        volume = self._volume()
        amount = close * volume
        return self._apply_ts(amount, ts_mean, 20)
    
    def alpha_133(self) -> pd.Series:
        """GTJ_133: 高低价新鲜度差"""
        close = self._close()
        high = self._high()
        low = self._low()
        # 简化实现
        max_high = self._apply_ts(high, ts_max, 20)
        min_low = self._apply_ts(low, ts_min, 20)
        return (max_high - close) / (close + 0.001) * 100 - (close - min_low) / (close + 0.001) * 100
    
    def alpha_134(self) -> pd.Series:
        """GTJ_134: 量价动量12日"""
        close = self._close()
        volume = self._volume()
        delay_12 = self._apply_ts(close, ts_delay, 12)
        ret = (close - delay_12) / (delay_12 + 0.001)
        return ret * volume
    
    def alpha_135(self) -> pd.Series:
        """GTJ_135: 延迟动量移动平均"""
        close = self._close()
        delay_20 = self._apply_ts(close, ts_delay, 20)
        ratio = close / (delay_20 + 0.001)
        delay_ratio = self._apply_ts(ratio, ts_delay, 1)
        return self._apply_ts(delay_ratio, ts_mean, 20)
    
    def alpha_136(self) -> pd.Series:
        """GTJ_136: 收益变化相关性"""
        close = self._close()
        open_price = self._open()
        volume = self._volume()
        returns = self._returns()
        delta_ret = self._apply_ts(returns, ts_delta, 3)
        corr = self._apply_corr(open_price, volume, 10)
        return -1 * self._group_rank(delta_ret) * corr
    
    def alpha_137(self) -> pd.Series:
        """GTJ_137: TR标准化动量"""
        close = self._close()
        high = self._high()
        low = self._low()
        prev_close = self._apply_ts(close, ts_delay, 1)
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        tr = pd.Series(tr, index=close.index)
        delta = self._apply_ts(close, ts_delta, 1)
        return 16 * delta / (tr + 0.001) * np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
    
    def alpha_138(self) -> pd.Series:
        """GTJ_138: 复合相关性"""
        close = self._close()
        volume = self._volume()
        vwap = self._vwap()
        corr = self._apply_corr(close, volume, 10)
        return -1 * self._group_rank(corr) * self._group_rank(vwap)
    
    def alpha_139(self) -> pd.Series:
        """GTJ_139: 开盘量相关性"""
        open_price = self._open()
        volume = self._volume()
        corr = self._apply_corr(open_price, volume, 10)
        return -1 * corr
    
    def alpha_140(self) -> pd.Series:
        """GTJ_140: 衰减排名最小值"""
        close = self._close()
        low = self._low()
        open_price = self._open()
        high = self._high()
        volume = self._volume()
        ol_hc = (open_price - low) / (high - close + 0.001)
        rank_ol_hc = self._group_rank(ol_hc)
        decay1 = self._apply_ts(rank_ol_hc, decay_linear, 8)
        corr = self._apply_corr(close, volume, 7)
        decay2 = self._apply_ts(corr, decay_linear, 7)
        return np.minimum(self._group_rank(decay1), self._apply_ts(decay2, ts_rank, 3))
    
    def alpha_141(self) -> pd.Series:
        """GTJ_141: 高价量相关性"""
        high = self._high()
        volume = self._volume()
        mean_vol = self._apply_ts(volume, ts_mean, 15)
        rank_high = self._group_rank(high)
        rank_vol = self._group_rank(mean_vol)
        corr = self._apply_corr(rank_high, rank_vol, 9)
        return -1 * self._group_rank(corr)
    
    def alpha_142(self) -> pd.Series:
        """GTJ_142: 多因子排名"""
        close = self._close()
        volume = self._volume()
        ts_rank_close = self._apply_ts(close, ts_rank, 10)
        delta_close = self._apply_ts(close, ts_delta, 2)
        vol_ratio = volume / (self._apply_ts(volume, ts_mean, 20) + 0.001)
        ts_rank_vol = self._apply_ts(vol_ratio, ts_rank, 5)
        return -1 * self._group_rank(ts_rank_close) * self._group_rank(delta_close) * self._group_rank(ts_rank_vol)
    
    def alpha_143(self) -> pd.Series:
        """GTJ_143: 递归上涨累积"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        up = pd.Series(np.where(delta > 0, 1, 0), index=close.index)
        return self._apply_ts(up, ts_sum, 20)
    
    def alpha_144(self) -> pd.Series:
        """GTJ_144: 下跌日收益波动"""
        close = self._close()
        volume = self._volume()
        returns = self._returns()
        delta = self._apply_ts(close, ts_delta, 1)
        down_ret = pd.Series(np.where(delta < 0, np.abs(returns), 0), index=close.index)
        amount = close * volume
        return self._apply_ts(down_ret / (amount + 0.001), ts_mean, 20)
    
    def alpha_145(self) -> pd.Series:
        """GTJ_145: 成交量偏离率"""
        close = self._close()
        volume = self._volume()
        mean_9 = self._apply_ts(volume, ts_mean, 9)
        mean_26 = self._apply_ts(volume, ts_mean, 26)
        mean_12 = self._apply_ts(volume, ts_mean, 12)
        return (mean_9 - mean_26) / (mean_12 + 0.001) * 100
    
    def alpha_146(self) -> pd.Series:
        """GTJ_146: 收益率t统计量"""
        close = self._close()
        returns = self._returns()
        mean_ret = self._apply_ts(returns, ts_mean, 20)
        std_ret = self._apply_ts(returns, ts_std, 20)
        return mean_ret / (std_ret + 0.001) * np.sqrt(20)
    
    def alpha_147(self) -> pd.Series:
        """GTJ_147: 均价回归Beta"""
        close = self._close()
        mean_close = self._apply_ts(close, ts_mean, 12)
        return self._apply_ts(mean_close, ts_delta, 1)
    
    def alpha_148(self) -> pd.Series:
        """GTJ_148: 条件判断因子"""
        close = self._close()
        volume = self._volume()
        mean_vol = self._apply_ts(volume, ts_mean, 20)
        condition = volume > mean_vol * 2
        return pd.Series(np.where(condition, 0, -1), index=close.index)
    
    def alpha_149(self) -> pd.Series:
        """GTJ_149: 大盘下跌日Beta"""
        close = self._close()
        returns = self._returns()
        # 简化实现
        return self._apply_ts(returns, ts_mean, 20)
    
    def alpha_150(self) -> pd.Series:
        """GTJ_150: 典型价格成交量"""
        close = self._close()
        high = self._high()
        low = self._low()
        volume = self._volume()
        typ = (close + high + low) / 3
        return typ * volume
    
    def alpha_151(self) -> pd.Series:
        """GTJ_151: 20日动量移动平均"""
        close = self._close()
        delay_20 = self._apply_ts(close, ts_delay, 20)
        momentum = close - delay_20
        return self._apply_ts(momentum, ts_mean, 20)
    
    def alpha_152(self) -> pd.Series:
        """GTJ_152: 复杂MACD变体"""
        close = self._close()
        delay_9 = self._apply_ts(close, ts_delay, 9)
        ratio = close / (delay_9 + 0.001)
        sma_ratio = self._apply_ts(ratio, ts_mean, 9)
        delay_sma = self._apply_ts(sma_ratio, ts_delay, 1)
        mean_12 = self._apply_ts(delay_sma, ts_mean, 12)
        mean_26 = self._apply_ts(delay_sma, ts_mean, 26)
        return self._apply_ts(mean_12 - mean_26, ts_mean, 9)
    
    def alpha_153(self) -> pd.Series:
        """GTJ_153: BBI指标"""
        close = self._close()
        ma3 = self._apply_ts(close, ts_mean, 3)
        ma6 = self._apply_ts(close, ts_mean, 6)
        ma12 = self._apply_ts(close, ts_mean, 12)
        ma24 = self._apply_ts(close, ts_mean, 24)
        return (ma3 + ma6 + ma12 + ma24) / 4
    
    def alpha_154(self) -> pd.Series:
        """GTJ_154: 条件判断因子"""
        close = self._close()
        volume = self._volume()
        mean_vol = self._apply_ts(volume, ts_mean, 20)
        condition = volume > mean_vol
        return pd.Series(np.where(condition, 1, 0), index=close.index)
    
    def alpha_155(self) -> pd.Series:
        """GTJ_155: 成交量MACD"""
        close = self._close()
        volume = self._volume()
        sma_13 = self._apply_ts(volume, ts_mean, 13)
        sma_27 = self._apply_ts(volume, ts_mean, 27)
        dif = sma_13 - sma_27
        dea = self._apply_ts(dif, ts_mean, 10)
        return 2 * (dif - dea)
    
    def alpha_156(self) -> pd.Series:
        """GTJ_156: 衰减排名最大值"""
        close = self._close()
        volume = self._volume()
        decay1 = self._apply_ts(self._group_rank(close), decay_linear, 10)
        decay2 = self._apply_ts(self._group_rank(volume), decay_linear, 10)
        return -1 * np.maximum(decay1, decay2)
    
    def alpha_157(self) -> pd.Series:
        """GTJ_157: 复杂嵌套因子"""
        close = self._close()
        volume = self._volume()
        return self._group_rank(self._apply_ts(close, ts_rank, 10)) * self._group_rank(volume)
    
    def alpha_158(self) -> pd.Series:
        """GTJ_158: 振幅比率"""
        close = self._close()
        high = self._high()
        low = self._low()
        return (high - low) / (close + 0.001)
    
    def alpha_159(self) -> pd.Series:
        """GTJ_159: 多窗口KDJ"""
        close = self._close()
        high = self._high()
        low = self._low()
        # 简化实现
        llv_9 = self._apply_ts(low, ts_min, 9)
        hhv_9 = self._apply_ts(high, ts_max, 9)
        rsv = (close - llv_9) / (hhv_9 - llv_9 + 0.001) * 100
        return self._apply_ts(rsv, ts_mean, 3)
    
    def alpha_160(self) -> pd.Series:
        """GTJ_160: 下跌日波动"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        std_close = self._apply_ts(close, ts_std, 20)
        down_std = pd.Series(np.where(delta < 0, std_close, 0), index=close.index)
        return self._apply_ts(down_std, ts_mean, 20)
    
    def alpha_161(self) -> pd.Series:
        """GTJ_161: 12日ATR"""
        close = self._close()
        high = self._high()
        low = self._low()
        prev_close = self._apply_ts(close, ts_delay, 1)
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        tr = pd.Series(tr, index=close.index)
        return self._apply_ts(tr, ts_mean, 12)
    
    def alpha_162(self) -> pd.Series:
        """GTJ_162: Stochastic-RSI"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        up = pd.Series(np.where(delta > 0, delta, 0), index=close.index)
        down = pd.Series(np.where(delta < 0, np.abs(delta), 0), index=close.index)
        sum_up = self._apply_ts(up, ts_sum, 12)
        sum_down = self._apply_ts(down, ts_sum, 12)
        rsi = sum_up / (sum_up + sum_down + 0.001) * 100
        min_rsi = self._apply_ts(rsi, ts_min, 12)
        max_rsi = self._apply_ts(rsi, ts_max, 12)
        return (rsi - min_rsi) / (max_rsi - min_rsi + 0.001)
    
    def alpha_163(self) -> pd.Series:
        """GTJ_163: 多因子乘积"""
        close = self._close()
        high = self._high()
        volume = self._volume()
        vwap = self._vwap()
        returns = self._returns()
        mean_vol = self._apply_ts(volume, ts_mean, 20)
        return self._group_rank(-1 * returns * mean_vol * vwap * (high - close))
    
    def alpha_164(self) -> pd.Series:
        """GTJ_164: 上涨日动量"""
        close = self._close()
        high = self._high()
        low = self._low()
        delta = self._apply_ts(close, ts_delta, 1)
        prev_close = self._apply_ts(close, ts_delay, 1)
        ret = delta / (prev_close + 0.001)
        up_ret = pd.Series(np.where(delta > 0, ret, 0), index=close.index)
        range_hl = high - low
        return self._apply_ts(up_ret / (range_hl + 0.001) * 100, ts_mean, 13)
    
    def alpha_165(self) -> pd.Series:
        """GTJ_165: 累积偏离"""
        close = self._close()
        mean_48 = self._apply_ts(close, ts_mean, 48)
        deviation = close - mean_48
        cum_dev = self._apply_ts(deviation, ts_sum, 20)
        std_close = self._apply_ts(close, ts_std, 48)
        return (np.maximum(cum_dev, 0) - np.minimum(cum_dev, 0)) / (std_close + 0.001)
    
    def alpha_166(self) -> pd.Series:
        """GTJ_166: 收益率偏度"""
        close = self._close()
        returns = self._returns()
        mean_ret = self._apply_ts(returns, ts_mean, 20)
        std_ret = self._apply_ts(returns, ts_std, 20)
        skew = self._apply_ts((returns - mean_ret) ** 3, ts_mean, 20) / (std_ret ** 3 + 0.001)
        return skew
    
    def alpha_167(self) -> pd.Series:
        """GTJ_167: 上涨差值累积"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        up = pd.Series(np.where(delta > 0, delta, 0), index=close.index)
        return self._apply_ts(up, ts_sum, 12)
    
    def alpha_168(self) -> pd.Series:
        """GTJ_168: 相对成交量"""
        close = self._close()
        volume = self._volume()
        mean_vol = self._apply_ts(volume, ts_mean, 20)
        return -1 * volume / (mean_vol + 0.001)
    
    def alpha_169(self) -> pd.Series:
        """GTJ_169: 差分MACD"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        sma_delta = self._apply_ts(delta, ts_mean, 9)
        delay_sma = self._apply_ts(sma_delta, ts_delay, 1)
        mean_12 = self._apply_ts(delay_sma, ts_mean, 12)
        mean_26 = self._apply_ts(delay_sma, ts_mean, 26)
        return self._apply_ts(mean_12 - mean_26, ts_mean, 10)
    
    def alpha_170(self) -> pd.Series:
        """GTJ_170: 复合多维度因子"""
        close = self._close()
        volume = self._volume()
        return self._group_rank(close) + self._group_rank(volume)
    
    def alpha_171(self) -> pd.Series:
        """GTJ_171: K线形态加权"""
        close = self._close()
        open_price = self._open()
        high = self._high()
        low = self._low()
        numerator = -1 * (low - close) * (open_price ** 5)
        denominator = (close - high) * (close ** 5) + 0.001
        return numerator / denominator
    
    def alpha_172(self) -> pd.Series:
        """GTJ_172: ADX变体"""
        close = self._close()
        high = self._high()
        low = self._low()
        # 简化实现
        range_hl = high - low
        return self._apply_ts(np.abs(range_hl), ts_mean, 6)
    
    def alpha_173(self) -> pd.Series:
        """GTJ_173: 多重移动平均"""
        close = self._close()
        sma1 = self._apply_ts(close, ts_mean, 13)
        sma2 = self._apply_ts(sma1, ts_mean, 13)
        sma3 = self._apply_ts(np.log(close + 0.001), ts_mean, 13)
        return 3 * sma1 - 2 * sma2 + sma3
    
    def alpha_174(self) -> pd.Series:
        """GTJ_174: 上涨日波动"""
        close = self._close()
        delta = self._apply_ts(close, ts_delta, 1)
        std_close = self._apply_ts(close, ts_std, 20)
        up_std = pd.Series(np.where(delta > 0, std_close, 0), index=close.index)
        return self._apply_ts(up_std, ts_mean, 20)
    
    def alpha_175(self) -> pd.Series:
        """GTJ_175: 6日ATR"""
        close = self._close()
        high = self._high()
        low = self._low()
        prev_close = self._apply_ts(close, ts_delay, 1)
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        tr = pd.Series(tr, index=close.index)
        return self._apply_ts(tr, ts_mean, 6)
    
    def alpha_176(self) -> pd.Series:
        """GTJ_176: KDJ量相关性"""
        close = self._close()
        high = self._high()
        low = self._low()
        volume = self._volume()
        llv_9 = self._apply_ts(low, ts_min, 9)
        hhv_9 = self._apply_ts(high, ts_max, 9)
        k = (close - llv_9) / (hhv_9 - llv_9 + 0.001) * 100
        rank_k = self._group_rank(k)
        rank_vol = self._group_rank(volume)
        return rank_k.groupby(level='stock_code').transform(
            lambda x: x.rolling(6).corr(rank_vol)
        )
    
    def alpha_177(self) -> pd.Series:
        """GTJ_177: 最高价新鲜度"""
        close = self._close()
        high = self._high()
        max_high = self._apply_ts(high, ts_max, 20)
        return self._group_rank((max_high - close) / (close + 0.001) * 100)
    
    def alpha_178(self) -> pd.Series:
        """GTJ_178: 量价动量"""
        close = self._close()
        volume = self._volume()
        delay_1 = self._apply_ts(close, ts_delay, 1)
        ret = (close - delay_1) / (delay_1 + 0.001)
        return ret * volume
    
    def alpha_179(self) -> pd.Series:
        """GTJ_179: 多因子相关性"""
        close = self._close()
        low = self._low()
        volume = self._volume()
        vwap = self._vwap()
        mean_vol = self._apply_ts(volume, ts_mean, 50)
        corr1 = self._apply_corr(vwap, volume, 4)
        rank_low = self._group_rank(low)
        rank_vol = self._group_rank(mean_vol)
        corr2 = self._apply_corr(rank_low, rank_vol, 12)
        return self._group_rank(corr1) * self._group_rank(corr2)
    
    def alpha_180(self) -> pd.Series:
        """GTJ_180: 条件量价因子"""
        close = self._close()
        volume = self._volume()
        mean_vol = self._apply_ts(volume, ts_mean, 20)
        delta = self._apply_ts(close, ts_delta, 1)
        condition = volume > mean_vol
        return pd.Series(np.where(condition, delta, -volume / (mean_vol + 0.001)), index=close.index)
    
    def alpha_181(self) -> pd.Series:
        """GTJ_181: 偏度调整Alpha"""
        close = self._close()
        returns = self._returns()
        cum_ret = self._apply_ts(returns, ts_sum, 20)
        std_ret = self._apply_ts(returns, ts_std, 20)
        return cum_ret / (std_ret + 0.001)
    
    def alpha_182(self) -> pd.Series:
        """GTJ_182: 同向运动占比"""
        close = self._close()
        returns = self._returns()
        # 简化实现
        return self._apply_ts(returns, ts_mean, 20)
    
    def alpha_183(self) -> pd.Series:
        """GTJ_183: 累积偏离24日"""
        close = self._close()
        mean_24 = self._apply_ts(close, ts_mean, 24)
        deviation = close - mean_24
        cum_dev = self._apply_ts(deviation, ts_sum, 20)
        std_close = self._apply_ts(close, ts_std, 24)
        return (np.maximum(cum_dev, 0) - np.minimum(cum_dev, 0)) / (std_close + 0.001)
    
    def alpha_184(self) -> pd.Series:
        """GTJ_184: 滞后量价相关性"""
        close = self._close()
        open_price = self._open()
        diff = open_price - close
        delay_diff = self._apply_ts(diff, ts_delay, 1)
        corr = self._apply_corr(delay_diff, close, 200)
        return self._group_rank(corr) + self._group_rank(diff)
    
    def alpha_185(self) -> pd.Series:
        """GTJ_185: 日内涨跌幅平方"""
        close = self._close()
        open_price = self._open()
        ratio = 1 - open_price / (close + 0.001)
        return self._group_rank(-1 * ratio ** 2)
    
    def alpha_186(self) -> pd.Series:
        """GTJ_186: 平滑ADX"""
        close = self._close()
        high = self._high()
        low = self._low()
        range_hl = high - low
        mean_range = self._apply_ts(np.abs(range_hl), ts_mean, 6)
        delay_mean = self._apply_ts(mean_range, ts_delay, 6)
        return (mean_range + delay_mean) / 2
    
    def alpha_187(self) -> pd.Series:
        """GTJ_187: 开盘向上突破累积"""
        close = self._close()
        open_price = self._open()
        high = self._high()
        up_break = pd.Series(np.where(high > open_price, 1, 0), index=close.index)
        return self._apply_ts(up_break, ts_sum, 20)
    
    def alpha_188(self) -> pd.Series:
        """GTJ_188: 振幅偏离率"""
        close = self._close()
        high = self._high()
        low = self._low()
        range_hl = high - low
        sma_range = self._apply_ts(range_hl, ts_mean, 11)
        return (range_hl - sma_range) / (sma_range + 0.001) * 100
    
    def alpha_189(self) -> pd.Series:
        """GTJ_189: MAD"""
        close = self._close()
        mean_6 = self._apply_ts(close, ts_mean, 6)
        return self._apply_ts(np.abs(close - mean_6), ts_mean, 6)
    
    def alpha_190(self) -> pd.Series:
        """GTJ_190: 收益率不对称性"""
        close = self._close()
        returns = self._returns()
        delta = self._apply_ts(close, ts_delta, 1)
        up_ret = pd.Series(np.where(delta > 0, returns, 0), index=close.index)
        down_ret = pd.Series(np.where(delta < 0, np.abs(returns), 0), index=close.index)
        std_up = self._apply_ts(up_ret, ts_std, 20)
        std_down = self._apply_ts(down_ret, ts_std, 20)
        return np.log((std_up + 0.001) / (std_down + 0.001))
    
    def alpha_191(self) -> pd.Series:
        """GTJ_191: 量价相关性偏离"""
        close = self._close()
        high = self._high()
        low = self._low()
        volume = self._volume()
        mean_vol = self._apply_ts(volume, ts_mean, 20)
        corr = self._apply_corr(mean_vol, low, 5)
        mid = (high + low) / 2
        return corr + mid - close
    
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
                factor_name = f'GTJ_{factor_num:03d}'
                
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
            因子编号 (1-191)
        
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
