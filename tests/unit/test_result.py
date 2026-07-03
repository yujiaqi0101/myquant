"""
tests/unit/test_result.py
=========================

回测结果与绩效指标单元测试（src/core/result.py）。

覆盖：
    1. BacktestResult 数据类基础方法（ok / to_summary / to_dict）
    2. PerformanceCalculator 空净值曲线返回 error
    3. PerformanceCalculator 计算关键指标（总收益/最终资产/交易统计）
    4. 默认常量（TRADING_DAYS_PER_YEAR/DEFAULT_BENCHMARK）

不依赖数据库：BenchmarkProvider 跳过（None），超额指标置 0。

运行：
    python -m pytest tests/unit/test_result.py -v
"""

from datetime import datetime, timedelta
from typing import List, Tuple

import pytest

from src.core.portfolio import Portfolio
from src.core.result import (
    DEFAULT_BENCHMARK,
    DEFAULT_RISK_FREE_RATE,
    TRADING_DAYS_PER_YEAR,
    BacktestResult,
    PerformanceCalculator,
)
from src.core.types import Direction, Fill


# ---------------------------------------------------------------------------
# 1. 默认常量
# ---------------------------------------------------------------------------


def test_default_constants() -> None:
    """默认常量值正确。"""
    assert TRADING_DAYS_PER_YEAR == 252
    assert DEFAULT_RISK_FREE_RATE == 0.0
    assert DEFAULT_BENCHMARK == "000300.SH"


# ---------------------------------------------------------------------------
# 2. BacktestResult 基础方法
# ---------------------------------------------------------------------------


def test_backtest_result_ok_returns_true_when_no_error() -> None:
    """error 为 None 时 ok() 返回 True。"""
    r = BacktestResult()
    assert r.ok() is True


def test_backtest_result_ok_returns_false_with_error() -> None:
    """error 非 None 时 ok() 返回 False。"""
    r = BacktestResult(error="回测失败")
    assert r.ok() is False


def test_backtest_result_to_summary_contains_key_metrics() -> None:
    """to_summary 应包含关键指标关键词。"""
    r = BacktestResult(
        total_return=15.5,
        annual_return=10.0,
        final_equity=1_155_000,
        max_drawdown=8.5,
        sharpe=1.2,
    )
    summary = r.to_summary()
    assert "回测绩效摘要" in summary
    assert "总收益" in summary
    assert "15.50%" in summary
    assert "夏普" in summary


def test_backtest_result_to_dict_has_all_fields() -> None:
    """to_dict 应包含全部 22+ 字段。"""
    r = BacktestResult(total_return=10.0, sharpe=1.0, beta=0.9)
    d = r.to_dict()
    expected_keys = {
        "total_return", "annual_return", "final_equity",
        "trade_count", "win_count", "loss_count", "win_rate",
        "max_drawdown", "sharpe", "calmar",
        "excess_return", "beta", "alpha", "information_ratio",
        "benchmark_code", "error",
    }
    assert expected_keys.issubset(d.keys())


# ---------------------------------------------------------------------------
# 3. PerformanceCalculator 空净值
# ---------------------------------------------------------------------------


def test_performance_calculator_empty_equity_curve_returns_error(
    portfolio: Portfolio,
) -> None:
    """空净值曲线返回 error。"""
    calc = PerformanceCalculator(portfolio)
    result = calc.calculate()
    assert not result.ok()
    assert "净值曲线为空" in result.error


# ---------------------------------------------------------------------------
# 4. PerformanceCalculator 完整流程
# ---------------------------------------------------------------------------


def test_performance_calculator_with_simple_equity_curve(
    portfolio: Portfolio, make_fill: callable
) -> None:
    """完整流程：构造净值曲线，验证关键指标计算。"""
    # 模拟 5 个交易日的净值曲线（无交易，纯资金）
    base = datetime(2024, 6, 1)
    for i in range(5):
        ts = base + timedelta(days=i)
        # 假设总资产每天上涨 1%（1M → 1.01M → 1.0201M ...）
        total = 1_000_000 * (1.01 ** i)
        # 注入现金使 portfolio.total_value 等于 total
        # 简化：直接操作 equity_curve
        portfolio.equity_curve.append((ts, total))
        portfolio.trade_dates.append(ts)

    # 加 1 笔交易记录用于交易统计
    fill = make_fill(direction="buy", volume=100, price=10.0)
    portfolio.fills.append(fill)
    # 不生成 Trade（避免引入复杂盈亏）

    calc = PerformanceCalculator(portfolio)
    result = calc.calculate()

    # 关键指标
    assert result.ok()
    # 5 个净值点产生 4 个日收益率，trading_days = 4
    assert result.trading_days == 4
    # 总收益 = (1.01^4 - 1) × 100% ≈ 4.06%
    assert result.total_return == pytest.approx(4.0604, rel=1e-3)
    assert result.final_equity == pytest.approx(1_040_604.01, rel=1e-3)
    # 上涨天数应为 4（4 个日收益率全部 > 0）
    assert result.up_days == 4
    # 日胜率 100%（每天盈亏 > 0）
    assert result.daily_win_rate == 100.0


def test_performance_calculator_calculates_drawdown(
    portfolio: Portfolio,
) -> None:
    """最大回撤计算：构造先涨后跌的净值曲线。"""
    # 1M → 1.1M（涨10%）→ 0.99M（跌10%）→ 1.05M
    base = datetime(2024, 6, 1)
    values = [1_000_000, 1_100_000, 990_000, 1_050_000]
    for i, v in enumerate(values):
        portfolio.equity_curve.append((base + timedelta(days=i), v))
        portfolio.trade_dates.append(base + timedelta(days=i))

    calc = PerformanceCalculator(portfolio)
    result = calc.calculate()

    # 最大回撤：从 1.1M 跌到 0.99M = 10%
    assert result.max_drawdown == pytest.approx(10.0, abs=0.5)


def test_performance_calculator_without_benchmark_zeros_excess(
    portfolio: Portfolio,
) -> None:
    """无 BenchmarkProvider 时超额指标为 0。"""
    base = datetime(2024, 6, 1)
    for i in range(3):
        portfolio.equity_curve.append((base + timedelta(days=i), 1_000_000))
        portfolio.trade_dates.append(base + timedelta(days=i))

    calc = PerformanceCalculator(portfolio, benchmark_provider=None)
    result = calc.calculate()
    assert result.excess_return == 0.0
    assert result.beta == 0.0
    assert result.alpha == 0.0
    assert result.benchmark_code == ""
