"""
金融行业估值模型

适用行业：银行、保险、券商、信托、多元金融
主要方法：PB-ROE模型（合理PB = ROE / 要求回报率）
辅助方法：PE估值
合理PB区间：基于历史分位数（25%-75%）和ROE调整
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


class FinancialValuationModel(ValuationModel):
    """
    金融行业估值模型
    
    适用于银行、保险、券商、信托、多元金融等金融行业。
    金融行业具有高杠杆、周期性强、资产驱动等特点，
    因此PB-ROE模型是最主要的估值方法。
    
    Attributes:
        required_return: 要求回报率（默认10%）
        pb_percentile_low: PB历史分位数下限（默认25%）
        pb_percentile_high: PB历史分位数上限（默认75%）
        pe_range: PE合理区间（默认5-15倍）
    """
    
    # 适用行业列表
    APPLICABLE_INDUSTRIES = [
        "银行", "保险", "券商", "信托", "多元金融",
        "商业银行", "投资银行", "资产管理", "金融租赁",
        "期货", "担保", "小额贷款", "互联网金融"
    ]
    
    def __init__(
        self,
        required_return: float = 0.10,
        pb_percentile_low: float = 25.0,
        pb_percentile_high: float = 75.0,
        pe_low: float = 5.0,
        pe_high: float = 15.0,
    ):
        """
        初始化金融行业估值模型
        
        Args:
            required_return: 要求回报率（默认10%）
            pb_percentile_low: PB历史分位数下限（默认25%）
            pb_percentile_high: PB历史分位数上限（默认75%）
            pe_low: PE下限（默认5倍）
            pe_high: PE上限（默认15倍）
        """
        super().__init__(ValuationMethod.PB)
        self.required_return = required_return
        self.pb_percentile_low = pb_percentile_low
        self.pb_percentile_high = pb_percentile_high
        self.pe_low = pe_low
        self.pe_high = pe_high
        
        # 历史PB数据（用于分位数计算）
        self._historical_pb: Optional[List[float]] = None
        # ROE历史数据
        self._historical_roe: Optional[List[float]] = None
    
    def set_historical_data(
        self,
        historical_pb: Optional[List[float]] = None,
        historical_roe: Optional[List[float]] = None,
    ):
        """
        设置历史数据用于分位数计算
        
        Args:
            historical_pb: 历史PB数据列表
            historical_roe: 历史ROE数据列表
        """
        self._historical_pb = historical_pb
        self._historical_roe = historical_roe
    
    def validate_input(self, input_data: ValuationInput) -> bool:
        """
        验证输入数据是否满足估值计算要求
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            bool: 验证是否通过
        """
        self._clear_validation_errors()
        
        # 基础数据验证
        valid = True
        valid &= self._check_positive(input_data.price, "当前股价")
        valid &= self._check_positive(input_data.total_shares, "总股本")
        valid &= self._check_positive(input_data.market_cap, "总市值")
        
        # 金融行业必须的数据
        valid &= self._check_not_none(input_data.shareholders_equity, "股东权益")
        valid &= self._check_positive(input_data.shareholders_equity, "股东权益")
        
        # 从extra_data获取ROE
        roe = input_data.extra_data.get("roe")
        if roe is None:
            # 如果没有直接提供ROE，尝试用净利润/股东权益计算
            if input_data.net_profit is None:
                self._add_validation_error("净利润或ROE必须提供其一")
                valid = False
        
        return valid
    
    def _calculate_roe(self, input_data: ValuationInput) -> Optional[float]:
        """
        计算ROE
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            Optional[float]: ROE值
        """
        # 优先使用提供的ROE
        roe = input_data.extra_data.get("roe")
        if roe is not None:
            return roe
        
        # 否则用净利润/股东权益计算
        if (input_data.net_profit is not None and 
            input_data.shareholders_equity is not None and
            input_data.shareholders_equity > 0):
            return input_data.net_profit / input_data.shareholders_equity
        
        return None
    
    def _get_historical_pb_range(self) -> Tuple[float, float]:
        """
        获取历史PB区间（基于分位数）
        
        Returns:
            Tuple[float, float]: (PB下限, PB上限)
        """
        if self._historical_pb and len(self._historical_pb) > 0:
            sorted_pb = sorted(self._historical_pb)
            n = len(sorted_pb)
            
            # 计算分位数索引
            low_idx = int(self.pb_percentile_low / 100 * (n - 1))
            high_idx = int(self.pb_percentile_high / 100 * (n - 1))
            
            pb_low = sorted_pb[low_idx]
            pb_high = sorted_pb[high_idx]
        else:
            # 使用默认区间
            pb_low = 0.6
            pb_high = 1.5
        
        return pb_low, pb_high
    
    def _calculate_theoretical_pb(self, roe: float) -> float:
        """
        基于PB-ROE模型计算理论PB
        
        公式：合理PB = ROE / 要求回报率
        
        Args:
            roe: 净资产收益率
            
        Returns:
            float: 理论PB值
        """
        if self.required_return <= 0:
            return 1.0
        return roe / self.required_return
    
    def get_fair_value_range(
        self,
        input_data: ValuationInput,
        **kwargs
    ) -> Tuple[float, float, float]:
        """
        获取公允价值区间
        
        Args:
            input_data: 估值输入数据
            **kwargs: 额外参数
                - roe_override: 覆盖ROE值
                - use_historical: 是否使用历史PB区间
                
        Returns:
            Tuple[float, float, float]: (PB下限, PB中值, PB上限)
        """
        # 获取ROE
        roe = kwargs.get("roe_override", self._calculate_roe(input_data))
        if roe is None:
            # 默认值
            roe = 0.10
        
        use_historical = kwargs.get("use_historical", True)
        
        if use_historical and self._historical_pb:
            # 使用历史分位数
            pb_low, pb_high = self._get_historical_pb_range()
            # 中值使用理论PB和历史中位数的加权平均
            theoretical_pb = self._calculate_theoretical_pb(roe)
            historical_mid = (pb_low + pb_high) / 2
            pb_mid = (theoretical_pb + historical_mid) / 2
        else:
            # 使用理论PB-ROE模型
            theoretical_pb = self._calculate_theoretical_pb(roe)
            # 根据ROE质量调整区间
            if roe >= 0.15:
                # 高ROE，给予溢价
                pb_low = theoretical_pb * 0.8
                pb_high = theoretical_pb * 1.3
            elif roe >= 0.10:
                # 中等ROE
                pb_low = theoretical_pb * 0.7
                pb_high = theoretical_pb * 1.2
            else:
                # 低ROE
                pb_low = theoretical_pb * 0.6
                pb_high = theoretical_pb * 1.1
            
            pb_mid = theoretical_pb
        
        # 确保区间合理性
        pb_low = max(0.3, pb_low)
        pb_high = max(pb_low * 1.2, pb_high)
        pb_mid = max(pb_low, min(pb_high, pb_mid))
        
        return pb_low, pb_mid, pb_high
    
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
            List[ValuationResult]: 估值结果列表（PB和PE两种方法）
        """
        results = []
        
        # 验证输入
        if not self.validate_input(input_data):
            return results
        
        # 计算ROE
        roe = self._calculate_roe(input_data)
        if roe is None:
            roe = 0.10
        
        # 获取每股净资产
        bvps = input_data.get_book_value_per_share()
        if bvps is None:
            return results
        
        # 当前PB
        current_pb = input_data.get_current_pb()
        if current_pb is None:
            current_pb = input_data.price / bvps
        
        # ===== 1. PB-ROE估值 =====
        pb_low, pb_mid, pb_high = self.get_fair_value_range(input_data, **kwargs)
        
        # 计算隐含股价
        implied_price_low = bvps * pb_low
        implied_price_mid = bvps * pb_mid
        implied_price_high = bvps * pb_high
        
        # 计算风险收益
        upside, downside = self._calculate_upside_downside(
            input_data.price,
            implied_price_low,
            implied_price_mid,
            implied_price_high
        )
        
        # 计算置信度（基于数据完整性和ROE稳定性）
        confidence = self._calculate_confidence(input_data, roe)
        
        # 警告信息
        warnings = []
        if roe < 0.05:
            warnings.append("ROE过低（<5%），估值可能不准确")
        if current_pb > 3.0:
            warnings.append("当前PB过高（>3倍），注意估值风险")
        if not self._historical_pb:
            warnings.append("缺少历史PB数据，使用理论模型估值")
        
        pb_result = ValuationResult(
            method=ValuationMethod.PB,
            stock_code=input_data.stock_code,
            current_value=current_pb,
            fair_value_low=pb_low,
            fair_value_mid=pb_mid,
            fair_value_high=pb_high,
            implied_price_low=implied_price_low,
            implied_price_mid=implied_price_mid,
            implied_price_high=implied_price_high,
            upside_potential=upside,
            downside_risk=downside,
            confidence=confidence,
            assumptions={
                "required_return": self.required_return,
                "roe": roe,
                "book_value_per_share": bvps,
                "pb_percentile_low": self.pb_percentile_low,
                "pb_percentile_high": self.pb_percentile_high,
                "methodology": "PB-ROE模型",
            },
            warnings=warnings,
            calculation_date=date.today(),
        )
        results.append(pb_result)
        
        # ===== 2. PE估值（辅助方法）=====
        eps = input_data.get_eps()
        if eps is not None and eps > 0:
            current_pe = input_data.get_current_pe()
            if current_pe is None:
                current_pe = input_data.price / eps
            
            # 根据ROE确定PE区间
            if roe >= 0.15:
                pe_low, pe_high = 10.0, 20.0
            elif roe >= 0.10:
                pe_low, pe_high = 6.0, 12.0
            else:
                pe_low, pe_high = 4.0, 8.0
            
            pe_mid = (pe_low + pe_high) / 2
            
            # 计算隐含股价
            pe_implied_low = eps * pe_low
            pe_implied_mid = eps * pe_mid
            pe_implied_high = eps * pe_high
            
            # 计算风险收益
            pe_upside, pe_downside = self._calculate_upside_downside(
                input_data.price,
                pe_implied_low,
                pe_implied_mid,
                pe_implied_high
            )
            
            pe_warnings = []
            if current_pe > 30:
                pe_warnings.append("当前PE过高（>30倍），注意估值风险")
            
            pe_result = ValuationResult(
                method=ValuationMethod.PE,
                stock_code=input_data.stock_code,
                current_value=current_pe,
                fair_value_low=pe_low,
                fair_value_mid=pe_mid,
                fair_value_high=pe_high,
                implied_price_low=pe_implied_low,
                implied_price_mid=pe_implied_mid,
                implied_price_high=pe_implied_high,
                upside_potential=pe_upside,
                downside_risk=pe_downside,
                confidence=confidence * 0.8,  # PE置信度略低
                assumptions={
                    "eps": eps,
                    "roe": roe,
                    "methodology": "PE估值法（辅助）",
                },
                warnings=pe_warnings,
                calculation_date=date.today(),
            )
            results.append(pe_result)
        
        return results
    
    def _calculate_confidence(
        self,
        input_data: ValuationInput,
        roe: float
    ) -> float:
        """
        计算估值置信度
        
        Args:
            input_data: 估值输入数据
            roe: ROE值
            
        Returns:
            float: 置信度(0-1)
        """
        confidence = 0.7  # 基础置信度
        
        # 数据完整性加分
        if input_data.net_profit is not None:
            confidence += 0.05
        if input_data.operating_profit is not None:
            confidence += 0.05
        if self._historical_pb is not None:
            confidence += 0.1
        if self._historical_roe is not None:
            confidence += 0.05
        
        # ROE合理性调整
        if 0.08 <= roe <= 0.20:
            confidence += 0.05
        elif roe < 0.02 or roe > 0.30:
            confidence -= 0.1
        
        return max(0.0, min(1.0, confidence))


# 便捷函数
def value_financial_stock(
    stock_code: str,
    price: float,
    total_shares: float,
    market_cap: float,
    shareholders_equity: float,
    net_profit: Optional[float] = None,
    roe: Optional[float] = None,
    historical_pb: Optional[List[float]] = None,
    **kwargs
) -> List[ValuationResult]:
    """
    便捷函数：对金融股票进行估值
    
    Args:
        stock_code: 股票代码
        price: 当前股价
        total_shares: 总股本
        market_cap: 总市值
        shareholders_equity: 股东权益
        net_profit: 净利润（可选）
        roe: ROE（可选，优先使用）
        historical_pb: 历史PB数据（可选）
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
        shareholders_equity=shareholders_equity,
        extra_data={"roe": roe} if roe else {},
    )
    
    model = FinancialValuationModel(**kwargs)
    if historical_pb:
        model.set_historical_data(historical_pb=historical_pb)
    
    return model.calculate(input_data)
