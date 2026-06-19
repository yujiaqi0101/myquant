"""
DataSource 抽象基类
==================

定义所有数据源必须实现的接口。每个数据源只需实现自己支持的方法，
不支持的方法返回空结果或抛出 NotImplementedError。

spec 规定：
- 东财掘金：主数据源（股票/ETF/指数/财务/估值/交易日/除权除息）
- 通达信：板块成分股
- AKShare/Tushare：备选数据源
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

import pandas as pd

logger = logging.getLogger(__name__)


class DataSource(ABC):
    """
    数据源抽象基类

    所有数据源必须实现 connect() / disconnect()，
    以及自己支持的数据获取方法。不支持的方法默认返回空结果。
    """

    def __init__(self, name: str):
        self.name = name
        self._connected = False

    @abstractmethod
    def connect(self) -> bool:
        """建立连接，返回是否成功"""

    def disconnect(self) -> None:
        """断开连接"""
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ============ 交易日历 ============

    def get_trading_dates(self, start_year: int, end_year: int, **kwargs) -> List[str]:
        """获取交易日列表"""
        return []

    # ============ 股票 ============

    def get_stock_list(self, **kwargs) -> pd.DataFrame:
        """获取 A 股股票列表，返回 DataFrame"""
        return pd.DataFrame()

    def get_stock_info(self, symbols: List[str] = None, **kwargs) -> pd.DataFrame:
        """获取股票基本信息"""
        return pd.DataFrame()

    def get_stock_daily(self, symbol: str, start_date: str = None,
                        end_date: str = None, adjust: int = 1, **kwargs) -> pd.DataFrame:
        """获取股票日K线数据"""
        return pd.DataFrame()

    def get_stock_daily_batch(self, symbols: List[str], start_date: str = None,
                              end_date: str = None, adjust: int = 1, **kwargs) -> Dict[str, pd.DataFrame]:
        """批量获取股票日K线数据，返回 {symbol: DataFrame}"""
        return {}

    # ============ ETF ============

    def get_etf_list(self, **kwargs) -> pd.DataFrame:
        """获取 ETF 列表"""
        return pd.DataFrame()

    def get_etf_info(self, symbols: List[str] = None, **kwargs) -> pd.DataFrame:
        """获取 ETF 基本信息"""
        return pd.DataFrame()

    def get_etf_daily(self, symbol: str, start_date: str = None,
                      end_date: str = None, adjust: int = 1, **kwargs) -> pd.DataFrame:
        """获取 ETF 日K线数据"""
        return pd.DataFrame()

    # ============ 指数 ============

    def get_index_list(self, **kwargs) -> pd.DataFrame:
        """获取指数列表"""
        return pd.DataFrame()

    def get_index_info(self, symbols: List[str] = None, **kwargs) -> pd.DataFrame:
        """获取指数基本信息"""
        return pd.DataFrame()

    def get_index_daily(self, symbol: str, start_date: str = None,
                        end_date: str = None, **kwargs) -> pd.DataFrame:
        """获取指数日K线数据"""
        return pd.DataFrame()

    def get_index_constituents(self, index_code: str, **kwargs) -> List[str]:
        """获取指数成分股"""
        return []

    # ============ 板块 ============

    def get_sector_list(self, **kwargs) -> List[str]:
        """获取板块列表"""
        return []

    def get_sector_info(self, **kwargs) -> pd.DataFrame:
        """获取板块基本信息"""
        return pd.DataFrame()

    def get_sector_constituents(self, sector_name: str, **kwargs) -> List[str]:
        """获取板块成分股"""
        return []

    # ============ 财务 ============

    def get_financial_data(self, symbols: List[str], start_date: str = None,
                           end_date: str = None, **kwargs) -> pd.DataFrame:
        """获取财务数据"""
        return pd.DataFrame()

    # ============ 估值 ============

    def get_valuation_data(self, symbols: List[str], start_date: str = None,
                           end_date: str = None, **kwargs) -> pd.DataFrame:
        """获取估值数据"""
        return pd.DataFrame()

    # ============ 除权除息 ============

    def get_dividend_data(self, symbols: List[str], start_date: str = None,
                          end_date: str = None, **kwargs) -> pd.DataFrame:
        """获取除权除息数据"""
        return pd.DataFrame()

    # ============ 每日市值 ============

    def get_daily_mktvalue_data(self, symbols: List[str], trade_date: str = None, **kwargs) -> pd.DataFrame:
        """获取每日市值指标数据"""
        return pd.DataFrame()

    # ============ 合约详情 ============

    def get_instrument_detail(self, symbol: str, **kwargs) -> Optional[Dict[str, Any]]:
        """获取合约详情"""
        return None

    # ============ 辅助 ============

    def __repr__(self):
        return f"<{self.__class__.__name__}(name={self.name}, connected={self._connected})>"
