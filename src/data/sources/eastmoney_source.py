"""
东财掘金数据源
==============

封装 EastmoneyConnector，对齐 DataSource 基类。
东财是主数据源，支持：股票/ETF/指数/财务/估值/交易日/除权除息/板块信息。
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

import pandas as pd

from .base import DataSource
from ..symbol_converter import SymbolConverter

logger = logging.getLogger(__name__)


class EastmoneySource(DataSource):
    """
    东财掘金数据源（主数据源）

    封装现有 EastmoneyConnector，对齐 DataSource 接口。
    """

    def __init__(self, token: str = None):
        super().__init__(name='eastmoney')
        self._token = token
        self._connector = None

    def connect(self) -> bool:
        from ..eastmoney_connector import EastmoneyConnector
        if not self._token:
            from config.config import get_credentials
            creds = get_credentials('eastmoney')
            self._token = creds.get('token', '')
        if not self._token:
            logger.warning("未配置 eastmoney token")
            return False
        self._connector = EastmoneyConnector(token=self._token)
        self._connected = self._connector.connect()
        return self._connected

    def disconnect(self) -> None:
        self._connector = None
        self._connected = False

    def _ensure_connected(self):
        if not self._connected or self._connector is None:
            if not self.connect():
                raise ConnectionError("东财掘金连接失败")

    # ============ 交易日历 ============

    def get_trading_dates(self, start_year: int, end_year: int, **kwargs) -> List[str]:
        self._ensure_connected()
        return self._connector.get_trading_dates(
            start_year=start_year, end_year=end_year,
            exchange=kwargs.get('exchange', 'SHSE'),
        )

    # ============ 股票 ============

    def get_stock_list(self, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        return self._connector.get_stock_list(trade_date=kwargs.get('trade_date'))

    def get_stock_info(self, symbols: List[str] = None, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        # get_symbol_infos 支持 sec_type2 参数
        from gm.api import get_symbol_infos
        sec_type2 = kwargs.get('sec_type2', 101001)  # 默认 A 股
        em_symbols = SymbolConverter.batch_to_eastmoney(symbols) if symbols else None
        return self._connector.get_symbol_infos(symbols=em_symbols)

    @staticmethod
    def _format_date(dt_str: str, time_suffix: str) -> str:
        """将日期字符串转为掘金 API 要求的格式: YYYY-MM-DD HH:MM:SS"""
        if not dt_str:
            return dt_str
        if ' ' in dt_str:
            return dt_str  # 已包含时间部分
        # YYYYMMDD -> YYYY-MM-DD
        if len(dt_str) == 8 and dt_str.isdigit():
            dt_str = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]}"
        return f"{dt_str} {time_suffix}"

    def get_stock_daily(self, symbol: str, start_date: str = None,
                        end_date: str = None, adjust: int = 1, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        em_symbol = SymbolConverter.to_eastmoney(symbol)
        start_time = self._format_date(start_date, '00:00:00')
        end_time = self._format_date(end_date, '23:59:59')
        return self._connector.get_history(
            symbol=em_symbol, frequency='1d',
            start_time=start_time, end_time=end_time,
            adjust=adjust,
        )

    def get_stock_daily_batch(self, symbols: List[str], start_date: str = None,
                              end_date: str = None, adjust: int = 1, **kwargs) -> Dict[str, pd.DataFrame]:
        """批量获取股票日K线数据（并发请求）"""
        self._ensure_connected()
        from concurrent.futures import ThreadPoolExecutor, as_completed

        result = {}
        max_workers = kwargs.get('max_workers', 5)

        def _fetch_one(symbol):
            try:
                df = self.get_stock_daily(symbol, start_date=start_date,
                                          end_date=end_date, adjust=adjust)
                return symbol, df
            except Exception as e:
                logger.debug(f"获取 {symbol} 日K线失败: {e}")
                return symbol, None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_one, s): s for s in symbols}
            for future in as_completed(futures):
                symbol, df = future.result()
                if df is not None and not df.empty:
                    result[symbol] = df

        return result

    # ============ ETF ============

    def get_etf_list(self, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        from gm.api import get_symbols
        return self._connector._request_with_retry(
            get_symbols, sec_type1=1020, sec_type2=102001, df=True,
        )

    def get_etf_info(self, symbols: List[str] = None, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        em_symbols = SymbolConverter.batch_to_eastmoney(symbols) if symbols else None
        return self._connector.get_symbol_infos(symbols=em_symbols)

    def get_etf_daily(self, symbol: str, start_date: str = None,
                      end_date: str = None, adjust: int = 1, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        em_symbol = SymbolConverter.to_eastmoney(symbol)
        start_time = self._format_date(start_date, '00:00:00')
        end_time = self._format_date(end_date, '23:59:59')
        return self._connector.get_history(
            symbol=em_symbol, frequency='1d',
            start_time=start_time, end_time=end_time,
            adjust=adjust,
        )

    # ============ 指数 ============

    def get_index_list(self, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        from gm.api import get_symbols
        return self._connector._request_with_retry(
            get_symbols, sec_type1=1060, sec_type2=106001, df=True,
        )

    def get_index_info(self, symbols: List[str] = None, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        em_symbols = SymbolConverter.batch_to_eastmoney(symbols) if symbols else None
        return self._connector.get_symbol_infos(symbols=em_symbols)

    def get_index_daily(self, symbol: str, start_date: str = None,
                        end_date: str = None, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        em_symbol = SymbolConverter.to_eastmoney(symbol)
        start_time = self._format_date(start_date, '00:00:00')
        end_time = self._format_date(end_date, '23:59:59')
        return self._connector.get_history(
            symbol=em_symbol, frequency='1d',
            start_time=start_time, end_time=end_time,
        )

    def get_index_constituents(self, index_code: str, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        return self._connector.get_index_constituents(
            index_code=index_code, trade_date=kwargs.get('trade_date'),
        )

    # ============ 板块 ============

    def get_sector_list(self, **kwargs) -> List[str]:
        self._ensure_connected()
        # 东财提供概念板块列表
        df = self._connector.get_symbol_infos(symbols=None)
        if df is not None and not df.empty:
            # sec_type2=107001 为概念板块
            from gm.api import get_symbols
            df = self._connector._request_with_retry(
                get_symbols, sec_type1=1070, sec_type2=107001, df=True,
            )
            if df is not None and not df.empty:
                return df['symbol'].tolist() if 'symbol' in df.columns else []
        return []

    def get_sector_info(self, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        from gm.api import get_symbols
        return self._connector._request_with_retry(
            get_symbols, sec_type1=1070, sec_type2=107001, df=True,
        )

    # ============ 财务 ============

    def get_financial_data(self, symbols: List[str], start_date: str = None,
                           end_date: str = None, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        em_symbols = SymbolConverter.batch_to_eastmoney(symbols) if symbols else None
        # stk_get_finance_prime_pt 是截面查询，需要 date 参数
        date = kwargs.get('date')
        if not date and end_date:
            # 将 YYYYMMDD 转为 YYYY-MM-DD
            date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date

        # 财务主要指标完整字段（对齐东财 stk_get_finance_prime_pt 文档）
        # 每次最多请求 20 个字段，需要分批请求再合并
        all_fields = kwargs.get('fields', ','.join([
            # 第1批: 每股指标 + 资产负债表关键项 + 利润表关键项 + ROE系列 (20字段)
            'eps_basic', 'eps_dil', 'eps_basic_cut', 'eps_dil_cut',
            'net_cf_oper_ps', 'bps_pcom_ps',
            'ttl_ast', 'ttl_liab', 'share_cptl',
            'ttl_inc_oper', 'inc_oper', 'oper_prof', 'ttl_prof',
            'ttl_eqy_pcom', 'net_prof_pcom', 'net_prof_pcom_cut',
            'roe', 'roe_weight_avg', 'roe_cut', 'roe_weight_avg_cut',
            # 第2批: 现金流 + 同比指标 + 其他每股指标 (9字段)
            'net_cf_oper', 'eps_yoy', 'inc_oper_yoy', 'ttl_inc_oper_yoy',
            'net_prof_pcom_yoy', 'bps_sh', 'net_asset', 'net_prof', 'net_prof_cut',
        ]))

        return self._connector.get_financial_prime_batch(
            symbols=em_symbols or [],
            fields=all_fields,
            date=date,
        )

    # ============ 财务衍生指标 ============

    def get_finance_deriv_data(self, symbols: List[str], start_date: str = None,
                                end_date: str = None, **kwargs) -> pd.DataFrame:
        """
        获取财务衍生指标截面数据（stk_get_finance_deriv_pt，多标的单日截面）

        字段以 stk_get_finance_deriv 的字段为准（共142个财务衍生指标）。
        接口每次最多请求20个字段，需要分批请求再合并（共8批：7批×20 + 1批×2）。

        Parameters
        ----------
        symbols : List[str]
            股票代码列表（内部格式 600000.SH）
        start_date : str, optional
            开始日期（未使用，保留接口兼容）
        end_date : str, optional
            结束日期，作为截面查询的 date 参数（YYYYMMDD 或 YYYY-MM-DD）
        kwargs : dict
            可通过 fields 自定义字段列表

        Returns
        -------
        pd.DataFrame
            合并后的财务衍生指标数据
        """
        self._ensure_connected()
        em_symbols = SymbolConverter.batch_to_eastmoney(symbols) if symbols else []

        # 财务衍生指标完整字段（对齐东财 stk_get_finance_deriv 文档，共142个字段）
        all_fields = kwargs.get('fields', [
            # 每股指标 (19)
            'eps_basic', 'eps_dil2', 'eps_dil', 'eps_basic_cut', 'eps_dil2_cut', 'eps_dil_cut',
            'bps', 'net_cf_oper_ps', 'ttl_inc_oper_ps', 'inc_oper_ps', 'ebit_ps',
            'cptl_rsv_ps', 'sur_rsv_ps', 'retain_prof_ps', 'retain_inc_ps',
            'net_cf_ps', 'fcff_ps', 'fcfe_ps', 'ebitda_ps',
            # ROE系列 + 现金流比率 + 同比增长 (20)
            'roe', 'roe_weight', 'roe_avg', 'roe_cut', 'roe_weight_cut', 'ocf_toi',
            'eps_dil_yoy', 'net_cf_oper_ps_yoy', 'ttl_inc_oper_yoy', 'inc_oper_yoy',
            'oper_prof_yoy', 'ttl_prof_yoy', 'net_prof_pcom_yoy', 'net_prof_pcom_cut_yoy',
            'net_cf_oper_yoy', 'roe_yoy', 'net_asset_yoy', 'ttl_liab_yoy',
            'ttl_asset_yoy', 'net_cash_flow_yoy',
            # 增长率(年初) + 债务股权比 + EBIT/EBITDA + 利润 (20)
            'bps_gr_begin_year', 'ttl_asset_gr_begin_year', 'ttl_eqy_pcom_gr_begin_year',
            'net_debt_eqy_ev', 'int_debt_eqy_ev', 'eps_bas_yoy',
            'ebit', 'ebitda', 'ebit_inverse', 'ebitda_inverse',
            'nr_prof_loss', 'net_prof_cut', 'gross_prof', 'oper_net_inc', 'val_chg_net_inc',
            'exp_rd', 'ttl_inv_cptl', 'work_cptl', 'net_work_cptl', 'tg_asset',
            # 留存收益 + 债务 + 现金流 + 杜邦 + 利润比率 + ROA/ROIC (20)
            'retain_inc', 'int_debt', 'net_debt', 'curr_liab_non_int', 'ncur_liab_non_int',
            'fcff', 'fcfe', 'cur_depr_amort', 'eqy_mult_dupont',
            'net_prof_pcom_np', 'net_prof_tp', 'ttl_prof_ebit',
            'roe_cut_avg', 'roe_add', 'roe_ann', 'roa', 'roa_ann', 'jroa', 'jroa_ann', 'roic',
            # 销售利润率 + 费用率 + EBITDA比率 (20)
            'sale_npm', 'sale_gpm', 'sale_cost_rate', 'sale_exp_rate',
            'net_prof_toi', 'oper_prof_toi', 'ebit_toi', 'ttl_cost_oper_toi',
            'exp_oper_toi', 'exp_admin_toi', 'exp_fin_toi', 'ast_impr_loss_toi', 'ebitda_toi',
            'oper_net_inc_tp', 'val_chg_net_inc_tp', 'net_exp_noper_tp', 'inc_tax_tp',
            'net_prof_cut_np', 'eqy_mult', 'curr_ast_ta',
            # 资产结构 + 负债结构 + 偿债能力 (20)
            'ncurr_ast_ta', 'tg_ast_ta', 'ttl_eqy_pcom_tic', 'int_debt_tic',
            'curr_liab_tl', 'ncurr_liab_tl', 'ast_liab_rate', 'quick_rate', 'curr_rate',
            'cons_quick_rate', 'liab_eqy_rate', 'ttl_eqy_pcom_tl', 'ttl_eqy_pcom_debt',
            'tg_ast_tl', 'tg_ast_int_debt', 'tg_ast_net_debt',
            'ebitda_tl', 'net_cf_oper_tl', 'net_cf_oper_int_debt', 'net_cf_oper_curr_liab',
            # 现金流/负债 + 利息保障 + 营业周期 + 周转率 (20)
            'net_cf_oper_net_liab', 'ebit_int_cover', 'long_liab_work_cptl', 'ebitda_int_debt',
            'oper_cycle', 'inv_turnover_days', 'acct_rcv_turnover_days',
            'inv_turnover_rate', 'acct_rcv_turnover_rate',
            'curr_ast_turnover_rate', 'fix_ast_turnover_rate', 'ttl_ast_turnover_rate',
            'cash_rcv_sale_oi', 'net_cf_oper_oi', 'net_cf_oper_oni', 'cptl_exp_da', 'cash_rate',
            'acct_pay_turnover_days', 'acct_pay_turnover_rate', 'net_oper_cycle',
            'ttl_cost_oper_yoy',
            # 同比增长率 (2)
            'net_prof_yoy', 'net_cf_oper_np',
        ])

        # 如果传入的是逗号分隔字符串，转为列表
        if isinstance(all_fields, str):
            all_fields = [f.strip() for f in all_fields.split(',') if f.strip()]

        # 截面查询日期：使用 end_date 作为 date 参数
        date = kwargs.get('date')
        if not date and end_date:
            # YYYYMMDD -> YYYY-MM-DD
            date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date

        # 分批：每批最多20个字段
        batch_size = 20
        merge_cols = ['symbol', 'pub_date', 'rpt_date']
        # 只保留 merge_cols + 请求字段列，丢弃 API 额外返回列
        keep_cols = set(merge_cols + all_fields)
        result_df = None

        for i in range(0, len(all_fields), batch_size):
            batch_fields = all_fields[i:i + batch_size]
            fields_str = ','.join(batch_fields)

            df = self._connector.get_financial_deriv(
                symbols=em_symbols,
                fields=fields_str,
                date=date,
            )

            if df is not None and not df.empty:
                # 只保留需要的列，丢弃 API 额外返回列（如 data_type, rpt_type）
                cols = [c for c in df.columns if c in keep_cols]
                df = df[cols]
                if result_df is None:
                    result_df = df
                else:
                    # 按 symbol + pub_date + rpt_date 合并
                    new_cols = [c for c in df.columns if c not in merge_cols]
                    result_df = result_df.merge(
                        df[merge_cols + new_cols],
                        on=merge_cols,
                        how='outer',
                    )

        return result_df if result_df is not None else pd.DataFrame()

    # ============ 估值 ============

    def get_valuation_data(self, symbols: List[str], start_date: str = None,
                           end_date: str = None, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        em_symbols = SymbolConverter.batch_to_eastmoney(symbols) if symbols else None

        # 估值指标完整字段（对齐东财 stk_get_daily_valuation_pt）
        # 每次最多请求 20 个字段，需要分批请求再合并（共30个指标字段）
        all_fields = kwargs.get('fields', ','.join([
            # 第1批: PE/PB/PCF (19字段)
            'pe_ttm', 'pe_lyr', 'pe_mrq', 'pe_1q', 'pe_2q', 'pe_3q',
            'pe_ttm_cut', 'pe_lyr_cut', 'pe_mrq_cut',
            'pe_1q_cut', 'pe_2q_cut', 'pe_3q_cut',
            'pb_lyr', 'pb_mrq',
            'pcf_ttm_oper', 'pcf_ttm_ncf', 'pcf_lyr_oper', 'pcf_lyr_ncf',
            # 第2批: PS/PEG/DY (11字段)
            'ps_ttm', 'ps_lyr', 'ps_mrq', 'ps_1q', 'ps_2q', 'ps_3q',
            'peg_lyr', 'peg_1q', 'peg_2q', 'peg_3q',
            'dy_ttm', 'dy_lfy',
        ]))

        return self._connector.get_daily_valuation_batch(
            symbols=em_symbols or [],
            fields=all_fields,
            start_date=start_date,
            end_date=end_date,
        )

    def get_daily_valuation_pt_data(self, symbols: List[str], trade_date: str,
                                     **kwargs) -> pd.DataFrame:
        """
        获取单日估值指标截面数据（stk_get_daily_valuation_pt，多标的单日）

        用于批量同步：按交易日遍历，每天一次请求获取所有标的数据。
        注意：该接口每次最多请求20个字段，超过需分批请求再合并。
        """
        self._ensure_connected()
        em_symbols = SymbolConverter.batch_to_eastmoney(symbols) if symbols else []

        all_fields = kwargs.get('fields', [
            # PE系列 (12)
            'pe_ttm', 'pe_lyr', 'pe_mrq', 'pe_1q', 'pe_2q', 'pe_3q',
            'pe_ttm_cut', 'pe_lyr_cut', 'pe_mrq_cut',
            'pe_1q_cut', 'pe_2q_cut', 'pe_3q_cut',
            # PB系列 (3)
            'pb_lyr', 'pb_mrq',
            # PCF系列 (4)
            'pcf_ttm_oper', 'pcf_ttm_ncf', 'pcf_lyr_oper', 'pcf_lyr_ncf',
            # PS系列 (6)
            'ps_ttm', 'ps_lyr', 'ps_mrq',
            'ps_1q', 'ps_2q', 'ps_3q',
            # PEG系列 (4)
            'peg_lyr', 'peg_1q', 'peg_2q', 'peg_3q',
            # 股息率 (2)
            'dy_ttm', 'dy_lfy',
        ])

        # 如果传入的是逗号分隔字符串，转为列表
        if isinstance(all_fields, str):
            all_fields = [f.strip() for f in all_fields.split(',') if f.strip()]

        # 分批：每批最多20个字段
        batch_size = 20
        merge_cols = ['symbol', 'trade_date']
        result_df = None

        for i in range(0, len(all_fields), batch_size):
            batch_fields = all_fields[i:i + batch_size]
            fields_str = ','.join(batch_fields)

            df = self._connector.get_daily_valuation_pt(
                symbols=em_symbols,
                fields=fields_str,
                trade_date=trade_date,
            )

            if df is not None and not df.empty:
                if result_df is None:
                    result_df = df
                else:
                    # 按 symbol + trade_date 合并
                    result_df = result_df.merge(df, on=merge_cols, how='outer')

        return result_df if result_df is not None else pd.DataFrame()

    # ============ 除权除息 ============

    def get_dividend_data(self, symbols: List[str], start_date: str = None,
                          end_date: str = None, **kwargs) -> pd.DataFrame:
        self._ensure_connected()
        try:
            from gm.api import stk_get_dividend
            em_symbols = SymbolConverter.batch_to_eastmoney(symbols) if symbols else []
            # stk_get_dividend(symbol, start_date, end_date) - 无 df 参数，symbol 单标的，日期必填
            all_dfs = []
            for sym in em_symbols:
                try:
                    # start_date/end_date 必填，格式 YYYY-MM-DD
                    s_date = start_date if start_date else '2020-01-01'
                    e_date = end_date if end_date else datetime.now().strftime('%Y-%m-%d')
                    # 转换 YYYYMMDD -> YYYY-MM-DD
                    if len(s_date) == 8:
                        s_date = f"{s_date[:4]}-{s_date[4:6]}-{s_date[6:8]}"
                    if len(e_date) == 8:
                        e_date = f"{e_date[:4]}-{e_date[4:6]}-{e_date[6:8]}"
                    df = self._connector._request_with_retry(
                        stk_get_dividend, symbol=sym,
                        start_date=s_date, end_date=e_date,
                    )
                    if df is not None and not df.empty:
                        all_dfs.append(df)
                except Exception as e:
                    logger.debug(f"获取 {sym} 除权除息数据失败: {e}")
            if all_dfs:
                return pd.concat(all_dfs, ignore_index=True)
            return pd.DataFrame()
        except (ImportError, AttributeError):
            logger.warning("stk_get_dividend 不可用")
            return pd.DataFrame()

    # ============ 每日市值 ============

    def get_daily_mktvalue_data(self, symbols: List[str], start_date: str = None,
                                end_date: str = None, **kwargs) -> pd.DataFrame:
        """获取每日市值指标数据（stk_get_daily_mktvalue 时序查询）"""
        self._ensure_connected()
        em_symbols = SymbolConverter.batch_to_eastmoney(symbols) if symbols else []

        # 市值指标完整字段（对齐东财 stk_get_daily_mktvalue 文档）
        all_fields = kwargs.get('fields', ','.join([
            'tot_mv', 'tot_mv_csrc', 'a_mv', 'a_mv_ex_ltd',
            'b_mv', 'b_mv_ex_ltd', 'ev', 'ev_ex_curr',
            'ev_ebitda', 'equity_value',
        ]))

        return self._connector.get_daily_mktvalue_batch(
            symbols=em_symbols,
            fields=all_fields,
            start_date=start_date,
            end_date=end_date,
        )

    def get_daily_mktvalue_pt_data(self, symbols: List[str], trade_date: str,
                                    **kwargs) -> pd.DataFrame:
        """
        获取单日市值指标截面数据（stk_get_daily_mktvalue_pt，多标的单日）

        用于批量同步：按交易日遍历，每天一次请求获取所有标的数据。
        """
        self._ensure_connected()
        em_symbols = SymbolConverter.batch_to_eastmoney(symbols) if symbols else []

        all_fields = kwargs.get('fields', ','.join([
            'tot_mv', 'tot_mv_csrc', 'a_mv', 'a_mv_ex_ltd',
            'b_mv', 'b_mv_ex_ltd', 'ev', 'ev_ex_curr',
            'ev_ebitda', 'equity_value',
        ]))

        return self._connector.get_daily_mktvalue_pt(
            symbols=em_symbols,
            fields=all_fields,
            trade_date=trade_date,
        )

    # ============ 合约详情 ============

    def get_instrument_detail(self, symbol: str, **kwargs) -> Optional[Dict[str, Any]]:
        self._ensure_connected()
        em_symbol = SymbolConverter.to_eastmoney(symbol)
        df = self._connector.get_symbol_infos(symbols=[em_symbol])
        if df is not None and not df.empty:
            return df.iloc[0].to_dict()
        return None
