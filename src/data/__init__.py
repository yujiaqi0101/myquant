# 数据模块
from .adapter import DataAdapter, DailyDataAdapter, MockDataAdapter
from .loader import DataLoader
from .database import DatabaseManager
from .db_adapter import DatabaseAdapter
from .csv_adapter import CSVTestDataAdapter
from .test_data_generator import TestDataGenerator
from .data_validator import DataValidator

# 东财掘金数据源（新增）
from .symbol_converter import SymbolConverter
from .stock_info_provider import StockInfoProvider, DatabaseStockInfoProvider, EastmoneyStockInfoProvider

# 东财掘金数据源采用延迟导入，避免在不需要时加载 gm
# 使用时通过 from src.data.eastmoney_connector import EastmoneyConnector 按需导入

__all__ = [
    "DataAdapter", "DailyDataAdapter", "MockDataAdapter", "DataLoader",
    "DatabaseManager", "DatabaseAdapter", "CSVTestDataAdapter", "TestDataGenerator",
    "DataValidator",
    # 东财掘金数据源
    "SymbolConverter", "StockInfoProvider", "DatabaseStockInfoProvider", "EastmoneyStockInfoProvider",
]
