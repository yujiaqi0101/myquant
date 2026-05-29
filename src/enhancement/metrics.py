"""
指标计算工具
============

提供指数增强分析所需的各类风险收益指标计算。
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional


class MetricsCalculator:
    """
    指标计算器

    提供指数增强分析的30+指标计算。
    """

    # ==================== 收益分析 ====================

    @staticmethod
    def excess_return(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> pd.Series:
        """计算超额收益序列"""
        return portfolio_returns - benchmark_returns

    @staticmethod
    def cumulative_alpha(excess_returns: pd.Series) -> pd.Series:
        """计算累计Alpha"""
        return (1 + excess_returns).cumprod() - 1

    @staticmethod
    def win_rate(excess_returns: pd.Series) -> float:
        """计算胜率（超额收益为正的比例）"""
        valid = excess_returns.dropna()
        return (valid > 0).sum() / len(valid) if len(valid) > 0 else 0.0

    @staticmethod
    def profit_loss_ratio(excess_returns: pd.Series) -> float:
        """计算盈亏比"""
        valid = excess_returns.dropna()
        wins = valid[valid > 0]
        losses = valid[valid < 0]
        if len(losses) == 0:
            return float('inf') if len(wins) > 0 else 0.0
        return wins.mean() / abs(losses.mean())

    # ==================== 跟踪与信息比率 ====================

    @staticmethod
    def tracking_error(excess_returns: pd.Series, annualize: bool = True) -> float:
        """计算跟踪误差"""
        valid = excess_returns.dropna()
        if len(valid) < 2:
            return 0.0
        te = valid.std()
        return te * np.sqrt(252) if annualize else te

    @staticmethod
    def information_ratio(excess_returns: pd.Series, tracking_error: float = None) -> float:
        """计算信息比率"""
        valid = excess_returns.dropna()
        if len(valid) < 2:
            return 0.0
        annual_excess = valid.mean() * 252
        if tracking_error is None:
            tracking_error = MetricsCalculator.tracking_error(valid)
        return annual_excess / tracking_error if tracking_error > 0 else 0.0

    # ==================== Beta与Alpha ====================

    @staticmethod
    def beta(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> float:
        """计算Beta系数"""
        aligned = pd.DataFrame({'p': portfolio_returns, 'b': benchmark_returns}).dropna()
        if len(aligned) < 2:
            return 1.0
        cov = np.cov(aligned['p'], aligned['b'])[0, 1]
        var = np.var(aligned['b'])
        return cov / var if var > 0 else 1.0

    @staticmethod
    def alpha(portfolio_returns: pd.Series, benchmark_returns: pd.Series,
              risk_free_rate: float = 0.03) -> float:
        """计算Jensen's Alpha（年化）"""
        b = MetricsCalculator.beta(portfolio_returns, benchmark_returns)
        p_annual = portfolio_returns.dropna().mean() * 252
        b_annual = benchmark_returns.dropna().mean() * 252
        return p_annual - risk_free_rate - b * (b_annual - risk_free_rate)

    @staticmethod
    def downside_beta(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> float:
        """计算下行Beta（仅市场下跌期间）"""
        aligned = pd.DataFrame({'p': portfolio_returns, 'b': benchmark_returns}).dropna()
        down = aligned[aligned['b'] < 0]
        if len(down) < 2:
            return 1.0
        cov = np.cov(down['p'], down['b'])[0, 1]
        var = np.var(down['b'])
        return cov / var if var > 0 else 1.0

    @staticmethod
    def rolling_beta(portfolio_returns: pd.Series, benchmark_returns: pd.Series,
                     window: int = 60) -> pd.Series:
        """计算滚动Beta"""
        aligned = pd.DataFrame({'p': portfolio_returns, 'b': benchmark_returns}).dropna()
        return aligned['p'].rolling(window).cov(aligned['b']) / aligned['b'].rolling(window).var()

    # ==================== 风险调整后收益 ====================

    @staticmethod
    def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.03) -> float:
        """计算夏普比率"""
        valid = returns.dropna()
        if len(valid) < 2:
            return 0.0
        excess = valid.mean() * 252 - risk_free_rate
        vol = valid.std() * np.sqrt(252)
        return excess / vol if vol > 0 else 0.0

    @staticmethod
    def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.03) -> float:
        """计算索提诺比率"""
        valid = returns.dropna()
        if len(valid) < 2:
            return 0.0
        excess = valid.mean() * 252 - risk_free_rate
        downside = valid[valid < 0].std() * np.sqrt(252)
        return excess / downside if downside > 0 else 0.0

    @staticmethod
    def calmar_ratio(returns: pd.Series) -> float:
        """计算卡玛比率"""
        valid = returns.dropna()
        if len(valid) < 2:
            return 0.0
        annual = valid.mean() * 252
        cum = (1 + valid).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        max_dd = abs(dd.min())
        return annual / max_dd if max_dd > 0 else 0.0

    @staticmethod
    def treynor_ratio(returns: pd.Series, benchmark_returns: pd.Series,
                      risk_free_rate: float = 0.03) -> float:
        """计算特雷诺比率"""
        b = MetricsCalculator.beta(returns, benchmark_returns)
        if abs(b) < 1e-6:
            return 0.0
        annual_excess = returns.dropna().mean() * 252 - risk_free_rate
        return annual_excess / b

    # ==================== 回撤与尾部风险 ====================

    @staticmethod
    def max_drawdown(returns: pd.Series) -> float:
        """计算最大回撤"""
        valid = returns.dropna()
        if len(valid) < 2:
            return 0.0
        cum = (1 + valid).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        return dd.min()

    @staticmethod
    def max_relative_drawdown(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> float:
        """计算最大相对回撤"""
        aligned = pd.DataFrame({'p': portfolio_returns, 'b': benchmark_returns}).dropna()
        if len(aligned) < 2:
            return 0.0
        cum_p = (1 + aligned['p']).cumprod()
        cum_b = (1 + aligned['b']).cumprod()
        ratio = cum_p / cum_b
        peak = ratio.cummax()
        dd = (ratio - peak) / peak
        return dd.min()

    @staticmethod
    def value_at_risk(returns: pd.Series, confidence: float = 0.95) -> float:
        """计算VaR"""
        valid = returns.dropna()
        if len(valid) < 10:
            return 0.0
        return np.percentile(valid, (1 - confidence) * 100)

    @staticmethod
    def cvar(returns: pd.Series, confidence: float = 0.95) -> float:
        """计算条件风险价值（CVaR）"""
        valid = returns.dropna()
        if len(valid) < 10:
            return 0.0
        var = MetricsCalculator.value_at_risk(valid, confidence)
        return valid[valid <= var].mean()

    @staticmethod
    def skewness(returns: pd.Series) -> float:
        """计算偏度"""
        valid = returns.dropna()
        if len(valid) < 10:
            return 0.0
        return valid.skew()

    @staticmethod
    def kurtosis(returns: pd.Series) -> float:
        """计算超额峰度"""
        valid = returns.dropna()
        if len(valid) < 10:
            return 0.0
        return valid.kurtosis()

    # ==================== 综合分析 ====================

    @staticmethod
    def full_analysis(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> Dict:
        """
        执行完整的指标分析

        Returns
        -------
        Dict
            包含所有分析指标的字典
        """
        excess = MetricsCalculator.excess_return(portfolio_returns, benchmark_returns)
        te = MetricsCalculator.tracking_error(excess)

        return {
            # 收益分析
            'excess_return': excess.mean() * 252,
            'cumulative_alpha': MetricsCalculator.cumulative_alpha(excess).iloc[-1] if len(excess) > 0 else 0.0,
            'win_rate': MetricsCalculator.win_rate(excess),
            'profit_loss_ratio': MetricsCalculator.profit_loss_ratio(excess),

            # 跟踪与信息比率
            'tracking_error': te,
            'information_ratio': MetricsCalculator.information_ratio(excess, te),

            # Beta与Alpha
            'beta': MetricsCalculator.beta(portfolio_returns, benchmark_returns),
            'alpha': MetricsCalculator.alpha(portfolio_returns, benchmark_returns),
            'downside_beta': MetricsCalculator.downside_beta(portfolio_returns, benchmark_returns),

            # 风险调整后收益
            'sharpe_ratio': MetricsCalculator.sharpe_ratio(portfolio_returns),
            'sortino_ratio': MetricsCalculator.sortino_ratio(portfolio_returns),
            'calmar_ratio': MetricsCalculator.calmar_ratio(portfolio_returns),
            'treynor_ratio': MetricsCalculator.treynor_ratio(portfolio_returns, benchmark_returns),

            # 回撤与尾部风险
            'max_drawdown': MetricsCalculator.max_drawdown(portfolio_returns),
            'max_relative_drawdown': MetricsCalculator.max_relative_drawdown(portfolio_returns, benchmark_returns),
            'var_95': MetricsCalculator.value_at_risk(portfolio_returns, 0.95),
            'cvar_95': MetricsCalculator.cvar(portfolio_returns, 0.95),
            'skewness': MetricsCalculator.skewness(portfolio_returns),
            'kurtosis': MetricsCalculator.kurtosis(portfolio_returns),
        }
