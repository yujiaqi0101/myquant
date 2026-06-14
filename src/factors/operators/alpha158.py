"""
Qlib Alpha158 因子实现（核心子集）
==================================

参考 Qlib 内置 Alpha158 公式（Qlib 文档 `docs/因子/Qlib_Alpha158_因子详解手册.docx`
在当前环境中未提供，故按 Qlib 公开实现选择 30 个最常用算子）。

Alpha158 一共 ~158 个特征，由 6 大类组成：
- KBar（K 线形态）  — KMID / KLEN / KUP / KLOW / KSFT 等
- Price（时序价）    — OPEN_n / HIGH_n / LOW_n / CLOSE_n
- Volume（时序量）   — VOLUME_n / AMOUNT_n
- Rolling（时序统计）— MA_n / STD_n / MAX_n / MIN_n / QS_n / TS-Ref
- Pattern（形态）    — ROC / ROCR / RSV / RSI / CCI / ATR / BOLL
- Cross-Section（横截面）— BETA / RSQR / RESI

完整 ~158 因子在 `src.factors.calculator.Alpha158Calculator` 类中
（按需扩展），本模块 ALPHA158_FUNCS 提供基于 ts/cross/math 算子拼装的
核心子集。

数据约定
--------
- 输入：pd.DataFrame 或 pd.Series，MultiIndex [trade_date, stock_code]
- 输出：pd.Series（同 MultiIndex，单列）
- 所有输入 df 内部先 squeeze 成单列（`v.iloc[:, 0]`），避免
  DataFrame 列名错位时 pandas 走 outer-join 产生全 NaN。
"""
import numpy as np
import pandas as pd

from . import (
    ts_mean, ts_std, ts_sum, ts_max, ts_min,
    ts_rank, ts_delta, ts_decay_linear, ts_decay_exp,
)
from .cross import rank, scale
from .math_ops import log as ts_log, sign, signed_power, where, abs_ as ts_abs


def _s(v):
    """把单列 DataFrame 压成 Series，避免列名错位时 pandas 走 outer-join。"""
    if isinstance(v, pd.DataFrame):
        if v.shape[1] == 1:
            return v.iloc[:, 0]
        # 多列时不强行压窄，保留原样（外层算子自己处理）
    return v


# ============================================================
# 1. KBar 类（K 线形态）
# ============================================================

def kbar_kmid(open_: pd.DataFrame, close: pd.DataFrame) -> pd.Series:
    """(close - open) / open"""
    o, c = _s(open_), _s(close)
    return (c - o) / o.replace(0, np.nan)


def kbar_klen(high: pd.DataFrame, low: pd.DataFrame, open_: pd.DataFrame) -> pd.Series:
    """(high - low) / open"""
    h, l, o = _s(high), _s(low), _s(open_)
    return (h - l) / o.replace(0, np.nan)


def kbar_kmid2(high: pd.DataFrame, low: pd.DataFrame, open_: pd.DataFrame,
               close: pd.DataFrame) -> pd.Series:
    """(close - open) / (high - low)"""
    h, l, o, c = _s(high), _s(low), _s(open_), _s(close)
    hl = (h - l).replace(0, np.nan)
    return (c - o) / hl


def kbar_kup(high: pd.DataFrame, open_: pd.DataFrame, close: pd.DataFrame) -> pd.Series:
    """(high - max(open, close)) / open"""
    h, o, c = _s(high), _s(open_), _s(close)
    upper = h - pd.concat([o, c], axis=1).max(axis=1)
    return upper / o.replace(0, np.nan)


def kbar_kup2(high: pd.DataFrame, low: pd.DataFrame, open_: pd.DataFrame,
              close: pd.DataFrame) -> pd.Series:
    """(high - max(open, close)) / (high - low)"""
    h, l, o, c = _s(high), _s(low), _s(open_), _s(close)
    hl = (h - l).replace(0, np.nan)
    upper = h - pd.concat([o, c], axis=1).max(axis=1)
    return upper / hl


def kbar_klow(low: pd.DataFrame, open_: pd.DataFrame, close: pd.DataFrame) -> pd.Series:
    """(min(open, close) - low) / open"""
    l, o, c = _s(low), _s(open_), _s(close)
    lower = pd.concat([o, c], axis=1).min(axis=1) - l
    return lower / o.replace(0, np.nan)


def kbar_klow2(high: pd.DataFrame, low: pd.DataFrame, open_: pd.DataFrame,
               close: pd.DataFrame) -> pd.Series:
    """(min(open, close) - low) / (high - low)"""
    h, l, o, c = _s(high), _s(low), _s(open_), _s(close)
    hl = (h - l).replace(0, np.nan)
    lower = pd.concat([o, c], axis=1).min(axis=1) - l
    return lower / hl


def kbar_ksft(high: pd.DataFrame, low: pd.DataFrame, open_: pd.DataFrame,
              close: pd.DataFrame) -> pd.Series:
    """(2*close - high - low) / open"""
    h, l, o, c = _s(high), _s(low), _s(open_), _s(close)
    return (2 * c - h - l) / o.replace(0, np.nan)


def kbar_ksft2(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame) -> pd.Series:
    """(2*close - high - low) / (high - low)"""
    h, l, c = _s(high), _s(low), _s(close)
    hl = (h - l).replace(0, np.nan)
    return (2 * c - h - l) / hl


# ============================================================
# 2. Price / Volume 时序类
# ============================================================

def price_high_n(high: pd.DataFrame, n: int) -> pd.Series:
    """HIGH 价过去 n 天的值"""
    return _s(high).groupby(level='stock_code').shift(n)


def price_low_n(low: pd.DataFrame, n: int) -> pd.Series:
    return _s(low).groupby(level='stock_code').shift(n)


def price_close_n(close: pd.DataFrame, n: int) -> pd.Series:
    return _s(close).groupby(level='stock_code').shift(n)


def price_open_n(open_: pd.DataFrame, n: int) -> pd.Series:
    return _s(open_).groupby(level='stock_code').shift(n)


def volume_mean_n(volume: pd.DataFrame, n: int) -> pd.Series:
    return ts_mean(_s(volume), n)


# ============================================================
# 3. Rolling 统计类
# ============================================================

def rolling_mean(close: pd.DataFrame, n: int) -> pd.Series:
    """N 日均价"""
    return ts_mean(_s(close), n)


def rolling_std(close: pd.DataFrame, n: int) -> pd.Series:
    """N 日标准差"""
    return ts_std(_s(close), n)


def rolling_sum(volume: pd.DataFrame, n: int) -> pd.Series:
    """N 日成交量之和"""
    return ts_sum(_s(volume), n)


def rolling_skew(close: pd.DataFrame, n: int) -> pd.Series:
    """N 日偏度"""
    return _s(close).groupby(level='stock_code').rolling(n, min_periods=1).skew().reset_index(level=0, drop=True)


def rolling_kurt(close: pd.DataFrame, n: int) -> pd.Series:
    """N 日峰度"""
    return _s(close).groupby(level='stock_code').rolling(n, min_periods=1).kurt().reset_index(level=0, drop=True)


def rolling_qs(close: pd.DataFrame, n: int, q: float = 0.5) -> pd.Series:
    """N 日滚动分位数"""
    return _s(close).groupby(level='stock_code').rolling(n, min_periods=1).quantile(q).reset_index(level=0, drop=True)


# ============================================================
# 4. Pattern 类
# ============================================================

def pattern_roc(close: pd.DataFrame, n: int) -> pd.Series:
    """ROC = close / delay(close, n) - 1"""
    c = _s(close)
    delayed = c.groupby(level='stock_code').shift(n)
    return c / delayed.replace(0, np.nan) - 1


def pattern_rocr(close: pd.DataFrame, n: int) -> pd.Series:
    """ROCR = close / delay(close, n)"""
    c = _s(close)
    delayed = c.groupby(level='stock_code').shift(n)
    return c / delayed.replace(0, np.nan)


def pattern_rsv(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, n: int) -> pd.Series:
    """RSV = (close - low_n) / (high_n - low_n)"""
    h, l, c = _s(high), _s(low), _s(close)
    h_n = ts_max(h, n)
    l_n = ts_min(l, n)
    diff = (h_n - l_n).replace(0, np.nan)
    return (c - l_n) / diff


def pattern_rsi(close: pd.DataFrame, n: int = 14) -> pd.Series:
    """RSI = SMA(gain, n) / (SMA(gain, n) + SMA(loss, n))

    简化：用 ts_mean 替代 SMA
    """
    c = _s(close)
    delta = ts_delta(c, 1)
    gain = where(delta > 0, delta, 0.0)
    loss = where(delta < 0, -delta, 0.0)
    avg_gain = ts_mean(gain, n)
    avg_loss = ts_mean(loss, n)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return rs / (1 + rs)


def pattern_cci(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, n: int = 14) -> pd.Series:
    """CCI = (tp - SMA(tp, n)) / (0.015 * MAD(tp, n))"""
    h, l, c = _s(high), _s(low), _s(close)
    tp = (h + l + c) / 3.0
    sma = ts_mean(tp, n)
    mad = tp.groupby(level='stock_code').rolling(n, min_periods=1).apply(
        lambda x: (x - x.mean()).abs().mean(), raw=True
    ).reset_index(level=0, drop=True)
    return (tp - sma) / (0.015 * mad.replace(0, np.nan))


def pattern_atr(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, n: int = 14) -> pd.Series:
    """ATR = ts_mean(true_range, n)

    true_range = max(high - low, |high - close_prev|, |low - close_prev|)
    """
    h, l, c = _s(high), _s(low), _s(close)
    high_low = h - l
    close_prev = c.groupby(level='stock_code').shift(1)
    high_cp = (h - close_prev).abs()
    low_cp = (l - close_prev).abs()
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return ts_mean(tr, n)


def pattern_boll(close: pd.DataFrame, n: int = 20, k: float = 2.0) -> pd.Series:
    """布林带位置 = (close - MA_n) / (k * STD_n)"""
    c = _s(close)
    ma = ts_mean(c, n)
    std = ts_std(c, n)
    return (c - ma) / (k * std.replace(0, np.nan))


# ============================================================
# 5. Cross-Section 时序回归类（轻量实现）
# ============================================================

def rolling_beta(close: pd.DataFrame, benchmark: pd.Series, n: int) -> pd.Series:
    """对 N 日 close 与 benchmark（Series）做时序回归，取斜率"""
    c = _s(close)
    aligned_b = benchmark.reindex(c.index)
    df = pd.DataFrame({'c': c, 'b': aligned_b})
    grouped = df.groupby(level='stock_code')
    cov = grouped['c'].rolling(n, min_periods=2).cov(grouped['b']).reset_index(level=0, drop=True)
    var = grouped['b'].rolling(n, min_periods=2).var().reset_index(level=0, drop=True)
    return cov / var.replace(0, np.nan)


def rolling_rsqr(close: pd.DataFrame, benchmark: pd.Series, n: int) -> pd.Series:
    """rolling beta 的 R^2"""
    c = _s(close)
    aligned_b = benchmark.reindex(c.index)
    df = pd.DataFrame({'c': c, 'b': aligned_b})
    grouped = df.groupby(level='stock_code')
    cov = grouped['c'].rolling(n, min_periods=2).cov(grouped['b']).reset_index(level=0, drop=True)
    var_c = grouped['c'].rolling(n, min_periods=2).var().reset_index(level=0, drop=True)
    var_b = grouped['b'].rolling(n, min_periods=2).var().reset_index(level=0, drop=True)
    denom = (var_c * var_b).pow(0.5).replace(0, np.nan)
    return (cov / denom) ** 2


# ============================================================
# 聚合
# ============================================================

ALPHA158_FUNCS = {
    # KBar
    'KMID': kbar_kmid,
    'KLEN': kbar_klen,
    'KMID2': kbar_kmid2,
    'KUP': kbar_kup,
    'KUP2': kbar_kup2,
    'KLOW': kbar_klow,
    'KLOW2': kbar_klow2,
    'KSFT': kbar_ksft,
    'KSFT2': kbar_ksft2,
    # Price/Volume 时序
    'HIGH_N': price_high_n,
    'LOW_N': price_low_n,
    'CLOSE_N': price_close_n,
    'OPEN_N': price_open_n,
    'VOLUME_MEAN_N': volume_mean_n,
    # Rolling
    'MA_N': rolling_mean,
    'STD_N': rolling_std,
    'SUM_N': rolling_sum,
    'SKEW_N': rolling_skew,
    'KURT_N': rolling_kurt,
    'QS_N': rolling_qs,
    # Pattern
    'ROC_N': pattern_roc,
    'ROCR_N': pattern_rocr,
    'RSV_N': pattern_rsv,
    'RSI': pattern_rsi,
    'CCI': pattern_cci,
    'ATR': pattern_atr,
    'BOLL': pattern_boll,
    # Cross-Section
    'BETA_N': rolling_beta,
    'RSQR_N': rolling_rsqr,
}


def get_alpha158_func(name: str):
    """通过名字获取 Alpha158 算子函数，未找到返回 None"""
    return ALPHA158_FUNCS.get(name)


__all__ = [
    # KBar
    'kbar_kmid', 'kbar_klen', 'kbar_kmid2',
    'kbar_kup', 'kbar_kup2', 'kbar_klow', 'kbar_klow2',
    'kbar_ksft', 'kbar_ksft2',
    # Price/Volume
    'price_high_n', 'price_low_n', 'price_close_n', 'price_open_n',
    'volume_mean_n',
    # Rolling
    'rolling_mean', 'rolling_std', 'rolling_sum',
    'rolling_skew', 'rolling_kurt', 'rolling_qs',
    # Pattern
    'pattern_roc', 'pattern_rocr', 'pattern_rsv',
    'pattern_rsi', 'pattern_cci', 'pattern_atr', 'pattern_boll',
    # Cross-Section
    'rolling_beta', 'rolling_rsqr',
    # Registry
    'ALPHA158_FUNCS', 'get_alpha158_func',
]
