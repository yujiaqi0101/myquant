from typing import Dict

from .base import (
PortfolioConstructor
)
from .target_portfolio import (
TargetPortfolio
)


class TopN(PortfolioConstructor):

    # 排序选股
    #
    # 适用场景：
    #   动量轮动
    #   行业 ETF 轮动
    #   多因子选股
    #
    # 规则：
    #   score > 0 的 symbol 视为候选
    #   按 score 降序排序
    #   取前 N 个
    #   等权分配 1/N
    #
    # 输入示例：
    #   {"AAPL":0.8, "MSFT":0.6, "NVDA":0.9, "TSLA":0.3}
    #   n=2
    # 输出：
    #   TargetPortfolio(
    #       timestamp=...,
    #       weights={"NVDA": 0.5, "AAPL": 0.5}
    #   )

    def __init__(self, n=2):

        if n < 1:

            raise ValueError(
                f"n must be >= 1, got {n}"
            )

        self.n = n

    def construct(
        self,
        scores: Dict[str, float],
        timestamp
    ) -> TargetPortfolio:

        candidates = [
            (s, v)
            for s, v
            in scores.items()
            if v > 0
        ]

        candidates.sort(
            key=lambda x: x[1],
            reverse=True
        )

        top = candidates[: self.n]

        if not top:

            return TargetPortfolio(
                timestamp=timestamp,
                weights={}
            )

        w = 1.0 / len(top)

        return TargetPortfolio(
            timestamp=timestamp,
            weights={
                s: w for s, _ in top
            }
        )
