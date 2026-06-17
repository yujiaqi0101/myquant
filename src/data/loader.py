"""
数据加载器模块
============

提供便捷的数据加载和预处理功能。
数据来源统一从 config/config.json 的 data_source.routing 字段按数据类型路由。
优先从数据库读取，数据库为空则报错。
"""

from typing import Union, List, Optional
from pathlib import Path
import pandas as pd
import numpy as np
import os

from .adapter import DailyDataAdapter, MockDataAdapter
from .db_adapter import DatabaseAdapter

# 东财掘金采用延迟导入，避免在不需要时加载 gm
_EASTMONEY_AVAILABLE = None


def _check_eastmoney_available():
    """延迟检测东财掘金是否可用"""
    global _EASTMONEY_AVAILABLE
    if _EASTMONEY_AVAILABLE is not None:
        return _EASTMONEY_AVAILABLE
    try:
        from .eastmoney_adapter import EastmoneyAdapter
        _EASTMONEY_AVAILABLE = True
    except ImportError:
        _EASTMONEY_AVAILABLE = False
    return _EASTMONEY_AVAILABLE


class DataLoader:
    """
    数据加载器
    
    提供便捷的数据加载、预处理和缓存功能。
    支持从CSV测试数据或数据库真实数据加载。
    """
    
    def __init__(self, adapter: Optional[DailyDataAdapter] = None):
        """
        初始化数据加载器
        
        Parameters
        ----------
        adapter : DailyDataAdapter, optional
            数据适配器实例，如果不提供则创建新实例
        """
        self.adapter = adapter or DailyDataAdapter()
        self._preprocessed = False
    
    @classmethod
    def from_csv(
        cls,
        price_path: str,
        index_path: Optional[str] = None,
        stock_list_path: Optional[str] = None
    ) -> 'DataLoader':
        """
        从CSV文件创建数据加载器
        
        Parameters
        ----------
        price_path : str
            价格数据文件路径
        index_path : str, optional
            指数数据文件路径
        stock_list_path : str, optional
            股票列表文件路径
        
        Returns
        -------
        DataLoader
            数据加载器实例
        """
        adapter = DailyDataAdapter()
        adapter.load_price_data(price_path)
        
        if index_path:
            adapter.load_index_data(index_path)
        
        if stock_list_path:
            adapter.load_stock_list(stock_list_path)
        
        return cls(adapter)
    
    @classmethod
    def from_test_data(cls, test_data_dir: Optional[str] = None) -> 'DataLoader':
        """
        从CSV测试数据创建数据加载器
        
        测试数据存储在 data/test_data/ 目录下：
        - stock_info.csv: 股票信息
        - stock_daily.csv: 股票日频数据
        - index_daily.csv: 指数日频数据
        
        如果测试数据文件不存在，会自动生成。
        
        Parameters
        ----------
        test_data_dir : str, optional
            测试数据目录路径
        
        Returns
        -------
        DataLoader
            数据加载器实例
        """
        from .csv_adapter import CSVTestDataAdapter
        from .test_data_generator import check_test_data_exists
        
        # 检查测试数据是否存在，不存在则生成
        if not check_test_data_exists():
            print("测试数据文件不存在，正在自动生成...")
            from .test_data_generator import TestDataGenerator
            generator = TestDataGenerator()
            generator.generate_all_test_data(n_stocks=100, n_days=250)
        
        # 使用CSV适配器加载测试数据
        adapter = CSVTestDataAdapter(test_data_dir)
        
        loader = cls(adapter)
        
        # 获取股票数量
        stock_count = len(adapter._stock_list_df) if adapter._stock_list_df is not None else 0
        price_count = len(adapter._price_df) if adapter._price_df is not None else 0
        print(f"✓ 测试数据加载完成: {stock_count} 只股票, {price_count} 条价格数据")
        
        return loader
    
    @classmethod
    def from_dataframe(
        cls,
        price_df: pd.DataFrame,
        index_df: Optional[pd.DataFrame] = None,
        stock_list_df: Optional[pd.DataFrame] = None
    ) -> 'DataLoader':
        """
        从DataFrame创建数据加载器
        
        Parameters
        ----------
        price_df : pd.DataFrame
            价格数据
        index_df : pd.DataFrame, optional
            指数数据
        stock_list_df : pd.DataFrame, optional
            股票列表
        
        Returns
        -------
        DataLoader
            数据加载器实例
        """
        adapter = DailyDataAdapter()
        adapter.load_price_data(price_df)
        
        if index_df is not None:
            adapter.load_index_data(index_df)
        
        if stock_list_df is not None:
            adapter.load_stock_list(stock_list_df)
        
        return cls(adapter)
    
    @classmethod
    def create_mock(
        cls,
        n_stocks: int = 100,
        n_days: int = 250,
        start_date: str = '2023-01-01'
    ) -> 'DataLoader':
        """
        创建模拟数据加载器（用于测试）
        
        注意：此方法已废弃，建议使用 from_test_data() 从CSV文件加载测试数据
        
        Parameters
        ----------
        n_stocks : int
            股票数量
        n_days : int
            交易日数量
        start_date : str
            开始日期
        
        Returns
        -------
        DataLoader
            包含模拟数据的数据加载器
        """
        print("⚠ create_mock() 已废弃，请使用 from_test_data() 从CSV文件加载测试数据")
        adapter = MockDataAdapter()
        adapter.generate_mock_data(n_stocks, n_days, start_date)
        return cls(adapter)

    @classmethod
    def from_database(cls, db_path: str) -> 'DataLoader':
        """
        从SQLite数据库创建数据加载器

        Parameters
        ----------
        db_path : str
            数据库文件路径

        Returns
        -------
        DataLoader
            数据加载器实例
        """
        adapter = DatabaseAdapter(db_path)
        adapter.load_all()
        return cls(adapter)
    
    @classmethod
    def from_eastmoney(
        cls,
        token: str = None,
        start_date: str = None,
        end_date: str = None,
        stock_codes: List[str] = None,
        adjust: int = 1,
    ) -> 'DataLoader':
        """
        从东财掘金 API 创建数据加载器

        Parameters
        ----------
        token : str, optional
            API token，不提供则从 config.json 读取
        start_date : str
            数据起始日期，格式 'YYYY-MM-DD'
        end_date : str
            数据结束日期，格式 'YYYY-MM-DD'
        stock_codes : List[str], optional
            股票代码列表（系统内部格式 600000.SH）
        adjust : int
            复权方式：0=不复权, 1=前复权, 2=后复权

        Returns
        -------
        DataLoader
            数据加载器实例
        """
        if not _check_eastmoney_available():
            raise ImportError(
                "东财掘金模块不可用。请确保已安装 gm 库。"
            )

        from config.config import get_credentials
        from .eastmoney_adapter import EastmoneyAdapter

        if not token:
            creds = get_credentials('eastmoney')
            token = creds.get('token', '')

        if not token:
            raise ValueError("东财掘金 token 未配置。请在 config.json 的 credentials.eastmoney.token 中设置")

        adapter = EastmoneyAdapter(token=token, adjust=adjust)

        # 加载价格数据
        if start_date and end_date:
            adapter.load_price_data(start_date=start_date, end_date=end_date, stock_codes=stock_codes)

        # 加载股票列表
        adapter.load_stock_list()

        return cls(adapter)

    @classmethod
    def create(cls, db_path: Optional[str] = None) -> 'DataLoader':
        """
        根据环境变量自动创建数据加载器（推荐方式）
        
        数据加载策略：
        - real 模式：只从数据库读取，数据库为空则报错
        - test/auto 模式：优先从数据库读取，数据库为空则回退到CSV模拟数据
        
        Parameters
        ----------
        db_path : str, optional
            数据库文件路径，默认为 data/aquant.db
        
        Returns
        -------
        tuple
            (DataLoader, used_mock_data) - 数据加载器和是否使用了模拟数据
        """
        from ..config.config import DATABASE_CONFIG
        
        if db_path is None:
            db_path = DATABASE_CONFIG["path"]
        
        # 统一行为：优先从数据库读，数据库为空则报错
        print("[数据加载] 从数据库加载")
        try:
            loader = cls.from_database(db_path)
            stock_list = loader.get_stock_list()
            if stock_list is not None and not stock_list.empty:
                print("[数据加载]   → 从数据库加载成功")
                return loader, False
            else:
                raise ValueError("数据库为空，请先运行 python main.py data sync 同步数据")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"数据库读取失败 ({e})，请先运行 python main.py data sync 同步数据")
    
    def preprocess(self, fill_method: str = 'ffill') -> 'DataLoader':
        """
        数据预处理
        
        Parameters
        ----------
        fill_method : str
            缺失值填充方法，'ffill'（前向填充）或 'drop'（删除）
        
        Returns
        -------
        DataLoader
            预处理后的数据加载器
        """
        if self._preprocessed:
            return self
        
        # 处理价格数据中的缺失值
        if hasattr(self.adapter, '_price_df') and self.adapter._price_df is not None:
            df = self.adapter._price_df
            
            if fill_method == 'ffill':
                # 按股票分组前向填充
                df = df.groupby(level='stock_code').fillna(method='ffill')
                # 如果还有缺失值，用后向填充
                df = df.groupby(level='stock_code').fillna(method='bfill')
            elif fill_method == 'drop':
                df = df.dropna()
            
            self.adapter._price_df = df
        
        self._preprocessed = True
        return self
    
    def get_price_data(
        self,
        stock_codes: Optional[Union[str, List[str]]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        获取价格数据
        
        Parameters
        ----------
        stock_codes : str or List[str], optional
            股票代码，不指定则返回所有股票
        start_date : str, optional
            开始日期
        end_date : str, optional
            结束日期
        fields : List[str], optional
            需要的字段
        
        Returns
        -------
        pd.DataFrame
            价格数据
        """
        # 获取所有可用日期
        if start_date is None or end_date is None:
            trade_dates = self.adapter.get_trade_dates(
                start_date or '1900-01-01',
                end_date or '2100-01-01'
            )
            if not trade_dates:
                raise ValueError("无法获取交易日数据")
            start_date = start_date or str(trade_dates[0])
            end_date = end_date or str(trade_dates[-1])
        
        # 获取所有可用股票
        if stock_codes is None:
            stock_codes = self.adapter.get_available_stocks(start_date)
        
        return self.adapter.get_price_data(stock_codes, start_date, end_date, fields)
    
    def get_index_data(
        self,
        index_codes: Optional[Union[str, List[str]]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """获取指数数据"""
        if start_date is None or end_date is None:
            trade_dates = self.adapter.get_trade_dates(
                start_date or '1900-01-01',
                end_date or '2100-01-01'
            )
            start_date = start_date or str(trade_dates[0])
            end_date = end_date or str(trade_dates[-1])
        
        # 默认获取主要指数
        if index_codes is None:
            index_codes = ['000001.SH']  # 默认上证指数
        
        return self.adapter.get_index_data(index_codes, start_date, end_date)
    
    def get_stock_list(self) -> pd.DataFrame:
        """获取股票列表"""
        return self.adapter.get_stock_list()
    
    def get_industry_mapping(self) -> dict:
        """获取股票-行业映射"""
        stock_list = self.get_stock_list()
        if 'industry' in stock_list.columns and 'stock_code' in stock_list.columns:
            return dict(zip(stock_list['stock_code'], stock_list['industry']))
        return {}
    
    def get_market_cap_data(self) -> dict:
        """获取股票-市值映射"""
        stock_list = self.get_stock_list()
        if 'market_cap' in stock_list.columns and 'stock_code' in stock_list.columns:
            return dict(zip(stock_list['stock_code'], stock_list['market_cap']))
        return {}
    
    def get_data_source_info(self) -> dict:
        """
        获取数据源信息
        
        Returns
        -------
        dict
            数据源信息，包含路径等
        """
        from ..config.config import DATABASE_CONFIG
        
        info = {
            'mode': 'database',
            'db_path': DATABASE_CONFIG["path"],
        }
        
        return info
    
    def calculate_features(self) -> pd.DataFrame:
        """
        计算常用特征
        
        Returns
        -------
        pd.DataFrame
            特征数据
        """
        price_data = self.get_price_data().reset_index()
        
        # 按股票分组计算特征
        features = []
        
        for stock_code, group in price_data.groupby('stock_code'):
            group = group.sort_values('trade_date')
            
            # 基础特征
            feature = {
                'trade_date': group['trade_date'].values,
                'stock_code': stock_code,
                'close': group['close'].values,
                'volume': group['volume'].values,
            }
            
            # 收益率
            feature['returns'] = group['close'].pct_change().values
            
            # 波动率
            feature['volatility_20d'] = group['close'].pct_change().rolling(20).std().values
            
            # 均线
            feature['ma_5'] = group['close'].rolling(5).mean().values
            feature['ma_10'] = group['close'].rolling(10).mean().values
            feature['ma_20'] = group['close'].rolling(20).mean().values
            feature['ma_60'] = group['close'].rolling(60).mean().values
            
            # 均线偏离
            feature['ma_5_bias'] = (group['close'] / feature['ma_5'] - 1).values
            feature['ma_20_bias'] = (group['close'] / feature['ma_20'] - 1).values
            
            # 成交量变化
            feature['volume_ma_5'] = group['volume'].rolling(5).mean().values
            feature['volume_ratio'] = (group['volume'] / feature['volume_ma_5']).values
            
            # 价格位置
            feature['high_20d'] = group['close'].rolling(20).max().values
            feature['low_20d'] = group['close'].rolling(20).min().values
            feature['price_position'] = (
                (group['close'] - feature['low_20d']) / 
                (feature['high_20d'] - feature['low_20d'])
            ).values
            
            # K线形态
            feature['upper_shadow'] = (group['high'] - group[['open', 'close']].max(axis=1)).values
            feature['lower_shadow'] = (group[['open', 'close']].min(axis=1) - group['low']).values
            feature['body'] = abs(group['close'] - group['open']).values
            
            features.append(pd.DataFrame(feature))
        
        result = pd.concat(features, ignore_index=True)
        result['trade_date'] = pd.to_datetime(result['trade_date'])
        result.set_index(['trade_date', 'stock_code'], inplace=True)
        
        return result
