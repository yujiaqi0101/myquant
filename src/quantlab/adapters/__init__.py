# Adapters：把策略接入不同后端
# 现在支持：
#   - SubprocessVectorBT（sandbox 友好的 vectorbt 验证）
#   - VectorBTAdapter（同进程 vbt，本机用）
# 未来：
#   - Live Trading Broker（实盘）

from .subprocess_vbt import (
    SubprocessVectorBT,
    get_subprocess_vbt,
)


try:

    from .vectorbt_adapter import (
        VectorBTAdapter
    )

except Exception:

    VectorBTAdapter = None


__all__ = [
    "SubprocessVectorBT",
    "get_subprocess_vbt",
    "VectorBTAdapter",
]
