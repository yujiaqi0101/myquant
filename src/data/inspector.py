"""
数据缺失检查器
==============

按照 spec Task 9 实现：
- 检测指定 stock list 在指定日期区间内是否有数据缺失
- 支持多种数据类型 (stock_daily / etf_daily / index_daily)
- 检查结果可用于自动触发补充同步

数据源：全部从数据库读取（飞书"模拟数据绝不写入数据库"原则）
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd

from .database import DatabaseManager

logger = logging.getLogger(__name__)


# 各表的"标的代码"列名映射
TABLE_CODE_COLUMN = {
    'stock_daily': 'stock_code',
    'etf_daily': 'etf_code',
    'index_daily': 'index_code',
    'index_constituent': 'index_code',
    'sector_constituent': 'sector_code',
    'dividend_date': 'stock_code',
}


class DataInspector:
    """
    数据缺失检查器

    典型用法
    --------
    >>> inspector = DataInspector(db)
    >>> missing = inspector.inspect(symbols=['SHSE.600000'], frequency='1d',
    ...                             start_date='2024-01-01', end_date='2024-01-31')
    >>> if missing['missing_symbols']:
    ...     # 触发补充同步
    """

    def __init__(self, db: DatabaseManager):
        self.db = db

    def inspect(
        self,
        symbols: Optional[List[str]] = None,
        frequency: str = '1d',
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        table: str = 'stock_daily',
    ) -> Dict[str, Any]:
        """
        检查指定范围内数据是否完整
        """
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        code_col = TABLE_CODE_COLUMN.get(table, 'stock_code')

        # 取数据库内的全部标的
        if symbols is None:
            symbols = self._list_symbols(table, code_col)
        symbols = [s for s in symbols if s]

        # 取交易日历
        trading_dates = self.db.get_trade_dates(start_date, end_date)
        expected = len(trading_dates)

        if not symbols or expected == 0:
            return {
                'total_symbols': len(symbols),
                'missing_symbols': [],
                'partial_symbols': [],
                'gaps': {},
                'checked_at': datetime.now().isoformat(),
                'message': '无标的或无交易日',
            }

        # 取每只标的的实际记录数
        actual = self._count_actual(table, code_col, symbols, start_date, end_date)
        missing = []
        partial = []
        gaps: Dict[str, List[str]] = {}
        for s in symbols:
            n = actual.get(s, 0)
            if n == 0:
                missing.append(s)
            elif n < expected:
                partial.append((s, n, expected))
                gaps[s] = self._find_gaps(table, code_col, s, start_date, end_date, trading_dates)

        return {
            'total_symbols': len(symbols),
            'missing_symbols': missing,
            'partial_symbols': partial,
            'gaps': gaps,
            'expected_days': expected,
            'start_date': start_date,
            'end_date': end_date,
            'checked_at': datetime.now().isoformat(),
        }

    def _list_symbols(self, table: str, code_col: str) -> List[str]:
        """取表中所有 distinct symbol"""
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT DISTINCT {code_col} FROM {table}")
            return [r[0] for r in cur.fetchall()]

    def _count_actual(
        self, table: str, code_col: str, symbols: List[str], start_date: str, end_date: str
    ) -> Dict[str, int]:
        """统计每只标的的实际记录数

        注意 SQLite 数字字符串 vs dash 字符串在 type affinity 上不等价，
        不能直接拼区间。改用两层 UNION（DASH + COMPACT）+ DISTINCT 计数。
        """
        if not symbols:
            return {}
        date_forms = self._candidate_date_forms(start_date, end_date)
        placeholders = ','.join('?' * len(symbols))
        union_parts = []
        params: List[Any] = []
        for lo, hi in date_forms:
            union_parts.append(
                f"SELECT {code_col}, trade_date FROM {table} "
                f"WHERE {code_col} IN ({placeholders}) "
                f"AND trade_date >= ? AND trade_date <= ?"
            )
            params.extend([*symbols, lo, hi])
        inner = " UNION ".join(union_parts)
        sql = (
            f"SELECT {code_col}, COUNT(DISTINCT trade_date) AS n "
            f"FROM ({inner}) GROUP BY {code_col}"
        )
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            rows = conn.execute(sql, params).fetchall()
            return {r[0]: r[1] for r in rows}

    def _find_gaps(
        self,
        table: str,
        code_col: str,
        symbol: str,
        start_date: str,
        end_date: str,
        trading_dates: List[str],
    ) -> List[str]:
        """找某只标的缺失的具体日期（兼容 YYYY-MM-DD / YYYYMMDD）"""
        date_forms = self._candidate_date_forms(start_date, end_date)
        union_parts = []
        params: List[Any] = []
        for lo, hi in date_forms:
            union_parts.append(
                f"SELECT trade_date FROM {table} "
                f"WHERE {code_col} = ? AND trade_date >= ? AND trade_date <= ?"
            )
            params.extend([symbol, lo, hi])
        sql = "SELECT DISTINCT trade_date FROM (" + " UNION ".join(union_parts) + ")"
        with self.db.get_connection() as conn:
            cur = conn.cursor()
            rows = conn.execute(sql, params).fetchall()
        present = {r[0] for r in rows}
        present_norm = {self._normalize_date(d) for d in present}
        gaps = []
        for d in trading_dates:
            if self._normalize_date(d) not in present_norm:
                gaps.append(d)
        return gaps

    @staticmethod
    def _candidate_date_forms(start_date: str, end_date: str):
        """返回若干 (lo, hi) 候选区间，覆盖 dash/compact 两种历史格式。"""
        norm_lo = DataInspector._normalize_date(start_date)
        norm_hi = DataInspector._normalize_date(end_date)
        compact_lo = norm_lo.replace('-', '')
        compact_hi = norm_hi.replace('-', '')
        # 字典序大的优先
        return sorted(
            {(norm_lo, norm_hi), (compact_lo, compact_hi)},
            key=lambda t: (t[0], t[1]),
        )

    @staticmethod
    def _normalize_date(d: str) -> str:
        """把日期字符串统一为 YYYY-MM-DD"""
        d = str(d)
        if len(d) == 8 and d.isdigit():
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return d[:10]


__all__ = ["DataInspector"]
