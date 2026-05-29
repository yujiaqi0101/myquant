"""
因子提供者抽象层
================

提供统一的因子数据获取接口，支持多数据源切换。

设计原则：
- 抽象基类 FactorProvider 定义统一接口
- 具体 Provider 实现对接不同数据源（东财掘金、本地数据库）
- 策略代码不感知底层 API，切换数据源零改动
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import logging
import pandas as pd

logger = logging.getLogger(__name__)


class FactorProvider(ABC):
    """
    因子数据提供者抽象基类

    所有具体 Provider 必须实现以下接口：
    - get_valuation: 获取估值因子（PB、PE等）
    - get_financial: 获取财务衍生因子（ROE等）
    - get_all_symbols: 获取全市场股票代码列表
    """

    @abstractmethod
    def get_valuation(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """
        获取估值因子

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段名，如 'pb_mrq', 'pe_ttm'
        date : str
            查询日期 'YYYY-MM-DD'

        Returns
        -------
        Dict[str, float]
            {stock_code: factor_value}
        """
        pass

    @abstractmethod
    def get_financial(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """
        获取财务衍生因子

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段名，如 'roe', 'roe_weight'
        date : str
            查询日期 'YYYY-MM-DD'

        Returns
        -------
        Dict[str, float]
            {stock_code: factor_value}
        """
        pass

    @abstractmethod
    def get_all_symbols(self) -> List[str]:
        """
        获取全市场股票代码列表

        Returns
        -------
        List[str]
            系统内部格式代码列表，如 ['000001.SZ', '600000.SH']
        """
        pass


class EastmoneyFactorProvider(FactorProvider):
    """
    东财掘金因子提供者

    调用 gm.api 获取真实财务数据，支持：
    - 估值因子：PB、PE_TTM 等（stk_get_daily_valuation_pt）
    - 财务衍生因子：ROE 等（stk_get_finance_deriv_pt）

    适用于 data_source='eastmoney' 场景
    """

    def __init__(self):
        from src.data.eastmoney_connector import EastmoneyConnector
        from config.config import get_credentials

        token = get_credentials('eastmoney').get('token', '')
        self._connector = EastmoneyConnector(token=token)
        logger.info("EastmoneyFactorProvider 初始化完成")

    def get_valuation(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """获取估值因子"""
        from src.data.symbol_converter import SymbolConverter

        try:
            df = self._connector.get_daily_valuation(
                symbols=symbols,
                fields=fields,
                trade_date=date,
            )

            if df is None or df.empty:
                return {}

            result = {}
            for _, row in df.iterrows():
                code = SymbolConverter.to_internal(row['symbol'])
                result[code] = row.get(fields, float('nan'))

            return result

        except Exception as e:
            logger.error(f"获取估值因子失败: {e}")
            return {}

    def get_financial(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """获取财务衍生因子"""
        from src.data.symbol_converter import SymbolConverter

        try:
            df = self._connector.get_financial_deriv(
                symbols=symbols,
                fields=fields,
                date=date,
            )

            if df is None or df.empty:
                return {}

            result = {}
            for _, row in df.iterrows():
                code = SymbolConverter.to_internal(row['symbol'])
                result[code] = row.get(fields, float('nan'))

            return result

        except Exception as e:
            logger.error(f"获取财务衍生因子失败: {e}")
            return {}

    def get_all_symbols(self) -> List[str]:
        """获取全市场股票代码列表"""
        from src.data.symbol_converter import SymbolConverter

        try:
            df = self._connector.get_stock_list()
            if df is None or df.empty:
                return []
            return SymbolConverter.batch_to_internal(df['symbol'].tolist())
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return []


class DatabaseFactorProvider(FactorProvider):
    """
    数据库因子提供者

    从本地 SQLite 数据库计算因子值，支持：
    - 估值因子：从 stock_daily 计算 PB、PE 等
    - 财务衍生因子：从 financial_data 计算 ROE 等

    适用于 data_source='database' 场景
    注意：部分复杂因子暂未实现，会抛出 NotImplementedError
    """

    def __init__(self, db_path: str):
        from src.data.database import DatabaseManager

        self._db = DatabaseManager(db_path)
        logger.info(f"DatabaseFactorProvider 初始化完成: {db_path}")

    def get_valuation(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """
        获取估值因子

        当前实现：
        - pb_mrq: 从 stock_daily 计算（需要市值和净资产数据）

        注意：数据库中缺少直接的每股净资产数据，需要进一步实现
        """
        if fields == 'pb_mrq':
            return self._calc_pb(symbols, date)
        elif fields == 'pe_ttm':
            return self._calc_pe_ttm(symbols, date)
        else:
            raise NotImplementedError(
                f"DatabaseFactorProvider 暂不支持估值因子: {fields}\n"
                f"请使用 data_source='eastmoney' 获取该因子"
            )

    def get_financial(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """
        获取财务衍生因子

        当前实现：
        - roe: 从 financial_data 计算

        注意：financial_data 存储的是原始报表 JSON，需要解析计算
        """
        if fields == 'roe':
            return self._calc_roe(symbols, date)
        else:
            raise NotImplementedError(
                f"DatabaseFactorProvider 暂不支持财务因子: {fields}\n"
                f"请使用 data_source='eastmoney' 获取该因子"
            )

    def get_all_symbols(self) -> List[str]:
        """获取全市场股票代码列表"""
        try:
            info = self._db.get_stock_info()
            if info.empty:
                return []
            return info['stock_code'].tolist()
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return []

    def _calc_pb(self, symbols: List[str], date: str) -> Dict[str, float]:
        """计算市净率 PB = 股价 / 每股净资产"""
        # TODO: 从 stock_daily 获取股价，从 financial_data 获取净资产
        # 当前数据库缺少直接的每股净资产数据
        logger.warning("DatabaseFactorProvider._calc_pb 暂未实现")
        return {}

    def _calc_pe_ttm(self, symbols: List[str], date: str) -> Dict[str, float]:
        """计算市盈率 PE_TTM = 总市值 / 净利润(TTM)"""
        # TODO: 需要计算 TTM 净利润
        logger.warning("DatabaseFactorProvider._calc_pe_ttm 暂未实现")
        return {}

    def _calc_roe(self, symbols: List[str], date: str) -> Dict[str, float]:
        """计算净资产收益率 ROE = 净利润 / 净资产"""
        # TODO: 从 financial_data 解析 JSON 计算
        logger.warning("DatabaseFactorProvider._calc_roe 暂未实现")
        return {}
