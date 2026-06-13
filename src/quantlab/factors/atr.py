"""
atr：Average True Range
衡量波动率
TR = max(high-low, |high-prev_close|, |low-prev_close|)
ATR = TR 的 N 期均值
"""

import pandas as pd


def atr(ctx, symbol, period=14):

    key = f"atr_{symbol}_{period}"

    val = ctx.cache.get(key)

    if val is None:

        df = ctx.data[symbol]
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        val = tr.rolling(period).mean()

        ctx.cache.set(key, val)

    return val
