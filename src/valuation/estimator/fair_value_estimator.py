"""
合理市值区间估算器
整合多种估值方法，计算加权合理价值和估值区间
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Recommendation(Enum):
    """投资建议枚举"""
    STRONG_OVERWEIGHT = "强烈超配"
    OVERWEIGHT = "超配"
    NEUTRAL = "标配"
    UNDERWEIGHT = "低配"
    STRONG_UNDERWEIGHT = "强烈低配"


@dataclass
class FairValueEstimate:
    """
    合理市值区间估算结果数据类
    """
    stock_code: str  # 股票代码
    method_results: Dict[str, Any] = field(default_factory=dict)  # 各方法估值结果
    weighted_fair_value: Optional[float] = None  # 加权合理价值
    fair_value_range: tuple = field(default_factory=lambda: (None, None))  # 合理价值区间 (low, high)
    current_market_cap: Optional[float] = None  # 当前市值
    deviation_pct: Optional[float] = None  # 偏离百分比
    recommendation: str = ""  # 投资建议
    confidence: str = "medium"  # 置信度：high/medium/low

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "stock_code": self.stock_code,
            "method_results": self.method_results,
            "weighted_fair_value": self.weighted_fair_value,
            "fair_value_range": self.fair_value_range,
            "current_market_cap": self.current_market_cap,
            "deviation_pct": self.deviation_pct,
            "recommendation": self.recommendation,
            "confidence": self.confidence
        }

    def __str__(self) -> str:
        """字符串表示"""
        return (
            f"FairValueEstimate("
            f"stock_code={self.stock_code}, "
            f"weighted_fair_value={self.weighted_fair_value}, "
            f"range={self.fair_value_range}, "
            f"deviation={self.deviation_pct}%, "
            f"recommendation={self.recommendation}, "
            f"confidence={self.confidence}"
            f")"
        )


class FairValueEstimator:
    """
    合理市值区间估算器
    整合多种估值方法，计算加权合理价值和估值区间
    """

    # 默认权重配置
    DEFAULT_WEIGHTS = {
        "PE估值法": 0.25,
        "PB估值法": 0.25,
        "PS估值法": 0.15,
        "DCF估值法": 0.25,
        "PEG估值法": 0.10,
        "NAV估值法": 0.25,
        "PB估值法（银行业）": 0.40,
        "PE估值法（辅助）": 0.10,
    }

    # 置信度阈值
    CONFIDENCE_HIGH_THRESHOLD = 0.7
    CONFIDENCE_LOW_THRESHOLD = 0.3

    def __init__(self, default_weights: Optional[Dict[str, float]] = None):
        """
        初始化估算器

        Args:
            default_weights: 默认权重配置，如不传入则使用类默认权重
        """
        self.weights = default_weights or self.DEFAULT_WEIGHTS.copy()
        logger.info("FairValueEstimator initialized")

    def estimate(
        self,
        valuation_results: Dict[str, List[Any]],
        custom_weights: Optional[Dict[str, float]] = None
    ) -> FairValueEstimate:
        """
        整合多种估值方法，计算加权合理价值

        Args:
            valuation_results: 估值结果字典 {模型名: [ValuationResult, ...]}
            custom_weights: 自定义权重，如不传入则使用默认权重

        Returns:
            FairValueEstimate对象
        """
        # 使用自定义权重或默认权重
        weights = custom_weights if custom_weights is not None else self.weights

        # 提取所有估值结果
        all_results = []
        for model_name, results in valuation_results.items():
            all_results.extend(results)

        if not all_results:
            logger.warning("没有可用的估值结果")
            return FairValueEstimate(
                stock_code="",
                recommendation="无法评估",
                confidence="low"
            )

        # 提取各方法的合理价值
        method_values = {}
        for result in all_results:
            method_name = result.method_name
            if result.fair_value is not None:
                method_values[method_name] = result.fair_value

        if not method_values:
            logger.warning("没有有效的估值数据")
            return FairValueEstimate(
                stock_code="",
                recommendation="无法评估",
                confidence="low"
            )

        # 计算加权合理价值
        weighted_fair_value = self._calculate_weighted_value(method_values, weights)

        # 计算估值区间（25%-75%分位数）
        fair_value_range = self._calculate_value_range(method_values)

        # 获取当前市值/股价
        current_price = all_results[0].current_price if all_results else None
        current_market_cap = None

        # 计算偏离度
        deviation_pct = None
        if weighted_fair_value is not None and current_price is not None and current_price > 0:
            deviation_pct = (current_price - weighted_fair_value) / weighted_fair_value * 100

        # 生成投资建议
        recommendation = self._get_recommendation(deviation_pct)

        # 计算置信度
        confidence = self._calculate_confidence(all_results, weights)

        # 构建结果
        estimate = FairValueEstimate(
            stock_code="",
            method_results=method_values,
            weighted_fair_value=round(weighted_fair_value, 2) if weighted_fair_value else None,
            fair_value_range=(
                round(fair_value_range[0], 2) if fair_value_range[0] else None,
                round(fair_value_range[1], 2) if fair_value_range[1] else None
            ),
            current_market_cap=current_market_cap,
            deviation_pct=round(deviation_pct, 2) if deviation_pct else None,
            recommendation=recommendation,
            confidence=confidence
        )

        logger.info(f"合理价值估算完成: {estimate}")
        return estimate

    def estimate_batch(
        self,
        batch_valuation_results: Dict[str, Dict[str, List[Any]]],
        custom_weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, FairValueEstimate]:
        """
        批量估算合理价值

        Args:
            batch_valuation_results: 批量估值结果 {stock_code: {模型名: [ValuationResult, ...]}}
            custom_weights: 自定义权重

        Returns:
            Dict[stock_code, FairValueEstimate]
        """
        results = {}

        logger.info(f"开始批量合理价值估算，共{len(batch_valuation_results)}只股票")

        for stock_code, valuation_results in batch_valuation_results.items():
            try:
                estimate = self.estimate(valuation_results, custom_weights)
                # 修正股票代码
                estimate.stock_code = stock_code
                results[stock_code] = estimate
            except Exception as e:
                logger.error(f"合理价值估算失败 {stock_code}: {str(e)}")
                results[stock_code] = FairValueEstimate(
                    stock_code=stock_code,
                    recommendation="计算错误",
                    confidence="low"
                )

        logger.info(f"批量合理价值估算完成")
        return results

    def _calculate_weighted_value(
        self,
        method_values: Dict[str, float],
        weights: Dict[str, float]
    ) -> Optional[float]:
        """
        计算加权合理价值

        Args:
            method_values: 各方法估值结果 {方法名: 估值}
            weights: 权重配置 {方法名: 权重}

        Returns:
            加权合理价值
        """
        total_weight = 0.0
        weighted_sum = 0.0

        for method_name, value in method_values.items():
            # 获取权重，如果未配置则使用默认权重0.1
            weight = weights.get(method_name, 0.1)

            if value is not None and weight > 0:
                weighted_sum += value * weight
                total_weight += weight

        if total_weight == 0:
            logger.warning("总权重为0，无法计算加权价值")
            return None

        return weighted_sum / total_weight

    def _calculate_value_range(
        self,
        method_values: Dict[str, float]
    ) -> tuple:
        """
        计算估值区间（25%-75%分位数）

        Args:
            method_values: 各方法估值结果

        Returns:
            (区间下限, 区间上限)
        """
        values = [v for v in method_values.values() if v is not None]

        if len(values) < 2:
            # 如果只有1个值，使用±20%作为区间
            if values:
                val = values[0]
                return (val * 0.8, val * 1.2)
            return (None, None)

        # 排序并计算分位数
        sorted_values = sorted(values)
        n = len(sorted_values)

        # 25%分位数
        q25_idx = (n - 1) * 0.25
        q25_low = int(q25_idx)
        q25_high = min(q25_low + 1, n - 1)
        q25_frac = q25_idx - q25_low
        q25 = sorted_values[q25_low] * (1 - q25_frac) + sorted_values[q25_high] * q25_frac

        # 75%分位数
        q75_idx = (n - 1) * 0.75
        q75_low = int(q75_idx)
        q75_high = min(q75_low + 1, n - 1)
        q75_frac = q75_idx - q75_low
        q75 = sorted_values[q75_low] * (1 - q75_frac) + sorted_values[q75_high] * q75_frac

        return (q25, q75)

    def _get_recommendation(self, deviation: Optional[float]) -> str:
        """
        根据偏离度生成投资建议

        偏离度计算: (当前价格 - 合理价值) / 合理价值 * 100

        建议规则:
        - <-30%: 强烈超配 (当前价格远低于合理价值)
        - -30%~-15%: 超配
        - -15%~+15%: 标配
        - +15%~+30%: 低配
        - >+30%: 强烈低配 (当前价格远高于合理价值)

        Args:
            deviation: 偏离百分比

        Returns:
            投资建议字符串
        """
        if deviation is None:
            return "无法评估"

        if deviation <= -30:
            return Recommendation.STRONG_OVERWEIGHT.value
        elif deviation <= -15:
            return Recommendation.OVERWEIGHT.value
        elif deviation < 15:
            return Recommendation.NEUTRAL.value
        elif deviation <= 30:
            return Recommendation.UNDERWEIGHT.value
        else:
            return Recommendation.STRONG_UNDERWEIGHT.value

    def _calculate_confidence(
        self,
        results: List[Any],
        weights: Dict[str, float]
    ) -> str:
        """
        计算置信度

        基于以下因素:
        1. 有效估值方法的数量
        2. 各方法结果的一致性
        3. 权重覆盖度

        Args:
            results: 估值结果列表
            weights: 权重配置

        Returns:
            置信度: high/medium/low
        """
        if not results:
            return "low"

        # 统计有效结果数量
        valid_results = [r for r in results if r.fair_value is not None]
        if len(valid_results) < 2:
            return "low"

        # 计算权重覆盖度
        total_available_weight = 0.0
        for result in valid_results:
            method_weight = weights.get(result.method_name, 0.1)
            total_available_weight += method_weight

        # 计算结果一致性（变异系数）
        values = [r.fair_value for r in valid_results]
        if len(values) >= 2:
            mean_val = sum(values) / len(values)
            if mean_val > 0:
                variance = sum((v - mean_val) ** 2 for v in values) / len(values)
                std_dev = variance ** 0.5
                cv = std_dev / mean_val  # 变异系数

                # 综合评分
                score = 0.0

                # 有效方法数量评分 (0-0.3)
                score += min(len(valid_results) / 5, 1.0) * 0.3

                # 权重覆盖度评分 (0-0.3)
                score += min(total_available_weight, 1.0) * 0.3

                # 一致性评分 (0-0.4)
                # CV越小越好，CV<0.2得满分，CV>0.5得0分
                consistency_score = max(0, 1 - (cv - 0.2) / 0.3) if cv > 0.2 else 1.0
                score += consistency_score * 0.4

                # 根据评分确定置信度
                if score >= self.CONFIDENCE_HIGH_THRESHOLD:
                    return "high"
                elif score >= self.CONFIDENCE_LOW_THRESHOLD:
                    return "medium"

        return "low"

    def update_weights(self, new_weights: Dict[str, float]):
        """
        更新默认权重配置

        Args:
            new_weights: 新的权重配置
        """
        self.weights.update(new_weights)
        logger.info(f"权重配置已更新: {self.weights}")

    def get_weights(self) -> Dict[str, float]:
        """
        获取当前权重配置

        Returns:
            权重配置字典
        """
        return self.weights.copy()

    def reset_weights(self):
        """重置为默认权重"""
        self.weights = self.DEFAULT_WEIGHTS.copy()
        logger.info("权重配置已重置为默认值")
