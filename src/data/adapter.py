"""
数据适配器模块
============

提供统一的数据访问接口，支持多频率、多来源扩展。
当前实现日频数据适配器，预留分钟级扩展接口。
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Union
from datetime import datetime, date
import pandas as pd
import numpy as np


class DataAdapter(ABC):
    """
    数据适配器基类
    
    支持多频率、多来源扩展的数据访问接口。
    """
    
    # 支持的频率列表
    SUPPORTED_FREQS = ['daily']
    
    # 计划支持的频率列表
    PLANNED_FREQS = ['5min', '15min', '30min', '60min']
    
    def __init__(self, freq: str = 'daily'):
        """
        初始化数据适配器
        
        Parameters
        ----------
        freq : str
            数据频率，当前仅支持 'daily'
        """
        self._validate_freq(freq)
        self.freq = freq
        self._data_cache = {}
    
    def _validate_freq(self, freq: str):
        """验证频率是否支持"""
        if freq not in self.SUPPORTED_FREQS:
            if freq in self.PLANNED_FREQS:
                raise NotImplementedError(
                    f"频率 '{freq}' 计划支持中，当前仅支持: {self.SUPPORTED_FREQS}"
                )
            else:
                raise ValueError(f"不支持的频率: '{freq}'")
    
    @abstractmethod
    def get_price_data(
        self,
        stock_codes: Union[str, List[str]],
        start_date: Union[str, date],
        end_date: Union[str, date],
        fields: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        获取价格数据
        
        Parameters
        ----------
        stock_codes : str or List[str]
            股票代码或代码列表
        start_date : str or date
            开始日期
        end_date : str or date
            结束日期
        fields : List[str], optional
            需要获取的字段列表
            
        Returns
        -------
        pd.DataFrame
            价格数据，索引为(trade_date, stock_code)
        """
        pass
    
    @abstractmethod
    def get_index_data(
        self,
        index_codes: Union[str, List[str]],
        start_date: Union[str, date],
        end_date: Union[str, date]
    ) -> pd.DataFrame:
        """
        获取指数数据
        
        Parameters
        ----------
        index_codes : str or List[str]
            指数代码或代码列表
        start_date : str or date
            开始日期
        end_date : str or date
            结束日期
            
        Returns
        -------
        pd.DataFrame
            指数数据
        """
        pass
    
    @abstractmethod
    def get_sector_data(
        self,
        start_date: Union[str, date],
        end_date: Union[str, date]
    ) -> pd.DataFrame:
        """
        获取板块数据
        
        Parameters
        ----------
        start_date : str or date
            开始日期
        end_date : str or date
            结束日期
            
        Returns
        -------
        pd.DataFrame
            板块数据
        """
        pass
    
    @abstractmethod
    def get_stock_list(self) -> pd.DataFrame:
        """
        获取股票列表
        
        Returns
        -------
        pd.DataFrame
            股票列表，包含代码、名称、行业、市值等信息
        """
        pass
    
    def clear_cache(self):
        """清除数据缓存"""
        self._data_cache.clear()


class DailyDataAdapter(DataAdapter):
    """
    日频数据适配器
    
    当前实现版本，支持从CSV文件或DataFrame加载数据。
    """
    
    # 标准字段名映射
    FIELD_MAPPING = {
        'trade_date': 'trade_date',
        'stock_code': 'stock_code',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'volume': 'volume',
        'amount': 'amount',
        'vwap': 'vwap',
        'turnover': 'turnover',
    }
    
    def __init__(self):
        """初始化日频数据适配器"""
        super().__init__(freq='daily')
        self._price_df = None
        self._index_df = None
        self._sector_df = None
        self._stock_list_df = None
    
    def load_price_data(self, data: Union[str, pd.DataFrame]):
        """
        加载价格数据
        
        Parameters
        ----------
        data : str or pd.DataFrame
            数据源，可以是文件路径或DataFrame
        """
        if isinstance(data, str):
            self._price_df = pd.read_csv(data)
        else:
            self._price_df = data.copy()
        
        # 标准化列名
        self._price_df = self._standardize_columns(self._price_df)
        
        # 确保日期格式正确
        if 'trade_date' in self._price_df.columns:
            self._price_df['trade_date'] = pd.to_datetime(self._price_df['trade_date'])
        
        # 设置索引
        if 'trade_date' in self._price_df.columns and 'stock_code' in self._price_df.columns:
            self._price_df.set_index(['trade_date', 'stock_code'], inplace=True)
    
    def load_index_data(self, data: Union[str, pd.DataFrame]):
        """加载指数数据"""
        if isinstance(data, str):
            self._index_df = pd.read_csv(data)
        else:
            self._index_df = data.copy()
        
        self._index_df = self._standardize_columns(self._index_df)
        
        if 'trade_date' in self._index_df.columns:
            self._index_df['trade_date'] = pd.to_datetime(self._index_df['trade_date'])
        
        if 'trade_date' in self._index_df.columns and 'index_code' in self._index_df.columns:
            self._index_df.set_index(['trade_date', 'index_code'], inplace=True)
    
    def load_sector_data(self, data: Union[str, pd.DataFrame]):
        """加载板块数据"""
        if isinstance(data, str):
            self._sector_df = pd.read_csv(data)
        else:
            self._sector_df = data.copy()
        
        self._sector_df = self._standardize_columns(self._sector_df)
        
        if 'trade_date' in self._sector_df.columns:
            self._sector_df['trade_date'] = pd.to_datetime(self._sector_df['trade_date'])
    
    def load_stock_list(self, data: Union[str, pd.DataFrame]):
        """加载股票列表"""
        if isinstance(data, str):
            self._stock_list_df = pd.read_csv(data)
        else:
            self._stock_list_df = data.copy()
        
        self._stock_list_df = self._standardize_columns(self._stock_list_df)
    
    def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化列名"""
        column_map = {k: v for k, v in self.FIELD_MAPPING.items() if k in df.columns}
        return df.rename(columns=column_map)
    
    def get_price_data(
        self,
        stock_codes: Union[str, List[str]],
        start_date: Union[str, date],
        end_date: Union[str, date],
        fields: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """获取价格数据"""
        if self._price_df is None:
            raise ValueError("请先使用 load_price_data() 加载价格数据")
        
        # 转换日期格式
        start_date = pd.to_datetime(start_date)
        end_date = pd.to_datetime(end_date)
        
        # 转换股票代码为列表
        if isinstance(stock_codes, str):
            stock_codes = [stock_codes]
        
        # 筛选数据
        try:
            result = self._price_df.loc[
                (slice(start_date, end_date), stock_codes)
            ]
        except KeyError:
            # 如果索引不匹配，尝试其他方式
            result = self._price_df.reset_index()
            result = result[
                (result['trade_date'] >= start_date) &
                (result['trade_date'] <= end_date) &
                (result['stock_code'].isin(stock_codes))
            ]
            result.set_index(['trade_date', 'stock_code'], inplace=True)
        
        # 选择字段
        if fields:
            available_fields = [f for f in fields if f in result.columns]
            result = result[available_fields]
        
        return result
    
    def get_index_data(
        self,
        index_codes: Union[str, List[str]],
        start_date: Union[str, date],
        end_date: Union[str, date]
    ) -> pd.DataFrame:
        """获取指数数据"""
        if self._index_df is None:
            raise ValueError("请先使用 load_index_data() 加载指数数据")
        
        start_date = pd.to_datetime(start_date)
        end_date = pd.to_datetime(end_date)
        
        if isinstance(index_codes, str):
            index_codes = [index_codes]
        
        try:
            result = self._index_df.loc[
                (slice(start_date, end_date), index_codes)
            ]
        except KeyError:
            result = self._index_df.reset_index()
            result = result[
                (result['trade_date'] >= start_date) &
                (result['trade_date'] <= end_date) &
                (result['index_code'].isin(index_codes))
            ]
            result.set_index(['trade_date', 'index_code'], inplace=True)
        
        return result
    
    def get_sector_data(
        self,
        start_date: Union[str, date],
        end_date: Union[str, date]
    ) -> pd.DataFrame:
        """获取板块数据"""
        if self._sector_df is None:
            raise ValueError("请先使用 load_sector_data() 加载板块数据")
        
        start_date = pd.to_datetime(start_date)
        end_date = pd.to_datetime(end_date)
        
        result = self._sector_df[
            (self._sector_df['trade_date'] >= start_date) &
            (self._sector_df['trade_date'] <= end_date)
        ]
        
        return result
    
    def get_stock_list(self) -> pd.DataFrame:
        """获取股票列表"""
        if self._stock_list_df is None:
            raise ValueError("请先使用 load_stock_list() 加载股票列表")
        
        return self._stock_list_df.copy()
    
    def get_trade_dates(
        self,
        start_date: Union[str, date],
        end_date: Union[str, date]
    ) -> List[date]:
        """获取交易日列表"""
        if self._price_df is None:
            raise ValueError("请先加载数据")
        
        start_date = pd.to_datetime(start_date)
        end_date = pd.to_datetime(end_date)
        
        # 从价格数据中提取交易日
        trade_dates = self._price_df.index.get_level_values('trade_date').unique()
        trade_dates = trade_dates[(trade_dates >= start_date) & (trade_dates <= end_date)]
        
        return trade_dates.sort_values().tolist()
    
    def get_available_stocks(self, trade_date: Union[str, date]) -> List[str]:
        """获取某日可交易的股票列表"""
        if self._price_df is None:
            raise ValueError("请先加载数据")
        
        trade_date = pd.to_datetime(trade_date)
        
        try:
            stocks = self._price_df.xs(trade_date, level='trade_date').index.tolist()
        except KeyError:
            stocks = []
        
        return stocks
    
    def calculate_vwap(self) -> pd.Series:
        """计算成交量加权平均价"""
        if self._price_df is None:
            raise ValueError("请先加载数据")
        
        if 'vwap' in self._price_df.columns:
            return self._price_df['vwap']
        
        # 如果没有VWAP，使用 (high + low + close) / 3 近似
        if all(col in self._price_df.columns for col in ['high', 'low', 'close']):
            return (self._price_df['high'] + self._price_df['low'] + self._price_df['close']) / 3
        
        raise ValueError("数据中缺少计算VWAP所需的字段")
    
    def calculate_returns(self, period: int = 1) -> pd.Series:
        """
        计算收益率
        
        Parameters
        ----------
        period : int
            收益率周期（交易日）
        
        Returns
        -------
        pd.Series
            收益率序列
        """
        if self._price_df is None:
            raise ValueError("请先加载数据")
        
        close = self._price_df['close']
        
        # 按股票分组计算收益率
        returns = close.groupby(level='stock_code').pct_change(period)
        
        return returns
    
    def calculate_adv(self, window: int = 20) -> pd.Series:
        """
        计算平均成交量
        
        Parameters
        ----------
        window : int
            滚动窗口（交易日）
        
        Returns
        -------
        pd.Series
            平均成交量序列
        """
        if self._price_df is None:
            raise ValueError("请先加载数据")
        
        volume = self._price_df['volume']
        
        # 按股票分组计算滚动平均
        adv = volume.groupby(level='stock_code').transform(
            lambda x: x.rolling(window=window, min_periods=1).mean()
        )
        
        return adv


class MockDataAdapter(DailyDataAdapter):
    """
    模拟数据适配器
    
    用于测试和演示，生成模拟数据。
    """
    
    def generate_mock_data(
        self,
        n_stocks: int = 100,
        n_days: int = 250,
        start_date: str = '2023-01-01'
    ):
        """
        生成模拟数据
        
        Parameters
        ----------
        n_stocks : int
            股票数量
        n_days : int
            交易日数量
        start_date : str
            开始日期
        """
        np.random.seed(42)
        
        # 生成交易日
        trade_dates = pd.date_range(start=start_date, periods=n_days, freq='B')
        
        # 生成股票代码
        stock_codes = [f'{i:06d}.SH' for i in range(1, n_stocks + 1)]
        
        # 生成价格数据
        data = []
        for stock_code in stock_codes:
            # 初始价格
            base_price = np.random.uniform(10, 100)
            
            # 生成收益率序列（带自相关）
            returns = np.random.randn(n_days) * 0.02
            returns[1:] += 0.3 * returns[:-1]  # 添加自相关
            
            # 计算价格
            close = base_price * np.cumprod(1 + returns)
            
            # 生成OHLC
            high = close * (1 + np.abs(np.random.randn(n_days)) * 0.02)
            low = close * (1 - np.abs(np.random.randn(n_days)) * 0.02)
            open_price = low + (high - low) * np.random.rand(n_days)
            
            # 生成成交量
            volume = np.random.uniform(1e6, 1e8, n_days)
            amount = close * volume
            
            # VWAP
            vwap = (high + low + close) / 3
            
            for i, trade_date in enumerate(trade_dates):
                data.append({
                    'trade_date': trade_date,
                    'stock_code': stock_code,
                    'open': round(open_price[i], 2),
                    'high': round(high[i], 2),
                    'low': round(low[i], 2),
                    'close': round(close[i], 2),
                    'volume': int(volume[i]),
                    'amount': amount[i],
                    'vwap': round(vwap[i], 2),
                })
        
        price_df = pd.DataFrame(data)
        self.load_price_data(price_df)
        
        # 生成指数数据
        index_data = []
        index_codes = ['000001.SH', '399001.SZ', '399006.SZ']
        
        for index_code in index_codes:
            base_price = 3000 if index_code == '000001.SH' else 10000
            returns = np.random.randn(n_days) * 0.015
            
            close = base_price * np.cumprod(1 + returns)
            high = close * (1 + np.abs(np.random.randn(n_days)) * 0.01)
            low = close * (1 - np.abs(np.random.randn(n_days)) * 0.01)
            open_price = low + (high - low) * np.random.rand(n_days)
            volume = np.random.uniform(1e9, 5e9, n_days)
            
            for i, trade_date in enumerate(trade_dates):
                index_data.append({
                    'trade_date': trade_date,
                    'index_code': index_code,
                    'open': round(open_price[i], 2),
                    'high': round(high[i], 2),
                    'low': round(low[i], 2),
                    'close': round(close[i], 2),
                    'volume': int(volume[i]),
                })
        
        index_df = pd.DataFrame(index_data)
        self.load_index_data(index_df)
        
        # 生成股票列表
        industries = ['银行', '非银金融', '房地产', '建筑装饰', '建筑材料',
                      '钢铁', '采掘', '有色金属', '化工', '机械设备',
                      '电气设备', '国防军工', '汽车', '家用电器', '轻工制造',
                      '纺织服装', '商业贸易', '农林牧渔', '食品饮料', '医药生物']
        
        stock_list = []
        for i, stock_code in enumerate(stock_codes):
            stock_list.append({
                'stock_code': stock_code,
                'stock_name': f'股票{i+1:03d}',
                'industry': industries[i % len(industries)],
                'market_cap': np.random.uniform(1e9, 1e12),
                'list_date': '2020-01-01',
            })
        
        stock_list_df = pd.DataFrame(stock_list)
        self.load_stock_list(stock_list_df)
        
        print(f"已生成模拟数据: {n_stocks}只股票, {n_days}个交易日")
