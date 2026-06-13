from abc import ABC, abstractmethod
from typing import Dict

from .target_portfolio import TargetPortfolio


class PortfolioConstructor(ABC):

    # 抽象基类
    #
    # 输入：scores: Dict[symbol, float]
    #       策略产出的单行信号
    #       离散信号：{-1, 0, 1}
    #       连续信号：{0.91, 0.42, -0.3}
    #       （未来 score 化以后：0.91, 0.42, 0.76）
    #
    # 输出：TargetPortfolio
    #       含 timestamp + weights dict

    @abstractmethod
    def construct(
        self,
        scores: Dict[str, float],
        timestamp
    ) -> TargetPortfolio:

        raise NotImplementedError
