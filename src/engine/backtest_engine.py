"""
通用回测引擎 - 核心引擎

支持所有策略在同一框架下运行，提供：
- 逐日事件循环
- 引擎级出场检查（止损/止盈/动态止盈/超时）
- 风控集成
- 完整的每日账户记录（支持逐日检查）
"""

from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
from datetime import timedelta

from .types import (
    Order, TradeRecord, Position, DailySnapshot, 
    BacktestResult, Context, Direction
)
from .exit_checker import ExitChecker


class BacktestEngine:
    """
    通用回测引擎 - 统一框架
    
    支持所有策略在同一框架下运行，提供：
    - 逐日事件循环
    - 引擎级出场检查（止损/止盈/动态止盈/超时）
    - 风控集成
    - 完整的每日账户记录（支持逐日检查）
    
    Parameters
    ----------
    strategy : BaseStrategy
        策略实例
    initial_capital : float
        初始资金
    enable_engine_exit : bool
        是否启用引擎级出场检查（默认True）
    risk_controller : RiskController, optional
        风控控制器
    """

    def __init__(
        self,
        strategy: 'BaseStrategy',
        initial_capital: float = 1_000_000,
        enable_engine_exit: bool = True,
        risk_controller: Any = None,
    ):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.enable_engine_exit = enable_engine_exit
        self.risk_controller = risk_controller
        
        # 从策略参数获取交易成本
        self.commission_rate = strategy.params.get('commission_rate', 0.0003)
        self.slippage = strategy.params.get('slippage', 0.0001)
        
        # 创建出场检查器
        self.exit_checker = ExitChecker(strategy.params) if enable_engine_exit else None

        # 运行时状态
        self.cash = initial_capital
        self.frozen_cash = 0.0
        self.positions: Dict[str, Position] = {}
        self.trades: List[TradeRecord] = []
        self.daily_snapshots: List[DailySnapshot] = []
        self.peak_value = initial_capital

    def run(
        self, 
        price_data: pd.DataFrame, 
        warmup_data: pd.DataFrame = None
    ) -> BacktestResult:
        """
        运行回测
        
        数据范围说明：
        -------------
        回测涉及两个时间范围：
        
        1. 预热期数据 (warmup_data): 
           - 用于策略在 on_init 中预计算指标（如均线、因子等）
           - 例如：回测2025-01-01至2025-02-01，但需要20日均线
           - 则预热期应包含2024-12-01至2024-12-31的数据
           - 这部分数据只用于计算，不产生交易信号
        
        2. 回测期数据 (price_data):
           - 正式回测的时间范围
           - 策略的 on_bar 从回测期第一天开始调用
           - 产生实际的交易信号和绩效计算
        
        Parameters
        ----------
        price_data : pd.DataFrame
            MultiIndex (trade_date, stock_code) 的价格数据（回测期）
        warmup_data : pd.DataFrame, optional
            预热期数据，用于策略初始化时预计算指标
            
        Returns
        -------
        BacktestResult
            包含完整历史记录的回测结果
        """
        trade_dates = sorted(price_data.index.get_level_values('trade_date').unique())
        
        # 如果有预热数据，合并到上下文供策略初始化使用
        full_data = price_data
        if warmup_data is not None and not warmup_data.empty:
            full_data = pd.concat([warmup_data, price_data]).sort_index()
        
        # 构建上下文
        context = Context(
            date=None,
            market_data={},
            full_data=full_data,
            positions=self.positions,
            cash=self.cash,
            frozen_cash=self.frozen_cash,
            total_value=self.initial_capital,
            history=self.daily_snapshots,
            params=self.strategy.params,
            _engine=self,
        )
        
        # 策略初始化 - 此时可访问完整数据（含预热期）
        self.strategy.on_init(context)
        self.strategy.on_start(context)
        
        # 逐日事件循环
        for date in trade_dates:
            context.date = date
            
            # 准备当日数据
            day_data = price_data.xs(date, level='trade_date')
            context.market_data = day_data.to_dict('index') if not day_data.empty else {}
            
            # 更新账户状态
            position_value = self._calc_position_value(day_data)
            context.cash = self.cash
            context.frozen_cash = self.frozen_cash
            context.total_value = self.cash + self.frozen_cash + position_value
            
            # 更新峰值和回撤
            if context.total_value > self.peak_value:
                self.peak_value = context.total_value
            drawdown = (self.peak_value - context.total_value) / self.peak_value
            
            # ---- 阶段1：引擎级出场检查 ----
            exit_orders = []
            if self.enable_engine_exit and self.exit_checker:
                for stock_code, position in list(self.positions.items()):
                    result = self.exit_checker.check_all(context, position)
                    if result.should_exit:
                        # 回调策略，让策略决定是否接受
                        order = self.strategy.on_exit_triggered(context, position, result.reason)
                        if order is None:
                            # 策略接受引擎建议，自动生成出场订单
                            order = Order(
                                stock_code=stock_code,
                                direction=position.direction,
                                quantity=position.quantity,
                                reason=result.reason
                            )
                        if order:
                            exit_orders.append(order)
            
            # ---- 阶段2：风控检查 ----
            if self.risk_controller:
                risk_orders = self._check_risk(context, day_data)
                exit_orders.extend(risk_orders)
            
            # 执行出场订单
            for order in exit_orders:
                self._execute_exit(order, day_data, date)
            
            # ---- 阶段3：调用策略生成订单 ----
            orders = self.strategy.on_bar(context)
            
            # ---- 阶段4：执行入场订单 ----
            for order in orders:
                self._execute_entry(order, day_data, date)
            
            # ---- 阶段5：记录每日快照 ----
            self._record_snapshot(date, day_data, drawdown)
        
        # 回测结束
        self.strategy.on_stop(context)
        
        return self._build_result()

    def _calc_position_value(self, day_data: pd.DataFrame) -> float:
        """计算持仓市值"""
        total = 0.0
        for stock_code, position in self.positions.items():
            price = day_data.get(stock_code, {}).get('close', 0)
            if price > 0:
                total += position.quantity * price
        return total

    def _check_risk(self, context: Context, day_data: pd.DataFrame) -> List[Order]:
        """检查风控条件"""
        orders = []
        # 组合风控检查
        if self.risk_controller:
            portfolio_value = context.total_value
            action, _, reason = self.risk_controller.check_portfolio_risk(
                context.date.strftime('%Y-%m-%d'),
                portfolio_value,
                sum(p.quantity * day_data.get(p.stock_code, {}).get('close', 0) 
                    for p in self.positions.values())
            )
            if action.value != 'none':
                # 组合止损触发，全部清仓
                for stock_code, position in list(self.positions.items()):
                    orders.append(Order(
                        stock_code=stock_code,
                        direction=position.direction,
                        quantity=position.quantity,
                        reason=f"组合止损: {reason}"
                    ))
        return orders

    def _execute_entry(self, order: Order, day_data: pd.DataFrame, date: pd.Timestamp):
        """执行入场订单"""
        # 检查是否已有持仓
        if order.stock_code in self.positions:
            return
        
        price = day_data.get(order.stock_code, {}).get('close', 0)
        if price <= 0:
            return
        
        # 计算成本（含佣金和滑点）
        cost = price * order.quantity * (1 + self.commission_rate + self.slippage)
        
        # 检查资金
        if cost > self.cash:
            self.strategy.on_order_rejected(
                Context(date=date), order, "资金不足"
            )
            return
        
        # 扣除资金
        self.cash -= cost
        
        # 创建持仓
        self.positions[order.stock_code] = Position(
            stock_code=order.stock_code,
            direction=order.direction,
            quantity=order.quantity,
            entry_price=price,
            entry_date=date,
            entry_reason=order.reason,
        )
        
        # 通知风控
        if self.risk_controller:
            self.risk_controller.record_entry(
                date.strftime('%Y-%m-%d'),
                order.stock_code, price,
                price * order.quantity / (self.cash + cost)
            )
        
        # 记录交易
        trade = TradeRecord(
            date=date,
            stock_code=order.stock_code,
            direction=order.direction,
            action="open",
            price=price,
            quantity=order.quantity,
            commission=price * order.quantity * self.commission_rate,
            slippage=price * order.quantity * self.slippage,
            reason=order.reason,
        )
        self.trades.append(trade)
        
        # 回调
        self.strategy.on_order_filled(Context(date=date), trade)

    def _execute_exit(self, order: Order, day_data: pd.DataFrame, date: pd.Timestamp):
        """执行出场订单"""
        if order.stock_code not in self.positions:
            return
        
        position = self.positions[order.stock_code]
        price = day_data.get(order.stock_code, {}).get('close', 0)
        if price <= 0:
            return
        
        # 计算盈亏
        if position.direction == Direction.LONG:
            pnl = (price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - price) * position.quantity
        
        # 计算交易成本
        commission = price * position.quantity * self.commission_rate
        slippage = price * position.quantity * self.slippage
        
        # 更新资金
        self.cash += price * position.quantity - commission - slippage
        
        # 移除持仓
        del self.positions[order.stock_code]
        
        # 通知风控
        if self.risk_controller:
            self.risk_controller.record_exit(order.stock_code)
        
        # 记录交易
        trade = TradeRecord(
            date=date,
            stock_code=order.stock_code,
            direction=position.direction,
            action="close",
            price=price,
            quantity=position.quantity,
            commission=commission,
            slippage=slippage,
            pnl=pnl,
            reason=order.reason,
        )
        self.trades.append(trade)
        
        # 回调
        self.strategy.on_order_filled(Context(date=date), trade)

    def _record_snapshot(self, date: pd.Timestamp, day_data: pd.DataFrame, drawdown: float):
        """记录每日快照"""
        position_value = self._calc_position_value(day_data)
        
        # 获取当日交易
        daily_trades = [t for t in self.trades if t.date == date]
        
        # 计算当日盈亏
        daily_pnl = sum(t.pnl for t in daily_trades if t.action == 'close')
        
        snapshot = DailySnapshot(
            date=date,
            cash=self.cash,
            frozen_cash=self.frozen_cash,
            position_value=position_value,
            total_value=self.cash + self.frozen_cash + position_value,
            n_positions=len(self.positions),
            daily_pnl=daily_pnl,
            daily_return=daily_pnl / (self.cash + self.frozen_cash + position_value - daily_pnl) 
                if (self.cash + self.frozen_cash + position_value - daily_pnl) > 0 else 0,
            drawdown=drawdown,
            max_drawdown=max(s.drawdown for s in self.daily_snapshots) if self.daily_snapshots else drawdown,
            trades=daily_trades,
        )
        self.daily_snapshots.append(snapshot)

    def _build_result(self) -> BacktestResult:
        """构建回测结果"""
        final_value = self.daily_snapshots[-1].total_value if self.daily_snapshots else self.initial_capital
        
        # 计算绩效指标
        performance = self._calculate_performance()
        
        # 获取风控报告
        risk_report = {}
        if self.risk_controller:
            risk_report = self.risk_controller.get_risk_report()
        
        return BacktestResult(
            strategy_name=self.strategy.name or self.strategy.__class__.__name__,
            start_date=self.daily_snapshots[0].date.strftime('%Y-%m-%d') if self.daily_snapshots else '',
            end_date=self.daily_snapshots[-1].date.strftime('%Y-%m-%d') if self.daily_snapshots else '',
            initial_capital=self.initial_capital,
            final_value=final_value,
            total_return=(final_value - self.initial_capital) / self.initial_capital,
            daily_snapshots=self.daily_snapshots,
            trades=self.trades,
            performance=performance,
            risk_report=risk_report,
        )

    def _calculate_performance(self) -> Dict[str, float]:
        """计算绩效指标"""
        if not self.daily_snapshots:
            return {}
        
        values = [s.total_value for s in self.daily_snapshots]
        returns = [s.daily_return for s in self.daily_snapshots]
        
        # 总收益率
        total_return = (values[-1] - values[0]) / values[0]
        
        # 年化收益率
        n_days = len(values)
        annual_return = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 else 0
        
        # 年化波动率
        annual_volatility = np.std(returns) * np.sqrt(252) if returns else 0
        
        # 夏普比率
        sharpe_ratio = annual_return / annual_volatility if annual_volatility > 0 else 0
        
        # 最大回撤
        max_drawdown = max(s.max_drawdown for s in self.daily_snapshots)
        
        # 胜率
        win_trades = [t for t in self.trades if t.action == 'close' and t.pnl > 0]
        total_close_trades = [t for t in self.trades if t.action == 'close']
        win_rate = len(win_trades) / len(total_close_trades) if total_close_trades else 0
        
        return {
            'total_return': total_return,
            'annual_return': annual_return,
            'annual_volatility': annual_volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'total_trades': len(self.trades),
            'win_trades': len(win_trades),
            'lose_trades': len(total_close_trades) - len(win_trades),
        }
