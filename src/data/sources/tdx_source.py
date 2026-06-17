"""
通达信数据源
============

通达信仅用于板块成分股获取（spec 规定板块成分股走通达信）。
其他方法返回空结果。

依赖：pytdx 库
"""

import logging
from typing import List

import pandas as pd

from .base import DataSource

logger = logging.getLogger(__name__)

# 尝试导入 pytdx
try:
    from pytdx.hq import TdxHq_API
    _PYTDX_AVAILABLE = True
except ImportError:
    _PYTDX_AVAILABLE = False
    logger.warning("pytdx 未安装，TdxSource 将以离线模式运行。pip install pytdx")


class TdxSource(DataSource):
    """
    通达信数据源

    仅实现板块成分股获取，其他方法返回空结果。
    """

    # 通达信板块类别常量
    SECTOR_TYPE_INDUSTRY = 2    # 行业板块
    SECTOR_TYPE_CONCEPT = 3     # 概念板块
    SECTOR_TYPE_REGION = 4      # 地区板块

    def __init__(self, host: str = '119.147.212.81', port: int = 7709):
        super().__init__(name='tdx')
        self._host = host
        self._port = port
        self._api = None

    def connect(self) -> bool:
        if not _PYTDX_AVAILABLE:
            logger.warning("pytdx 未安装，无法连接通达信")
            return False
        try:
            self._api = TdxHq_API()
            self._connected = self._api.connect(self._host, self._port)
            if self._connected:
                logger.info(f"通达信连接成功: {self._host}:{self._port}")
            else:
                logger.warning(f"通达信连接失败: {self._host}:{self._port}")
            return self._connected
        except Exception as e:
            logger.error(f"通达信连接异常: {e}")
            return False

    def disconnect(self) -> None:
        if self._api:
            try:
                self._api.disconnect()
            except Exception:
                pass
        self._api = None
        self._connected = False

    def _ensure_connected(self):
        if not self._connected or self._api is None:
            if not self.connect():
                raise ConnectionError("通达信连接失败")

    # ============ 板块（核心功能） ============

    def get_sector_list(self, **kwargs) -> List[str]:
        """获取板块列表"""
        self._ensure_connected()
        sector_type = kwargs.get('sector_type', self.SECTOR_TYPE_CONCEPT)
        try:
            data = self._api.get_and_parse_block_data(sector_type)
            if data:
                return [item.get('blockname', '') for item in data if item.get('blockname')]
        except Exception as e:
            logger.error(f"获取板块列表失败: {e}")
        return []

    def get_sector_info(self, **kwargs) -> pd.DataFrame:
        """获取板块基本信息"""
        self._ensure_connected()
        sector_type = kwargs.get('sector_type', self.SECTOR_TYPE_CONCEPT)
        try:
            data = self._api.get_and_parse_block_data(sector_type)
            if data:
                return pd.DataFrame(data)
        except Exception as e:
            logger.error(f"获取板块信息失败: {e}")
        return pd.DataFrame()

    def get_sector_constituents(self, sector_name: str, **kwargs) -> List[str]:
        """
        获取板块成分股

        Parameters
        ----------
        sector_name : str
            板块名称，如 '概念板块.锂电池'

        Returns
        -------
        List[str]
            成分股代码列表（6位纯数字格式，如 '000001'）
        """
        self._ensure_connected()
        sector_type = kwargs.get('sector_type', self.SECTOR_TYPE_CONCEPT)
        try:
            data = self._api.get_and_parse_block_data(sector_type)
            if data:
                for block in data:
                    if block.get('blockname') == sector_name:
                        code_list = block.get('code_list', [])
                        return [code.get('code', '') for code in code_list if code.get('code')]
            logger.warning(f"未找到板块: {sector_name}")
        except Exception as e:
            logger.error(f"获取板块成分股失败: {e}")
        return []

    def __repr__(self):
        return f"<TdxSource(host={self._host}:{self._port}, connected={self._connected})>"
