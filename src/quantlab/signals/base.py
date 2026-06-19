import inspect

import pandas as pd

from abc import ABC
from abc import abstractmethod


class SignalStrategy(ABC):

    # Spectre-style strategy
    # 策略只产生 signal
    # 不关心回测引擎是 VectorBT / BarEngine / TickEngine
    # 不关心仓位如何转换为订单

    # signal 的取值约定：
    #   1   = 做多
    #   0   = 空仓
    #  -1   = 做空（暂不强制使用）

    # V1.9: signal 必须是 DataFrame
    #   index   = bar 时间
    #   columns = symbol（多标的）
    #   value   ∈ {-1, 0, 1}
    # 每根 bar 取 signal.iloc[i-1].to_dict() → scores
    # 适配器负责把 signal 翻译成：
    #   - VectorBT  : per-symbol entries / exits
    #   - BarEngine : PortfolioConstructor 接收 scores dict
    #                 → TargetPortfolio → List[Order]

    @property
    def params(self) -> dict:
        """从实例属性自动构建参数字典（取 __init__ 参数名对应的属性值）"""
        sig = inspect.signature(self.__init__)
        return {
            name: getattr(self, name)
            for name in sig.parameters
            if name != 'self' and hasattr(self, name)
        }

    @abstractmethod
    def signal(
        self,
        ctx
    ) -> pd.DataFrame:

        pass
