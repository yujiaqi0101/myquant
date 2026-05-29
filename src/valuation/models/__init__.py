"""
估值模型子模块 - 包含各种估值方法的实现
"""

from .base import (
    ValuationMethod,
    ValuationInput,
    ValuationResult,
    ValuationModel,
)

# 行业估值模型
from .financial import (
    FinancialValuationModel,
    value_financial_stock,
)
from .consumer import (
    ConsumerValuationModel,
    value_consumer_stock,
)
from .cyclical import (
    CyclicalValuationModel,
    value_cyclical_stock,
)
from .technology import (
    TechnologyValuationModel,
    value_tech_stock,
)
from .real_estate import (
    RealEstateValuationModel,
    value_real_estate_stock,
)
from .utility import (
    UtilityValuationModel,
    value_utility_stock,
)

__all__ = [
    # 基础类
    "ValuationMethod",
    "ValuationInput",
    "ValuationResult",
    "ValuationModel",
    # 行业估值模型
    "FinancialValuationModel",
    "ConsumerValuationModel",
    "CyclicalValuationModel",
    "TechnologyValuationModel",
    "RealEstateValuationModel",
    "UtilityValuationModel",
    # 便捷函数
    "value_financial_stock",
    "value_consumer_stock",
    "value_cyclical_stock",
    "value_tech_stock",
    "value_real_estate_stock",
    "value_utility_stock",
]
