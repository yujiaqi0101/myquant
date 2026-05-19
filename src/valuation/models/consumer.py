"""
消费行业估值模型

适用行业：食品饮料、家用电器、医药生物、商贸零售、农林牧渔
主要方法：PE、PEG（PEG = PE / 盈利增长率）
辅助方法：PS
合理区间：PE 15-35倍，PEG < 1.5为低估
"""

from datetime import date
from typing import Dict, List, Optional, Tuple, Any
import math

from .base import (
    ValuationMethod,
    ValuationInput,
    ValuationResult,
    ValuationModel,
)


class ConsumerValuationModel(ValuationModel):
    """
    消费行业估值模型
    
    适用于食品饮料、家用电器、医药生物、商贸零售、农林牧渔等消费行业。
    消费行业具有品牌溢价、现金流稳定、成长性好等特点，
    适合使用PE、PEG等基于盈利的估值方法。
    
    Attributes:
        pe_low: PE下限（默认15倍）
        pe_high: PE上限（默认35倍）
        peg_threshold: PEG低估阈值（默认1.5）
        ps_low: PS下限（默认1.0倍）
        ps_high: PS上限（默认5.0倍）
        growth_rate: 预期盈利增长率
    """
    
    # 适用行业列表
    APPLICABLE_INDUSTRIES = [
        "食品饮料", "家用电器", "医药生物", "商贸零售", "农林牧渔",
        "白酒", "啤酒", "乳制品", "调味品", "休闲食品",
        "白色家电", "黑色家电", "小家电", "医疗器械", "生物制药",
        "中药", "化学制药", "医药商业", "医疗服务", "超市",
        "百货", "专业连锁", "电商", "农产品", "畜禽养殖",
        "饲料", "种子"
    ]
    
    def __init__(
        self,
        pe_low: float = 15.0,
        pe_high: float = 35.0,
        peg_threshold: float = 1.5,
        ps_low: float = 1.0,
        ps_high: float = 5.0,
        growth_rate: Optional[float] = None,
    ):
        """
        初始化消费行业估值模型
        
        Args:
            pe_low: PE下限（默认15倍）
            pe_high: PE上限（默认35倍）
            peg_threshold: PEG低估阈值（默认1.5）
            ps_low: PS下限（默认1.0倍）
            ps_high: PS上限（默认5.0倍）
            growth_rate: 预期盈利增长率（可选）
        """
        super().__init__(ValuationMethod.PE)
        self.pe_low = pe_low
        self.pe_high = pe_high
        self.peg_threshold = peg_threshold
        self.ps_low = ps_low
        self.ps_high = ps_high
        self.growth_rate = growth_rate
    
    def validate_input(self, input_data: ValuationInput) -> bool:
        """
        验证输入数据是否满足估值计算要求
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            bool: 验证是否通过
        """
        self._clear_validation_errors()
        
        valid = True
        valid &= self._check_positive(input_data.price, "当前股价")
        valid &= self._check_positive(input_data.total_shares, "总股本")
        valid &= self._check_positive(input_data.market_cap, "总市值")
        
        # PE估值需要净利润
        if input_data.net_profit is None:
            self._add_validation_error("净利润不能为空（PE估值需要）")
            valid = False
        
        return valid
    
    def _get_growth_rate(self, input_data: ValuationInput) -> float:
        """
        获取盈利增长率
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            float: 增长率（小数形式）
        """
        # 优先使用传入的增长率
        if self.growth_rate is not None:
            return self.growth_rate
        
        # 从extra_data获取
        growth = input_data.extra_data.get("profit_growth_rate")
        if growth is not None:
            return growth
        
        # 使用默认增长率（消费行业通常10-20%）
        return 0.15
    
    def _adjust_pe_by_growth(self, growth_rate: float) -> Tuple[float, float]:
        """
        根据增长率调整PE区间
        
        Args:
            growth_rate: 增长率（小数形式）
            
        Returns:
            Tuple[float, float]: 调整后的PE区间
        """
        # 增长率转百分比
        g_pct = growth_rate * 100
        
        # 基于增长率调整PE区间
        # 高增长（>25%）：PE 20-45倍
        # 中等增长（15-25%）：PE 15-35倍
        # 低增长（<15%）：PE 10-25倍
        if g_pct >= 25:
            pe_low = 20.0
            pe_high = 45.0
        elif g_pct >= 15:
            pe_low = 15.0
            pe_high = 35.0
        else:
            pe_low = 10.0
            pe_high = 25.0
        
        return pe_low, pe_high
    
    def _calculate_peg(
        self,
        pe: float,
        growth_rate: float
    ) -> Optional[float]:
        """
        计算PEG比率
        
        公式：PEG = PE / (盈利增长率 * 100)
        
        Args:
            pe: 市盈率
            growth_rate: 增长率（小数形式）
            
        Returns:
            Optional[float]: PEG值
        """
        if growth_rate <= 0:
            return None
        return pe / (growth_rate * 100)
    
    def get_fair_value_range(
        self,
        input_data: ValuationInput,
        **kwargs
    ) -> Tuple[float, float, float]:
        """
        获取公允价值区间（PE区间）
        
        Args:
            input_data: 估值输入数据
            **kwargs: 额外参数
                - growth_override: 覆盖增长率
                - industry_premium: 行业溢价系数
                
        Returns:
            Tuple[float, float, float]: (PE下限, PE中值, PE上限)
        """
        growth_rate = kwargs.get("growth_override", self._get_growth_rate(input_data))
        industry_premium = kwargs.get("industry_premium", 1.0)
        
        # 根据增长率调整PE区间
        pe_low, pe_high = self._adjust_pe_by_growth(growth_rate)
        
        # 应用行业溢价
        pe_low *= industry_premium
        pe_high *= industry_premium
        
        # 中值
        pe_mid = (pe_low + pe_high) / 2
        
        # 根据PEG调整（如果PEG < 1，给予PE溢价）
        current_pe = input_data.get_current_pe()
        if current_pe is not None:
            peg = self._calculate_peg(current_pe, growth_rate)
            if peg is not None and peg < 1.0:
                # PEG低估，给予PE溢价
                pe_mid *= 1.1
                pe_high *= 1.1
        
        return pe_low, pe_mid, pe_high
    
    def calculate(
        self,
        input_data: ValuationInput,
        **kwargs
    ) -> List[ValuationResult]:
        """
        执行估值计算
        
        Args:
            input_data: 估值输入数据
            **kwargs: 额外参数
                
        Returns:
            List[ValuationResult]: 估值结果列表
        """
        results = []
        
        # 验证输入
        if not self.validate_input(input_data):
            return results
        
        # 获取每股收益
        eps = input_data.get_eps()
        if eps is None or eps <= 0:
            self._add_validation_error("每股收益计算失败或为零")
            return results
        
        # 当前PE
        current_pe = input_data.get_current_pe()
        if current_pe is None:
            current_pe = input_data.price / eps
        
        # 获取增长率
        growth_rate = self._get_growth_rate(input_data)
        
        # ===== 1. PE估值 =====
        pe_low, pe_mid, pe_high = self.get_fair_value_range(input_data, **kwargs)
        
        # 计算隐含股价
        implied_price_low = eps * pe_low
        implied_price_mid = eps * pe_mid
        implied_price_high = eps * pe_high
        
        # 计算风险收益
        upside, downside = self._calculate_upside_downside(
            input_data.price,
            implied_price_low,
            implied_price_mid,
            implied_price_high
        )
        
        # 计算置信度
        confidence = self._calculate_confidence(input_data, growth_rate)
        
        # 警告信息
        warnings = []
        if current_pe > 50:
            warnings.append("当前PE过高（>50倍），注意估值泡沫风险")
        elif current_pe > self.pe_high:
            warnings.append(f"当前PE高于合理区间上限（{self.pe_high}倍）")
        if growth_rate < 0.05:
            warnings.append("增长率过低（<5%），PEG估值可能不适用")
        
        pe_result = ValuationResult(
            method=ValuationMethod.PE,
            stock_code=input_data.stock_code,
            current_value=current_pe,
            fair_value_low=pe_low,
            fair_value_mid=pe_mid,
            fair_value_high=pe_high,
            implied_price_low=implied_price_low,
            implied_price_mid=implied_price_mid,
            implied_price_high=implied_price_high,
            upside_potential=upside,
            downside_risk=downside,
            confidence=confidence,
            assumptions={
                "eps": eps,
                "growth_rate": growth_rate,
                "pe_range": f"{pe_low:.1f}-{pe_high:.1f}",
                "methodology": "PE估值法",
            },
            warnings=warnings,
            calculation_date=date.today(),
        )
        results.append(pe_result)
        
        # ===== 2. PEG估值 =====
        peg = self._calculate_peg(current_pe, growth_rate)
        if peg is not None:
            # PEG合理区间：0.8-1.5
            peg_low, peg_high = 0.8, 1.5
            peg_mid = 1.0
            
            # 计算PEG隐含PE
            peg_implied_pe_low = peg_low * growth_rate * 100
            peg_implied_pe_mid = peg_mid * growth_rate * 100
            peg_implied_pe_high = peg_high * growth_rate * 100
            
            # 计算隐含股价
            peg_implied_price_low = eps * peg_implied_pe_low
            peg_implied_price_mid = eps * peg_implied_pe_mid
            peg_implied_price_high = eps * peg_implied_pe_high
            
            # 计算风险收益
            peg_upside, peg_downside = self._calculate_upside_downside(
                input_data.price,
                peg_implied_price_low,
                peg_implied_price_mid,
                peg_implied_price_high
            )
            
            peg_warnings = []
            if peg > self.peg_threshold:
                peg_warnings.append(f"PEG > {self.peg_threshold}，可能被高估")
            elif peg < 0.8:
                peg_warnings.append("PEG < 0.8，可能被低估")
            
            peg_result = ValuationResult(
                method=ValuationMethod.PEG,
                stock_code=input_data.stock_code,
                current_value=peg,
                fair_value_low=peg_low,
                fair_value_mid=peg_mid,
                fair_value_high=peg_high,
                implied_price_low=peg_implied_price_low,
                implied_price_mid=peg_implied_price_mid,
                implied_price_high=peg_implied_price_high,
                upside_potential=peg_upside,
                downside_risk=peg_downside,
                confidence=confidence * 0.9,
                assumptions={
                    "eps": eps,
                    "growth_rate": growth_rate,
                    "implied_pe_low": peg_implied_pe_low,
                    "implied_pe_mid": peg_implied_pe_mid,
                    "implied_pe_high": peg_implied_pe_high,
                    "methodology": "PEG估值法",
                },
                warnings=peg_warnings,
                calculation_date=date.today(),
            )
            results.append(peg_result)
        
        # ===== 3. PS估值（辅助方法）=====
        if input_data.revenue is not None and input_data.revenue > 0:
            rps = input_data.get_revenue_per_share()
            if rps is not None and rps > 0:
                current_ps = input_data.get_current_ps()
                if current_ps is None:
                    current_ps = input_data.price / rps
                
                # 根据增长率调整PS区间
                if growth_rate >= 0.20:
                    ps_low, ps_high = 2.0, 8.0
                elif growth_rate >= 0.10:
                    ps_low, ps_high = 1.0, 5.0
                else:
                    ps_low, ps_high = 0.5, 3.0
                
                ps_mid = (ps_low + ps_high) / 2
                
                # 计算隐含股价
                ps_implied_price_low = rps * ps_low
                ps_implied_price_mid = rps * ps_mid
                ps_implied_price_high = rps * ps_high
                
                # 计算风险收益
                ps_upside, ps_downside = self._calculate_upside_downside(
                    input_data.price,
                    ps_implied_price_low,
                    ps_implied_price_mid,
                    ps_implied_price_high
                )
                
                ps_warnings = []
                if current_ps > 10:
                    ps_warnings.append("当前PS过高（>10倍），注意估值风险")
                
                ps_result = ValuationResult(
                    method=ValuationMethod.PS,
                    stock_code=input_data.stock_code,
                    current_value=current_ps,
                    fair_value_low=ps_low,
                    fair_value_mid=ps_mid,
                    fair_value_high=ps_high,
                    implied_price_low=ps_implied_price_low,
                    implied_price_mid=ps_implied_price_mid,
                    implied_price_high=ps_implied_price_high,
                    upside_potential=ps_upside,
                    downside_risk=ps_downside,
                    confidence=confidence * 0.7,  # PS置信度较低
                    assumptions={
                        "rps": rps,
                        "growth_rate": growth_rate,
                        "methodology": "PS估值法（辅助）",
                    },
                    warnings=ps_warnings,
                    calculation_date=date.today(),
                )
                results.append(ps_result)
        
        return results
    
    def _calculate_confidence(
        self,
        input_data: ValuationInput,
        growth_rate: float
    ) -> float:
        """
        计算估值置信度
        
        Args:
            input_data: 估值输入数据
            growth_rate: 增长率
            
        Returns:
            float: 置信度(0-1)
        """
        confidence = 0.75  # 消费行业基础置信度较高
        
        # 数据完整性
        if input_data.revenue is not None:
            confidence += 0.05
        if input_data.operating_profit is not None:
            confidence += 0.05
        
        # 增长率合理性
        if 0.08 <= growth_rate <= 0.30:
            confidence += 0.1
        elif growth_rate < 0 or growth_rate > 0.50:
            confidence -= 0.1
        
        # 盈利质量
        if input_data.net_profit is not None and input_data.operating_profit is not None:
            if input_data.net_profit > 0 and input_data.operating_profit > 0:
                # 净利润与营业利润比例合理
                ratio = input_data.net_profit / input_data.operating_profit
                if 0.5 <= ratio <= 1.2:
                    confidence += 0.05
        
        return max(0.0, min(1.0, confidence))


# 便捷函数
def value_consumer_stock(
    stock_code: str,
    price: float,
    total_shares: float,
    market_cap: float,
    net_profit: float,
    revenue: Optional[float] = None,
    growth_rate: Optional[float] = None,
    **kwargs
) -> List[ValuationResult]:
    """
    便捷函数：对消费行业股票进行估值
    
    Args:
        stock_code: 股票代码
        price: 当前股价
        total_shares: 总股本
        market_cap: 总市值
        net_profit: 净利润
        revenue: 营业收入（可选，用于PS估值）
        growth_rate: 预期增长率（可选）
        **kwargs: 其他参数
        
    Returns:
        List[ValuationResult]: 估值结果列表
    """
    input_data = ValuationInput(
        stock_code=stock_code,
        report_date=date.today(),
        total_shares=total_shares,
        price=price,
        market_cap=market_cap,
        net_profit=net_profit,
        revenue=revenue,
        extra_data={"profit_growth_rate": growth_rate} if growth_rate else {},
    )
    
    model = ConsumerValuationModel(**kwargs)
    return model.calculate(input_data)
