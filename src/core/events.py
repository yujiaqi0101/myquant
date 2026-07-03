"""
src/core/events.py
==================

事件类型定义模块（事件驱动内核的核心）。

本模块定义引擎流转过程中所有事件的统一抽象：
    - EventType 枚举：8 种事件类型（INIT/BAR/TICK/ORDER/TRADE/TIMER/ACCOUNT/STOP）
    - Event 基类：所有事件共享 type 和 timestamp 两个核心字段
    - 8 个具体事件类：携带各自业务字段

事件流转总览（设计文档 3.1 节）：
    INIT          → 回测开始/实盘启动时触发一次
    BAR / TICK    → 由 DataFeed 按交易日推送（K线/Tick）
    ORDER         → 订单状态变化（提交/部分成交/全部成交/撤销/拒绝）
    TRADE         → 成交回报（每次撮合成交一次）
    ACCOUNT       → 账户资金变化（成交扣款/出入金）
    TIMER         → 定时器事件（调仓日/开盘前/收盘后由调度器触发）
    STOP          → 回测结束/实盘停止时触发一次

策略在 on_event(event, context) 中通过 event.type 分发处理，不感知运行模式。

用法示例：
    from src.core.events import EventType, BarEvent
    bar = BarEvent(timestamp=clock, symbol="000001.SZ", open=..., ...)
    if bar.type is EventType.BAR:
        ...
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Dict, Optional


class EventType(str, Enum):
    """事件类型枚举。

    继承 str 便于序列化和日志打印（event.type.value 直接得到字符串）。
    """

    # 初始化事件：回测开始/实盘启动，只推送一次
    INIT = "init"
    # K线事件（日/分钟级）：DataFeed 按交易日推送
    BAR = "bar"
    # Tick 事件（高频可选）：DataFeed 实时推送
    TICK = "tick"
    # 订单状态变化：订单提交/成交/撤销/拒绝
    ORDER = "order"
    # 成交回报：每次撮合成交
    TRADE = "trade"
    # 定时器事件：调仓日/开盘前/收盘后
    TIMER = "timer"
    # 账户资金变化：成交扣款/出入金
    ACCOUNT = "account"
    # 结束事件：回测结束/实盘停止，只推送一次
    STOP = "stop"


@dataclass
class Event:
    """所有事件的基类。

    所有具体事件必须继承本类并扩展自己的业务字段。
    使用 dataclass 而非普通类，便于自动生成 __init__/__repr__/__eq__。

    设计说明：
        type 字段使用 ClassVar（类变量），不作为实例字段存储。
        子类在类体中覆盖 type 为自己的 EventType 常量，实例化时无需传 type，
        读取 event.type 通过类属性查找得到正确值。这样既保证"事件类型由类决定、不可变"
        的语义，又避免子类实例化时必须传 type 的样板代码。

    Attributes:
        timestamp: 事件发生时间（回测用 bar 时间，实盘用墙钟时间）
    """

    # 事件发生时间（必填）
    timestamp: datetime
    # 事件类型：类变量，子类覆盖为对应 EventType，不进入 __init__
    type: ClassVar[EventType] = EventType.INIT


@dataclass
class InitEvent(Event):
    """初始化事件。

    引擎启动时推送一次，策略在 on_init 中接收并完成订阅数据、设置定时器等准备。
    """

    # 类变量覆盖：InitEvent 永远是 INIT 类型
    type: ClassVar[EventType] = EventType.INIT


@dataclass
class BarEvent(Event):
    """K线事件（日频或分钟级）。

    由 DataFeed 按交易日逐根推送。字段与 t_stock_daily 表对齐，便于直接从 DB 构造。

    Attributes:
        symbol: 标的代码（如 600000.SH）
        open/high/low/close: OHLC 价格
        volume: 成交量（股）
        amount: 成交额（元）
        frequency: 频率标识，默认 "1d"（日线）；分钟线可传 "1m" 等
        extra: 扩展字段（如复权因子、涨跌停价等），不强制结构
    """

    # 类变量覆盖：BarEvent 永远是 BAR 类型
    type: ClassVar[EventType] = EventType.BAR

    symbol: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    frequency: str = "1d"
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TickEvent(Event):
    """Tick 事件（高频可选）。

    实盘或模拟盘由实时行情源推送。回测默认不使用。

    Attributes:
        symbol: 标的代码
        price: 最新价
        volume: 本次 Tick 成交量
        bid_price/ask_price: 买一/卖一价（可选）
        bid_volume/ask_volume: 买一/卖一量（可选）
    """

    # 类变量覆盖：TickEvent 永远是 TICK 类型
    type: ClassVar[EventType] = EventType.TICK

    symbol: str = ""
    price: float = 0.0
    volume: float = 0.0
    bid_price: float = 0.0
    ask_price: float = 0.0
    bid_volume: float = 0.0
    ask_volume: float = 0.0


@dataclass
class OrderEvent(Event):
    """订单状态变化事件。

    由 Execution 在订单状态变化时推送（提交/部分成交/全部成交/撤销/拒绝）。
    策略可据此更新本地订单簿，但不依赖该事件驱动主流程（主流程由 BAR/TIMER 驱动）。

    Attributes:
        order_id: 订单ID（引擎生成或策略指定）
        symbol: 标的代码
        direction: 买卖方向（buy/sell/target），见 types.Direction
        volume: 委托数量
        filled_volume: 已成交数量
        avg_fill_price: 成交均价
        status: 订单状态（pending/submitted/partial/filled/cancelled/rejected）
        reason: 拒绝/撤销原因（可选）
    """

    # 类变量覆盖：OrderEvent 永远是 ORDER 类型
    type: ClassVar[EventType] = EventType.ORDER

    order_id: str = ""
    symbol: str = ""
    direction: str = ""
    volume: float = 0.0
    filled_volume: float = 0.0
    avg_fill_price: float = 0.0
    status: str = ""
    reason: Optional[str] = None


@dataclass
class TradeEvent(Event):
    """成交回报事件。

    每次撮合成交推送一次，对应一个 Fill 对象（见 types.Fill）。

    Attributes:
        fill_id: 成交ID（Execution 生成）
        order_id: 关联订单ID
        symbol: 标的代码
        direction: 买卖方向
        volume: 成交数量
        price: 成交价
        commission: 佣金
        stamp_tax: 印花税（仅卖出）
        transfer_fee: 过户费
    """

    # 类变量覆盖：TradeEvent 永远是 TRADE 类型
    type: ClassVar[EventType] = EventType.TRADE

    fill_id: str = ""
    order_id: str = ""
    symbol: str = ""
    direction: str = ""
    volume: float = 0.0
    price: float = 0.0
    commission: float = 0.0
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0


@dataclass
class TimerEvent(Event):
    """定时器事件。

    由调度器在策略注册的触发时机推送。常见用途：
        - 调仓日（month_start/month_end/week_start）
        - 开盘前/收盘后做日终结算

    Attributes:
        name: 定时器名称（策略注册时指定，与 is_timer_due 配合使用）
        rule: 触发规则描述（仅用于日志/调试）
    """

    # 类变量覆盖：TimerEvent 永远是 TIMER 类型
    type: ClassVar[EventType] = EventType.TIMER

    name: str = ""
    rule: str = ""


@dataclass
class AccountEvent(Event):
    """账户资金变化事件。

    成交扣款、出入金等导致账户资金变化时推送。策略可据此刷新本地账户缓存。

    Attributes:
        cash: 当前可用现金
        frozen: 冻结资金（Pending 订单占用）
        market_value: 持仓市值
        total: 总资产 = cash + frozen + market_value
        pnl: 累计盈亏
        pnl_pct: 累计盈亏百分比
        daily_pnl: 当日盈亏
        daily_pnl_pct: 当日盈亏百分比
    """

    # 类变量覆盖：AccountEvent 永远是 ACCOUNT 类型
    type: ClassVar[EventType] = EventType.ACCOUNT

    cash: float = 0.0
    frozen: float = 0.0
    market_value: float = 0.0
    total: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0


@dataclass
class StopEvent(Event):
    """结束事件。

    引擎停止时推送一次，策略在 on_stop 中接收并完成资源清理。
    """

    # 类变量覆盖：StopEvent 永远是 STOP 类型
    type: ClassVar[EventType] = EventType.STOP
