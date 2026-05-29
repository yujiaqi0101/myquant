"""
数据库适配器
============

从SQLite数据库读取数据，实现与DailyDataAdapter相同的接口。
"""

from typing import List, Optional, Union
from datetime import date
import pandas as pd

from .adapter import DailyDataAdapter
from .database import DatabaseManager


class DatabaseAdapter(DailyDataAdapter):
    """
    数据库适配器

    从SQLite数据库读取数据，实现与DailyDataAdapter相同的接口。
    """

    def __init__(self, db_path: str):
        """
        Parameters
        ----------
        db_path : str
            数据库文件路径
        """
        super().__init__()
        self.db = DatabaseManager(db_path)

    def load_price_data(self, data=None):
        """从数据库加载价格数据"""
        self._price_df = self.db.get_stock_daily()

    def load_index_data(self, data=None):
        """从数据库加载指数数据"""
        self._index_df = self.db.get_index_daily()

    def load_stock_list(self, data=None):
        """从数据库加载股票列表"""
        self._stock_list_df = self.db.get_stock_info()

    def load_all(self):
        """一次性加载所有数据"""
        self.load_price_data()
        self.load_index_data()
        self.load_stock_list()

    def get_trade_dates(
        self,
        start_date: Union[str, date],
        end_date: Union[str, date]
    ) -> List:
        """获取交易日列表"""
        start_str = str(start_date)[:10]
        end_str = str(end_date)[:10]
        return self.db.get_trade_dates(start_str, end_str)

    def get_available_stocks(self, trade_date: Union[str, date]) -> List[str]:
        """获取某日可交易的股票列表"""
        date_str = str(trade_date)[:10]
        return self.db.get_available_stocks(date_str)

    def get_database_manager(self) -> DatabaseManager:
        """获取数据库管理器"""
        return self.db
