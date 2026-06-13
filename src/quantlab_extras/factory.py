"""
A 股默认 RiskManager / Execution 工厂。

build_ashare_risk_manager:
    把 6 个 A 股 Check + OrderSizeCheck + KillSwitch 串到 RiskManager 上。

build_ashare_execution:
    构造 A 股默认执行器：
        - 100 股一手 (lot_size=100)
        - 容忍度 2%
        - 佣金万 2.5 / 滑点万 1（以属性方式挂在对象上，
          供 BarEngine / LiveEngine 等下游组件按需读取）
"""

from typing import Optional

from src.quantlab.risk.risk_manager import RiskManager
from src.quantlab.risk.limits import (
    MaxOrderSize,
    MaxPositionLimit,
)
from src.quantlab.risk.checks import (
    OrderSizeCheck,
    PositionLimitCheck,
)
from src.quantlab.risk.kill_switch import (
    EmergencyStop,
    KillSwitch,
)

from .limit_filter import (
    LimitUpCheck,
    LimitDownCheck,
)
from .st_filter import (
    STFilterCheck,
)
from .t_plus_one import (
    TPlusOneCheck,
)
from .new_stock import (
    NewStockCheck,
)
from .suspend import (
    SuspendCheck,
)


def build_ashare_risk_manager(
    enable_limit_filter: bool = True,
    enable_st_filter: bool = True,
    enable_t_plus_one: bool = True,
    enable_new_stock_filter: bool = True,
    enable_suspend_filter: bool = True,
    new_stock_days: int = 60,
    min_order_size: int = 100,
    max_order_size: int = 1_000_000,
    max_daily_loss_pct: float = 0.05,
    max_position_qty: int = 1_000_000,
    position_limit_symbols: Optional[list] = None,
) -> RiskManager:
    """
    构造 A 股默认 RiskManager。

    默认包含：
        - LimitUpCheck        (涨停不买)
        - LimitDownCheck      (跌停不卖)
        - STFilterCheck       (ST/*ST/退市过滤)
        - TPlusOneCheck       (T+1)
        - NewStockCheck       (新股过滤，默认 60 天)
        - SuspendCheck        (停牌过滤)
        - OrderSizeCheck      (单笔最大量)
        - KillSwitch          (日亏急停，默认 5%)

    总计 ≥ 8 个 check（5 涨跌 + ST + T+1 + 新股 + 停牌 + OrderSize + KillSwitch）。
    """
    rm = RiskManager()

    if enable_limit_filter:
        rm.add_check(LimitUpCheck())
        rm.add_check(LimitDownCheck())

    if enable_st_filter:
        rm.add_check(STFilterCheck())

    if enable_t_plus_one:
        rm.add_check(TPlusOneCheck())

    if enable_new_stock_filter:
        rm.add_check(NewStockCheck(min_days=new_stock_days))

    if enable_suspend_filter:
        rm.add_check(SuspendCheck())

    # 单笔最大下单量
    rm.add_check(OrderSizeCheck(MaxOrderSize(max_qty=max_order_size)))

    # 全局单 symbol 持仓上限（可选）
    if position_limit_symbols:
        limits = [
            MaxPositionLimit(symbol=s, max_qty=max_position_qty)
            for s in position_limit_symbols
        ]
        rm.add_check(PositionLimitCheck(limits))

    # 日亏急停：默认 5%
    estop = EmergencyStop(threshold=-max_daily_loss_pct)
    rm.add_check(KillSwitch(estop))
    # 把 EmergencyStop 挂在 rm 上，便于 LiveEngine 配置 initial_equity / update_pnl
    rm._emergency_stop = estop  # noqa: SLF001

    # 仅记录提示，不真正使用
    _ = min_order_size  # 1 手 = 100 股的语义体现在 lot_size/execution 层

    return rm


def build_ashare_execution(
    commission_rate: float = 0.00025,  # 万 2.5
    slippage_rate: float = 0.0001,     # 万 1
    lot_size: int = 100,               # 1 手
    position_tolerance: float = 0.02,  # 2%
    cash_buffer: float = 0.02,         # 2% 现金缓冲（仅记录语义）
):
    """
    构造 A 股默认 Execution。

    当前 quantlab.execution.TargetWeightExecution 仅暴露
    `lot_size` / `position_tolerance` 字段；commission 与 slippage
    以对象属性方式挂到 execution 上，下游 BarEngine / LiveEngine
    可按需读取。cash_buffer 留作未来扩展点。
    """
    from src.quantlab.execution import (
        PercentageCommission,
        PercentageSlippage,
        TargetWeightExecution,
    )

    execution = TargetWeightExecution(
        lot_size=lot_size,
        position_tolerance=position_tolerance,
    )
    execution.commission = PercentageCommission(rate=commission_rate)
    execution.slippage = PercentageSlippage(rate=slippage_rate)
    execution.cash_buffer = cash_buffer
    return execution
