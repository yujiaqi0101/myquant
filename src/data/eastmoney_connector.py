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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        request_interval: float = 0.1,
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
                if self._request_interval > 0:
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

    def get_index_constituents(self, index_code: str, trade_date: str = None) -> pd.DataFrame:
        """
        获取指数成分股（来源：stk_get_index_constituents）

        Parameters
        ----------
        index_code : str
            指数代码（系统内部格式 000300.SH）
        trade_date : str
            交易日期 'YYYY-MM-DD'

        Returns
        -------
        pd.DataFrame
            包含列: index_code, stock_code, weight, trade_date, market_value_total, market_value_circ
        """
        from gm.api import stk_get_index_constituents

        # 转换为掘金格式
        mq_index = SymbolConverter.to_eastmoney(index_code)

        result = self._request_with_retry(
            stk_get_index_constituents,
            index=mq_index,
            trade_date=trade_date,
        )

        if result is None or (isinstance(result, pd.DataFrame) and result.empty):
            return pd.DataFrame()

        # 统一转为 DataFrame
        if not isinstance(result, pd.DataFrame):
            result = pd.DataFrame(result)

        # 转换代码格式并重命名列
        result['index_code'] = index_code
        result['stock_code'] = result['symbol'].apply(SymbolConverter.to_internal)
        result = result.rename(columns={
            'weight': 'weight',
            'trade_date': 'trade_date',
            'market_value_total': 'market_value_total',
            'market_value_circ': 'market_value_circ',
        })

        return result[['index_code', 'stock_code', 'weight', 'trade_date',
                        'market_value_total', 'market_value_circ']]

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

    def get_financial_deriv_batch(
        self,
        symbols: List[str],
        fields: str,
        date: str = None,
        max_fields_per_request: int = 20,
    ) -> pd.DataFrame:
        """
        分批获取财务衍生指标截面数据，每次最多请求 max_fields_per_request 个字段，
        然后按 symbol + pub_date + rpt_date 合并结果。

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            完整字段列表，逗号分隔
        date : str
            查询日期 'YYYY-MM-DD'
        max_fields_per_request : int
            每次请求最大字段数，默认 20

        Returns
        -------
        pd.DataFrame
            合并后的财务衍生指标数据
        """
        field_list = [f.strip() for f in fields.split(',') if f.strip()]
        if len(field_list) <= max_fields_per_request:
            return self.get_financial_deriv(symbols=symbols, fields=fields, date=date)

        # 分批请求
        merge_cols = ['symbol', 'pub_date', 'rpt_date']
        # 只保留 merge_cols + 本次请求的字段列，丢弃 API 额外返回的非指标列
        keep_cols = set(merge_cols + field_list)
        result_df = None

        for i in range(0, len(field_list), max_fields_per_request):
            batch_fields = ','.join(field_list[i:i + max_fields_per_request])
            logger.debug(f"财务数据分批请求字段 {i // max_fields_per_request + 1}: {batch_fields}")
            try:
                df = self.get_financial_deriv(symbols=symbols, fields=batch_fields, date=date)
                if df is not None and not df.empty:
                    # 只保留需要的列，丢弃 API 额外返回列（如 data_type, rpt_type）
                    cols = [c for c in df.columns if c in keep_cols]
                    df = df[cols]
                    if result_df is None:
                        result_df = df
                    else:
                        # 按 symbol + pub_date + rpt_date 合并
                        # 只保留新批次的数据列（非合并键列）
                        new_cols = [c for c in df.columns if c not in merge_cols]
                        result_df = result_df.merge(
                            df[merge_cols + new_cols],
                            on=merge_cols,
                            how='outer',
                        )
            except Exception as e:
                logger.warning(f"财务数据字段批次 {i // max_fields_per_request + 1} 请求失败: {e}")

        return result_df if result_df is not None else pd.DataFrame()

    def get_financial_prime(
        self,
        symbols: List[str],
        fields: str = 'eps_basic',
        date: str = None,
    ) -> pd.DataFrame:
        """
        获取财务主要指标截面数据

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段列表，如 'eps_basic,eps_dil,roe'
        date : str
            查询日期 'YYYY-MM-DD'

        Returns
        -------
        pd.DataFrame
            财务主要指标数据
        """
        from gm.api import stk_get_finance_prime_pt

        kwargs = dict(
            symbols=symbols,
            fields=fields,
            df=True,
        )
        if date:
            kwargs['date'] = date

        return self._request_with_retry(stk_get_finance_prime_pt, **kwargs)

    def get_financial_prime_batch(
        self,
        symbols: List[str],
        fields: str,
        date: str = None,
        max_fields_per_request: int = 20,
    ) -> pd.DataFrame:
        """
        分批获取财务主要指标截面数据，每次最多请求 max_fields_per_request 个字段，
        然后按 symbol + pub_date + rpt_date 合并结果。

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            完整字段列表，逗号分隔
        date : str
            查询日期 'YYYY-MM-DD'
        max_fields_per_request : int
            每次请求最大字段数，默认 20

        Returns
        -------
        pd.DataFrame
            合并后的财务主要指标数据
        """
        field_list = [f.strip() for f in fields.split(',') if f.strip()]
        if len(field_list) <= max_fields_per_request:
            return self.get_financial_prime(symbols=symbols, fields=fields, date=date)

        merge_cols = ['symbol', 'pub_date', 'rpt_date']
        # 只保留 merge_cols + 本次请求的字段列，丢弃 API 额外返回的非指标列
        keep_cols = set(merge_cols + field_list)
        result_df = None

        for i in range(0, len(field_list), max_fields_per_request):
            batch_fields = ','.join(field_list[i:i + max_fields_per_request])
            logger.debug(f"财务主要指标字段批次 {i // max_fields_per_request + 1}: {batch_fields}")
            try:
                df = self.get_financial_prime(symbols=symbols, fields=batch_fields, date=date)
                if df is not None and not df.empty:
                    # 只保留需要的列，丢弃 API 额外返回列（如 data_type, rpt_type）
                    cols = [c for c in df.columns if c in keep_cols]
                    df = df[cols]
                    if result_df is None:
                        result_df = df
                    else:
                        new_cols = [c for c in df.columns if c not in merge_cols]
                        result_df = result_df.merge(
                            df[merge_cols + new_cols],
                            on=merge_cols,
                            how='outer',
                        )
            except Exception as e:
                logger.warning(f"财务主要指标字段批次 {i // max_fields_per_request + 1} 请求失败: {e}")

        return result_df if result_df is not None else pd.DataFrame()

    def get_daily_valuation(
        self,
        symbol: str,
        fields: str = 'pb_mrq',
        start_date: str = None,
        end_date: str = None,
    ) -> pd.DataFrame:
        """
        获取估值指标时序数据（如 PB）

        Parameters
        ----------
        symbol : str
            掘金格式代码，单个标的，如 'SHSE.600000'
        fields : str
            字段列表，如 'pb_mrq,pe_ttm'
        start_date : str
            开始日期 'YYYY-MM-DD'
        end_date : str
            结束日期 'YYYY-MM-DD'

        Returns
        -------
        pd.DataFrame
            估值指标数据
        """
        from gm.api import stk_get_daily_valuation

        kwargs = dict(
            symbol=symbol,
            fields=fields,
            df=True,
        )
        if start_date:
            kwargs['start_date'] = start_date
        if end_date:
            kwargs['end_date'] = end_date

        return self._request_with_retry(stk_get_daily_valuation, **kwargs)

    def get_daily_valuation_pt(
        self,
        symbols: List[str],
        fields: str = 'pe_ttm',
        trade_date: str = None,
    ) -> pd.DataFrame:
        """
        获取估值指标截面数据（多标的单日），用于批量同步

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段列表
        trade_date : str
            交易日期 'YYYY-MM-DD'

        Returns
        -------
        pd.DataFrame
            估值指标截面数据
        """
        from gm.api import stk_get_daily_valuation_pt

        kwargs = dict(symbols=symbols, fields=fields, df=True)
        if trade_date:
            kwargs['trade_date'] = trade_date
        return self._request_with_retry(stk_get_daily_valuation_pt, **kwargs)

    def get_daily_valuation_batch(
        self,
        symbols: List[str],
        fields: str,
        start_date: str = None,
        end_date: str = None,
        max_fields_per_request: int = 20,
        max_workers: int = 5,
    ) -> pd.DataFrame:
        """
        并发获取估值指标时序数据：按标的遍历，使用线程池并发请求，
        每次最多请求 max_fields_per_request 个字段。

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            完整字段列表，逗号分隔
        start_date : str
            开始日期 'YYYY-MM-DD'
        end_date : str
            结束日期 'YYYY-MM-DD'
        max_fields_per_request : int
            每次请求最大字段数，默认 20
        max_workers : int
            并发线程数，默认 5

        Returns
        -------
        pd.DataFrame
            合并后的估值指标数据
        """
        field_list = [f.strip() for f in fields.split(',') if f.strip()]
        need_split = len(field_list) > max_fields_per_request
        # 只保留 merge_cols + 请求字段列，丢弃 API 额外返回列
        valuation_keep_cols = set(['symbol', 'trade_date'] + field_list)

        def _fetch_one(sym):
            """获取单个标的的估值数据"""
            try:
                if not need_split:
                    return self.get_daily_valuation(symbol=sym, fields=fields,
                                                     start_date=start_date, end_date=end_date)
                # 分批请求字段
                sym_result = None
                merge_cols = ['symbol', 'trade_date']
                for i in range(0, len(field_list), max_fields_per_request):
                    batch_fields = ','.join(field_list[i:i + max_fields_per_request])
                    df = self.get_daily_valuation(symbol=sym, fields=batch_fields,
                                                   start_date=start_date, end_date=end_date)
                    if df is not None and not df.empty:
                        # 只保留需要的列，丢弃 API 额外返回列
                        cols = [c for c in df.columns if c in valuation_keep_cols]
                        df = df[cols]
                        if sym_result is None:
                            sym_result = df
                        else:
                            new_cols = [c for c in df.columns if c not in merge_cols]
                            sym_result = sym_result.merge(
                                df[merge_cols + new_cols],
                                on=merge_cols,
                                how='outer',
                            )
                return sym_result
            except Exception as e:
                logger.debug(f"获取 {sym} 估值数据失败: {e}")
                return None

        all_dfs = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_one, sym): sym for sym in symbols}
            for future in as_completed(futures):
                try:
                    df = future.result()
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception as e:
                    sym = futures[future]
                    logger.debug(f"获取 {sym} 估值数据异常: {e}")

        if all_dfs:
            return pd.concat(all_dfs, ignore_index=True)
        return pd.DataFrame()

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

    def get_daily_mktvalue(
        self,
        symbol: str,
        fields: str = 'a_mv',
        start_date: str = None,
        end_date: str = None,
    ) -> pd.DataFrame:
        """
        获取市值指标时序数据（如流通市值）

        Parameters
        ----------
        symbol : str
            掘金格式代码，单个标的，如 'SHSE.600000'
        fields : str
            字段列表，如 'a_mv,tot_mv'
        start_date : str
            开始日期 'YYYY-MM-DD'
        end_date : str
            结束日期 'YYYY-MM-DD'

        Returns
        -------
        pd.DataFrame
            市值指标数据
        """
        from gm.api import stk_get_daily_mktvalue

        kwargs = dict(
            symbol=symbol,
            fields=fields,
            df=True,
        )
        if start_date:
            kwargs['start_date'] = start_date
        if end_date:
            kwargs['end_date'] = end_date

        return self._request_with_retry(stk_get_daily_mktvalue, **kwargs)

    def get_daily_mktvalue_pt(
        self,
        symbols: List[str],
        fields: str = 'a_mv',
        trade_date: str = None,
    ) -> pd.DataFrame:
        """
        获取市值指标截面数据（多标的单日），用于批量同步

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段列表
        trade_date : str
            交易日期 'YYYY-MM-DD'

        Returns
        -------
        pd.DataFrame
            市值指标截面数据
        """
        from gm.api import stk_get_daily_mktvalue_pt

        kwargs = dict(symbols=symbols, fields=fields, df=True)
        if trade_date:
            kwargs['trade_date'] = trade_date
        return self._request_with_retry(stk_get_daily_mktvalue_pt, **kwargs)

    def get_daily_mktvalue_batch(
        self,
        symbols: List[str],
        fields: str,
        start_date: str = None,
        end_date: str = None,
        max_workers: int = 5,
    ) -> pd.DataFrame:
        """
        并发获取市值指标时序数据：按标的遍历，使用线程池并发请求

        Parameters
        ----------
        symbols : List[str]
            掘金格式代码列表
        fields : str
            字段列表，逗号分隔
        start_date : str
            开始日期 'YYYY-MM-DD'
        end_date : str
            结束日期 'YYYY-MM-DD'
        max_workers : int
            并发线程数，默认 5

        Returns
        -------
        pd.DataFrame
            合并后的市值指标数据
        """
        def _fetch_one(sym):
            try:
                return self.get_daily_mktvalue(symbol=sym, fields=fields,
                                                start_date=start_date, end_date=end_date)
            except Exception as e:
                logger.debug(f"获取 {sym} 市值数据失败: {e}")
                return None

        all_dfs = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_one, sym): sym for sym in symbols}
            for future in as_completed(futures):
                try:
                    df = future.result()
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception as e:
                    sym = futures[future]
                    logger.debug(f"获取 {sym} 市值数据异常: {e}")

        if all_dfs:
            return pd.concat(all_dfs, ignore_index=True)
        return pd.DataFrame()

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
