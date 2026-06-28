"""
breakout_pullback_v2 - 突破回踩策略（quantlab SignalStrategy 版）
===============================================================

原版 BaseStrategy (on_bar)：``src/strategies/9b1f7a05/breakout_pullback_v1.py``
- 识别震荡区间（过去 N 天 high_max / low_min）
- 检测向上突破（close > high_max * (1 + breakout_threshold)）
- 检测回踩（曾向上突破 + 当前未突破 + close 在 high_max 上下 pullback_threshold 内）
- 跌破 low_min → 箱体下沿止损
- 引擎级出场（止损/ATR/超时）由 ExitChecker 管理

v2 简化（遵循 quantlab/signals/base.py 契约）
------------------------------------------
- 区间识别 → 用 quantlab.factors.ma 计算均线 + 自定义 rolling high
- 突破 + 回踩 → signal 表达式（v1 是分步查 dict）
- 箱体下沿止损 → 移除（统一由 RiskManager 接管）
- 引擎级出场 → 移除（统一由 RiskManager 接管）
- max_positions / position_size 仓位约束 → 委托给 PortfolioConstructor

数据约定（DataAdapter 注入到 ctx.data[sym]）
-----------------------------------------
- open / high / low / close / volume
- pre_close / amount / market_cap
"""

from __future__ import annotations

import pandas as pd

from src.quantlab.factors.ma import ma
from src.quantlab.signals.base import SignalStrategy


class BreakoutPullbackV2(SignalStrategy):
    """
    突破回踩策略 V2（quantlab SignalStrategy）

    单标的信号规则（突破 + 回踩）：
        1. 突破：close > 过去 ``breakout_window`` 天最高价（donchian 高点，shift(1) 防未来函数）
        2. 回踩：曾向上突破 + 当前未突破 + low 跌破 ma 但 close 站上 ma
        3. signal ∈ {0, 1}：1=满足条件想做多，0=不持有
    """

    name = "breakout_pullback"
    description = "突破回踩策略 V2 (quantlab) - 突破后回踩均线做多"

    def __init__(
        self,
        breakout_window: int = 20,
        ma_period: int = 20,
        breakout_threshold: float = 0.01,
    ):
        # 参数全部为基本类型，可 JSON 序列化
        self.breakout_window = int(breakout_window)
        self.ma_period = int(ma_period)
        self.breakout_threshold = float(breakout_threshold)

        # 入参合理性校验
        if self.breakout_window < 2:
            raise ValueError(f"breakout_window must be >= 2, got {breakout_window}")
        if self.ma_period < 2:
            raise ValueError(f"ma_period must be >= 2, got {ma_period}")
        if not (0 < self.breakout_threshold < 0.5):
            raise ValueError(
                f"require 0 < breakout_threshold < 0.5, got {breakout_threshold}"
            )

    # ------------------------------------------------------------------ #
    # SignalStrategy 接口
    # ------------------------------------------------------------------ #
    def signal(
        self,
        ctx,
    ) -> pd.DataFrame:
        out: dict[str, pd.Series] = {}
        for sym in ctx.data:
            out[sym] = self._signal_one(ctx, sym)
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
        df = ctx.data[sym]
        if len(df) < max(self.breakout_window, self.ma_period) + 1:
            return pd.Series(0, index=df.index, dtype="int8")

        # ---- 1. 突破识别（donchian 高点 + shift(1) 防未来函数）----
        high_max = (
            df["high"]
            .rolling(self.breakout_window, min_periods=1)
            .max()
            .shift(1)
        )
        breakout = (df["close"] > high_max * (1.0 + self.breakout_threshold)).fillna(False)

        # ---- 2. 曾突破（lookback = breakout_window）----
        had_breakout = (
            breakout.rolling(self.breakout_window, min_periods=1)
            .max()
            .fillna(0)
            .astype(bool)
        )

        # ---- 3. 当前未突破 ----
        not_breakout = (~breakout).fillna(False)

        # ---- 4. 回踩：low 跌破 ma 但 close 站上 ma ----
        # 关键：ma 也要 shift(1)，避免当日实时价格影响"昨日均线"的判断
        ma_val = ma(ctx, sym, self.ma_period)
        pullback = ((df["low"] < ma_val) & (df["close"] > ma_val)).fillna(False)

        qualified = (had_breakout & not_breakout & pullback).fillna(False)
        return qualified.astype("int8")


# ---------------------------------------------------------------------- #
# 工厂方法
# ---------------------------------------------------------------------- #
def make_breakout_pullback_v2(
    breakout_window: int = 20,
    ma_period: int = 20,
    breakout_threshold: float = 0.01,
) -> BreakoutPullbackV2:
    """显式工厂。"""
    return BreakoutPullbackV2(
        breakout_window=breakout_window,
        ma_period=ma_period,
        breakout_threshold=breakout_threshold,
    )


# ---------------------------------------------------------------------- #
# 典型参数网格
# ---------------------------------------------------------------------- #
BREAKOUT_PULLBACK_PARAM_SPACE: dict = {
    "breakout_window":    [10, 20, 30, 60],
    "ma_period":          [5, 10, 20, 30, 60],
    "breakout_threshold": [0.005, 0.01, 0.02, 0.05],
}
