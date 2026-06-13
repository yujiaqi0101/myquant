import pandas as pd

from ..factors.ma import ma
from .base import SignalStrategy


class MACrossStrategy(SignalStrategy):

    # V2: 多标的
    # signal(ctx) 返回 DataFrame
    #   index   = bar 时间
    #   columns = symbol
    #   value   ∈ {-1, 0, 1}
    # 策略层只决定"哪个 symbol 在哪个 bar 应该持什么方向"
    # 仓位大小由 PositionSizer 决定

    def __init__(self,fast=20,slow=60):
        self.fast = fast
        self.slow = slow

    def signal(self,ctx) -> pd.DataFrame:

        signals = {}

        for symbol in ctx.data:

            fast_ma = ma(ctx,symbol,self.fast)

            slow_ma = ma(ctx,symbol,self.slow)

            signals[symbol] = (fast_ma>slow_ma).astype(int)

        return pd.DataFrame(signals)
