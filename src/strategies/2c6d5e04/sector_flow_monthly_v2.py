"""
sector_flow_monthly_v2 - 申万行业资金流向策略（quantlab SignalStrategy 版）
=========================================================================

原版 BaseStrategy (on_bar)：``src/strategies/2c6d5e04/sector_flow_monthly_v1.py``
- 每日拉取申万一级行业资金流入排名
- Top N 行业 → 在该行业内选 净流入 Top + 涨幅 Top
- 同行业重叠 1.5 份，否则 1 份
- 月度调仓（T 日计算排名，T+1 日开盘调仓）
- 引擎级出场（止损/止盈/动态止盈/超时）

v2 简化（遵循 quantlab/signals/base.py 契约）
------------------------------------------
- 行业排名 TopN → 选行业所有成员
- 月度调仓 → 委托给 PortfolioConstructor 的 rebalance 逻辑
- 行业暴露约束 → 委托给 RiskManager（行业中性 / 行业上限）
- 引擎级出场 → 统一由 RiskManager 接管
- 同行业 1.5 份加仓 → 委托给 PortfolioConstructor 的权重逻辑
- 行业成分股查询 + 净流入 / 涨幅 Top → 退化为单一阈值
  （DataAdapter 已把"行业资金流入排名"预计算注入到 ctx.data[sym]）

数据约定（DataAdapter 注入到 ctx.data[sym]）
-----------------------------------------
- open / high / low / close / volume
- pre_close / amount / market_cap
- **industry_inflow_rank**（1=top）：当日该股所属行业在申万一级中的资金流入排名
"""

from __future__ import annotations

import pandas as pd

from src.quantlab.signals.base import SignalStrategy


class SectorFlowMonthlyV2(SignalStrategy):
    """
    申万行业资金流向策略 V2（quantlab SignalStrategy）

    单标的信号规则：
        1. ``industry_inflow_rank`` ≤ ``top_n_industries``（行业资金流入排名 TopN）
        2. signal ∈ {0, 1}：1=属于 TopN 行业想买，0=不持有
        3. 行业暴露由 RiskManager 约束
        4. 月度调仓由 PortfolioConstructor 决定
    """

    name = "sector_flow_monthly_v2"
    description = "申万行业资金流向策略 V2 (quantlab) - 行业资金流入排名 TopN"

    def __init__(
        self,
        top_n_industries: int = 3,
    ):
        # 参数全部为基本类型，可 JSON 序列化
        self.top_n_industries = int(top_n_industries)

        # 入参合理性校验
        if self.top_n_industries < 1:
            raise ValueError(
                f"top_n_industries must be >= 1, got {top_n_industries}"
            )
        # 申万一级行业共 31 个，TopN 最多 31
        if self.top_n_industries > 31:
            raise ValueError(
                f"top_n_industries must be <= 31 (申万一级行业总数), "
                f"got {top_n_industries}"
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

        if "industry_inflow_rank" not in df.columns:
            return pd.Series(0, index=df.index, dtype="int8")

        rank = df["industry_inflow_rank"]
        ok = ((rank > 0) & (rank <= self.top_n_industries)).fillna(False)
        return ok.astype("int8")


# ---------------------------------------------------------------------- #
# 工厂方法
# ---------------------------------------------------------------------- #
def make_sector_flow_monthly_v2(
    top_n_industries: int = 3,
) -> SectorFlowMonthlyV2:
    """显式工厂。"""
    return SectorFlowMonthlyV2(top_n_industries=top_n_industries)


# ---------------------------------------------------------------------- #
# 典型参数网格
# ---------------------------------------------------------------------- #
SECTOR_FLOW_MONTHLY_PARAM_SPACE: dict = {
    # 申万一级行业 Top N（1=第一名）
    "top_n_industries": [1, 2, 3, 5, 10],
}
