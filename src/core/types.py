"""
src/core/types.py
=================

统一数据结构模块（事件驱动内核的领域模型）。

本模块定义引擎流转过程中所有"领域对象"的统一数据结构：
    - 4 个枚举：Direction / PositionDirection / OpenClose / OrderStatus
    - 4 个 dataclass：Order / Fill / Trade / Position

设计目标（设计文档第 6.1 节）：
    1. 支持期货期权多空方向扩展（当前 A 股仅多头，架构预留空头）
    2. Position 内置 T+1 处理（today_bought 冻结，settle_new_day 解冻）
    3. lot_size 规则：688 开头（科创板）200 股/手，其他 100 股/手
    4. A 股费用拆分（佣金/印花税/过户费）独立字段，便于报表统计

不依赖引擎内部组件，可被 strategies / execution / portfolio / persistence 等任意模块导入。

用法示例：
    from src.core.types import Order, Direction, OrderStatus
    o = Order(order_id="o1", symbol="600000.SH", direction=Direction.BUY, volume=100)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# 枚举定义
# ---------------------------------------------------------------------------


class Direction(str, Enum):
    """订单买卖方向。

    TARGET 是"目标权重"模式：策略只指定目标持仓权重，
    引擎根据当前持仓自动计算 delta（正数买、负数卖、0 不动）。
    """

    BUY = "buy"          # 按数量买入
    SELL = "sell"        # 按数量卖出
    TARGET = "target"    # 目标权重调仓（与 price_type="target_percent" 配合）


class PositionDirection(str, Enum):
    """持仓方向。

    A 股股票默认多头（LONG）。架构预留 SHORT 以支持期货/期权卖出开仓。
    """

    LONG = "long"        # 多头
    SHORT = "short"      # 空头


class OpenClose(str, Enum):
    """开平方向（用于 Trade 配对标注）。

    A 股股票只用到 OPEN_LONG / CLOSE_LONG。
    OPEN_SHORT / CLOSE_SHORT 预留给期货/期权。
    """

    OPEN_LONG = "open_long"        # 多开
    CLOSE_LONG = "close_long"      # 多平
    OPEN_SHORT = "open_short"      # 空开（期货/期权）
    CLOSE_SHORT = "close_short"    # 空平（期货/期权）


class OrderStatus(str, Enum):
    """订单状态。

    状态流转：
        PENDING   → 已提交但未进入撮合（如 next_open 订单等待次日开盘）
        SUBMITTED → 已进入撮合队列
        PARTIAL   → 部分成交
        FILLED    → 全部成交
        CANCELLED → 已撤销
        REJECTED  → 已拒绝（风控或交易所）
    """

    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def get_lot_size(symbol: str) -> int:
    """获取标的最小交易手数对应的股数。

    A 股规则：
        - 688 开头（科创板）：200 股/手
        - 其他：100 股/手

    Args:
        symbol: 标的代码，如 "688001.SH" 或 "688001"

    Returns:
        每手对应的股数（200 或 100）
    """
    # 取 symbol 的纯数字部分做前缀判断，兼容 "688001.SH" / "SHSE.688001" 等格式
    digits = "".join(ch for ch in symbol if ch.isdigit())
    if digits.startswith("688"):
        return 200
    return 100


# ---------------------------------------------------------------------------
# Order：订单
# ---------------------------------------------------------------------------


@dataclass
class Order:
    """订单数据结构。

    由策略通过 context.submit_order() 创建，经风控管线检查后送入 Execution。

    支持两种下单方式：
        1. 按数量：direction=BUY/SELL + volume
        2. 按目标权重：direction=TARGET + target_weight + price_type="target_percent"
           （引擎自动计算目标股数 = floor(总资产 × weight / 价格 / lot_size) × lot_size）

    Attributes:
        order_id: 订单ID（引擎生成，若策略未指定则自动生成）
        symbol: 标的代码
        direction: 买卖方向（Direction 枚举）
        volume: 委托数量（按数量下单时使用，TARGET 模式下由引擎计算后回填）
        target_weight: 目标持仓权重 0-1（仅 direction=TARGET 时使用）
        price_type: 价格类型（market/limit/next_open/target_percent）
        price: 限价单价格（price_type=limit 时使用，其他为 None）
        status: 订单状态
        created_time: 订单创建时间
        filled_volume: 已成交数量
        filled_price: 成交均价
    """

    order_id: str = ""
    symbol: str = ""
    direction: Direction = Direction.BUY
    volume: float = 0.0
    target_weight: Optional[float] = None
    price_type: str = "market"
    price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    created_time: Optional[datetime] = None
    filled_volume: float = 0.0
    filled_price: float = 0.0

    @property
    def remaining_volume(self) -> float:
        """未成交数量 = 委托数量 - 已成交数量"""
        return self.volume - self.filled_volume

    @property
    def is_active(self) -> bool:
        """订单是否仍在生效（未终结）。

        PENDING/SUBMITTED/PARTIAL 视为活跃，可继续撮合或撤销；
        FILLED/CANCELLED/REJECTED 视为终结。
        """
        return self.status in (
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIAL,
        )


# ---------------------------------------------------------------------------
# Fill：成交记录
# ---------------------------------------------------------------------------


@dataclass
class Fill:
    """成交记录。

    每次撮合成交生成一个 Fill，对应一个 TradeEvent。
    A 股费用拆分为三项：佣金（双向）/ 印花税（仅卖出）/ 过户费（双向）。

    Attributes:
        fill_id: 成交ID（Execution 生成）
        order_id: 关联订单ID
        symbol: 标的代码
        direction: 买卖方向
        volume: 成交数量
        price: 成交价
        commission: 佣金（双向，费率 0.025%，最低 5 元）
        stamp_tax: 印花税（仅卖出，费率 0.05%）
        transfer_fee: 过户费（双向，费率 0.002%）
        fill_time: 成交时间
    """

    fill_id: str = ""
    order_id: str = ""
    symbol: str = ""
    direction: Direction = Direction.BUY
    volume: float = 0.0
    price: float = 0.0
    commission: float = 0.0
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0
    fill_time: Optional[datetime] = None

    @property
    def turnover(self) -> float:
        """成交金额 = 成交数量 × 成交价"""
        return self.volume * self.price

    @property
    def total_cost(self) -> float:
        """成交总成本 = 成交金额 + 佣金 + 印花税 + 过户费。

        买入时为现金流出（正数），卖出时为现金流入的抵减项。
        注意：卖出时 turnover 是回收的现金，total_cost 仅表示费用合计，
        净现金流 = -turnover + total_cost（卖出）或 -turnover - total_cost（买入），
        具体符号由调用方根据 direction 解释。
        """
        return self.commission + self.stamp_tax + self.transfer_fee


# ---------------------------------------------------------------------------
# Trade：平仓交易记录
# ---------------------------------------------------------------------------


@dataclass
class Trade:
    """平仓交易记录（开仓与平仓配对后生成）。

    由 Portfolio 维护 FIFO 配对：买入时记录待平仓头寸，
    卖出时与开仓配对生成 Trade 并计算盈亏。

    Attributes:
        trade_id: 交易ID
        symbol: 标的代码
        direction: 持仓方向（LONG/SHORT）
        open_close: 开平方向（OPEN_LONG/CLOSE_LONG/...）
        open_time: 开仓时间
        open_price: 开仓均价
        close_time: 平仓时间
        close_price: 平仓均价
        volume: 平仓数量
        pnl: 盈亏金额（close_price - open_price）× volume（多头）
        pnl_pct: 盈亏百分比 = pnl / (open_price × volume)
        holding_days: 持仓天数
    """

    trade_id: str = ""
    symbol: str = ""
    direction: PositionDirection = PositionDirection.LONG
    open_close: OpenClose = OpenClose.CLOSE_LONG
    open_time: Optional[datetime] = None
    open_price: float = 0.0
    close_time: Optional[datetime] = None
    close_price: float = 0.0
    volume: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    holding_days: int = 0


# ---------------------------------------------------------------------------
# Position：单个标的持仓
# ---------------------------------------------------------------------------


@dataclass
class Position:
    """单个标的持仓。

    由 Portfolio 按 symbol 维护。内置 T+1 处理：
        - today_bought: 今日买入量（不可卖，次日开盘转入 available）
        - available: 可卖数量 = quantity - today_bought

    Attributes:
        symbol: 标的代码
        direction: 持仓方向（A 股默认 LONG）
        quantity: 总持仓数量
        available: 可卖数量（T+1 后解冻）
        avg_price: 持仓均价
        market_price: 最新市价
        market_value: 市值 = quantity × market_price
        cost: 持仓成本 = quantity × avg_price
        pnl: 浮动盈亏 = market_value - cost
        pnl_pct: 浮动盈亏百分比 = pnl / cost
        today_bought: 今日买入量（T+1 冻结，settle_new_day 后清零）
    """

    symbol: str = ""
    direction: PositionDirection = PositionDirection.LONG
    quantity: float = 0.0
    available: float = 0.0
    avg_price: float = 0.0
    market_price: float = 0.0
    market_value: float = 0.0
    cost: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    today_bought: float = 0.0

    # ----- 撮合回调 -----

    def update_on_fill(self, direction: Direction, volume: float, price: float) -> None:
        """根据成交回报更新持仓。

        T+1 规则：
            - 买入：quantity += volume，today_bought += volume（available 不变）
            - 卖出：必须 available >= volume，卖出后 quantity -= volume，available -= volume

        均价计算（仅多头买入时更新）：
            新均价 = (旧成本 + 买入金额) / 新数量

        Args:
            direction: 买卖方向（BUY/SELL）
            volume: 成交数量（正数）
            price: 成交价

        Raises:
            ValueError: 卖出时可用数量不足
        """
        if volume <= 0:
            return

        if direction is Direction.BUY:
            # 买入：累加数量，按加权平均更新均价
            old_cost = self.cost
            new_cost = old_cost + volume * price
            self.quantity += volume
            # 均价 = 总成本 / 总数量（数量为 0 时均价清零避免除零）
            self.avg_price = new_cost / self.quantity if self.quantity > 0 else 0.0
            self.cost = new_cost
            # T+1：今日买入记入 today_bought，available 不变
            self.today_bought += volume
        elif direction is Direction.SELL:
            # 卖出：校验可用数量（T+1 约束）
            if volume > self.available + 1e-9:
                raise ValueError(
                    f"卖出数量 {volume} 超过可用数量 {self.available}（symbol={self.symbol}）"
                )
            self.quantity -= volume
            self.available -= volume
            # 卖出后数量为 0：清零均价和成本，便于重新建仓
            if self.quantity <= 1e-9:
                self.quantity = 0.0
                self.avg_price = 0.0
                self.cost = 0.0
            else:
                # 持仓成本按比例减少（均价不变）
                self.cost = self.quantity * self.avg_price
        # direction=TARGET 不应直接走本方法，由 Execution 折算成 BUY/SELL 后再调用

        # 同步市价相关派生字段（成交价作为最新价）
        self.update_market_price(price)

    def update_market_price(self, price: float) -> None:
        """更新市价及派生字段（市值/盈亏）。

        在 BarEvent 推送或成交后调用。

        Args:
            price: 最新市价
        """
        self.market_price = price
        self.market_value = self.quantity * price
        # 浮动盈亏 = 市值 - 成本
        self.pnl = self.market_value - self.cost
        # 盈亏百分比 = 盈亏 / 成本（成本为 0 时为 0，避免除零）
        self.pnl_pct = self.pnl / self.cost if self.cost > 0 else 0.0

    def settle_new_day(self) -> None:
        """T+1 日终结算：今日买入转入可卖，今日买入清零。

        引擎在每日开盘前（或上一交易日收盘后）调用，将 today_bought 解冻。
        """
        # 今日买入量转入可卖
        self.available += self.today_bought
        self.today_bought = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于持久化/日志/JSON 序列化）。"""
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "quantity": self.quantity,
            "available": self.available,
            "avg_price": self.avg_price,
            "market_price": self.market_price,
            "market_value": self.market_value,
            "cost": self.cost,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "today_bought": self.today_bought,
        }
