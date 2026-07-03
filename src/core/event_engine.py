"""
src/core/event_engine.py
========================

事件总线模块（事件驱动内核的调度核心）。

EventEngine 是新版统一引擎的调度核心，负责：
    - 维护事件处理器注册表（EventType → List[handler]）
    - 接收 publish 的事件，按类型分发到对应 handler
    - 按 mode 选择调度策略：
        backtest → 同步单线程（无并发，结果可复现）
        paper    → 异步多线程（实时行情线程生产，主线程消费）
        live     → 异步多线程（实盘行情/订单回报异步推送）

设计要点（设计文档 3.4 节）：
    1. 三种模式共享同一个事件分发内核，差异仅在调度策略
    2. handler 签名：handler(event, context)
    3. 事件不阻塞：handler 中如果需要下单，通过 context.submit_order 异步提交

阶段1 实现：
    - 完整的注册/反注册/发布/分发机制
    - backtest 模式：同步处理已发布事件队列
    - live/paper 模式：后台线程消费事件队列（线程安全）
    - DataFeed/Execution/RiskManager 通过 setter 注入（本阶段可空）
    - 具体的 DataFeed 驱动循环在阶段 2/5 实现
"""

import logging
import queue
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from src.core.context import Context
from src.core.events import Event, EventType

# 事件处理器签名：handler(event, context) -> None
EventHandler = Callable[[Event, Context], None]

logger = logging.getLogger(__name__)


class EventEngine:
    """事件总线。

    生命周期：
        engine = EventEngine(mode="backtest")
        engine.register(handler, EventType.BAR)
        engine.set_risk_manager(rm)        # 可选，阶段3接入
        engine.set_execution(exec)         # 可选，阶段2接入
        engine.start(context)              # 启动调度
        engine.publish(event)              # 推送事件（可在外部或内部）
        engine.stop()                      # 停止

    Attributes:
        mode: 运行模式（"backtest"/"paper"/"live"）
        context: 当前上下文（start 时绑定）
        risk_manager: 风控管理器（阶段3接入，None 表示不启用风控）
        execution: 执行层（阶段2接入，None 表示不启用执行层）
    """

    def __init__(self, mode: str = "backtest") -> None:
        """初始化事件总线。

        Args:
            mode: 运行模式，取值：
                "backtest" - 回测，同步单线程
                "paper"    - 模拟盘，异步多线程
                "live"     - 实盘，异步多线程

        Raises:
            ValueError: mode 不在允许列表中
        """
        # 校验模式
        if mode not in ("backtest", "paper", "live"):
            raise ValueError(
                f"不支持的引擎模式 '{mode}'，允许值：backtest/paper/live"
            )
        self.mode: str = mode

        # 事件处理器注册表：EventType → handler 列表
        # 用 defaultdict 避免每个 EventType 都要预初始化空列表
        self._handlers: Dict[EventType, List[EventHandler]] = defaultdict(list)

        # 事件队列：线程安全，backtest 模式同步消费，live/paper 模式异步消费
        self._queue: "queue.Queue[Optional[Event]]" = queue.Queue()

        # 当前绑定的上下文（start 时设置，stop 后清空）
        self.context: Optional[Context] = None

        # 风控管理器（阶段3接入，由 RiskManager 实现填充）
        self.risk_manager: Optional[Any] = None
        # 执行层（阶段2接入，由 Execution 实现填充）
        self.execution: Optional[Any] = None

        # 后台消费线程（仅 live/paper 模式启动）
        self._consumer_thread: Optional[threading.Thread] = None
        # 停止标志：消费者线程轮询该标志决定是否退出
        self._stop_flag: threading.Event = threading.Event()

    # -------------------------------------------------------------------
    # 处理器注册
    # -------------------------------------------------------------------

    def register(self, handler: EventHandler, event_type: EventType) -> None:
        """注册事件处理器。

        同一 handler 可注册到多个 EventType；同一 EventType 可注册多个 handler，
        按注册顺序依次调用。

        Args:
            handler: 处理函数，签名 handler(event, context) -> None
            event_type: 事件类型
        """
        # 去重：同一 handler 在同一 event_type 下不重复注册
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def unregister(self, handler: EventHandler, event_type: EventType) -> bool:
        """反注册事件处理器。

        Args:
            handler: 处理函数
            event_type: 事件类型

        Returns:
            是否成功移除（handler 不存在时返回 False）
        """
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
            return True
        return False

    # -------------------------------------------------------------------
    # 依赖注入（阶段2/3接入）
    # -------------------------------------------------------------------

    def set_risk_manager(self, rm: Any) -> None:
        """注入风控管理器。

        由 RiskManager 实现填充（阶段3）。设置后，submit_order 路径会经过风控管线检查。

        Args:
            rm: RiskManager 实例
        """
        self.risk_manager = rm

    def set_execution(self, execution: Any) -> None:
        """注入执行层。

        由 Execution 实现填充（阶段2）。设置后，订单会送入执行层撮合。

        Args:
            execution: Execution 实例
        """
        self.execution = execution

    # -------------------------------------------------------------------
    # 事件发布
    # -------------------------------------------------------------------

    def publish(self, event: Event) -> None:
        """发布事件。

        - backtest 模式：直接同步分发（事件立即被处理，便于结果可复现）
        - live/paper 模式：放入队列，由后台消费者线程异步处理

        Args:
            event: 事件对象
        """
        if self.mode == "backtest":
            # 回测模式同步分发，保证事件处理顺序与发布顺序严格一致
            # context 在 start 后才有值；start 前 publish 直接分发（context=None）
            self._dispatch(event, self.context)
        else:
            # 模拟盘/实盘异步分发，事件入队后立即返回
            self._queue.put(event)

    # -------------------------------------------------------------------
    # 启动 / 停止
    # -------------------------------------------------------------------

    def start(self, context: Context) -> None:
        """启动事件总线。

        - backtest 模式：同步运行，处理完所有已入队事件后返回
        - live/paper 模式：启动后台消费者线程，立即返回

        Args:
            context: 策略上下文（由引擎注入）
        """
        self.context = context
        # 重置停止标志，支持 restart
        self._stop_flag.clear()

        if self.mode == "backtest":
            # 回测：同步模式，事件循环由 DataFeed 驱动（阶段2接入后填充实逻辑）
            # 阶段1 提供框架：drain 当前队列中的事件
            self._run_backtest(context)
        else:
            # 模拟盘/实盘：启动后台消费者线程
            self._run_live(context)

    def stop(self) -> None:
        """停止事件总线。

        - backtest 模式：无操作（同步运行已结束）
        - live/paper 模式：设置停止标志 + 投递哨兵 None 唤醒消费者线程
        """
        if self.mode == "backtest":
            # 回测模式同步执行，start 返回时已结束，stop 仅清理 context
            self.context = None
            return

        # 设置停止标志
        self._stop_flag.set()
        # 投递哨兵事件唤醒可能阻塞在 get() 上的消费者线程
        self._queue.put(None)

        # 等待消费者线程退出（timeout 避免死锁）
        if self._consumer_thread is not None and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=5.0)
            if self._consumer_thread.is_alive():
                logger.warning("事件消费者线程在 5 秒内未退出，可能存在阻塞")
        self._consumer_thread = None
        self.context = None

    # -------------------------------------------------------------------
    # 调度实现
    # -------------------------------------------------------------------

    def _run_backtest(self, context: Context) -> None:
        """回测模式调度（同步）。

        阶段1 实现：drain 当前队列中的所有事件，按 FIFO 同步分发。
        阶段2 接入 DataFeed 后，本方法将扩展为：
            1. 启动 DataFeed（加载历史数据）
            2. 推送 InitEvent
            3. 循环：DataFeed.next_bar() → publish(BarEvent) → 等待处理
            4. 推送 StopEvent
        """
        # 阶段1：仅处理已 publish 到队列的事件（backtest 模式 publish 走同步分发，
        # 队列通常为空；此处保留以兼容未来 DataFeed 直接入队的场景）
        while not self._queue.empty():
            event = self._queue.get_nowait()
            if event is None:
                # 哨兵，忽略
                continue
            self._dispatch(event, context)

    def _run_live(self, context: Context) -> None:
        """实盘/模拟盘模式调度（异步）。

        启动后台消费者线程，循环从队列取事件并分发。
        DataFeed（阶段2接入）会从行情源异步生产事件入队。
        """
        self._consumer_thread = threading.Thread(
            target=self._consume_loop,
            name=f"EventEngine-{self.mode}",
            daemon=True,  # 守护线程：主进程退出时自动结束，避免阻塞退出
        )
        self._consumer_thread.start()

    def _consume_loop(self) -> None:
        """消费者线程主循环（live/paper 模式）。

        阻塞从队列取事件，遇到哨兵 None 或停止标志时退出。
        """
        while not self._stop_flag.is_set():
            try:
                # 阻塞获取，超时 1 秒以便定期检查停止标志
                event = self._queue.get(timeout=1.0)
            except queue.Empty:
                # 超时无事件，继续轮询停止标志
                continue

            # 哨兵：stop() 投递的 None，收到即退出
            if event is None:
                break

            # 分发事件（context 在 start 时已绑定）
            try:
                self._dispatch(event, self.context)
            except Exception:
                # 单个事件处理异常不应导致消费者线程退出
                # 详细异常已由 _dispatch 内部记录日志
                pass

    # -------------------------------------------------------------------
    # 事件分发
    # -------------------------------------------------------------------

    def _dispatch(self, event: Event, context: Optional[Context]) -> None:
        """分发单个事件到所有注册的 handler。

        按 EventType 查找 handler 列表，依次调用。
        单个 handler 异常不影响后续 handler 执行（隔离故障）。

        Args:
            event: 事件对象
            context: 策略上下文（start 前可能为 None）
        """
        handlers = self._handlers.get(event.type, [])
        if not handlers:
            # 无 handler 注册的事件类型，跳过（避免日志噪音）
            return

        for handler in handlers:
            try:
                handler(event, context)
            except Exception:
                # 隔离故障：单个 handler 异常不阻断其他 handler
                logger.exception(
                    "事件处理器异常: event_type=%s handler=%s",
                    event.type.value,
                    getattr(handler, "__name__", repr(handler)),
                )

    # -------------------------------------------------------------------
    # 状态查询
    # -------------------------------------------------------------------

    def is_running(self) -> bool:
        """事件总线是否在运行（仅 live/paper 模式有意义）。"""
        return (
            self._consumer_thread is not None
            and self._consumer_thread.is_alive()
        )

    def pending_events(self) -> int:
        """队列中待处理事件数量（用于监控积压）。"""
        return self._queue.qsize()
