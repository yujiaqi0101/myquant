"""
出场检查器工具类 - 供策略选择使用

提供常用的出场检查逻辑，策略可组合使用：
- 止损（stop_loss）
- 止盈（take_profit）
- ATR动态止盈（trailing_stop）
- 超时平仓（max_holding_days）

使用示例：
    class MyStrategy(BaseStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._exit_checker = ExitChecker({
                'stop_loss': 0.07,
                'take_profit': 0.20
            })

        def exit_checker(self, context, position):
            return self._exit_checker.check_all(context, position)
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class ExitCheckResult:
    """出场检查结果"""
    should_exit: bool
    reason: str = ""
    suggested_order: Optional['Order'] = None


class ExitChecker:
    """
    出场检查器 - 策略层工具类

    提供止损、止盈、ATR动态止盈、超时平仓等常用逻辑。
    策略通过组合此类实现标准出场功能，也可完全自定义。

    Parameters
    ----------
    params : Dict[str, Any]
        检查参数，支持：
        - stop_loss: 止损比例（如0.07表示7%）
        - take_profit: 止盈比例（如0.20表示20%）
        - trailing_stop: ATR动态止盈倍数（如3表示3倍ATR）
        - max_holding_days: 最大持仓天数
    """

    def __init__(self, params: Dict[str, Any]):
        self.params = params

    def check_all(self, context: 'Context', position: 'Position') -> Optional[ExitCheckResult]:
        """
        检查所有出场条件

        按优先级顺序检查：止损 > 止盈 > 动态止盈 > 超时

        Parameters
        ----------
        context : Context
            策略上下文
        position : Position
            当前持仓

        Returns
        -------
        Optional[ExitCheckResult]
            触发出场时返回 ExitCheckResult，不触发时返回 None
        """
        # 1. 检查止损
        result = self._check_stop_loss(context, position)
        if result is not None:
            return result

        # 2. 检查止盈
        result = self._check_take_profit(context, position)
        if result is not None:
            return result

        # 3. 检查动态止盈
        result = self._check_trailing_stop(context, position)
        if result is not None:
            return result

        # 4. 检查超时
        result = self._check_timeout(context, position)
        if result is not None:
            return result

        return None  # 不触发

    def _check_stop_loss(self, context: 'Context', position: 'Position') -> Optional[ExitCheckResult]:
        """检查止损"""
        from .types import Direction

        stop_loss = self.params.get('stop_loss', 0)
        if stop_loss <= 0:
            return None

        price = context.market_data.get(position.stock_code, {}).get('close', 0)
        if price <= 0:
            return None

        pnl = (price - position.entry_price) / position.entry_price

        if position.direction == Direction.LONG and pnl <= -stop_loss:
            return ExitCheckResult(
                should_exit=True,
                reason=f"止损：亏损 {pnl:.2%} (阈值 {-stop_loss:.2%})"
            )
        if position.direction == Direction.SHORT and pnl >= stop_loss:
            return ExitCheckResult(
                should_exit=True,
                reason=f"止损：亏损 {pnl:.2%} (阈值 {stop_loss:.2%})"
            )

        return None

    def _check_take_profit(self, context: 'Context', position: 'Position') -> Optional[ExitCheckResult]:
        """检查止盈"""
        from .types import Direction

        take_profit = self.params.get('take_profit', 0)
        if take_profit <= 0:
            return None

        price = context.market_data.get(position.stock_code, {}).get('close', 0)
        if price <= 0:
            return None

        pnl = (price - position.entry_price) / position.entry_price

        if position.direction == Direction.LONG and pnl >= take_profit:
            return ExitCheckResult(
                should_exit=True,
                reason=f"止盈：盈利 {pnl:.2%} (阈值 {take_profit:.2%})"
            )
        if position.direction == Direction.SHORT and pnl <= -take_profit:
            return ExitCheckResult(
                should_exit=True,
                reason=f"止盈：盈利 {pnl:.2%} (阈值 {-take_profit:.2%})"
            )

        return None

    def _check_trailing_stop(self, context: 'Context', position: 'Position') -> Optional[ExitCheckResult]:
        """
        检查ATR动态止盈（仅支持做多）

        做多：收盘价 < 最高价 - N×ATR 时卖出
        """
        from .types import Direction

        trailing_stop = self.params.get('trailing_stop', 0)
        if trailing_stop <= 0:
            return None

        # 仅支持做多
        if position.direction != Direction.LONG:
            return None

        price = context.market_data.get(position.stock_code, {}).get('close', 0)
        atr = context.market_data.get(position.stock_code, {}).get('atr', 0)
        highest_price = position.highest_price

        if price <= 0 or atr <= 0 or highest_price <= 0:
            return None

        # ATR动态止盈：价格从最高点回落超过 N×ATR
        threshold = highest_price - trailing_stop * atr
        if price < threshold:
            return ExitCheckResult(
                should_exit=True,
                reason=f"ATR动态止盈：收盘价 {price:.2f} < 最高价 {highest_price:.2f} - {trailing_stop}×ATR {atr:.2f}"
            )

        return None

    def _check_timeout(self, context: 'Context', position: 'Position') -> Optional[ExitCheckResult]:
        """检查超时"""
        max_days = self.params.get('max_holding_days', 0)
        if max_days <= 0:
            return None

        holding_days = (context.date - position.entry_date).days * 5 // 7

        if holding_days >= max_days:
            return ExitCheckResult(
                should_exit=True,
                reason=f"超时平仓：持仓 {holding_days} 天 (最大 {max_days} 天)"
            )

        return None
