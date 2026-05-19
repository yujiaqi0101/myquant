"""
估值模块
提供股票估值计算功能
"""

from .analyzer import ValuationAnalyzer
from .calculator.metrics import ValuationMetrics
from .calculator.valuation_calculator import (
    ValuationCalculator,
    FinancialData,
    PriceData,
    ValuationInput,
    ValuationResult,
    BaseValuationModel,
    GeneralValuationModel,
    BankValuationModel,
    TechValuationModel,
    REITsValuationModel,
)
from .estimator.fair_value_estimator import (
    FairValueEstimator,
    FairValueEstimate,
    Recommendation,
)
from .sentiment.news_sentiment import (
    NewsSentimentAnalyzer,
    MockSentimentAnalyzer,
    SentimentResult,
)

__all__ = [
    # 主入口
    "ValuationAnalyzer",
    # 指标计算
    "ValuationMetrics",
    # 估值计算器
    "ValuationCalculator",
    "FinancialData",
    "PriceData",
    "ValuationInput",
    "ValuationResult",
    # 估值模型
    "BaseValuationModel",
    "GeneralValuationModel",
    "BankValuationModel",
    "TechValuationModel",
    "REITsValuationModel",
    # 合理价值估算
    "FairValueEstimator",
    "FairValueEstimate",
    "Recommendation",
    # 情感分析
    "NewsSentimentAnalyzer",
    "MockSentimentAnalyzer",
    "SentimentResult",
]
