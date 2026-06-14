"""
时序算子（Time-Series Operators）
================================

所有算子接受 DataFrame（MultiIndex: [trade_date, stock_code]），
返回与输入同形状的 Series 或 DataFrame。
"""
import numpy as np
import pandas as pd


def ts_mean(df: pd.DataFrame, window: int) -> pd.Series:
    """时序移动平均"""
    return df.groupby(level='stock_code').rolling(window, min_periods=1).mean().reset_index(level=0, drop=True)


def ts_std(df: pd.DataFrame, window: int) -> pd.Series:
    """时序移动标准差"""
    return df.groupby(level='stock_code').rolling(window, min_periods=1).std().reset_index(level=0, drop=True)


def ts_sum(df: pd.DataFrame, window: int) -> pd.Series:
    """时序移动求和"""
    return df.groupby(level='stock_code').rolling(window, min_periods=1).sum().reset_index(level=0, drop=True)


def ts_max(df: pd.DataFrame, window: int) -> pd.Series:
    """时序移动最大值"""
    return df.groupby(level='stock_code').rolling(window, min_periods=1).max().reset_index(level=0, drop=True)


def ts_min(df: pd.DataFrame, window: int) -> pd.Series:
    """时序移动最小值"""
    return df.groupby(level='stock_code').rolling(window, min_periods=1).min().reset_index(level=0, drop=True)


def ts_rank(df: pd.DataFrame, window: int) -> pd.Series:
    """
    时序排序（当前值在过去 window 天内的分位排名 0~1）
    """
    def _rank(s):
        return pd.Series(s).rank(pct=True).iloc[-1]

    return df.groupby(level='stock_code').rolling(window, min_periods=1).apply(_rank, raw=True).reset_index(level=0, drop=True)


def ts_delta(df: pd.DataFrame, period: int) -> pd.Series:
    """时序差分（当前值 - period 天前的值）"""
    return df.groupby(level='stock_code').diff(period)


def ts_delay(df: pd.DataFrame, period: int) -> pd.Series:
    """时序滞后（period 天前的值）"""
    return df.groupby(level='stock_code').shift(period)


def ts_corr(df_a: pd.DataFrame, df_b: pd.DataFrame, window: int) -> pd.Series:
    """时序相关系数"""
    a = df_a.groupby(level='stock_code')
    b = df_b.groupby(level='stock_code')
    result = pd.Series(index=df_a.index, dtype=float)
    for code in df_a.index.get_level_values('stock_code').unique():
        a_s = a.get_group(code)
        b_s = b.get_group(code)
        result.loc[a_s.index] = a_s.iloc[:, 0].rolling(window, min_periods=1).corr(b_s.iloc[:, 0]).values
    return result


def ts_cov(df_a: pd.DataFrame, df_b: pd.DataFrame, window: int) -> pd.Series:
    """时序协方差"""
    a = df_a.groupby(level='stock_code')
    b = df_b.groupby(level='stock_code')
    result = pd.Series(index=df_a.index, dtype=float)
    for code in df_a.index.get_level_values('stock_code').unique():
        a_s = a.get_group(code)
        b_s = b.get_group(code)
        result.loc[a_s.index] = a_s.iloc[:, 0].rolling(window, min_periods=1).cov(b_s.iloc[:, 0]).values
    return result


def ts_decay_linear(df: pd.DataFrame, window: int) -> pd.Series:
    """
    线性衰减移动平均（最近权重最大）

    权重: 1, 2, 3, ..., window
    """
    weights = np.arange(1, window + 1, dtype=float)
    weights /= weights.sum()

    def _apply(s):
        # rolling apply with raw=True, s is numpy ndarray
        if len(s) < window:
            return np.nan
        return np.dot(s[-window:], weights[::-1])

    return df.groupby(level='stock_code').rolling(window, min_periods=window).apply(_apply, raw=True).reset_index(level=0, drop=True)


def ts_decay_exp(df: pd.DataFrame, window: int, halflife: int = None) -> pd.Series:
    """
    指数衰减移动平均（最近权重最大）

    halflife: 半衰期（默认 window / 2）
    """
    if halflife is None:
        halflife = max(1, window // 2)
    return df.groupby(level='stock_code').ewm(halflife=halflife, adjust=False).mean().reset_index(level=0, drop=True)


def ts_argmax(df: pd.DataFrame, window: int) -> pd.Series:
    """时序窗口内最大值位置"""
    return df.groupby(level='stock_code').rolling(window, min_periods=1).apply(lambda x: np.argmax(x), raw=True).reset_index(level=0, drop=True)


def ts_argmin(df: pd.DataFrame, window: int) -> pd.Series:
    """时序窗口内最小值位置"""
    return df.groupby(level='stock_code').rolling(window, min_periods=1).apply(lambda x: np.argmin(x), raw=True).reset_index(level=0, drop=True)


def ts_skew(df: pd.DataFrame, window: int) -> pd.Series:
    """时序偏度"""
    return df.groupby(level='stock_code').rolling(window, min_periods=3).skew().reset_index(level=0, drop=True)


def ts_kurt(df: pd.DataFrame, window: int) -> pd.Series:
    """时序峰度"""
    return df.groupby(level='stock_code').rolling(window, min_periods=4).kurt().reset_index(level=0, drop=True)


def ts_median(df: pd.DataFrame, window: int) -> pd.Series:
    """时序中位数"""
    return df.groupby(level='stock_code').rolling(window, min_periods=1).median().reset_index(level=0, drop=True)


def ts_quantile(df: pd.DataFrame, window: int, q: float = 0.5) -> pd.Series:
    """时序分位数"""
    return df.groupby(level='stock_code').rolling(window, min_periods=1).quantile(q).reset_index(level=0, drop=True)


def ts_ema(df: pd.DataFrame, window: int) -> pd.Series:
    """时序指数移动平均"""
    return df.groupby(level='stock_code').ewm(span=window, adjust=False).mean().reset_index(level=0, drop=True)
