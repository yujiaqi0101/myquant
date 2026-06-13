"""
rsi：Relative Strength Index
0-100 之间
> 70 超买，< 30 超卖
"""

import pandas as pd


def rsi(ctx, symbol, period=14):

    key = f"rsi_{symbol}_{period}"

    val = ctx.cache.get(key)

    if val is None:

        close = ctx.data[symbol]["close"]
        delta = close.diff()

        gain = (
            delta
            .clip(lower=0)
            .rolling(period)
            .mean()
        )
        loss = (
            (-delta)
            .clip(lower=0)
            .rolling(period)
            .mean()
        )

        rs = gain / loss.replace(0, 1e-9)
        val = 100 - (100 / (1 + rs))

        ctx.cache.set(key, val)

    return val
