"""
横截面算子（Cross-Sectional Operators）
======================================

对每个交易日，所有股票横截面上做计算。
"""
import numpy as np
import pandas as pd


def rank(df: pd.DataFrame) -> pd.Series:
    """横截面排名（百分比 0~1）"""
    return df.groupby(level='trade_date').rank(pct=True)


def scale(df: pd.DataFrame, target_sum: float = 1.0) -> pd.Series:
    """横截面缩放（使每日总和为 target_sum）"""
    def _scale(s):
        s_sum = float(s.abs().sum())
        if s_sum == 0 or np.isnan(s_sum):
            return s
        return s / s_sum * target_sum

    return df.groupby(level='trade_date').apply(_scale)


def normalize(df: pd.DataFrame) -> pd.Series:
    """横截面归一化（减均值除以绝对均值之和）"""
    def _normalize(s):
        s_mean = float(s.mean())
        s_abs_mean = float(s.abs().mean())
        if s_abs_mean == 0 or np.isnan(s_abs_mean):
            return s - s_mean
        return (s - s_mean) / s_abs_mean

    return df.groupby(level='trade_date').apply(_normalize)


def neutralize(df: pd.DataFrame, by: pd.Series = None) -> pd.Series:
    """
    横截面中性化（对分组做正交化）
    不传 by 时做 demean（去均值）
    """
    if by is None:
        return df.groupby(level='trade_date').transform(lambda s: s - s.mean())
    return df.groupby(level=['trade_date', by]).transform(lambda s: s - s.mean())


def mad(df: pd.DataFrame) -> pd.Series:
    """横截面中位数绝对偏差"""
    def _mad(s):
        med = s.median()
        if hasattr(med, 'iloc'):
            med = float(med.iloc[0])
        else:
            med = float(med)
        return (s - med).abs().median()

    return df.groupby(level='trade_date').transform(_mad)


def zscore(df: pd.DataFrame) -> pd.Series:
    """横截面 z-score（减均值除以标准差）"""
    def _zscore(s):
        std = s.std()
        mean = s.mean()
        if hasattr(std, 'iloc'):
            std = float(std.iloc[0])
        else:
            std = float(std)
        if hasattr(mean, 'iloc'):
            mean = float(mean.iloc[0])
        else:
            mean = float(mean)
        if std == 0 or np.isnan(std):
            return s - mean
        return (s - mean) / std

    return df.groupby(level='trade_date').transform(_zscore)


def demean(df: pd.DataFrame) -> pd.Series:
    """横截面去均值"""
    return df.groupby(level='trade_date').transform(lambda s: s - s.mean())
