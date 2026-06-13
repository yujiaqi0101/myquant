"""
兼容层：旧路径 → 新路径
所有 quantlab/cache.py 等顶层文件改为 re-export
这样 main.py / engine.py / optimizer.py / 等旧 import 不破
未来 V2：直接删掉这些兼容文件
"""

# ---- data ----
from .data.cache import (
    FactorCache,
    factor_cache,
)

from .data.context import (
    StrategyContext,
)


# ---- signals ----
from .signals.base import (
    SignalStrategy,
)

from .signals.ma_cross import (
    MACrossStrategy,
)

from .signals.rsi import (
    RSIStrategy,
    make_rsi,
)


# ---- core ----
from .core.fill import (
    Fill,
)

from .core.position import (
    Position,
)

from .core.portfolio import (
    Portfolio,
)

from .core.trade import (
    ClosedTrade,
    TradeBuilder,
)

from .core.tradebook import (
    TradeBook,
)

from .core.backtest_result import (
    BacktestResult,
)

from .core.base_engine import (
    BaseBacktestEngine,
)


# ---- execution ----
from .execution.order import (
    Order,
)

from .execution.commission import (
    PercentageCommission,
)

from .execution.slippage import (
    PercentageSlippage,
)

from .execution.matcher import (
    TargetWeightExecution,
)


# ---- event ----
from .event.event_types import (
    MarketEvent,
    SignalEvent,
    OrderEvent,
    FillEvent,
    Event,
)

from .event.event_bus import (
    EventBus,
    event_bus,
)


# ---- optimizer ----
from .optimizer import (
    Optimizer,
    FastOptimizer,
    TwoStageResult,
)
