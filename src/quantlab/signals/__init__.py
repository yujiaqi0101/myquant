# Signals Layer
# 策略只产生 signal
# 不知道引擎，不知道仓位，不知道撮合
# 输出 pd.Series 或 pd.DataFrame
# 取值约定：1=多，0=空，-1=空（暂不强用）

from .base import (
    SignalStrategy,
)

# 经典技术指标信号
from .ma_cross import (
    MACrossStrategy,
)
from .rsi import (
    RSIStrategy,
    make_rsi,
    RSI_PARAM_SPACE,
    RSI_PARAM_SPACE_TREND,
)


__all__ = [
    "SignalStrategy",
    "MACrossStrategy",
    "RSIStrategy",
    "make_rsi",
    "RSI_PARAM_SPACE",
    "RSI_PARAM_SPACE_TREND",
]
