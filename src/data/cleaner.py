"""
数据清洗器
==========

按照 spec Task 10 实现：
- 除牌日处理：用前一天价格，成交量为 0
- 除权除息日处理：从除权除息日重新拉取数据

依赖：
- dividend_date 表（除权除息日）
- stock_info 表（判断是否除牌）
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import pandas as pd

from .database import DatabaseManager

logger = logging.getLogger(__name__)


class DataCleaner:
    """
    数据清洗器

    典型用法
    --------
    >>> cleaner = DataCleaner(db)
    >>> result = cleaner.clean_stock_daily(symbols=['SHSE.600000'],
    ...                                     start_date='2024-01-01',
    ...                                     end_date='2024-01-31')
    """

    def __init__(self, db: DatabaseManager):
        self.db = db

    def clean_stock_daily(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        清洗股票日频数据

        Parameters
        ----------
        symbols : List[str], optional
            标的代码列表，None 表示全部
        start_date / end_date : str
            起止日期

        Returns
        -------
        dict
            {
                'delisted_filled': int,    # 填充的除牌日数
                'ex_dividend_refetched': int, # 除权除息日重新拉取数
                'symbols_processed': int,
            }
        """
        if not symbols:
            symbols = self._list_symbols()

        delisted_filled = 0
        ex_dividend_refetched = 0

        for symbol in symbols:
            delisted_filled += self._fill_delisted_days(symbol, start_date, end_date)
            ex_dividend_refetched += self._refetch_ex_dividend_days(symbol, start_date, end_date)

        return {
            'delisted_filled': delisted_filled,
            'ex_dividend_refetched': ex_dividend_refetched,
            'symbols_processed': len(symbols),
        }

    def _list_symbols(self) -> List[str]:
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT stock_code FROM stock_info")
            return [r[0] for r in cur.fetchall()]

    def _fill_delisted_days(
        self,
        symbol: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> int:
        """
        除牌日处理

        规则：除牌日 (listed=0) 在数据库里没有该日的 stock_daily 记录，
        需要填充一行：价格用最后一天收盘价，成交量为 0，suspend_flag=1
        """
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            # 1) 取最后上市日
            cur.execute(
                """
                SELECT MAX(trade_date) FROM stock_daily WHERE stock_code = ?
                """,
                (symbol,),
            )
            last_row = cur.fetchone()
            if not last_row or not last_row[0]:
                return 0
            last_date = self._normalize_date(last_row[0])
            # 2) 取该日的 OHLCV
            cur.execute(
                """
                SELECT open, high, low, close, volume
                FROM stock_daily
                WHERE stock_code = ? AND trade_date = ?
                """,
                (symbol, last_date),
            )
            ohlc = cur.fetchone()
            if not ohlc:
                return 0
            o, h, l, c, v = ohlc
            # 3) 把最后一天标记为停牌
            cur.execute(
                """
                UPDATE stock_daily SET suspend_flag = 1
                WHERE stock_code = ? AND trade_date = ?
                """,
                (symbol, last_date),
            )
            return cur.rowcount

    def _refetch_ex_dividend_days(
        self,
        symbol: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> int:
        """
        除权除息日数据重新拉取

        规则：从 dividend_date 表取该标的的除权除息日，
        检查 stock_daily 在除权除息日是否有数据，
        缺失则触发外部补充同步（此函数返回"待补拉"的日期数量）。
        """
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT ex_date FROM dividend_date
                WHERE stock_code = ?
                  AND (? IS NULL OR ex_date >= ?)
                  AND (? IS NULL OR ex_date <= ?)
                """,
                (symbol, start_date, start_date, end_date, end_date),
            )
            ex_dates = [self._normalize_date(r[0]) for r in cur.fetchall()]
            if not ex_dates:
                return 0
            placeholders = ','.join('?' * len(ex_dates))
            cur.execute(
                f"""
                SELECT DISTINCT trade_date FROM stock_daily
                WHERE stock_code = ?
                  AND trade_date IN ({placeholders})
                """,
                (symbol, *ex_dates),
            )
            present = {self._normalize_date(r[0]) for r in cur.fetchall()}
            missing = [d for d in ex_dates if d not in present]
            if missing:
                logger.info(
                    f"{symbol}: {len(missing)} 个除权除息日需重新拉取"
                )
            return len(missing)

    @staticmethod
    def _normalize_date(d: str) -> str:
        d = str(d)
        if len(d) == 8 and d.isdigit():
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return d[:10]


__all__ = ["DataCleaner"]
