from typing import Dict

from .base import (
PortfolioConstructor
)
from .target_portfolio import (
TargetPortfolio
)


class EqualWeight(PortfolioConstructor):

    # V1 等权
    #
    # 规则：
    #   score > 0 的 symbol 进入 active
    #   每个 active symbol 拿 1 / N 资金
    #   score <= 0 的 symbol 权重为 0
    #
    # 输入示例：
    #   {"AAPL": 1, "MSFT": 1, "NVDA": 0}
    # 输出：
    #   TargetPortfolio(
    #       timestamp=...,
    #       weights={"AAPL": 0.5, "MSFT": 0.5}
    #   )

    def construct(
        self,
        scores: Dict[str, float],
        timestamp
    ) -> TargetPortfolio:

        active = [
            s
            for s, v
            in scores.items()
            if v > 0
        ]

        if not active:

            return TargetPortfolio(
                timestamp=timestamp,
                weights={}
            )

        w = 1.0 / len(active)

        return TargetPortfolio(
            timestamp=timestamp,
            weights={
                s: w for s in active
            }
        )
