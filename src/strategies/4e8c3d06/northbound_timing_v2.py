"""
northbound_timing_v2 - 北向资金择时策略（quantlab SignalStrategy 版）
====================================================================

原版 BaseStrategy (on_bar)：``src/strategies/4e8c3d06/northbound_timing_v1.py``
- 每日拉取北向资金净流入 → 滚动窗口 Z-Score
- Z > upper → 满仓（买 000300.SH），Z < lower → 空仓
- 引擎级出场关闭（止损/止盈/ATR/超时都关）
- execution_price = next_open（T+1 开盘执行）

v2 简化（遵循 quantlab/signals/base.py 契约）
------------------------------------------
- v1 跟踪单标的 ETF（沪深 300）；v2 简化成"按北向净流入过滤全市场股票"
- 月度调仓 / 行业暴露 → 委托给 PortfolioConstructor + RiskManager
- Z-Score 阈值择时 → 退化为单阈值净流入过滤
- Z-Score 满仓/空仓 → 用 {0, 1} 表达多空方向，仓位由 Portfolio 决定
- 次日开盘执行 → 由 BarEngine fill 机制处理（T+1 天然滞后一档）
- 引擎级出场 → 一律关闭，由 RiskManager 接管

数据约定（DataAdapter 注入到 ctx.data[sym]）
-----------------------------------------
- open / high / low / close / volume
- pre_close / amount / market_cap
- **northbound_net_inflow**（元）：单日北向资金对该股的净流入
"""

from __future__ import annotations

import pandas as pd

from src.quantlab.signals.base import SignalStrategy


class NorthboundTimingV2(SignalStrategy):
    """
    北向资金择时策略 V2（quantlab SignalStrategy）

    单标的信号规则：
        1. ``northbound_net_inflow`` > ``inflow_threshold``
        2. signal ∈ {0, 1}：1=满足条件想买，0=不持有
        3. 月度调仓（具体 rebalance 逻辑交 PortfolioConstructor 决定）
    """

    name = "northbound_timing_v2"
    description = "北向资金择时策略 V2 (quantlab) - 北向净流入阈值选股"

    def __init__(
        self,
        inflow_threshold: float = 0.0,
    ):
        # 参数全部为基本类型，可 JSON 序列化
        self.inflow_threshold = float(inflow_threshold)

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

        if "northbound_net_inflow" not in df.columns:
            return pd.Series(0, index=df.index, dtype="int8")

        inflow = df["northbound_net_inflow"]
        ok = (inflow > self.inflow_threshold).fillna(False)
        return ok.astype("int8")


# ---------------------------------------------------------------------- #
# 工厂方法
# ---------------------------------------------------------------------- #
def make_northbound_timing_v2(
    inflow_threshold: float = 0.0,
) -> NorthboundTimingV2:
    """显式工厂。"""
    return NorthboundTimingV2(inflow_threshold=inflow_threshold)


# ---------------------------------------------------------------------- #
# 典型参数网格
# ---------------------------------------------------------------------- #
NORTHBOUND_TIMING_PARAM_SPACE: dict = {
    # 元；> 0 视为当日北向净流入为正才持仓
    "inflow_threshold": [0.0, 1_000_000.0, 5_000_000.0, 10_000_000.0],
}
