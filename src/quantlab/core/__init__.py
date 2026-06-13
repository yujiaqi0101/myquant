# Core Domain Model
# 整个系统最核心的领域对象
# 用 @dataclass(slots=True) 优化内存
# 未来 Fill 可能几十万、几百万，slots 减 30-60% 内存

from .fill import (
    Fill,
)

from .order import (
    Order,
)

from .position import (
    Position,
)

from .trade import (
    ClosedTrade,
    TradeBuilder,
)

from .portfolio import (
    Portfolio,
)

from .tradebook import (
    TradeBook,
)

from .backtest_result import (
    BacktestResult,
)

from .base_engine import (
    BaseBacktestEngine,
)

from .portfolio_snapshot import (
    PortfolioSnapshot,
)


__all__ = [
    "Fill",
    "Order",
    "Position",
    "ClosedTrade",
    "TradeBuilder",
    "Portfolio",
    "TradeBook",
    "BacktestResult",
    "BaseBacktestEngine",
    "PortfolioSnapshot",
]
