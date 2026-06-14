"""
数据源注册中心
==============

统一管理所有数据源实例，提供按数据类型路由的能力。
- eastmoney: 东财掘金
- qmt: 国金QMT
- tdx: 通达信
- database: 本地 SQLite 数据库（不需要实例化）

与 config/config.json 的 data_source 字段配合使用：
    {
        "stock_daily": "qmt",
        "sector_constituents": "tdx",
        "dividend": "eastmoney",
        ...
    }
"""
import logging
from typing import Optional, Dict, Any

from config.config import get_data_source as _get_data_source_for_type

logger = logging.getLogger(__name__)


class SourceRegistry:
    """
    数据源注册中心（单例）

    Usage:
        registry = SourceRegistry()
        eastmoney = registry.get_source('eastmoney')
    """

    _instance: Optional['SourceRegistry'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._instances: Dict[str, Any] = {}
        self._initialized = True

    def get_source(self, source_name: str):
        """
        获取数据源实例（懒加载）

        Parameters
        ----------
        source_name : str
            数据源名 'eastmoney' / 'qmt' / 'tdx'

        Returns
        -------
        数据源实例，无效或加载失败时返回 None
        """
        if source_name in ('database', ''):
            return None

        if source_name in self._instances:
            return self._instances[source_name]

        try:
            if source_name == 'eastmoney':
                from .eastmoney_connector import EastmoneyConnector
                from config.config import get_credentials
                token = get_credentials('eastmoney').get('token', '')
                if not token:
                    logger.warning("未配置 eastmoney token")
                    return None
                instance = EastmoneyConnector(token=token)
                instance.connect()
            elif source_name == 'qmt':
                from .qmt_connector import QMTConnector
                instance = QMTConnector()
            elif source_name == 'tdx':
                from .tdx_source import TdxSource
                instance = TdxSource()
            else:
                logger.warning(f"未知数据源: {source_name}")
                return None

            self._instances[source_name] = instance
            return instance
        except Exception as e:
            logger.error(f"创建数据源 {source_name} 失败: {e}")
            return None

    def get_source_for_data_type(self, data_type: str):
        """
        根据数据类型获取数据源实例

        Parameters
        ----------
        data_type : str
            数据类型，如 'stock_daily', 'sector_constituents'

        Returns
        -------
        数据源实例
        """
        source_name = _get_data_source_for_type(data_type)
        return self.get_source(source_name)

    def reset(self) -> None:
        """重置所有数据源实例（用于测试）"""
        for name, instance in self._instances.items():
            try:
                if hasattr(instance, 'disconnect'):
                    instance.disconnect()
            except Exception:
                pass
        self._instances.clear()


def get_source_for_data_type(data_type: str):
    """
    便捷函数：根据数据类型获取数据源

    Usage:
        from src.data.source_registry import get_source_for_data_type
        src = get_source_for_data_type('sector_constituents')
    """
    return SourceRegistry().get_source_for_data_type(data_type)


__all__ = ['SourceRegistry', 'get_source_for_data_type']
