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

        # 2) 调 constructor，构造 weights_df (目标权重，0~1，所有列和=1)
        weights_df: pd.DataFrame = (
            self._build_weights_df(
                signal=signal,
                constructor=self._constructor,
            )
        )

        # 3) 构建 close DataFrame 和 size DataFrame（多资产组合一次性回测）
        #    对齐所有 symbol 的索引
        symbols = list(data.keys())
        
        # 使用pd.concat构建close_df，避免DataFrame碎片化
        close_series_list = []
        for sym in symbols:
            close_s = data[sym]['close'].rename(sym)
            close_series_list.append(close_s)
        close_df = pd.concat(close_series_list, axis=1)
        close_df = close_df.reindex(weights_df.index)
        
        # size_df = weights_df：NaN表示"不操作，继续持有"，非NaN表示调仓到目标权重
        # 策略通过在非调仓日输出NaN来控制调仓频率
        size_df = weights_df.reindex(columns=symbols)

        # 4) 使用vbt多资产组合回测（共享资金，目标权重模式）
        #    allow_partial=True：允许部分成交。
        #    若设为 False，当目标仓位100%但加上手续费/滑点后资金略不足时，
        #    vbt 会直接放弃整笔订单（ETF 低价标的 + 满仓场景必中此坑）。
        pf = vbt.Portfolio.from_orders(
            close=close_df,
            size=size_df,
            size_type='targetpercent',
            fees=self._fees,
            slippage=self._slippage,
            init_cash=self._init_cash,
            cash_sharing=True,
            freq="D",
            allow_partial=True,
        )

        return self._build_result(
            pf=pf,
            signal=signal,
            weights_df=weights_df,
            symbols=symbols,
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
        # 约定：
        #   - 如果某天所有 scores 都是 NaN → 该日不调仓，所有 weights 设为 NaN
        #     （vbt 遇到 NaN size 不会下单，继续持有现有仓位）
        #   - 否则，NaN 的 symbol 视为 0（不持有），正常计算权重

        symbols = list(signal.columns)
        weights = {
            sym: []
            for sym in symbols
        }
        timestamps = []

        for ts, row in signal.iterrows():

            scores = row.to_dict()

            # 检查是否全部为 NaN（策略表示"今天不调仓"）
            valid_scores = [
                v for v in scores.values()
                if v is not None and not (isinstance(v, float) and pd.isna(v))
            ]
            if not valid_scores:
                # 全 NaN → 不操作，所有 symbol 权重设为 NaN
                for sym in symbols:
                    weights[sym].append(float('nan'))
                timestamps.append(ts)
                continue

            # 正常计算目标权重（NaN score 视为 0）
            clean_scores = {}
            for s, v in scores.items():
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    clean_scores[s] = 0.0
                else:
                    clean_scores[s] = v

            target = constructor.construct(
                scores=clean_scores,
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
        pf,
        signal,
        weights_df,
        symbols,
    ):

        from ..analytics import (
            sharpe_ratio,
            total_return,
            max_drawdown,
        )

        # 获取组合净值曲线
        equity = pf.value()
        if hasattr(equity, "values"):
            equity_values = equity.values
        else:
            equity_values = equity
        equity_list = list(equity_values)

        # 时间戳来自weights_df的索引
        timestamps = list(weights_df.index)

        # 获取交易次数
        trade_count = len(pf.trades.records_readable)

        if not equity_list:
            return BacktestResult(
                equity_curve=[],
                total_return=0.0,
                sharpe=0.0,
                max_drawdown=0.0,
                trade_count=0,
                win_rate=0.0,
                final_equity=0.0,
                source="vectorbt",
                raw={"portfolio": pf},
                signal=signal,
                weights_df=weights_df,
                timestamps=timestamps,
                error="no equity to combine",
            )

        return BacktestResult(
            equity_curve=equity_list,
            total_return=round(
                total_return(equity_list) * 100, 2
            ),
            sharpe=round(
                sharpe_ratio(equity_list), 3
            ),
            max_drawdown=round(
                max_drawdown(equity_list) * 100, 2
            ),
            trade_count=trade_count,
            win_rate=0.0,
            final_equity=round(
                equity_list[-1], 2
            ),
            source="vectorbt",
            raw={
                "portfolio": pf,
                "signal": signal,
            },
            signal=signal,
            weights_df=weights_df,
            timestamps=timestamps,
            portfolio=pf,
        )
