"""
quantlab_quintile — 基于 quantlab BarEngine 的 5 分位分层回测包装。

替代 ``src.factors.multi_factor_quintile_backtest_v2.MultiFactorQuintileBacktestEngineV2``，
提供更解耦、更可测试、跨引擎一致的分层回测实现。

核心组件：
    - QuintileSignalStrategy: 根据 factor_data 选股输出 signal 的 SignalStrategy
    - QuintileExperiment: 主入口，5 分位独立回测 + 多空对冲 + IC/IR
    - QuintileResult: 输出 dataclass（含 quintile_curves / long_short / ic_series）

使用示例::

    from src.quantlab_quintile import QuintileExperiment
    exp = QuintileExperiment(n_quantiles=5, rebalance_freq=5)
    res = exp.run(factor_df, data, long_quantile=1, short_quantile=5)
    res.quintile_curves[1]   # Q1 净值曲线
    res.long_short           # 多空对冲净值
    res.ic_series            # IC 时序
    res.ir                   # IR
"""

from .quintile_strategy import (
    QuintileSignalStrategy,
)
from .quintile_experiment import (
    QuintileExperiment,
    QuintileResult,
)


__all__ = [
    "QuintileSignalStrategy",
    "QuintileExperiment",
    "QuintileResult",
]
