"""
QuintileExperiment — 5 分位分层回测 + 多空对冲 + IC/IR。

工作流：
    1) 输入 factor_data (date × symbol) + data (quantlab Dict)
    2) 每个 rebalance_freq 调一次仓，按 factor_data 截面分 N 桶
    3) 对每 quintile 跑一次 quantlab BarEngine（独立的 strategy 实例）
    4) 收集 equity_curve 形成 quintile_curves
    5) 计算 long_short（Q_high - Q_low）净值曲线
    6) 计算 IC = corr(factor_value_t, next_R_days_return)
       IR = mean(IC) / std(IC)
    7) 输出 QuintileResult

优势（vs 旧 MultiFactorQuintileBacktestEngineV2）：
    - 用 quantlab BarEngine，1 套引擎 4 个后端
    - 5 分位是独立 strategy，配置 / 风控 / 调仓逻辑可独立调
    - 复用现有 RiskManager / Execution / PortfolioConstructor
    - IC/IR 是标准实现，旧版需手工算
    - 输出的 BacktestResult 可直接走 ResultAdapter 兼容老代码
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.quantlab.core.backtest_result import BacktestResult
from src.quantlab.engine import BarEngine
from src.quantlab.execution import (
    PercentageCommission,
    PercentageSlippage,
    TargetWeightExecution,
)
from src.quantlab.portfolio_construction import (
    EqualWeight,
)

from .quintile_strategy import QuintileSignalStrategy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------- #
# 输出结果
# ---------------------------------------------------------------------- #
@dataclass
class QuintileResult:
    """
    分层回测结果。

    Attributes
    ----------
    factor_name : str
        因子名（仅用于展示 / 入库）
    quintile_curves : dict[int, list[float]]
        {quintile_id: equity_curve}，key=1..n_quantiles
    quintile_metrics : dict[int, dict]
        {quintile_id: {sharpe, total_return, max_drawdown, ...}}
    long_short : list[float]
        多空对冲净值曲线（= long_equity / short_equity）
    long_short_metrics : dict
        {sharpe, total_return, max_drawdown, ...}
    ic_series : list[float]
        IC 时序（每个调仓日一个值）
    ir : float
        IR = mean(IC) / std(IC)
    ic_mean : float
        IC 均值
    ic_std : float
        IC 标准差
    factor_data : pd.DataFrame
        输入的因子值（透传，便于报告）
    backtest_results : dict[int, BacktestResult]
        {quintile_id: quantlab BacktestResult}（用于深入分析）
    extras : dict
        其他元数据
    """

    factor_name: str = ""
    quintile_curves: Dict[int, List[float]] = field(default_factory=dict)
    quintile_metrics: Dict[int, Dict[str, float]] = field(default_factory=dict)
    long_short: List[float] = field(default_factory=list)
    long_short_metrics: Dict[str, float] = field(default_factory=dict)
    ic_series: List[float] = field(default_factory=list)
    ir: float = 0.0
    ic_mean: float = 0.0
    ic_std: float = 0.0
    factor_data: Optional[pd.DataFrame] = None
    backtest_results: Dict[int, BacktestResult] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转 dict（用于 JSON 序列化 / 入库）。"""
        return {
            "factor_name": self.factor_name,
            "quintile_metrics": self.quintile_metrics,
            "long_short_metrics": self.long_short_metrics,
            "ic_mean": self.ic_mean,
            "ic_std": self.ic_std,
            "ir": self.ir,
            "n_ic": len(self.ic_series),
        }

    def summary(self) -> str:
        """人类可读摘要。"""
        lines = [f"Quintile Result: {self.factor_name}"]
        lines.append(f"  IC = {self.ic_mean:.4f} ± {self.ic_std:.4f}, IR = {self.ir:.3f}")
        lines.append("  Per-quintile metrics:")
        for q in sorted(self.quintile_metrics):
            m = self.quintile_metrics[q]
            lines.append(
                f"    Q{q}: sharpe={m.get('sharpe', 0):.3f}, "
                f"return={m.get('total_return', 0):.2f}%, "
                f"maxDD={m.get('max_drawdown', 0):.2f}%"
            )
        if self.long_short_metrics:
            ls = self.long_short_metrics
            lines.append(
                f"  Long-Short: sharpe={ls.get('sharpe', 0):.3f}, "
                f"return={ls.get('total_return', 0):.2f}%, "
                f"maxDD={ls.get('max_drawdown', 0):.2f}%"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------- #
# 主类
# ---------------------------------------------------------------------- #
class QuintileExperiment:
    """
    5 分位分层回测入口。

    Parameters
    ----------
    n_quantiles : int
        分位数量（默认 5）
    rebalance_freq : int
        调仓频率（每 N 个 bar 调一次，默认 5 = 周度）
    initial_cash : float
        每次分位独立回测的初始资金
    commission_rate : float
        佣金率（万 2.5 = 0.00025）
    slippage_rate : float
        滑点率（万 1 = 0.0001）
    long_direction : str
        'high'（默认）：Q_n 因子值最大 → 做多 Q_n
        'low'：Q_1 因子值最大 → 做多 Q_1
    ic_lag : int
        IC 计算时用未来多少 bar 的收益（默认 1 = 下 1 根 bar 收益）
    factor_name : str
        因子名（仅用于展示）
    lot_size : int
        1 手股数（A 股默认 100）
    position_tolerance : float
        仓位容忍度
    """

    def __init__(
        self,
        n_quantiles: int = 5,
        rebalance_freq: int = 5,
        initial_cash: float = 1_000_000.0,
        commission_rate: float = 0.00025,
        slippage_rate: float = 0.0001,
        long_direction: str = "high",
        ic_lag: int = 1,
        factor_name: str = "factor",
        lot_size: int = 100,
        position_tolerance: float = 0.02,
        min_factor_count: int = 10,
    ):
        if n_quantiles < 2:
            raise ValueError(f"n_quantiles must be >= 2, got {n_quantiles}")
        if long_direction not in ("high", "low"):
            raise ValueError(
                f"long_direction must be 'high' or 'low', got {long_direction}"
            )

        self.n_quantiles = int(n_quantiles)
        self.rebalance_freq = int(rebalance_freq)
        self.initial_cash = float(initial_cash)
        self.commission_rate = float(commission_rate)
        self.slippage_rate = float(slippage_rate)
        self.long_direction = long_direction
        self.ic_lag = int(ic_lag)
        self.factor_name = str(factor_name)
        self.lot_size = int(lot_size)
        self.position_tolerance = float(position_tolerance)
        # 默认 min_factor_count = n_quantiles（小数据测试用），用户可调
        # 真实场景下股票池通常 100+ 个，调大可以过滤掉非主流截面
        self.min_factor_count = max(int(min_factor_count), n_quantiles)

    # ------------------------------------------------------------------ #
    # 公共方法
    # ------------------------------------------------------------------ #
    def run(
        self,
        factor_data: pd.DataFrame,
        data: Dict[str, pd.DataFrame],
        long_quantile: Optional[int] = None,
        short_quantile: Optional[int] = None,
    ) -> QuintileResult:
        """
        跑完整 5 分位 + 多空对冲 + IC/IR。

        Parameters
        ----------
        factor_data : pd.DataFrame
            因子值，index=date, columns=symbol。
            必须与 data 共享相同 (date × symbol) 空间。
        data : Dict[str, pd.DataFrame]
            quantlab 格式数据。DataFrame 含 open/close 至少。
        long_quantile : int | None
            多头 quintile（默认 = n_quantiles，因子值最大）
        short_quantile : int | None
            空头 quintile（默认 = 1，因子值最小）。None=不做空。
        """
        if factor_data is None or factor_data.empty:
            raise ValueError("factor_data 不能为空")
        if not data:
            raise ValueError("data 不能为空")

        if long_quantile is None:
            long_quantile = self.n_quantiles
        if short_quantile is None:
            short_quantile = 1

        if not (1 <= long_quantile <= self.n_quantiles):
            raise ValueError(
                f"long_quantile must be in [1, {self.n_quantiles}], got {long_quantile}"
            )
        if not (1 <= short_quantile <= self.n_quantiles):
            raise ValueError(
                f"short_quantile must be in [1, {self.n_quantiles}], got {short_quantile}"
            )

        # 对齐 factor_data 和 data 的 symbol
        factor_data = self._align_factor_data(factor_data, data)

        # ---- 1) 每个 quintile 跑一次 BarEngine ----
        backtest_results: Dict[int, BacktestResult] = {}
        quintile_curves: Dict[int, List[float]] = {}
        quintile_metrics: Dict[int, Dict[str, float]] = {}

        for q in range(1, self.n_quantiles + 1):
            logger.info("Running quintile Q%d ...", q)
            strategy = QuintileSignalStrategy(
                factor_data=factor_data,
                target_quintile=q,
                n_quantiles=self.n_quantiles,
                direction=self.long_direction,
                rebalance_freq=self.rebalance_freq,
                min_factor_count=self.min_factor_count,
            )
            engine = self._build_engine(strategy)
            result = engine.run(strategy=strategy, data=data, params={})
            backtest_results[q] = result
            quintile_curves[q] = list(result.equity_curve or [])
            quintile_metrics[q] = self._extract_metrics(result)

        # ---- 2) 多空对冲 ----
        long_short: List[float] = []
        if short_quantile is not None and short_quantile != long_quantile:
            long_short = self._compute_long_short(
                quintile_curves[long_quantile],
                quintile_curves[short_quantile],
            )
        else:
            # 不做空：直接用多头曲线
            long_short = list(quintile_curves[long_quantile])

        long_short_metrics = self._metrics_from_curve(long_short)

        # ---- 3) IC / IR ----
        ic_series = self._compute_ic_series(factor_data, data)
        ir, ic_mean, ic_std = self._compute_ir(ic_series)

        return QuintileResult(
            factor_name=self.factor_name,
            quintile_curves=quintile_curves,
            quintile_metrics=quintile_metrics,
            long_short=long_short,
            long_short_metrics=long_short_metrics,
            ic_series=ic_series,
            ir=ir,
            ic_mean=ic_mean,
            ic_std=ic_std,
            factor_data=factor_data,
            backtest_results=backtest_results,
            extras={
                "n_quantiles": self.n_quantiles,
                "rebalance_freq": self.rebalance_freq,
                "long_quantile": long_quantile,
                "short_quantile": short_quantile,
            },
        )

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #
    def _align_factor_data(
        self,
        factor_data: pd.DataFrame,
        data: Dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """
        把 factor_data 对齐到 data 的 (date × symbol) 空间。
        缺失值填 NaN。
        """
        data_symbols = list(data.keys())
        if not data_symbols:
            return factor_data

        # 拿 data 的统一 index
        data_index = data[data_symbols[0]].index

        # 缺失 symbol → 加 NaN 列
        missing_cols = [s for s in data_symbols if s not in factor_data.columns]
        if missing_cols:
            for s in missing_cols:
                factor_data[s] = np.nan

        # 缺失 date → 补 NaN 行
        missing_idx = data_index.difference(factor_data.index)
        if len(missing_idx) > 0:
            extra = pd.DataFrame(
                np.nan,
                index=missing_idx,
                columns=factor_data.columns,
            )
            factor_data = pd.concat([factor_data, extra]).sort_index()

        # 只保留 data 中存在的 symbol
        factor_data = factor_data[data_symbols]

        return factor_data

    def _build_engine(self, strategy: QuintileSignalStrategy) -> BarEngine:
        """构造一个 BarEngine 实例（每个 quintile 独立）。"""
        portfolio_constructor = EqualWeight()
        execution = TargetWeightExecution(
            lot_size=self.lot_size,
            position_tolerance=self.position_tolerance,
        )
        # 挂上 commission / slippage（按 factory.py 约定）
        execution.commission = PercentageCommission(rate=self.commission_rate)
        execution.slippage = PercentageSlippage(rate=self.slippage_rate)

        commission_model = PercentageCommission(rate=self.commission_rate)
        slippage_model = PercentageSlippage(rate=self.slippage_rate)

        return BarEngine(
            strategy=strategy,
            portfolio_constructor=portfolio_constructor,
            execution_model=execution,
            commission_model=commission_model,
            slippage_model=slippage_model,
            initial_cash=self.initial_cash,
        )

    def _extract_metrics(self, result: BacktestResult) -> Dict[str, float]:
        """从 BacktestResult 提取标准指标。"""
        return {
            "sharpe": float(getattr(result, "sharpe", 0) or 0),
            "total_return": float(getattr(result, "total_return", 0) or 0),
            "max_drawdown": float(getattr(result, "max_drawdown", 0) or 0),
            "final_equity": float(getattr(result, "final_equity", 0) or 0),
            "trade_count": int(getattr(result, "trade_count", 0) or 0),
        }

    def _compute_long_short(
        self,
        long_curve: List[float],
        short_curve: List[float],
    ) -> List[float]:
        """
        多空对冲净值曲线 = (1 + long_ret) / (1 + short_ret) - 1 累加
        简化：直接 (long / short) - 1 累加。
        """
        if not long_curve or not short_curve:
            return []
        n = min(len(long_curve), len(short_curve))
        if n == 0:
            return []

        # 多头收益
        long_returns = []
        for i in range(1, n):
            prev = long_curve[i - 1]
            curr = long_curve[i]
            r = (curr - prev) / prev if prev > 0 else 0.0
            long_returns.append(r)

        # 空头收益（取负）
        short_returns = []
        for i in range(1, n):
            prev = short_curve[i - 1]
            curr = short_curve[i]
            r = (curr - prev) / prev if prev > 0 else 0.0
            short_returns.append(-r)  # 做空 = 反向

        # 多空组合净值：从 1 开始累乘
        ls = [1.0]
        for lr, sr in zip(long_returns, short_returns):
            ls.append(ls[-1] * (1 + lr + sr))

        return ls

    def _metrics_from_curve(self, equity: List[float]) -> Dict[str, float]:
        """从 equity 曲线算 sharpe / total_return / max_drawdown。"""
        if not equity or len(equity) < 2:
            return {
                "sharpe": 0.0,
                "total_return": 0.0,
                "max_drawdown": 0.0,
            }

        eq = pd.Series(equity, dtype=float)
        daily_ret = eq.pct_change().dropna()
        total_return = (eq.iloc[-1] / eq.iloc[0] - 1) * 100 if eq.iloc[0] > 0 else 0.0

        sharpe = 0.0
        if len(daily_ret) > 0 and daily_ret.std() > 0:
            sharpe = float(daily_ret.mean() / daily_ret.std() * (252 ** 0.5))

        # 最大回撤
        running_max = eq.cummax()
        drawdown = (eq - running_max) / running_max
        max_dd = float(drawdown.min() * 100) if len(drawdown) > 0 else 0.0

        return {
            "sharpe": round(sharpe, 4),
            "total_return": round(total_return, 4),
            "max_drawdown": round(max_dd, 4),
        }

    def _compute_ic_series(
        self,
        factor_data: pd.DataFrame,
        data: Dict[str, pd.DataFrame],
    ) -> List[float]:
        """
        IC = corr(factor_value_t, next_{ic_lag}_bar_return)
        每天（每个 factor_data index）算一次截面 rank IC。
        """
        ic_series: List[float] = []

        # 算每日收益
        # 用 close 价格
        symbols = list(factor_data.columns)
        if not symbols:
            return ic_series

        # 拼 close 矩阵
        close_dict = {}
        for s in symbols:
            if s in data:
                close_dict[s] = data[s]["close"]
        if not close_dict:
            return ic_series

        close_df = pd.DataFrame(close_dict).sort_index()
        # 未来 ic_lag 根 bar 的收益
        fwd_ret = close_df.shift(-self.ic_lag) / close_df - 1

        # 遍历 factor_data 的每个日期
        for date in factor_data.index:
            if date not in fwd_ret.index:
                continue
            f_row = factor_data.loc[date]
            r_row = fwd_ret.loc[date]

            # 对齐 + 丢 NaN
            valid = pd.concat([f_row, r_row], axis=1).dropna()
            valid.columns = ["factor", "ret"]
            if len(valid) < 5:
                continue
            # 截面 rank 相关系数
            corr = valid["factor"].rank().corr(valid["ret"].rank())
            if not np.isnan(corr):
                ic_series.append(float(corr))

        return ic_series

    def _compute_ir(
        self,
        ic_series: List[float],
    ) -> Tuple[float, float, float]:
        """IR = mean(IC) / std(IC)。"""
        if len(ic_series) < 2:
            return 0.0, 0.0, 0.0
        arr = np.asarray(ic_series, dtype=float)
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        ir = mean / std if std > 0 else 0.0
        return round(ir, 4), round(mean, 4), round(std, 4)


__all__ = ["QuintileExperiment", "QuintileResult"]
