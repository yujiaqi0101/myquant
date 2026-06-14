"""
成分股统一接口
============

按照 spec Task 11 实现：
- `get_etf_constituents(etf, date=None)` 从数据库 etf_daily 关联读取
- `get_index_constituents(index, date=None)` 从 index_constituent 读取
- `get_sector_constituents(sector, date=None)` 从 sector_constituent 读取

飞书"模拟数据绝不写入数据库"：所有读取从数据库进行，
数据库为空时返回空列表（不报错，方便上层调用做 fallback）
"""
import logging
from typing import List, Optional
import pandas as pd

from .database import DatabaseManager

logger = logging.getLogger(__name__)


def get_etf_constituents(
    db: DatabaseManager, etf_code: str, date: Optional[str] = None
) -> List[str]:
    """
    获取 ETF 成分股

    从 etf_constituent 表读取。
    date 参数：None 表示最新；否则取该日及之前的最新成分
    """
    with db.get_connection() as conn:
        cur = conn.cursor()
        if date:
            cur.execute(
                """
                SELECT DISTINCT stock_code FROM etf_constituent
                WHERE etf_code = ? AND trade_date <= ?
                """,
                (etf_code, date),
            )
        else:
            cur.execute(
                """
                SELECT DISTINCT stock_code FROM etf_constituent
                WHERE etf_code = ?
                """,
                (etf_code,),
            )
        return [r[0] for r in cur.fetchall()]


def get_index_constituents(
    db: DatabaseManager, index_code: str, date: Optional[str] = None
) -> List[str]:
    """
    获取指数成分股

    从 index_constituent 表读取。
    index_constituent 不含历史日期字段（每次同步覆盖全量），
    date 参数为兼容接口保留但实际不使用。
    """
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT stock_code FROM index_constituent
            WHERE index_code = ?
            """,
            (index_code,),
        )
        return [r[0] for r in cur.fetchall()]


def get_sector_constituents(
    db: DatabaseManager, sector_code: str, date: Optional[str] = None
) -> List[str]:
    """
    获取板块成分股

    从 sector_constituent 表读取。
    date 参数：None 表示最新；否则取该日及之前的最新成分
    """
    with db.get_connection() as conn:
        cur = conn.cursor()
        if date:
            cur.execute(
                """
                SELECT DISTINCT stock_code FROM sector_constituent
                WHERE sector_code = ? AND trade_date <= ?
                """,
                (sector_code, date),
            )
        else:
            cur.execute(
                """
                SELECT DISTINCT stock_code FROM sector_constituent
                WHERE sector_code = ?
                """,
                (sector_code,),
            )
        return [r[0] for r in cur.fetchall()]


def _parse_constituents_str(s: str) -> List[str]:
    """
    解析多种格式的成分股字符串

    兼容格式：
    - "SHSE.600000,SHSE.600001"
    - "SHSE.600000, SZSE.000001"
    - "['SHSE.600000', 'SHSE.600001']"
    - JSON list
    """
    s = s.strip()
    if s.startswith('[') and s.endswith(']'):
        import json
        try:
            return json.loads(s)
        except Exception:
            # 去掉引号
            s = s.strip('[]').replace("'", '').replace('"', '')
    return [x.strip() for x in s.split(',') if x.strip()]


__all__ = [
    "get_etf_constituents",
    "get_index_constituents",
    "get_sector_constituents",
]
