"""
PortfolioSnapshot - V1.9 新增
单 bar 的组合快照

每根 bar 收盘后生成一个：
  - timestamp
  - equity
  - cash
  - weights：当前各 symbol 占总权益的权重

权益曲线 = List[PortfolioSnapshot]

分析模块 / WalkForward / Report
全部基于这个 List 复用
"""

from dataclasses import (
    dataclass,
    field,
)
from typing import Dict


@dataclass(slots=True)
class PortfolioSnapshot:

    timestamp: object

    equity: float

    cash: float

    weights: Dict[str, float] = field(
        default_factory=dict
    )

    @property
    def invested_weight(self) -> float:
        # 实际投资比例 = 1 - cash_ratio
        if self.equity <= 0:
            return 0.0
        return 1.0 - (
            self.cash / self.equity
        )
