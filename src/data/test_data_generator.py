"""
测试数据生成器
=============

生成用于测试的模拟数据并导出为CSV文件。
注意：测试数据不再写入数据库，而是保存到 data/test_data/ 目录。
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import random
from pathlib import Path


class TestDataGenerator:
    """
    测试数据生成器

    生成模拟的股票数据、指数数据、股票信息，并导出为CSV文件。
    """

    INDUSTRIES = [
        '银行', '非银金融', '房地产', '建筑装饰', '建筑材料',
        '钢铁', '采掘', '有色金属', '化工', '机械设备',
        '电气设备', '国防军工', '汽车', '家用电器', '轻工制造',
        '纺织服装', '商业贸易', '农林牧渔', '食品饮料', '医药生物',
        '电子', '计算机', '传媒', '通信', '电力设备'
    ]

    INDEX_CODES = ['000001.SH', '399001.SZ', '399006.SZ', '000300.SH', '000852.SH']

    # 默认测试数据输出目录
    DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "test_data"

    def __init__(self, db_manager=None, output_dir: Optional[str] = None):
        """
        Parameters
        ----------
        db_manager : DatabaseManager, optional
            数据库管理器实例（仅保留兼容性，不再使用）
        output_dir : str, optional
            CSV文件输出目录，默认为 data/test_data/
        """
        self.db = db_manager
        self.output_dir = Path(output_dir) if output_dir else self.DEFAULT_OUTPUT_DIR
        self._ensure_output_dir()
        np.random.seed(42)
        random.seed(42)

    def _ensure_output_dir(self):
        """确保输出目录存在"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_stock_info(self, n_stocks: int = 100) -> pd.DataFrame:
        """生成股票信息"""
        stock_codes = []
        stock_names = []

        for i in range(1, n_stocks + 1):
            if i % 2 == 0:
                code = f'{600000 + i:06d}.SH'
            else:
                code = f'{1 + i:06d}.SZ'
            stock_codes.append(code)
            stock_names.append(f'股票{i:04d}')

        df = pd.DataFrame({
            'stock_code': stock_codes,
            'stock_name': stock_names,
            'industry': [self.INDUSTRIES[i % len(self.INDUSTRIES)] for i in range(n_stocks)],
            'market_cap': np.random.uniform(1e9, 1e12, n_stocks),
            'list_date': [
                (datetime(2020, 1, 1) + timedelta(days=random.randint(0, 1000))).strftime('%Y-%m-%d')
                for _ in range(n_stocks)
            ]
        })

        return df

    def generate_stock_daily(
        self,
        stock_codes: List[str],
        n_days: int = 250,
        start_date: str = '2023-01-01'
    ) -> pd.DataFrame:
        """生成股票日频数据"""
        trade_dates = pd.date_range(start=start_date, periods=n_days, freq='B')

        data = []
        for stock_code in stock_codes:
            base_price = np.random.uniform(5, 200)
            volatility = np.random.uniform(0.01, 0.03)

            returns = np.random.randn(n_days) * volatility
            returns[1:] += 0.2 * returns[:-1]
            returns += np.random.randn(n_days) * 0.005

            close_prices = base_price * np.cumprod(1 + returns)

            for i, trade_date in enumerate(trade_dates):
                close = close_prices[i]
                daily_range = abs(np.random.randn()) * volatility * close
                high = close + daily_range * np.random.rand()
                low = close - daily_range * np.random.rand()
                open_price = low + (high - low) * np.random.rand()

                base_volume = np.random.uniform(1e6, 1e8)
                volume = base_volume * (1 + abs(returns[i]) * 10)

                data.append({
                    'trade_date': trade_date.strftime('%Y-%m-%d'),
                    'stock_code': stock_code,
                    'open': round(open_price, 2),
                    'high': round(high, 2),
                    'low': round(low, 2),
                    'close': round(close, 2),
                    'volume': int(volume),
                    'amount': round(close * volume, 2),
                    'vwap': round((high + low + close) / 3, 2)
                })

        return pd.DataFrame(data)

    def generate_index_daily(
        self,
        index_codes: Optional[List[str]] = None,
        n_days: int = 250,
        start_date: str = '2023-01-01'
    ) -> pd.DataFrame:
        """生成指数日频数据"""
        if index_codes is None:
            index_codes = self.INDEX_CODES

        trade_dates = pd.date_range(start=start_date, periods=n_days, freq='B')

        base_prices = {
            '000001.SH': 3000, '399001.SZ': 10000, '399006.SZ': 2000,
            '000300.SH': 4000, '000852.SH': 6000
        }

        data = []
        for index_code in index_codes:
            base_price = base_prices.get(index_code, 5000)
            volatility = 0.015
            returns = np.random.randn(n_days) * volatility
            close_prices = base_price * np.cumprod(1 + returns)

            for i, trade_date in enumerate(trade_dates):
                close = close_prices[i]
                daily_range = abs(np.random.randn()) * volatility * close
                high = close + daily_range * np.random.rand()
                low = close - daily_range * np.random.rand()
                open_price = low + (high - low) * np.random.rand()
                volume = np.random.uniform(2e11, 5e11)

                data.append({
                    'trade_date': trade_date.strftime('%Y-%m-%d'),
                    'index_code': index_code,
                    'open': round(open_price, 2),
                    'high': round(high, 2),
                    'low': round(low, 2),
                    'close': round(close, 2),
                    'volume': int(volume)
                })

        return pd.DataFrame(data)

    def export_to_csv(self, output_dir: Optional[str] = None) -> Dict[str, str]:
        """
        将生成的测试数据导出为CSV文件

        Parameters
        ----------
        output_dir : str, optional
            输出目录，默认为初始化时指定的目录

        Returns
        -------
        Dict[str, str]
            各CSV文件的路径
        """
        if output_dir:
            self.output_dir = Path(output_dir)
            self._ensure_output_dir()

        exported_files = {}

        # 导出股票信息
        stock_info_path = self.output_dir / "stock_info.csv"
        if hasattr(self, '_stock_info_df') and self._stock_info_df is not None:
            self._stock_info_df.to_csv(stock_info_path, index=False, encoding='utf-8-sig')
            exported_files['stock_info'] = str(stock_info_path)

        # 导出股票日频数据
        stock_daily_path = self.output_dir / "stock_daily.csv"
        if hasattr(self, '_stock_daily_df') and self._stock_daily_df is not None:
            self._stock_daily_df.to_csv(stock_daily_path, index=False, encoding='utf-8-sig')
            exported_files['stock_daily'] = str(stock_daily_path)

        # 导出指数日频数据
        index_daily_path = self.output_dir / "index_daily.csv"
        if hasattr(self, '_index_daily_df') and self._index_daily_df is not None:
            self._index_daily_df.to_csv(index_daily_path, index=False, encoding='utf-8-sig')
            exported_files['index_daily'] = str(index_daily_path)

        return exported_files

    def generate_all_test_data(
        self,
        n_stocks: int = 100,
        n_days: int = 250,
        start_date: str = '2023-01-01',
        export_csv: bool = True,
        output_dir: Optional[str] = None
    ) -> dict:
        """
        生成所有测试数据并导出为CSV

        Parameters
        ----------
        n_stocks : int
            股票数量
        n_days : int
            交易日数量
        start_date : str
            开始日期
        export_csv : bool
            是否导出为CSV文件
        output_dir : str, optional
            CSV输出目录

        Returns
        -------
        dict
            生成的各类型数据
        """
        print(f"开始生成测试数据: {n_stocks}只股票, {n_days}个交易日")

        print("  [1/4] 生成股票信息...")
        self._stock_info_df = self.generate_stock_info(n_stocks)

        print("  [2/4] 生成股票日频数据...")
        self._stock_daily_df = self.generate_stock_daily(
            self._stock_info_df['stock_code'].tolist(), n_days, start_date
        )

        print("  [3/4] 生成指数日频数据...")
        self._index_daily_df = self.generate_index_daily(n_days=n_days, start_date=start_date)

        if export_csv:
            print("  [4/4] 导出为CSV文件...")
            exported = self.export_to_csv(output_dir)
            for name, path in exported.items():
                print(f"      {name}: {path}")
            print(f"测试数据导出完成! 保存目录: {self.output_dir}")
        else:
            print("测试数据生成完成!")

        return {
            'stock_info': self._stock_info_df,
            'stock_daily': self._stock_daily_df,
            'index_daily': self._index_daily_df
        }


def get_test_data_path(data_type: str = 'stock_info') -> Path:
    """
    获取测试数据CSV文件路径

    Parameters
    ----------
    data_type : str
        数据类型: 'stock_info', 'stock_daily', 'index_daily'

    Returns
    -------
    Path
        CSV文件路径
    """
    test_data_dir = Path(__file__).parent.parent.parent / "data" / "test_data"
    filename_map = {
        'stock_info': 'stock_info.csv',
        'stock_daily': 'stock_daily.csv',
        'index_daily': 'index_daily.csv'
    }
    return test_data_dir / filename_map.get(data_type, f'{data_type}.csv')


def load_test_data_csv(data_type: str = 'stock_info') -> pd.DataFrame:
    """
    加载测试数据CSV文件

    Parameters
    ----------
    data_type : str
        数据类型: 'stock_info', 'stock_daily', 'index_daily'

    Returns
    -------
    pd.DataFrame
        测试数据
    """
    path = get_test_data_path(data_type)
    if not path.exists():
        # 如果CSV不存在，自动生成测试数据
        print(f"测试数据文件不存在，正在自动生成...")
        generator = TestDataGenerator()
        generator.generate_all_test_data(n_stocks=100, n_days=250)
        print(f"测试数据已生成: {path.parent}")

    return pd.read_csv(path, encoding='utf-8-sig')


def check_test_data_exists() -> bool:
    """
    检查测试数据CSV文件是否存在

    Returns
    -------
    bool
        是否所有测试数据文件都存在
    """
    required_files = ['stock_info.csv', 'stock_daily.csv', 'index_daily.csv']
    test_data_dir = Path(__file__).parent.parent.parent / "data" / "test_data"
    return all((test_data_dir / f).exists() for f in required_files)


if __name__ == '__main__':
    # 直接运行此文件生成测试数据
    print("=" * 60)
    print("测试数据生成工具")
    print("=" * 60)
    print(f"\n输出目录: {TestDataGenerator.DEFAULT_OUTPUT_DIR}")
    print()

    generator = TestDataGenerator()
    data = generator.generate_all_test_data(n_stocks=100, n_days=250)

    print("\n数据预览:")
    print(f"  股票信息: {len(data['stock_info'])} 条")
    print(f"  股票日频: {len(data['stock_daily'])} 条")
    print(f"  指数日频: {len(data['index_daily'])} 条")
