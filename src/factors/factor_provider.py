"""
因子提供者抽象层
================

提供统一的因子数据获取接口，支持多数据源切换。

设计原则：
- 抽象基类 FactorProvider 定义统一接口
- 具体 Provider 实现对接不同数据源（东财掘金、本地数据库）
- 策略代码不感知底层 API，切换数据源零改动
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import logging
import pandas as pd

logger = logging.getLogger(__name__)


class FactorProvider(ABC):
    """
    因子数据提供者抽象基类

    所有具体 Provider 必须实现以下接口：
    - get_valuation: 获取估值因子（PB、PE等）
    - get_financial: 获取财务衍生因子（ROE等）
    - get_all_symbols: 获取全市场股票代码列表
    """

    @abstractmethod
    def get_valuation(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """
        获取估值因子

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段名，如 'pb_mrq', 'pe_ttm'
        date : str
            查询日期 'YYYY-MM-DD'

        Returns
        -------
        Dict[str, float]
            {stock_code: factor_value}
        """
        pass

    @abstractmethod
    def get_financial(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """
        获取财务衍生因子

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段名，如 'roe', 'roe_weight'
        date : str
            查询日期 'YYYY-MM-DD'

        Returns
        -------
        Dict[str, float]
            {stock_code: factor_value}
        """
        pass

    @abstractmethod
    def get_all_symbols(self) -> List[str]:
        """
        获取全市场股票代码列表

        Returns
        -------
        List[str]
            系统内部格式代码列表，如 ['000001.SZ', '600000.SH']
        """
        pass

    @abstractmethod
    def get_mktvalue(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """
        获取市值因子

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段名，如 'a_mv', 'tot_mv'
        date : str
            查询日期 'YYYY-MM-DD'

        Returns
        -------
        Dict[str, float]
            {stock_code: factor_value}
        """
        pass


class EastmoneyFactorProvider(FactorProvider):
    """
    东财掘金因子提供者

    调用 gm.api 获取真实财务数据，支持：
    - 估值因子：PB、PE_TTM 等（stk_get_daily_valuation）
    - 财务衍生因子：ROE 等（stk_get_finance_deriv_pt）

    适用于 data_source='eastmoney' 场景
    """

    def __init__(self):
        from src.data.eastmoney_connector import EastmoneyConnector
        from config.config import get_credentials

        token = get_credentials('eastmoney').get('token', '')
        self._connector = EastmoneyConnector(token=token)
        logger.info("EastmoneyFactorProvider 初始化完成")

    def get_valuation(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """获取估值因子（按标的遍历，取指定日期数据）"""
        from src.data.symbol_converter import SymbolConverter

        try:
            df = self._connector.get_daily_valuation_batch(
                symbols=symbols,
                fields=fields,
                start_date=date,
                end_date=date,
            )

            if df is None or df.empty:
                return {}

            result = {}
            for _, row in df.iterrows():
                code = SymbolConverter.to_internal(row['symbol'])
                result[code] = row.get(fields, float('nan'))

            return result

        except Exception as e:
            logger.error(f"获取估值因子失败: {e}")
            return {}

    def get_financial(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """获取财务衍生因子"""
        from src.data.symbol_converter import SymbolConverter

        try:
            df = self._connector.get_financial_deriv(
                symbols=symbols,
                fields=fields,
                date=date,
            )

            if df is None or df.empty:
                return {}

            result = {}
            for _, row in df.iterrows():
                code = SymbolConverter.to_internal(row['symbol'])
                result[code] = row.get(fields, float('nan'))

            return result

        except Exception as e:
            logger.error(f"获取财务衍生因子失败: {e}")
            return {}

    def get_all_symbols(self) -> List[str]:
        """获取全市场股票代码列表"""
        from src.data.symbol_converter import SymbolConverter

        try:
            df = self._connector.get_stock_list()
            if df is None or df.empty:
                return []
            return SymbolConverter.batch_to_internal(df['symbol'].tolist())
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return []

    def get_mktvalue(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """获取市值因子（按标的遍历，取指定日期数据）"""
        from src.data.symbol_converter import SymbolConverter

        try:
            df = self._connector.get_daily_mktvalue_batch(
                symbols=symbols,
                fields=fields,
                start_date=date,
                end_date=date,
            )

            if df is None or df.empty:
                return {}

            result = {}
            for _, row in df.iterrows():
                code = SymbolConverter.to_internal(row['symbol'])
                result[code] = row.get(fields, float('nan'))

            return result

        except Exception as e:
            logger.error(f"获取市值因子失败: {e}")
            return {}


class DatabaseFactorProvider(FactorProvider):
    """
    数据库因子提供者

    从本地 SQLite 数据库获取因子值，支持：
    - 估值因子：从 t_valuation_data 读取（PB、PE 等）
    - 财务因子：从 t_finance_prime 读取（ROE、营收增长等）
    - 市值因子：从 t_valuation_data 读取（流通市值等）
    """

    def __init__(self, db_path: str):
        from src.data.database import DatabaseManager

        self._db = DatabaseManager(db_path)
        logger.info(f"DatabaseFactorProvider 初始化完成: {db_path}")

    def get_valuation(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """从 t_valuation_data 获取估值因子"""
        # 字段映射：因子field名 → 数据库列名
        field_map = {
            'pb_mrq': 'pb_mrq',
            'pe_ttm': 'pe_ttm',
            'pe_lyr': 'pe_lyr',
            'pe_mrq': 'pe_mrq',
            'ps_ttm': 'ps_ttm',
            'ps_lyr': 'ps_lyr',
            'pcf_ttm_oper': 'pcf_ttm_oper',
            'pcf_ttm_ncf': 'pcf_ttm_ncf',
            'pcf_lyr_oper': 'pcf_lyr_oper',
            'pcf_lyr_ncf': 'pcf_lyr_ncf',
            'dv_ratio': 'dv_ratio',
            'dv_ttm': 'dv_ttm',
        }
        col = field_map.get(fields, fields)
        return self._query_valuation(col, date, symbols)

    def get_financial(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """从 t_finance_prime 获取财务因子"""
        # 字段映射：因子field名 → 数据库列名
        field_map = {
            'roe': 'roe_weight_avg',      # roe列常为NULL，用roe_weight_avg替代
            'roe_weight': 'roe_weight_avg',
            'roe_cut': 'roe_cut',
            'roa': 'roa',
            'gross_margin': 'gross_margin',
            'net_margin': 'net_margin',
            'net_prof_yoy': 'net_prof_pcom_yoy',
            'inc_oper_yoy': 'inc_oper_yoy',
            'ttl_inc_oper_yoy': 'ttl_inc_oper_yoy',
            'eps_yoy': 'eps_yoy',
        }
        col = field_map.get(fields, fields)
        return self._query_financial(col, date, symbols)

    def get_all_symbols(self) -> List[str]:
        """获取全市场股票代码列表"""
        try:
            info = self._db.get_stock_info()
            if info.empty:
                return []
            return info['stock_code'].tolist()
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return []

    def get_mktvalue(self, symbols: List[str], fields: str, date: str) -> Dict[str, float]:
        """从 t_valuation_data 获取市值因子"""
        # 字段映射：市值因子field → 数据库列名
        field_map = {
            'a_mv': 'circ_mv',        # A股流通市值
            'tot_mv': 'market_cap',    # 总市值
            'total_mv': 'total_mv',    # 总市值
            'circ_mv': 'circ_mv',      # 流通市值
        }
        col = field_map.get(fields, fields)
        return self._query_valuation(col, date, symbols)

    def _query_valuation(self, col: str, date: str, symbols: List[str] = None) -> Dict[str, float]:
        """查询 t_valuation_data 表，若指定日期无数据则回退到最近可用日期"""
        try:
            with self._db.get_connection() as conn:
                # symbols 是掘金格式（如 SHSE.600000），需转为内部格式
                if symbols:
                    internal_codes = [self._gm_to_internal(s) for s in symbols]
                    placeholders = ','.join(['?'] * len(internal_codes))
                    sql = f"SELECT stock_code, {col} FROM t_valuation_data WHERE trade_date = ? AND stock_code IN ({placeholders})"
                    params = [date] + internal_codes
                else:
                    sql = f"SELECT stock_code, {col} FROM t_valuation_data WHERE trade_date = ?"
                    params = [date]

                df = pd.read_sql(sql, conn, params=params)

                # 若指定日期无数据，回退到最近可用日期
                if df.empty:
                    fallback_sql = f"SELECT MAX(trade_date) FROM t_valuation_data WHERE trade_date <= ?"
                    fallback_date = pd.read_sql(fallback_sql, conn, params=[date]).iloc[0, 0]
                    if fallback_date is None:
                        # 尝试最近的日期（不限 <= date）
                        fallback_sql2 = f"SELECT MAX(trade_date) FROM t_valuation_data"
                        fallback_date = pd.read_sql(fallback_sql2, conn).iloc[0, 0]
                    if fallback_date is not None:
                        logger.debug(f"估值数据 {date} 无记录，回退到 {fallback_date}")
                        if symbols:
                            sql = f"SELECT stock_code, {col} FROM t_valuation_data WHERE trade_date = ? AND stock_code IN ({placeholders})"
                            params = [fallback_date] + internal_codes
                        else:
                            sql = f"SELECT stock_code, {col} FROM t_valuation_data WHERE trade_date = ?"
                            params = [fallback_date]
                        df = pd.read_sql(sql, conn, params=params)

                if df.empty:
                    return {}

                result = {}
                for _, row in df.iterrows():
                    val = row[col]
                    if pd.notna(val):
                        result[row['stock_code']] = float(val)
                return result

        except Exception as e:
            logger.error(f"查询估值数据失败 ({col}, {date}): {e}")
            return {}

    def _query_financial(self, col: str, date: str, symbols: List[str] = None) -> Dict[str, float]:
        """查询 t_finance_prime 表，取指定日期前最近一期报表"""
        try:
            with self._db.get_connection() as conn:
                # t_finance_prime.stock_code 是掘金格式（SHSE.600000），需用掘金格式匹配
                if symbols:
                    # symbols 已经是掘金格式
                    placeholders = ','.join(['?'] * len(symbols))
                    sql = f"""
                        SELECT f.stock_code, f.{col}
                        FROM t_finance_prime f
                        INNER JOIN (
                            SELECT stock_code, MAX(rpt_date) as max_rpt
                            FROM t_finance_prime
                            WHERE rpt_date <= ? AND stock_code IN ({placeholders})
                            GROUP BY stock_code
                        ) latest ON f.stock_code = latest.stock_code AND f.rpt_date = latest.max_rpt
                        WHERE f.stock_code IN ({placeholders})
                    """
                    params = [date] + list(symbols) + list(symbols)
                else:
                    sql = f"""
                        SELECT f.stock_code, f.{col}
                        FROM t_finance_prime f
                        INNER JOIN (
                            SELECT stock_code, MAX(rpt_date) as max_rpt
                            FROM t_finance_prime
                            WHERE rpt_date <= ?
                            GROUP BY stock_code
                        ) latest ON f.stock_code = latest.stock_code AND f.rpt_date = latest.max_rpt
                    """
                    params = [date]

                df = pd.read_sql(sql, conn, params=params)

                if df.empty:
                    return {}

                result = {}
                for _, row in df.iterrows():
                    val = row[col]
                    if pd.notna(val):
                        # stock_code 是掘金格式，转为内部格式
                        internal_code = self._gm_to_internal(row['stock_code'])
                        result[internal_code] = float(val)
                return result

        except Exception as e:
            logger.error(f"查询财务数据失败 ({col}, {date}): {e}")
            return {}

    @staticmethod
    def _gm_to_internal(gm_code: str) -> str:
        """掘金格式 → 内部格式：SHSE.600000 → 600000.SH"""
        if '.' in gm_code:
            prefix, code = gm_code.split('.', 1)
            suffix = 'SH' if prefix == 'SHSE' else 'SZ'
            return f"{code}.{suffix}"
        return gm_code
