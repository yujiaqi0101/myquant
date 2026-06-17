"""
数据源注册中心
==============

单例模式，管理所有数据源实例（懒加载）。
根据 config/config.json 的 data_source.routing 字段按数据类型路由到对应数据源。

spec 规定：
- 每种数据有自己的"最佳"数据源
- 板块成分股走通达信，其他走东财
- 支持配置切换
"""

import logging
from typing import Dict, Optional

from .sources.base import DataSource

logger = logging.getLogger(__name__)

# 默认路由配置：数据类型 -> 数据源名称
DEFAULT_ROUTING = {
    'stock_daily': 'eastmoney',
    'stock_info': 'eastmoney',
    'etf_daily': 'eastmoney',
    'etf_info': 'eastmoney',
    'index_daily': 'eastmoney',
    'index_info': 'eastmoney',
    'index_constituents': 'eastmoney',
    'sector_list': 'tdx',
    'sector_info': 'tdx',
    'sector_constituents': 'tdx',
    'financial_data': 'eastmoney',
    'valuation_data': 'eastmoney',
    'dividend_data': 'eastmoney',
    'trading_dates': 'eastmoney',
}


class SourceRegistry:
    """
    数据源注册中心（单例）

    管理所有数据源实例，按数据类型路由到最佳数据源。
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, routing: Dict[str, str] = None):
        if self._initialized:
            return
        self._sources: Dict[str, DataSource] = {}
        self._routing: Dict[str, str] = routing or self._load_routing_from_config()
        self._initialized = True

    @staticmethod
    def _load_routing_from_config() -> Dict[str, str]:
        """从 config.json 加载路由配置"""
        try:
            from config.config import _CONFIG
            routing = _CONFIG.get('data_source', {}).get('routing', {})
            if routing:
                return routing
        except Exception:
            pass
        return DEFAULT_ROUTING.copy()

    def register(self, name: str, source: DataSource) -> None:
        """注册数据源"""
        self._sources[name] = source
        logger.info(f"注册数据源: {name} -> {source}")

    def get_source(self, name: str) -> Optional[DataSource]:
        """
        按名称获取数据源（懒加载）

        如果数据源未注册，尝试自动创建。
        """
        if name in self._sources:
            return self._sources[name]

        # 懒加载：尝试自动创建数据源
        source = self._create_source(name)
        if source:
            self._sources[name] = source
            return source

        logger.warning(f"数据源 '{name}' 不可用")
        return None

    def get_source_for_data_type(self, data_type: str) -> Optional[DataSource]:
        """
        根据数据类型路由到对应数据源

        Parameters
        ----------
        data_type : str
            数据类型，如 'stock_daily', 'sector_constituents' 等

        Returns
        -------
        DataSource or None
            对应的数据源实例
        """
        source_name = self._routing.get(data_type)
        if not source_name:
            logger.warning(f"未配置数据类型 '{data_type}' 的路由，使用默认数据源 'eastmoney'")
            source_name = 'eastmoney'
        return self.get_source(source_name)

    def set_routing(self, data_type: str, source_name: str) -> None:
        """动态修改路由配置"""
        self._routing[data_type] = source_name
        logger.info(f"路由更新: {data_type} -> {source_name}")

    def get_routing(self) -> Dict[str, str]:
        """获取当前路由配置"""
        return self._routing.copy()

    def _create_source(self, name: str) -> Optional[DataSource]:
        """懒加载创建数据源实例"""
        try:
            if name == 'eastmoney':
                from .sources.eastmoney_source import EastmoneySource
                return EastmoneySource()
            elif name == 'tdx':
                from .sources.tdx_source import TdxSource
                return TdxSource()
            elif name == 'akshare':
                from .sources.akshare_source import AKShareSource
                return AKShareSource()
            elif name == 'tushare':
                from .sources.tushare_source import TushareSource
                return TushareSource()
            else:
                logger.warning(f"未知数据源: {name}")
                return None
        except Exception as e:
            logger.error(f"创建数据源 '{name}' 失败: {e}")
            return None

    def connect_all(self) -> Dict[str, bool]:
        """尝试连接所有已注册的数据源"""
        results = {}
        for name, source in self._sources.items():
            try:
                results[name] = source.connect()
            except Exception as e:
                logger.error(f"连接数据源 '{name}' 失败: {e}")
                results[name] = False
        return results

    def disconnect_all(self) -> None:
        """断开所有数据源"""
        for source in self._sources.values():
            try:
                source.disconnect()
            except Exception:
                pass

    @classmethod
    def reset(cls):
        """重置单例（仅用于测试）"""
        if cls._instance:
            cls._instance.disconnect_all()
        cls._instance = None

    def __repr__(self):
        return f"<SourceRegistry(sources={list(self._sources.keys())}, routing={self._routing})>"
