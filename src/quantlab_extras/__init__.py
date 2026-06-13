"""
quantlab_extras — A 股专用扩展

为 quantlab.risk 框架补齐 A 股市场的特殊风控检查：
    - 涨跌停过滤 (LimitUpCheck / LimitDownCheck)
    - ST 股票过滤 (STFilterCheck)
    - T+1 规则 (TPlusOneCheck)
    - 新股过滤 (NewStockCheck)
    - 停牌过滤 (SuspendCheck)
    - 默认工厂 (build_ashare_risk_manager / build_ashare_execution)
"""

from .limit_filter import (
    LimitUpCheck,
    LimitDownCheck,
)
from .st_filter import (
    STFilterCheck,
)
from .t_plus_one import (
    TPlusOneCheck,
)
from .new_stock import (
    NewStockCheck,
)
from .suspend import (
    SuspendCheck,
)
from .factory import (
    build_ashare_risk_manager,
    build_ashare_execution,
)


__all__ = [
    "LimitUpCheck",
    "LimitDownCheck",
    "STFilterCheck",
    "TPlusOneCheck",
    "NewStockCheck",
    "SuspendCheck",
    "build_ashare_risk_manager",
    "build_ashare_execution",
]
