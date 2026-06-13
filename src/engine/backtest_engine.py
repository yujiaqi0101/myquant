"""
通用回测引擎 - 核心引擎

支持所有策略在同一框架下运行，提供：
- 逐日事件循环
- 策略层出场检查（通过 strategy.exit_checker）
- 风控集成
- 完整的每日账户记录（支持逐日检查）

=========================================================================
DEPRECATED — 此引擎自 Phase 4 起标记为 deprecated
-------------------------------------------------------------------------
新项目请使用：
    from src.quantlab.engine import BarEngine
    from src.quantlab_adapters import (
        to_quantlab_dict,
        build_ashare_risk_manager,
        build_ashare_execution,
    )

新策略请继承 SignalStrategy：
    from src.quantlab.signals.base import SignalStrategy

迁移指南见 docs/quantlab_integration_guide.md（Phase 7 撰写）。
本引擎保留运行用于：
    1) Phase 2 的策略等价性测试（v1 vs v2 行为对比）
    2) 6 个 v1 策略的旧 CLI 调用
    3) 渐进式迁移的过渡期
=========================================================================
"""

import warnings

from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

from .types import (
    Order, TradeRecord, Position, DailySnapshot,
    BacktestResult, Context, Direction
)


# -------------------------------------------------------------------------
# 触发 DeprecationWarning（模块导入时）
# -------------------------------------------------------------------------
warnings.warn(
    "src.engine.backtest_engine.BacktestEngine 已废弃（Phase 4），"
    "请迁移到 src.quantlab.engine.BarEngine + SignalStrategy。"
    "本引擎仅保留用于 v1 策略与等价性测试。",
    DeprecationWarning,
    stacklevel=2,
)


class BacktestEngine:
    """
    通用回测引擎 - 统一框架
    
    支持所有策略在同一框架下运行，提供：
    - 逐日事件循环
    - 策略层出场检查（通过 strategy.exit_checker）
    - 风控集成
    - 完整的每日账户记录（支持逐日检查）
    
    Parameters
    ----------
    strategy : BaseStrategy
        策略实例
    initial_capital : float
        初始资金
    risk_controller : RiskController, optional
        风控控制器
    """

    def __init__(
        self,
        strategy: 'BaseStrategy',
        initial_capital: float = 1_000_000,
        risk_controller: Any = None,
        execution_price: str = 'close',
        market_filter: Dict[str, Any] = None,
        stock_info_provider: Any = None,
    ):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.risk_controller = risk_controller
        self.execution_price = execution_price  # 'close' 或 'next_open'

        # 市场过滤配置
        self.market_filter = market_filter or {}

        # 股票信息提供者（新增，用于解耦数据源）
        self._stock_info_provider = stock_info_provider

        # 从策略参数获取交易成本
        self.commission_rate = strategy.params.get('commission_rate', 0.0003)
        self.slippage = strategy.params.get('slippage', 0.0001)

        # 运行时状态
        self.cash = initial_capital
        self.frozen_cash = 0.0
        self.positions: Dict[str, Position] = {}
        self.trades: List[TradeRecord] = []
        self.daily_snapshots: List[DailySnapshot] = []
        self.peak_value = initial_capital
        self._trades_by_date: Dict[pd.Timestamp, List[TradeRecord]] = {}  # 按日期索引交易记录
        
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
        
        # 预计算ATR（用于ATR动态止盈）
        atr_window = self.strategy.params.get('atr_window', 14)
        self._atr_data = self._precompute_atr(full_data, atr_window)
        
        # 预分割数据：按日期建立索引字典，避免每日 xs() 调用
        self._daily_data_dict = {}
        for date in trade_dates:
            try:
                self._daily_data_dict[date] = price_data.xs(date, level='trade_date')
            except KeyError:
                self._daily_data_dict[date] = pd.DataFrame()
        
        # 预计算市场过滤结果（避免每日重复计算）
        self._precompute_market_filters(trade_dates)
        
        # 逐日事件循环
        for i, date in enumerate(trade_dates):
            context.date = date
            
            # 准备当日数据（使用预分割数据，避免 xs() 调用）
            day_data = self._daily_data_dict.get(date, pd.DataFrame())
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
            
            # 更新持仓最高价（用于ATR动态止盈）
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
            
            # ---- 阶段1：策略层出场检查 ----
            exit_orders = []
            for stock_code, position in list(self.positions.items()):
                result = self.strategy.exit_checker(context, position)
                if result is not None and result.should_exit:
                    # 策略触发出场
                    if result.suggested_order:
                        exit_orders.append(result.suggested_order)
                    else:
                        # 自动生成出场订单（方向与持仓相反 = 平仓）
                        exit_direction = Direction.SHORT if position.direction == Direction.LONG else Direction.LONG
                        exit_orders.append(Order(
                            stock_code=stock_code,
                            direction=exit_direction,
                            quantity=position.quantity,
                            reason=result.reason
                        ))
            
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
        """计算持仓市值（向量化实现）"""
        if not self.positions or day_data.empty:
            return 0.0
        
        # 提取持仓股票代码
        held_codes = [code for code in self.positions if code in day_data.index]
        if not held_codes:
            return 0.0
        
        # 向量化获取价格和数量
        prices = day_data.loc[held_codes, 'close'].values
        quantities = np.array([self.positions[code].quantity for code in held_codes])
        
        # 过滤无效价格
        valid_mask = prices > 0
        return float(np.sum(prices[valid_mask] * quantities[valid_mask]))

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
                tradable = day_data.loc[order.stock_code, 'tradable'] if 'tradable' in day_data.columns else True
            else:
                return
        except:
            return
        
        if price <= 0:
            return
        
        # 检查是否可交易（涨停不可买入）
        if not tradable:
            logger.debug(f"{date} 买入被拒绝: {order.stock_code} 涨停/跌停，无法交易")
            self.strategy.on_order_rejected(
                Context(date=date), order, "涨跌停不可交易"
            )
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
        # 按日期索引交易记录
        if date not in self._trades_by_date:
            self._trades_by_date[date] = []
        self._trades_by_date[date].append(trade)
        
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
                tradable = day_data.loc[order.stock_code, 'tradable'] if 'tradable' in day_data.columns else True
            else:
                return
        except:
            return
        
        if price <= 0:
            return
        
        # 检查是否可交易（跌停不可卖出）
        if not tradable:
            logger.debug(f"{date} 卖出被拒绝: {order.stock_code} 涨停/跌停，无法交易")
            self.strategy.on_order_rejected(
                Context(date=date), order, "涨跌停不可交易"
            )
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
        # 按日期索引交易记录
        if date not in self._trades_by_date:
            self._trades_by_date[date] = []
        self._trades_by_date[date].append(trade)
        
        # 回调
        self.strategy.on_order_filled(Context(date=date), trade)

    def _precompute_market_filters(self, trade_dates: list):
        """
        一次性预计算所有交易日的市场过滤结果
        
        将 ST、新股、涨跌停等过滤规则一次性计算好，
        在逐日循环中直接查表使用，避免每日重复计算。
        使用预分割的 _daily_data_dict 避免重复 xs()。
        """
        self._filter_cache = {}  # {date_str: set_of_removed_codes}
        self._tradable_cache = {}  # {date_str: {stock_code: bool}}
        
        if not self.market_filter:
            # 无过滤规则，所有股票都可交易
            for date in trade_dates:
                date_str = date.strftime('%Y-%m-%d')
                self._filter_cache[date_str] = set()
                self._tradable_cache[date_str] = {}
            return
        
        # 预加载 ST 股票集合（静态，只需加载一次）
        st_codes = self._get_st_filtered_codes() if self.market_filter.get('exclude_st', False) else set()
        
        # 预加载股票基本信息（用于新股过滤）
        min_days = self.market_filter.get('exclude_new_stock', 0)
        stock_info = self._load_stock_info() if min_days > 0 else None
        
        # 预加载交易日历（用于新股过滤的二分查找）
        if min_days > 0 and stock_info is not None and not stock_info.empty:
            list_dates = stock_info['list_date'].dropna().tolist()
            if list_dates:
                min_list_dt = min(str(d) for d in list_dates)
                last_trade_dt = trade_dates[-1].strftime('%Y-%m-%d')
                if self._trade_dates_cache is None:
                    if self._stock_info_provider is not None:
                        self._trade_dates_cache = self._stock_info_provider.get_trade_dates(min_list_dt, last_trade_dt)
                    else:
                        db_path = self.strategy.params.get('db_path')
                        if db_path:
                            from src.data.database import DatabaseManager
                            db = DatabaseManager(db_path)
                            self._trade_dates_cache = db.get_trade_dates(min_list_dt, last_trade_dt)
        
        import bisect
        all_trade_dates = self._trade_dates_cache or []
        
        # 预计算新股过滤：一次性算出每只股票的"可交易起始日期"
        # 避免对每个交易日都遍历所有股票
        new_stock_codes_by_date = {}
        if min_days > 0 and stock_info is not None and not stock_info.empty and all_trade_dates:
            trade_date_list = sorted(all_trade_dates)
            last_trade_dt = trade_dates[-1].strftime('%Y-%m-%d')
            
            # 一次性计算每只股票的可交易起始日期
            stock_tradeable_from = {}  # {stock_code: trade_date_str when it becomes tradeable}
            for _, row in stock_info.iterrows():
                list_date = row.get('list_date')
                if pd.notna(list_date) and list_date:
                    try:
                        list_dt = pd.Timestamp(list_date).strftime('%Y-%m-%d')
                        idx = bisect.bisect_left(trade_date_list, list_dt)
                        if idx + min_days - 1 < len(trade_date_list):
                            stock_tradeable_from[row['stock_code']] = trade_date_list[idx + min_days - 1]
                        else:
                            stock_tradeable_from[row['stock_code']] = '9999-12-31'
                    except Exception:
                        pass
            
            # 按日期构建新股集合
            if stock_tradeable_from:
                # 找出在回测期内有过"新股"阶段的股票
                # 即可交易起始日期 > 回测开始日期的股票
                first_trade_dt = trade_dates[0].strftime('%Y-%m-%d')
                new_stock_candidates = {code: start_dt for code, start_dt in stock_tradeable_from.items() 
                                       if start_dt > first_trade_dt}
                
                if new_stock_candidates:
                    for date in trade_dates:
                        trade_dt = date.strftime('%Y-%m-%d')
                        # 当日仍是新股 = 可交易起始日期 > 当日
                        new_codes = {code for code, start_dt in new_stock_candidates.items() 
                                     if start_dt > trade_dt}
                        if new_codes:
                            new_stock_codes_by_date[trade_dt] = new_codes
        
        # 逐日预计算过滤结果
        for date in trade_dates:
            date_str = date.strftime('%Y-%m-%d')
            removed_codes = set()
            
            try:
                day_data = self._daily_data_dict.get(date, pd.DataFrame())
            except (KeyError, AttributeError):
                self._filter_cache[date_str] = set()
                self._tradable_cache[date_str] = {}
                continue
            
            if day_data.empty:
                self._filter_cache[date_str] = set()
                self._tradable_cache[date_str] = {}
                continue
            
            stock_codes_in_data = set(day_data.index)
            
            # 1. ST 过滤
            if st_codes:
                removed_codes |= (st_codes & stock_codes_in_data)
            
            # 2. 新股过滤
            if date_str in new_stock_codes_by_date:
                removed_codes |= (new_stock_codes_by_date[date_str] & stock_codes_in_data)
            
            # 3. 停牌过滤
            if self.market_filter.get('exclude_suspend', False) and 'suspend_flag' in day_data.columns:
                suspend_codes = set(day_data[day_data['suspend_flag'] != 0].index)
                removed_codes |= suspend_codes
            
            # 4. 零成交量过滤
            if self.market_filter.get('exclude_zero_vol', False) and 'volume' in day_data.columns:
                zero_vol_codes = set(day_data[day_data['volume'] <= 0].index)
                removed_codes |= zero_vol_codes
            
            self._filter_cache[date_str] = removed_codes
            
            # 5. 涨跌停标记（只对未被移除的股票标记）
            tradable_map = {}
            if self.market_filter.get('exclude_limit', False) and 'pre_close' in day_data.columns:
                remaining = day_data.index.difference(removed_codes)
                if not remaining.empty:
                    sub = day_data.loc[remaining]
                    pre_close = sub['pre_close']
                    valid_pre = pre_close.notna() & (pre_close > 0)
                    limit_up = (sub['close'] >= pre_close * 1.095) & valid_pre
                    limit_down = (sub['close'] <= pre_close * 0.905) & valid_pre
                    for code in remaining:
                        tradable_map[code] = bool(not (limit_up.get(code, False) or limit_down.get(code, False)))
            self._tradable_cache[date_str] = tradable_map
    
    def _apply_market_filter(self, day_data: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
        """
        对当日市场数据应用过滤规则 - 使用预计算结果
        
        ST/次新/停牌/零成交量：直接从 market_data 中移除（不可交易也不可见）
        涨跌停：保留在 market_data 中（策略可见），但标记 tradable=False（不可买入/卖出）
        """
        if not self.market_filter or day_data.empty:
            return day_data
        
        date_str = date.strftime('%Y-%m-%d')
        
        # 使用预计算的过滤结果
        removed_codes = self._filter_cache.get(date_str, set())
        if removed_codes:
            day_data = day_data[~day_data.index.isin(removed_codes)]
        
        # 使用预计算的涨跌停标记
        tradable_map = self._tradable_cache.get(date_str, {})
        if tradable_map or self.market_filter.get('exclude_limit', False):
            day_data = day_data.copy()
            if tradable_map:
                day_data['tradable'] = day_data.index.map(lambda c: tradable_map.get(c, True))
            else:
                day_data['tradable'] = True
        
        return day_data
    
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
            
            # 加载交易日历（带缓存，只查一次）
            if self._trade_dates_cache is None:
                # 优先使用注入的 StockInfoProvider（新增，用于解耦数据源）
                if self._stock_info_provider is not None:
                    self._trade_dates_cache = self._stock_info_provider.get_trade_dates(min_list_dt, trade_dt)
                else:
                    # 兼容旧逻辑：从数据库获取
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
        预计算ATR（Average True Range）- 向量化实现
        
        使用 groupby + 向量化运算替代双重循环，性能提升约50-100倍。
        
        返回: {date_str: {stock_code: atr_value}}
        """
        if data is None or data.empty:
            return None
        
        try:
            # 确保索引有序
            data_sorted = data.sort_index()
            
            # 向量化计算 True Range（所有股票同时计算）
            prev_close = data_sorted.groupby(level='stock_code')['close'].shift(1)
            high = data_sorted['high']
            low = data_sorted['low']
            
            tr = np.maximum(
                high - low,
                np.maximum(
                    np.abs(high - prev_close),
                    np.abs(low - prev_close)
                )
            )
            
            # 向量化计算 ATR（按股票分组做 EMA）
            atr = tr.groupby(data_sorted.index.get_level_values('stock_code')).transform(
                lambda x: x.ewm(span=window, adjust=False).mean()
            )
            
            # 构建 {date_str: {stock_code: atr_value}} 格式（兼容现有调用方式）
            atr_series = pd.Series(atr.values, index=data_sorted.index, name='atr')
            
            # 按日期分组，快速构建嵌套字典
            dates = atr_series.index.get_level_values('trade_date')
            stocks = atr_series.index.get_level_values('stock_code')
            
            atr_data = {}
            # 使用 groupby 按日期聚合，避免逐行循环
            for date_val, group in atr_series.groupby(level='trade_date'):
                date_str = date_val.strftime('%Y-%m-%d') if hasattr(date_val, 'strftime') else str(date_val)
                stock_indices = group.index.get_level_values('stock_code')
                atr_data[date_str] = dict(zip(stock_indices, group.values))
            
            return atr_data
        except Exception:
            return None
    
    def _load_stock_info(self) -> Optional[pd.DataFrame]:
        """加载股票基本信息（带缓存）"""
        if self._stock_info_cache is not None:
            return self._stock_info_cache

        try:
            # 优先使用注入的 StockInfoProvider（新增，用于解耦数据源）
            if self._stock_info_provider is not None:
                self._stock_info_cache = self._stock_info_provider.get_stock_info_filtered()
                return self._stock_info_cache

            # 兼容旧逻辑：从 strategy.params 获取 db_path
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
        
        # 使用按日期索引的交易记录（O(1) 查找，替代遍历全部交易）
        daily_trades = self._trades_by_date.get(date, [])
        
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
