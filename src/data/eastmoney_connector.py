"""
东财掘金 API 连接器

封装 gm.api 调用，处理：
- 认证（set_token）
- 流控（单次最大 33000 条，请求间隔）
- 重试机制
- 数据格式转换
"""

import logging
import time
from typing import List, Optional

import pandas as pd

from .symbol_converter import SymbolConverter

logger = logging.getLogger(__name__)


class EastmoneyConnector:
    """东财掘金 API 连接器"""

    def __init__(
        self,
        token: str,
        max_rows: int = 33000,
        request_interval: float = 0.5,
        retry_attempts: int = 3,
        retry_interval: float = 2.0,
    ):
        self._token = token
        self._max_rows = max_rows
        self._request_interval = request_interval
        self._retry_attempts = retry_attempts
        self._retry_interval = retry_interval
        self._connected = False

    def connect(self) -> bool:
        """认证连接"""
        try:
            from gm.api import set_token
            set_token(self._token)
            self._connected = True
            logger.info("东财掘金 API 认证成功")
            return True
        except Exception as e:
            logger.error(f"东财掘金 API 认证失败: {e}")
            self._connected = False
            return False

    def _ensure_connected(self):
        """确保已连接"""
        if not self._connected:
            self.connect()

    def _request_with_retry(self, func, *args, **kwargs):
        """带重试的请求"""
        self._ensure_connected()
        last_error = None
        for attempt in range(self._retry_attempts):
            try:
                result = func(*args, **kwargs)
                time.sleep(self._request_interval)  # 流控
                return result
            except Exception as e:
                last_error = e
                logger.warning(f"请求失败 (第{attempt+1}次): {e}")
                if attempt < self._retry_attempts - 1:
                    time.sleep(self._retry_interval)
        raise ConnectionError(f"东财掘金 API 请求失败（已重试{self._retry_attempts}次）: {last_error}")

    def get_history(
        self,
        symbol: str,
        frequency: str = '1d',
        start_time: str = None,
        end_time: str = None,
        fields: str = None,
        adjust: int = 1,
    ) -> pd.DataFrame:
        """
        获取历史行情（自动分页处理 33000 条限制）

        Parameters
        ----------
        symbol : str
            掘金格式代码，如 'SHSE.600000'
        frequency : str
            频率: '1d', '60s', '300s' 等
        start_time : str
            开始时间 'YYYY-MM-DD HH:MM:SS'
        end_time : str
            结束时间
        fields : str
            字段列表
        adjust : int
            复权方式: 0=不复权, 1=前复权, 2=后复权

        Returns
        -------
        pd.DataFrame
            历史行情数据
        """
        from gm.api import history

        df = self._request_with_retry(
            history,
            symbol=symbol,
            frequency=frequency,
            start_time=start_time,
            end_time=end_time,
            fields=fields,
            adjust=adjust,
            df=True,
        )
        return df

    def get_history_n(
        self,
        symbol: str,
        frequency: str = '1d',
        count: int = 100,
        end_time: str = None,
        fields: str = None,
        adjust: int = 1,
    ) -> pd.DataFrame:
        """
        获取历史行情最新 N 条

        Parameters
        ----------
        symbol : str
            掘金格式代码，如 'SHSE.600000'
        frequency : str
            频率
        count : int
            数量
        end_time : str
            结束时间
        fields : str
            字段列表
        adjust : int
            复权方式

        Returns
        -------
        pd.DataFrame
            历史行情数据
        """
        from gm.api import history_n

        df = self._request_with_retry(
            history_n,
            symbol=symbol,
            frequency=frequency,
            count=count,
            end_time=end_time,
            fields=fields,
            adjust=adjust,
            df=True,
        )
        return df

    def get_stock_list(self, trade_date: str = None) -> pd.DataFrame:
        """
        获取 A 股股票列表

        Parameters
        ----------
        trade_date : str, optional
            交易日期，默认最新

        Returns
        -------
        pd.DataFrame
            股票列表
        """
        from gm.api import get_symbols

        kwargs = dict(
            sec_type1=1010,       # 股票
            sec_type2=101001,     # A 股
            skip_suspended=False,  # 不跳过停牌
            skip_st=False,         # 不跳过 ST
            df=True,
        )
        if trade_date:
            kwargs['trade_date'] = trade_date

        return self._request_with_retry(get_symbols, **kwargs)

    def get_symbol_infos(self, symbols: List[str] = None) -> pd.DataFrame:
        """
        获取标的基本信息

        Parameters
        ----------
        symbols : List[str], optional
            掘金格式代码列表

        Returns
        -------
        pd.DataFrame
            标的基本信息
        """
        from gm.api import get_symbol_infos

        kwargs = dict(sec_type1=1010, df=True)
        if symbols:
            kwargs['symbols'] = symbols

        return self._request_with_retry(get_symbol_infos, **kwargs)

    def get_index_constituents(self, index_code: str, trade_date: str = None) -> List[str]:
        """
        获取指数成分股

        Parameters
        ----------
        index_code : str
            指数代码（系统内部格式 000300.SH）
        trade_date : str
            交易日期 'YYYY-MM-DD'

        Returns
        -------
        List[str]
            成分股代码列表（系统内部格式）
        """
        from gm.api import stk_get_index_constituents

        # 转换为掘金格式
        mq_index = SymbolConverter.to_eastmoney(index_code)

        result = self._request_with_retry(
            stk_get_index_constituents,
            index=mq_index,
            trade_date=trade_date,
        )

        if result is None:
            return []

        # 转换回系统内部格式
        if isinstance(result, pd.DataFrame):
            return SymbolConverter.batch_to_internal(result['symbol'].tolist())
        elif isinstance(result, list):
            return SymbolConverter.batch_to_internal(
                [item['symbol'] for item in result]
            )
        return []

    def get_trading_dates(
        self,
        start_year: int,
        end_year: int,
        exchange: str = 'SHSE'
    ) -> List[str]:
        """
        获取交易日历

        Parameters
        ----------
        start_year : int
            开始年份
        end_year : int
            结束年份
        exchange : str
            交易所代码

        Returns
        -------
        List[str]
            交易日列表
        """
        from gm.api import get_trading_dates_by_year

        df = self._request_with_retry(
            get_trading_dates_by_year,
            exchange=exchange,
            start_year=start_year,
            end_year=end_year,
        )

        if df is None or df.empty:
            return []

        # 过滤出实际交易日（trade_date 列非空）
        trade_dates = df[df['trade_date'] != '']['trade_date'].tolist()
        return trade_dates

    def get_financial_deriv(
        self,
        symbols: List[str],
        fields: str = 'roe',
        date: str = None,
    ) -> pd.DataFrame:
        """
        获取财务衍生指标截面数据（如 ROE）

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段列表，如 'roe,roe_weight'
        date : str
            查询日期 'YYYY-MM-DD'

        Returns
        -------
        pd.DataFrame
            财务衍生指标数据
        """
        from gm.api import stk_get_finance_deriv_pt

        kwargs = dict(
            symbols=symbols,
            fields=fields,
            df=True,
        )
        if date:
            kwargs['date'] = date

        return self._request_with_retry(stk_get_finance_deriv_pt, **kwargs)

    def get_daily_valuation(
        self,
        symbols: List[str],
        fields: str = 'pb_mrq',
        trade_date: str = None,
    ) -> pd.DataFrame:
        """
        获取估值指标单日截面数据（如 PB）

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段列表，如 'pb_mrq,pe_ttm'
        trade_date : str
            查询日期 'YYYY-MM-DD'

        Returns
        -------
        pd.DataFrame
            估值指标数据
        """
        from gm.api import stk_get_daily_valuation_pt

        kwargs = dict(
            symbols=symbols,
            fields=fields,
            df=True,
        )
        if trade_date:
            kwargs['trade_date'] = trade_date

        return self._request_with_retry(stk_get_daily_valuation_pt, **kwargs)

    def get_money_flow(
        self,
        symbols: List[str],
        trade_date: str = None,
    ) -> pd.DataFrame:
        """
        获取个股资金流向数据

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        trade_date : str
            查询日期 'YYYY-MM-DD'

        Returns
        -------
        pd.DataFrame
            字段: symbol, main_net_in, main_in, main_out, main_net_in_rate 等
        """
        from gm.api import stk_get_money_flow

        kwargs = dict(
            symbols=symbols,
            df=True,
        )
        if trade_date:
            kwargs['trade_date'] = trade_date

        return self._request_with_retry(stk_get_money_flow, **kwargs)

    def get_industry_category(
        self,
        source: str = 'sw2021',
        level: int = 1,
    ) -> pd.DataFrame:
        """
        获取行业分类列表

        Parameters
        ----------
        source : str
            行业来源，'sw2021'(申万2021) 或 'zjh2012'(证监会2012)
        level : int
            行业分级，1/2/3

        Returns
        -------
        pd.DataFrame
            字段: industry_code, industry_name
        """
        from gm.api import stk_get_industry_category

        return self._request_with_retry(
            stk_get_industry_category,
            source=source,
            level=level,
            df=True,
        )

    def get_industry_constituents(
        self,
        industry_code: str,
        date: str = None,
    ) -> pd.DataFrame:
        """
        获取行业成分股

        Parameters
        ----------
        industry_code : str
            行业代码
        date : str, optional
            查询日期，None 表示最新

        Returns
        -------
        pd.DataFrame
            字段: symbol, sec_name, date_in, date_out
        """
        from gm.api import stk_get_industry_constituents

        kwargs = dict(
            industry_code=industry_code,
            df=True,
        )
        if date:
            kwargs['date'] = date

        return self._request_with_retry(stk_get_industry_constituents, **kwargs)
