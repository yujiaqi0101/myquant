"""
数学算子（Math Operators）
=========================

对元素级别（element-wise）的数学运算。
"""
import numpy as np
import pandas as pd


def log(df: pd.DataFrame) -> pd.Series:
    """自然对数"""
    return np.log(df.replace(0, np.nan))


def sign(df: pd.DataFrame) -> pd.Series:
    """符号函数"""
    return np.sign(df)


def signed_power(df: pd.DataFrame, exponent: float) -> pd.Series:
    """保留符号的幂"""
    return np.sign(df) * (np.abs(df) ** exponent)


def abs_(df: pd.DataFrame) -> pd.Series:
    """绝对值"""
    return np.abs(df)


def max_(df_a: pd.DataFrame, df_b) -> pd.Series:
    """逐元素最大值"""
    return np.maximum(df_a, df_b)


def min_(df_a: pd.DataFrame, df_b) -> pd.Series:
    """逐元素最小值"""
    return np.minimum(df_a, df_b)


def where(condition, x, y) -> pd.Series:
    """三目运算（np.where）"""
    result = np.where(condition, x, y)
    if isinstance(result, np.ndarray) and result.ndim > 1:
        result = result.ravel()
    return pd.Series(result, index=condition.index)


def decay_linear(df: pd.DataFrame, window: int) -> pd.Series:
    """
    线性衰减（与 ts_decay_linear 同义，简写形式）
    权重: 1, 2, ..., window
    """
    from .ts import ts_decay_linear
    return ts_decay_linear(df, window)


def decay_exp(df: pd.DataFrame, halflife: int) -> pd.Series:
    """
    指数衰减（halflife 半衰期）
    """
    return df.groupby(level='stock_code').ewm(halflife=halflife, adjust=False).mean().reset_index(level=0, drop=True)
