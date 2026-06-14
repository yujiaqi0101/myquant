"""
通达信数据源（pytdx）
====================

板块成分股通过通达信获取（与飞书文档数据库表格完全对齐）：
- sector_constituents: 板块成分股 → tdx

通达信需要客户端运行，本模块基于 pytdx 库。
如果 pytdx 未安装，提供离线降级接口（返回空列表）。
"""
import logging
from typing import List, Optional, Dict, Any

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from pytdx.hq import TdxHq_API
    from pytdx.config.hosts import hq_hosts
    HAS_PYTDX = True
except ImportError:
    HAS_PYTDX = False
    TdxHq_API = None
    hq_hosts = []
    logger.warning("pytdx 未安装，TdxSource 将以降级模式运行（返回空数据）")


class TdxSource:
    """
    通达信数据源

    提供板块成分股（`get_stock_list_in_sector`）的访问能力。
    飞书文档"## 数据库"章节明确：
    > 板块 - 板块成分股 → 通达信 (get_stock_list_in_sector)
    """

    def __init__(self):
        self._api: Optional[Any] = None
        self._connected = False

    def connect(self) -> bool:
        """连接通达信行情服务器"""
        if not HAS_PYTDX:
            logger.warning("pytdx 未安装，无法连接通达信")
            return False
        try:
            self._api = TdxHq_API()
            # 尝试连接标准服务器
            with self._api.connect(*hq_hosts[0]) as _:
                self._connected = True
                logger.info(f"通达信连接成功: {hq_hosts[0]}")
            return True
        except Exception as e:
            logger.error(f"通达信连接失败: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        """断开连接"""
        if self._api is not None:
            try:
                self._api.disconnect()
            except Exception:
                pass
            self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def _ensure_connected(self) -> bool:
        if not self._connected:
            return self.connect()
        return True

    def get_sector_list(self) -> List[Dict[str, str]]:
        """
        获取板块列表

        Returns
        -------
        list[dict]
            板块列表，每项包含 sector_code, sector_name
        """
        if not self._ensure_connected():
            return []

        try:
            # pytdx 0.0.4+ 提供了 get_sector_list 接口
            sectors = self._api.get_sector_list()
            result = []
            for s in sectors or []:
                # s 格式: (code, name, start, end)
                if isinstance(s, (list, tuple)) and len(s) >= 2:
                    result.append({
                        'sector_code': str(s[0]),
                        'sector_name': str(s[1]),
                    })
            return result
        except Exception as e:
            logger.error(f"获取板块列表失败: {e}")
            return []

    def get_sector_constituents(self, sector_code: str) -> List[str]:
        """
        获取板块成分股

        Parameters
        ----------
        sector_code : str
            板块代码（通达信格式）

        Returns
        -------
        list[str]
            股票代码列表（标准格式：SHSE.600000 或 SZSE.000001）
        """
        if not self._ensure_connected():
            return []

        try:
            # pytdx 返回的股票代码是 6 位字符串，需要转换为标准格式
            raw_codes = self._api.get_stock_list_in_sector(sector_code)
            return [_convert_to_standard_code(code) for code in (raw_codes or [])]
        except Exception as e:
            logger.error(f"获取板块 {sector_code} 成分股失败: {e}")
            return []


def _convert_to_standard_code(code: str) -> str:
    """
    将通达信格式股票代码转换为标准格式

    规则：
    - 6/9 开头 → SHSE
    - 0/3 开头 → SZSE
    - 4/8 开头 → BJSE (北交所)

    Parameters
    ----------
    code : str
        6 位股票代码

    Returns
    -------
    str
        标准格式代码，如 'SHSE.600000'
    """
    if not isinstance(code, str):
        code = str(code)
    code = code.strip()
    if '.' in code:
        # 已经是标准格式
        return code
    if not code or len(code) != 6:
        return code
    if code.startswith(('6', '9', '5')):
        return f'SHSE.{code}'
    if code.startswith(('0', '3', '2')):
        return f'SZSE.{code}'
    if code.startswith(('4', '8')):
        return f'BJSE.{code}'
    return code


__all__ = ['TdxSource', 'HAS_PYTDX']
