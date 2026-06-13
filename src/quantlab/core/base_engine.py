"""
BaseBacktestEngine：所有回测引擎的统一接口

V1 阶段有 3 个实现：
- EventEngine：精确、慢、事件流
- BarEngine：兼容旧 API（dict 返）
- VectorBTAdapter：快速、但精度低
- SubprocessVectorBT：沙箱友好

Optimizer / ValidationRunner 只认 BaseBacktestEngine
新增引擎只需继承 + run() 返 BacktestResult
"""

from abc import (
    ABC,
    abstractmethod,
)
from typing import Any, Dict


class BaseBacktestEngine(ABC):

    @abstractmethod
    def run(
        self,
        strategy,
        data: Dict,
        params: Dict = None,
    ) -> "BacktestResult":
        """
        Args:
            strategy: 策略对象
                必须有 .signal(ctx) -> pd.DataFrame
            data: Dict[symbol, pd.DataFrame]
            params: 策略参数（可选，给报告/回放用）

        Returns:
            BacktestResult: 统一输出
        """
        pass
