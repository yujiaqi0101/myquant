"""
国泰君安 Alpha191 因子实现（核心子集）
====================================

参考 docs/因子/国泰君安Alpha191因子公式详解.docx

完整 191 个因子的实现见 src.factors.guotai.GuotaiFactors 类
（194 个方法，含 alpha_001~alpha_191 + 内部工具方法），
策略开发时推荐使用类方法形式。

本模块 ALPHA191_FUNCS 字典仅收录基于算子库的简化核心子集，
供 operators 命名空间使用，演示如何用 ts/cross/math 算子拼装国泰君安因子。
"""
import numpy as np
import pandas as pd
from . import ts_mean, ts_std, ts_corr, ts_decay_linear
from .cross import rank


def alpha_002(close: pd.DataFrame, low: pd.DataFrame, high: pd.DataFrame, open_: pd.DataFrame) -> pd.Series:
    """
    Alpha#2: ((-1 * delta((((close - low) - (high - close)) / (close - low)), 9)))
    简化版
    """
    diff = (close - low) - (high - close)
    ratio = diff / (close - low).replace(0, np.nan)
    return -1 * ratio.groupby(level='stock_code').diff(9)


def alpha_012(close: pd.DataFrame, volume: pd.DataFrame) -> pd.Series:
    """
    Alpha#12: sign(delta(volume, 1)) * (-1 * delta(close, 1))
    """
    sign_v = np.sign(volume.groupby(level='stock_code').diff(1))
    delta_c = close.groupby(level='stock_code').diff(1)
    return sign_v * (-1 * delta_c)


ALPHA191_FUNCS = {
    'GTJ_002': alpha_002,
    'GTJ_012': alpha_012,
}


__all__ = list(ALPHA191_FUNCS.keys()) + ['ALPHA191_FUNCS']
