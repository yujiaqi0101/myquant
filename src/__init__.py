"""
A股量化分析系统
================

一个专注于分析的A股量化研究平台，包含：
- 市场阶段识别
- 股票走势相似度分析
- 因子组合筛选与反测
- 风控系统
- 可视化界面
"""

__version__ = "0.1.0"
__author__ = "Quant Team"

from .data import DataAdapter, DataLoader
from .factors import FactorCalculator, FactorSelector, Backtester
from .analysis import MarketStageDetector, SimilarityAnalyzer
from .risk import RiskManager
from .valuation import (
    ValuationCalculator,
    FairValueEstimator,
    ValuationMetrics,
    ValuationInput,
    ValuationResult,
    FinancialData,
    PriceData,
)

__all__ = [
    "DataAdapter",
    "DataLoader",
    "FactorCalculator",
    "FactorSelector",
    "Backtester",
    "MarketStageDetector",
    "SimilarityAnalyzer",
    "RiskManager",
    "ValuationCalculator",
    "FairValueEstimator",
    "ValuationMetrics",
    "ValuationInput",
    "ValuationResult",
    "FinancialData",
    "PriceData",
]
