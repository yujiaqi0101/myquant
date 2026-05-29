"""
公用事业估值模型

适用行业：电力、水务、燃气、交通运输
主要方法：PE、DCF
辅助方法：股息率模型
DCF参数：WACC 8%，永续增长率 2%
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


class UtilityValuationModel(ValuationModel):
    """
    公用事业估值模型
    
    适用于电力、水务、燃气、交通运输等公用事业行业。
    公用事业具有现金流稳定、增长缓慢、高股息等特点，
    适合使用PE、DCF和股息率模型进行估值。
    
    Attributes:
        wacc: 加权平均资本成本（默认8%）
        terminal_growth_rate: 永续增长率（默认2%）
        pe_low: PE下限（默认10倍）
        pe_high: PE上限（默认20倍）
        dividend_yield_low: 股息率下限（默认3%）
        dividend_yield_high: 股息率上限（默认6%）
        projection_years: DCF预测年数（默认10年）
    """
    
    # 适用行业列表
    APPLICABLE_INDUSTRIES = [
        "电力", "水务", "燃气", "交通运输",
        "火电", "水电", "核电", "风电", "光伏",
        "供水", "污水处理", "天然气", "城市燃气",
        "港口", "高速公路", "铁路", "航空", "物流",
        "电网", "供热"
    ]
    
    def __init__(
        self,
        wacc: float = 0.08,
        terminal_growth_rate: float = 0.02,
        pe_low: float = 10.0,
        pe_high: float = 20.0,
        dividend_yield_low: float = 0.03,
        dividend_yield_high: float = 0.06,
        projection_years: int = 10,
    ):
        """
        初始化公用事业估值模型
        
        Args:
            wacc: 加权平均资本成本（默认8%）
            terminal_growth_rate: 永续增长率（默认2%）
            pe_low: PE下限（默认10倍）
            pe_high: PE上限（默认20倍）
            dividend_yield_low: 股息率下限（默认3%）
            dividend_yield_high: 股息率上限（默认6%）
            projection_years: DCF预测年数（默认10年）
        """
        super().__init__(ValuationMethod.DCF)
        self.wacc = wacc
        self.terminal_growth_rate = terminal_growth_rate
        self.pe_low = pe_low
        self.pe_high = pe_high
        self.dividend_yield_low = dividend_yield_low
        self.dividend_yield_high = dividend_yield_high
        self.projection_years = projection_years
    
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
        
        # PE需要净利润
        if input_data.net_profit is None:
            self._add_validation_error("净利润不能为空（PE估值需要）")
            valid = False
        
        # DCF需要自由现金流或经营现金流
        if input_data.free_cash_flow is None and input_data.operating_cash_flow is None:
            self._add_validation_error("自由现金流或经营现金流不能为空（DCF需要）")
            valid = False
        
        return valid
    
    def _get_growth_rate(self, input_data: ValuationInput) -> float:
        """
        获取增长率（公用事业通常较低且稳定）
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            float: 增长率（小数形式）
        """
        # 从extra_data获取
        growth = input_data.extra_data.get("profit_growth_rate")
        if growth is not None:
            return max(0, min(0.10, growth))  # 限制在0-10%
        
        # 公用事业默认低增长
        return 0.03
    
    def _get_dividend(self, input_data: ValuationInput) -> Optional[float]:
        """
        获取股息数据
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            Optional[float]: 年度股息总额
        """
        dividend = input_data.extra_data.get("dividend")
        if dividend is not None:
            return dividend
        
        # 尝试用净利润和分红率计算
        payout_ratio = input_data.extra_data.get("payout_ratio")
        if payout_ratio is not None and input_data.net_profit is not None:
            return input_data.net_profit * payout_ratio
        
        return None
    
    def _calculate_dcf(
        self,
        input_data: ValuationInput,
        growth_rate: float
    ) -> Optional[Tuple[float, float, float]]:
        """
        计算DCF估值
        
        Args:
            input_data: 估值输入数据
            growth_rate: 增长率
            
        Returns:
            Optional[Tuple[float, float, float]]: (股权价值下限, 中值, 上限)
        """
        # 获取自由现金流
        fcf = input_data.free_cash_flow
        if fcf is None:
            # 用经营现金流近似
            if input_data.operating_cash_flow is not None:
                # 假设资本支出为经营现金流的30%
                fcf = input_data.operating_cash_flow * 0.7
            else:
                return None
        
        if fcf <= 0:
            return None
        
        # 计算不同情景下的DCF价值
        scenarios = []
        
        for scenario_growth in [growth_rate * 0.5, growth_rate, growth_rate * 1.5]:
            # 确保增长率合理
            scenario_growth = max(0, min(0.08, scenario_growth))
            
            # 预测期现金流现值
            pv_cf = 0
            cf = fcf
            for year in range(1, self.projection_years + 1):
                cf *= (1 + scenario_growth)
                pv_cf += cf / ((1 + self.wacc) ** year)
            
            # 终值（Gordon增长模型）
            terminal_cf = cf * (1 + self.terminal_growth_rate)
            terminal_value = terminal_cf / (self.wacc - self.terminal_growth_rate)
            pv_terminal = terminal_value / ((1 + self.wacc) ** self.projection_years)
            
            # 企业价值
            enterprise_value = pv_cf + pv_terminal
            
            # 股权价值（减去净负债）
            net_debt = input_data.net_debt if input_data.net_debt is not None else 0
            equity_value = enterprise_value - net_debt
            
            scenarios.append(max(0, equity_value))
        
        if len(scenarios) < 3:
            return None
        
        return scenarios[0], scenarios[1], scenarios[2]
    
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
                - regulatory_environment: 监管环境
                
        Returns:
            Tuple[float, float, float]: (PE下限, PE中值, PE上限)
        """
        growth_rate = kwargs.get("growth_override", self._get_growth_rate(input_data))
        regulatory_env = kwargs.get("regulatory_environment", "neutral")
        
        # 基础PE区间
        pe_low, pe_high = self.pe_low, self.pe_high
        
        # 根据增长率调整
        if growth_rate >= 0.05:
            pe_low += 2
            pe_high += 3
        elif growth_rate < 0.02:
            pe_low -= 2
            pe_high -= 3
        
        # 根据监管环境调整
        if regulatory_env == "favorable":
            pe_low += 1
            pe_high += 2
        elif regulatory_env == "restrictive":
            pe_low -= 2
            pe_high -= 2
        
        # 确保区间合理性
        pe_low = max(8.0, pe_low)
        pe_high = max(pe_low + 3, pe_high)
        
        pe_mid = (pe_low + pe_high) / 2
        
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
        
        # 获取基础数据
        eps = input_data.get_eps()
        if eps is None or eps <= 0:
            return results
        
        growth_rate = self._get_growth_rate(input_data)
        
        # ===== 1. DCF估值 =====
        dcf_values = self._calculate_dcf(input_data, growth_rate)
        
        if dcf_values is not None:
            dcf_low, dcf_mid, dcf_high = dcf_values
            
            # 转换为每股价格
            if input_data.total_shares > 0:
                dcf_price_low = dcf_low / input_data.total_shares
                dcf_price_mid = dcf_mid / input_data.total_shares
                dcf_price_high = dcf_high / input_data.total_shares
                
                # 计算风险收益
                dcf_upside, dcf_downside = self._calculate_upside_downside(
                    input_data.price,
                    dcf_price_low,
                    dcf_price_mid,
                    dcf_price_high
                )
                
                # 计算置信度
                confidence = self._calculate_confidence(input_data)
                
                # 警告信息
                warnings = []
                if input_data.free_cash_flow is None:
                    warnings.append("缺少自由现金流数据，使用经营现金流估算")
                
                dcf_result = ValuationResult(
                    method=ValuationMethod.DCF,
                    stock_code=input_data.stock_code,
                    current_value=input_data.price,  # DCF没有直接可比值
                    fair_value_low=dcf_low,
                    fair_value_mid=dcf_mid,
                    fair_value_high=dcf_high,
                    implied_price_low=dcf_price_low,
                    implied_price_mid=dcf_price_mid,
                    implied_price_high=dcf_price_high,
                    upside_potential=dcf_upside,
                    downside_risk=dcf_downside,
                    confidence=confidence,
                    assumptions={
                        "wacc": self.wacc,
                        "terminal_growth_rate": self.terminal_growth_rate,
                        "projection_years": self.projection_years,
                        "growth_rate": growth_rate,
                        "methodology": "DCF估值法",
                    },
                    warnings=warnings,
                    calculation_date=date.today(),
                )
                results.append(dcf_result)
        
        # ===== 2. PE估值 =====
        current_pe = input_data.get_current_pe()
        if current_pe is None:
            current_pe = input_data.price / eps
        
        pe_low, pe_mid, pe_high = self.get_fair_value_range(input_data, **kwargs)
        
        # 计算隐含股价
        pe_implied_price_low = eps * pe_low
        pe_implied_price_mid = eps * pe_mid
        pe_implied_price_high = eps * pe_high
        
        # 计算风险收益
        pe_upside, pe_downside = self._calculate_upside_downside(
            input_data.price,
            pe_implied_price_low,
            pe_implied_price_mid,
            pe_implied_price_high
        )
        
        # 警告信息
        pe_warnings = []
        if current_pe > 25:
            pe_warnings.append("当前PE过高（>25倍），注意估值风险")
        elif current_pe < 8:
            pe_warnings.append("当前PE过低（<8倍），可能存在经营风险")
        
        pe_result = ValuationResult(
            method=ValuationMethod.PE,
            stock_code=input_data.stock_code,
            current_value=current_pe,
            fair_value_low=pe_low,
            fair_value_mid=pe_mid,
            fair_value_high=pe_high,
            implied_price_low=pe_implied_price_low,
            implied_price_mid=pe_implied_price_mid,
            implied_price_high=pe_implied_price_high,
            upside_potential=pe_upside,
            downside_risk=pe_downside,
            confidence=self._calculate_confidence(input_data) * 0.9,
            assumptions={
                "eps": eps,
                "growth_rate": growth_rate,
                "pe_range": f"{pe_low:.1f}-{pe_high:.1f}",
                "methodology": "PE估值法",
            },
            warnings=pe_warnings,
            calculation_date=date.today(),
        )
        results.append(pe_result)
        
        # ===== 3. 股息率模型（辅助方法）=====
        dividend = self._get_dividend(input_data)
        if dividend is not None and dividend > 0:
            # 每股股息
            dps = dividend / input_data.total_shares
            
            # 当前股息率
            current_yield = dps / input_data.price
            
            # 计算不同股息率要求下的隐含股价
            div_price_low = dps / self.dividend_yield_low
            div_price_high = dps / self.dividend_yield_high
            div_price_mid = (div_price_low + div_price_high) / 2
            
            # 计算风险收益
            div_upside, div_downside = self._calculate_upside_downside(
                input_data.price,
                div_price_low,
                div_price_mid,
                div_price_high
            )
            
            # 股息率合理区间
            yield_low, yield_high = self.dividend_yield_low, self.dividend_yield_high
            yield_mid = (yield_low + yield_high) / 2
            
            div_warnings = []
            if current_yield < 0.02:
                div_warnings.append("股息率较低（<2%），不符合公用事业特征")
            
            # 计算分红率
            payout_ratio = dividend / input_data.net_profit if input_data.net_profit else 0
            if payout_ratio > 0.9:
                div_warnings.append("分红率过高（>90%），可持续性存疑")
            
            div_result = ValuationResult(
                method=ValuationMethod.PE,  # 复用PE类型表示股息率
                stock_code=input_data.stock_code,
                current_value=current_yield,
                fair_value_low=yield_low,
                fair_value_mid=yield_mid,
                fair_value_high=yield_high,
                implied_price_low=div_price_low,
                implied_price_mid=div_price_mid,
                implied_price_high=div_price_high,
                upside_potential=div_upside,
                downside_risk=div_downside,
                confidence=self._calculate_confidence(input_data) * 0.8,
                assumptions={
                    "dps": dps,
                    "dividend": dividend,
                    "payout_ratio": payout_ratio,
                    "methodology": "股息率模型",
                },
                warnings=div_warnings,
                calculation_date=date.today(),
            )
            results.append(div_result)
        
        return results
    
    def _calculate_confidence(self, input_data: ValuationInput) -> float:
        """
        计算估值置信度
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            float: 置信度(0-1)
        """
        confidence = 0.75  # 公用事业基础置信度较高（现金流稳定）
        
        # 数据完整性
        if input_data.free_cash_flow is not None:
            confidence += 0.1
        elif input_data.operating_cash_flow is not None:
            confidence += 0.05
        
        if input_data.net_debt is not None:
            confidence += 0.05
        
        # 股息数据
        if self._get_dividend(input_data) is not None:
            confidence += 0.05
        
        # 盈利稳定性
        if input_data.net_profit is not None and input_data.operating_profit is not None:
            if input_data.net_profit > 0 and input_data.operating_profit > 0:
                confidence += 0.05
        
        return max(0.0, min(1.0, confidence))


# 便捷函数
def value_utility_stock(
    stock_code: str,
    price: float,
    total_shares: float,
    market_cap: float,
    net_profit: float,
    free_cash_flow: Optional[float] = None,
    operating_cash_flow: Optional[float] = None,
    net_debt: Optional[float] = None,
    dividend: Optional[float] = None,
    **kwargs
) -> List[ValuationResult]:
    """
    便捷函数：对公用事业股票进行估值
    
    Args:
        stock_code: 股票代码
        price: 当前股价
        total_shares: 总股本
        market_cap: 总市值
        net_profit: 净利润
        free_cash_flow: 自由现金流（可选）
        operating_cash_flow: 经营现金流（可选）
        net_debt: 净债务（可选）
        dividend: 年度股息（可选）
        **kwargs: 其他参数
        
    Returns:
        List[ValuationResult]: 估值结果列表
    """
    extra_data = {}
    if dividend is not None:
        extra_data["dividend"] = dividend
    
    input_data = ValuationInput(
        stock_code=stock_code,
        report_date=date.today(),
        total_shares=total_shares,
        price=price,
        market_cap=market_cap,
        net_profit=net_profit,
        free_cash_flow=free_cash_flow,
        operating_cash_flow=operating_cash_flow,
        net_debt=net_debt,
        extra_data=extra_data,
    )
    
    model = UtilityValuationModel(**kwargs)
    return model.calculate(input_data)
