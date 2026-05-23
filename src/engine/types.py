"""
通用回测引擎 - 核心数据类型定义

定义了回测过程中使用的所有核心数据结构，包括：
- Order: 订单
- TradeRecord: 成交记录
- Position: 持仓信息
- DailySnapshot: 每日账户快照
- BacktestResult: 回测结果
- Context: 策略上下文
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np


class Direction(Enum):
    """交易方向"""
    LONG = 1       # 做多
    SHORT = -1     # 做空


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"     # 市价单
    LIMIT = "limit"       # 限价单


@dataclass
class Order:
    """订单"""
    stock_code: str
    direction: Direction
    quantity: int
    price: float = 0.0          # 0 表示市价单
    order_type: OrderType = OrderType.MARKET
    reason: str = ""            # 下单原因（用于报告）


@dataclass
class TradeRecord:
    """成交记录"""
    date: pd.Timestamp
    stock_code: str
    direction: Direction
    action: str                  # "open" / "close"
    price: float
    quantity: int
    commission: float
    slippage: float
    pnl: float = 0.0             # 平仓时的盈亏
    reason: str = ""


@dataclass
class Position:
    """持仓信息"""
    stock_code: str
    direction: Direction
    quantity: int
    entry_price: float
    entry_date: pd.Timestamp
    entry_reason: str = ""
    highest_price: float = 0.0  # 持仓期间最高价（用于ATR跟踪止盈）
    # 扩展字段（策略可自定义）
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DailySnapshot:
    """
    每日账户快照 - 支持逐日检查
    
    这是回测过程中每天记录的核心数据结构，
    包含了完整的账户状态信息。
    """
    date: pd.Timestamp
    cash: float                          # 可用现金
    position_value: float                # 持仓市值
    total_value: float                   # 总资产
    n_positions: int                     # 持仓数量
    frozen_cash: float = 0.0             # 冻结资金（如空头保证金）
    daily_pnl: float = 0.0               # 当日盈亏
    daily_return: float = 0.0            # 当日收益率
    drawdown: float = 0.0                # 当前回撤
    max_drawdown: float = 0.0            # 历史最大回撤
    trades: List[TradeRecord] = field(default_factory=list)  # 当日成交记录
    risk_events: List[Dict] = field(default_factory=list)    # 当日风控事件


@dataclass
class BacktestResult:
    """
    回测结果 - 包含完整的历史记录，支持逐日检查
    """
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_return: float
    
    # 完整历史序列（可逐日检查）
    daily_snapshots: List[DailySnapshot]  # 每日快照
    trades: List[TradeRecord]             # 所有交易记录
    
    # 绩效指标
    performance: Dict[str, float] = field(default_factory=dict)
    
    # 风控报告
    risk_report: Dict = field(default_factory=dict)
    
    def get_daily_cashflow(self, date: str) -> Dict:
        """获取指定日期的现金流信息"""
        for snapshot in self.daily_snapshots:
            if snapshot.date.strftime('%Y-%m-%d') == date:
                return {
                    'date': date,
                    'cash': snapshot.cash,
                    'frozen_cash': snapshot.frozen_cash,
                    'inflow': sum(t.pnl for t in snapshot.trades if t.action == 'close' and t.pnl > 0),
                    'outflow': sum(t.commission + t.slippage for t in snapshot.trades),
                }
        return {}
    
    def get_daily_positions(self, date: str) -> List[Position]:
        """获取指定日期的持仓信息"""
        # 通过遍历交易记录重建指定日期的持仓
        positions = {}
        for trade in self.trades:
            if trade.date.strftime('%Y-%m-%d') > date:
                break
            if trade.action == 'open':
                positions[trade.stock_code] = Position(
                    stock_code=trade.stock_code,
                    direction=trade.direction,
                    quantity=trade.quantity,
                    entry_price=trade.price,
                    entry_date=trade.date,
                )
            elif trade.action == 'close':
                positions.pop(trade.stock_code, None)
        return list(positions.values())
    
    def get_trade_history(self, stock_code: str = None) -> List[TradeRecord]:
        """获取交易历史，可按股票代码过滤"""
        if stock_code:
            return [t for t in self.trades if t.stock_code == stock_code]
        return self.trades


@dataclass
class Context:
    """
    策略上下文 - 每个交易日传递给策略
    
    策略通过 context 获取市场数据和账户状态，
    通过返回 Order 列表来表达交易意图。
    
    数据访问说明：
    ----------------
    - market_data: 当日市场数据（只包含当前交易日的数据）
    - full_data: 完整历史数据（含预热期），只在 on_init 阶段可用
    - history: 回测历史净值序列（截至昨日）
    
    使用建议：
    - on_init 阶段：使用 full_data 预计算指标（如均线、因子等）
    - on_bar 阶段：使用 market_data 获取当日数据，使用 self.state 访问预计算指标
    """
    date: pd.Timestamp
    # 当日市场数据 {stock_code: {open, high, low, close, volume, ...}}
    market_data: Dict[str, Dict] = field(default_factory=dict)
    # 完整历史数据（含预热期），只在 on_init 阶段有意义
    full_data: Optional[pd.DataFrame] = field(default=None, repr=False)
    # 当前持仓 {stock_code: Position}
    positions: Dict[str, Position] = field(default_factory=dict)
    # 可用现金
    cash: float = 0.0
    # 冻结资金
    frozen_cash: float = 0.0
    # 总资产
    total_value: float = 0.0
    # 历史净值序列（截至昨日）
    history: List[DailySnapshot] = field(default_factory=list)
    # 策略参数（包含 stop_loss, take_profit 等）
    params: Dict[str, Any] = field(default_factory=dict)
    # 引擎内部状态（策略不应直接修改）
    _engine: Any = field(default=None, repr=False)
