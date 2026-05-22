"""
通用回测引擎 - 出场检查器

根据策略参数自动检查出场条件，支持：
- 止损（stop_loss）
- 止盈（take_profit）
- 动态跟踪止盈（trailing_stop）
- 超时平仓（max_holding_days）
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
    出场检查器 - 引擎级辅助检查
    
    根据策略参数自动检查出场条件，策略可选择接受或忽略。
    支持的检查项：
    - 止损（stop_loss）
    - 止盈（take_profit）
    - 动态跟踪止盈（trailing_stop）
    - 超时平仓（max_holding_days）
    """
    
    def __init__(self, params: Dict[str, Any]):
        """
        Parameters
        ----------
        params : Dict
            策略参数，包含 stop_loss, take_profit, trailing_stop, max_holding_days
        """
        self.params = params
    
    def check_all(self, context: 'Context', position: 'Position') -> ExitCheckResult:
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
        ExitCheckResult
            出场检查结果
        """
        # 1. 检查止损
        result = self._check_stop_loss(context, position)
        if result.should_exit:
            return result
        
        # 2. 检查止盈
        result = self._check_take_profit(context, position)
        if result.should_exit:
            return result
        
        # 3. 检查动态止盈
        result = self._check_trailing_stop(context, position)
        if result.should_exit:
            return result
        
        # 4. 检查超时
        result = self._check_timeout(context, position)
        if result.should_exit:
            return result
        
        return ExitCheckResult(should_exit=False)
    
    def _check_stop_loss(self, context: 'Context', position: 'Position') -> ExitCheckResult:
        """检查止损"""
        from .types import Direction
        
        stop_loss = self.params.get('stop_loss', 0)
        if stop_loss <= 0:
            return ExitCheckResult(should_exit=False)
        
        price = context.market_data.get(position.stock_code, {}).get('close', 0)
        if price <= 0:
            return ExitCheckResult(should_exit=False)
        
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
        
        return ExitCheckResult(should_exit=False)
    
    def _check_take_profit(self, context: 'Context', position: 'Position') -> ExitCheckResult:
        """检查止盈"""
        from .types import Direction
        
        take_profit = self.params.get('take_profit', 0)
        if take_profit <= 0:
            return ExitCheckResult(should_exit=False)
        
        price = context.market_data.get(position.stock_code, {}).get('close', 0)
        if price <= 0:
            return ExitCheckResult(should_exit=False)
        
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
        
        return ExitCheckResult(should_exit=False)
    
    def _check_trailing_stop(self, context: 'Context', position: 'Position') -> ExitCheckResult:
        """检查动态跟踪止盈"""
        from .types import Direction
        
        trailing_stop = self.params.get('trailing_stop', 0)
        if trailing_stop <= 0:
            return ExitCheckResult(should_exit=False)
        
        price = context.market_data.get(position.stock_code, {}).get('close', 0)
        ma_col = f'ma_{trailing_stop}'
        ma_val = context.market_data.get(position.stock_code, {}).get(ma_col, 0)
        
        if price <= 0 or ma_val <= 0:
            return ExitCheckResult(should_exit=False)
        
        if position.direction == Direction.LONG and price < ma_val:
            return ExitCheckResult(
                should_exit=True,
                reason=f"动态止盈：收盘价 {price:.2f} 跌破 {trailing_stop} 日均线 {ma_val:.2f}"
            )
        if position.direction == Direction.SHORT and price > ma_val:
            return ExitCheckResult(
                should_exit=True,
                reason=f"动态止盈：收盘价 {price:.2f} 超过 {trailing_stop} 日均线 {ma_val:.2f}"
            )
        
        return ExitCheckResult(should_exit=False)
    
    def _check_timeout(self, context: 'Context', position: 'Position') -> ExitCheckResult:
        """检查超时"""
        max_days = self.params.get('max_holding_days', 0)
        if max_days <= 0:
            return ExitCheckResult(should_exit=False)
        
        holding_days = (context.date - position.entry_date).days * 5 // 7
        
        if holding_days >= max_days:
            return ExitCheckResult(
                should_exit=True,
                reason=f"超时平仓：持仓 {holding_days} 天 (最大 {max_days} 天)"
            )
        
        return ExitCheckResult(should_exit=False)
