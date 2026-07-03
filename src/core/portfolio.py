"""
src/core/portfolio.py
=====================

Portfolio 持仓管理模块（事件驱动内核的账户与持仓状态机）。

本模块维护引擎运行期间的账户资金、持仓、订单、成交、平仓配对等全部状态，
是回测/模拟盘/实盘共用的核心领域对象。Portfolio 本身是纯内存状态机，
不感知数据库与运行模式；持久化由 persistence.PersistenceRepository 负责。

设计目标（设计文档第 6.1 节）：
    1. 内置 T+1 处理：委托 Position.settle_new_day()，每日开盘解冻
    2. FIFO 开仓/平仓配对：买入记录待平仓头寸，卖出按先进先出配对生成 Trade
    3. 现金流自动核算：买入扣现金（金额+费用），卖出现金回笼（金额-费用）
    4. 不依赖数据库：纯内存，回测模式零持久化开销

核心数据流：
    Execution 撮合成交 → 生成 Fill → Portfolio.apply_fill(fill)
        → 更新 Position（含 T+1）→ 更新现金 → FIFO 配对生成 Trade
    DataFeed 推送 BarEvent → Portfolio.update_market_prices(prices)
        → 更新市值/浮动盈亏 → snapshot() 记录净值曲线

用法示例：
    from src.core.portfolio import Portfolio
    pf = Portfolio(initial_capital=1_000_000.0)
    pf.apply_fill(fill)              # 处理成交
    pf.update_market_prices(prices)  # 更新市价
    pf.settle_new_day()              # 日终 T+1 解冻
    acct = pf.get_account()          # 取账户快照
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.core.types import (
    Direction,
    Fill,
    OpenClose,
    Order,
    Position,
    PositionDirection,
    Trade,
)


# ---------------------------------------------------------------------------
# 账户快照数据结构
# ---------------------------------------------------------------------------


@dataclass
class AccountInfo:
    """账户资金快照（某一时点的账户状态）。

    由 Portfolio.get_account() 生成，用于 AccountEvent 推送和持久化。

    Attributes:
        cash: 可用现金
        frozen: 冻结资金（Pending 订单占用，回测简化为 0）
        market_value: 持仓总市值
        total: 总资产 = cash + frozen + market_value
        initial_capital: 初始资金
        peak_value: 历史峰值总资产（用于最大回撤）
        pnl: 累计盈亏 = total - initial_capital
        pnl_pct: 累计盈亏百分比 = pnl / initial_capital
        daily_pnl: 当日盈亏（相对上一交易日总资产）
        daily_pnl_pct: 当日盈亏百分比
    """

    cash: float = 0.0
    frozen: float = 0.0
    market_value: float = 0.0
    total: float = 0.0
    initial_capital: float = 0.0
    peak_value: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（持久化/日志用）。"""
        return {
            "cash": self.cash,
            "frozen": self.frozen,
            "market_value": self.market_value,
            "total": self.total,
            "initial_capital": self.initial_capital,
            "peak_value": self.peak_value,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_pct": self.daily_pnl_pct,
        }


# ---------------------------------------------------------------------------
# 待平仓头寸（FIFO 配对单元）
# ---------------------------------------------------------------------------


@dataclass
class OpenLot:
    """待平仓头寸（FIFO 配对用）。

    每次买入成交生成一个 OpenLot，卖出时按先进先出消费。
    一个 symbol 维护一个 OpenLot 队列，部分平仓时 remaining 递减。

    Attributes:
        symbol: 标的代码
        open_time: 开仓时间（成交时间）
        open_price: 开仓均价
        remaining: 剩余未平仓数量
    """

    symbol: str = ""
    open_time: Optional[datetime] = None
    open_price: float = 0.0
    remaining: float = 0.0


# ---------------------------------------------------------------------------
# Portfolio：持仓管理状态机
# ---------------------------------------------------------------------------


class Portfolio:
    """持仓管理状态机。

    维护引擎运行期间的账户资金、持仓、订单、成交、平仓配对等全部状态。
    纯内存对象，不感知运行模式，由引擎驱动状态流转。

    核心职责：
        1. 处理成交回报（apply_fill）：更新持仓 + 现金 + FIFO 配对
        2. 更新市价（update_market_prices）：刷新市值/浮动盈亏
        3. T+1 结算（settle_new_day）：解冻今日买入
        4. 账户快照（get_account）：返回当前资金状态
        5. 净值曲线（snapshot）：记录每日总资产，供绩效计算

    Parameters
    ----------
    initial_capital : float
        初始资金（如 1_000_000.0）
    """

    def __init__(self, initial_capital: float):
        # 资金状态
        self.initial_capital: float = float(initial_capital)
        self.cash: float = float(initial_capital)
        self.frozen: float = 0.0
        # 峰值总资产（用于最大回撤计算）
        self.peak_value: float = float(initial_capital)
        # 上一交易日总资产（用于当日盈亏计算）
        self._last_total: float = float(initial_capital)
        self.daily_pnl: float = 0.0

        # 持仓：{symbol: Position}
        self.positions: Dict[str, Position] = {}
        # 订单流水（全部，含未成交/拒绝）
        self.orders: List[Order] = []
        # 成交流水（全部）
        self.fills: List[Fill] = []
        # 平仓配对后的交易记录（含盈亏）
        self.trades: List[Trade] = []
        # FIFO 待平仓队列：{symbol: [OpenLot, ...]}
        self.open_lots: Dict[str, List[OpenLot]] = {}

        # 净值曲线：[(datetime, total_value), ...]
        # 由 snapshot() 在每日收盘后追加，供绩效指标计算
        self.equity_curve: List[Tuple[datetime, float]] = []
        # 每日日期列表（与 equity_curve 对齐）
        self.trade_dates: List[datetime] = []

        # 内部计数器（生成 trade_id）
        self._trade_counter: int = 0

    # ------------------------------------------------------------------
    # 成交处理
    # ------------------------------------------------------------------

    def apply_fill(self, fill: Fill) -> Optional[Trade]:
        """处理成交回报，更新持仓/现金/平仓配对。

        流程：
            1. 获取或创建 Position
            2. 调用 Position.update_on_fill 更新持仓（含 T+1）
            3. 核算现金流（买入扣现金，卖出现金回笼）
            4. 买入：记录 OpenLot 到 FIFO 队列
            5. 卖出：与最早 OpenLot 配对生成 Trade（含盈亏）

        Args:
            fill: 成交记录（含 commission/stamp_tax/transfer_fee）

        Returns:
            卖出成交时返回生成的 Trade；买入成交返回 None
        """
        self.fills.append(fill)
        symbol = fill.symbol
        pos = self.positions.get(symbol)

        # 现金流核算：买入扣现金，卖出现金回笼
        # Fill.total_cost = commission + stamp_tax + transfer_fee
        # 买入：cash -= (turnover + total_cost)
        # 卖出：cash += (turnover - total_cost)
        turnover = fill.turnover
        total_fee = fill.total_cost

        if fill.direction is Direction.BUY:
            # 买入：建仓或加仓
            if pos is None:
                pos = Position(symbol=symbol, direction=PositionDirection.LONG)
                self.positions[symbol] = pos
            pos.update_on_fill(Direction.BUY, fill.volume, fill.price)
            # 扣减现金（成交金额 + 费用）
            self.cash -= (turnover + total_fee)
            # 记录待平仓头寸（FIFO 队列追加）
            self.open_lots.setdefault(symbol, []).append(
                OpenLot(
                    symbol=symbol,
                    open_time=fill.fill_time,
                    open_price=fill.price,
                    remaining=fill.volume,
                )
            )
            return None

        elif fill.direction is Direction.SELL:
            # 卖出：减仓（Position 已校验可用量）
            if pos is None:
                # 无持仓卖出（理论上风控已拦截），保守忽略
                return None
            pos.update_on_fill(Direction.SELL, fill.volume, fill.price)
            # 现金回笼（成交金额 - 费用）
            self.cash += (turnover - total_fee)
            # FIFO 配对生成 Trade
            trade = self._match_close(symbol, fill)
            return trade

        # direction=TARGET 不应进入此处（Execution 已折算为 BUY/SELL）
        return None

    def _match_close(self, symbol: str, fill: Fill) -> Optional[Trade]:
        """FIFO 配对平仓，生成 Trade（含盈亏计算）。

        消费 open_lots[symbol] 队首，部分平仓时递减 remaining。
        若队列耗尽仍有卖出量（异常情况），生成零开仓价的 Trade 兜底。

        Args:
            symbol: 标的代码
            fill: 卖出成交记录

        Returns:
            生成的 Trade（可能为 None，当无开仓记录可配对时）
        """
        lots = self.open_lots.get(symbol, [])
        remaining_sell = fill.volume
        close_price = fill.price
        close_time = fill.fill_time
        last_trade: Optional[Trade] = None

        while remaining_sell > 1e-9 and lots:
            lot = lots[0]
            # 本次平仓数量 = min(剩余卖出量, 该 lot 剩余量)
            close_qty = min(remaining_sell, lot.remaining)
            # 盈亏计算（多头）：(平仓价 - 开仓价) × 平仓数量
            pnl = (close_price - lot.open_price) * close_qty
            # 盈亏百分比 = 盈亏 / (开仓价 × 平仓数量)
            cost_basis = lot.open_price * close_qty
            pnl_pct = pnl / cost_basis if cost_basis > 0 else 0.0
            # 持仓天数（粗略计算：平仓日 - 开仓日）
            holding_days = 0
            if lot.open_time is not None and close_time is not None:
                delta = close_time - lot.open_time
                holding_days = max(0, delta.days)

            self._trade_counter += 1
            trade = Trade(
                trade_id=f"T{self._trade_counter:08d}",
                symbol=symbol,
                direction=PositionDirection.LONG,
                open_close=OpenClose.CLOSE_LONG,
                open_time=lot.open_time,
                open_price=lot.open_price,
                close_time=close_time,
                close_price=close_price,
                volume=close_qty,
                pnl=pnl,
                pnl_pct=pnl_pct,
                holding_days=holding_days,
            )
            self.trades.append(trade)
            last_trade = trade

            # 消费 lot
            lot.remaining -= close_qty
            remaining_sell -= close_qty
            if lot.remaining <= 1e-9:
                lots.pop(0)

        return last_trade

    # ------------------------------------------------------------------
    # 市价更新与日终结算
    # ------------------------------------------------------------------

    def update_market_prices(
        self,
        prices: Dict[str, float],
        timestamp: Optional[datetime] = None,
    ) -> None:
        """更新所有持仓的市价及派生字段（市值/浮动盈亏）。

        在 BarEvent 推送后或成交后调用。无持仓的 symbol 忽略。

        Args:
            prices: {symbol: 最新价} 字典
            timestamp: 当前时间（仅用于日志）
        """
        for symbol, price in prices.items():
            pos = self.positions.get(symbol)
            if pos is not None and pos.quantity > 1e-9:
                pos.update_market_price(price)

    def settle_new_day(self) -> None:
        """T+1 日终结算：所有持仓今日买入转入可卖。

        引擎在每日开盘前（或上一交易日收盘后）调用。
        将每个 Position 的 today_bought 解冻到 available。
        """
        for pos in self.positions.values():
            pos.settle_new_day()

    # ------------------------------------------------------------------
    # 账户快照与净值曲线
    # ------------------------------------------------------------------

    @property
    def market_value(self) -> float:
        """持仓总市值 = 所有持仓市值之和。"""
        return sum(p.market_value for p in self.positions.values() if p.quantity > 1e-9)

    @property
    def total_value(self) -> float:
        """总资产 = 现金 + 冻结 + 持仓市值。"""
        return self.cash + self.frozen + self.market_value

    def get_account(self) -> AccountInfo:
        """返回当前账户快照。

        包含现金/冻结/市值/总资产/峰值/累计盈亏/当日盈亏。
        """
        total = self.total_value
        # 更新峰值（用于最大回撤）
        if total > self.peak_value:
            self.peak_value = total
        # 当日盈亏 = 当前总资产 - 上一交易日总资产
        daily_pnl = total - self._last_total
        daily_pnl_pct = (
            daily_pnl / self._last_total if self._last_total > 0 else 0.0
        )
        self.daily_pnl = daily_pnl

        return AccountInfo(
            cash=self.cash,
            frozen=self.frozen,
            market_value=self.market_value,
            total=total,
            initial_capital=self.initial_capital,
            peak_value=self.peak_value,
            pnl=total - self.initial_capital,
            pnl_pct=(total - self.initial_capital) / self.initial_capital
            if self.initial_capital > 0
            else 0.0,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
        )

    def snapshot(self, timestamp: datetime) -> Dict[str, Any]:
        """记录每日净值快照，追加到权益曲线。

        引擎在每日收盘后调用，生成快照并更新净值曲线。
        同时刷新 _last_total 作为下一交易日当日盈亏的基准。

        Args:
            timestamp: 当前交易日时间戳

        Returns:
            快照字典（含日期/现金/市值/总资产/当日盈亏）
        """
        acct = self.get_account()
        # 追加净值曲线
        self.equity_curve.append((timestamp, acct.total))
        self.trade_dates.append(timestamp)
        # 刷新当日盈亏基准
        self._last_total = acct.total
        return {
            "timestamp": timestamp,
            "cash": acct.cash,
            "market_value": acct.market_value,
            "total": acct.total,
            "daily_pnl": acct.daily_pnl,
            "daily_pnl_pct": acct.daily_pnl_pct,
            "pnl": acct.pnl,
            "pnl_pct": acct.pnl_pct,
        }

    # ------------------------------------------------------------------
    # 持仓查询
    # ------------------------------------------------------------------

    def get_position(self, symbol: str) -> Optional[Position]:
        """查询单个标的持仓，无持仓返回 None。"""
        return self.positions.get(symbol)

    def get_positions(self) -> Dict[str, Position]:
        """返回全部持仓（含已平仓的零持仓，调用方按 quantity>0 过滤）。"""
        return self.positions

    def get_active_positions(self) -> Dict[str, Position]:
        """返回当前有效持仓（quantity > 0）。"""
        return {
            sym: pos for sym, pos in self.positions.items() if pos.quantity > 1e-9
        }

    # ------------------------------------------------------------------
    # 订单记录
    # ------------------------------------------------------------------

    def record_order(self, order: Order) -> None:
        """记录订单到流水（无论是否成交）。"""
        self.orders.append(order)

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """导出全部状态为字典（持久化/调试用）。"""
        return {
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "frozen": self.frozen,
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
            "orders": [self._order_to_dict(o) for o in self.orders],
            "fills": [self._fill_to_dict(f) for f in self.fills],
            "trades": [self._trade_to_dict(t) for t in self.trades],
            "equity_curve": [
                {"timestamp": ts.isoformat(), "total": val}
                for ts, val in self.equity_curve
            ],
        }

    @staticmethod
    def _order_to_dict(o: Order) -> Dict[str, Any]:
        return {
            "order_id": o.order_id,
            "symbol": o.symbol,
            "direction": o.direction.value,
            "volume": o.volume,
            "target_weight": o.target_weight,
            "price_type": o.price_type,
            "price": o.price,
            "status": o.status.value,
            "filled_volume": o.filled_volume,
            "filled_price": o.filled_price,
        }

    @staticmethod
    def _fill_to_dict(f: Fill) -> Dict[str, Any]:
        return {
            "fill_id": f.fill_id,
            "order_id": f.order_id,
            "symbol": f.symbol,
            "direction": f.direction.value,
            "volume": f.volume,
            "price": f.price,
            "commission": f.commission,
            "stamp_tax": f.stamp_tax,
            "transfer_fee": f.transfer_fee,
            "fill_time": f.fill_time.isoformat() if f.fill_time else None,
        }

    @staticmethod
    def _trade_to_dict(t: Trade) -> Dict[str, Any]:
        return {
            "trade_id": t.trade_id,
            "symbol": t.symbol,
            "direction": t.direction.value,
            "open_close": t.open_close.value,
            "open_time": t.open_time.isoformat() if t.open_time else None,
            "open_price": t.open_price,
            "close_time": t.close_time.isoformat() if t.close_time else None,
            "close_price": t.close_price,
            "volume": t.volume,
            "pnl": t.pnl,
            "pnl_pct": t.pnl_pct,
            "holding_days": t.holding_days,
        }
