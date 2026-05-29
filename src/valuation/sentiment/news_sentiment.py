"""
新闻情感分析接口（预留）

提供新闻情感分析的基础数据结构和抽象接口
用于后续集成新闻情感分析功能
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Dict, Any
import random
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SentimentResult:
    """
    情感分析结果数据类

    Attributes:
        stock_code: 股票代码
        date: 分析日期
        sentiment_score: 情感分数 (-1 到 1)
        sentiment_label: 情感标签 (positive/negative/neutral)
        confidence: 置信度 (0 到 1)
        news_count: 分析的新闻数量
        keywords: 关键词列表
    """
    stock_code: str
    date: date
    sentiment_score: float  # -1 到 1
    sentiment_label: str  # positive/negative/neutral
    confidence: float  # 0 到 1
    news_count: int
    keywords: List[str] = field(default_factory=list)

    def __post_init__(self):
        """初始化后的验证和规范化"""
        # 确保情感分数在 -1 到 1 范围内
        self.sentiment_score = max(-1.0, min(1.0, self.sentiment_score))
        # 确保置信度在 0 到 1 范围内
        self.confidence = max(0.0, min(1.0, self.confidence))
        # 标准化情感标签
        if self.sentiment_label not in ("positive", "negative", "neutral"):
            # 根据分数自动判断
            if self.sentiment_score > 0.2:
                self.sentiment_label = "positive"
            elif self.sentiment_score < -0.2:
                self.sentiment_label = "negative"
            else:
                self.sentiment_label = "neutral"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "stock_code": self.stock_code,
            "date": self.date.isoformat(),
            "sentiment_score": self.sentiment_score,
            "sentiment_label": self.sentiment_label,
            "confidence": self.confidence,
            "news_count": self.news_count,
            "keywords": self.keywords
        }

    def __str__(self) -> str:
        """字符串表示"""
        return (
            f"SentimentResult("
            f"stock_code={self.stock_code}, "
            f"date={self.date}, "
            f"score={self.sentiment_score:.2f}, "
            f"label={self.sentiment_label}, "
            f"confidence={self.confidence:.2f}, "
            f"news_count={self.news_count}"
            f")"
        )


class NewsSentimentAnalyzer(ABC):
    """
    新闻情感分析器抽象基类

    所有具体的新闻情感分析实现都需要继承此类
    """

    @abstractmethod
    def analyze(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> SentimentResult:
        """
        分析单只股票的新闻情感

        Args:
            stock_code: 股票代码
            start_date: 开始日期，如未提供则使用最近7天
            end_date: 结束日期，如未提供则使用今天

        Returns:
            SentimentResult: 情感分析结果
        """
        pass

    @abstractmethod
    def batch_analyze(
        self,
        stock_codes: List[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, SentimentResult]:
        """
        批量分析多只股票的新闻情感

        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期，如未提供则使用最近7天
            end_date: 结束日期，如未提供则使用今天

        Returns:
            Dict[stock_code, SentimentResult]: 各股票的情感分析结果
        """
        pass

    def _normalize_dates(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> tuple:
        """
        规范化日期参数

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            tuple: (start_date, end_date)
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            # 默认分析最近7天
            from datetime import timedelta
            start_date = end_date - timedelta(days=7)
        return start_date, end_date


class MockSentimentAnalyzer(NewsSentimentAnalyzer):
    """
    模拟情感分析器（用于开发测试）

    返回随机生成的情感结果，不依赖外部API或数据库
    """

    # 正面关键词
    POSITIVE_KEYWORDS = [
        "增长", "盈利", "突破", "创新", "扩张", "合作",
        "利好", "超预期", "强劲", "复苏", "升级", "优化"
    ]

    # 负面关键词
    NEGATIVE_KEYWORDS = [
        "下滑", "亏损", "风险", "监管", "竞争", "压力",
        "不及预期", "放缓", "收缩", "裁员", "诉讼", "违约"
    ]

    # 中性关键词
    NEUTRAL_KEYWORDS = [
        "持平", "稳定", "维持", "调整", "观察", "等待",
        "符合预期", "正常", "常规", "例行", "披露", "公告"
    ]

    def __init__(self, seed: Optional[int] = None):
        """
        初始化模拟分析器

        Args:
            seed: 随机种子，用于可重复测试
        """
        if seed is not None:
            random.seed(seed)
        logger.info("MockSentimentAnalyzer initialized")

    def analyze(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> SentimentResult:
        """
        模拟分析单只股票的新闻情感

        根据股票代码生成确定性的随机结果（相同代码返回相同结果）

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            SentimentResult: 模拟的情感分析结果
        """
        # 规范化日期
        start_date, end_date = self._normalize_dates(start_date, end_date)

        # 基于股票代码生成确定性的随机数
        code_hash = sum(ord(c) for c in stock_code)
        random.seed(code_hash + end_date.toordinal())

        # 生成随机情感分数 (-1 到 1)
        sentiment_score = random.uniform(-0.8, 0.8)

        # 确定情感标签
        if sentiment_score > 0.2:
            sentiment_label = "positive"
            keywords = random.sample(self.POSITIVE_KEYWORDS, k=random.randint(2, 4))
        elif sentiment_score < -0.2:
            sentiment_label = "negative"
            keywords = random.sample(self.NEGATIVE_KEYWORDS, k=random.randint(2, 4))
        else:
            sentiment_label = "neutral"
            keywords = random.sample(self.NEUTRAL_KEYWORDS, k=random.randint(2, 4))

        # 生成随机置信度
        confidence = random.uniform(0.6, 0.95)

        # 生成随机新闻数量
        news_count = random.randint(5, 50)

        result = SentimentResult(
            stock_code=stock_code,
            date=end_date,
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
            confidence=confidence,
            news_count=news_count,
            keywords=keywords
        )

        logger.info(f"Mock sentiment analysis completed: {result}")
        return result

    def batch_analyze(
        self,
        stock_codes: List[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Dict[str, SentimentResult]:
        """
        批量模拟分析多只股票的新闻情感

        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            Dict[stock_code, SentimentResult]: 各股票的情感分析结果
        """
        results = {}

        logger.info(f"Starting batch sentiment analysis for {len(stock_codes)} stocks")

        for stock_code in stock_codes:
            try:
                result = self.analyze(stock_code, start_date, end_date)
                results[stock_code] = result
            except Exception as e:
                logger.error(f"Sentiment analysis failed for {stock_code}: {str(e)}")
                # 返回一个中性结果作为fallback
                results[stock_code] = SentimentResult(
                    stock_code=stock_code,
                    date=end_date or date.today(),
                    sentiment_score=0.0,
                    sentiment_label="neutral",
                    confidence=0.5,
                    news_count=0,
                    keywords=["分析失败"]
                )

        logger.info(f"Batch sentiment analysis completed")
        return results


# 工厂函数
def create_sentiment_analyzer(analyzer_type: str = "mock", **kwargs) -> NewsSentimentAnalyzer:
    """
    创建情感分析器实例

    Args:
        analyzer_type: 分析器类型 ("mock" 或其他)
        **kwargs: 传递给分析器的参数

    Returns:
        NewsSentimentAnalyzer: 情感分析器实例
    """
    if analyzer_type == "mock":
        return MockSentimentAnalyzer(**kwargs)
    else:
        # 预留：其他类型的分析器
        raise ValueError(f"Unknown analyzer type: {analyzer_type}")
