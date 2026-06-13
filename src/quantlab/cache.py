# 兼容层：原 cache.py 已迁移到 data/cache.py
# 旧 import 仍可用：from quantlab.cache import factor_cache
from ._compat import (
    FactorCache,
    factor_cache,
)
