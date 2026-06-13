"""
RSI 策略 —— 超买超卖反转 + 可选趋势过滤

信号规则（默认 mean_reversion 模式）:
  RSI < oversold       → 1   超卖，做多
  RSI > overbought     → 0   超买，止盈/不进场
  其他                  → 0   中性区间

可选 trend_filter:
  启用后只允许在 close > MA(trend_period) 时做多
  用于过滤"下跌趋势里 RSI 假超卖"陷阱

取值 ∈ {-1, 0, 1}:
  1   做多
  0   空仓
  -1  暂不输出（接口留位）

遵循 quantlab/signals/base.py 的契约:
  - 继承 SignalStrategy
  - __init__ 参数可 JSON 序列化
  - signal(ctx) 返回 DataFrame(date × symbol)
  - 不在 .signal() 里 print / 起线程 / 改全局
  - 走 quantlab.factors.rsi.rsi() 走 cache，不手写 rolling
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from quantlab.factors.ma import ma
from quantlab.factors.rsi import rsi
from quantlab.signals.base import SignalStrategy


class RSIStrategy(SignalStrategy):
    """
    Parameters
    ----------
    period : int
        RSI 计算窗口，默认 14
    oversold : float
        超卖阈值，RSI < oversold 取 1，默认 30
    overbought : float
        超买阈值，RSI > overbought 取 0，默认 70
    use_trend_filter : bool
        是否启用 MA 趋势过滤，默认 False
    trend_period : int
        趋势 MA 周期，仅在 use_trend_filter=True 时生效，默认 200
    """

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        use_trend_filter: bool = False,
        trend_period: int = 200,
    ):

        # 参数全部为基本类型，可 JSON 序列化
        # 不持有任何不可序列化对象（model / conn / file）
        self.period = int(period)
        self.oversold = float(oversold)
        self.overbought = float(overbought)
        self.use_trend_filter = bool(use_trend_filter)
        self.trend_period = int(trend_period)

        # 入参合理性校验（启动即失败，不要在 .signal() 跑一半才崩）
        if not (0 < self.oversold < self.overbought < 100):
            raise ValueError(
                f"require 0 < oversold < overbought < 100, "
                f"got oversold={oversold}, overbought={overbought}"
            )
        if self.period < 2:
            raise ValueError(
                f"period must be >= 2, got {period}"
            )
        if self.use_trend_filter and self.trend_period < 2:
            raise ValueError(
                f"trend_period must be >= 2, got {trend_period}"
            )

    # ------------------------------------------------------------------ #
    # SignalStrategy 接口
    # ------------------------------------------------------------------ #
    def signal(
        self,
        ctx,
    ) -> pd.DataFrame:

        # 多标的遍历
        # 严格保持 ctx.data.keys() 顺序
        out: dict[str, pd.Series] = {}

        for sym in ctx.data:
            out[sym] = self._signal_one(ctx, sym)

        # 完整 DataFrame(date × symbol)
        # 取值 ∈ {0, 1}，整型
        df = pd.DataFrame(out).astype("int8")

        return df

    # ------------------------------------------------------------------ #
    # 单标逻辑（私有）
    # ------------------------------------------------------------------ #
    def _signal_one(
        self,
        ctx,
        sym: str,
    ) -> pd.Series:

        # 1) 走 quantlab.factors.rsi 走 cache
        rsi_series = rsi(
            ctx,
            sym,
            self.period,
        )

        # 2) 基础超买超卖信号
        #    NaN 比较返回 False，自动变成 0 —— 符合"前 N 根不做决策"语义
        long_signal = (rsi_series < self.oversold).astype("int8")
        exit_signal = (rsi_series > self.overbought).astype("int8")

        # 3) 趋势过滤（可选）
        #    仅在多头信号上叠加：
        #       - close > MA(N)        → 允许做多
        #       - close <= MA(N)       → 不做多（即便 RSI 超卖）
        if self.use_trend_filter:
            trend_ma = ma(
                ctx,
                sym,
                self.trend_period,
            )
            close = ctx.data[sym]["close"]
            above_trend = (close > trend_ma).astype("int8")
            long_signal = (long_signal & above_trend).astype("int8")

        # 4) 出场不直接落到 signal 上
        #    signal ∈ {0, 1}：1=目标持仓，0=目标空仓
        #    超买时清零，让 Engine 触发平仓
        signal = long_signal.copy()
        signal[exit_signal == 1] = 0

        return signal


# ---------------------------------------------------------------------- #
# 工厂方法：方便 ExperimentRecord 用 kwargs 构造
# ---------------------------------------------------------------------- #
def make_rsi(
    period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
    use_trend_filter: bool = False,
    trend_period: int = 200,
) -> RSIStrategy:
    """
    显式工厂
    避免某些调用方依赖默认参数顺序
    """
    return RSIStrategy(
        period=period,
        oversold=oversold,
        overbought=overbought,
        use_trend_filter=use_trend_filter,
        trend_period=trend_period,
    )


# ---------------------------------------------------------------------- #
# 典型参数网格（给 Optimizer / ParallelOptimizer 用）
# ---------------------------------------------------------------------- #
RSI_PARAM_SPACE: dict = {
    # 周期：经典 14 附近 ± 步长
    "period":          [9, 14, 21],
    # 阈值：30/70 是 Wilder 原版
    "oversold":        [20.0, 25.0, 30.0],
    "overbought":      [70.0, 75.0, 80.0],
    # 趋势过滤：开发期先关，验证完再开
    "use_trend_filter": [False],
    "trend_period":    [200],
}

# 含趋势过滤的网格（验证过 mean_reversion 主策略后开启）
RSI_PARAM_SPACE_TREND: dict = {
    "period":          [14, 21],
    "oversold":        [25.0, 30.0],
    "overbought":      [70.0, 75.0],
    "use_trend_filter": [True],
    "trend_period":    [100, 200],
}
