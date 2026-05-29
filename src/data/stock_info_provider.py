"""
股票信息提供者抽象接口

解耦 BacktestEngine 对 DatabaseManager 的直接依赖。
不同数据源实现各自的数据获取逻辑。
"""

from abc import ABC, abstractmethod
from typing import List, Set
import pandas as pd


class StockInfoProvider(ABC):
    """股票信息提供者抽象基类"""

    @abstractmethod
    def get_stock_info_filtered(self) -> pd.DataFrame:
        """
        获取股票基本信息（用于 ST 判断 + 新股判断）

        Returns
        -------
        pd.DataFrame
            至少包含列: stock_code, stock_name, list_date
        """
        pass

    @abstractmethod
    def get_trade_dates(self, start_date: str, end_date: str) -> List[str]:
        """
        获取交易日列表

        Parameters
        ----------
        start_date : str
            开始日期 'YYYY-MM-DD'
        end_date : str
            结束日期 'YYYY-MM-DD'

        Returns
        -------
        List[str]
            交易日列表 ['2024-01-02', '2024-01-03', ...]
        """
        pass

    @abstractmethod
    def get_st_codes(self) -> Set[str]:
        """
        获取 ST 股票代码集合

        Returns
        -------
        Set[str]
            ST 股票代码集合
        """
        pass


class DatabaseStockInfoProvider(StockInfoProvider):
    """基于 SQLite 数据库的股票信息提供者"""

    def __init__(self, db_path: str):
        from .database import DatabaseManager
        self._db = DatabaseManager(db_path)

    def get_stock_info_filtered(self) -> pd.DataFrame:
        """从数据库获取股票基本信息"""
        return self._db.get_stock_info_filtered()

    def get_trade_dates(self, start_date: str, end_date: str) -> List[str]:
        """从数据库获取交易日列表"""
        return self._db.get_trade_dates(start_date, end_date)

    def get_st_codes(self) -> Set[str]:
        """从股票名称中识别 ST 股票"""
        stock_info = self.get_stock_info_filtered()
        st_codes = set()
        for _, row in stock_info.iterrows():
            name = str(row.get('stock_name', ''))
            if 'ST' in name.upper():
                st_codes.add(row['stock_code'])
        return st_codes


class EastmoneyStockInfoProvider(StockInfoProvider):
    """基于东财掘金 API 的股票信息提供者"""

    def __init__(self, adapter: 'EastmoneyAdapter'):
        self._adapter = adapter

    def get_stock_info_filtered(self) -> pd.DataFrame:
        """从掘金 API 获取股票基本信息"""
        return self._adapter.get_stock_info_filtered()

    def get_trade_dates(self, start_date: str, end_date: str) -> List[str]:
        """从掘金 API 获取交易日列表"""
        return self._adapter.get_trade_dates(start_date, end_date)

    def get_st_codes(self) -> Set[str]:
        """从掘金 API 获取 ST 股票代码"""
        return self._adapter.get_st_codes()
