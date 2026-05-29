"""
估值分析主入口

整合估值计算、合理价值估算、情感分析等功能
提供统一的估值分析接口
"""

from typing import Dict, List, Optional, Any
from datetime import date
import logging
import pandas as pd

from .calculator.valuation_calculator import ValuationCalculator, ValuationResult
from .estimator.fair_value_estimator import FairValueEstimator, FairValueEstimate
from .sentiment.news_sentiment import (
    NewsSentimentAnalyzer,
    MockSentimentAnalyzer,
    SentimentResult,
    create_sentiment_analyzer
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ValuationAnalyzer:
    """
    估值分析主类

    整合估值计算器、合理价值估算器、情感分析器
    提供完整的估值分析功能
    """

    def __init__(
        self,
        db_manager: Any = None,
        sentiment_analyzer: Optional[NewsSentimentAnalyzer] = None
    ):
        """
        初始化估值分析器

        Args:
            db_manager: 数据库管理器实例
            sentiment_analyzer: 情感分析器实例，如未提供则使用MockSentimentAnalyzer
        """
        self.db_manager = db_manager

        # 初始化估值计算器
        self.calculator = ValuationCalculator(db_manager=db_manager)
        logger.info("ValuationCalculator initialized")

        # 初始化合理价值估算器
        self.estimator = FairValueEstimator()
        logger.info("FairValueEstimator initialized")

        # 初始化情感分析器
        if sentiment_analyzer is None:
            self.sentiment_analyzer = MockSentimentAnalyzer()
            logger.info("MockSentimentAnalyzer initialized (default)")
        else:
            self.sentiment_analyzer = sentiment_analyzer
            logger.info("Custom sentiment analyzer initialized")

    def analyze(
        self,
        stock_code: str,
        include_sentiment: bool = False,
        industry: Optional[str] = None,
        report_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行完整估值分析

        Args:
            stock_code: 股票代码
            include_sentiment: 是否包含情感分析
            industry: 行业分类（如未提供则自动获取）
            report_date: 报告日期（如未提供则使用最新）

        Returns:
            Dict: 完整分析结果字典，包含：
                - stock_code: 股票代码
                - analysis_date: 分析日期
                - valuation_results: 各方法估值结果
                - fair_value_estimate: 综合合理价值估算
                - sentiment_result: 情感分析结果（可选）
                - summary: 分析摘要
        """
        logger.info(f"Starting full valuation analysis for {stock_code}")

        result = {
            "stock_code": stock_code,
            "analysis_date": date.today().isoformat(),
            "valuation_results": {},
            "fair_value_estimate": None,
            "sentiment_result": None,
            "summary": {}
        }

        # 1. 调用calculator计算各方法估值
        try:
            valuation_results = self.calculator.calculate(
                stock_code=stock_code,
                industry=industry,
                report_date=report_date
            )
            result["valuation_results"] = valuation_results
            logger.info(f"Valuation calculation completed for {stock_code}")
        except Exception as e:
            logger.error(f"Valuation calculation failed for {stock_code}: {str(e)}")
            result["valuation_results"] = {}

        # 2. 调用estimator估算综合合理价值
        if result["valuation_results"]:
            try:
                fair_value_estimate = self.estimator.estimate(
                    valuation_results=result["valuation_results"]
                )
                # 修正股票代码
                fair_value_estimate.stock_code = stock_code
                result["fair_value_estimate"] = fair_value_estimate
                logger.info(f"Fair value estimation completed for {stock_code}")
            except Exception as e:
                logger.error(f"Fair value estimation failed for {stock_code}: {str(e)}")
                result["fair_value_estimate"] = FairValueEstimate(
                    stock_code=stock_code,
                    recommendation="计算错误",
                    confidence="low"
                )

        # 3. 可选调用sentiment分析情感
        if include_sentiment:
            try:
                sentiment_result = self.sentiment_analyzer.analyze(stock_code)
                result["sentiment_result"] = sentiment_result
                logger.info(f"Sentiment analysis completed for {stock_code}")
            except Exception as e:
                logger.error(f"Sentiment analysis failed for {stock_code}: {str(e)}")
                result["sentiment_result"] = SentimentResult(
                    stock_code=stock_code,
                    date=date.today(),
                    sentiment_score=0.0,
                    sentiment_label="neutral",
                    confidence=0.0,
                    news_count=0,
                    keywords=["分析失败"]
                )

        # 4. 生成分析摘要
        result["summary"] = self._generate_summary(result)

        logger.info(f"Full valuation analysis completed for {stock_code}")
        return result

    def analyze_batch(
        self,
        stock_codes: List[str],
        include_sentiment: bool = False,
        industry_map: Optional[Dict[str, str]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        批量执行完整估值分析

        Args:
            stock_codes: 股票代码列表
            include_sentiment: 是否包含情感分析
            industry_map: 行业映射字典 {stock_code: industry}

        Returns:
            Dict[stock_code, analysis_result]: 各股票的分析结果
        """
        results = {}
        industry_map = industry_map or {}

        logger.info(f"Starting batch analysis for {len(stock_codes)} stocks")

        for stock_code in stock_codes:
            try:
                industry = industry_map.get(stock_code)
                result = self.analyze(
                    stock_code=stock_code,
                    include_sentiment=include_sentiment,
                    industry=industry
                )
                results[stock_code] = result
            except Exception as e:
                logger.error(f"Batch analysis failed for {stock_code}: {str(e)}")
                results[stock_code] = {
                    "stock_code": stock_code,
                    "analysis_date": date.today().isoformat(),
                    "error": str(e),
                    "valuation_results": {},
                    "fair_value_estimate": None,
                    "sentiment_result": None,
                    "summary": {"status": "failed"}
                }

        logger.info(f"Batch analysis completed")
        return results

    def screen_undervalued(
        self,
        stock_codes: List[str],
        upside_threshold: float = 0.20,
        industry_map: Optional[Dict[str, str]] = None
    ) -> pd.DataFrame:
        """
        筛选低估股票

        Args:
            stock_codes: 股票代码列表
            upside_threshold: 上涨空间阈值（默认20%）
            industry_map: 行业映射字典

        Returns:
            pd.DataFrame: 低估股票筛选结果，包含列：
                - stock_code: 股票代码
                - current_price: 当前股价
                - weighted_fair_value: 加权合理价值
                - upside_potential: 上涨空间（%）
                - recommendation: 投资建议
                - confidence: 置信度
        """
        logger.info(f"Screening undervalued stocks from {len(stock_codes)} candidates")

        # 批量分析股票列表
        results = self.analyze_batch(stock_codes, include_sentiment=False, industry_map=industry_map)

        # 筛选上涨空间超过阈值的
        undervalued_list = []

        for stock_code, result in results.items():
            if result.get("fair_value_estimate") is None:
                continue

            estimate = result["fair_value_estimate"]

            # 获取当前股价
            current_price = None
            valuation_results = result.get("valuation_results", {})
            for model_results in valuation_results.values():
                if model_results and len(model_results) > 0:
                    current_price = model_results[0].current_price
                    break

            # 计算上涨空间
            weighted_fair_value = estimate.weighted_fair_value
            upside_potential = None

            if weighted_fair_value is not None and current_price is not None and current_price > 0:
                upside_potential = (weighted_fair_value - current_price) / current_price

            # 筛选条件：上涨空间超过阈值
            if upside_potential is not None and upside_potential >= upside_threshold:
                undervalued_list.append({
                    "stock_code": stock_code,
                    "current_price": current_price,
                    "weighted_fair_value": weighted_fair_value,
                    "upside_potential": round(upside_potential * 100, 2),  # 转换为百分比
                    "recommendation": estimate.recommendation,
                    "confidence": estimate.confidence
                })

        # 按上涨空间降序排序
        undervalued_list.sort(key=lambda x: x["upside_potential"], reverse=True)

        df = pd.DataFrame(undervalued_list)
        logger.info(f"Found {len(df)} undervalued stocks (upside >= {upside_threshold*100}%)")

        return df

    def save_results(
        self,
        stock_code: str,
        results: Dict[str, Any]
    ) -> bool:
        """
        保存估值结果到数据库

        Args:
            stock_code: 股票代码
            results: 分析结果字典

        Returns:
            bool: 保存是否成功
        """
        if self.db_manager is None:
            logger.warning("No database manager provided, cannot save results")
            return False

        try:
            # 1. 保存各方法结果到valuation_result表
            valuation_results = results.get("valuation_results", {})
            for model_name, method_results in valuation_results.items():
                for method_result in method_results:
                    self._save_valuation_result(stock_code, method_result)

            # 2. 保存综合结果到valuation_summary表
            fair_value_estimate = results.get("fair_value_estimate")
            if fair_value_estimate:
                self._save_valuation_summary(stock_code, fair_value_estimate)

            logger.info(f"Results saved to database for {stock_code}")
            return True

        except Exception as e:
            logger.error(f"Failed to save results for {stock_code}: {str(e)}")
            return False

    def _save_valuation_result(
        self,
        stock_code: str,
        result: ValuationResult
    ) -> bool:
        """
        保存单个估值方法结果到数据库

        Args:
            stock_code: 股票代码
            result: 估值结果

        Returns:
            bool: 保存是否成功
        """
        if self.db_manager is None:
            return False

        try:
            sql = """
                INSERT INTO valuation_result (
                    stock_code, method_name, fair_value, fair_value_low,
                    fair_value_high, current_price, deviation_pct,
                    pe_ratio, pb_ratio, ps_ratio, confidence, notes, calc_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            params = (
                stock_code,
                result.method_name,
                result.fair_value,
                result.fair_value_low,
                result.fair_value_high,
                result.current_price,
                result.deviation_pct,
                result.pe_ratio,
                result.pb_ratio,
                result.ps_ratio,
                result.confidence,
                result.notes,
                date.today().isoformat()
            )

            self.db_manager.execute(sql, params)
            return True

        except Exception as e:
            logger.error(f"Failed to save valuation result: {str(e)}")
            return False

    def _save_valuation_summary(
        self,
        stock_code: str,
        estimate: FairValueEstimate
    ) -> bool:
        """
        保存估值综合结果到数据库

        Args:
            stock_code: 股票代码
            estimate: 合理价值估算结果

        Returns:
            bool: 保存是否成功
        """
        if self.db_manager is None:
            return False

        try:
            sql = """
                INSERT INTO valuation_summary (
                    stock_code, weighted_fair_value, fair_value_low,
                    fair_value_high, deviation_pct, recommendation,
                    confidence, method_results, calc_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            import json
            method_results_json = json.dumps(estimate.method_results)

            params = (
                stock_code,
                estimate.weighted_fair_value,
                estimate.fair_value_range[0],
                estimate.fair_value_range[1],
                estimate.deviation_pct,
                estimate.recommendation,
                estimate.confidence,
                method_results_json,
                date.today().isoformat()
            )

            self.db_manager.execute(sql, params)
            return True

        except Exception as e:
            logger.error(f"Failed to save valuation summary: {str(e)}")
            return False

    def _generate_summary(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成分析摘要

        Args:
            result: 分析结果字典

        Returns:
            Dict: 分析摘要
        """
        summary = {
            "status": "success",
            "methods_count": 0,
            "has_fair_value": False,
            "has_sentiment": False
        }

        # 统计估值方法数量
        valuation_results = result.get("valuation_results", {})
        methods_count = 0
        for model_results in valuation_results.values():
            methods_count += len(model_results)
        summary["methods_count"] = methods_count

        # 检查是否有合理价值估算
        fair_value_estimate = result.get("fair_value_estimate")
        if fair_value_estimate and fair_value_estimate.weighted_fair_value is not None:
            summary["has_fair_value"] = True
            summary["weighted_fair_value"] = fair_value_estimate.weighted_fair_value
            summary["fair_value_range"] = fair_value_estimate.fair_value_range
            summary["deviation_pct"] = fair_value_estimate.deviation_pct
            summary["recommendation"] = fair_value_estimate.recommendation
            summary["confidence"] = fair_value_estimate.confidence

        # 检查是否有情感分析
        sentiment_result = result.get("sentiment_result")
        if sentiment_result:
            summary["has_sentiment"] = True
            summary["sentiment_score"] = sentiment_result.sentiment_score
            summary["sentiment_label"] = sentiment_result.sentiment_label
            summary["sentiment_confidence"] = sentiment_result.confidence

        return summary

    def get_valuation_report(
        self,
        stock_code: str,
        results: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        生成估值分析报告文本

        Args:
            stock_code: 股票代码
            results: 分析结果（如未提供则重新分析）

        Returns:
            str: 格式化的分析报告
        """
        if results is None:
            results = self.analyze(stock_code)

        lines = []
        lines.append("=" * 60)
        lines.append(f"股票估值分析报告: {stock_code}")
        lines.append("=" * 60)
        lines.append(f"分析日期: {results.get('analysis_date', date.today().isoformat())}")
        lines.append("")

        # 估值方法结果
        valuation_results = results.get("valuation_results", {})
        if valuation_results:
            lines.append("-" * 40)
            lines.append("估值方法结果:")
            lines.append("-" * 40)
            for model_name, method_results in valuation_results.items():
                lines.append(f"\n模型: {model_name}")
                for result in method_results:
                    lines.append(f"  方法: {result.method_name}")
                    lines.append(f"    合理价值: {result.fair_value}")
                    lines.append(f"    当前股价: {result.current_price}")
                    lines.append(f"    偏离度: {result.deviation_pct}%")
                    lines.append(f"    置信度: {result.confidence}")

        # 综合估算结果
        fair_value_estimate = results.get("fair_value_estimate")
        if fair_value_estimate:
            lines.append("")
            lines.append("-" * 40)
            lines.append("综合合理价值估算:")
            lines.append("-" * 40)
            lines.append(f"加权合理价值: {fair_value_estimate.weighted_fair_value}")
            lines.append(f"合理价值区间: {fair_value_estimate.fair_value_range}")
            lines.append(f"偏离度: {fair_value_estimate.deviation_pct}%")
            lines.append(f"投资建议: {fair_value_estimate.recommendation}")
            lines.append(f"置信度: {fair_value_estimate.confidence}")

        # 情感分析结果
        sentiment_result = results.get("sentiment_result")
        if sentiment_result:
            lines.append("")
            lines.append("-" * 40)
            lines.append("新闻情感分析:")
            lines.append("-" * 40)
            lines.append(f"情感分数: {sentiment_result.sentiment_score:.2f}")
            lines.append(f"情感标签: {sentiment_result.sentiment_label}")
            lines.append(f"置信度: {sentiment_result.confidence:.2f}")
            lines.append(f"新闻数量: {sentiment_result.news_count}")
            lines.append(f"关键词: {', '.join(sentiment_result.keywords)}")

        # 摘要
        summary = results.get("summary", {})
        lines.append("")
        lines.append("-" * 40)
        lines.append("分析摘要:")
        lines.append("-" * 40)
        lines.append(f"估值方法数: {summary.get('methods_count', 0)}")
        lines.append(f"投资建议: {summary.get('recommendation', 'N/A')}")
        lines.append(f"置信度: {summary.get('confidence', 'N/A')}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


# 便捷函数
def analyze_stock(
    stock_code: str,
    db_manager: Any = None,
    include_sentiment: bool = False
) -> Dict[str, Any]:
    """
    便捷函数：分析单只股票

    Args:
        stock_code: 股票代码
        db_manager: 数据库管理器
        include_sentiment: 是否包含情感分析

    Returns:
        Dict: 分析结果
    """
    analyzer = ValuationAnalyzer(db_manager=db_manager)
    return analyzer.analyze(stock_code, include_sentiment=include_sentiment)


def screen_stocks(
    stock_codes: List[str],
    upside_threshold: float = 0.20,
    db_manager: Any = None
) -> pd.DataFrame:
    """
    便捷函数：筛选低估股票

    Args:
        stock_codes: 股票代码列表
        upside_threshold: 上涨空间阈值
        db_manager: 数据库管理器

    Returns:
        pd.DataFrame: 筛选结果
    """
    analyzer = ValuationAnalyzer(db_manager=db_manager)
    return analyzer.screen_undervalued(stock_codes, upside_threshold)
