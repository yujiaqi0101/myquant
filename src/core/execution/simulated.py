"""
src/core/execution/simulated.py
===============================

SimulatedExecution 模拟撮合执行层（回测/模拟盘）。

在内存中模拟订单撮合，支持四种价格类型：
    - market：当前市价即时成交
    - limit：限价单（触及限价成交，否则挂起）
    - next_open：次日开盘价成交（登记 Pending，T+1 撮合）
    - target_percent：目标权重调仓（与 direction=TARGET 配合，引擎折算 delta）

目标权重计算（设计文档 4.2 节）：
    目标股数 = floor(总资产 × target_weight / 价格 / lot_size) × lot_size
    delta = 目标股数 - 当前持仓（正数买、负数卖、0 不动）
    lot_size：688开头200股/手，其他100股/手（get_lot_size）

T+1 规则：
    卖出时校验 portfolio.get_position(symbol)["available"]，不足则拒绝。
    今日买入量不可卖，次日开盘由 Portfolio.settle_new_day() 解冻。

用法：
    from src.core.execution.simulated import SimulatedExecution
    exec_ = SimulatedExecution(portfolio, event_engine, mode="backtest")
    exec_.submit(order, current_price=10.0, current_time=clock)
    exec_.process_pending_orders(clock, {"600000.SH": 10.5})  # 次日开盘撮合
"""

import logging
import math
from datetime import datetime
from typing import Any, Dict, Optional

from src.core.event_engine import EventEngine
from src.core.execution.base import Execution
from src.core.types import Direction, Fill, Order, OrderStatus, get_lot_size

logger = logging.getLogger(__name__)


class SimulatedExecution(Execution):
    """模拟撮合执行层。

    Attributes:
        mode: 运行模式（"backtest" 回测 / "paper" 模拟盘）
        _pending_orders: Pending 订单池（next_open 类型），order_id -> Order
        _last_time: 最近一次撮合时间（cancel 时作为事件时间回退用）
    """

    def __init__(self, portfolio: Any, event_engine: EventEngine, mode: str = "backtest") -> None:
        """初始化模拟撮合执行层。

        Args:
            portfolio: Portfolio 实例（阶段4实现）
            event_engine: 事件总线实例
            mode: 运行模式，"backtest" 或 "paper"

        Raises:
            ValueError: mode 不在允许列表中
        """
        super().__init__(portfolio, event_engine)
        # 校验模式
        if mode not in ("backtest", "paper"):
            raise ValueError(f"不支持的 SimulatedExecution 模式 '{mode}'，允许：backtest/paper")
        self.mode = mode
        # Pending 订单池：next_open 类型订单等待次日开盘撮合
        self._pending_orders: Dict[str, Order] = {}
        # 最近一次撮合时间，cancel 签名无 current_time 时用作回退
        self._last_time: Optional[datetime] = None

    # ------------------------------------------------------------------
    # 提交订单
    # ------------------------------------------------------------------

    def submit(self, order: Order, current_price: float, current_time: datetime) -> None:
        """提交订单到模拟撮合。

        分三种路径：
            1. direction=TARGET：折算为目标数量后转 buy/sell
            2. price_type=next_open：登记 Pending，等待次日开盘
            3. market/limit：即时撮合

        Args:
            order: 订单对象
            current_price: 当前市价
            current_time: 当前时间
        """
        # 记录最近时间，cancel 时回退使用
        self._last_time = current_time

        # 路径1：目标权重订单，折算成 buy/sell
        if order.direction is Direction.TARGET:
            self._process_target_order(order, current_price, current_time)
            return

        # 路径2：next_open 订单，登记 Pending 等待次日开盘
        if order.price_type == "next_open":
            order.status = OrderStatus.PENDING
            self._pending_orders[order.order_id] = order
            self._emit_order_event(
                order, current_time, OrderStatus.PENDING, reason="等待次日开盘价撮合"
            )
            return

        # 路径3：market / limit，计算撮合价后即时撮合
        fill_price = self._compute_fill_price(order, current_price)
        if fill_price is None:
            # 限价未触及：挂起为 PENDING（回测中暂不自动重试，等待下次 submit 或策略撤单）
            order.status = OrderStatus.PENDING
            self._emit_order_event(
                order, current_time, OrderStatus.SUBMITTED, reason="限价未触及，挂起等待"
            )
            return
        self._fill_order(order, fill_price, current_time)

    def _compute_fill_price(self, order: Order, current_price: float) -> Optional[float]:
        """根据价格类型计算撮合价。

        - market：当前市价
        - limit：限价单，买入时当前价<=限价触发，卖出时当前价>=限价触发；未触及返回 None

        Args:
            order: 订单对象
            current_price: 当前市价

        Returns:
            撮合价；限价未触及返回 None
        """
        # 市价单：直接用当前价
        if order.price_type == "market":
            return current_price
        # 限价单
        if order.price_type == "limit":
            # 限价未指定：降级为市价
            if order.price is None:
                return current_price
            # 买入：当前价 <= 限价才能买到
            if order.direction is Direction.BUY and current_price <= order.price:
                return order.price
            # 卖出：当前价 >= 限价才能卖出
            if order.direction is Direction.SELL and current_price >= order.price:
                return order.price
            # 未触及限价
            return None
        # target_percent 已在 _process_target_order 中折算，不应走到这里；兜底用当前价
        return current_price

    def _process_target_order(self, order: Order, current_price: float, current_time: datetime) -> None:
        """目标权重订单折算为按数量的 buy/sell。

        计算逻辑：
            目标股数 = floor(总资产 × target_weight / 价格 / lot_size) × lot_size
            delta = 目标股数 - 当前持仓
            delta>0 买入，delta<0 卖出，delta==0 不动

        Args:
            order: 目标权重订单（direction=TARGET）
            current_price: 当前市价
            current_time: 当前时间
        """
        # 校验 target_weight
        if order.target_weight is None:
            order.status = OrderStatus.REJECTED
            self._emit_order_event(
                order, current_time, OrderStatus.REJECTED, reason="TARGET 订单缺少 target_weight"
            )
            return
        # 校验价格有效性
        if current_price <= 0:
            order.status = OrderStatus.REJECTED
            self._emit_order_event(
                order, current_time, OrderStatus.REJECTED, reason="当前价格无效，无法计算目标数量"
            )
            return

        # 获取账户总资产（Portfolio.get_account 返回 AccountInfo 对象）
        account = self._portfolio.get_account()
        total = account.total if account is not None else 0.0
        # lot_size 按 symbol 判断（688开头200，其他100）
        lot_size = get_lot_size(order.symbol)
        # 目标数量 = floor(总资产 × 权重 / 价格 / lot_size) × lot_size
        raw_qty = total * order.target_weight / current_price / lot_size
        target_qty = math.floor(raw_qty) * lot_size

        # 当前持仓数量（Portfolio.get_position 返回 Position 对象或 None）
        pos = self._portfolio.get_position(order.symbol)
        current_qty = pos.quantity if pos is not None else 0.0
        # delta = 目标 - 当前
        delta = target_qty - current_qty

        if delta > 0:
            # 买入 delta 股
            order.direction = Direction.BUY
            order.volume = float(delta)
            self._fill_order(order, current_price, current_time)
        elif delta < 0:
            # 卖出 |delta| 股
            order.direction = Direction.SELL
            order.volume = float(abs(delta))
            self._fill_order(order, current_price, current_time)
        else:
            # delta == 0：目标已满足，无需调仓，标记为成交（0 数量）
            order.status = OrderStatus.FILLED
            order.filled_volume = 0.0
            order.filled_price = current_price
            self._emit_order_event(
                order, current_time, OrderStatus.FILLED, reason="目标权重已满足，无需调仓"
            )

    def _fill_order(self, order: Order, fill_price: float, current_time: datetime) -> None:
        """执行撮合：校验、计算费用、更新持仓、推送事件。

        步骤：
            1. 卖出校验 available（T+1），不足则拒绝
            2. 计算A股费用
            3. 更新订单状态为 FILLED
            4. 调用 portfolio.update_on_fill 更新持仓和现金
            5. 构造 Fill 推送 TradeEvent
            6. 推送 OrderEvent(filled)

        Args:
            order: 订单对象（direction 已确定为 BUY/SELL）
            fill_price: 撮合价
            current_time: 当前时间
        """
        # 卖出校验可用数量（T+1 约束）
        if order.direction is Direction.SELL:
            pos = self._portfolio.get_position(order.symbol)
            available = pos.available if pos is not None else 0.0
            if order.volume > available + 1e-9:
                # 可用不足：拒绝订单
                order.status = OrderStatus.REJECTED
                self._emit_order_event(
                    order, current_time, OrderStatus.REJECTED,
                    reason=f"可用数量不足（T+1）：需 {order.volume}，可用 {available}",
                )
                return

        # 计算A股交易费用
        cost = self._calculate_cost(order.direction, order.volume, fill_price)

        # 更新订单状态为全部成交（模拟撮合默认一次性全成）
        order.status = OrderStatus.FILLED
        order.filled_volume = order.volume
        order.filled_price = fill_price

        # 构造 Fill 对象（含费用明细）
        fill = Fill(
            fill_id=f"fill_{order.order_id}",
            order_id=order.order_id,
            symbol=order.symbol,
            direction=order.direction,
            volume=order.volume,
            price=fill_price,
            commission=cost["commission"],
            stamp_tax=cost["stamp_tax"],
            transfer_fee=cost["transfer_fee"],
            fill_time=current_time,
        )
        # 调用 Portfolio.apply_fill 更新持仓/现金/FIFO 配对
        # apply_fill 内部根据 direction 核算现金流并生成 Trade（卖出时）
        self._portfolio.apply_fill(fill)
        # 记录订单到 Portfolio 流水
        self._portfolio.record_order(order)
        # 推送成交回报事件
        self._emit_trade_event(fill, current_time)
        # 推送订单成交事件
        self._emit_order_event(order, current_time, OrderStatus.FILLED)

    # ------------------------------------------------------------------
    # Pending 订单处理与撤单
    # ------------------------------------------------------------------

    def process_pending_orders(self, current_time: datetime, open_prices: Dict[str, float]) -> None:
        """次日开盘撮合所有 Pending（next_open）订单。

        遍历 Pending 池，用当日开盘价撮合。symbol 无开盘价（可能停牌）的订单保留待下一日。

        Args:
            current_time: 当前时间（开盘时间）
            open_prices: 当日开盘价字典 {symbol: price}
        """
        # 记录最近时间
        self._last_time = current_time
        # 复制键集合，避免撮合过程中修改字典导致迭代异常
        for order_id in list(self._pending_orders.keys()):
            order = self._pending_orders.get(order_id)
            if order is None:
                continue
            # symbol 无开盘价（停牌等）：跳过，保留待下一日撮合
            if order.symbol not in open_prices:
                continue
            fill_price = open_prices[order.symbol]
            # 取出 Pending 订单
            self._pending_orders.pop(order_id, None)
            # 用开盘价撮合
            self._fill_order(order, fill_price, current_time)

    def cancel(self, order_id: str) -> bool:
        """撤销订单。仅支持 Pending（next_open）订单。

        已进入撮合（market/limit 即时成交）的订单不支持撤销。

        Args:
            order_id: 订单ID

        Returns:
            是否撤销成功（订单不在 Pending 池中返回 False）
        """
        # 从 Pending 池移除
        order = self._pending_orders.pop(order_id, None)
        if order is None:
            logger.warning(
                "撤单失败：订单 %s 不在 Pending 池中（仅支持 Pending 订单撤销）", order_id
            )
            return False
        # 标记为已撤销
        order.status = OrderStatus.CANCELLED
        # cancel 签名无 current_time，用最近一次撮合时间回退；无则用墙钟时间
        ts = self._last_time if self._last_time is not None else datetime.now()
        self._emit_order_event(order, ts, OrderStatus.CANCELLED, reason="用户撤销")
        return True
