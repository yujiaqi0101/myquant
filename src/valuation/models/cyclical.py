"""
周期行业估值模型

适用行业：煤炭、钢铁、化工、有色金属、石油石化
主要方法：PB、EV/EBITDA
特点：使用正常化盈利处理周期性，周期底部PB更安全
合理PB区间：0.8-1.5倍
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


class CyclicalValuationModel(ValuationModel):
    """
    周期行业估值模型
    
    适用于煤炭、钢铁、化工、有色金属、石油石化等强周期行业。
    周期行业盈利波动大，不适合单纯使用PE估值，
    应使用PB、EV/EBITDA等基于资产或现金流的估值方法。
    
    Attributes:
        pb_low: PB下限（默认0.8倍）
        pb_high: PB上限（默认1.5倍）
        ev_ebitda_low: EV/EBITDA下限（默认4倍）
        ev_ebitda_high: EV/EBITDA上限（默认8倍）
        normalization_years: 正常化盈利计算年数（默认5年）
    """
    
    # 适用行业列表
    APPLICABLE_INDUSTRIES = [
        "煤炭", "钢铁", "化工", "有色金属", "石油石化",
        "煤炭开采", "焦炭", "普钢", "特钢", "基础化工",
        "石油化工", "化学纤维", "塑料", "橡胶", "农化制品",
        "化学原料", "化学制品", "贵金属", "工业金属", "能源金属",
        "小金属", "油气开采", "油服工程", "炼化贸易"
    ]
    
    def __init__(
        self,
        pb_low: float = 0.8,
        pb_high: float = 1.5,
        ev_ebitda_low: float = 4.0,
        ev_ebitda_high: float = 8.0,
        normalization_years: int = 5,
    ):
        """
        初始化周期行业估值模型
        
        Args:
            pb_low: PB下限（默认0.8倍）
            pb_high: PB上限（默认1.5倍）
            ev_ebitda_low: EV/EBITDA下限（默认4倍）
            ev_ebitda_high: EV/EBITDA上限（默认8倍）
            normalization_years: 正常化盈利计算年数（默认5年）
        """
        super().__init__(ValuationMethod.PB)
        self.pb_low = pb_low
        self.pb_high = pb_high
        self.ev_ebitda_low = ev_ebitda_low
        self.ev_ebitda_high = ev_ebitda_high
        self.normalization_years = normalization_years
        
        # 历史数据存储
        self._historical_profits: Optional[List[float]] = None
        self._historical_ebitda: Optional[List[float]] = None
        self._historical_pb: Optional[List[float]] = None
    
    def set_historical_data(
        self,
        historical_profits: Optional[List[float]] = None,
        historical_ebitda: Optional[List[float]] = None,
        historical_pb: Optional[List[float]] = None,
    ):
        """
        设置历史数据用于正常化计算
        
        Args:
            historical_profits: 历史净利润数据
            historical_ebitda: 历史EBITDA数据
            historical_pb: 历史PB数据
        """
        self._historical_profits = historical_profits
        self._historical_ebitda = historical_ebitda
        self._historical_pb = historical_pb
    
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
        
        # PB估值需要股东权益
        valid &= self._check_not_none(input_data.shareholders_equity, "股东权益")
        valid &= self._check_positive(input_data.shareholders_equity, "股东权益")
        
        return valid
    
    def _calculate_normalized_profit(self, input_data: ValuationInput) -> Optional[float]:
        """
        计算正常化盈利（平滑周期性）
        
        使用历史盈利的平均值来平滑周期波动
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            Optional[float]: 正常化盈利
        """
        profits = []
        
        # 加入当前盈利
        if input_data.net_profit is not None:
            profits.append(input_data.net_profit)
        
        # 加入历史盈利
        if self._historical_profits:
            profits.extend(self._historical_profits)
        
        if len(profits) == 0:
            return None
        
        # 使用中位数（对异常值更稳健）
        sorted_profits = sorted(profits)
        n = len(sorted_profits)
        
        if n % 2 == 0:
            normalized = (sorted_profits[n//2 - 1] + sorted_profits[n//2]) / 2
        else:
            normalized = sorted_profits[n//2]
        
        return normalized
    
    def _calculate_normalized_ebitda(self, input_data: ValuationInput) -> Optional[float]:
        """
        计算正常化EBITDA
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            Optional[float]: 正常化EBITDA
        """
        ebitdas = []
        
        # 加入当前EBITDA
        if input_data.ebitda is not None:
            ebitdas.append(input_data.ebitda)
        
        # 加入历史EBITDA
        if self._historical_ebitda:
            ebitdas.extend(self._historical_ebitda)
        
        if len(ebitdas) == 0:
            return None
        
        # 使用中位数
        sorted_ebitdas = sorted(ebitdas)
        n = len(sorted_ebitdas)
        
        if n % 2 == 0:
            normalized = (sorted_ebitdas[n//2 - 1] + sorted_ebitdas[n//2]) / 2
        else:
            normalized = sorted_ebitdas[n//2]
        
        return normalized
    
    def _detect_cycle_phase(self) -> str:
        """
        检测周期阶段
        
        基于历史数据判断当前处于周期的哪个阶段
        
        Returns:
            str: 周期阶段（"peak"/"trough"/"normal"）
        """
        if not self._historical_profits or len(self._historical_profits) < 3:
            return "unknown"
        
        # 简单判断：如果最近盈利远高于历史平均，可能是顶部
        recent = self._historical_profits[-1] if self._historical_profits else 0
        historical_avg = sum(self._historical_profits) / len(self._historical_profits)
        
        if recent > historical_avg * 1.5:
            return "peak"
        elif recent < historical_avg * 0.5:
            return "trough"
        else:
            return "normal"
    
    def get_fair_value_range(
        self,
        input_data: ValuationInput,
        **kwargs
    ) -> Tuple[float, float, float]:
        """
        获取公允价值区间（PB区间）
        
        Args:
            input_data: 估值输入数据
            **kwargs: 额外参数
                - cycle_phase: 周期阶段覆盖
                - asset_quality: 资产质量系数（0.8-1.2）
                
        Returns:
            Tuple[float, float, float]: (PB下限, PB中值, PB上限)
        """
        cycle_phase = kwargs.get("cycle_phase", self._detect_cycle_phase())
        asset_quality = kwargs.get("asset_quality", 1.0)
        
        # 根据周期阶段调整PB区间
        if cycle_phase == "peak":
            # 周期顶部，使用保守PB
            pb_low = self.pb_low * 0.9
            pb_high = self.pb_low * 1.3
        elif cycle_phase == "trough":
            # 周期底部，PB更安全，可以给予一定溢价
            pb_low = self.pb_low
            pb_high = self.pb_high * 1.1
        else:
            # 正常周期
            pb_low = self.pb_low
            pb_high = self.pb_high
        
        # 应用资产质量调整
        pb_low *= asset_quality
        pb_high *= asset_quality
        
        # 中值
        pb_mid = (pb_low + pb_high) / 2
        
        # 确保区间合理性
        pb_low = max(0.5, pb_low)
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
            List[ValuationResult]: 估值结果列表
        """
        results = []
        
        # 验证输入
        if not self.validate_input(input_data):
            return results
        
        # 获取每股净资产
        bvps = input_data.get_book_value_per_share()
        if bvps is None:
            return results
        
        # 当前PB
        current_pb = input_data.get_current_pb()
        if current_pb is None:
            current_pb = input_data.price / bvps
        
        # 检测周期阶段
        cycle_phase = self._detect_cycle_phase()
        
        # ===== 1. PB估值 =====
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
        
        # 计算置信度
        confidence = self._calculate_confidence(input_data, cycle_phase)
        
        # 警告信息
        warnings = []
        if cycle_phase == "peak":
            warnings.append("当前可能处于周期顶部，盈利可能不可持续")
        if current_pb > 2.0:
            warnings.append("当前PB过高（>2倍），注意估值风险")
        if not self._historical_profits:
            warnings.append("缺少历史盈利数据，无法进行正常化调整")
        
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
                "book_value_per_share": bvps,
                "cycle_phase": cycle_phase,
                "pb_range": f"{pb_low:.2f}-{pb_high:.2f}",
                "methodology": "PB估值法（周期行业）",
            },
            warnings=warnings,
            calculation_date=date.today(),
        )
        results.append(pb_result)
        
        # ===== 2. EV/EBITDA估值 =====
        normalized_ebitda = self._calculate_normalized_ebitda(input_data)
        if normalized_ebitda is not None and normalized_ebitda > 0:
            ev = input_data.get_enterprise_value()
            if ev is not None and ev > 0:
                current_ev_ebitda = ev / normalized_ebitda
                
                # 根据周期阶段调整EV/EBITDA区间
                if cycle_phase == "peak":
                    ev_ebitda_low, ev_ebitda_high = 3.0, 6.0
                elif cycle_phase == "trough":
                    ev_ebitda_low, ev_ebitda_high = 5.0, 10.0
                else:
                    ev_ebitda_low, ev_ebitda_high = self.ev_ebitda_low, self.ev_ebitda_high
                
                ev_ebitda_mid = (ev_ebitda_low + ev_ebitda_high) / 2
                
                # 计算隐含企业价值
                ev_implied_low = normalized_ebitda * ev_ebitda_low
                ev_implied_mid = normalized_ebitda * ev_ebitda_mid
                ev_implied_high = normalized_ebitda * ev_ebitda_high
                
                # 转换为股权价值（减去净负债）
                net_debt = input_data.net_debt if input_data.net_debt is not None else 0
                
                equity_implied_low = max(0, ev_implied_low - net_debt)
                equity_implied_mid = max(0, ev_implied_mid - net_debt)
                equity_implied_high = max(0, ev_implied_high - net_debt)
                
                # 转换为每股价格
                if input_data.total_shares > 0:
                    ebitda_implied_price_low = equity_implied_low / input_data.total_shares
                    ebitda_implied_price_mid = equity_implied_mid / input_data.total_shares
                    ebitda_implied_price_high = equity_implied_high / input_data.total_shares
                    
                    # 计算风险收益
                    ebitda_upside, ebitda_downside = self._calculate_upside_downside(
                        input_data.price,
                        ebitda_implied_price_low,
                        ebitda_implied_price_mid,
                        ebitda_implied_price_high
                    )
                    
                    ebitda_warnings = []
                    if current_ev_ebitda > 12:
                        ebitda_warnings.append("EV/EBITDA过高（>12倍），注意估值风险")
                    
                    ebitda_result = ValuationResult(
                        method=ValuationMethod.EV_EBITDA,
                        stock_code=input_data.stock_code,
                        current_value=current_ev_ebitda,
                        fair_value_low=ev_ebitda_low,
                        fair_value_mid=ev_ebitda_mid,
                        fair_value_high=ev_ebitda_high,
                        implied_price_low=ebitda_implied_price_low,
                        implied_price_mid=ebitda_implied_price_mid,
                        implied_price_high=ebitda_implied_price_high,
                        upside_potential=ebitda_upside,
                        downside_risk=ebitda_downside,
                        confidence=confidence * 0.85,
                        assumptions={
                            "normalized_ebitda": normalized_ebitda,
                            "enterprise_value": ev,
                            "net_debt": net_debt,
                            "cycle_phase": cycle_phase,
                            "methodology": "EV/EBITDA估值法",
                        },
                        warnings=ebitda_warnings,
                        calculation_date=date.today(),
                    )
                    results.append(ebitda_result)
        
        return results
    
    def _calculate_confidence(
        self,
        input_data: ValuationInput,
        cycle_phase: str
    ) -> float:
        """
        计算估值置信度
        
        Args:
            input_data: 估值输入数据
            cycle_phase: 周期阶段
            
        Returns:
            float: 置信度(0-1)
        """
        confidence = 0.65  # 周期行业基础置信度较低
        
        # 历史数据完整性
        if self._historical_profits and len(self._historical_profits) >= 5:
            confidence += 0.15
        elif self._historical_profits and len(self._historical_profits) >= 3:
            confidence += 0.08
        
        if self._historical_ebitda and len(self._historical_ebitda) >= 3:
            confidence += 0.05
        
        # 周期阶段判断
        if cycle_phase != "unknown":
            confidence += 0.05
        
        # 数据质量
        if input_data.ebitda is not None:
            confidence += 0.05
        if input_data.net_debt is not None:
            confidence += 0.05
        
        return max(0.0, min(1.0, confidence))


# 便捷函数
def value_cyclical_stock(
    stock_code: str,
    price: float,
    total_shares: float,
    market_cap: float,
    shareholders_equity: float,
    net_profit: Optional[float] = None,
    ebitda: Optional[float] = None,
    net_debt: Optional[float] = None,
    historical_profits: Optional[List[float]] = None,
    historical_ebitda: Optional[List[float]] = None,
    **kwargs
) -> List[ValuationResult]:
    """
    便捷函数：对周期行业股票进行估值
    
    Args:
        stock_code: 股票代码
        price: 当前股价
        total_shares: 总股本
        market_cap: 总市值
        shareholders_equity: 股东权益
        net_profit: 净利润（可选）
        ebitda: EBITDA（可选）
        net_debt: 净债务（可选）
        historical_profits: 历史净利润（可选）
        historical_ebitda: 历史EBITDA（可选）
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
        ebitda=ebitda,
        net_debt=net_debt,
    )
    
    model = CyclicalValuationModel(**kwargs)
    model.set_historical_data(
        historical_profits=historical_profits,
        historical_ebitda=historical_ebitda,
    )
    
    return model.calculate(input_data)
