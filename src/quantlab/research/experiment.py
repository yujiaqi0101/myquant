"""
Experiment：单次实验入口

V2 改造：
- engine 吃 BaseBacktestEngine
- engine.run() 返 BacktestResult
- ExperimentResult 由 BacktestResult + 元数据组成
"""

from .result import (
    ExperimentResult
)

from ..core.backtest_result import (
    BacktestResult
)


class Experiment:

    # 一次实验的入口
    #
    # 现在：
    #   exp = Experiment(name="ma_cross_v1")
    #   result = exp.run(
    #       strategy=MACrossStrategy(fast=20, slow=60),
    #       engine=engine,
    #       data=data
    #   )
    #   result.metrics["sharpe"]     # 1.13
    #   result.metrics["max_drawdown"]  # -0.16

    def __init__(self, name="experiment"):

        self.name = name

    def _compute_metrics(
        self,
        result: BacktestResult,
    ):

        from ..statistics import (
            win_rate,
            profit_factor,
            average_trade
        )

        # BacktestResult 已经算过核心指标
        # 这里补 trade-level 指标
        closed = (
            result.tradebook.closed_trades
            if result.tradebook
            else []
        )

        # 多标的 exposure
        # BacktestResult.position_qty 是 Dict[symbol, List[qty]]
        position_qty = (
            result.position_qty
        )
        equity = result.equity_curve

        exposure = 0.0
        if (
            position_qty
            and len(equity) > 0
        ):

            symbols = list(
                position_qty.keys()
            )
            n_bars = min(
                len(equity),
                *(
                    len(v)
                    for v in position_qty.values()
                )
            )

            for i in range(n_bars):

                bar_pos_value = sum(
                    abs(
                        position_qty[s][i]
                        * result.portfolio
                        .last_prices
                        .get(s, 0)
                    )
                    for s in symbols
                )
                if equity[i] > 0:

                    exposure += (
                        bar_pos_value
                        / equity[i]
                    )

            exposure = (
                exposure
                / max(n_bars, 1)
            )

        return {
            "final_equity": (
                round(result.final_equity, 2)
            ),
            "total_return": (
                round(result.total_return, 2)
            ),
            "sharpe": (
                round(result.sharpe, 3)
            ),
            "max_drawdown": (
                round(
                    result.max_drawdown, 2
                )
            ),
            "trade_count": (
                result.trade_count
            ),
            "fill_count": (
                len(result.fills)
            ),
            "win_rate": (
                round(
                    win_rate(closed) * 100, 2
                ) if closed else 0.0
            ),
            "profit_factor": (
                round(
                    profit_factor(closed), 2
                ) if closed else 0.0
            ),
            "avg_trade": (
                round(
                    average_trade(closed), 2
                ) if closed else 0.0
            ),
            "exposure": (
                round(exposure * 100, 2)
            ),
            "source": result.source,
        }

    def run(
        self,
        strategy,
        engine,
        data,
        params=None,
    ) -> ExperimentResult:

        params = params or {}

        # 每次 Experiment 独立运行
        # 必须清 factor_cache
        from ..data.cache import (
            factor_cache
        )
        factor_cache.clear()

        # BaseBacktestEngine 协议
        # engine.run() 现在返 BacktestResult
        raw: BacktestResult = (
            engine.run(
                strategy=strategy,
                data=data,
                params=params,
            )
        )

        # 兼容：如果还是老 dict，包一下
        if not isinstance(
            raw, BacktestResult
        ):

            raw = BacktestResult.from_event_dict(
                raw
            )

        if not raw.ok():

            return ExperimentResult(
                name=self.name,
                strategy_name=(
                    type(strategy).__name__
                ),
                params=params,
                metrics={
                    "error": (
                        raw.error
                        or "engine error"
                    )
                },
                equity_curve=[],
                timestamps=[],
                extras={
                    "source": raw.source,
                }
            )

        metrics = self._compute_metrics(raw)

        # 拿 timestamps
        ts = raw.timestamps
        if ts is None and raw.portfolio:

            ts = raw.portfolio.timestamps

        return ExperimentResult(
            name=self.name,
            strategy_name=(
                type(strategy).__name__
            ),
            params=params,
            metrics=metrics,
            equity_curve=list(
                raw.equity_curve
                or []
            ),
            timestamps=ts or [],
            tradebook=raw.tradebook,
            extras={
                "source": raw.source,
                "fill_count": (
                    len(raw.fills)
                ),
                "trade_count": raw.trade_count,
            }
        )
