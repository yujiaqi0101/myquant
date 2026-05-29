"""
分析模块
========

包含市场阶段识别、相似度分析等功能。
"""

from .market_stage import MarketStageDetector
from .similarity import SimilarityAnalyzer

__all__ = ["MarketStageDetector", "SimilarityAnalyzer"]
