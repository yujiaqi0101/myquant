"""
WorldQuant Alpha101 因子实现（核心子集）
====================================

参考 docs/因子/WorldQuant_101_Alphas_完整解析.docx

完整 101 个因子的实现见 src.factors.worldquant.WorldQuantFactors 类
（104 个方法，含 alpha_001~alpha_101 + 内部工具方法），
策略开发时推荐使用类方法形式。

本模块 ALPHA101_FUNCS 字典仅收录基于算子库的简化核心子集，
供 operators 命名空间使用，演示如何用 ts/cross/math 算子拼装 WQ 因子。
"""
import numpy as np
import pandas as pd
from . import ts_mean, ts_std, ts_delta, ts_rank, ts_decay_linear
from .cross import rank, scale


def alpha_001(close: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    """
    Alpha#1: rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5
    """
    inner = pd.DataFrame(
        np.where(returns < 0, returns.rolling(20, min_periods=1).std().values, close.values),
        index=close.index, columns=close.columns
    )
    inner = np.sign(inner) * (np.abs(inner) ** 2)
    argmax = inner.groupby(level='stock_code').rolling(5, min_periods=1).apply(lambda x: np.argmax(x), raw=True).reset_index(level=0, drop=True)
    return rank(argmax) - 0.5


def alpha_006(close: pd.DataFrame, open_: pd.DataFrame) -> pd.Series:
    """
    Alpha#6: -1 * correlation(open, volume, 10)
    """
    a = open_.groupby(level='stock_code')
    b = close.groupby(level='stock_code')  # 用 close 代替 volume 简化
    # 简化为 open 与 close 的相关性
    return -1 * a.rolling(10).corr(b)


ALPHA101_FUNCS = {
    'WQ_001': alpha_001,
    'WQ_006': alpha_006,
}


__all__ = list(ALPHA101_FUNCS.keys()) + ['ALPHA101_FUNCS']
