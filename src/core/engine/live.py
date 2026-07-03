"""
src/core/engine/live.py
=======================

LiveEngine 实盘引擎 + LiveContext 策略上下文。

实盘引擎用于真实下单交易，与模拟盘引擎的差异：
    1. 使用 LiveExecution（调用券商 API 真实下单）
    2. 订单状态由券商异步回报（非本地撮合）
    3. 持仓以券商为准（reconcile 对账）
    4. 持久化账户/持仓/订单/成交到 DB

运行模式（设计文档 7.2 节）：
    实盘引擎需接入券商 API（如东财掘金），订单提交后由券商回报状态。
    本类提供完整框架，券商 API 适配由 LiveExecution 实现（阶段2已定义接口）。

生命周期：
    1. load_state() 从 DB 恢复账户状态
    2. reconcile() 从券商同步真实持仓（对账）
    3. 策略 on_init
    4. 事件循环（LiveDataFeed 推 bar / 券商回报推 Order/Trade 事件）
    5. 每日收盘后 save_state() 持久化
    6. 策略 on_stop

用法示例：
    from src.core.engine import LiveEngine
    engine = LiveEngine(
        strategy=s, db=db, account_id="live_001",
        execution=live_exec, datafeed=live_feed,
        token="YOUR_TOKEN",
    )
    engine.start()
    # ... 运行中由 datafeed 推 bar，券商回报推 order/trade 事件
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
from src.core.execution.base import Execution
from src.core.persistence import PersistenceRepository
from src.core.portfolio import Portfolio
from src.core.risk.manager import RiskManager
from src.core.strategy import Strategy
from src.core.types import Direction, Order, OrderStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LiveContext：实盘策略上下文
# ---------------------------------------------------------------------------


class LiveContext(Context):
    """实盘策略上下文。

    接口与 PaperContext 一致，差异在于订单委托给 LiveExecution（真实下单），
    订单状态由券商异步回报，不立即确认成交。
    """

    def __init__(self, engine: "LiveEngine") -> None:
        self._engine = engine

    def subscribe(self, symbols: Union[str, List[str]]) -> None:
        if isinstance(symbols, str):
            symbols = [symbols]
        self._engine.datafeed.subscribe(symbols)

    def history(
        self,
        symbol: str,
        fields: Union[str, List[str]] = "close",
        count: int = 100,
    ) -> Any:
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
        if isinstance(fields, str):
            fields_list: Optional[List[str]] = [fields]
        else:
            fields_list = list(fields) if fields else None
        return self._engine.datafeed.history_multi(symbols, fields_list, count)

    def get_subscribed_symbols(self) -> List[str]:
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
            order_id = f"L_{uuid.uuid4().hex[:12]}"
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
            self._engine.repository.save_order(self._engine.account_id, order)
            return order_id
        # 风控检查（实盘风控必须执行）
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
                self._engine.repository.save_order(self._engine.account_id, order)
                return order_id
        # 提交券商执行（订单状态由券商异步回报）
        self._engine.execution.submit(order, current_price, self._engine.clock)
        # 持久化订单
        self._engine.repository.save_order(self._engine.account_id, order)
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
        full_msg = f"[LIVE][{self._engine.strategy.name}] {msg}"
        if extra:
            full_msg = f"{full_msg} | {extra}"
        getattr(logger, level.lower(), logger.info)(full_msg)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._engine.config.get(key, default)

    def get_db(self) -> Optional[Any]:
        return self._engine.db


# ---------------------------------------------------------------------------
# LiveEngine：实盘引擎
# ---------------------------------------------------------------------------


class LiveEngine:
    """实盘引擎（异步事件驱动 + 券商 API 真实下单）。

    组装 LiveDataFeed + LiveExecution + RiskManager + Portfolio +
    PersistenceRepository，订单由券商真实执行，状态异步回报。

    Parameters
    ----------
    strategy : Strategy
        策略实例
    db : DatabaseManager
        数据库管理器
    account_id : str
        账户ID（持久化主键）
    execution : Execution
        实盘执行层（LiveExecution，封装券商 API）
    datafeed : LiveDataFeed
        实时数据流
    initial_capital : float
        初始资金（首次运行时使用）
    risk_manager : RiskManager, optional
        风控管理器（实盘强烈建议启用）
    token : str, optional
        券商 API token
    config : dict, optional
        引擎配置
    """

    def __init__(
        self,
        strategy: Strategy,
        db: Any,
        account_id: str,
        execution: Execution,
        datafeed: Any,
        initial_capital: float = 1_000_000.0,
        risk_manager: Optional[RiskManager] = None,
        token: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.strategy: Strategy = strategy
        self.db: Any = db
        self.account_id: str = account_id
        self.config: Dict[str, Any] = dict(config) if config else {}
        self.config.setdefault("initial_capital", initial_capital)
        if token:
            self.config["token"] = token

        # 核心组件
        self.portfolio: Portfolio = Portfolio(initial_capital)
        self.datafeed: Any = datafeed
        self.event_engine: EventEngine = EventEngine(mode="live")
        self.execution: Execution = execution
        self.risk_manager: Optional[RiskManager] = risk_manager
        self.repository: PersistenceRepository = PersistenceRepository(db)
        self.repository.ensure_tables()

        # 上下文
        self.context: LiveContext = LiveContext(self)

        # 运行时状态
        self._clock: datetime = datetime.now()
        self._current_bar: Optional[BarEvent] = None
        self._timers: Dict[str, str] = {}
        self._triggered_timers: set = set()
        self._started: bool = False

    @property
    def clock(self) -> datetime:
        return self._clock

    # ------------------------------------------------------------------
    # 启动与停止
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动实盘引擎。

        流程：
            1. 恢复账户状态
            2. 从券商对账（reconcile）
            3. 注入 datafeed
            4. 策略 on_init
            5. 推送 InitEvent
            6. 启动异步事件循环 + datafeed 后台线程
        """
        if self._started:
            logger.warning("LiveEngine 已启动，重复调用 start 被忽略")
            return

        # 恢复账户
        self.load_state()

        # 从券商对账（同步真实持仓）
        try:
            self.reconcile()
        except Exception:
            logger.exception("券商对账失败，使用本地持仓继续")

        # 注入 datafeed
        if self.datafeed is not None:
            self.datafeed.set_event_engine(self.event_engine)

        # 注册事件处理器
        for et in EventType:
            self.event_engine.register(self._on_event_wrapper, et)

        # 策略初始化
        self.strategy.on_init(self.context)

        # 推送 InitEvent + 启动异步循环
        self._clock = datetime.now()
        self.event_engine.start(self.context)
        self.event_engine.publish(InitEvent(timestamp=self._clock))

        # 启动 datafeed
        if self.datafeed is not None:
            self.datafeed.start()

        self._started = True
        logger.warning(
            "LiveEngine 已启动实盘交易: account=%s strategy=%s",
            self.account_id, self.strategy.name,
        )

    def stop(self) -> None:
        """停止实盘引擎，持久化状态。"""
        if not self._started:
            return
        self._clock = datetime.now()
        self.event_engine.publish(StopEvent(timestamp=self._clock))
        self.strategy.on_stop(self.context)
        if self.datafeed is not None:
            self.datafeed.stop()
        self.event_engine.stop()
        self.save_state(self._clock.strftime("%Y-%m-%d"))
        self._started = False
        logger.info("LiveEngine 已停止: account=%s", self.account_id)

    # ------------------------------------------------------------------
    # 券商对账
    # ------------------------------------------------------------------

    def reconcile(self) -> None:
        """从券商同步真实持仓（对账）。

        实盘场景下券商持仓为准，本地 Portfolio 需对齐。
        具体实现依赖 LiveExecution 提供的券商查询接口。
        """
        # 查询券商真实持仓
        broker_positions = None
        if hasattr(self.execution, "query_positions"):
            broker_positions = self.execution.query_positions()

        if not broker_positions:
            logger.info("券商无持仓或查询失败，保持本地持仓不变")
            return

        # 用券商持仓覆盖本地（简化：直接重建 positions）
        from src.core.types import Position, PositionDirection
        new_positions: Dict[str, Position] = {}
        for symbol, pos_data in broker_positions.items():
            new_positions[symbol] = Position(
                symbol=symbol,
                direction=PositionDirection(
                    pos_data.get("direction", "long")
                ),
                quantity=float(pos_data.get("quantity", 0.0)),
                available=float(pos_data.get("available", 0.0)),
                avg_price=float(pos_data.get("avg_price", 0.0)),
                market_price=float(pos_data.get("market_price", 0.0)),
            )
            # 重算派生字段
            new_positions[symbol].update_market_price(
                float(pos_data.get("market_price", 0.0))
            )
        self.portfolio.positions = new_positions
        logger.info(
            "券商对账完成: account=%s positions=%d",
            self.account_id, len(new_positions),
        )

    # ------------------------------------------------------------------
    # 单日处理（实盘日频调仓）
    # ------------------------------------------------------------------

    def run_one_day(self, bar: BarEvent) -> None:
        """处理单个交易日（实盘日频调仓核心）。

        Args:
            bar: 当日 BarEvent（含全市场 OHLC）
        """
        if not self._started:
            self._init_for_daily_mode()

        self._process_bar(bar)

        # 持久化当日状态
        trade_date = bar.extra.get("trade_date", self._clock.strftime("%Y-%m-%d"))
        self.save_state(trade_date)

    def _init_for_daily_mode(self) -> None:
        """每日模式的轻量初始化。"""
        self.load_state()
        try:
            self.reconcile()
        except Exception:
            logger.exception("券商对账失败")
        if self.datafeed is not None:
            self.datafeed.set_event_engine(self.event_engine)
        for et in EventType:
            self.event_engine.register(self._on_event_wrapper, et)
        self.strategy.on_init(self.context)
        self._clock = datetime.now()
        self.event_engine.publish(InitEvent(timestamp=self._clock))
        self._started = True

    def _process_bar(self, bar: BarEvent) -> None:
        """处理单根 BarEvent。"""
        self._clock = bar.timestamp
        self._current_bar = bar

        # T+1 结算
        self.portfolio.settle_new_day()

        # Pending 订单处理（实盘由券商处理，此处空操作）
        # execution.process_pending_orders 在 LiveExecution 中为空实现

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

        # 推送 BarEvent（策略决策、下单由券商执行）
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
    # 事件分发与持久化
    # ------------------------------------------------------------------

    def _on_event_wrapper(self, event: Event, context: Context) -> None:
        self.strategy.on_event(event, context)

    def publish(self, event: Event) -> None:
        self.event_engine.publish(event)

    def load_state(self) -> bool:
        return self.repository.load_account_state(self.account_id, self.portfolio)

    def save_state(self, trade_date: str) -> None:
        self.repository.save_account_state(
            self.account_id, self.strategy.name, self.portfolio, trade_date
        )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def get_current_price(self, symbol: str) -> Optional[float]:
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
        triggered: set = set()
        for name, rule in self._timers.items():
            if rule in ("daily_open", "daily_close"):
                triggered.add(name)
        return triggered

    def build_risk_context(
        self, symbol: str, current_price: float
    ) -> Dict[str, Any]:
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
