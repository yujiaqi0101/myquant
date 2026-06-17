"""
AKShare 数据源
==============

开源免费数据源，无需 token。
适用于东财不可用时的备选方案。
"""

import logging
from typing import List, Optional, Dict, Any

import pandas as pd

from .base import DataSource

logger = logging.getLogger(__name__)

try:
    import akshare as ak
    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False
    logger.warning("akshare 未安装，AKShareSource 不可用。pip install akshare")


class AKShareSource(DataSource):
    """
    AKShare 数据源（备选，开源免费）

    无需 token，直接调用 akshare 接口。
    """

    def __init__(self, **kwargs):
        super().__init__(name='akshare')

    def connect(self) -> bool:
        if not _AKSHARE_AVAILABLE:
            logger.warning("akshare 未安装")
            return False
        try:
            # 测试连接：获取一只股票数据
            ak.stock_zh_a_hist(symbol='000001', period='daily', start_date='20240101', end_date='20240102', adjust='qfq')
            self._connected = True
            logger.info("AKShare 连接成功")
            return True
        except Exception as e:
            logger.error(f"AKShare 连接测试失败: {e}")
            return False

    # ============ 股票 ============

    def get_stock_list(self, **kwargs) -> pd.DataFrame:
        if not _AKSHARE_AVAILABLE:
            return pd.DataFrame()
        try:
            df = ak.stock_zh_a_spot_em()
            return df
        except Exception as e:
            logger.error(f"AKShare 获取股票列表失败: {e}")
            return pd.DataFrame()

    def get_stock_daily(self, symbol: str, start_date: str = None,
                        end_date: str = None, adjust: int = 1, **kwargs) -> pd.DataFrame:
        if not _AKSHARE_AVAILABLE:
            return pd.DataFrame()
        try:
            adjust_map = {0: '', 1: 'qfq', 2: 'hfq'}
            adj = adjust_map.get(adjust, 'qfq')
            # 去掉后缀，只保留6位代码
            code = symbol.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
            df = ak.stock_zh_a_hist(
                symbol=code, period='daily',
                start_date=start_date.replace('-', '') if start_date else '19900101',
                end_date=end_date.replace('-', '') if end_date else '20991231',
                adjust=adj,
            )
            return df
        except Exception as e:
            logger.error(f"AKShare 获取股票日K失败 [{symbol}]: {e}")
            return pd.DataFrame()

    # ============ 指数 ============

    def get_index_daily(self, symbol: str, start_date: str = None,
                        end_date: str = None, **kwargs) -> pd.DataFrame:
        if not _AKSHARE_AVAILABLE:
            return pd.DataFrame()
        try:
            code = symbol.replace('.SH', '').replace('.SZ', '')
            df = ak.index_zh_a_hist(
                symbol=code, period='daily',
                start_date=start_date.replace('-', '') if start_date else '19900101',
                end_date=end_date.replace('-', '') if end_date else '20991231',
            )
            return df
        except Exception as e:
            logger.error(f"AKShare 获取指数日K失败 [{symbol}]: {e}")
            return pd.DataFrame()

    # ============ 板块 ============

    def get_sector_constituents(self, sector_name: str, **kwargs) -> List[str]:
        if not _AKSHARE_AVAILABLE:
            return []
        try:
            df = ak.stock_board_concept_cons_em(symbol=sector_name)
            if df is not None and not df.empty:
                return df['代码'].tolist() if '代码' in df.columns else []
        except Exception as e:
            logger.error(f"AKShare 获取板块成分股失败 [{sector_name}]: {e}")
        return []
