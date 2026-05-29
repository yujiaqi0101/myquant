"""
Symbol 格式转换工具

处理系统内部格式与东财掘金 API 格式之间的双向转换。

系统内部格式: 600000.SH, 000001.SZ (代码.交易所后缀)
掘金 API 格式: SHSE.600000, SZSE.000001 (交易所前缀.代码)
"""

from datetime import datetime
from typing import List


class SymbolConverter:
    """Symbol 双向转换器"""

    # 交易所后缀 -> 掘金前缀
    SUFFIX_TO_PREFIX = {
        'SH': 'SHSE',   # 上交所
        'SZ': 'SZSE',   # 深交所
    }

    # 掘金前缀 -> 交易所后缀
    PREFIX_TO_SUFFIX = {v: k for k, v in SUFFIX_TO_PREFIX.items()}

    @classmethod
    def to_eastmoney(cls, symbol: str) -> str:
        """
        系统内部格式 -> 掘金格式

        Parameters
        ----------
        symbol : str
            系统内部格式，如 '600000.SH'

        Returns
        -------
        str
            掘金格式，如 'SHSE.600000'

        Raises
        ------
        ValueError
            格式无效或未知的交易所后缀
        """
        parts = symbol.split('.')
        if len(parts) != 2:
            raise ValueError(f"无效的系统内部 symbol 格式: {symbol}，期望格式: 代码.后缀")

        code, suffix = parts
        prefix = cls.SUFFIX_TO_PREFIX.get(suffix.upper())
        if prefix is None:
            raise ValueError(f"未知的交易所后缀: {suffix}，支持: {list(cls.SUFFIX_TO_PREFIX.keys())}")

        return f"{prefix}.{code}"

    @classmethod
    def to_internal(cls, symbol: str) -> str:
        """
        掘金格式 -> 系统内部格式

        Parameters
        ----------
        symbol : str
            掘金格式，如 'SHSE.600000'

        Returns
        -------
        str
            系统内部格式，如 '600000.SH'

        Raises
        ------
        ValueError
            格式无效或未知的掘金交易所前缀
        """
        parts = symbol.split('.')
        if len(parts) != 2:
            raise ValueError(f"无效的掘金 symbol 格式: {symbol}，期望格式: 前缀.代码")

        prefix, code = parts
        suffix = cls.PREFIX_TO_SUFFIX.get(prefix.upper())
        if suffix is None:
            raise ValueError(f"未知的掘金交易所前缀: {prefix}，支持: {list(cls.PREFIX_TO_SUFFIX.keys())}")

        return f"{code}.{suffix}"

    @classmethod
    def batch_to_eastmoney(cls, symbols: List[str]) -> List[str]:
        """批量转换: 系统内部 -> 掘金"""
        return [cls.to_eastmoney(s) for s in symbols]

    @classmethod
    def batch_to_internal(cls, symbols: List[str]) -> List[str]:
        """批量转换: 掘金 -> 系统内部"""
        return [cls.to_internal(s) for s in symbols]

    @staticmethod
    def format_datetime(date_str: str, time_str: str = "09:00:00") -> str:
        """
        系统日期格式 -> 掘金日期时间格式

        Parameters
        ----------
        date_str : str
            系统日期格式 'YYYY-MM-DD'
        time_str : str, optional
            时间部分，默认 '09:00:00'

        Returns
        -------
        str
            掘金格式 'YYYY-MM-DD HH:MM:SS'
        """
        return f"{date_str} {time_str}"

    @staticmethod
    def parse_datetime(dt) -> str:
        """
        掘金返回的 datetime (带时区) -> 系统日期格式

        Parameters
        ----------
        dt : datetime or str
            掘金返回的 eob 字段，可能是带时区的 datetime 或字符串

        Returns
        -------
        str
            系统日期格式 'YYYY-MM-DD'
        """
        if isinstance(dt, str):
            # 字符串格式，直接取日期部分
            return dt[:10]

        if isinstance(dt, datetime):
            # 去除时区，转为日期字符串
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt.strftime('%Y-%m-%d')

        raise ValueError(f"无法解析的日期类型: {type(dt)}")
