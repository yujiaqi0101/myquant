def ma(ctx, symbol, period):

    # 简单移动平均
    # V2: 多标的
    # cache key 包含 symbol
    # 例如 ma_AAPL_20 / ma_MSFT_20 互不干扰

    key = (
        f"ma_{symbol}_{period}"
    )

    val = ctx.cache.get(
        key
    )

    if val is None:

        val = (
            ctx.data[symbol]["close"]
            .rolling(period)
            .mean()
        )

        ctx.cache.set(
            key,
            val
        )

    return val
