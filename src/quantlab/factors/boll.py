"""
boll：Bollinger Bands
中轨 = N 期 MA
上下轨 = 中轨 ± K * N 期标准差
"""

import pandas as pd


def boll(
    ctx,
    symbol,
    period=20,
    num_std=2.0,
    return_tuple=False,
):

    # 返回：
    #   default: 中轨 Series
    #   return_tuple=True: (中轨, 上轨, 下轨) 三个 Series

    key = f"boll_{symbol}_{period}_{num_std}"

    val = ctx.cache.get(key)

    if val is None:

        close = ctx.data[symbol]["close"]
        mid = close.rolling(period).mean()
        std = close.rolling(period).std()

        upper = mid + num_std * std
        lower = mid - num_std * std

        if return_tuple:

            val = (mid, upper, lower)

        else:

            val = mid

        ctx.cache.set(key, val)

    return val
