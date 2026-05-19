"""
估值模型基础模块

定义估值方法枚举、输入输出数据类和抽象基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple, Any
import math


class ValuationMethod(Enum):
    """估值方法枚举"""
    PE = auto()          # 市盈率法 (Price-to-Earnings)
    PB = auto()          # 市净率法 (Price-to-Book)
    PS = auto()          # 市销率法 (Price-to-Sales)
    PEG = auto()         # PEG比率法 (PE-to-Growth)
    EV_EBITDA = auto()   # 企业价值倍数法 (EV/EBITDA)
    DCF = auto()         # 现金流折现法 (Discounted Cash Flow)
    NAV = auto()         # 净资产价值法 (Net Asset Value)

    def __str__(self) -> str:
        method_names = {
            ValuationMethod.PE: "市盈率法(PE)",
            ValuationMethod.PB: "市净率法(PB)",
            ValuationMethod.PS: "市销率法(PS)",
            ValuationMethod.PEG: "PEG比率法",
            ValuationMethod.EV_EBITDA: "EV/EBITDA倍数法",
            ValuationMethod.DCF: "现金流折现法(DCF)",
            ValuationMethod.NAV: "净资产价值法(NAV)",
        }
        return method_names.get(self, self.name)


@dataclass
class ValuationInput:
    """
    估值输入数据类
    
    包含进行估值计算所需的所有财务和市场数据
    """
    # 基础信息
    stock_code: str                          # 股票代码
    report_date: date                        # 报告日期
    total_shares: float                      # 总股本
    price: float                             # 当前股价
    market_cap: float                        # 总市值
    
    # 利润表数据
    revenue: Optional[float] = None          # 营业收入
    net_profit: Optional[float] = None       # 净利润
    operating_profit: Optional[float] = None # 营业利润
    ebitda: Optional[float] = None           # 息税折旧摊销前利润
    
    # 资产负债表数据
    total_assets: Optional[float] = None     # 总资产
    total_liabilities: Optional[float] = None # 总负债
    shareholders_equity: Optional[float] = None # 股东权益
    net_debt: Optional[float] = None         # 净债务
    
    # 现金流量表数据
    operating_cash_flow: Optional[float] = None # 经营活动现金流
    free_cash_flow: Optional[float] = None   # 自由现金流
    
    # 扩展字段（用于特定估值方法）
    extra_data: Dict[str, Any] = field(default_factory=dict)
    
    def get_enterprise_value(self) -> Optional[float]:
        """计算企业价值 (EV = 市值 + 净债务)"""
        if self.net_debt is None:
            return None
        return self.market_cap + self.net_debt
    
    def get_book_value_per_share(self) -> Optional[float]:
        """计算每股净资产"""
        if self.shareholders_equity is None or self.total_shares <= 0:
            return None
        return self.shareholders_equity / self.total_shares
    
    def get_eps(self) -> Optional[float]:
        """计算每股收益"""
        if self.net_profit is None or self.total_shares <= 0:
            return None
        return self.net_profit / self.total_shares
    
    def get_revenue_per_share(self) -> Optional[float]:
        """计算每股营业收入"""
        if self.revenue is None or self.total_shares <= 0:
            return None
        return self.revenue / self.total_shares
    
    def get_current_pe(self) -> Optional[float]:
        """计算当前市盈率"""
        eps = self.get_eps()
        if eps is None or eps == 0:
            return None
        return self.price / eps
    
    def get_current_pb(self) -> Optional[float]:
        """计算当前市净率"""
        bvps = self.get_book_value_per_share()
        if bvps is None or bvps == 0:
            return None
        return self.price / bvps
    
    def get_current_ps(self) -> Optional[float]:
        """计算当前市销率"""
        rps = self.get_revenue_per_share()
        if rps is None or rps == 0:
            return None
        return self.price / rps


@dataclass
class ValuationResult:
    """
    估值结果数据类
    
    包含估值计算的结果和相关信息
    """
    # 基本信息
    method: ValuationMethod                  # 估值方法
    stock_code: str                          # 股票代码
    
    # 当前价值
    current_value: float                     # 当前价值（如当前PE、PB等）
    
    # 公允价值区间
    fair_value_low: float                    # 公允价值下限
    fair_value_mid: float                    # 公允价值中值
    fair_value_high: float                   # 公允价值上限
    
    # 隐含股价区间
    implied_price_low: float                 # 隐含股价下限
    implied_price_mid: float                 # 隐含股价中值
    implied_price_high: float                # 隐含股价上限
    
    # 风险收益评估
    upside_potential: float                  # 上涨潜力（百分比）
    downside_risk: float                     # 下跌风险（百分比）
    
    # 置信度
    confidence: float                        # 置信度 (0-1)
    
    # 假设条件
    assumptions: Dict[str, Any] = field(default_factory=dict)
    
    # 警告信息
    warnings: List[str] = field(default_factory=list)
    
    # 计算时间戳
    calculation_date: date = field(default_factory=date.today)
    
    def __post_init__(self):
        """初始化后的验证"""
        # 确保置信度在0-1范围内
        self.confidence = max(0.0, min(1.0, self.confidence))
    
    def get_recommendation(self) -> str:
        """
        根据估值结果生成投资建议
        
        Returns:
            str: 投资建议（买入/持有/卖出）
        """
        if self.upside_potential > 20:
            return "买入"
        elif self.upside_potential > 5:
            return "增持"
        elif self.downside_risk > 20:
            return "卖出"
        elif self.downside_risk > 5:
            return "减持"
        else:
            return "持有"
    
    def is_undervalued(self) -> bool:
        """判断是否被低估"""
        return self.implied_price_mid > self.current_value * 1.1
    
    def is_overvalued(self) -> bool:
        """判断是否被高估"""
        return self.implied_price_mid < self.current_value * 0.9
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "method": str(self.method),
            "stock_code": self.stock_code,
            "current_value": self.current_value,
            "fair_value_low": self.fair_value_low,
            "fair_value_mid": self.fair_value_mid,
            "fair_value_high": self.fair_value_high,
            "implied_price_low": self.implied_price_low,
            "implied_price_mid": self.implied_price_mid,
            "implied_price_high": self.implied_price_high,
            "upside_potential": self.upside_potential,
            "downside_risk": self.downside_risk,
            "confidence": self.confidence,
            "recommendation": self.get_recommendation(),
            "is_undervalued": self.is_undervalued(),
            "is_overvalued": self.is_overvalued(),
            "assumptions": self.assumptions,
            "warnings": self.warnings,
            "calculation_date": self.calculation_date.isoformat(),
        }


class ValuationModel(ABC):
    """
    估值模型抽象基类
    
    所有具体估值方法都需要继承此类并实现抽象方法
    """
    
    def __init__(self, method: ValuationMethod):
        """
        初始化估值模型
        
        Args:
            method: 估值方法类型
        """
        self.method = method
        self._validation_errors: List[str] = []
    
    @abstractmethod
    def calculate(self, input_data: ValuationInput, 
                  **kwargs) -> ValuationResult:
        """
        执行估值计算
        
        Args:
            input_data: 估值输入数据
            **kwargs: 额外的计算参数
            
        Returns:
            ValuationResult: 估值结果
        """
        pass
    
    @abstractmethod
    def get_fair_value_range(self, input_data: ValuationInput,
                             **kwargs) -> Tuple[float, float, float]:
        """
        获取公允价值区间
        
        Args:
            input_data: 估值输入数据
            **kwargs: 额外的计算参数
            
        Returns:
            Tuple[float, float, float]: (下限, 中值, 上限)
        """
        pass
    
    @abstractmethod
    def validate_input(self, input_data: ValuationInput) -> bool:
        """
        验证输入数据是否满足估值计算要求
        
        Args:
            input_data: 估值输入数据
            
        Returns:
            bool: 验证是否通过
        """
        pass
    
    def get_validation_errors(self) -> List[str]:
        """获取验证错误信息"""
        return self._validation_errors.copy()
    
    def _add_validation_error(self, error: str):
        """添加验证错误信息"""
        self._validation_errors.append(error)
    
    def _clear_validation_errors(self):
        """清空验证错误信息"""
        self._validation_errors.clear()
    
    def _calculate_upside_downside(self, current_price: float,
                                   implied_low: float,
                                   implied_mid: float,
                                   implied_high: float) -> Tuple[float, float]:
        """
        计算上涨潜力和下跌风险
        
        Args:
            current_price: 当前股价
            implied_low: 隐含股价下限
            implied_mid: 隐含股价中值
            implied_high: 隐含股价上限
            
        Returns:
            Tuple[float, float]: (上涨潜力, 下跌风险) 百分比
        """
        if current_price <= 0:
            return 0.0, 0.0
        
        # 上涨潜力基于中值到上限的平均
        upside = ((implied_mid + implied_high) / 2 / current_price - 1) * 100
        
        # 下跌风险基于当前价到下限
        downside = (1 - implied_low / current_price) * 100
        
        return max(0, upside), max(0, downside)
    
    def _check_positive(self, value: Optional[float], name: str) -> bool:
        """检查值是否为正数"""
        if value is None:
            self._add_validation_error(f"{name}不能为空")
            return False
        if value <= 0:
            self._add_validation_error(f"{name}必须大于0")
            return False
        return True
    
    def _check_non_negative(self, value: Optional[float], name: str) -> bool:
        """检查值是否为非负数"""
        if value is None:
            self._add_validation_error(f"{name}不能为空")
            return False
        if value < 0:
            self._add_validation_error(f"{name}不能为负数")
            return False
        return True
    
    def _check_not_none(self, value: Optional[Any], name: str) -> bool:
        """检查值是否不为空"""
        if value is None:
            self._add_validation_error(f"{name}不能为空")
            return False
        return True


# 工具函数
def calculate_weighted_average(values: List[float], 
                                weights: List[float]) -> float:
    """
    计算加权平均值
    
    Args:
        values: 数值列表
        weights: 权重列表
        
    Returns:
        float: 加权平均值
    """
    if len(values) != len(weights) or len(values) == 0:
        return 0.0
    
    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    
    weighted_sum = sum(v * w for v, w in zip(values, weights))
    return weighted_sum / total_weight


def calculate_percentile(values: List[float], percentile: float) -> float:
    """
    计算百分位数
    
    Args:
        values: 数值列表
        percentile: 百分位 (0-100)
        
    Returns:
        float: 百分位数值
    """
    if not values:
        return 0.0
    
    sorted_values = sorted(values)
    n = len(sorted_values)
    
    if percentile <= 0:
        return sorted_values[0]
    if percentile >= 100:
        return sorted_values[-1]
    
    index = (percentile / 100) * (n - 1)
    lower = int(index)
    upper = lower + 1
    
    if upper >= n:
        return sorted_values[lower]
    
    fraction = index - lower
    return sorted_values[lower] + fraction * (sorted_values[upper] - sorted_values[lower])
