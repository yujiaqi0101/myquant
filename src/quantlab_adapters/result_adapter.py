"""
ResultAdapter — quantlab BacktestResult → myquant BacktestResult。

quantlab 的 BacktestResult 走 equity_curve + portfolio + tradebook 模型；
myquant 的 BacktestResult 走 daily_snapshots + trades + performance 模型。
本模块负责把 quantlab 的结果翻译成 myquant 兼容结构，
让现有 HTML 报告、CLI `--show` 仍可工作。

注意：转换是"展示级"的（保留关键指标 + 简化时间序列），
不做交易明细的完全重建（quantlab 的 TradeBook 已经是最终 closed trades）。
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _safe_float(x, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def to_myquant_result(
    quantlab_result,
    strategy_name: str,
    initial_capital: float,
) -> "BacktestResult":
    """
    quantlab BacktestResult → myquant BacktestResult。

    Parameters
    ----------
    quantlab_result : src.quantlab.core.backtest_result.BacktestResult
    strategy_name : str
        策略名（用于报告）
    initial_capital : float

    Returns
    -------
    src.engine.types.BacktestResult
    """
    # 延迟 import：避免 quantlab_adapters 引用时强制加载整个 myquant engine
    from src.engine.types import (
        BacktestResult,
        DailySnapshot,
        TradeRecord,
        Direction,
    )

    ql = quantlab_result

    # ---- 1) equity_curve → daily_snapshots ----
    equity_curve = ql.equity_curve or []
    timestamps = ql.timestamps or []

    # quantlab 默认：equity_curve 长度 = timestamps 长度
    # 若 timestamps 为空而 portfolio 有，从 portfolio 拿
    portfolio = ql.portfolio
    if not timestamps and portfolio is not None:
        timestamps = portfolio.timestamps

    n = min(len(equity_curve), len(timestamps)) if timestamps else len(equity_curve)
    daily_snapshots = []
    peak = _safe_float(initial_capital)
    for i in range(n):
        equity = _safe_float(equity_curve[i], default=initial_capital)
        peak = max(peak, equity)
        dd = (equity - peak) / peak if peak > 0 else 0.0

        ts = timestamps[i] if i < len(timestamps) else None
        # ts 可能是 pd.Timestamp / datetime / str
        try:
            date_val = pd.Timestamp(ts)
        except Exception:
            date_val = pd.Timestamp.now()

        prev_eq = (
            _safe_float(equity_curve[i - 1], default=initial_capital)
            if i > 0
            else _safe_float(initial_capital)
        )
        daily_return = (equity - prev_eq) / prev_eq if prev_eq > 0 else 0.0
        daily_pnl = equity - prev_eq

        # 粗略估计 cash / position_value：从 daily_pnl 反推
        # （quantlab 没暴露 cash 时序，所以这里做近似）
        position_value = max(equity - initial_capital, 0) if i > 0 else 0
        cash = equity - position_value

        daily_snapshots.append(
            DailySnapshot(
                date=date_val,
                cash=cash,
                position_value=position_value,
                total_value=equity,
                n_positions=_count_open_positions(ql, i, portfolio, timestamps[i] if i < len(timestamps) else None),
                daily_pnl=daily_pnl,
                daily_return=daily_return,
                drawdown=dd,
                max_drawdown=dd,
            )
        )

    # ---- 2) trades → TradeRecord[] ----
    # 支持两种来源：
    #   a) quantlab原生tradebook（ql.tradebook）
    #   b) vectorbt Portfolio对象（ql.portfolio，即vbt.Portfolio）
    trades: list = []
    
    # 先尝试从vbt Portfolio提取
    portfolio = ql.portfolio
    if portfolio is not None and hasattr(portfolio, 'trades') and hasattr(portfolio.trades, 'records_readable'):
        # vectorbt 路径：从pf.trades.records_readable提取
        try:
            trades_df = portfolio.trades.records_readable
            if trades_df is not None and len(trades_df) > 0:
                for _, row in trades_df.iterrows():
                    try:
                        symbol = str(row.get('Column', ''))
                        size = _safe_float(row.get('Size', 0))
                        if size <= 0:
                            continue
                        entry_dt = pd.Timestamp(row['Entry Timestamp'])
                        exit_dt = pd.Timestamp(row['Exit Timestamp'])
                        entry_price = _safe_float(row.get('Avg Entry Price', 0))
                        exit_price = _safe_float(row.get('Avg Exit Price', 0))
                        pnl = _safe_float(row.get('PnL', 0))
                        qty = int(abs(size))
                        
                        # 开仓
                        trades.append(
                            TradeRecord(
                                date=entry_dt,
                                stock_code=symbol,
                                direction=Direction.LONG,
                                action="open",
                                price=entry_price,
                                quantity=qty,
                                commission=0.0,
                                slippage=0.0,
                                pnl=0.0,
                                reason="rebalance",
                            )
                        )
                        # 平仓
                        trades.append(
                            TradeRecord(
                                date=exit_dt,
                                stock_code=symbol,
                                direction=Direction.LONG,
                                action="close",
                                price=exit_price,
                                quantity=qty,
                                commission=0.0,
                                slippage=0.0,
                                pnl=pnl,
                                reason="rebalance",
                            )
                        )
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"从vbt portfolio提取交易记录失败: {e}")
    
    # quantlab原生tradebook路径
    tradebook = ql.tradebook
    if tradebook is not None and len(trades) == 0:
        # rebuild() 后 closed_trades / closed_trades_by_symbol 都有
        try:
            tradebook.rebuild()
        except Exception:
            pass

        closed = getattr(tradebook, "closed_trades", []) or []
        for ct in closed:
            try:
                entry_dt = pd.Timestamp(ct.entry_time)
                exit_dt = pd.Timestamp(ct.exit_time)
            except Exception:
                continue

            qty = int(getattr(ct, "qty", 0) or 0)
            entry_price = _safe_float(getattr(ct, "entry_price", 0))
            exit_price = _safe_float(getattr(ct, "exit_price", 0))

            # 开仓记录
            trades.append(
                TradeRecord(
                    date=entry_dt,
                    stock_code=ct.symbol,
                    direction=Direction.LONG,
                    action="open",
                    price=entry_price,
                    quantity=qty,
                    commission=0.0,
                    slippage=0.0,
                    pnl=0.0,
                    reason="quantlab signal=1",
                )
            )
            # 平仓记录
            trades.append(
                TradeRecord(
                    date=exit_dt,
                    stock_code=ct.symbol,
                    direction=Direction.LONG,
                    action="close",
                    price=exit_price,
                    quantity=qty,
                    commission=0.0,
                    slippage=0.0,
                    pnl=_safe_float(getattr(ct, "pnl", 0)),
                    reason="quantlab signal=0",
                )
            )

    # ---- 3) performance dict ----
    # myquant 习惯把 sharpe / max_drawdown 当作 ratio
    # quantlab 给出 sharpe（无量纲） / total_return（%） / max_drawdown（%）
    # 这里统一转成 myquant 习惯：
    #   total_return (小数) / annual_return (小数) / sharpe_ratio / max_drawdown (小数)
    total_return = _safe_float(ql.total_return) / 100.0  # % -> 小数
    max_drawdown = _safe_float(ql.max_drawdown) / 100.0  # % -> 小数
    sharpe = _safe_float(ql.sharpe)
    n_days = max(len(daily_snapshots), 1)
    annual_return = (
        (1 + total_return) ** (252 / n_days) - 1
        if total_return > -1
        else 0.0
    )

    # 用 equity_curve 算 volatility
    if len(equity_curve) > 1:
        eq = pd.Series(equity_curve[:n], dtype=float)
        daily_returns = eq.pct_change().dropna()
        annual_volatility = (
            float(daily_returns.std() * (252 ** 0.5))
            if len(daily_returns) > 0
            else 0.0
        )
    else:
        annual_volatility = 0.0

    performance = {
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_drawdown,
        "win_rate": _safe_float(ql.win_rate) / 100.0,
        "total_trades": int(getattr(ql, "trade_count", 0) or 0),
        "win_trades": 0,
        "lose_trades": 0,
        "source": ql.source or "quantlab",
    }

    # ---- 4) start_date / end_date ----
    start_date = ""
    end_date = ""
    if timestamps:
        try:
            start_date = pd.Timestamp(timestamps[0]).strftime("%Y-%m-%d")
            end_date = pd.Timestamp(timestamps[-1]).strftime("%Y-%m-%d")
        except Exception:
            pass

    return BacktestResult(
        strategy_name=strategy_name,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        final_value=_safe_float(ql.final_equity, default=initial_capital),
        total_return=total_return,
        daily_snapshots=daily_snapshots,
        trades=trades,
        performance=performance,
    )


def _count_open_positions(ql, i: int, portfolio=None, ts=None) -> int:
    """
    估算当日持仓数量：
    1. 优先从vbt Portfolio获取（如果portfolio是vbt.Portfolio）
    2. 否则从 ql.position_qty 拿
    """
    # 先尝试vbt portfolio
    if portfolio is not None and hasattr(portfolio, 'positions'):
        try:
            # 使用持仓记录：在给定时间点的持仓数
            # vbt的positions.records可以获取每个时间点的持仓
            if hasattr(portfolio, 'position_mask'):
                mask = portfolio.position_mask
                if mask is not None and i < len(mask):
                    # position_mask是布尔DataFrame，True表示该日该标的有持仓
                    row = mask.iloc[i] if hasattr(mask, 'iloc') else mask[i]
                    return int(row.sum()) if hasattr(row, 'sum') else 0
        except Exception:
            pass
    
    # 回退到ql.position_qty
    pq = getattr(ql, 'position_qty', None)
    if not isinstance(pq, dict) or not pq:
        return 0
    count = 0
    for sym, qty_list in pq.items():
        if not qty_list:
            continue
        last_idx = min(i, len(qty_list) - 1)
        if last_idx < 0:
            continue
        if qty_list[last_idx]:
            count += 1
    return count


__all__ = ["to_myquant_result"]
