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
        execution_price: str = 'close',
        market_filter: Dict[str, Any] = None,
    ):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.enable_engine_exit = enable_engine_exit
        self.risk_controller = risk_controller
        self.execution_price = execution_price  # 'close' 或 'next_open'
        
        # 市场过滤配置
        self.market_filter = market_filter or {}
        
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
        
        # 延迟执行订单队列（用于次日开盘执行）
        self._pending_orders: List[Order] = []
        
        # ST/新股过滤缓存（静态数据，只需加载一次）
        self._stock_info_cache: Optional[pd.DataFrame] = None
        self._st_filtered_codes: Optional[set] = None
        self._trade_dates_cache: Optional[List[str]] = None  # 交易日历缓存

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
        import time as _time
        _t0 = _time.time()
        self.strategy.on_init(context)
        print(f"  策略初始化耗时: {_time.time()-_t0:.1f}s")
        self.strategy.on_start(context)
        
        # 预计算ATR（用于ATR跟踪止盈）
        atr_window = self.strategy.params.get('atr_window', 14)
        self._atr_data = self._precompute_atr(full_data, atr_window)
        
        # 逐日事件循环
        for i, date in enumerate(trade_dates):
            context.date = date
            
            # 准备当日数据
            day_data = price_data.xs(date, level='trade_date')
            day_data_raw = day_data  # 保存原始数据（用于计算持仓市值）
            
            # ---- 市场过滤 ----
            day_data = self._apply_market_filter(day_data, date)
            
            context.market_data = day_data.to_dict('index') if not day_data.empty else {}
            
            # 添加当日ATR到market_data
            date_str = date.strftime('%Y-%m-%d')
            if self._atr_data is not None and date_str in self._atr_data:
                for stock_code, atr in self._atr_data[date_str].items():
                    if stock_code in context.market_data:
                        context.market_data[stock_code]['atr'] = atr
            
            # 更新账户状态（用原始数据计算持仓市值，不受涨跌停过滤影响）
            position_value = self._calc_position_value(day_data_raw)
            context.cash = self.cash
            context.frozen_cash = self.frozen_cash
            context.total_value = self.cash + self.frozen_cash + position_value
            
            # 更新持仓最高价（用于ATR跟踪止盈）
            for stock_code, position in self.positions.items():
                if stock_code in context.market_data:
                    high = context.market_data[stock_code].get('high', 0)
                    if high > 0 and high > position.highest_price:
                        position.highest_price = high
            
            # 更新峰值和回撤
            if context.total_value > self.peak_value:
                self.peak_value = context.total_value
            drawdown = (self.peak_value - context.total_value) / self.peak_value
            
            # ---- 阶段0：执行前一日延迟的订单（次日开盘执行）----
            if self.execution_price == 'next_open' and self._pending_orders:
                for order in self._pending_orders:
                    if order.stock_code in self.positions:
                        # 出场订单
                        self._execute_exit(order, day_data, date, use_open_price=True)
                    else:
                        # 入场订单
                        self._execute_entry(order, day_data, date, use_open_price=True)
                self._pending_orders = []
            
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
            
            # 执行出场订单（立即执行）
            for order in exit_orders:
                self._execute_exit(order, day_data, date)
            
            # ---- 阶段3：调用策略生成订单 ----
            orders = self.strategy.on_bar(context)
            
            # ---- 阶段4：执行策略订单 ----
            for order in orders:
                # 判断是入场还是出场
                if order.stock_code in self.positions:
                    position = self.positions[order.stock_code]
                    # 如果订单方向与持仓方向相反，则是平仓
                    if order.direction != position.direction:
                        self._execute_exit(order, day_data, date)
                    else:
                        # 同方向，可能是加仓（暂不支持）
                        pass
                else:
                    # 无持仓，是开仓
                    if self.execution_price == 'next_open':
                        # 延迟到次日开盘执行
                        self._pending_orders.append(order)
                    else:
                        # 立即执行（收盘价）
                        self._execute_entry(order, day_data, date)
            
            # ---- 阶段5：记录每日快照 ----
            self._record_snapshot(date, day_data_raw, drawdown)
            
            # 进度输出（每100天）
            if (i + 1) % 100 == 0 or i == len(trade_dates) - 1:
                print(f"  回测进度: {date.strftime('%Y-%m-%d')} ({i+1}/{len(trade_dates)})")
        
        # 回测结束
        self.strategy.on_stop(context)
        
        return self._build_result()

    def _calc_position_value(self, day_data: pd.DataFrame) -> float:
        """计算持仓市值"""
        total = 0.0
        for stock_code, position in self.positions.items():
            try:
                if stock_code in day_data.index:
                    price = day_data.loc[stock_code, 'close']
                    if price > 0:
                        total += position.quantity * price
            except:
                continue
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

    def _execute_entry(self, order: Order, day_data: pd.DataFrame, date: pd.Timestamp, use_open_price: bool = False):
        """执行入场订单"""
        # 检查是否已有持仓
        if order.stock_code in self.positions:
            return
        
        # 获取价格 - day_data 是 DataFrame，需要用 loc 或 iloc 访问
        price_col = 'open' if use_open_price else 'close'
        try:
            if order.stock_code in day_data.index:
                price = day_data.loc[order.stock_code, price_col]
            else:
                return
        except:
            return
        
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
            highest_price=price,  # 初始化为入场价
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

    def _execute_exit(self, order: Order, day_data: pd.DataFrame, date: pd.Timestamp, use_open_price: bool = False):
        """执行出场订单"""
        if order.stock_code not in self.positions:
            return
        
        position = self.positions[order.stock_code]
        
        # 获取价格
        price_col = 'open' if use_open_price else 'close'
        try:
            if order.stock_code in day_data.index:
                price = day_data.loc[order.stock_code, price_col]
            else:
                return
        except:
            return
        
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

    def _apply_market_filter(self, day_data: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
        """
        对当日市场数据应用过滤规则
        
        只检查 day_data 中实际存在的股票，而非全市场扫描。
        """
        if not self.market_filter or day_data.empty:
            return day_data
        
        mask = pd.Series(True, index=day_data.index)
        stock_codes_in_data = set(day_data.index)
        
        # 1. 排除ST（只检查当天在 day_data 中的股票）
        if self.market_filter.get('exclude_st', False):
            st_codes = self._get_st_filtered_codes()
            if st_codes is not None:
                mask &= ~day_data.index.isin(st_codes & stock_codes_in_data)
        
        # 2. 排除上市不满N个交易日（只检查当天在 day_data 中的股票）
        min_days = self.market_filter.get('exclude_new_stock', 0)
        if min_days > 0:
            new_stock_codes = self._get_new_stock_filtered_codes(date, min_days, stock_codes_in_data)
            if new_stock_codes is not None:
                mask &= ~day_data.index.isin(new_stock_codes)
        
        # 3. 排除涨跌停
        if self.market_filter.get('exclude_limit', False):
            if 'pre_close' in day_data.columns:
                pre_close = day_data['pre_close']
                valid_pre = pre_close.notna() & (pre_close > 0)
                mask &= ~((day_data['close'] >= pre_close * 1.095) & valid_pre)
                mask &= ~((day_data['close'] <= pre_close * 0.905) & valid_pre)
        
        # 4. 排除停牌
        if self.market_filter.get('exclude_suspend', False):
            if 'suspend_flag' in day_data.columns:
                mask &= (day_data['suspend_flag'] == 0)
        
        # 5. 排除零成交量
        if self.market_filter.get('exclude_zero_vol', False):
            if 'volume' in day_data.columns:
                mask &= (day_data['volume'] > 0)
        
        return day_data[mask]
    
    def _get_st_filtered_codes(self) -> Optional[set]:
        """获取ST股票代码集合（带缓存）"""
        if self._st_filtered_codes is not None:
            return self._st_filtered_codes
        
        try:
            stock_info = self._load_stock_info()
            if stock_info is None or stock_info.empty:
                self._st_filtered_codes = set()
                return self._st_filtered_codes
            
            st_codes = set()
            for _, row in stock_info.iterrows():
                name = str(row.get('stock_name', ''))
                if 'ST' in name.upper():
                    st_codes.add(row['stock_code'])
            
            self._st_filtered_codes = st_codes
            return st_codes
        except Exception:
            self._st_filtered_codes = set()
            return self._st_filtered_codes
    
    def _get_new_stock_filtered_codes(self, date: pd.Timestamp, min_days: int, check_codes: set = None) -> Optional[set]:
        """获取上市交易日不满N天的股票代码集合（只检查指定股票）"""
        try:
            stock_info = self._load_stock_info()
            if stock_info is None or stock_info.empty:
                return set()
            
            # 只检查需要判断的股票（而非全市场）
            if check_codes:
                stock_info = stock_info[stock_info['stock_code'].isin(check_codes)]
            
            if stock_info.empty:
                return set()
            
            trade_dt = date.strftime('%Y-%m-%d')
            
            # 获取需要检查的股票中最早的上市日期
            list_dates = stock_info['list_date'].dropna().tolist()
            if not list_dates:
                return set()
            
            min_list_dt = min(str(d) for d in list_dates)
            
            # 加载交易日历（带缓存，只查一次数据库）
            if self._trade_dates_cache is None:
                db_path = self.strategy.params.get('db_path')
                if not db_path:
                    return set()
                from src.data.database import DatabaseManager
                db = DatabaseManager(db_path)
                self._trade_dates_cache = db.get_trade_dates(min_list_dt, trade_dt)
            
            all_trade_dates = self._trade_dates_cache
            
            # 用二分查找计算交易日数量
            import bisect
            new_codes = set()
            for _, row in stock_info.iterrows():
                list_date = row.get('list_date')
                if pd.notna(list_date) and list_date:
                    try:
                        list_dt = pd.Timestamp(list_date).strftime('%Y-%m-%d')
                        if list_dt >= min_list_dt:
                            idx = bisect.bisect_left(all_trade_dates, list_dt)
                            trade_days = len(all_trade_dates) - idx
                            if trade_days < min_days:
                                new_codes.add(row['stock_code'])
                    except Exception:
                        pass
            
            return new_codes
        except Exception:
            return set()
    
    def _precompute_atr(self, data: pd.DataFrame, window: int = 14) -> Optional[Dict[str, Dict[str, float]]]:
        """
        预计算ATR（Average True Range）
        
        返回: {date_str: {stock_code: atr_value}}
        """
        if data is None or data.empty:
            return None
        
        try:
            atr_data = {}
            
            # 获取所有股票代码
            try:
                stock_codes = data.index.get_level_values('stock_code').unique()
            except:
                return None
            
            for stock_code in stock_codes:
                try:
                    # 获取单只股票数据
                    stock_data = data.xs(stock_code, level='stock_code').copy()
                    
                    # 计算True Range
                    stock_data['prev_close'] = stock_data['close'].shift(1)
                    stock_data['tr'] = np.maximum(
                        stock_data['high'] - stock_data['low'],
                        np.maximum(
                            abs(stock_data['high'] - stock_data['prev_close']),
                            abs(stock_data['low'] - stock_data['prev_close'])
                        )
                    )
                    
                    # 计算ATR（指数移动平均）
                    stock_data['atr'] = stock_data['tr'].ewm(span=window, adjust=False).mean()
                    
                    # 存入结果
                    for date, row in stock_data.iterrows():
                        date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)
                        if date_str not in atr_data:
                            atr_data[date_str] = {}
                        atr_data[date_str][stock_code] = row['atr']
                        
                except Exception:
                    continue
            
            return atr_data
        except Exception:
            return None
    
    def _load_stock_info(self) -> Optional[pd.DataFrame]:
        """加载股票基本信息（带缓存）"""
        if self._stock_info_cache is not None:
            return self._stock_info_cache
        
        try:
            # 从 full_data 的 context 中获取数据库路径
            # 通过 strategy 的 params 传入 db_path
            db_path = self.strategy.params.get('db_path')
            if not db_path:
                self._stock_info_cache = pd.DataFrame()
                return self._stock_info_cache
            
            from src.data.database import DatabaseManager
            db = DatabaseManager(db_path)
            self._stock_info_cache = db.get_stock_info_filtered()
            return self._stock_info_cache
        except Exception:
            self._stock_info_cache = pd.DataFrame()
            return self._stock_info_cache

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
