# ------------------------------------------------------------
# vectorbt 在某些受限环境（sandbox）里
# 启动 numba JIT / mpl cache 时会直接 crash 进程
# 必须先设环境变量关掉 numba JIT
# 再 try import vectorbt
# ------------------------------------------------------------
import os

os.environ.setdefault(
    "NUMBA_DISABLE_JIT", "1"
)
os.environ.setdefault(
    "MPLBACKEND", "Agg"
)
os.environ.setdefault(
    "VECTORBT_NO_CACHING", "1"
)

try:

    import vectorbt as vbt

    _VBT_AVAILABLE = True

except Exception:

    vbt = None
    _VBT_AVAILABLE = False


from typing import Dict

import pandas as pd

from ..data.cache import factor_cache
from ..data.context import StrategyContext

from ..core.base_engine import (
    BaseBacktestEngine,
)
from ..core.backtest_result import (
    BacktestResult,
)


class VectorBTAdapter(BaseBacktestEngine):

    # V2.0 正式版
    #
    # 完整研究流水线（与 EventEngine 一致）：
    #   signal (DataFrame: date × symbol)
    #     ↓
    #   PortfolioConstructor.construct(scores, ts)
    #     ↓
    #   TargetPortfolio.weights
    #     ↓
    #   weights_df (date × symbol) ∈ [0, 1]
    #     ↓
    #   vbt.Portfolio.from_orders(close, size=weights)
    #     ↓
    #   BacktestResult
    #
    # 关键变化：
    #   - 不再 from_signals
    #   - 用 from_orders 喂权重
    #   - constructor 统一了 BarEngine 和 VectorBT 的权重生成逻辑

    def __init__(
        self,
        constructor=None,
        fees=0.0003,
        slippage=0.0002,
        init_cash=100000,
    ):

        # 默认等权
        # 用户可以传 TopN / RiskParity / 自定义
        if constructor is None:

            from ..portfolio_construction import (
                EqualWeight
            )
            constructor = EqualWeight()

        self._constructor = constructor
        self._fees = fees
        self._slippage = slippage
        self._init_cash = init_cash

    def set_constructor(self, constructor):

        self._constructor = constructor

    def run(
        self,
        strategy=None,
        data: Dict = None,
        params: Dict = None,
        constructor=None,
    ) -> BacktestResult:

        # BaseBacktestEngine 协议
        # + 允许运行时覆盖 constructor

        if constructor is not None:

            self._constructor = constructor

        if strategy is None:

            raise ValueError(
                "VectorBTAdapter.run() requires a strategy"
            )

        if data is None:

            raise ValueError(
                "VectorBTAdapter.run() requires data"
            )

        return self._run(
            strategy=strategy,
            data=data,
        )

    # ----------------------------------------------------------------
    # 内部：signal → weights_df → from_orders
    # ----------------------------------------------------------------

    def _run(
        self,
        strategy,
        data: Dict,
    ):

        ctx = StrategyContext(
            data,
            factor_cache
        )

        # 1) signal: DataFrame(date × symbol)
        signal: pd.DataFrame = (
            strategy.signal(ctx)
        )

        # 2) 调 constructor，构造 weights_df
        weights_df: pd.DataFrame = (
            self._build_weights_df(
                signal=signal,
                constructor=self._constructor,
            )
        )

        # 3) per-symbol 调 from_orders
        #    VBT 的 from_order 只能对单 symbol
        #    所以 per-symbol 跑一次
        #    然后再合并 equity
        n_symbols = max(len(data), 1)
        per_symbol_cash = (
            self._init_cash / n_symbols
        )

        portfolios = {}

        for sym in data:

            # VBT 内部对 close / size 做 Series 比较
            # 必须保持同样的 DatetimeIndex
            # 否则 "Can only compare identically-labeled Series objects"
            #
            # 关键：
            #   - close 带 DatetimeIndex（pd.Series）
            #   - size 用相同 index 转 pd.Series
            close_index = (
                data[sym]["close"].index
            )

            close = pd.Series(
                data[sym]["close"].to_numpy(),
                index=close_index,
            )

            # size: 该 symbol 的权重序列
            # 用 close 同样的 DatetimeIndex
            size = pd.Series(
                weights_df[sym]
                .reindex(close_index)
                .fillna(0.0)
                .to_numpy(),
                index=close_index,
            )

            pf = vbt.Portfolio.from_orders(
                close=close,
                size=size,
                fees=self._fees,
                slippage=self._slippage,
                init_cash=per_symbol_cash,
                freq="D",
            )

            portfolios[sym] = pf

        return self._build_result(
            portfolios=portfolios,
            signal=signal,
            weights_df=weights_df,
        )

    def _build_weights_df(
        self,
        signal: pd.DataFrame,
        constructor,
    ) -> pd.DataFrame:

        # 对 signal 的每一行（每根 bar）
        # 调 constructor.construct(scores, ts)
        # 累积成 weights_df
        #
        # 这就是"组合权重策略"
        # 不再是"单资产信号策略"

        symbols = list(signal.columns)
        weights = {
            sym: []
            for sym in symbols
        }
        timestamps = []

        for ts, row in signal.iterrows():

            scores = row.to_dict()

            target = constructor.construct(
                scores=scores,
                timestamp=ts,
            )

            for sym in symbols:

                weights[sym].append(
                    target.weights.get(sym, 0.0)
                )

            timestamps.append(ts)

        return pd.DataFrame(
            weights,
            index=timestamps,
        )

    # ----------------------------------------------------------------
    # 结果合并
    # ----------------------------------------------------------------

    def _build_result(
        self,
        portfolios,
        signal,
        weights_df,
    ):

        from ..analytics import (
            sharpe_ratio,
            total_return,
            max_drawdown,
        )

        # 合并 equity（按 bar 加和）
        equities = []
        for sym, pf in portfolios.items():

            v = pf.value()

            if hasattr(v, "values"):

                v = v.values

            equities.append(v)

        if not equities:

            return BacktestResult(
                equity_curve=[],
                total_return=0.0,
                sharpe=0.0,
                max_drawdown=0.0,
                trade_count=0,
                win_rate=0.0,
                final_equity=0.0,
                source="vectorbt",
                raw={"portfolios": {}},
                signal=signal,
                weights_df=weights_df,
                error=(
                    "no portfolios to combine"
                ),
            )

        min_len = min(
            len(v) for v in equities
        )
        combined = [
            sum(
                equities[k][i]
                for k in range(len(equities))
            )
            for i in range(min_len)
        ]

        trade_count = sum(
            len(pf.trades.records_readable)
            for pf in portfolios.values()
        )

        return BacktestResult(
            equity_curve=combined,
            total_return=round(
                total_return(combined) * 100, 2
            ),
            sharpe=round(
                sharpe_ratio(combined), 3
            ),
            max_drawdown=round(
                max_drawdown(combined) * 100, 2
            ),
            trade_count=trade_count,
            win_rate=0.0,
            final_equity=round(
                combined[-1], 2
            ),
            source="vectorbt",
            raw={
                "portfolios": portfolios,
                "signal": signal,
            },
            signal=signal,
            weights_df=weights_df,
        )
