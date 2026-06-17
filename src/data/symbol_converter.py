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

    # 纯数字代码 -> 交易所后缀的推断规则
    @classmethod
    def _infer_suffix(cls, code: str) -> str:
        """根据纯数字代码推断交易所后缀"""
        if code.startswith(('6', '9', '5')):
            return 'SH'  # 上交所：6开头主板、9开头B股、5开头基金
        elif code.startswith(('0', '3', '2')):
            return 'SZ'  # 深交所：0开头主板、3开头创业板、2开头B股
        else:
            return 'SZ'  # 默认深交所

    @classmethod
    def to_eastmoney(cls, symbol: str) -> str:
        """
        系统内部格式 -> 掘金格式

        支持三种输入格式：
        - '600000.SH' (代码.后缀) -> 'SHSE.600000'
        - '600000' (纯数字) -> 自动推断交易所 -> 'SHSE.600000'
        - 'SHSE.600000' (已是掘金格式) -> 'SHSE.600000'
        """
        parts = symbol.split('.')
        if len(parts) == 2:
            left, right = parts
            # 判断是掘金格式 (SHSE.600000) 还是内部格式 (600000.SH)
            if left.upper() in cls.PREFIX_TO_SUFFIX:
                # 已经是掘金格式，直接返回
                return f"{left.upper()}.{right}"
            else:
                # 内部格式: 代码.后缀
                code, suffix = left, right
                prefix = cls.SUFFIX_TO_PREFIX.get(suffix.upper())
                if prefix is None:
                    raise ValueError(f"未知的交易所后缀: {suffix}，支持: {list(cls.SUFFIX_TO_PREFIX.keys())}")
                return f"{prefix}.{code}"
        elif len(parts) == 1:
            # 纯数字代码，自动推断交易所
            code = parts[0]
            suffix = cls._infer_suffix(code)
            prefix = cls.SUFFIX_TO_PREFIX[suffix]
            return f"{prefix}.{code}"
        else:
            raise ValueError(f"无效的 symbol 格式: {symbol}，期望格式: 代码.后缀 或 纯数字代码")

    @classmethod
    def to_internal(cls, symbol: str) -> str:
        """
        掘金格式 -> 系统内部格式

        支持三种输入格式：
        - 'SHSE.600000' (掘金格式) -> '600000.SH'
        - '600000.SH' (已是内部格式) -> '600000.SH'
        - '600000' (纯数字) -> 自动推断交易所 -> '600000.SH'
        """
        parts = symbol.split('.')
        if len(parts) == 2:
            left, right = parts
            # 判断是掘金格式 (SHSE.600000) 还是内部格式 (600000.SH)
            if left.upper() in cls.PREFIX_TO_SUFFIX:
                # 掘金格式 -> 内部格式
                prefix, code = left.upper(), right
                suffix = cls.PREFIX_TO_SUFFIX[prefix]
                return f"{code}.{suffix}"
            else:
                # 已经是内部格式，直接返回
                return f"{left}.{right.upper()}"
        elif len(parts) == 1:
            # 纯数字代码，自动推断交易所
            code = parts[0]
            suffix = cls._infer_suffix(code)
            return f"{code}.{suffix}"
        else:
            raise ValueError(f"无效的 symbol 格式: {symbol}")

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
