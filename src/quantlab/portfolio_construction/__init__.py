# Portfolio Construction Layer
#
# 职责：
#   接收 signal/score -> 输出 TargetPortfolio
#
# 关键对象：
#   - TargetPortfolio：时间戳 + 目标权重 dict
#   - PortfolioConstructor：抽象基类
#   - EqualWeight / TopN：第一版两个具体实现
#
# 未来扩展：
#   - RiskParity：按波动率倒数加权
#   - MaxWeightConstraint：限制单标的权重上限
#   - SectorLimit：行业暴露约束
#   - CashBuffer：保留一定现金
#   - RebalanceTime：只在调仓日才更新权重

from .target_portfolio import (
    TargetPortfolio
)

from .base import (
    PortfolioConstructor
)

from .equal_weight import (
    EqualWeight
)

from .top_n import (
    TopN
)


__all__ = [
    "TargetPortfolio",
    "PortfolioConstructor",
    "EqualWeight",
    "TopN",
]
