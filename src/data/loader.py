"""
数据加载器模块
============

提供便捷的数据加载和预处理功能。
支持通过环境变量 AQUANT_DATA_MODE 配置选择数据源：
- test: 使用 data/test_data/ 目录下的CSV测试数据
- real: 使用数据库中的真实数据
- auto: 自动检测（默认）
"""

from typing import Union, List, Optional
from pathlib import Path
import pandas as pd
import numpy as np
import os

from .adapter import DailyDataAdapter, MockDataAdapter
from .db_adapter import DatabaseAdapter

try:
    from .qmt_connector import QMTConnector
    from .data_sync import DataSynchronizer
    _QMT_AVAILABLE = True
except ImportError:
    _QMT_AVAILABLE = False


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
    def from_qmt(
        cls,
        db_path: str,
        account: str = None,
        password: str = None,
        start_date: str = '20230101',
        end_date: str = '',
        sync_if_empty: bool = True
    ) -> 'DataLoader':
        """
        从QMT数据源创建数据加载器

        Parameters
        ----------
        db_path : str
            数据库文件路径
        account : str, optional
            QMT交易账号
        password : str, optional
            QMT交易密码
        start_date : str
            数据起始日期，格式 'YYYYMMDD'
        end_date : str
            数据结束日期，空字符串表示到最新
        sync_if_empty : bool
            数据库为空时是否自动同步数据

        Returns
        -------
        DataLoader
            数据加载器实例
        """
        if not _QMT_AVAILABLE:
            raise ImportError(
                "QMT模块不可用。请确保已安装xtquant库，"
                "并且国金QMT交易端已以极简模式启动。"
            )

        from ..data.database import DatabaseManager
        from config.config import get_credentials

        db = DatabaseManager(db_path)

        # 账号密码：参数优先，为空时从credentials.json读取
        if not account or not password:
            creds = get_credentials('qmt')
            account = account or creds.get('account', '')
            password = password or creds.get('password', '')

        # 检查是否需要同步数据
        if sync_if_empty:
            summary = db.get_data_summary()
            if summary['stock_daily']['count'] == 0:
                print("数据库为空，开始从QMT同步数据...")
                connector = QMTConnector(account=account, password=password)
                if not connector.is_connected():
                    connector.connect()

                synchronizer = DataSynchronizer(connector, db)
                result = synchronizer.sync_all(start_date=start_date, end_date=end_date)
                print(f"数据同步完成: {result}")

        return cls.from_database(db_path)

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
        from ..config.config import (
            get_data_mode, 
            DataMode, 
            is_test_mode,
            DATABASE_CONFIG
        )
        
        mode = get_data_mode()
        
        if db_path is None:
            db_path = DATABASE_CONFIG["path"]
        
        if mode == DataMode.REAL:
            # 真实模式：只从数据库读取
            print("[数据加载] 模式: 真实数据 (仅数据库)")
            return cls.from_database(db_path), False
        else:
            # test/auto 模式：优先数据库，为空则回退模拟数据
            print("[数据加载] 模式: 测试模式 (优先数据库，可回退模拟数据)")
            try:
                loader = cls.from_database(db_path)
                # 检查数据库是否真的有数据
                stock_list = loader.get_stock_list()
                if stock_list is not None and not stock_list.empty:
                    print("[数据加载]   → 从数据库加载成功")
                    return loader, False
                else:
                    print("[数据加载]   → 数据库为空，回退到模拟数据 (CSV)")
                    return cls.from_test_data(), True
            except Exception as e:
                print(f"[数据加载]   → 数据库读取失败 ({e})，回退到模拟数据 (CSV)")
                return cls.from_test_data(), True
    
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
            数据源信息，包含模式、路径等
        """
        from ..config.config import get_data_mode, DataMode
        
        mode = get_data_mode()
        info = {
            'mode': mode,
            'mode_description': {
                DataMode.TEST: '测试数据 (CSV)',
                DataMode.REAL: '真实数据 (数据库)',
                DataMode.AUTO: '自动检测'
            }.get(mode, mode),
        }
        
        if mode == DataMode.TEST or (mode == DataMode.AUTO and is_test_mode()):
            from .test_data_generator import get_test_data_path
            info['stock_info_path'] = str(get_test_data_path('stock_info'))
            info['stock_daily_path'] = str(get_test_data_path('stock_daily'))
            info['index_daily_path'] = str(get_test_data_path('index_daily'))
        else:
            from ..config.config import DATABASE_CONFIG
            info['db_path'] = DATABASE_CONFIG["path"]
        
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


def is_test_mode() -> bool:
    """
    判断当前是否使用测试数据模式
    
    Returns
    -------
    bool
        是否为测试数据模式
    """
    from ..config.config import is_test_mode
    return is_test_mode()


def is_real_mode() -> bool:
    """
    判断当前是否使用真实数据模式
    
    Returns
    -------
    bool
        是否为真实数据模式
    """
    from ..config.config import is_real_mode
    return is_real_mode()
