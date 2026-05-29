"""
CSV测试数据适配器
================

用于从CSV文件加载测试数据的适配器。
"""

from typing import List, Optional, Union
from datetime import date
import pandas as pd
from pathlib import Path

from .adapter import DailyDataAdapter


class CSVTestDataAdapter(DailyDataAdapter):
    """
    CSV测试数据适配器

    从CSV文件加载测试数据，实现与DailyDataAdapter相同的接口。
    """

    def __init__(self, test_data_dir: Optional[str] = None):
        """
        Parameters
        ----------
        test_data_dir : str, optional
            测试数据目录，默认为 data/test_data/
        """
        super().__init__()
        if test_data_dir:
            self._test_data_dir = Path(test_data_dir)
        else:
            self._test_data_dir = Path(__file__).parent.parent.parent / "data" / "test_data"
        
        self._price_df = None
        self._index_df = None
        self._stock_list_df = None
        self._trade_dates_cache = None
        
        # 加载所有数据
        self.load_all()

    def load_price_data(self, data=None):
        """从CSV文件加载价格数据"""
        price_path = self._test_data_dir / "stock_daily.csv"
        if price_path.exists():
            df = pd.read_csv(price_path, encoding='utf-8-sig')
            # 转换trade_date为datetime格式（不转字符串）
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            # 设置索引 - 与数据库适配器保持一致
            if 'stock_code' in df.columns and 'trade_date' in df.columns:
                df = df.set_index(['trade_date', 'stock_code'])
            self._price_df = df
        else:
            self._price_df = pd.DataFrame()

    def load_index_data(self, data=None):
        """从CSV文件加载指数数据"""
        index_path = self._test_data_dir / "index_daily.csv"
        if index_path.exists():
            df = pd.read_csv(index_path, encoding='utf-8-sig')
            # 转换trade_date为datetime格式
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            # 设置索引 - 与数据库适配器保持一致
            if 'index_code' in df.columns and 'trade_date' in df.columns:
                df = df.set_index(['trade_date', 'index_code'])
            self._index_df = df
        else:
            self._index_df = pd.DataFrame()

    def load_stock_list(self, data=None):
        """从CSV文件加载股票列表"""
        stock_list_path = self._test_data_dir / "stock_info.csv"
        if stock_list_path.exists():
            self._stock_list_df = pd.read_csv(stock_list_path, encoding='utf-8-sig')
        else:
            self._stock_list_df = pd.DataFrame()

    def load_all(self):
        """一次性加载所有数据"""
        self.load_price_data()
        self.load_index_data()
        self.load_stock_list()
        self._build_trade_dates_cache()

    def _build_trade_dates_cache(self):
        """构建交易日缓存"""
        if self._price_df is not None and not self._price_df.empty:
            if isinstance(self._price_df.index, pd.MultiIndex):
                dates = self._price_df.index.get_level_values('trade_date').unique()
            else:
                dates = self._price_df['trade_date'].unique()
            self._trade_dates_cache = sorted([d for d in dates])

    def get_trade_dates(
        self,
        start_date: Union[str, date],
        end_date: Union[str, date]
    ) -> List:
        """获取交易日列表"""
        if self._trade_dates_cache is None:
            self._build_trade_dates_cache()
        
        start_date = pd.to_datetime(start_date)
        end_date = pd.to_datetime(end_date)
        
        if self._trade_dates_cache:
            return [d for d in self._trade_dates_cache if start_date <= d <= end_date]
        return []

    def get_available_stocks(self, trade_date: Union[str, date]) -> List[str]:
        """获取某日可交易的股票列表"""
        trade_date = pd.to_datetime(trade_date)
        
        if self._price_df is None or self._price_df.empty:
            return []
        
        if isinstance(self._price_df.index, pd.MultiIndex):
            # MultiIndex: trade_date, stock_code
            try:
                stocks = self._price_df.xs(trade_date, level='trade_date').index.tolist()
                return [str(s) for s in stocks]
            except KeyError:
                return []
        else:
            # 普通DataFrame
            if 'trade_date' in self._price_df.columns:
                return self._price_df[self._price_df['trade_date'] == trade_date]['stock_code'].unique().tolist()
            return []
