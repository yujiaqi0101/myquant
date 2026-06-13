"""
small_cap_v2 - 小市值策略（quantlab SignalStrategy 版）
====================================================

原版 BaseStrategy (on_bar)：``src/strategies/3a7b2c01/small_cap_v1.py``
- 月度调仓：六步选股（市值/流动性/波动率/动量/行业分散）
- 异动止盈 + 个股止损
- 净值风控 + 市场趋势过滤

v2 简化（遵循 quantlab/signals/base.py 契约）
------------------------------------------
- 策略层只输出"想买什么"（signal=1）或"不持有"（signal=0）
- 止盈止损 / 净值风控 / 市场趋势 → 委托给 RiskManager（Phase 3）
- 月度调仓 → 委托给 PortfolioConstructor 的 rebalance 逻辑
- 行业分散 → 自定义 PortfolioConstructor（Phase 2）

数据约定（DataAdapter 注入到 ctx.data[sym]）
-----------------------------------------
- open / high / low / close / volume
- pre_close / amount / market_cap
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from src.quantlab.signals.base import SignalStrategy


# A 股有效板块前缀（沪市主板 60 / 深市主板 00 / 创业板 30 / 科创板 68）
_VALID_BOARD_PREFIXES = ("60", "00", "30", "68")


class SmallCapV2(SignalStrategy):
    """
    小市值策略 V2（quantlab SignalStrategy）

    单标的信号规则（六步选股 + 软过滤）：
        1. 主板/创业板/科创板有效股票
        2. 流通市值 < ``max_market_cap``（亿）
        3. 日均成交额 > ``min_amount``（万元）
        4. N 日波动率 < ``max_vol``
        5. N 日涨幅 >= ``min_momentum``
        6. 上市天数 >= ``min_listed_days``（如有 list_date 列）

    TopN 截断由 PortfolioConstructor 决定，本类只输出"过没过"。

    signal ∈ {0, 1}：1=满足选股条件想买，0=不持有。
    """

    name = "small_cap_v2"
    description = "小市值策略 V2 (quantlab) - 月度调仓等权 TopN"

    def __init__(
        self,
        top_n: int = 30,
        min_market_cap: float = 15.0,
        max_market_cap: float = 200.0,
        min_amount: float = 500.0,
        max_vol: float = 0.05,
        min_momentum: float = -0.10,
        min_listed_days: int = 60,
        vol_period: int = 20,
    ):
        # 参数全部为基本类型（int / float / bool / str），可 JSON 序列化
        self.top_n = int(top_n)
        self.min_market_cap = float(min_market_cap)
        self.max_market_cap = float(max_market_cap)
        self.min_amount = float(min_amount)
        self.max_vol = float(max_vol)
        self.min_momentum = float(min_momentum)
        self.min_listed_days = int(min_listed_days)
        self.vol_period = int(vol_period)

        # 入参合理性校验（启动即失败，不要在 .signal() 跑一半才崩）
        if self.top_n < 1:
            raise ValueError(f"top_n must be >= 1, got {top_n}")
        if not (0 < self.min_market_cap < self.max_market_cap):
            raise ValueError(
                f"require 0 < min_market_cap < max_market_cap, "
                f"got min={min_market_cap}, max={max_market_cap}"
            )
        if self.min_amount < 0:
            raise ValueError(f"min_amount must be >= 0, got {min_amount}")
        if not (0 < self.max_vol < 1):
            raise ValueError(f"require 0 < max_vol < 1, got {max_vol}")
        if self.vol_period < 2:
            raise ValueError(f"vol_period must be >= 2, got {vol_period}")
        if self.min_listed_days < 0:
            raise ValueError(f"min_listed_days must be >= 0, got {min_listed_days}")

    # ------------------------------------------------------------------ #
    # SignalStrategy 接口
    # ------------------------------------------------------------------ #
    def signal(
        self,
        ctx,
    ) -> pd.DataFrame:
        # 多标的遍历，严格保持 ctx.data.keys() 顺序
        out: dict[str, pd.Series] = {}
        for sym in ctx.data:
            out[sym] = self._signal_one(ctx, sym)

        # 完整 DataFrame(date × symbol)，整型（int8）节省内存
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

        if len(df) < self.vol_period + 1:
            return pd.Series(0, index=df.index, dtype="int8")

        # ---- 1. 有效板块 ----
        prefix = str(sym).split(".")[0][:2]
        if prefix not in _VALID_BOARD_PREFIXES:
            return pd.Series(0, index=df.index, dtype="int8")

        # ---- 2. 流通市值 < max ----
        mc = df["market_cap"] if "market_cap" in df.columns else pd.Series(float("nan"), index=df.index)
        mc_ok = (mc > 0) & (mc < self.max_market_cap * 1e8)

        # ---- 3. 成交额 > min ----
        amt = df["amount"] if "amount" in df.columns else pd.Series(float("nan"), index=df.index)
        amt_ok = amt > self.min_amount * 1e4

        # ---- 4. N 日波动率 < max ----
        ret = df["close"].pct_change()
        vol = ret.rolling(self.vol_period).std()
        vol_ok = vol < self.max_vol

        # ---- 5. N 日涨幅 >= min ----
        mom = df["close"].pct_change(self.vol_period)
        mom_ok = mom >= self.min_momentum

        # ---- 6. 上市天数（可选，缺列跳过）----
        if "list_date" in df.columns:
            try:
                first_valid = df["close"].first_valid_index()
                if first_valid is not None:
                    n_bars = len(df.loc[first_valid:])
                    if n_bars < self.min_listed_days:
                        return pd.Series(0, index=df.index, dtype="int8")
            except Exception:
                pass

        # ---- 综合选股条件：全 AND ----
        qualified = (mc_ok & amt_ok & vol_ok & mom_ok).fillna(False)
        return qualified.astype("int8")


# ---------------------------------------------------------------------- #
# 工厂方法：方便 ExperimentRecord / CLI 用 kwargs 构造
# ---------------------------------------------------------------------- #
def make_small_cap_v2(
    top_n: int = 30,
    min_market_cap: float = 15.0,
    max_market_cap: float = 200.0,
    min_amount: float = 500.0,
    max_vol: float = 0.05,
    min_momentum: float = -0.10,
    min_listed_days: int = 60,
    vol_period: int = 20,
) -> SmallCapV2:
    """显式工厂：避免某些调用方依赖默认参数顺序。"""
    return SmallCapV2(
        top_n=top_n,
        min_market_cap=min_market_cap,
        max_market_cap=max_market_cap,
        min_amount=min_amount,
        max_vol=max_vol,
        min_momentum=min_momentum,
        min_listed_days=min_listed_days,
        vol_period=vol_period,
    )


# ---------------------------------------------------------------------- #
# 典型参数网格（给 Optimizer / ParallelOptimizer 用）
# ---------------------------------------------------------------------- #
SMALL_CAP_PARAM_SPACE: dict = {
    # 持仓数：等权 TopN
    "top_n":              [10, 20, 30, 50],
    # 市值范围（亿）
    "min_market_cap":     [10.0, 15.0, 20.0],
    "max_market_cap":     [100.0, 200.0, 300.0],
    # 流动性下限（万元）
    "min_amount":         [200.0, 500.0, 1000.0],
    # 波动率上限
    "max_vol":            [0.03, 0.05, 0.08],
    # 动量下限
    "min_momentum":       [-0.20, -0.10, -0.05],
    # 上市天数
    "min_listed_days":    [60, 120, 250],
    # 波动 / 动量周期
    "vol_period":         [10, 20, 30],
}
