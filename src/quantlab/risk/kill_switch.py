"""
V2.5 Risk — Kill Switch / Emergency Stop

当 daily_loss < 阈值：
    1) 拒新单
    2) 平掉所有持仓（市价单）
    3) 停止 LiveEngine

V1：
    - 阈值写在构造里
    - 触发后只置一个 stop flag
    - 平仓逻辑由 LiveEngine 执行
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .limits import MaxDailyLoss
from .checks import RiskCheck


@dataclass
class EmergencyStop:
    """
    紧急停止
    触发条件：daily_pnl < threshold
    触发后：
        - stop = True
        - 通知 LiveEngine
    """

    threshold: float  # 负数，如 -0.05
    daily_pnl: float = 0.0
    initial_equity: float = 0.0
    stop: bool = False
    _on_trigger: Optional[Callable] = None

    def set_initial_equity(self, equity: float) -> None:
        self.initial_equity = equity

    def on_trigger(self, callback: Callable) -> None:
        self._on_trigger = callback

    def update_pnl(self, pnl: float) -> None:
        self.daily_pnl = pnl
        if self.initial_equity > 0:
            ret = pnl / self.initial_equity
            if ret <= self.threshold:
                self.stop = True
                if self._on_trigger is not None:
                    self._on_trigger(self)


class KillSwitch(RiskCheck):
    """
    包装 EmergencyStop
    当 stop = True，所有新单都拒
    """

    name = "KILL_SWITCH"

    def __init__(self, estop: EmergencyStop):
        self.estop = estop

    def check(self, order, context: Dict) -> bool:
        return not self.estop.stop
