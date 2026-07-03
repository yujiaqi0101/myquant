"""
src/core/result.py
==================

回测结果与绩效指标模块（事件驱动内核的输出层）。

本模块定义统一的回测输出 BacktestResult，并实现完整的绩效指标计算（22+ 项），
覆盖收益/交易统计/日胜率/回撤/波动/换手率/风险调整/超额收益等维度，
同时支持沪深300等基准对比（Beta/Alpha/信息比率）。

设计目标（设计文档第 6.2 节）：
    1. 统一输出：所有引擎（回测/模拟盘/实盘）共用 BacktestResult
    2. 完整指标：22+ 项绩效指标，含基准对比
    3. 基准可配：默认沪深300（000300.SH），可通过 CLI --benchmark 切换
    4. 纯计算：不依赖引擎内部状态，从 Portfolio 的净值曲线/交易记录计算

绩效指标分类（设计文档 6.2 节）：
    - 收益类：总收益、年化收益、最终资产
    - 交易统计：平仓次数、盈利/亏损次数、胜率、最大/平均单次盈亏、盈亏比
    - 日胜率/涨跌：日胜率、交易天数、上涨/下跌天数、最大连续上涨/下跌天数
    - 回撤类：最大回撤、最大回撤持续天数、最大回撤时段、最长不创新高天数、最大日回撤
    - 日波动：单日最大上涨、单日最大下跌
    - 换手率：年换手率
    - 风险调整：夏普比率、卡尔玛比率
    - 超额收益：超额收益、超额年化、Beta、Alpha、信息比率

用法示例：
    from src.core.result import BacktestResult, PerformanceCalculator, BenchmarkProvider
    calc = PerformanceCalculator(portfolio, benchmark_provider)
    result = calc.calculate(start_date, end_date)
    print(result.to_summary())
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import math


# ---------------------------------------------------------------------------
# 默认参数
# ---------------------------------------------------------------------------

# A 股年化交易日数（用于年化收益/夏普等计算）
TRADING_DAYS_PER_YEAR: int = 252
# 默认无风险利率（年化，简化为 0，可按需调整）
DEFAULT_RISK_FREE_RATE: float = 0.0
# 默认基准代码：沪深300
DEFAULT_BENCHMARK: str = "000300.SH"


# ---------------------------------------------------------------------------
# BacktestResult：统一回测输出
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    """统一回测结果。

    包含绩效指标、净值曲线、交易记录、持仓快照等全部输出。
    所有引擎（回测/模拟盘/实盘）共用本结构，便于报告生成与对比分析。

    Attributes:
        --- 收益类 ---
        total_return: 总收益率（百分比，如 12.34 表示 12.34%）
        annual_return: 年化收益率（百分比）
        final_equity: 最终总资产

        --- 交易统计 ---
        trade_count: 平仓次数（完成的 Trade 数量）
        win_count: 盈利次数
        loss_count: 亏损次数
        win_rate: 胜率（百分比）
        max_win: 最大单次盈利金额
        avg_win: 平均单次盈利金额
        max_loss: 最大单次亏损金额（负数）
        avg_loss: 平均单次亏损金额（负数）
        profit_loss_ratio: 盈亏比 = 平均盈利 / |平均亏损|

        --- 日胜率/涨跌 ---
        daily_win_rate: 日胜率（百分比，当日盈亏>0 计为胜）
        trading_days: 交易天数
        up_days: 上涨天数
        down_days: 下跌天数
        max_consecutive_up: 最大连续上涨天数
        max_consecutive_down: 最大连续下跌天数

        --- 回撤类 ---
        max_drawdown: 最大回撤（百分比，正数）
        max_drawdown_duration: 最大回撤持续天数
        max_drawdown_period: 最大回撤时段（字符串，如 "2024-01-15 ~ 2024-03-20"）
        longest_no_new_high: 最长不创新高天数
        max_daily_drawdown: 最大日回撤（百分比，正数）

        --- 日波动 ---
        max_daily_up: 单日最大上涨（百分比）
        max_daily_down: 单日最大下跌（百分比）

        --- 换手率 ---
        annual_turnover: 年换手率（百分比）

        --- 风险调整 ---
        sharpe: 夏普比率
        calmar: 卡尔玛比率

        --- 超额收益（相对基准）---
        excess_return: 超额收益（累计，百分比）
        excess_annual_return: 超额年化收益（百分比）
        beta: Beta 系数
        alpha: Alpha（年化，百分比）
        information_ratio: 信息比率

        --- 原始数据 ---
        equity_curve: 净值曲线 [(datetime, total_value), ...]
        trades: 平仓交易记录列表
        fills: 全部成交流水
        benchmark_code: 基准代码
        error: 错误信息（None 表示成功）
    """

    # 收益类
    total_return: float = 0.0
    annual_return: float = 0.0
    final_equity: float = 0.0

    # 交易统计
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    max_win: float = 0.0
    avg_win: float = 0.0
    max_loss: float = 0.0
    avg_loss: float = 0.0
    profit_loss_ratio: float = 0.0

    # 日胜率/涨跌
    daily_win_rate: float = 0.0
    trading_days: int = 0
    up_days: int = 0
    down_days: int = 0
    max_consecutive_up: int = 0
    max_consecutive_down: int = 0

    # 回撤类
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    max_drawdown_period: str = ""
    longest_no_new_high: int = 0
    max_daily_drawdown: float = 0.0

    # 日波动
    max_daily_up: float = 0.0
    max_daily_down: float = 0.0

    # 换手率
    annual_turnover: float = 0.0

    # 风险调整
    sharpe: float = 0.0
    calmar: float = 0.0

    # 超额收益
    excess_return: float = 0.0
    excess_annual_return: float = 0.0
    beta: float = 0.0
    alpha: float = 0.0
    information_ratio: float = 0.0

    # 原始数据
    equity_curve: List[Tuple[Any, float]] = field(default_factory=list)
    trades: List[Any] = field(default_factory=list)
    fills: List[Any] = field(default_factory=list)
    benchmark_code: str = ""
    error: Optional[str] = None

    def ok(self) -> bool:
        """回测是否成功（无错误）。"""
        return self.error is None

    def to_summary(self) -> str:
        """生成可读的绩效摘要文本。"""
        lines = [
            "==================== 回测绩效摘要 ====================",
            f"总收益: {self.total_return:.2f}%   年化收益: {self.annual_return:.2f}%",
            f"最终资产: {self.final_equity:,.2f}",
            f"最大回撤: {self.max_drawdown:.2f}%   夏普比率: {self.sharpe:.3f}   卡尔玛: {self.calmar:.3f}",
            "-------------------- 交易统计 --------------------",
            f"平仓次数: {self.trade_count}   胜率: {self.win_rate:.2f}%",
            f"盈利次数: {self.win_count}   亏损次数: {self.loss_count}   盈亏比: {self.profit_loss_ratio:.2f}",
            f"最大单次盈利: {self.max_win:,.2f}   平均盈利: {self.avg_win:,.2f}",
            f"最大单次亏损: {self.max_loss:,.2f}   平均亏损: {self.avg_loss:,.2f}",
            "-------------------- 日胜率/涨跌 --------------------",
            f"日胜率: {self.daily_win_rate:.2f}%   交易天数: {self.trading_days}",
            f"上涨天数: {self.up_days}   下跌天数: {self.down_days}",
            f"最大连续上涨: {self.max_consecutive_up}天   最大连续下跌: {self.max_consecutive_down}天",
            "-------------------- 回撤/波动 --------------------",
            f"最大回撤: {self.max_drawdown:.2f}%   持续: {self.max_drawdown_duration}天",
            f"最大回撤时段: {self.max_drawdown_period or '无'}",
            f"最长不创新高: {self.longest_no_new_high}天   最大日回撤: {self.max_daily_drawdown:.2f}%",
            f"单日最大上涨: {self.max_daily_up:.2f}%   单日最大下跌: {self.max_daily_down:.2f}%",
            "-------------------- 换手率 --------------------",
            f"年换手率: {self.annual_turnover:.2f}%",
            "-------------------- 超额收益（基准: "
            + (self.benchmark_code or "无")
            + "）--------------------",
            f"超额收益: {self.excess_return:.2f}%   超额年化: {self.excess_annual_return:.2f}%",
            f"Beta: {self.beta:.3f}   Alpha(年化): {self.alpha:.2f}%   信息比率: {self.information_ratio:.3f}",
            "====================================================",
        ]
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典（JSON 序列化/报告生成用）。"""
        return {
            "total_return": self.total_return,
            "annual_return": self.annual_return,
            "final_equity": self.final_equity,
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": self.win_rate,
            "max_win": self.max_win,
            "avg_win": self.avg_win,
            "max_loss": self.max_loss,
            "avg_loss": self.avg_loss,
            "profit_loss_ratio": self.profit_loss_ratio,
            "daily_win_rate": self.daily_win_rate,
            "trading_days": self.trading_days,
            "up_days": self.up_days,
            "down_days": self.down_days,
            "max_consecutive_up": self.max_consecutive_up,
            "max_consecutive_down": self.max_consecutive_down,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_duration": self.max_drawdown_duration,
            "max_drawdown_period": self.max_drawdown_period,
            "longest_no_new_high": self.longest_no_new_high,
            "max_daily_drawdown": self.max_daily_drawdown,
            "max_daily_up": self.max_daily_up,
            "max_daily_down": self.max_daily_down,
            "annual_turnover": self.annual_turnover,
            "sharpe": self.sharpe,
            "calmar": self.calmar,
            "excess_return": self.excess_return,
            "excess_annual_return": self.excess_annual_return,
            "beta": self.beta,
            "alpha": self.alpha,
            "information_ratio": self.information_ratio,
            "benchmark_code": self.benchmark_code,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# BenchmarkProvider：基准数据提供者
# ---------------------------------------------------------------------------


class BenchmarkProvider:
    """基准数据提供者。

    从数据库 t_index_daily 表读取基准指数（如沪深300）的日频收盘价，
    用于计算超额收益/Beta/Alpha/信息比率。

    解耦设计：PerformanceCalculator 可选依赖本类，无基准时超额指标置 0。

    Parameters
    ----------
    db : DatabaseManager
        数据库管理器（需有 get_index_daily 方法）
    benchmark_code : str
        基准指数代码，默认 000300.SH（沪深300）
    """

    def __init__(self, db: Any, benchmark_code: str = DEFAULT_BENCHMARK):
        self.db = db
        self.benchmark_code = benchmark_code
        # 缓存基准序列：[(datetime, close), ...]
        self._cache: Optional[List[Tuple[Any, float]]] = None

    def load(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Tuple[Any, float]]:
        """加载基准收盘价序列。

        Args:
            start_date: 起始日期（YYYY-MM-DD），None 不限制
            end_date: 结束日期（YYYY-MM-DD），None 不限制

        Returns:
            [(datetime, close_price), ...] 按日期升序
        """
        if self.db is None:
            return []
        try:
            df = self.db.get_index_daily(
                index_codes=[self.benchmark_code],
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            return []

        if df is None or df.empty:
            return []

        # df 的索引是 (trade_date, index_code)，close 列为收盘价
        result: List[Tuple[Any, float]] = []
        try:
            # 重置索引取 trade_date 和 close
            df_reset = df.reset_index()
            for _, row in df_reset.iterrows():
                trade_date = row.get("trade_date")
                close = row.get("close")
                if trade_date is not None and close is not None:
                    result.append((trade_date, float(close)))
        except Exception:
            return []
        return result

    def get_returns(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[float]:
        """获取基准日收益率序列。

        Returns:
            [daily_return, ...] 日收益率列表（小数，如 0.0123 表示 1.23%）
        """
        series = self.load(start_date, end_date)
        if len(series) < 2:
            return []
        returns: List[float] = []
        for i in range(1, len(series)):
            prev_close = series[i - 1][1]
            curr_close = series[i][1]
            if prev_close > 0:
                returns.append((curr_close - prev_close) / prev_close)
            else:
                returns.append(0.0)
        return returns

    def get_total_return(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> float:
        """获取基准累计收益率（小数）。"""
        series = self.load(start_date, end_date)
        if len(series) < 2:
            return 0.0
        start_close = series[0][1]
        end_close = series[-1][1]
        if start_close <= 0:
            return 0.0
        return (end_close - start_close) / start_close


# ---------------------------------------------------------------------------
# PerformanceCalculator：绩效指标计算器
# ---------------------------------------------------------------------------


class PerformanceCalculator:
    """绩效指标计算器。

    从 Portfolio 的净值曲线、交易记录、成交流水计算 22+ 项绩效指标，
    生成 BacktestResult。可选依赖 BenchmarkProvider 计算超额收益。

    Parameters
    ----------
    portfolio : Portfolio
        回测结束后的 Portfolio 实例（含完整净值曲线和交易记录）
    benchmark_provider : BenchmarkProvider, optional
        基准数据提供者，None 时不计算超额指标
    risk_free_rate : float
        无风险年化利率（默认 0）
    trading_days_per_year : int
        年化交易日数（默认 252）
    """

    def __init__(
        self,
        portfolio: Any,
        benchmark_provider: Optional[BenchmarkProvider] = None,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
    ):
        self.portfolio = portfolio
        self.benchmark = benchmark_provider
        self.risk_free_rate = risk_free_rate
        self.trading_days_per_year = trading_days_per_year

    def calculate(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> BacktestResult:
        """计算全部绩效指标，返回 BacktestResult。

        Args:
            start_date: 回测起始日期（用于基准查询，YYYY-MM-DD）
            end_date: 回测结束日期（用于基准查询，YYYY-MM-DD）
        """
        pf = self.portfolio
        equity_curve: List[Tuple[Any, float]] = list(pf.equity_curve)

        # 净值曲线为空，返回空结果
        if not equity_curve:
            return BacktestResult(
                error="净值曲线为空，无法计算绩效指标",
                equity_curve=[],
                trades=list(pf.trades),
                fills=list(pf.fills),
                benchmark_code=self.benchmark.benchmark_code if self.benchmark else "",
            )

        # 提取总资产序列（每日总资产）
        totals: List[float] = [v for _, v in equity_curve]
        timestamps: List[Any] = [t for t, _ in equity_curve]

        # 计算日收益率序列
        daily_returns: List[float] = self._calc_daily_returns(totals)

        # ---------- 收益类 ----------
        initial = pf.initial_capital
        final_equity = totals[-1]
        total_return = (final_equity - initial) / initial * 100 if initial > 0 else 0.0
        # 年化收益 = (最终/初始)^(252/天数) - 1
        n_days = len(totals)
        annual_return = self._annualized_return(final_equity, initial, n_days)

        # ---------- 交易统计 ----------
        trades = list(pf.trades)
        trade_stats = self._calc_trade_stats(trades)

        # ---------- 日胜率/涨跌 ----------
        daily_stats = self._calc_daily_stats(daily_returns)

        # ---------- 回撤类 ----------
        drawdown_stats = self._calc_drawdown_stats(totals, timestamps)

        # ---------- 日波动 ----------
        volatility_stats = self._calc_volatility_stats(daily_returns)

        # ---------- 换手率 ----------
        annual_turnover = self._calc_annual_turnover(pf.fills, initial, n_days)

        # ---------- 风险调整 ----------
        sharpe = self._calc_sharpe(daily_returns)
        calmar = self._calc_calmar(annual_return, drawdown_stats["max_drawdown"])

        # ---------- 超额收益 ----------
        excess_stats = self._calc_excess_stats(
            daily_returns, totals, start_date, end_date
        )

        benchmark_code = (
            self.benchmark.benchmark_code if self.benchmark is not None else ""
        )

        return BacktestResult(
            # 收益类
            total_return=round(total_return, 4),
            annual_return=round(annual_return, 4),
            final_equity=round(final_equity, 2),
            # 交易统计
            trade_count=trade_stats["trade_count"],
            win_count=trade_stats["win_count"],
            loss_count=trade_stats["loss_count"],
            win_rate=round(trade_stats["win_rate"], 4),
            max_win=round(trade_stats["max_win"], 2),
            avg_win=round(trade_stats["avg_win"], 2),
            max_loss=round(trade_stats["max_loss"], 2),
            avg_loss=round(trade_stats["avg_loss"], 2),
            profit_loss_ratio=round(trade_stats["profit_loss_ratio"], 4),
            # 日胜率/涨跌
            daily_win_rate=round(daily_stats["daily_win_rate"], 4),
            trading_days=daily_stats["trading_days"],
            up_days=daily_stats["up_days"],
            down_days=daily_stats["down_days"],
            max_consecutive_up=daily_stats["max_consecutive_up"],
            max_consecutive_down=daily_stats["max_consecutive_down"],
            # 回撤类
            max_drawdown=round(drawdown_stats["max_drawdown"], 4),
            max_drawdown_duration=drawdown_stats["max_drawdown_duration"],
            max_drawdown_period=drawdown_stats["max_drawdown_period"],
            longest_no_new_high=drawdown_stats["longest_no_new_high"],
            max_daily_drawdown=round(drawdown_stats["max_daily_drawdown"], 4),
            # 日波动
            max_daily_up=round(volatility_stats["max_daily_up"], 4),
            max_daily_down=round(volatility_stats["max_daily_down"], 4),
            # 换手率
            annual_turnover=round(annual_turnover, 4),
            # 风险调整
            sharpe=round(sharpe, 4),
            calmar=round(calmar, 4),
            # 超额收益
            excess_return=round(excess_stats["excess_return"], 4),
            excess_annual_return=round(excess_stats["excess_annual_return"], 4),
            beta=round(excess_stats["beta"], 4),
            alpha=round(excess_stats["alpha"], 4),
            information_ratio=round(excess_stats["information_ratio"], 4),
            # 原始数据
            equity_curve=equity_curve,
            trades=trades,
            fills=list(pf.fills),
            benchmark_code=benchmark_code,
        )

    # ------------------------------------------------------------------
    # 收益类计算
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_daily_returns(totals: List[float]) -> List[float]:
        """计算日收益率序列。

        日收益率 = (当日总资产 - 前日总资产) / 前日总资产
        """
        returns: List[float] = []
        for i in range(1, len(totals)):
            prev = totals[i - 1]
            curr = totals[i]
            if prev > 0:
                returns.append((curr - prev) / prev)
            else:
                returns.append(0.0)
        return returns

    def _annualized_return(
        self, final: float, initial: float, n_days: int
    ) -> float:
        """年化收益率（百分比）。

        公式：(final/initial)^(252/n_days) - 1，再 ×100
        """
        if initial <= 0 or n_days <= 0:
            return 0.0
        ratio = final / initial
        if ratio <= 0:
            return -100.0
        # 年化因子
        factor = self.trading_days_per_year / n_days
        ann = ratio ** factor - 1
        return ann * 100

    # ------------------------------------------------------------------
    # 交易统计计算
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_trade_stats(trades: List[Any]) -> Dict[str, Any]:
        """计算交易统计：胜率/盈亏/盈亏比。"""
        if not trades:
            return {
                "trade_count": 0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0.0,
                "max_win": 0.0,
                "avg_win": 0.0,
                "max_loss": 0.0,
                "avg_loss": 0.0,
                "profit_loss_ratio": 0.0,
            }

        pnls = [t.pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        win_count = len(wins)
        loss_count = len(losses)
        total = win_count + loss_count
        win_rate = (win_count / total * 100) if total > 0 else 0.0

        max_win = max(wins) if wins else 0.0
        avg_win = (sum(wins) / win_count) if win_count > 0 else 0.0
        max_loss = min(losses) if losses else 0.0
        avg_loss = (sum(losses) / loss_count) if loss_count > 0 else 0.0

        # 盈亏比 = 平均盈利 / |平均亏损|
        profit_loss_ratio = (
            avg_win / abs(avg_loss) if avg_loss != 0 else 0.0
        )

        return {
            "trade_count": len(trades),
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": win_rate,
            "max_win": max_win,
            "avg_win": avg_win,
            "max_loss": max_loss,
            "avg_loss": avg_loss,
            "profit_loss_ratio": profit_loss_ratio,
        }

    # ------------------------------------------------------------------
    # 日胜率/涨跌计算
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_daily_stats(daily_returns: List[float]) -> Dict[str, Any]:
        """计算日胜率/上涨下跌天数/最大连续涨跌天数。"""
        if not daily_returns:
            return {
                "daily_win_rate": 0.0,
                "trading_days": 0,
                "up_days": 0,
                "down_days": 0,
                "max_consecutive_up": 0,
                "max_consecutive_down": 0,
            }

        up_days = sum(1 for r in daily_returns if r > 0)
        down_days = sum(1 for r in daily_returns if r < 0)
        flat_days = sum(1 for r in daily_returns if r == 0)
        trading_days = len(daily_returns)
        # 日胜率：收益>0 计为胜（持平不计胜）
        daily_win_rate = (up_days / trading_days * 100) if trading_days > 0 else 0.0

        # 最大连续上涨/下跌天数
        max_up = 0
        max_down = 0
        cur_up = 0
        cur_down = 0
        for r in daily_returns:
            if r > 0:
                cur_up += 1
                cur_down = 0
                if cur_up > max_up:
                    max_up = cur_up
            elif r < 0:
                cur_down += 1
                cur_up = 0
                if cur_down > max_down:
                    max_down = cur_down
            else:
                cur_up = 0
                cur_down = 0

        return {
            "daily_win_rate": daily_win_rate,
            "trading_days": trading_days,
            "up_days": up_days,
            "down_days": down_days,
            "max_consecutive_up": max_up,
            "max_consecutive_down": max_down,
        }

    # ------------------------------------------------------------------
    # 回撤类计算
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_drawdown_stats(
        totals: List[float], timestamps: List[Any]
    ) -> Dict[str, Any]:
        """计算最大回撤相关指标。

        - max_drawdown: 历史峰值到谷底的最大跌幅（百分比，正数）
        - max_drawdown_duration: 从峰值到恢复新高的天数
        - max_drawdown_period: 最大回撤时段字符串
        - longest_no_new_high: 最长不创新高天数
        - max_daily_drawdown: 单日最大回撤（百分比，正数）
        """
        if not totals:
            return {
                "max_drawdown": 0.0,
                "max_drawdown_duration": 0,
                "max_drawdown_period": "",
                "longest_no_new_high": 0,
                "max_daily_drawdown": 0.0,
            }

        # 单日最大回撤（取日收益率最小值的绝对值）
        max_daily_drawdown = 0.0
        for i in range(1, len(totals)):
            if totals[i - 1] > 0:
                daily_dd = (totals[i - 1] - totals[i]) / totals[i - 1]
                if daily_dd > max_daily_drawdown:
                    max_daily_drawdown = daily_dd
        max_daily_drawdown *= 100

        # 最大回撤：遍历计算峰值到谷底
        peak = totals[0]
        max_dd = 0.0
        max_dd_peak_idx = 0
        max_dd_trough_idx = 0
        current_peak_idx = 0
        current_peak = totals[0]

        for i, v in enumerate(totals):
            if v > current_peak:
                current_peak = v
                current_peak_idx = i
            if current_peak > 0:
                dd = (current_peak - v) / current_peak
                if dd > max_dd:
                    max_dd = dd
                    max_dd_peak_idx = current_peak_idx
                    max_dd_trough_idx = i

        max_drawdown = max_dd * 100

        # 最大回撤持续天数：从峰值到恢复新高（或结束）
        # 从 max_dd_peak_idx 开始，找到首次 totals >= peak 的位置
        duration = 0
        peak_value = totals[max_dd_peak_idx]
        for i in range(max_dd_peak_idx, len(totals)):
            if totals[i] >= peak_value and i > max_dd_peak_idx:
                break
            duration += 1

        # 最大回撤时段字符串
        period = ""
        if max_dd > 0 and max_dd_trough_idx < len(timestamps):
            start_ts = timestamps[max_dd_peak_idx]
            end_ts = timestamps[max_dd_trough_idx]
            start_str = (
                start_ts.strftime("%Y-%m-%d")
                if hasattr(start_ts, "strftime")
                else str(start_ts)
            )
            end_str = (
                end_ts.strftime("%Y-%m-%d")
                if hasattr(end_ts, "strftime")
                else str(end_ts)
            )
            period = f"{start_str} ~ {end_str}"

        # 最长不创新高天数
        longest_no_new_high = 0
        cur_peak = totals[0]
        cur_gap = 0
        for v in totals[1:]:
            if v > cur_peak:
                cur_peak = v
                if cur_gap > longest_no_new_high:
                    longest_no_new_high = cur_gap
                cur_gap = 0
            else:
                cur_gap += 1
        if cur_gap > longest_no_new_high:
            longest_no_new_high = cur_gap

        return {
            "max_drawdown": max_drawdown,
            "max_drawdown_duration": duration,
            "max_drawdown_period": period,
            "longest_no_new_high": longest_no_new_high,
            "max_daily_drawdown": max_daily_drawdown,
        }

    # ------------------------------------------------------------------
    # 日波动计算
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_volatility_stats(daily_returns: List[float]) -> Dict[str, float]:
        """计算单日最大上涨/下跌（百分比）。"""
        if not daily_returns:
            return {"max_daily_up": 0.0, "max_daily_down": 0.0}
        max_up = max(daily_returns) * 100
        max_down = min(daily_returns) * 100
        return {"max_daily_up": max_up, "max_daily_down": max_down}

    # ------------------------------------------------------------------
    # 换手率计算
    # ------------------------------------------------------------------

    def _calc_annual_turnover(
        self,
        fills: List[Any],
        initial_capital: float,
        n_days: int,
    ) -> float:
        """计算年换手率（百分比）。

        年换手率 = (总成交额 / 平均总资产) × (252 / 交易天数) × 100
        简化：平均总资产用 initial_capital 近似
        """
        if not fills or n_days <= 0 or initial_capital <= 0:
            return 0.0
        # 总成交额 = sum(每个 fill 的成交金额)
        total_turnover = sum(f.turnover for f in fills)
        avg_capital = initial_capital
        annual_factor = self.trading_days_per_year / n_days
        return (total_turnover / avg_capital) * annual_factor * 100

    # ------------------------------------------------------------------
    # 风险调整指标计算
    # ------------------------------------------------------------------

    def _calc_sharpe(self, daily_returns: List[float]) -> float:
        """夏普比率。

        公式：(年化均值收益 - 无风险利率) / 年化标准差
        年化：均值 × 252，标准差 × sqrt(252)
        """
        if len(daily_returns) < 2:
            return 0.0
        n = len(daily_returns)
        mean_r = sum(daily_returns) / n
        var = sum((r - mean_r) ** 2 for r in daily_returns) / (n - 1)
        std = math.sqrt(var)
        if std <= 0:
            return 0.0
        # 年化
        ann_mean = mean_r * self.trading_days_per_year
        ann_std = std * math.sqrt(self.trading_days_per_year)
        # 无风险利率已年化，转日频对比
        rf_daily = self.risk_free_rate / self.trading_days_per_year
        excess = ann_mean - self.risk_free_rate
        return excess / ann_std if ann_std > 0 else 0.0

    @staticmethod
    def _calc_calmar(annual_return: float, max_drawdown: float) -> float:
        """卡尔玛比率 = 年化收益 / 最大回撤。

        annual_return 和 max_drawdown 均为百分比（如 12.34 / 8.5）。
        """
        if max_drawdown <= 0:
            return 0.0
        return annual_return / max_drawdown

    # ------------------------------------------------------------------
    # 超额收益计算
    # ------------------------------------------------------------------

    def _calc_excess_stats(
        self,
        daily_returns: List[float],
        totals: List[float],
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Dict[str, float]:
        """计算超额收益/Beta/Alpha/信息比率。"""
        # 无基准时全部置 0
        if self.benchmark is None:
            return {
                "excess_return": 0.0,
                "excess_annual_return": 0.0,
                "beta": 0.0,
                "alpha": 0.0,
                "information_ratio": 0.0,
            }

        benchmark_returns = self.benchmark.get_returns(start_date, end_date)
        if not benchmark_returns:
            return {
                "excess_return": 0.0,
                "excess_annual_return": 0.0,
                "beta": 0.0,
                "alpha": 0.0,
                "information_ratio": 0.0,
            }

        # 对齐长度（取较小值）
        n = min(len(daily_returns), len(benchmark_returns))
        if n < 2:
            return {
                "excess_return": 0.0,
                "excess_annual_return": 0.0,
                "beta": 0.0,
                "alpha": 0.0,
                "information_ratio": 0.0,
            }

        port_returns = daily_returns[:n]
        bench_returns = benchmark_returns[:n]

        # 超额日收益率序列
        excess_daily = [p - b for p, b in zip(port_returns, bench_returns)]

        # 超额累计收益（百分比）
        # 策略累计收益
        port_total = 1.0
        for r in port_returns:
            port_total *= (1 + r)
        bench_total = 1.0
        for r in bench_returns:
            bench_total *= (1 + r)
        excess_return = (port_total - bench_total) * 100

        # 超额年化收益
        excess_annual = self._annualized_return(
            port_total, bench_total, n
        )

        # Beta = Cov(port, bench) / Var(bench)
        mean_p = sum(port_returns) / n
        mean_b = sum(bench_returns) / n
        cov = sum(
            (p - mean_p) * (b - mean_b) for p, b in zip(port_returns, bench_returns)
        ) / (n - 1)
        var_b = sum((b - mean_b) ** 2 for b in bench_returns) / (n - 1)
        beta = cov / var_b if var_b > 0 else 0.0

        # Alpha（年化，CAPM）
        # 日 Alpha = 平均超额收益 - Beta × 平均基准收益
        # 年化 Alpha = 日 Alpha × 252 × 100（百分比）
        mean_excess = sum(excess_daily) / n
        daily_alpha = mean_excess - beta * mean_b
        alpha = daily_alpha * self.trading_days_per_year * 100

        # 信息比率 = 平均超额收益 / 跟踪误差
        # 跟踪误差 = 超额收益的标准差（年化）
        if len(excess_daily) > 1:
            var_excess = sum(
                (e - mean_excess) ** 2 for e in excess_daily
            ) / (len(excess_daily) - 1)
            te = math.sqrt(var_excess)
            te_annual = te * math.sqrt(self.trading_days_per_year)
            ir = (
                (mean_excess * self.trading_days_per_year) / te_annual
                if te_annual > 0
                else 0.0
            )
        else:
            ir = 0.0

        return {
            "excess_return": excess_return,
            "excess_annual_return": excess_annual,
            "beta": beta,
            "alpha": alpha,
            "information_ratio": ir,
        }
