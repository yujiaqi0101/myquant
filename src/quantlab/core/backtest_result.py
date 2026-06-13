"""
BacktestResult：所有回测引擎的统一输出

V1：保留 equity_curve / sharpe / trade_count / source / raw
raw 字段保留引擎原始输出（vbt.Portfolio / 老的 dict）
方便高级用法（plots / trade records）
"""

from dataclasses import (
    dataclass,
    field,
)
from typing import Any, List, Dict, Optional


@dataclass(slots=True)
class BacktestResult:

    # 核心指标
    equity_curve: Any

    total_return: float = 0.0

    sharpe: float = 0.0

    max_drawdown: float = 0.0

    trade_count: int = 0

    win_rate: float = 0.0

    final_equity: float = 0.0

    # 来源（"event" / "bar" / "vectorbt" / "vectorbt_subprocess"）
    source: str = "event"

    # 引擎原始输出（vbt.Portfolio / dict / 其他）
    raw: Any = None

    # 详细数据（Experiment / Report 用的）
    fills: List = field(
        default_factory=list
    )

    tradebook: Any = None

    portfolio: Any = None

    position_qty: Any = None

    signal: Any = None

    timestamps: Any = None

    # V2.0: 目标权重 DataFrame
    #   date × symbol, values ∈ [0, 1]
    #   VectorBT 路径生成
    #   BarEngine 路径暂为 None（每根 bar 调一次 constructor）
    weights_df: Any = None

    # 错误信息
    error: Optional[str] = None

    def ok(self) -> bool:
        return self.error is None

    def to_summary_dict(self) -> Dict:

        return {
            "source": self.source,
            "total_return": self.total_return,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "trade_count": self.trade_count,
            "win_rate": self.win_rate,
            "final_equity": self.final_equity,
        }

    @staticmethod
    def from_event_dict(raw: Dict) -> "BacktestResult":

        # 把 EventEngine / BarEngine 老的 dict
        # 转成 BacktestResult
        from ..analytics import (
            sharpe_ratio,
            max_drawdown,
            total_return,
        )
        from ..statistics import (
            win_rate,
        )

        portfolio = raw.get("portfolio")
        tradebook = raw.get("tradebook")
        equity = (
            portfolio.equity_curve
            if portfolio is not None
            else []
        )

        closed = (
            tradebook.closed_trades
            if tradebook is not None
            else []
        )

        return BacktestResult(
            equity_curve=equity,
            total_return=round(
                total_return(equity) * 100, 2
            ) if len(equity) > 0 else 0.0,
            sharpe=round(
                sharpe_ratio(equity), 3
            ) if len(equity) > 0 else 0.0,
            max_drawdown=round(
                max_drawdown(equity) * 100, 2
            ) if len(equity) > 0 else 0.0,
            trade_count=len(closed),
            win_rate=round(
                win_rate(closed) * 100, 2
            ) if closed else 0.0,
            final_equity=round(
                equity[-1], 2
            ) if len(equity) > 0 else 0.0,
            source="event",
            raw=raw,
            fills=raw.get("fills", []),
            tradebook=tradebook,
            portfolio=portfolio,
            position_qty=raw.get("position_qty"),
            signal=raw.get("signal"),
            timestamps=(
                portfolio.timestamps
                if portfolio is not None
                else None
            ),
        )
