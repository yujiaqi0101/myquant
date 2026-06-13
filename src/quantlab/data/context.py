class StrategyContext:

    # V1.4 + V1.9
    # 策略执行的上下文
    # 把 data 和 cache 打包传给策略
    # 以后再加：universe / calendar / benchmark 等
    # 都通过 ctx 暴露，策略签名不变

    def __init__(
        self,
        data,
        cache
    ):

        self.data = data
        self.cache = cache

    @property
    def symbols(self):
        # 所有可交易标的
        # ctx.data = {sym: df, ...}
        return list(self.data.keys())
