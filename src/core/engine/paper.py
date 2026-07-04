"""
src/core/engine/paper.py
========================

PaperEngine 模拟盘引擎 + PaperContext 策略上下文。

模拟盘引擎用于实时行情 + 模拟撮合 + 数据库持久化，支持跨日恢复运行。
与回测引擎的差异：
    1. 使用 LiveDataFeed（实时行情，可降级为定时从 DB 读最新 bar）
    2. 每日收盘后持久化账户/持仓/订单/快照（PersistenceRepository）
    3. 支持跨日 Pending 订单（T+1 次日开盘撮合）
    4. 异步事件循环（EventEngine mode="paper"）

多策略子账户模式：
    - 一个主账户可同时运行多个策略，每个策略对应一个子账户
    - PaperEngine 通过 strategy_name 参数标识当前运行的子账户
    - 持久化时所有数据（持仓/订单/成交/快照）都带 strategy_name 标签
    - 资金隔离：每个子账户独立 Portfolio，主账户资金通过 account_strategies 管理

运行模式（设计文档 7.2 节）：
    - 长驻模式：run() 启动后持续运行，由 LiveDataFeed 后台线程推 bar
    - 每日模式：run_one_day(trade_date) 处理单个交易日（适合 A 股日频调仓）

生命周期：
    1. load_state() 从 DB 恢复子账户状态（首次运行初始化）
    2. 策略 on_init
    3. 每个交易日：
       a. 接收当日 bar（LiveDataFeed 推送或从 DB 读取）
       b. T+1 结算 + Pending 撮合 + 定时器检查
       c. 推送 BarEvent → 策略决策 → 风控 → 撮合
       d. 更新市价 + 净值快照
       e. save_state(trade_date) 持久化
    4. 策略 on_stop

用法示例（多策略子账户）：
    from src.core.engine import PaperEngine

    # 主账户 acc_001 下运行策略 small_cap，分配 50 万资金
    engine = PaperEngine(
        strategy=s,
        db=db,
        account_id="acc_001",
        strategy_name="small_cap",  # 子账户标识
        initial_capital=500_000,
    )
    engine.start()
    engine.run_one_day(bar)  # 处理单日
    engine.stop()
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from src.core.context import Context
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
from src.core.persistence import PersistenceRepository
from src.core.portfolio import Portfolio
from src.core.risk.manager import RiskManager
from src.core.strategy import Strategy
from src.core.types import Direction, Order, OrderStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PaperContext：模拟盘策略上下文
# ---------------------------------------------------------------------------


class PaperContext(Context):
    """模拟盘策略上下文。

    接口与 BacktestContext 一致，差异在于数据访问委托给 LiveDataFeed，
    订单操作经风控后送入 SimulatedExecution(paper)。
    """

    def __init__(self, engine: "PaperEngine") -> None:
        self._engine = engine

    def subscribe(self, symbols: Union[str, List[str]]) -> None:
        if isinstance(symbols, str):
            symbols = [symbols]
        # datafeed 为 None 时（降级模式）优雅跳过，由 run_one_day 直接注入 bar
        if self._engine.datafeed is None:
            return
        self._engine.datafeed.subscribe(symbols)

    def history(
        self,
        symbol: str,
        fields: Union[str, List[str]] = "close",
        count: int = 100,
    ) -> Any:
        if self._engine.datafeed is None:
            return []
        if isinstance(fields, str):
            fields_list: Optional[List[str]] = [fields]
        else:
            fields_list = list(fields) if fields else None
        df = self._engine.datafeed.history(symbol, fields_list, count)
        if isinstance(fields, str) and not df.empty and fields in df.columns:
            return df[fields].tolist()
        return df

    def history_multi(
        self,
        symbols: List[str],
        fields: Union[str, List[str]] = "close",
        count: int = 100,
    ) -> Any:
        if self._engine.datafeed is None:
            return {}
        if isinstance(fields, str):
            fields_list: Optional[List[str]] = [fields]
        else:
            fields_list = list(fields) if fields else None
        return self._engine.datafeed.history_multi(symbols, fields_list, count)

    def get_subscribed_symbols(self) -> List[str]:
        if self._engine.datafeed is None:
            return []
        return list(self._engine.datafeed._symbols)

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
        if volume is None and target_weight is None:
            raise ValueError("volume 和 target_weight 不能同时为空")
        if order_id is None:
            order_id = f"P_{uuid.uuid4().hex[:12]}"
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
        current_price = self._engine.get_current_price(symbol)
        if current_price is None or current_price <= 0:
            order.status = OrderStatus.REJECTED
            self._engine.publish(
                OrderEvent(
                    timestamp=self._engine.clock,
                    order_id=order_id,
                    symbol=symbol,
                    direction=direction,
                    volume=order.volume,
                    status=OrderStatus.REJECTED.value,
                    reason="无可用市价",
                )
            )
            self._engine.portfolio.record_order(order)
            # 持久化订单（带 strategy_name 标识子账户）
            self._engine.repository.save_order(
                self._engine.account_id, order, self._engine.strategy_name
            )
            return order_id
        # 风控检查
        if self._engine.risk_manager is not None:
            context_data = self._engine.build_risk_context(symbol, current_price)
            result = self._engine.risk_manager.check_order(order, context_data)
            if not result.passed:
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
                self._engine.repository.save_order(
                    self._engine.account_id, order, self._engine.strategy_name
                )
                return order_id
        # 提交撮合
        self._engine.execution.submit(order, current_price, self._engine.clock)
        # 持久化订单（带 strategy_name 标识子账户）
        self._engine.repository.save_order(
            self._engine.account_id, order, self._engine.strategy_name
        )
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        ok = self._engine.execution.cancel(order_id)
        return ok

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        pos = self._engine.portfolio.get_position(symbol)
        if pos is None or pos.quantity <= 1e-9:
            return None
        return pos.to_dict()

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        return {
            s: p.to_dict()
            for s, p in self._engine.portfolio.get_active_positions().items()
        }

    def get_account(self) -> Dict[str, Any]:
        return self._engine.portfolio.get_account().to_dict()

    def add_timer(self, name: str, rule: str) -> None:
        self._engine.add_timer(name, rule)

    def is_timer_due(self, name: str) -> bool:
        return self._engine.is_timer_due(name)

    def get_clock(self) -> datetime:
        return self._engine.clock

    def log(self, level: str, msg: str, **kwargs: Any) -> None:
        extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
        full_msg = f"[{self._engine.strategy.name}] {msg}"
        if extra:
            full_msg = f"{full_msg} | {extra}"
        getattr(logger, level.lower(), logger.info)(full_msg)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._engine.config.get(key, default)

    def get_db(self) -> Optional[Any]:
        return self._engine.db


# ---------------------------------------------------------------------------
# PaperEngine：模拟盘引擎
# ---------------------------------------------------------------------------


class PaperEngine:
    """模拟盘引擎（异步事件驱动 + DB 持久化）。

    组装 LiveDataFeed + SimulatedExecution(paper) + RiskManager + Portfolio +
    PersistenceRepository，支持跨日恢复运行。

    多策略子账户模式：
        一个主账户（account_id）可同时运行多个策略，每个策略对应一个子账户
        （strategy_name）。PaperEngine 实例代表一个子账户的运行，资金独立隔离。
        主账户的资金通过 PersistenceRepository.init_main_account/add_strategy 管理。

    Parameters
    ----------
    strategy : Strategy
        策略实例
    db : DatabaseManager
        数据库管理器
    account_id : str
        主账户ID（持久化主键，每个模拟盘账户唯一）
    strategy_name : str, optional
        子账户策略名称（多策略模式下标识当前子账户）。
        None 时回退到 strategy.name（向后兼容）
    initial_capital : float
        子账户初始资金（首次运行时使用，后续从 DB 恢复）
    datafeed : LiveDataFeed, optional
        实时数据流，None 时降级为从 DB 读取
    risk_manager : RiskManager, optional
        风控管理器
    config : dict, optional
        引擎配置
    """

    def __init__(
        self,
        strategy: Strategy,
        db: Any,
        account_id: str,
        strategy_name: Optional[str] = None,
        initial_capital: float = 1_000_000.0,
        datafeed: Optional[Any] = None,
        risk_manager: Optional[RiskManager] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.strategy: Strategy = strategy
        self.db: Any = db
        self.account_id: str = account_id
        # 子账户策略名称：未指定时回退到 strategy.name（兼容旧调用）
        self.strategy_name: str = strategy_name if strategy_name else strategy.name
        self.config: Dict[str, Any] = dict(config) if config else {}
        self.config.setdefault("initial_capital", initial_capital)

        # 核心组件
        self.portfolio: Portfolio = Portfolio(initial_capital)
        # datafeed 可为 None（降级模式由 run_one_day 直接注入 bar）
        self.datafeed: Any = datafeed
        # 事件引擎模式：有 datafeed（长驻模式）用异步 paper；无 datafeed（每日模式）用同步 backtest
        # 每日模式下 run_one_day 同步调用，事件必须同步处理才能保证策略 on_event 被及时调用
        ee_mode = "paper" if datafeed is not None else "backtest"
        self.event_engine: EventEngine = EventEngine(mode=ee_mode)
        self.execution: SimulatedExecution = SimulatedExecution(
            self.portfolio, self.event_engine, mode="paper"
        )
        self.risk_manager: Optional[RiskManager] = risk_manager
        self.repository: PersistenceRepository = PersistenceRepository(db)
        self.repository.ensure_tables()

        # 上下文
        self.context: PaperContext = PaperContext(self)

        # 运行时状态
        self._clock: datetime = datetime.now()
        self._current_bar: Optional[BarEvent] = None
        self._timers: Dict[str, str] = {}
        self._triggered_timers: set = set()
        self._started: bool = False

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def clock(self) -> datetime:
        return self._clock

    # ------------------------------------------------------------------
    # 启动与恢复
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动模拟盘引擎。

        流程：
            1. 从 DB 恢复账户状态（load_state）
            2. 注入 datafeed 到 event_engine
            3. 注册策略 on_event 为处理器
            4. 策略 on_init
            5. 推送 InitEvent
            6. 启动异步事件循环
        """
        if self._started:
            logger.warning("PaperEngine 已启动，重复调用 start 被忽略")
            return

        # 恢复账户状态
        self.load_state()

        # 注入 datafeed
        if self.datafeed is not None:
            self.datafeed.set_event_engine(self.event_engine)

        # 注册事件处理器
        for et in EventType:
            self.event_engine.register(self._on_event_wrapper, et)

        # 策略初始化
        self.strategy.on_init(self.context)

        # 推送 InitEvent
        self._clock = datetime.now()
        self.event_engine.start(self.context)
        self.event_engine.publish(InitEvent(timestamp=self._clock))

        # 启动 datafeed（后台线程推 bar）
        if self.datafeed is not None:
            self.datafeed.start()

        self._started = True
        logger.info(
            "PaperEngine 启动: account=%s strategy=%s",
            self.account_id, self.strategy_name,
        )

    def stop(self) -> None:
        """停止模拟盘引擎，持久化状态。"""
        if not self._started:
            return
        # 推送 StopEvent
        self._clock = datetime.now()
        self.event_engine.publish(StopEvent(timestamp=self._clock))
        # 策略 on_stop
        self.strategy.on_stop(self.context)
        # 停止 datafeed
        if self.datafeed is not None:
            self.datafeed.stop()
        # 停止事件引擎
        self.event_engine.stop()
        # 持久化最终状态
        self.save_state(self._clock.strftime("%Y-%m-%d"))
        self._started = False
        logger.info(
            "PaperEngine 已停止: account=%s strategy=%s",
            self.account_id, self.strategy_name,
        )

    # ------------------------------------------------------------------
    # 单日运行（A股日频调仓核心）
    # ------------------------------------------------------------------

    def run_one_day(self, bar: BarEvent) -> None:
        """处理单个交易日的完整流程。

        A 股日频调仓场景：每日收盘后由调度器调用，传入当日 bar。
        完成决策、撮合、持久化全流程。

        Args:
            bar: 当日 BarEvent（含全市场 OHLC）
        """
        if not self._started:
            # 未启动时自动启动（不启动异步循环，仅初始化）
            self._init_for_daily_mode()

        # 处理单日 bar（与 BacktestEngine._process_bar 一致）
        self._process_bar(bar)

        # 持久化当日状态
        trade_date = bar.extra.get("trade_date", self._clock.strftime("%Y-%m-%d"))
        self.save_state(trade_date)

    def _init_for_daily_mode(self) -> None:
        """每日模式的轻量初始化（不启动异步线程）。"""
        self.load_state()
        if self.datafeed is not None:
            self.datafeed.set_event_engine(self.event_engine)
        for et in EventType:
            self.event_engine.register(self._on_event_wrapper, et)
        # 启动事件总线（绑定 context）
        # 每日模式 datafeed=None 时 EventEngine 为同步 backtest 模式，start 会绑定 context
        # 长驻模式 datafeed!=None 时 EventEngine 为异步 paper 模式，start 会启动消费者线程
        self.event_engine.start(self.context)
        self.strategy.on_init(self.context)
        self._clock = datetime.now()
        self.event_engine.publish(InitEvent(timestamp=self._clock))
        self._started = True

    def _process_bar(self, bar: BarEvent) -> None:
        """处理单根 BarEvent（与 BacktestEngine 一致，回测引擎已验证）。"""
        self._clock = bar.timestamp
        self._current_bar = bar

        # T+1 结算
        self.portfolio.settle_new_day()

        # Pending 订单开盘撮合
        open_prices = {
            sym: float(b.get("open", 0.0))
            for sym, b in bar.extra.get("symbols_bars", {}).items()
            if b.get("open") is not None
        }
        if open_prices:
            self.execution.process_pending_orders(self._clock, open_prices)

        # 定时器检查
        self._triggered_timers = self._check_timers_simple()
        for timer_name in self._triggered_timers:
            self.event_engine.publish(
                TimerEvent(
                    timestamp=self._clock,
                    name=timer_name,
                    rule=self._timers.get(timer_name, ""),
                )
            )

        # 推送 BarEvent
        self.event_engine.publish(bar)

        # 更新市价
        close_prices = {
            sym: float(b.get("close", 0.0))
            for sym, b in bar.extra.get("symbols_bars", {}).items()
            if b.get("close") is not None
        }
        self.portfolio.update_market_prices(close_prices, self._clock)

        # 推送账户事件
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

        # 净值快照
        self.portfolio.snapshot(self._clock)

    # ------------------------------------------------------------------
    # 事件分发
    # ------------------------------------------------------------------

    def _on_event_wrapper(self, event: Event, context: Context) -> None:
        """事件处理器包装。"""
        self.strategy.on_event(event, context)

    def publish(self, event: Event) -> None:
        """发布事件到事件总线。"""
        self.event_engine.publish(event)

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def load_state(self) -> bool:
        """从 DB 恢复子账户状态（按 strategy_name 隔离）。"""
        ok = self.repository.load_account_state(
            self.account_id, self.strategy_name, self.portfolio
        )
        if ok:
            logger.info(
                "PaperEngine 恢复子账户: account=%s strategy=%s cash=%.2f positions=%d",
                self.account_id, self.strategy_name, self.portfolio.cash,
                len(self.portfolio.get_active_positions()),
            )
        return ok

    def save_state(self, trade_date: str) -> None:
        """持久化子账户状态到 DB（按 strategy_name 隔离）。"""
        self.repository.save_account_state(
            self.account_id, self.strategy_name, self.portfolio, trade_date
        )

    # ------------------------------------------------------------------
    # 市价与辅助
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

    def add_timer(self, name: str, rule: str) -> None:
        self._timers[name] = rule

    def is_timer_due(self, name: str) -> bool:
        return name in self._triggered_timers

    def _check_timers_simple(self) -> set:
        """简化定时器检查（每日模式默认全部触发）。

        模拟盘每日只处理一个 bar，定时器判断依赖外部调度。
        简化规则：daily_open/daily_close 每日触发；
        month_start/month_end/week_start 由调用方通过 bar 日期判断。
        """
        triggered: set = set()
        for name, rule in self._timers.items():
            if rule in ("daily_open", "daily_close"):
                triggered.add(name)
            # 月度/周度定时器在每日模式下简化为每日触发
            # 生产环境应按实际交易日历判断
        return triggered

    def build_risk_context(
        self, symbol: str, current_price: float
    ) -> Dict[str, Any]:
        """构建风控上下文。"""
        bar_dict = None
        if self._current_bar is not None:
            bar_dict = self._current_bar.extra.get("symbols_bars", {}).get(symbol)
        pos = self.portfolio.get_position(symbol)
        acct = self.portfolio.get_account()
        return {
            "current_time": self._clock,
            "current_price": current_price,
            "bar": bar_dict,
            "stock_info": None,
            "position": pos,
            "account": acct,
            "portfolio": self.portfolio.get_active_positions(),
        }
