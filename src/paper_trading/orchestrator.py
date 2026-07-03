"""
模拟交易流程编排器（Paper Trading Orchestrator）

本文件实现 PaperTradingOrchestrator 类，负责多策略的每日模拟交易调度：
1. 自动发现并加载活跃策略（is_active=1）
2. 为每个策略构造 Context（持仓、资金、行情缓冲区）
3. 执行每日主流程：
   - 撮合昨日 Pending 订单（基于今日 open）
   - 调用 exit_checker 出场检查
   - 调用 on_bar 入场选股
   - 收盘结算并写净值快照

编排器只负责调度与数据准备，不参与策略信号决策。

用法:
    from src.paper_trading.orchestrator import PaperTradingOrchestrator
    orch = PaperTradingOrchestrator()
    orch.run_daily_process('2024-01-02')
"""

from typing import Dict, List, Optional, Any
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.data.database import DatabaseManager
from src.engine.base_strategy import StrategyRegistry
from src.engine.types import Order, Context, Direction
from .engine import PaperTradingEngine
from .config import PAPER_TRADING_CONFIG

logger = logging.getLogger(__name__)


def _get_db_path() -> str:
    """获取数据库路径（与 backtest_cli 保持一致）"""
    return str(Path(__file__).parent.parent.parent / 'data' / 'aquant.db')


class PaperTradingOrchestrator:
    """
    模拟交易流程编排器 - 多策略每日调度

    Parameters
    ----------
    db_path : str, optional
        数据库路径，默认为项目 data/aquant.db
    price_type : str
        撮合价格模式：'close'（当日收盘）或 'next_open'（次日开盘）
    warmup_days : int
        历史数据预热天数（用于策略 on_init 预计算指标）
    config : dict, optional
        费用参数覆盖
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        price_type: str = 'close',
        warmup_days: int = 365,
        config: Optional[Dict] = None,
    ):
        self.db_path = db_path or _get_db_path()
        self.db = DatabaseManager(self.db_path)
        self.price_type = price_type
        self.warmup_days = warmup_days
        self.config = {**PAPER_TRADING_CONFIG, **(config or {})}

        # 缓存：股票基本信息（ST/新股过滤用）
        self._stock_info_cache: Optional[pd.DataFrame] = None
        self._st_codes_cache: Optional[set] = None
        self._trade_dates_cache: Optional[List[str]] = None

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def run_daily_process(self, trade_date: str, strategy_name: str = None) -> None:
        """
        执行每日模拟交易流程。

        Parameters
        ----------
        trade_date : str
            交易日 (YYYY-MM-DD)
        strategy_name : str, optional
            只运行指定策略；None 时运行全部活跃策略
        """
        print(f"\n{'=' * 60}")
        print(f"[PaperTrading] 开始执行 {trade_date} 模拟交易")
        print(f"{'=' * 60}")

        # 1. 自动发现并加载活跃策略
        StrategyRegistry.auto_discover('src.strategies')

        # 2. 获取活跃策略列表
        active_strategies = self.db.get_active_strategies()
        if active_strategies.empty:
            print("[PaperTrading] 无活跃策略，请先注册策略并激活版本")
            return

        # 过滤指定策略
        if strategy_name:
            active_strategies = active_strategies[
                active_strategies['strategy_name'] == strategy_name
            ]
            if active_strategies.empty:
                print(f"[PaperTrading] 未找到活跃策略 '{strategy_name}'")
                return

        # 3. 预加载市场数据（全策略共用同一日的行情）
        market_data = self._load_market_data(trade_date)
        if market_data is None:
            print(f"[PaperTrading] {trade_date} 无行情数据，请先同步数据")
            return

        full_data, day_data_dict, day_close_prices, day_open_prices = market_data

        # 4. 预加载股票基本信息（ST/新股过滤）
        self._load_stock_info()

        # 5. 逐策略处理
        for _, strategy_row in active_strategies.iterrows():
            try:
                self._process_strategy(strategy_row, trade_date, full_data,
                                       day_data_dict, day_close_prices, day_open_prices)
            except Exception as e:
                logger.error(
                    f"[PaperTrading] 策略 {strategy_row['strategy_name']} 执行失败: {e}",
                    exc_info=True,
                )
                print(f"[PaperTrading] 策略 {strategy_row['strategy_name']} 执行失败: {e}")

        print(f"\n[PaperTrading] {trade_date} 模拟交易完成")

    def _process_strategy(
        self,
        strategy_row: pd.Series,
        trade_date: str,
        full_data: pd.DataFrame,
        day_data_dict: Dict[str, Dict],
        day_close_prices: Dict[str, float],
        day_open_prices: Dict[str, float],
    ) -> None:
        """处理单个策略的每日流程"""
        strategy_id = strategy_row['strategy_id']
        strategy_name = strategy_row['strategy_name']
        version = strategy_row['version']

        print(f"\n--- 策略: {strategy_name} ({version}) ---")

        # 1. 创建引擎并加载账户
        engine = PaperTradingEngine(
            db=self.db,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            version=version,
            config=self.config,
        )
        engine.load_or_init_account()

        # 2. 实例化策略
        strategy_class = StrategyRegistry.get(strategy_name)
        if strategy_class is None:
            print(f"[PaperTrading] 策略类 {strategy_name} 未注册，跳过")
            return

        # 构建策略参数：使用策略默认参数 + 数据库路径 + 模拟交易费用
        strategy_params = {
            'db_path': self.db_path,
            'commission_rate': self.config['commission_rate'],
            'slippage': 0.0,  # 模拟交易用实际成交价，不加滑点
        }
        strategy = strategy_class(**strategy_params)

        # 3. 构建上下文并调用 on_init
        context = Context(
            date=pd.Timestamp(trade_date),
            market_data=day_data_dict,
            full_data=full_data,
            positions=engine.positions,
            cash=engine.cash,
            frozen_cash=engine.frozen_cash,
            total_value=engine.total_value,
            params=strategy.params,
        )
        try:
            strategy.on_init(context)
        except Exception as e:
            logger.warning(f"[PaperTrading] 策略 {strategy_name} on_init 失败: {e}")
            # on_init 失败不阻断当日流程（可能策略无 on_init 预计算）

        # 4. 撮合昨日 Pending 订单（基于今日 open）
        self._fill_pending_orders(engine, trade_date, day_open_prices, day_data_dict)

        # 5. 出场检查（exit_checker）
        self._check_exits(engine, strategy, context, trade_date, day_data_dict, day_close_prices)

        # 6. 入场选股（on_bar）
        self._check_entries(engine, strategy, context, trade_date, day_data_dict, day_close_prices)

        # 7. 收盘结算
        engine.settle_daily(trade_date, day_close_prices)

    # ------------------------------------------------------------------
    # Pending 订单撮合
    # ------------------------------------------------------------------

    def _fill_pending_orders(
        self,
        engine: PaperTradingEngine,
        trade_date: str,
        day_open_prices: Dict[str, float],
        day_data_dict: Dict[str, Dict],
    ) -> None:
        """撮合昨日生成的 Pending（next_open）订单，用今日 open 价成交"""
        pending_orders = self.db.get_pending_orders(engine.strategy_id)
        if not pending_orders:
            return

        print(f"  撮合 {len(pending_orders)} 笔 Pending 订单")
        for order in pending_orders:
            stock_code = order['stock_code']
            open_price = day_open_prices.get(stock_code, 0.0)

            if open_price <= 0:
                # 今日停牌或无数据，订单保留 pending（等下一交易日）
                print(f"    {stock_code} 今日无开盘价，Pending 订单保留")
                continue

            # 卖单（direction='short'）：直接用 open 价卖出
            if order['direction'] == 'short':
                success = engine.execute_sell(
                    stock_code=stock_code,
                    quantity=order['quantity'],
                    price=open_price,
                    trade_date=trade_date,
                    reason=order.get('reason', ''),
                    order_id=order['order_id'],
                )
                if success:
                    self.db.update_paper_order_status(order['order_id'], 'filled')
                else:
                    self.db.update_paper_order_status(order['order_id'], 'rejected')

            # 买单（direction='long'）：需要解冻资金并按 open 价成交
            elif order['direction'] == 'long':
                # 重新计算冻结金额（按订单创建时的 close 价预估）
                # 简化：从 frozen_cash 中按比例解冻；此处用 open 价重新计算成本
                # 由于冻结时按 close 价计算，这里需要找回冻结金额
                # 方案：用 order 的 created_date 的 close 价重算冻结金额
                frozen_amount = self._calc_frozen_amount(order, day_data_dict)
                if frozen_amount <= 0:
                    self.db.update_paper_order_status(order['order_id'], 'rejected')
                    continue

                engine.execute_pending_buy(
                    order_id=order['order_id'],
                    stock_code=stock_code,
                    quantity=order['quantity'],
                    frozen_amount=frozen_amount,
                    open_price=open_price,
                    trade_date=trade_date,
                )

    def _calc_frozen_amount(self, order: Dict, day_data_dict: Dict[str, Dict]) -> float:
        """
        根据 pending 买单重新计算冻结金额。

        冻结时按 created_date 的 close 价计算：
        frozen = close_price * quantity * (1 + commission_rate + transfer_fee_rate)
        （佣金按比例计算，未应用最低5元，因为冻结时按预估成本）
        """
        price = day_data_dict.get(order['stock_code'], {}).get('close', 0.0)
        if price <= 0:
            return 0.0
        amount = price * order['quantity']
        commission = amount * self.config['commission_rate']
        transfer_fee = amount * self.config['transfer_fee_rate']
        return amount + commission + transfer_fee

    # ------------------------------------------------------------------
    # 出场检查
    # ------------------------------------------------------------------

    def _check_exits(
        self,
        engine: PaperTradingEngine,
        strategy,
        context: Context,
        trade_date: str,
        day_data_dict: Dict[str, Dict],
        day_close_prices: Dict[str, float],
    ) -> None:
        """调用策略 exit_checker，触发出场则生成卖出订单"""
        if not engine.positions:
            return

        exit_orders: List[Order] = []
        for stock_code, position in list(engine.positions.items()):
            try:
                result = strategy.exit_checker(context, position)
            except Exception as e:
                logger.warning(f"[PaperTrading] exit_checker 异常 {stock_code}: {e}")
                continue

            if result is not None and result.should_exit:
                if result.suggested_order is not None:
                    exit_orders.append(result.suggested_order)
                else:
                    # 自动生成反向平仓订单（与 backtest_engine 一致）
                    exit_direction = Direction.SHORT if position.direction == Direction.LONG else Direction.LONG
                    exit_orders.append(Order(
                        stock_code=stock_code,
                        direction=exit_direction,
                        quantity=position.quantity,
                        reason=result.reason,
                    ))

        if not exit_orders:
            return

        print(f"  出场检查: {len(exit_orders)} 笔卖出订单")
        for order in exit_orders:
            self._execute_exit_order(engine, order, trade_date, day_data_dict, day_close_prices)

    def _execute_exit_order(
        self,
        engine: PaperTradingEngine,
        order: Order,
        trade_date: str,
        day_data_dict: Dict[str, Dict],
        day_close_prices: Dict[str, float],
    ) -> None:
        """执行单笔卖出订单（close 立即成交 / next_open 登记pending）"""
        stock_code = order.stock_code
        if stock_code not in engine.positions:
            return

        # 市场过滤：跌停不可卖出
        md = day_data_dict.get(stock_code, {})
        close = md.get('close', 0.0)
        pre_close = md.get('pre_close', 0.0)
        if engine.is_limit_down(close, pre_close):
            print(f"    卖出拒绝 {stock_code}: 跌停")
            return

        if self.price_type == 'next_open':
            # 登记为 pending 卖单，次日开盘成交
            engine.add_pending_sell_order(
                stock_code=stock_code,
                quantity=order.quantity,
                trade_date=trade_date,
                reason=order.reason,
            )
        else:
            # close 模式：当日收盘价直接成交
            order_id = self.db.insert_paper_order({
                'strategy_id': engine.strategy_id,
                'stock_code': stock_code,
                'direction': 'short',
                'quantity': order.quantity,
                'price_type': 'close',
                'reason': order.reason,
                'status': 'pending',
                'created_date': trade_date,
            })
            success = engine.execute_sell(
                stock_code=stock_code,
                quantity=order.quantity,
                price=close,
                trade_date=trade_date,
                reason=order.reason,
                order_id=order_id,
            )
            self.db.update_paper_order_status(order_id, 'filled' if success else 'rejected')

    # ------------------------------------------------------------------
    # 入场选股
    # ------------------------------------------------------------------

    def _check_entries(
        self,
        engine: PaperTradingEngine,
        strategy,
        context: Context,
        trade_date: str,
        day_data_dict: Dict[str, Dict],
        day_close_prices: Dict[str, float],
    ) -> None:
        """调用策略 on_bar，生成买入订单并撮合"""
        try:
            orders = strategy.on_bar(context)
        except Exception as e:
            logger.error(f"[PaperTrading] on_bar 执行失败: {e}", exc_info=True)
            print(f"  on_bar 执行失败: {e}")
            return

        if not orders:
            return

        print(f"  入场选股: {len(orders)} 笔买入订单")
        for order in orders:
            self._execute_entry_order(engine, order, trade_date, day_data_dict, day_close_prices)

    def _execute_entry_order(
        self,
        engine: PaperTradingEngine,
        order: Order,
        trade_date: str,
        day_data_dict: Dict[str, Dict],
        day_close_prices: Dict[str, float],
    ) -> None:
        """执行单笔买入订单（含市场过滤）"""
        stock_code = order.stock_code

        # 已持仓则跳过（不支持加仓）
        if stock_code in engine.positions:
            return

        # 市场过滤：ST / 新股 / 涨跌停
        md = day_data_dict.get(stock_code, {})
        close = md.get('close', 0.0)
        pre_close = md.get('pre_close', 0.0)

        # ST 过滤
        if self._st_codes_cache and stock_code in self._st_codes_cache:
            print(f"    买入拒绝 {stock_code}: ST 股票")
            return

        # 新股过滤
        if self._is_new_stock(stock_code, trade_date):
            print(f"    买入拒绝 {stock_code}: 新股（上市未满 {self.config['new_stock_min_days']} 天）")
            return

        # 涨停过滤
        if engine.is_limit_up(close, pre_close):
            print(f"    买入拒绝 {stock_code}: 涨停")
            return

        if close <= 0:
            print(f"    买入拒绝 {stock_code}: 无有效收盘价")
            return

        if self.price_type == 'next_open':
            # 冻结资金，登记 pending 买单
            engine.freeze_for_buy(
                stock_code=stock_code,
                quantity=order.quantity,
                price=close,  # 按 close 价预估冻结金额
                trade_date=trade_date,
                reason=order.reason,
            )
        else:
            # close 模式：当日收盘价直接成交
            order_id = self.db.insert_paper_order({
                'strategy_id': engine.strategy_id,
                'stock_code': stock_code,
                'direction': 'long',
                'quantity': order.quantity,
                'price_type': 'close',
                'reason': order.reason,
                'status': 'pending',
                'created_date': trade_date,
            })
            success = engine.execute_buy(
                stock_code=stock_code,
                quantity=order.quantity,
                price=close,
                trade_date=trade_date,
                reason=order.reason,
                order_id=order_id,
            )
            self.db.update_paper_order_status(order_id, 'filled' if success else 'rejected')

    # ------------------------------------------------------------------
    # 市场数据加载
    # ------------------------------------------------------------------

    def _load_market_data(self, trade_date: str):
        """
        加载历史行情数据（含预热期）与当日数据。

        Returns
        -------
        tuple (full_data, day_data_dict, day_close_prices, day_open_prices) 或 None
            full_data: MultiIndex(trade_date, stock_code) DataFrame，用于 on_init
            day_data_dict: {stock_code: {open, close, ...}} 当日行情
            day_close_prices: {stock_code: close_price}
            day_open_prices: {stock_code: open_price}
        """
        # 计算预热期起始日期
        start_dt = pd.Timestamp(trade_date) - timedelta(days=self.warmup_days)
        start_date = start_dt.strftime('%Y-%m-%d')

        # 从数据库加载全市场日频数据
        full_data = self.db.get_stock_daily(
            stock_codes=None,
            start_date=start_date,
            end_date=trade_date,
        )
        if full_data is None or full_data.empty:
            return None

        # 提取当日数据
        try:
            day_data = full_data.xs(pd.Timestamp(trade_date), level='trade_date')
        except KeyError:
            # 当日无数据
            return None

        # 转为 {stock_code: {open, close, ...}} 字典
        day_data_dict = day_data.to_dict('index')

        # 提取收盘价和开盘价字典
        day_close_prices = {
            code: row.get('close', 0.0)
            for code, row in day_data_dict.items()
            if row.get('close', 0.0) > 0
        }
        day_open_prices = {
            code: row.get('open', 0.0)
            for code, row in day_data_dict.items()
            if row.get('open', 0.0) > 0
        }

        return full_data, day_data_dict, day_close_prices, day_open_prices

    # ------------------------------------------------------------------
    # 股票基本信息加载与过滤
    # ------------------------------------------------------------------

    def _load_stock_info(self) -> None:
        """加载股票基本信息（带缓存），用于 ST 与新股过滤"""
        if self._stock_info_cache is not None:
            return

        try:
            self._stock_info_cache = self.db.get_stock_info_filtered()
        except Exception:
            self._stock_info_cache = pd.DataFrame()

        # 预计算 ST 股票集合
        self._st_codes_cache = set()
        if self._stock_info_cache is not None and not self._stock_info_cache.empty:
            for _, row in self._stock_info_cache.iterrows():
                name = str(row.get('stock_name', ''))
                if 'ST' in name.upper() or '退' in name:
                    self._st_codes_cache.add(row['stock_code'])

    def _is_new_stock(self, stock_code: str, trade_date: str) -> bool:
        """判断是否为新股（上市未满 new_stock_min_days 个交易日）"""
        min_days = self.config['new_stock_min_days']
        if min_days <= 0 or self._stock_info_cache is None or self._stock_info_cache.empty:
            return False

        # 查找该股票的上市日期
        match = self._stock_info_cache[self._stock_info_cache['stock_code'] == stock_code]
        if match.empty:
            return False

        list_date = match.iloc[0].get('list_date')
        if pd.isna(list_date) or list_date is None:
            return False

        try:
            list_date_str = pd.Timestamp(list_date).strftime('%Y-%m-%d')
        except Exception:
            return False

        # 加载交易日历（带缓存）
        if self._trade_dates_cache is None:
            try:
                self._trade_dates_cache = self.db.get_trade_dates(list_date_str, trade_date)
            except Exception:
                self._trade_dates_cache = []

        # 上市日至 trade_date 之间的交易日数
        trade_days = [d for d in self._trade_dates_cache if list_date_str <= d <= trade_date]
        return len(trade_days) < min_days
