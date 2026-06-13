from dataclasses import dataclass, field
from typing import Dict


@dataclass(slots=True)
class TargetPortfolio:

    # Portfolio Construction Layer 的输出
    # Execution 的输入
    #
    # 不要再传裸 dict
    # 未来要加：
    #   rebalance_time
    #   cash_buffer
    #   max_weight
    #   sector_limit
    # 都挂在这个类上

    timestamp: object

    weights: Dict[str, float] = field(
        default_factory=dict
    )

    def __post_init__(self):

        # 防御性校验
        # 允许 sum < 1（剩余视为 cash）
        # 不允许 weight < 0
        for sym, w in self.weights.items():

            if w < 0:

                raise ValueError(
                    f"weight for {sym} must be >= 0, "
                    f"got {w}"
                )

    @property
    def symbols(self):

        return list(self.weights.keys())

    @property
    def total_weight(self):

        return sum(self.weights.values())
