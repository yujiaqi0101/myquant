"""
Tushare 数据源
==============

付费数据源，需要 token。
适用于专业量化场景，数据质量高。
"""

import logging
from typing import List, Optional, Dict, Any

import pandas as pd

from .base import DataSource

logger = logging.getLogger(__name__)

try:
    import tushare as ts
    _TUSHARE_AVAILABLE = True
except ImportError:
    _TUSHARE_AVAILABLE = False
    logger.warning("tushare 未安装，TushareSource 不可用。pip install tushare")


class TushareSource(DataSource):
    """
    Tushare 数据源（备选，付费）

    需要配置 token，数据质量高，适合专业量化场景。
    """

    def __init__(self, token: str = None):
        super().__init__(name='tushare')
        self._token = token
        self._pro = None

    def connect(self) -> bool:
        if not _TUSHARE_AVAILABLE:
            logger.warning("tushare 未安装")
            return False
        if not self._token:
            from config.config import get_credentials
            creds = get_credentials('tushare')
            self._token = creds.get('token', '')
        if not self._token:
            logger.warning("未配置 tushare token")
            return False
        try:
            ts.set_token(self._token)
            self._pro = ts.pro_api()
            # 测试连接
            self._pro.trade_cal(exchange='SSE', start_date='20240101', end_date='20240102')
            self._connected = True
            logger.info("Tushare 连接成功")
            return True
        except Exception as e:
            logger.error(f"Tushare 连接失败: {e}")
            return False

    def _ensure_connected(self):
        if not self._connected or self._pro is None:
            if not self.connect():
                raise ConnectionError("Tushare 连接失败")

    # ============ 交易日历 ============

    def get_trading_dates(self, start_year: int, end_year: int, **kwargs) -> List[str]:
        self._ensure_connected()
        try:
            df = self._pro.trade_cal(
                exchange='SSE',
                start_date=f"{start_year}0101",
                end_date=f"{end_year}1231",
            )
            if df is not None and not df.empty:
                return df[df['is_open'] == 1]['cal_date'].tolist()
        except Exception as e:
            logger.error(f"Tushare 获取交易日历失败: {e}")
        return []

    # ============ 股票 ============

    def get_stock_list(self, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        try:
            df = self._pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry,list_date')
            return df
        except Exception as e:
            logger.error(f"Tushare 获取股票列表失败: {e}")
            return pd.DataFrame()

    def get_stock_daily(self, symbol: str, start_date: str = None,
                        end_date: str = None, adjust: int = 1, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        try:
            # Tushare 使用 000001.SZ 格式
            ts_code = symbol if '.' in symbol else self._to_ts_code(symbol)
            if adjust == 1:
                df = self._pro.daily(ts_code=ts_code,
                                     start_date=start_date.replace('-', '') if start_date else None,
                                     end_date=end_date.replace('-', '') if end_date else None)
            elif adjust == 2:
                df = self._pro.daily(ts_code=ts_code,
                                     start_date=start_date.replace('-', '') if start_date else None,
                                     end_date=end_date.replace('-', '') if end_date else None)
                # 后复权需要额外接口
                df_hfq = ts.pro_bar(ts_code=ts_code, adj='hfq',
                                    start_date=start_date.replace('-', '') if start_date else None,
                                    end_date=end_date.replace('-', '') if end_date else None)
                return df_hfq if df_hfq is not None and not df_hfq.empty else df
            else:
                df = ts.pro_bar(ts_code=ts_code, adj=None,
                                start_date=start_date.replace('-', '') if start_date else None,
                                end_date=end_date.replace('-', '') if end_date else None)
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.error(f"Tushare 获取股票日K失败 [{symbol}]: {e}")
            return pd.DataFrame()

    # ============ 指数 ============

    def get_index_daily(self, symbol: str, start_date: str = None,
                        end_date: str = None, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        try:
            ts_code = symbol if '.' in symbol else self._to_ts_code(symbol)
            df = self._pro.index_daily(ts_code=ts_code,
                                       start_date=start_date.replace('-', '') if start_date else None,
                                       end_date=end_date.replace('-', '') if end_date else None)
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.error(f"Tushare 获取指数日K失败 [{symbol}]: {e}")
            return pd.DataFrame()

    # ============ 财务 ============

    def get_financial_data(self, symbols: List[str], start_date: str = None,
                           end_date: str = None, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        try:
            ts_codes = [s if '.' in s else self._to_ts_code(s) for s in symbols]
            period = kwargs.get('period')
            df = self._pro.income(ts_code=','.join(ts_codes[:1]), period=period)
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.error(f"Tushare 获取财务数据失败: {e}")
            return pd.DataFrame()

    # ============ 辅助 ============

    @staticmethod
    def _to_ts_code(symbol: str) -> str:
        """将6位代码转为 Tushare 格式 (000001.SZ)"""
        if '.' in symbol:
            return symbol
        if symbol.startswith(('6',)):
            return f"{symbol}.SH"
        elif symbol.startswith(('0', '3')):
            return f"{symbol}.SZ"
        elif symbol.startswith(('4', '8')):
            return f"{symbol}.BJ"
        return f"{symbol}.SZ"
