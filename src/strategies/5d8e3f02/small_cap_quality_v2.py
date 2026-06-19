"""
small_cap_quality_v2 - 小盘股质量策略（quantlab SignalStrategy 版）
==================================================================

原版 BaseStrategy (on_bar)：``src/strategies/5d8e3f02/small_cap_quality_v1.py``
- 月度调仓：质量因子（ROE / PB / 营收增长）+ 流通市值排序取前 N
- 月末清仓、月初重建
- 每日止损（-8%）/ 止盈（+25%）

v2 简化（遵循 quantlab/signals/base.py 契约）
------------------------------------------
- 策略层只输出"基本面过关+小市值"（signal=1）或"不持有"（signal=0）
- 月末清仓 → 委托给 PortfolioConstructor 的 rebalance="M" 逻辑
- 止损/止盈 → 委托给 RiskManager（Phase 3）

数据约定（DataAdapter 注入到 ctx.data[sym]）
-----------------------------------------
- open / high / low / close / volume
- pre_close / amount / market_cap
- pb（市净率）/ roe（净资产收益率）/ revenue_growth（营收同比，可选）
"""

from __future__ import annotations

import pandas as pd

from src.quantlab.signals.base import SignalStrategy


class SmallCapQualityV2(SignalStrategy):
    """
    小盘股质量策略 V2（quantlab SignalStrategy）

    单标的信号规则（多条件 AND）：
        1. ROE > ``roe_threshold``
        2. 0 < PB < ``pb_threshold``
        3. 营收增长 > ``revenue_growth_threshold``（可选，缺列视为 True）
        4. 流通市值 ∈ [``min_circ_mv``, ``max_circ_mv``]（亿）
        5. 上市天数 >= ``min_listed_days``（如有 list_date 列）

    TopN 截断由 PortfolioConstructor 决定。

    signal ∈ {0, 1}：1=基本面过关+小市值，0=不持有。
    """

    name = "small_cap_quality_v2"
    description = "小盘股质量策略 V2 (quantlab) - 质量因子+小市值，月度调仓"

    def __init__(
        self,
        n_positions: int = 20,
        roe_threshold: float = 0.05,
        pb_threshold: float = 3.0,
        revenue_growth_threshold: float = 0.0,
        use_revenue_growth: bool = True,
        max_circ_mv: float = 500.0,
        min_circ_mv: float = 0.0,
        min_listed_days: int = 60,
    ):
        # 参数全部为基本类型，可 JSON 序列化
        self.n_positions = int(n_positions)
        self.roe_threshold = float(roe_threshold)
        self.pb_threshold = float(pb_threshold)
        self.revenue_growth_threshold = float(revenue_growth_threshold)
        self.use_revenue_growth = bool(use_revenue_growth)
        self.max_circ_mv = float(max_circ_mv)
        self.min_circ_mv = float(min_circ_mv)
        self.min_listed_days = int(min_listed_days)

        # 入参合理性校验
        if self.n_positions < 1:
            raise ValueError(f"n_positions must be >= 1, got {n_positions}")
        if not (0 < self.pb_threshold):
            raise ValueError(f"pb_threshold must be > 0, got {pb_threshold}")
        if not (0 <= self.min_circ_mv < self.max_circ_mv):
            raise ValueError(
                f"require 0 <= min_circ_mv < max_circ_mv, "
                f"got min={min_circ_mv}, max={max_circ_mv}"
            )
        if self.min_listed_days < 0:
            raise ValueError(f"min_listed_days must be >= 0, got {min_listed_days}")

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
        df = pd.DataFrame(out).fillna(0).astype("int8")
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

        # ---- 0. 上市天数（可选，缺列跳过）----
        if "list_date" in df.columns:
            try:
                first_valid = df["close"].first_valid_index()
                if first_valid is not None:
                    n_bars = len(df.loc[first_valid:])
                    if n_bars < self.min_listed_days:
                        return pd.Series(0, index=df.index, dtype="int8")
            except Exception:
                pass

        # ---- 1. ROE > threshold（全空时降级为 True）----
        if "roe" in df.columns and df["roe"].notna().any():
            roe = df["roe"]
            roe_ok = (roe > self.roe_threshold).fillna(False)
        else:
            roe_ok = pd.Series(True, index=df.index)

        # ---- 2. 0 < PB < threshold（全空时降级为 True）----
        if "pb" in df.columns and df["pb"].notna().any():
            pb = df["pb"]
            pb_ok = ((pb > 0) & (pb < self.pb_threshold)).fillna(False)
        else:
            pb_ok = pd.Series(True, index=df.index)

        # ---- 3. 营收增长 > threshold（可选）----
        if self.use_revenue_growth and "revenue_growth" in df.columns:
            rg = df["revenue_growth"]
            rg_ok = (rg > self.revenue_growth_threshold).fillna(False)
        else:
            rg_ok = pd.Series(True, index=df.index)

        # ---- 4. 流通市值区间（亿）（全空时降级为 True）----
        if "market_cap" in df.columns and df["market_cap"].notna().any():
            mc = df["market_cap"]
            mv_yi = mc / 1e8
            mv_ok = ((mv_yi > self.min_circ_mv) & (mv_yi < self.max_circ_mv)).fillna(False)
        else:
            mv_ok = pd.Series(True, index=df.index)

        # ---- 综合：全 AND ----
        qualified = (roe_ok & pb_ok & rg_ok & mv_ok)
        return qualified.astype("int8")


# ---------------------------------------------------------------------- #
# 工厂方法
# ---------------------------------------------------------------------- #
def make_small_cap_quality_v2(
    n_positions: int = 20,
    roe_threshold: float = 0.05,
    pb_threshold: float = 3.0,
    revenue_growth_threshold: float = 0.0,
    use_revenue_growth: bool = True,
    max_circ_mv: float = 500.0,
    min_circ_mv: float = 0.0,
    min_listed_days: int = 60,
) -> SmallCapQualityV2:
    """显式工厂。"""
    return SmallCapQualityV2(
        n_positions=n_positions,
        roe_threshold=roe_threshold,
        pb_threshold=pb_threshold,
        revenue_growth_threshold=revenue_growth_threshold,
        use_revenue_growth=use_revenue_growth,
        max_circ_mv=max_circ_mv,
        min_circ_mv=min_circ_mv,
        min_listed_days=min_listed_days,
    )


# ---------------------------------------------------------------------- #
# 典型参数网格
# ---------------------------------------------------------------------- #
SMALL_CAP_QUALITY_PARAM_SPACE: dict = {
    "n_positions":                [10, 20, 30, 50],
    "roe_threshold":              [0.0, 0.05, 0.10, 0.15],
    "pb_threshold":               [1.5, 2.0, 3.0, 5.0],
    "revenue_growth_threshold":   [-0.10, 0.0, 0.10, 0.20],
    "use_revenue_growth":         [True, False],
    "max_circ_mv":                [100.0, 200.0, 500.0],
    "min_circ_mv":                [0.0],
    "min_listed_days":            [60, 120, 250],
}
