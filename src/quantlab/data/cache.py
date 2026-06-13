class FactorCache:

    # V1.4
    # 因子计算缓存
    # 防止参数网格搜索时重复计算同一因子
    # 例如 ma(20) 在 12 组参数中只算 1 次

    def __init__(self):

        self._cache = {}

    def get(
        self,
        key
    ):

        return self._cache.get(
            key
        )

    def set(
        self,
        key,
        value
    ):

        self._cache[
            key
        ] = value

    def clear(self):

        self._cache.clear()


# 全局 Cache
# 策略、引擎、适配器都共享同一个
# Optimizer 跑 12 组参数时
# ma(20) 第一次算后被缓存
# 后续 11 次直接命中
factor_cache = FactorCache()
