"""
科技行业估值模型

适用行业：电子、计算机、通信、传媒、新能源
主要方法：PEG、PS
辅助方法：EV/Sales
特点：关注成长性和研发投入，PEG考虑成长性溢价
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


class TechnologyValuationModel(ValuationModel):
    """
    科技行业估值模型
    
    适用于电子、计算机、通信、传媒、新能源等科技行业。
    科技行业具有高成长、高投入、轻资产等特点，
    适合使用PEG、PS等关注成长性的估值方法。
    
    Attributes:
        peg_low: PEG下限（默认0.8）
        peg_high: PEG上限（默认2.0）
        ps_low: PS下限（默认3.0）
        ps_high: PS上限（默认15.0）
        growth_rate: 预期增长率
        rd_intensity_threshold: 研发投入强度阈值
    """
    
    # 适用行业列表
    APPLICABLE_INDUSTRIES = [
        "电子", "计算机", "通信", "传媒", "新能源",
        "半导体", "元件", "光学光电子", "消费电子", "电子化学品",
        "软件开发", "IT服务", "计算机设备", "通信设备", "通信服务",
        "游戏", "广告营销", "影视院线", "数字媒体", "社交",
        "光伏", "风电", "储能", "锂电池", "新能源汽车",
        "军工电子", "医疗器械", "创新药", "CXO"
    ]
    
    def __init__(
        self,
        peg_low: float = 0.8,
        peg_high: float = 2.0,
        ps_low: float = 3.0,
        ps_high: float = 15.0,
        growth_rate: Optional[float] = None,
        rd_intensity_threshold: float = 0.10,
    ):
        """
        初始化科技行业估值模型
        
        Args:
            peg_low: PEG下限（默认0.8）
            peg_high: PEG上限（默认2.0）
            ps_low: PS下限（默认3.0）
            ps_high: PS上限（默认15.0）
            growth_rate: 预期增长率（可选）
            rd_intensity_threshold: 研发投入强度阈值（默认10%）
        """
        super().__init__(ValuationMethod.PEG)
        self.peg_low = peg_low
        self.peg_high = peg_high
        self.ps_low = ps_low
        self.ps_high = ps_high
        self.growth_rate = growth_rate
        self.rd_intensity_threshold = rd_intensity_threshold
    
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
        
        # PEG需要净利润和增长率
        if input_data.net_profit is None:
            self._add_validation_error("净利润不能为空（PEG估值需要）")
            valid = False
        
        # PS需要收入
        if input_data.revenue is None:
            self._add_validation_error("营业收入不能为空（PS估值需要）")
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
        
        # 营收增长率
        revenue_growth = input_data.extra_data.get("revenue_growth_rate")
        if revenue_growth is not None:
            return revenue_growth
        
        # 科技行业默认较高增长率
        return 0.25
    
    def _get_rd_intensity(self, input_data: ValuationInput) -> float:
        """
        获取研发投入强度
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            float: 研发投入强度（研发费用/收入）
        """
        rd_expense = input_data.extra_data.get("rd_expense")
        if rd_expense is not None and input_data.revenue is not None and input_data.revenue > 0:
            return rd_expense / input_data.revenue
        
        return input_data.extra_data.get("rd_intensity", 0.0)
    
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
    
    def _adjust_ps_by_growth(self, growth_rate: float, rd_intensity: float) -> Tuple[float, float]:
        """
        根据增长率和研发投入调整PS区间
        
        Args:
            growth_rate: 增长率（小数形式）
            rd_intensity: 研发投入强度
            
        Returns:
            Tuple[float, float]: 调整后的PS区间
        """
        g_pct = growth_rate * 100
        
        # 基础PS区间
        if g_pct >= 40:
            ps_low, ps_high = 8.0, 25.0
        elif g_pct >= 25:
            ps_low, ps_high = 5.0, 15.0
        elif g_pct >= 15:
            ps_low, ps_high = 3.0, 10.0
        else:
            ps_low, ps_high = 2.0, 6.0
        
        # 研发投入溢价
        if rd_intensity >= self.rd_intensity_threshold:
            rd_premium = 1 + (rd_intensity - self.rd_intensity_threshold)
            ps_low *= min(1.3, rd_premium)
            ps_high *= min(1.5, rd_premium)
        
        return ps_low, ps_high
    
    def get_fair_value_range(
        self,
        input_data: ValuationInput,
        **kwargs
    ) -> Tuple[float, float, float]:
        """
        获取公允价值区间（PEG区间）
        
        Args:
            input_data: 估值输入数据
            **kwargs: 额外参数
                - growth_override: 覆盖增长率
                - tech_premium: 技术溢价系数
                
        Returns:
            Tuple[float, float, float]: (PEG下限, PEG中值, PEG上限)
        """
        growth_rate = kwargs.get("growth_override", self._get_growth_rate(input_data))
        tech_premium = kwargs.get("tech_premium", 1.0)
        
        # 根据增长率调整PEG区间
        g_pct = growth_rate * 100
        if g_pct >= 40:
            peg_low, peg_high = 1.0, 2.5
        elif g_pct >= 25:
            peg_low, peg_high = 0.8, 2.0
        elif g_pct >= 15:
            peg_low, peg_high = 0.6, 1.5
        else:
            peg_low, peg_high = 0.5, 1.2
        
        # 应用技术溢价
        peg_low *= tech_premium
        peg_high *= tech_premium
        
        peg_mid = (peg_low + peg_high) / 2
        
        return peg_low, peg_mid, peg_high
    
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
        
        # 获取基础数据
        eps = input_data.get_eps()
        rps = input_data.get_revenue_per_share()
        
        if eps is None or rps is None:
            return results
        
        # 获取增长率
        growth_rate = self._get_growth_rate(input_data)
        rd_intensity = self._get_rd_intensity(input_data)
        
        # ===== 1. PEG估值 =====
        if eps > 0:
            current_pe = input_data.get_current_pe()
            if current_pe is None:
                current_pe = input_data.price / eps
            
            peg = self._calculate_peg(current_pe, growth_rate)
            
            if peg is not None:
                peg_low, peg_mid, peg_high = self.get_fair_value_range(input_data, **kwargs)
                
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
                
                # 计算置信度
                confidence = self._calculate_confidence(input_data, growth_rate)
                
                # 警告信息
                warnings = []
                if current_pe > 80:
                    warnings.append("当前PE过高（>80倍），注意估值泡沫风险")
                if peg > 3.0:
                    warnings.append("PEG过高（>3），可能被严重高估")
                elif peg > self.peg_high:
                    warnings.append(f"PEG高于合理区间上限（{self.peg_high}）")
                if growth_rate < 0.10:
                    warnings.append("增长率过低（<10%），不符合科技行业特征")
                
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
                    confidence=confidence,
                    assumptions={
                        "eps": eps,
                        "current_pe": current_pe,
                        "growth_rate": growth_rate,
                        "implied_pe_low": peg_implied_pe_low,
                        "implied_pe_mid": peg_implied_pe_mid,
                        "implied_pe_high": peg_implied_pe_high,
                        "methodology": "PEG估值法",
                    },
                    warnings=warnings,
                    calculation_date=date.today(),
                )
                results.append(peg_result)
        
        # ===== 2. PS估值 =====
        if rps > 0:
            current_ps = input_data.get_current_ps()
            if current_ps is None:
                current_ps = input_data.price / rps
            
            ps_low, ps_high = self._adjust_ps_by_growth(growth_rate, rd_intensity)
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
            if current_ps > 20:
                ps_warnings.append("当前PS过高（>20倍），注意估值风险")
            if rd_intensity < 0.05:
                ps_warnings.append("研发投入强度较低（<5%），科技属性存疑")
            
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
                confidence=self._calculate_confidence(input_data, growth_rate) * 0.85,
                assumptions={
                    "rps": rps,
                    "growth_rate": growth_rate,
                    "rd_intensity": rd_intensity,
                    "methodology": "PS估值法",
                },
                warnings=ps_warnings,
                calculation_date=date.today(),
            )
            results.append(ps_result)
        
        # ===== 3. EV/Sales估值（辅助方法）=====
        if input_data.revenue is not None and input_data.revenue > 0:
            ev = input_data.get_enterprise_value()
            if ev is not None and ev > 0:
                current_ev_sales = ev / input_data.revenue
                
                # EV/Sales区间（通常比PS略低）
                ev_sales_low = ps_low * 0.9
                ev_sales_high = ps_high * 0.9
                ev_sales_mid = (ev_sales_low + ev_sales_high) / 2
                
                # 计算隐含企业价值
                ev_implied_low = input_data.revenue * ev_sales_low
                ev_implied_mid = input_data.revenue * ev_sales_mid
                ev_implied_high = input_data.revenue * ev_sales_high
                
                # 转换为股权价值
                net_debt = input_data.net_debt if input_data.net_debt is not None else 0
                
                equity_implied_low = max(0, ev_implied_low - net_debt)
                equity_implied_mid = max(0, ev_implied_mid - net_debt)
                equity_implied_high = max(0, ev_implied_high - net_debt)
                
                # 转换为每股价格
                if input_data.total_shares > 0:
                    ev_sales_implied_price_low = equity_implied_low / input_data.total_shares
                    ev_sales_implied_price_mid = equity_implied_mid / input_data.total_shares
                    ev_sales_implied_price_high = equity_implied_high / input_data.total_shares
                    
                    # 计算风险收益
                    ev_sales_upside, ev_sales_downside = self._calculate_upside_downside(
                        input_data.price,
                        ev_sales_implied_price_low,
                        ev_sales_implied_price_mid,
                        ev_sales_implied_price_high
                    )
                    
                    ev_sales_result = ValuationResult(
                        method=ValuationMethod.EV_EBITDA,  # 复用EV/EBITDA类型
                        stock_code=input_data.stock_code,
                        current_value=current_ev_sales,
                        fair_value_low=ev_sales_low,
                        fair_value_mid=ev_sales_mid,
                        fair_value_high=ev_sales_high,
                        implied_price_low=ev_sales_implied_price_low,
                        implied_price_mid=ev_sales_implied_price_mid,
                        implied_price_high=ev_sales_implied_price_high,
                        upside_potential=ev_sales_upside,
                        downside_risk=ev_sales_downside,
                        confidence=self._calculate_confidence(input_data, growth_rate) * 0.75,
                        assumptions={
                            "revenue": input_data.revenue,
                            "enterprise_value": ev,
                            "net_debt": net_debt,
                            "growth_rate": growth_rate,
                            "methodology": "EV/Sales估值法（辅助）",
                        },
                        warnings=[],
                        calculation_date=date.today(),
                    )
                    results.append(ev_sales_result)
        
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
        confidence = 0.65  # 科技行业基础置信度
        
        # 数据完整性
        if input_data.net_profit is not None:
            confidence += 0.05
        if input_data.revenue is not None:
            confidence += 0.05
        if input_data.operating_profit is not None:
            confidence += 0.05
        
        # 增长率合理性
        if 0.15 <= growth_rate <= 0.50:
            confidence += 0.1
        elif growth_rate < 0:
            confidence -= 0.15
        elif growth_rate > 1.0:
            confidence -= 0.1
        
        # 研发投入信息
        rd_intensity = self._get_rd_intensity(input_data)
        if rd_intensity > 0:
            confidence += 0.05
        
        # 盈利质量
        if input_data.net_profit is not None and input_data.revenue is not None:
            if input_data.revenue > 0:
                net_margin = input_data.net_profit / input_data.revenue
                if net_margin > 0.10:
                    confidence += 0.05
        
        return max(0.0, min(1.0, confidence))


# 便捷函数
def value_tech_stock(
    stock_code: str,
    price: float,
    total_shares: float,
    market_cap: float,
    net_profit: float,
    revenue: float,
    growth_rate: Optional[float] = None,
    rd_expense: Optional[float] = None,
    net_debt: Optional[float] = None,
    **kwargs
) -> List[ValuationResult]:
    """
    便捷函数：对科技行业股票进行估值
    
    Args:
        stock_code: 股票代码
        price: 当前股价
        total_shares: 总股本
        market_cap: 总市值
        net_profit: 净利润
        revenue: 营业收入
        growth_rate: 预期增长率（可选）
        rd_expense: 研发费用（可选）
        net_debt: 净债务（可选）
        **kwargs: 其他参数
        
    Returns:
        List[ValuationResult]: 估值结果列表
    """
    extra_data = {}
    if growth_rate is not None:
        extra_data["profit_growth_rate"] = growth_rate
    if rd_expense is not None:
        extra_data["rd_expense"] = rd_expense
    
    input_data = ValuationInput(
        stock_code=stock_code,
        report_date=date.today(),
        total_shares=total_shares,
        price=price,
        market_cap=market_cap,
        net_profit=net_profit,
        revenue=revenue,
        net_debt=net_debt,
        extra_data=extra_data,
    )
    
    model = TechnologyValuationModel(**kwargs)
    return model.calculate(input_data)
