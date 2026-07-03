"""
src/core/engine/backtest.py
===========================

BacktestEngine 回测引擎 + BacktestContext 策略上下文。

回测引擎是事件驱动内核的同步实现，组装各组件完成历史数据回测：
    HistoricalDataFeed → EventEngine(同步) → Strategy → RiskManager → SimulatedExecution → Portfolio

生命周期（设计文档 7.2 节）：
    1. 启动 DataFeed（加载历史K线到内存）
    2. 策略 on_init（订阅数据、设置定时器、预计算）
    3. 事件循环（逐日推进）：
       a. T+1 结算（settle_new_day）
       b. Pending 订单开盘撮合（process_pending_orders）
       c. 检查定时器并推送 TimerEvent
       d. 推送 BarEvent → 策略决策 → submit_order → 风控 → 撮合
       e. 更新市价（update_market_prices）
       f. 净值快照（snapshot）
    4. 推送 StopEvent，策略 on_stop
    5. 计算 22 项绩效指标，返回 BacktestResult

BacktestContext 实现 Context 抽象基类，策略通过 context 与引擎交互：
    - 数据访问：委托 DataFeed
    - 订单操作：构造 Order → RiskManager 检查 → Execution 撮合
    - 持仓/账户查询：委托 Portfolio（返回 dict，符合 Context 契约）
    - 定时器：委托引擎定时器管理
    - 时间查询：返回当前 BarEvent 时间戳

用法示例：
    from src.core.engine import BacktestEngine
    engine = BacktestEngine(
        strategy=SmallCapStrategy(params={"top_n": 5}),
        db=db,
        start_date="2024-01-01",
        end_date="2024-06-30",
        initial_capital=1_000_000,
    )
    result = engine.run()
    print(result.to_summary())
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from src.core.context import Context
from src.core.datafeed.historical import HistoricalDataFeed
from src.core.event_engine import EventEngine
from src.core.events import (
    AccountEvent,
    BarEvent,
    Event,
    EventType,
    InitEvent,
    OrderEvent,
    StopEvent,
    TimerEvent,
)
from src.core.execution.simulated import SimulatedExecution
from src.core.portfolio import AccountInfo, Portfolio
from src.core.result import (
    BacktestResult,
    BenchmarkProvider,
    PerformanceCalculator,
)
from src.core.risk.manager import RiskManager
from src.core.strategy import Strategy
from src.core.types import Direction, Order, OrderStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BacktestContext：回测策略上下文
# ---------------------------------------------------------------------------


class BacktestContext(Context):
    """回测策略上下文。

    实现 Context 抽象基类，将策略请求委托给引擎各组件：
        - 数据访问 → HistoricalDataFeed
        - 订单操作 → RiskManager + SimulatedExecution
        - 持仓/账户 → Portfolio（转换为 dict 返回，符合 Context 契约）
        - 定时器 → 引擎定时器管理器
        - 时间 → 当前 BarEvent 时间戳

    策略通过本上下文不感知运行模式，同一份代码可切换到模拟盘/实盘。

    Parameters
    ----------
    engine : BacktestEngine
        所属引擎实例（访问 datafeed/execution/portfolio/risk_manager/timers）
    """

    def __init__(self, engine: "BacktestEngine") -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # 1. 数据访问
    # ------------------------------------------------------------------

    def subscribe(self, symbols: Union[str, List[str]]) -> None:
        """订阅标的行情，委托给 HistoricalDataFeed。"""
        if isinstance(symbols, str):
            symbols = [symbols]
        self._engine.datafeed.subscribe(symbols)

    def history(
        self,
        symbol: str,
        fields: Union[str, List[str]] = "close",
        count: int = 100,
    ) -> Any:
        """查询单标的的历史K线，委托给 HistoricalDataFeed。"""
        # Context 契约：fields 可以是 str 或 list，统一转 list 给 DataFeed
        if isinstance(fields, str):
            fields_list: Optional[List[str]] = [fields]
        else:
            fields_list = list(fields) if fields else None
        df = self._engine.datafeed.history(symbol, fields_list, count)
        # 单字段时返回 List[float]（按 Context 契约）
        if isinstance(fields, str) and not df.empty and fields in df.columns:
            return df[fields].tolist()
        return df

    def history_multi(
        self,
        symbols: List[str],
        fields: Union[str, List[str]] = "close",
        count: int = 100,
    ) -> Any:
        """批量查询多标的历史K线。"""
        if isinstance(fields, str):
            fields_list: Optional[List[str]] = [fields]
        else:
            fields_list = list(fields) if fields else None
        return self._engine.datafeed.history_multi(symbols, fields_list, count)

    def get_subscribed_symbols(self) -> List[str]:
        """获取已订阅标的列表。"""
        return list(self._engine.datafeed._symbols)

    # ------------------------------------------------------------------
    # 2. 订单操作
    # ------------------------------------------------------------------

    def submit_order(
        self,
        symbol: str,
        direction: str,
        volume: Optional[float] = None,
        target_weight: Optional[float] = None,
        price_type: str = "market",
        price: Optional[float] = None,
        order_id: Optional[str] = None,
    ) -> str:
        """提交订单：构造 Order → 风控检查 → Execution 撮合。

        主动式下单（vnpy 风格），立即返回 order_id，实际成交通过
        OrderEvent/TradeEvent 异步回报（回测同步模式下立即完成）。
        """
        # 参数校验
        if volume is None and target_weight is None:
            raise ValueError("volume 和 target_weight 不能同时为空")

        # 生成订单ID
        if order_id is None:
            order_id = f"O_{uuid.uuid4().hex[:12]}"

        # 构造 Order
        order = Order(
            order_id=order_id,
            symbol=symbol,
            direction=Direction(direction),
            volume=float(volume) if volume is not None else 0.0,
            target_weight=target_weight,
            price_type=price_type,
            price=price,
            status=OrderStatus.PENDING,
            created_time=self._engine.clock,
        )

        # 获取当前市价（用于风控和撮合）
        current_price = self._engine.get_current_price(symbol)
        if current_price is None or current_price <= 0:
            # 无市价：拒绝订单
            order.status = OrderStatus.REJECTED
            self._engine.publish(
                OrderEvent(
                    timestamp=self._engine.clock,
                    order_id=order_id,
                    symbol=symbol,
                    direction=direction,
                    volume=order.volume,
                    status=OrderStatus.REJECTED.value,
                    reason="无可用市价，无法下单",
                )
            )
            self._engine.portfolio.record_order(order)
            return order_id

        # 风控检查
        if self._engine.risk_manager is not None:
            context_data = self._engine.build_risk_context(symbol, current_price)
            result = self._engine.risk_manager.check_order(order, context_data)
            if not result.passed:
                # 风控拒绝：推送拒绝事件
                order.status = OrderStatus.REJECTED
                self._engine.publish(
                    OrderEvent(
                        timestamp=self._engine.clock,
                        order_id=order_id,
                        symbol=symbol,
                        direction=direction,
                        volume=order.volume,
                        status=OrderStatus.REJECTED.value,
                        reason=result.reason,
                    )
                )
                self._engine.portfolio.record_order(order)
                return order_id

        # 风控通过：提交执行层撮合
        self._engine.execution.submit(order, current_price, self._engine.clock)
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单，委托给 Execution。"""
        return self._engine.execution.cancel(order_id)

    # ------------------------------------------------------------------
    # 3. 持仓查询（返回 dict，符合 Context 契约）
    # ------------------------------------------------------------------

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """查询单标的持仓，返回 dict 或 None。"""
        pos = self._engine.portfolio.get_position(symbol)
        if pos is None or pos.quantity <= 1e-9:
            return None
        return pos.to_dict()

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        """查询全部有效持仓（quantity>0）。"""
        result: Dict[str, Dict[str, Any]] = {}
        for symbol, pos in self._engine.portfolio.get_active_positions().items():
            result[symbol] = pos.to_dict()
        return result

    # ------------------------------------------------------------------
    # 4. 账户查询
    # ------------------------------------------------------------------

    def get_account(self) -> Dict[str, Any]:
        """查询账户资金，返回 dict。"""
        return self._engine.portfolio.get_account().to_dict()

    # ------------------------------------------------------------------
    # 5. 定时器
    # ------------------------------------------------------------------

    def add_timer(self, name: str, rule: str) -> None:
        """注册定时器。"""
        self._engine.add_timer(name, rule)

    def is_timer_due(self, name: str) -> bool:
        """判断指定定时器在当前事件中是否触发。"""
        return self._engine.is_timer_due(name)

    # ------------------------------------------------------------------
    # 6. 时间查询
    # ------------------------------------------------------------------

    def get_clock(self) -> datetime:
        """获取当前回测时间（当前 BarEvent 时间戳）。"""
        return self._engine.clock

    # ------------------------------------------------------------------
    # 7. 日志与配置
    # ------------------------------------------------------------------

    def log(self, level: str, msg: str, **kwargs: Any) -> None:
        """写日志。"""
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
        full_msg = f"[{self._engine.strategy.name}] {msg}"
        if extra:
            full_msg = f"{full_msg} | {extra}"
        getattr(logger, level.lower(), logger.info)(full_msg)

    def get_config(self, key: str, default: Any = None) -> Any:
        """读取引擎配置。"""
        return self._engine.config.get(key, default)

    # ------------------------------------------------------------------
    # 8. 数据库访问
    # ------------------------------------------------------------------

    def get_db(self) -> Optional[Any]:
        """获取数据库连接（只读用途）。"""
        return self._engine.db


# ---------------------------------------------------------------------------
# BacktestEngine：回测引擎
# ---------------------------------------------------------------------------


class BacktestEngine:
    """回测引擎（同步事件驱动）。

    组装 HistoricalDataFeed + SimulatedExecution + RiskManager + Portfolio，
    按交易日逐根推进，驱动策略 on_event 决策，返回 BacktestResult。

    Parameters
    ----------
    strategy : Strategy
        策略实例（已注册，含 params）
    db : DatabaseManager
        数据库管理器（提供 get_stock_daily / get_index_daily）
    start_date, end_date : str
        回测起止日期 YYYY-MM-DD
    initial_capital : float
        初始资金（默认 1,000,000）
    benchmark_code : str
        基准指数代码（默认 000300.SH 沪深300）
    risk_manager : RiskManager, optional
        风控管理器，None 表示不启用风控（不推荐）
    config : dict, optional
        引擎配置（策略可通过 context.get_config 读取）
    """

    def __init__(
        self,
        strategy: Strategy,
        db: Any,
        start_date: str,
        end_date: str,
        initial_capital: float = 1_000_000.0,
        benchmark_code: str = "000300.SH",
        risk_manager: Optional[RiskManager] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        # 策略与配置
        self.strategy: Strategy = strategy
        self.db: Any = db
        self.config: Dict[str, Any] = dict(config) if config else {}
        self.config.setdefault("initial_capital", initial_capital)
        self.config.setdefault("benchmark", benchmark_code)
        self.config.setdefault("start_date", start_date)
        self.config.setdefault("end_date", end_date)

        # 核心组件
        self.portfolio: Portfolio = Portfolio(initial_capital)
        self.datafeed: HistoricalDataFeed = HistoricalDataFeed(
            db, start_date, end_date
        )
        self.event_engine: EventEngine = EventEngine(mode="backtest")
        self.execution: SimulatedExecution = SimulatedExecution(
            self.portfolio, self.event_engine, mode="backtest"
        )
        self.risk_manager: Optional[RiskManager] = risk_manager

        # 基准（用于超额收益计算）
        self.benchmark_provider: BenchmarkProvider = BenchmarkProvider(
            db, benchmark_code
        )

        # 策略上下文
        self.context: BacktestContext = BacktestContext(self)

        # 运行时状态
        self._clock: datetime = datetime.now()
        self._current_bar: Optional[BarEvent] = None
        # 定时器注册表：{name: rule}
        self._timers: Dict[str, str] = {}
        # 当前触发的定时器集合（供 is_timer_due 查询）
        self._triggered_timers: set = set()
        # 所有交易日列表（datafeed.start 后填充，用于判断月初/月末）
        self._all_dates: List[Any] = []
        # 订单ID计数器
        self._order_counter: int = 0

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def clock(self) -> datetime:
        """当前回测时间。"""
        return self._clock

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def run(self) -> BacktestResult:
        """执行回测，返回 BacktestResult。

        完整生命周期：启动 → on_init → 事件循环 → on_stop → 绩效计算。
        """
        try:
            # 1. 启动 DataFeed（加载历史数据）
            self.datafeed.set_event_engine(self.event_engine)
            self.datafeed.start()
            self._all_dates = list(self.datafeed._dates)

            if not self._all_dates:
                return BacktestResult(
                    error="回测区间无历史数据",
                    equity_curve=[],
                    benchmark_code=self.benchmark_provider.benchmark_code,
                )

            # 2. 注册策略 on_event 为事件处理器
            # 统一处理所有事件类型（on_event 内部按 event.type 分发）
            for et in EventType:
                self.event_engine.register(self._on_event_wrapper, et)

            # 3. 启动事件总线（绑定 context，回测模式同步）
            #    必须在 publish 前调用，否则 _dispatch 时 context 为 None
            self.event_engine.start(self.context)

            # 4. 策略 on_init
            self.strategy.on_init(self.context)

            # 5. 推送 InitEvent
            self._clock = self._to_datetime(self._all_dates[0])
            self.event_engine.publish(InitEvent(timestamp=self._clock))

            # 5. 事件循环：逐日推进
            while True:
                bar = self.datafeed.next_bar()
                if bar is None:
                    break
                self._process_bar(bar)

            # 6. 推送 StopEvent
            self.event_engine.publish(StopEvent(timestamp=self._clock))
            # 7. 策略 on_stop
            self.strategy.on_stop(self.context)
            # 8. 停止事件总线（清理 context）
            self.event_engine.stop()

            # 9. 计算绩效指标
            start_str = self.config.get("start_date")
            end_str = self.config.get("end_date")
            calc = PerformanceCalculator(
                self.portfolio, self.benchmark_provider
            )
            return calc.calculate(start_date=start_str, end_date=end_str)

        except Exception as e:
            logger.exception("回测引擎运行异常")
            return BacktestResult(
                error=f"回测异常: {e}",
                equity_curve=list(self.portfolio.equity_curve),
                trades=list(self.portfolio.trades),
                fills=list(self.portfolio.fills),
                benchmark_code=self.benchmark_provider.benchmark_code,
            )

    # ------------------------------------------------------------------
    # 单日处理
    # ------------------------------------------------------------------

    def _process_bar(self, bar: BarEvent) -> None:
        """处理单根 BarEvent 的完整流程。

        步骤：
            1. 更新时钟
            2. T+1 结算（settle_new_day）
            3. Pending 订单开盘撮合
            4. 检查定时器并推送 TimerEvent
            5. 推送 BarEvent（策略决策、下单、撮合）
            6. 更新市价
            7. 净值快照
        """
        # 1. 更新时钟
        self._clock = bar.timestamp
        self._current_bar = bar

        # 2. T+1 结算：今日开盘解冻昨日买入
        self.portfolio.settle_new_day()

        # 3. Pending 订单开盘撮合
        open_prices = self._extract_open_prices(bar)
        if open_prices:
            self.execution.process_pending_orders(self._clock, open_prices)

        # 4. 检查定时器
        self._triggered_timers = self._check_timers()
        for timer_name in self._triggered_timers:
            self.event_engine.publish(
                TimerEvent(
                    timestamp=self._clock,
                    name=timer_name,
                    rule=self._timers.get(timer_name, ""),
                )
            )

        # 5. 推送 BarEvent（策略 on_event 处理，可能 submit_order）
        self.event_engine.publish(bar)

        # 6. 更新市价（用收盘价）
        close_prices = self._extract_close_prices(bar)
        self.portfolio.update_market_prices(close_prices, self._clock)

        # 7. 推送账户事件
        acct = self.portfolio.get_account()
        self.event_engine.publish(
            AccountEvent(
                timestamp=self._clock,
                cash=acct.cash,
                frozen=acct.frozen,
                market_value=acct.market_value,
                total=acct.total,
                pnl=acct.pnl,
                pnl_pct=acct.pnl_pct,
                daily_pnl=acct.daily_pnl,
                daily_pnl_pct=acct.daily_pnl_pct,
            )
        )

        # 8. 净值快照
        self.portfolio.snapshot(self._clock)

    # ------------------------------------------------------------------
    # 事件分发
    # ------------------------------------------------------------------

    def _on_event_wrapper(self, event: Event, context: Context) -> None:
        """事件处理器包装：调用策略 on_event。

        EventEngine 分发时调用，统一转给策略 on_event。
        """
        self.strategy.on_event(event, context)

    def publish(self, event: Event) -> None:
        """发布事件到事件总线（供 Context 内部调用）。"""
        self.event_engine.publish(event)

    # ------------------------------------------------------------------
    # 市价与 bar 字段提取
    # ------------------------------------------------------------------

    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前 bar 中指定 symbol 的收盘价。"""
        if self._current_bar is None:
            return None
        symbols_bars = self._current_bar.extra.get("symbols_bars", {})
        bar_dict = symbols_bars.get(symbol)
        if bar_dict is None:
            return None
        close = bar_dict.get("close")
        return float(close) if close is not None else None

    @staticmethod
    def _extract_open_prices(bar: BarEvent) -> Dict[str, float]:
        """从 BarEvent 提取全市场开盘价字典。"""
        symbols_bars = bar.extra.get("symbols_bars", {})
        return {
            sym: float(b.get("open", 0.0))
            for sym, b in symbols_bars.items()
            if b.get("open") is not None
        }

    @staticmethod
    def _extract_close_prices(bar: BarEvent) -> Dict[str, float]:
        """从 BarEvent 提取全市场收盘价字典。"""
        symbols_bars = bar.extra.get("symbols_bars", {})
        return {
            sym: float(b.get("close", 0.0))
            for sym, b in symbols_bars.items()
            if b.get("close") is not None
        }

    # ------------------------------------------------------------------
    # 定时器管理
    # ------------------------------------------------------------------

    def add_timer(self, name: str, rule: str) -> None:
        """注册定时器。

        支持的 rule：
            - month_start: 每月第一个交易日
            - month_end:   每月最后一个交易日
            - week_start:  每周第一个交易日
            - daily_open:  每日开盘
            - daily_close: 每日收盘
        """
        self._timers[name] = rule

    def is_timer_due(self, name: str) -> bool:
        """判断指定定时器在当前事件中是否触发。"""
        return name in self._triggered_timers

    def _check_timers(self) -> set:
        """检查当前交易日触发的定时器集合。

        根据 _timers 注册的 rule 判断当日是否触发。
        """
        if not self._timers:
            return set()

        triggered: set = set()
        current_idx = self.datafeed._current_idx
        dates = self._all_dates

        for name, rule in self._timers.items():
            if rule == "daily_open" or rule == "daily_close":
                # 每日触发
                triggered.add(name)
            elif rule == "month_start":
                # 每月第一个交易日：当前日期的月份与前一交易日不同
                if self._is_month_start(current_idx, dates):
                    triggered.add(name)
            elif rule == "month_end":
                # 每月最后一个交易日：当前日期的月份与下一交易日不同
                if self._is_month_end(current_idx, dates):
                    triggered.add(name)
            elif rule == "week_start":
                # 每周第一个交易日：当前日期的周数与前一交易日不同
                if self._is_week_start(current_idx, dates):
                    triggered.add(name)
        return triggered

    @staticmethod
    def _get_month(idx: int, dates: List[Any]) -> Optional[int]:
        """安全获取 dates[idx] 的月份。"""
        if idx < 0 or idx >= len(dates):
            return None
        d = dates[idx]
        # 兼容 pd.Timestamp 和 datetime
        if hasattr(d, "month"):
            return d.month
        return None

    @staticmethod
    def _get_weekday(idx: int, dates: List[Any]) -> Optional[int]:
        """安全获取 dates[idx] 的星期（ISO 周一到周日=1-7）。"""
        if idx < 0 or idx >= len(dates):
            return None
        d = dates[idx]
        if hasattr(d, "isoweekday"):
            return d.isoweekday()
        return None

    def _is_month_start(self, idx: int, dates: List[Any]) -> bool:
        """判断当前交易日是否是每月第一个交易日。"""
        if idx <= 0:
            return True  # 回测第一天视为月初
        cur_month = self._get_month(idx, dates)
        prev_month = self._get_month(idx - 1, dates)
        return cur_month != prev_month

    def _is_month_end(self, idx: int, dates: List[Any]) -> bool:
        """判断当前交易日是否是每月最后一个交易日。"""
        if idx >= len(dates) - 1:
            return True  # 回测最后一天视为月末
        cur_month = self._get_month(idx, dates)
        next_month = self._get_month(idx + 1, dates)
        return cur_month != next_month

    def _is_week_start(self, idx: int, dates: List[Any]) -> bool:
        """判断当前交易日是否是每周第一个交易日。

        简化规则：当前交易日是周一，或与前一日不在同一自然周。
        """
        if idx <= 0:
            return True
        cur_wd = self._get_weekday(idx, dates)
        prev_wd = self._get_weekday(idx - 1, dates)
        if cur_wd is None or prev_wd is None:
            return False
        # 周一视为每周第一天
        return cur_wd == 1 or cur_wd <= prev_wd

    # ------------------------------------------------------------------
    # 风控上下文构建
    # ------------------------------------------------------------------

    def build_risk_context(
        self, symbol: str, current_price: float
    ) -> Dict[str, Any]:
        """构建风控检查上下文数据。

        供 RiskManager.check_order 使用，包含当前 bar/持仓/账户等信息。
        """
        bar_dict = None
        if self._current_bar is not None:
            bar_dict = self._current_bar.extra.get("symbols_bars", {}).get(symbol)
        pos = self.portfolio.get_position(symbol)
        acct = self.portfolio.get_account()
        return {
            "current_time": self._clock,
            "current_price": current_price,
            "bar": bar_dict,
            "stock_info": None,  # 由策略层预加载或风控内部查询
            "position": pos,
            "account": acct,
            "portfolio": self.portfolio.get_active_positions(),
        }

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _to_datetime(d: Any) -> datetime:
        """将 pd.Timestamp / datetime 统一转为 datetime。"""
        if hasattr(d, "to_pydatetime"):
            return d.to_pydatetime()
        if isinstance(d, datetime):
            return d
        return datetime.now()
