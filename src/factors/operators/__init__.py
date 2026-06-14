"""
算子库（Operator Library）
==========================

飞书"## 因子"章节要求：
> 基于 alpha101（参考 WorldQuant_101_Alphas_完整解析.docx）
> 基于 alpha191（参考 国泰君安Alpha191因子公式详解.docx）
> 基于 Qlib Alpha158（参考 Qlib_Alpha158_因子详解手册.docx）

算子可独立引用，避免策略开发时重复写逻辑转换。

子模块：
- ts: 时序算子（ts_mean, ts_std, ts_rank, ts_delta, ts_corr, ...）
- cross: 横截面算子（rank, scale, neutralize, ...）
- math: 数学算子（log, sign, signed_power, decay_linear, ...）
- alpha101: WorldQuant 101 因子实现
- alpha191: 国泰君安 191 因子实现
"""
from .ts import (
    ts_mean, ts_std, ts_sum, ts_max, ts_min,
    ts_rank, ts_delta, ts_delay, ts_corr, ts_cov,
    ts_decay_linear, ts_decay_exp, ts_argmax, ts_argmin,
    ts_skew, ts_kurt, ts_median, ts_quantile, ts_ema,
)
from .cross import (
    rank, scale, normalize, neutralize,
    mad, zscore, demean,
)
from .math_ops import (
    log, sign, signed_power, abs_, max_, min_, where,
    decay_linear, decay_exp,
)
from .alpha101 import ALPHA101_FUNCS
from .alpha191 import ALPHA191_FUNCS

__all__ = [
    # 时序算子
    'ts_mean', 'ts_std', 'ts_sum', 'ts_max', 'ts_min',
    'ts_rank', 'ts_delta', 'ts_delay', 'ts_corr', 'ts_cov',
    'ts_decay_linear', 'ts_decay_exp', 'ts_argmax', 'ts_argmin',
    'ts_skew', 'ts_kurt', 'ts_median', 'ts_quantile', 'ts_ema',
    # 横截面算子
    'rank', 'scale', 'normalize', 'neutralize',
    'mad', 'zscore', 'demean',
    # 数学算子
    'log', 'sign', 'signed_power', 'abs_', 'max_', 'min_', 'where',
    'decay_linear', 'decay_exp',
    # 因子实现
    'ALPHA101_FUNCS', 'ALPHA191_FUNCS',
]
