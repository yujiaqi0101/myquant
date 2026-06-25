"""
因子注册表
==========

提供运行时因子元数据注册和查询功能。

设计原则：
- 集中管理因子元数据（名称、分类、数据源、排名方向）
- 支持运行时动态注册新因子
- 与 categories.py 静态元数据互补
"""

from typing import Dict, List, Optional, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class FactorCategory(Enum):
    """因子分类枚举"""
    VALUATION = "valuation"           # 估值因子
    PROFITABILITY = "profitability"   # 盈利因子
    GROWTH = "growth"                 # 成长因子
    QUALITY = "quality"               # 质量因子
    TECHNICAL = "technical"           # 技术因子


class FactorSource(Enum):
    """因子数据来源枚举"""
    VALUATION = "valuation"           # 估值接口（stk_get_daily_valuation）
    FINANCIAL = "financial"           # 财务衍生接口（stk_get_finance_deriv_pt）
    MKTVALUE = "mktvalue"             # 市值接口（stk_get_daily_mktvalue）


# 因子元数据注册表
# key: factor_name (小写)
# value: 元数据字典
FACTOR_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ========== 估值因子 ==========
    'pb': {
        'name': '市净率',
        'source': FactorSource.VALUATION,
        'field': 'pb_mrq',
        'category': FactorCategory.VALUATION,
        'description': '市净率（MRQ），股价/每股净资产，越低越好',
        'default_ascending': True,
        'data_sources': ['eastmoney', 'database'],  # 支持的数据源
    },
    'pe_ttm': {
        'name': '市盈率TTM',
        'source': FactorSource.VALUATION,
        'field': 'pe_ttm',
        'category': FactorCategory.VALUATION,
        'description': '市盈率（TTM），总市值/净利润（过去12个月），越低越好',
        'default_ascending': True,
        'data_sources': ['eastmoney'],
    },
    'ps_ttm': {
        'name': '市销率TTM',
        'source': FactorSource.VALUATION,
        'field': 'ps_ttm',
        'category': FactorCategory.VALUATION,
        'description': '市销率（TTM），总市值/营业收入（过去12个月），越低越好',
        'default_ascending': True,
        'data_sources': ['eastmoney'],
    },
    'pcf_ttm': {
        'name': '市现率TTM',
        'source': FactorSource.VALUATION,
        'field': 'pcf_ttm',
        'category': FactorCategory.VALUATION,
        'description': '市现率（TTM），总市值/经营现金流（过去12个月），越低越好',
        'default_ascending': True,
        'data_sources': ['eastmoney'],
    },

    # ========== 盈利因子 ==========
    'roe': {
        'name': '净资产收益率',
        'source': FactorSource.FINANCIAL,
        'field': 'roe',
        'category': FactorCategory.PROFITABILITY,
        'description': '净资产收益率，净利润/净资产，越高越好',
        'default_ascending': False,
        'data_sources': ['eastmoney', 'database'],
    },
    'roe_weight': {
        'name': '加权净资产收益率',
        'source': FactorSource.FINANCIAL,
        'field': 'roe_weight',
        'category': FactorCategory.PROFITABILITY,
        'description': '加权平均净资产收益率，越高越好',
        'default_ascending': False,
        'data_sources': ['eastmoney'],
    },
    'roa': {
        'name': '总资产收益率',
        'source': FactorSource.FINANCIAL,
        'field': 'roa',
        'category': FactorCategory.PROFITABILITY,
        'description': '总资产收益率，净利润/总资产，越高越好',
        'default_ascending': False,
        'data_sources': ['eastmoney'],
    },
    'gross_margin': {
        'name': '毛利率',
        'source': FactorSource.FINANCIAL,
        'field': 'gross_margin',
        'category': FactorCategory.PROFITABILITY,
        'description': '销售毛利率，（营业收入-营业成本）/营业收入，越高越好',
        'default_ascending': False,
        'data_sources': ['eastmoney'],
    },
    'net_margin': {
        'name': '净利率',
        'source': FactorSource.FINANCIAL,
        'field': 'net_margin',
        'category': FactorCategory.PROFITABILITY,
        'description': '销售净利率，净利润/营业收入，越高越好',
        'default_ascending': False,
        'data_sources': ['eastmoney'],
    },

    # ========== 成长因子 ==========
    'np_growth_q': {
        'name': '净利润季度增长率',
        'source': FactorSource.FINANCIAL,
        'field': 'net_prof_yoy',
        'category': FactorCategory.GROWTH,
        'description': '净利润同比增长率，越高越好',
        'default_ascending': False,
        'data_sources': ['eastmoney'],
    },
    'revenue_growth_q': {
        'name': '营收季度增长率',
        'source': FactorSource.FINANCIAL,
        'field': 'inc_oper_yoy',
        'category': FactorCategory.GROWTH,
        'description': '营业收入同比增长率，越高越好',
        'default_ascending': False,
        'data_sources': ['eastmoney'],
    },

    # ========== 估值因子（扩展） ==========
    'circ_mv': {
        'name': '流通市值',
        'source': FactorSource.MKTVALUE,
        'field': 'a_mv',
        'category': FactorCategory.VALUATION,
        'description': 'A股流通市值，单位：元，越小越好',
        'default_ascending': True,
        'data_sources': ['eastmoney'],
    },

    # ========== 质量因子 ==========
    'debt_ratio': {
        'name': '资产负债率',
        'source': FactorSource.FINANCIAL,
        'field': 'debt_ratio',
        'category': FactorCategory.QUALITY,
        'description': '资产负债率，总负债/总资产，越低越好',
        'default_ascending': True,
        'data_sources': ['eastmoney'],
    },
    'current_ratio': {
        'name': '流动比率',
        'source': FactorSource.FINANCIAL,
        'field': 'current_ratio',
        'category': FactorCategory.QUALITY,
        'description': '流动比率，流动资产/流动负债，越高越好',
        'default_ascending': False,
        'data_sources': ['eastmoney'],
    },
}


def register_factor(
    name: str,
    field: str,
    source: FactorSource,
    category: FactorCategory,
    description: str,
    default_ascending: bool = True,
    data_sources: List[str] = None,
) -> None:
    """
    注册新因子

    Parameters
    ----------
    name : str
        因子名称（英文标识，如 'pb', 'roe'）
    field : str
        API字段名（如 'pb_mrq', 'roe'）
    source : FactorSource
        数据来源（VALUATION / FINANCIAL）
    category : FactorCategory
        因子分类
    description : str
        因子描述
    default_ascending : bool
        默认排名方向，True=升序(越小越好)，False=降序(越大越好)
    data_sources : List[str]
        支持的数据源列表，如 ['eastmoney', 'database']

    Example
    -------
    >>> from src.factors.factor_registry import register_factor, FactorSource, FactorCategory
    >>> register_factor(
    ...     name='custom_factor',
    ...     field='custom_field',
    ...     source=FactorSource.VALUATION,
    ...     category=FactorCategory.VALUATION,
    ...     description='自定义因子',
    ...     default_ascending=True,
    ...     data_sources=['eastmoney'],
    ... )
    """
    name = name.lower()
    if name in FACTOR_REGISTRY:
        logger.warning(f"因子 '{name}' 已存在，将被覆盖")

    FACTOR_REGISTRY[name] = {
        'name': name,
        'field': field,
        'source': source,
        'category': category,
        'description': description,
        'default_ascending': default_ascending,
        'data_sources': data_sources or ['eastmoney'],
    }
    logger.info(f"因子 '{name}' 注册成功")


def get_factor_info(name: str) -> Optional[Dict[str, Any]]:
    """
    获取因子元数据

    Parameters
    ----------
    name : str
        因子名称

    Returns
    -------
    Dict[str, Any] or None
        因子元数据字典，不存在则返回 None
    """
    return FACTOR_REGISTRY.get(name.lower())


def list_factors(
    category: Optional[FactorCategory] = None,
    data_source: Optional[str] = None,
) -> List[str]:
    """
    列出已注册因子

    Parameters
    ----------
    category : FactorCategory, optional
        按分类筛选
    data_source : str, optional
        按支持的数据源筛选，如 'eastmoney', 'database'

    Returns
    -------
    List[str]
        因子名称列表
    """
    result = []
    for name, meta in FACTOR_REGISTRY.items():
        if category and meta['category'] != category:
            continue
        if data_source and data_source not in meta.get('data_sources', []):
            continue
        result.append(name)
    return sorted(result)


def get_factors_by_category(category: FactorCategory) -> Dict[str, List[str]]:
    """
    按分类获取因子列表

    Returns
    -------
    Dict[str, List[str]]
        {category_name: [factor_names]}
    """
    result = {}
    for cat in FactorCategory:
        result[cat.value] = list_factors(category=cat)
    return result


def is_factor_supported(name: str, data_source: str) -> bool:
    """
    检查因子是否支持指定数据源

    Parameters
    ----------
    name : str
        因子名称
    data_source : str
        数据源名称

    Returns
    -------
    bool
        是否支持
    """
    info = get_factor_info(name)
    if not info:
        return False
    return data_source in info.get('data_sources', [])


def print_factor_list():
    """打印所有已注册因子列表（用于调试）"""
    print("=" * 80)
    print("已注册因子列表")
    print("=" * 80)

    for cat in FactorCategory:
        factors = list_factors(category=cat)
        if factors:
            print(f"\n【{cat.value}】")
            for name in factors:
                info = get_factor_info(name)
                direction = "↑" if info['default_ascending'] else "↓"
                sources = ", ".join(info.get('data_sources', []))
                print(f"  - {name:15} {direction}  ({sources})")
                print(f"    {info['description']}")

    print("\n" + "=" * 80)


# 初始化时打印因子列表（可选）
if __name__ == '__main__':
    print_factor_list()
