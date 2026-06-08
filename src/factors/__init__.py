"""
因子计算模块
============

实现WorldQuant 101、国泰君安191和基本面因子库。

因子分类体系：
- 技术指标类：K线形态、成交量异常、VWAP偏离、动量类、均值回复、波动率类、相关性类、情绪类、突破类
- 基本面类：估值因子、盈利因子、成长因子、质量因子

新增：策略级因子服务（FactorService）
- 统一因子获取接口，支持多数据源切换
- 按日获取因子值，适合策略内调用
"""

from .calculator import FactorCalculator
from .worldquant import WorldQuantFactors
from .guotai import GuotaiFactors
from .fundamental import FundamentalFactors
from .selector import FactorSelector
from .backtest import Backtester
from .report_generator import BacktestReportGenerator, generate_backtest_report
from .categories import (
    FactorCategory,
    CATEGORY_NAMES,
    CATEGORY_DESCRIPTIONS,
    WQ_FACTOR_META,
    GTJ_FACTOR_META,
    FUNDAMENTAL_FACTOR_META,
    ALL_FACTOR_META,
    get_factor_category,
    get_factor_name,
    get_factor_description,
    get_factors_by_category,
    get_category_factors_dict,
    print_factor_categories,
)

# 新增：策略级因子服务
from .factor_service import FactorService
from .factor_registry import (
    register_factor,
    get_factor_info,
    list_factors,
    is_factor_supported,
    FactorCategory as FR_FactorCategory,
    FactorSource,
)
from .factor_provider import (
    FactorProvider,
    EastmoneyFactorProvider,
    DatabaseFactorProvider,
)

__all__ = [
    # 核心类
    "FactorCalculator",
    "WorldQuantFactors",
    "GuotaiFactors",
    "FundamentalFactors",
    "FactorSelector",
    "Backtester",
    # 报告生成
    "BacktestReportGenerator",
    "generate_backtest_report",
    # 分类系统
    "FactorCategory",
    "CATEGORY_NAMES",
    "CATEGORY_DESCRIPTIONS",
    "WQ_FACTOR_META",
    "GTJ_FACTOR_META",
    "FUNDAMENTAL_FACTOR_META",
    "ALL_FACTOR_META",
    # 工具函数
    "get_factor_category",
    "get_factor_name",
    "get_factor_description",
    "get_factors_by_category",
    "get_category_factors_dict",
    "print_factor_categories",
    # 新增：策略级因子服务
    "FactorService",
    "register_factor",
    "get_factor_info",
    "list_factors",
    "is_factor_supported",
    "FactorProvider",
    "EastmoneyFactorProvider",
    "DatabaseFactorProvider",
]
