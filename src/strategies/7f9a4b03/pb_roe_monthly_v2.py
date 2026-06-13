"""
pb_roe_monthly_v2 - PB+ROE 月度轮动策略（quantlab SignalStrategy 版）
====================================================================

原版 BaseStrategy (on_bar)：``src/strategies/7f9a4b03/pb_roe_monthly_v1.py``
- 月末清仓所有持仓
- 月初全市场按 PB 升序 + ROE 降序综合排名取前 10%
- 持仓上限 100 只
- 不带止损/止盈

v2 简化（遵循 quantlab/signals/base.py 契约）
------------------------------------------
- 策略层只输出"双优"（signal=1）或"不持有"（signal=0）
- 月末清仓 / 月初建仓 → 委托给 PortfolioConstructor 的 rebalance="M" 逻辑
- 全市场综合排名 + TopN 截断 → 委托给 PortfolioConstructor
- v2 单标的层面用"双优度 score" + 阈值近似表达"排名靠前"

数据约定（DataAdapter 注入到 ctx.data[sym]）
-----------------------------------------
- open / high / low / close / volume
- pre_close / amount / market_cap
- pb（市净率）/ roe（净资产收益率）
"""

from __future__ import annotations

import pandas as pd

from src.quantlab.signals.base import SignalStrategy


class PbRoeMonthlyV2(SignalStrategy):
    """
    PB+ROE 月度轮动策略 V2（quantlab SignalStrategy）

    单标的信号规则（双优度 + 阈值近似）：
        1. 计算双优度 score = -PB_zscore + ROE_zscore（滚动 ``zscore_window`` 日标准化）
           - PB 越低 → 得分越高（取负号）
           - ROE 越高 → 得分越高
        2. score >= ``min_score`` 时为候选
        3. 流通市值 ∈ [``min_circ_mv``, ``max_circ_mv``]（亿）

    真正的"全市场排名取前 N%"在 PortfolioConstructor 中完成。

    signal ∈ {0, 1}：1=双优可买，0=不持有。
    """

    name = "pb_roe_monthly_v2"
    description = "PB+ROE 月度轮动策略 V2 (quantlab) - 双优度+小市值，月度调仓"

    def __init__(
        self,
        top_pct: float = 10.0,
        max_positions: int = 100,
        pb_rank_asc: bool = True,
        roe_rank_asc: bool = False,
        zscore_window: int = 252,
        min_score: float = 0.0,
        max_circ_mv: float = 500.0,
        min_circ_mv: float = 0.0,
    ):
        # 参数全部为基本类型，可 JSON 序列化
        self.top_pct = float(top_pct)
        self.max_positions = int(max_positions)
        self.pb_rank_asc = bool(pb_rank_asc)
        self.roe_rank_asc = bool(roe_rank_asc)
        self.zscore_window = int(zscore_window)
        self.min_score = float(min_score)
        self.max_circ_mv = float(max_circ_mv)
        self.min_circ_mv = float(min_circ_mv)

        # 入参合理性校验
        if not (0 < self.top_pct <= 100):
            raise ValueError(f"top_pct must be in (0, 100], got {top_pct}")
        if self.max_positions < 1:
            raise ValueError(f"max_positions must be >= 1, got {max_positions}")
        if self.zscore_window < 20:
            raise ValueError(f"zscore_window must be >= 20, got {zscore_window}")
        if not (0 <= self.min_circ_mv < self.max_circ_mv):
            raise ValueError(
                f"require 0 <= min_circ_mv < max_circ_mv, "
                f"got min={min_circ_mv}, max={max_circ_mv}"
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
        window = self.zscore_window
        min_periods = max(20, window // 4)

        # ---- 1. PB 滚动 z-score ----
        if "pb" in df.columns:
            pb = df["pb"]
            pb_mean = pb.rolling(window, min_periods=min_periods).mean()
            pb_std = pb.rolling(window, min_periods=min_periods).std()
            pb_z = (pb - pb_mean) / pb_std.replace(0, pd.NA)
        else:
            pb_z = pd.Series(float("nan"), index=df.index)

        # ---- 2. ROE 滚动 z-score ----
        if "roe" in df.columns:
            roe = df["roe"]
            roe_mean = roe.rolling(window, min_periods=min_periods).mean()
            roe_std = roe.rolling(window, min_periods=min_periods).std()
            roe_z = (roe - roe_mean) / roe_std.replace(0, pd.NA)
        else:
            roe_z = pd.Series(float("nan"), index=df.index)

        # ---- 3. 双优度 ----
        # PB 越低越好（取负号），ROE 越高越好
        # 可通过 pb_rank_asc / roe_rank_asc 翻转方向
        pb_dir = 1.0 if self.pb_rank_asc else -1.0
        roe_dir = 1.0 if not self.roe_rank_asc else -1.0
        score = -pb_dir * pb_z + roe_dir * roe_z
        score_ok = (score >= self.min_score).fillna(False)

        # ---- 4. 流通市值区间 ----
        if "market_cap" in df.columns:
            mv_yi = df["market_cap"] / 1e8
            mv_ok = ((mv_yi > self.min_circ_mv) & (mv_yi < self.max_circ_mv)).fillna(False)
        else:
            mv_ok = pd.Series(False, index=df.index)

        qualified = (score_ok & mv_ok)
        return qualified.astype("int8")


# ---------------------------------------------------------------------- #
# 工厂方法
# ---------------------------------------------------------------------- #
def make_pb_roe_monthly_v2(
    top_pct: float = 10.0,
    max_positions: int = 100,
    pb_rank_asc: bool = True,
    roe_rank_asc: bool = False,
    zscore_window: int = 252,
    min_score: float = 0.0,
    max_circ_mv: float = 500.0,
    min_circ_mv: float = 0.0,
) -> PbRoeMonthlyV2:
    """显式工厂。"""
    return PbRoeMonthlyV2(
        top_pct=top_pct,
        max_positions=max_positions,
        pb_rank_asc=pb_rank_asc,
        roe_rank_asc=roe_rank_asc,
        zscore_window=zscore_window,
        min_score=min_score,
        max_circ_mv=max_circ_mv,
        min_circ_mv=min_circ_mv,
    )


# ---------------------------------------------------------------------- #
# 典型参数网格
# ---------------------------------------------------------------------- #
PB_ROE_MONTHLY_PARAM_SPACE: dict = {
    "top_pct":         [5.0, 10.0, 20.0],
    "max_positions":   [20, 50, 100, 200],
    "pb_rank_asc":     [True],
    "roe_rank_asc":    [False],
    "zscore_window":   [120, 252, 504],
    "min_score":       [-1.0, 0.0, 0.5, 1.0],
    "max_circ_mv":     [100.0, 200.0, 500.0],
    "min_circ_mv":     [0.0],
}
