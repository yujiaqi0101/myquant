"""
房地产估值模型

适用行业：房地产、建筑装饰
主要方法：NAV（净资产价值）
公式：NAV = 已开发项目现值 + 土地储备现值 - 净负债
特点：关注土储质量、融资成本
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


class RealEstateValuationModel(ValuationModel):
    """
    房地产估值模型
    
    适用于房地产、建筑装饰等房地产行业。
    房地产行业具有项目制、重资产、高杠杆等特点，
    NAV（净资产价值）法是最主要的估值方法。
    
    Attributes:
        discount_rate: 折现率（默认10%）
        nav_discount_low: NAV折价下限（默认0.7）
        nav_discount_high: NAV折价上限（默认0.9）
        land_reserve_premium: 土地储备溢价系数
    """
    
    # 适用行业列表
    APPLICABLE_INDUSTRIES = [
        "房地产", "建筑装饰",
        "住宅开发", "商业地产", "物业管理", "房地产服务",
        "房屋建设", "装修装饰", "基础建设", "专业工程",
        "园区开发", "仓储物流", "产业地产"
    ]
    
    def __init__(
        self,
        discount_rate: float = 0.10,
        nav_discount_low: float = 0.70,
        nav_discount_high: float = 0.90,
        land_reserve_premium: float = 1.0,
    ):
        """
        初始化房地产估值模型
        
        Args:
            discount_rate: 折现率（默认10%）
            nav_discount_low: NAV折价下限（默认0.7）
            nav_discount_high: NAV折价上限（默认0.9）
            land_reserve_premium: 土地储备溢价系数（默认1.0）
        """
        super().__init__(ValuationMethod.NAV)
        self.discount_rate = discount_rate
        self.nav_discount_low = nav_discount_low
        self.nav_discount_high = nav_discount_high
        self.land_reserve_premium = land_reserve_premium
    
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
        
        # NAV需要股东权益作为基础
        valid &= self._check_not_none(input_data.shareholders_equity, "股东权益")
        
        # 检查NAV相关数据
        nav_data = input_data.extra_data.get("nav_components", {})
        if not nav_data:
            # 如果没有提供NAV组件，至少要有股东权益和净负债
            if input_data.net_debt is None:
                self._add_validation_error("净负债不能为空（NAV计算需要）")
                valid = False
        
        return valid
    
    def _calculate_nav(self, input_data: ValuationInput) -> Optional[float]:
        """
        计算净资产价值（NAV）
        
        公式：NAV = 已开发项目现值 + 土地储备现值 - 净负债
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            Optional[float]: NAV值
        """
        nav_data = input_data.extra_data.get("nav_components", {})
        
        if nav_data:
            # 使用提供的NAV组件计算
            developed_projects_pv = nav_data.get("developed_projects_pv", 0)
            land_reserve_pv = nav_data.get("land_reserve_pv", 0)
            net_debt = nav_data.get("net_debt", input_data.net_debt or 0)
            
            # 应用土地储备溢价
            land_reserve_pv *= self.land_reserve_premium
            
            nav = developed_projects_pv + land_reserve_pv - net_debt
        else:
            # 简化计算：使用股东权益作为NAV近似
            if input_data.shareholders_equity is not None:
                nav = input_data.shareholders_equity
                if input_data.net_debt is not None:
                    # 调整净负债影响
                    nav -= input_data.net_debt * 0.5  # 简化调整
            else:
                return None
        
        return nav
    
    def _calculate_nav_components(
        self,
        input_data: ValuationInput
    ) -> Dict[str, float]:
        """
        计算NAV各组成部分
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            Dict[str, float]: NAV各组成部分
        """
        nav_data = input_data.extra_data.get("nav_components", {})
        
        components = {
            "developed_projects_pv": nav_data.get("developed_projects_pv", 0),
            "land_reserve_pv": nav_data.get("land_reserve_pv", 0),
            "investment_property_pv": nav_data.get("investment_property_pv", 0),
            "other_assets": nav_data.get("other_assets", 0),
            "net_debt": nav_data.get("net_debt", input_data.net_debt or 0),
        }
        
        return components
    
    def _assess_land_quality(self, input_data: ValuationInput) -> str:
        """
        评估土地储备质量
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            str: 土地质量评级（"high"/"medium"/"low"）
        """
        land_data = input_data.extra_data.get("land_reserve", {})
        
        if not land_data:
            return "unknown"
        
        # 评估指标
        tier1_city_ratio = land_data.get("tier1_city_ratio", 0)
        avg_land_cost = land_data.get("avg_land_cost", 0)
        avg_selling_price = land_data.get("avg_selling_price", 0)
        
        # 一二线城市占比高、土地成本低的质量较好
        score = 0
        if tier1_city_ratio > 0.5:
            score += 2
        elif tier1_city_ratio > 0.3:
            score += 1
        
        if avg_selling_price > 0 and avg_land_cost / avg_selling_price < 0.4:
            score += 2
        elif avg_selling_price > 0 and avg_land_cost / avg_selling_price < 0.5:
            score += 1
        
        if score >= 3:
            return "high"
        elif score >= 1:
            return "medium"
        else:
            return "low"
    
    def get_fair_value_range(
        self,
        input_data: ValuationInput,
        **kwargs
    ) -> Tuple[float, float, float]:
        """
        获取公允价值区间（NAV折价区间）
        
        Args:
            input_data: 估值输入数据
            **kwargs: 额外参数
                - land_quality: 土地质量覆盖
                - policy_environment: 政策环境系数
                
        Returns:
            Tuple[float, float, float]: (NAV折价下限, NAV折价中值, NAV折价上限)
        """
        land_quality = kwargs.get("land_quality", self._assess_land_quality(input_data))
        policy_environment = kwargs.get("policy_environment", "neutral")
        
        # 基础折价区间
        discount_low = self.nav_discount_low
        discount_high = self.nav_discount_high
        
        # 根据土地质量调整
        if land_quality == "high":
            discount_low += 0.05
            discount_high += 0.05
        elif land_quality == "low":
            discount_low -= 0.1
            discount_high -= 0.1
        
        # 根据政策环境调整
        if policy_environment == "favorable":
            discount_low += 0.05
            discount_high += 0.05
        elif policy_environment == "restrictive":
            discount_low -= 0.1
            discount_high -= 0.1
        
        # 确保区间合理性
        discount_low = max(0.4, min(1.0, discount_low))
        discount_high = max(discount_low + 0.1, min(1.1, discount_high))
        
        discount_mid = (discount_low + discount_high) / 2
        
        return discount_low, discount_mid, discount_high
    
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
        
        # 计算NAV
        nav = self._calculate_nav(input_data)
        if nav is None or nav <= 0:
            self._add_validation_error("NAV计算失败或为零/负数")
            return results
        
        # 每股NAV
        nav_per_share = nav / input_data.total_shares
        
        # 当前P/NAV（市净率概念）
        current_p_nav = input_data.price / nav_per_share
        
        # 评估土地质量
        land_quality = self._assess_land_quality(input_data)
        
        # 获取NAV折价区间
        discount_low, discount_mid, discount_high = self.get_fair_value_range(
            input_data, **kwargs
        )
        
        # 计算隐含股价（NAV * 折价率）
        implied_price_low = nav_per_share * discount_low
        implied_price_mid = nav_per_share * discount_mid
        implied_price_high = nav_per_share * discount_high
        
        # 计算风险收益
        upside, downside = self._calculate_upside_downside(
            input_data.price,
            implied_price_low,
            implied_price_mid,
            implied_price_high
        )
        
        # 计算置信度
        confidence = self._calculate_confidence(input_data, land_quality)
        
        # 获取NAV组成部分
        components = self._calculate_nav_components(input_data)
        
        # 警告信息
        warnings = []
        if current_p_nav > 1.2:
            warnings.append("当前股价高于NAV（溢价），注意估值风险")
        if components.get("net_debt", 0) > nav * 0.8:
            warnings.append("净负债过高，财务风险较大")
        if land_quality == "low":
            warnings.append("土地储备质量较低，NAV存在下调风险")
        
        # 融资成本关注
        financing_cost = input_data.extra_data.get("avg_financing_cost")
        if financing_cost is not None and financing_cost > 0.08:
            warnings.append(f"融资成本较高（{financing_cost*100:.1f}%），影响盈利能力")
        
        nav_result = ValuationResult(
            method=ValuationMethod.NAV,
            stock_code=input_data.stock_code,
            current_value=current_p_nav,
            fair_value_low=discount_low,
            fair_value_mid=discount_mid,
            fair_value_high=discount_high,
            implied_price_low=implied_price_low,
            implied_price_mid=implied_price_mid,
            implied_price_high=implied_price_high,
            upside_potential=upside,
            downside_risk=downside,
            confidence=confidence,
            assumptions={
                "nav": nav,
                "nav_per_share": nav_per_share,
                "discount_rate": self.discount_rate,
                "land_quality": land_quality,
                "nav_components": components,
                "methodology": "NAV估值法",
            },
            warnings=warnings,
            calculation_date=date.today(),
        )
        results.append(nav_result)
        
        # ===== 辅助方法：PB估值 =====
        if input_data.shareholders_equity is not None and input_data.shareholders_equity > 0:
            bvps = input_data.get_book_value_per_share()
            if bvps is not None and bvps > 0:
                current_pb = input_data.get_current_pb()
                if current_pb is None:
                    current_pb = input_data.price / bvps
                
                # 房地产PB区间（通常0.5-1.2倍）
                if land_quality == "high":
                    pb_low, pb_high = 0.8, 1.5
                elif land_quality == "medium":
                    pb_low, pb_high = 0.6, 1.2
                else:
                    pb_low, pb_high = 0.4, 1.0
                
                pb_mid = (pb_low + pb_high) / 2
                
                # 计算隐含股价
                pb_implied_price_low = bvps * pb_low
                pb_implied_price_mid = bvps * pb_mid
                pb_implied_price_high = bvps * pb_high
                
                # 计算风险收益
                pb_upside, pb_downside = self._calculate_upside_downside(
                    input_data.price,
                    pb_implied_price_low,
                    pb_implied_price_mid,
                    pb_implied_price_high
                )
                
                pb_warnings = []
                if current_pb > 2.0:
                    pb_warnings.append("当前PB过高（>2倍），注意估值风险")
                
                pb_result = ValuationResult(
                    method=ValuationMethod.PB,
                    stock_code=input_data.stock_code,
                    current_value=current_pb,
                    fair_value_low=pb_low,
                    fair_value_mid=pb_mid,
                    fair_value_high=pb_high,
                    implied_price_low=pb_implied_price_low,
                    implied_price_mid=pb_implied_price_mid,
                    implied_price_high=pb_implied_price_high,
                    upside_potential=pb_upside,
                    downside_risk=pb_downside,
                    confidence=confidence * 0.8,
                    assumptions={
                        "book_value_per_share": bvps,
                        "land_quality": land_quality,
                        "methodology": "PB估值法（辅助）",
                    },
                    warnings=pb_warnings,
                    calculation_date=date.today(),
                )
                results.append(pb_result)
        
        return results
    
    def _calculate_confidence(
        self,
        input_data: ValuationInput,
        land_quality: str
    ) -> float:
        """
        计算估值置信度
        
        Args:
            input_data: 估值输入数据
            land_quality: 土地质量评级
            
        Returns:
            float: 置信度(0-1)
        """
        confidence = 0.60  # 房地产行业基础置信度
        
        # NAV数据完整性
        nav_data = input_data.extra_data.get("nav_components", {})
        if nav_data:
            if "developed_projects_pv" in nav_data:
                confidence += 0.05
            if "land_reserve_pv" in nav_data:
                confidence += 0.05
            if "land_reserve" in input_data.extra_data:
                confidence += 0.05
        
        # 土地质量
        if land_quality == "high":
            confidence += 0.1
        elif land_quality == "medium":
            confidence += 0.05
        
        # 财务数据
        if input_data.net_debt is not None:
            confidence += 0.05
        
        # 融资成本信息
        if input_data.extra_data.get("avg_financing_cost") is not None:
            confidence += 0.05
        
        return max(0.0, min(1.0, confidence))


# 便捷函数
def value_real_estate_stock(
    stock_code: str,
    price: float,
    total_shares: float,
    market_cap: float,
    shareholders_equity: float,
    net_debt: float,
    developed_projects_pv: Optional[float] = None,
    land_reserve_pv: Optional[float] = None,
    land_reserve_data: Optional[Dict[str, Any]] = None,
    **kwargs
) -> List[ValuationResult]:
    """
    便捷函数：对房地产股票进行估值
    
    Args:
        stock_code: 股票代码
        price: 当前股价
        total_shares: 总股本
        market_cap: 总市值
        shareholders_equity: 股东权益
        net_debt: 净负债
        developed_projects_pv: 已开发项目现值（可选）
        land_reserve_pv: 土地储备现值（可选）
        land_reserve_data: 土地储备数据（可选）
        **kwargs: 其他参数
        
    Returns:
        List[ValuationResult]: 估值结果列表
    """
    extra_data = {}
    
    # 构建NAV组件
    nav_components = {
        "net_debt": net_debt,
    }
    if developed_projects_pv is not None:
        nav_components["developed_projects_pv"] = developed_projects_pv
    if land_reserve_pv is not None:
        nav_components["land_reserve_pv"] = land_reserve_pv
    
    if nav_components:
        extra_data["nav_components"] = nav_components
    
    if land_reserve_data:
        extra_data["land_reserve"] = land_reserve_data
    
    input_data = ValuationInput(
        stock_code=stock_code,
        report_date=date.today(),
        total_shares=total_shares,
        price=price,
        market_cap=market_cap,
        shareholders_equity=shareholders_equity,
        net_debt=net_debt,
        extra_data=extra_data,
    )
    
    model = RealEstateValuationModel(**kwargs)
    return model.calculate(input_data)
