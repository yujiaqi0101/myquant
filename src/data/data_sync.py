"""
数据同步模块
============

负责从数据源下载数据并写入SQLite数据库。
支持全量同步和增量同步，自动计算VWAP，填充停牌数据。

同步流程对齐东财掘金API结构（16步）：
1.  交易日历 → t_trading_date
2.  股票基本信息 → t_stock_info
3.  申万行业分类明细 → t_stock_in_sw
4.  股票日频数据 → t_stock_daily
5.  ETF基本信息 → t_etf_info
6.  ETF日频数据 → t_etf_daily
7.  指数基本信息 → t_index_info
8.  指数成分股 → t_stock_in_index
9.  指数日频数据 → t_index_daily
10. 板块基本信息 → t_sector_info
11. 板块成分股 → t_stock_list_in_sector (通达信)
12. 财务数据 → t_finance_prime
13. 财务衍生指标 → t_finance_deriv
14. 每日市值指标 → t_stock_mktvalue
15. 估值数据 → t_valuation_data
16. 除权除息 → t_dividend_date

通过 SourceRegistry 按数据类型路由到最佳数据源：
- 股票/ETF/指数/财务/估值/除权除息 -> 东财掘金（默认）
- 板块成分股 -> 通达信（默认）
- 可通过 config/config.json 的 data_source.routing 字段切换

所有表定义统一由 database.py 管理，本模块不创建任何表。
"""

import logging
import time
from datetime import datetime
from typing import List, Optional, Dict, Callable

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# 同步步骤总数
SYNC_TOTAL_STEPS = 16


# ============ 统一列名映射 ============

# 东财API返回的标准字段 -> 数据库表字段的映射配置
COLUMN_MAPPINGS = {
    'stock_info': {'symbol': 'stock_code', 'sec_name': 'stock_name'},
    'etf_info': {'symbol': 'etf_code', 'sec_name': 'etf_name'},
    'index_info': {'symbol': 'index_code', 'sec_name': 'index_name'},
    'sector_info': {'symbol': 'sector_code', 'sec_name': 'sector_name'},
    'daily': {'symbol': 'stock_code'},
    'financial': {'symbol': 'stock_code'},
    'valuation': {'symbol': 'stock_code'},
    'dividend': {'symbol': 'stock_code'},
}


def apply_column_mapping(df: pd.DataFrame, mapping_key: str) -> pd.DataFrame:
    """
    统一列名映射：将东财API返回字段映射为数据库表字段。

    仅在源列存在且目标列不存在时执行映射，避免覆盖已有列。

    Parameters
    ----------
    df : pd.DataFrame
        待映射的DataFrame
    mapping_key : str
        映射配置键名，如 'stock_info', 'daily' 等

    Returns
    -------
    pd.DataFrame
        映射后的DataFrame
    """
    if df.empty:
        return df

    col_map = COLUMN_MAPPINGS.get(mapping_key, {})
    if not col_map:
        return df

    actual_map = {}
    for src, dst in col_map.items():
        if src in df.columns and dst not in df.columns:
            actual_map[src] = dst

    if actual_map:
        df = df.rename(columns=actual_map)

    return df


class DataSynchronizer:
    """
    数据同步器

    从多数据源同步数据到SQLite数据库，支持全量/增量同步，
    自动计算VWAP，填充停牌数据，批量写入数据库。

    通过 SourceRegistry 按数据类型路由到最佳数据源。

    Parameters
    ----------
    db_manager : DatabaseManager
        数据库管理器实例
    registry : SourceRegistry, optional
        数据源注册中心，按数据类型路由到最佳数据源
    """

    # 已知指数代码列表（用于区分股票和指数）
    KNOWN_INDEX_CODES = frozenset({
        '000001.SH', '000300.SH', '000852.SH', '000905.SH',
        '000016.SH', '000015.SH', '399001.SZ', '399006.SZ',
        '399005.SZ', '399300.SZ', '399673.SZ',
    })

    def __init__(self, db_manager=None, registry=None):
        self.db = db_manager

        # 创建或使用传入的 registry
        if registry:
            self._registry = registry
        else:
            from .source_registry import SourceRegistry
            self._registry = SourceRegistry()

    def _get_source(self, data_type: str):
        """根据数据类型获取对应的数据源"""
        source = self._registry.get_source_for_data_type(data_type)
        if source is None:
            raise ConnectionError(f"无可用的数据源 (data_type={data_type})")
        return source

    # ============ 主入口 ============

    def sync_all(self, start_date='20230101', end_date='', progress_callback=None) -> dict:
        """
        全量同步，对齐东财掘金API结构

        同步流程（16步）：
        1.  交易日历 → t_trading_date
        2.  股票基本信息 → t_stock_info
        3.  申万行业分类明细 → t_stock_in_sw
        4.  股票日频数据 → t_stock_daily
        5.  ETF基本信息 → t_etf_info
        6.  ETF日频数据 → t_etf_daily
        7.  指数基本信息 → t_index_info
        8.  指数成分股 → t_stock_in_index
        9.  指数日频数据 → t_index_daily
        10. 板块基本信息 → t_sector_info
        11. 板块成分股 → t_stock_list_in_sector (通达信)
        12. 财务数据 → t_finance_prime
        13. 每日市值指标 → t_stock_mktvalue
        14. 估值数据 → t_valuation_data
        15. 除权除息 → t_dividend_date

        Parameters
        ----------
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD，为空则使用当前日期
        progress_callback : callable, optional
            进度回调函数，签名: callback(stage: str, current: int, total: int, message: str)

        Returns
        -------
        dict
            同步结果汇总
        """
        if not end_date:
            end_date = datetime.now().strftime('%Y%m%d')

        start_time = datetime.now()
        logger.info(f"开始全量同步: {start_date} -> {end_date}")
        results = {
            'start_date': start_date,
            'end_date': end_date,
            'steps': {},
            'errors': [],
        }

        try:
            # ---- 步骤1: 交易日历 → t_trading_date（全量同步，不受时间范围影响）----
            step = 1
            self._report_progress(progress_callback, 'trading_dates', step, SYNC_TOTAL_STEPS,
                                  '正在同步交易日历（全量）...')
            r = self.sync_trading_dates()
            results['steps']['trading_dates'] = r
            self._report_progress(progress_callback, 'trading_dates', step, SYNC_TOTAL_STEPS,
                                  f'交易日历同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤2: 股票基本信息 → t_stock_info ----
            step = 2
            self._report_progress(progress_callback, 'stock_info', step, SYNC_TOTAL_STEPS,
                                  '正在同步股票基本信息...')
            r = self.sync_stock_info()
            results['steps']['stock_info'] = r
            stock_list = r.get('codes', [])
            self._report_progress(progress_callback, 'stock_info', step, SYNC_TOTAL_STEPS,
                                  f'股票基本信息同步完成，共 {r.get("count", 0)} 条')

            if not stock_list:
                logger.warning("股票列表为空，跳过后续同步")
                results['errors'].append('股票列表为空')
                self._log_sync('full_sync', start_time, datetime.now(), 0, 'failed',
                               error_message='股票列表为空')
                return results

            # ---- 步骤3: 申万行业分类明细 → t_stock_in_sw ----
            step = 3
            self._report_progress(progress_callback, 'shenwan_industry_detail', step, SYNC_TOTAL_STEPS,
                                  '正在同步申万行业分类明细...')
            r = self.sync_shenwan_industry_detail()
            results['steps']['shenwan_industry_detail'] = r
            self._report_progress(progress_callback, 'shenwan_industry_detail', step, SYNC_TOTAL_STEPS,
                                  f'申万行业分类明细同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤4: 股票日频数据 → t_stock_daily ----
            step = 4
            self._report_progress(progress_callback, 'stock_daily', step, SYNC_TOTAL_STEPS,
                                  '正在同步股票日频数据...')
            r = self.sync_stock_daily(stock_list, start_date, end_date, progress_callback)
            results['steps']['stock_daily'] = r
            self._report_progress(progress_callback, 'stock_daily', step, SYNC_TOTAL_STEPS,
                                  f'股票日频数据同步完成，共 {r.get("records", 0)} 条')

            # ---- 步骤5: ETF基本信息 → t_etf_info ----
            step = 5
            self._report_progress(progress_callback, 'etf_info', step, SYNC_TOTAL_STEPS,
                                  '正在同步ETF基本信息...')
            r = self.sync_etf_info()
            results['steps']['etf_info'] = r
            etf_list = r.get('codes', [])
            self._report_progress(progress_callback, 'etf_info', step, SYNC_TOTAL_STEPS,
                                  f'ETF基本信息同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤6: ETF日频数据 → t_etf_daily ----
            step = 6
            self._report_progress(progress_callback, 'etf_daily', step, SYNC_TOTAL_STEPS,
                                  '正在同步ETF日频数据...')
            r = self.sync_etf_daily(etf_list, start_date, end_date, progress_callback)
            results['steps']['etf_daily'] = r
            self._report_progress(progress_callback, 'etf_daily', step, SYNC_TOTAL_STEPS,
                                  f'ETF日频数据同步完成，共 {r.get("records", 0)} 条')

            # ---- 步骤7: 指数基本信息 → t_index_info ----
            step = 7
            self._report_progress(progress_callback, 'index_info', step, SYNC_TOTAL_STEPS,
                                  '正在同步指数基本信息...')
            r = self.sync_index_info()
            results['steps']['index_info'] = r
            index_list = r.get('codes', [])
            self._report_progress(progress_callback, 'index_info', step, SYNC_TOTAL_STEPS,
                                  f'指数基本信息同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤8: 指数成分股 → t_stock_in_index ----
            step = 8
            self._report_progress(progress_callback, 'index_constituents', step, SYNC_TOTAL_STEPS,
                                  '正在同步指数成分股...')
            r = self.sync_index_constituents(start_date, end_date)
            results['steps']['index_constituents'] = r
            self._report_progress(progress_callback, 'index_constituents', step, SYNC_TOTAL_STEPS,
                                  f'指数成分股同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤9: 指数日频数据 → t_index_daily ----
            step = 9
            self._report_progress(progress_callback, 'index_daily', step, SYNC_TOTAL_STEPS,
                                  '正在同步指数日频数据...')
            r = self.sync_index_daily(index_list, start_date, end_date, progress_callback)
            results['steps']['index_daily'] = r
            self._report_progress(progress_callback, 'index_daily', step, SYNC_TOTAL_STEPS,
                                  f'指数日频数据同步完成，共 {r.get("records", 0)} 条')

            # ---- 步骤10: 板块基本信息 → t_sector_info ----
            step = 10
            self._report_progress(progress_callback, 'sector_info', step, SYNC_TOTAL_STEPS,
                                  '正在同步板块基本信息...')
            r = self.sync_sector_info()
            results['steps']['sector_info'] = r
            self._report_progress(progress_callback, 'sector_info', step, SYNC_TOTAL_STEPS,
                                  f'板块基本信息同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤11: 板块成分股 → t_stock_list_in_sector (通达信) ----
            step = 11
            self._report_progress(progress_callback, 'sector_constituents', step, SYNC_TOTAL_STEPS,
                                  '正在同步板块成分股...')
            r = self.sync_sector_constituents()
            results['steps']['sector_constituents'] = r
            self._report_progress(progress_callback, 'sector_constituents', step, SYNC_TOTAL_STEPS,
                                  f'板块成分股同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤12: 财务数据 → t_finance_prime ----
            step = 12
            self._report_progress(progress_callback, 'financial_data', step, SYNC_TOTAL_STEPS,
                                  '正在同步财务数据...')
            r = self.sync_financial_data(stock_list, start_date, end_date, progress_callback)
            results['steps']['financial_data'] = r
            self._report_progress(progress_callback, 'financial_data', step, SYNC_TOTAL_STEPS,
                                  f'财务数据同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤13: 财务衍生指标 → t_finance_deriv ----
            step = 13
            self._report_progress(progress_callback, 'finance_deriv_data', step, SYNC_TOTAL_STEPS,
                                  '正在同步财务衍生指标...')
            r = self.sync_finance_deriv_data(stock_list, start_date, end_date, progress_callback)
            results['steps']['finance_deriv_data'] = r
            self._report_progress(progress_callback, 'finance_deriv_data', step, SYNC_TOTAL_STEPS,
                                  f'财务衍生指标同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤14: 每日市值指标 → t_stock_mktvalue ----
            step = 14
            self._report_progress(progress_callback, 'stock_mktvalue', step, SYNC_TOTAL_STEPS,
                                  '正在同步每日市值指标...')
            r = self.sync_stock_mktvalue(stock_list, start_date, end_date)
            results['steps']['stock_mktvalue'] = r
            self._report_progress(progress_callback, 'stock_mktvalue', step, SYNC_TOTAL_STEPS,
                                  f'每日市值指标同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤15: 估值数据 → t_valuation_data ----
            step = 15
            self._report_progress(progress_callback, 'valuation_data', step, SYNC_TOTAL_STEPS,
                                  '正在同步估值数据...')
            r = self.sync_valuation_data(stock_list, start_date, end_date)
            results['steps']['valuation_data'] = r
            self._report_progress(progress_callback, 'valuation_data', step, SYNC_TOTAL_STEPS,
                                  f'估值数据同步完成，共 {r.get("count", 0)} 条')

            # ---- 步骤16: 除权除息 → t_dividend_date ----
            step = 16
            self._report_progress(progress_callback, 'dividend_data', step, SYNC_TOTAL_STEPS,
                                  '正在同步除权除息数据...')
            r = self.sync_dividend_data(stock_list, start_date, end_date)
            results['steps']['dividend_data'] = r
            if r.get('status') == 'skipped':
                self._report_progress(progress_callback, 'dividend_data', step, SYNC_TOTAL_STEPS,
                                      '除权除息接口无权限，已跳过')
            else:
                self._report_progress(progress_callback, 'dividend_data', step, SYNC_TOTAL_STEPS,
                                      f'除权除息数据同步完成，共 {r.get("count", 0)} 条')

            # 汇总
            end_time = datetime.now()
            total_records = sum(
                s.get('count', 0) + s.get('records', 0)
                for s in results['steps'].values()
                if isinstance(s, dict)
            )
            self._log_sync('full_sync', start_time, end_time, total_records, 'success',
                           details=f'全量同步完成，耗时 {(end_time - start_time).total_seconds():.1f}s')
            logger.info(f"全量同步完成，耗时 {(end_time - start_time).total_seconds():.1f}s")

            # 同步后自动 inspect + 补同步闭环
            self._run_sync_inspect_loop(start_date, end_date, results)

        except Exception as e:
            logger.error(f"全量同步失败: {e}", exc_info=True)
            results['errors'].append(str(e))
            self._log_sync('full_sync', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))

        self._report_progress(progress_callback, 'done', SYNC_TOTAL_STEPS, SYNC_TOTAL_STEPS,
                              '全量同步完成')
        return results

    # ============ 按步骤同步 ============

    # 步骤定义表：(名称, 目标表, 是否需要stock_list, 是否需要日期范围)
    SYNC_STEPS = {
        1:  ('交易日历', 't_trading_date', False, False),
        2:  ('股票基本信息', 't_stock_info', False, False),
        3:  ('申万行业分类明细', 't_stock_in_sw', False, False),
        4:  ('股票日频数据', 't_stock_daily', True, True),
        5:  ('ETF基本信息', 't_etf_info', False, False),
        6:  ('ETF日频数据', 't_etf_daily', True, True),
        7:  ('指数基本信息', 't_index_info', False, False),
        8:  ('指数成分股', 't_stock_in_index', False, False),
        9:  ('指数日频数据', 't_index_daily', True, True),
        10: ('板块基本信息', 't_sector_info', False, False),
        11: ('板块成分股', 't_stock_list_in_sector', False, False),
        12: ('财务数据', 't_finance_prime', True, True),
        13: ('财务衍生指标', 't_finance_deriv', True, True),
        14: ('每日市值指标', 't_stock_mktvalue', True, True),
        15: ('估值数据', 't_valuation_data', True, True),
        16: ('除权除息', 't_dividend_date', True, True),
    }

    def sync_steps(self, steps: list, start_date='20230101', end_date='', progress_callback=None) -> dict:
        """
        按指定步骤同步数据

        Parameters
        ----------
        steps : list
            要执行的步骤编号列表，如 [14, 15] 或 [1, 2, 3]
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD，为空则使用当前日期
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        dict
            同步结果汇总
        """
        if not end_date:
            end_date = datetime.now().strftime('%Y%m%d')

        start_time = datetime.now()
        results = {
            'start_date': start_date,
            'end_date': end_date,
            'steps': {},
            'errors': [],
        }

        # 预加载依赖数据：stock_list / etf_list / index_list
        stock_list = []
        etf_list = []
        index_list = []

        needs_stock_list = any(self.SYNC_STEPS.get(s, (None,))[2] for s in steps if s in self.SYNC_STEPS)
        needs_etf_list = 7 in steps
        needs_index_list = 10 in steps

        if needs_stock_list or needs_etf_list or needs_index_list:
            logger.info("从数据库加载前置数据...")
            if needs_stock_list:
                stock_list = self._get_stock_list_from_db()
                if not stock_list:
                    logger.warning("数据库中无股票列表，请先执行步骤2（股票基本信息）")
            if needs_etf_list:
                etf_list = self._get_etf_list_from_db()
            if needs_index_list:
                index_list = self._get_index_list_from_db()

        total_steps = len(steps)
        for idx, step_num in enumerate(steps, 1):
            if step_num not in self.SYNC_STEPS:
                logger.warning(f"无效步骤号: {step_num}，跳过")
                continue

            step_name, table_name, _, _ = self.SYNC_STEPS[step_num]
            self._report_progress(progress_callback, step_name, idx, total_steps,
                                  f'正在同步 {step_name}...')

            try:
                r = self._execute_step(step_num, stock_list, etf_list, index_list,
                                       start_date, end_date, progress_callback)
                results['steps'][step_name] = r
                self._report_progress(progress_callback, step_name, idx, total_steps,
                                      f'{step_name}同步完成，共 {r.get("count", r.get("records", 0))} 条')
            except Exception as e:
                logger.error(f"步骤{step_num}({step_name})同步失败: {e}", exc_info=True)
                results['steps'][step_name] = {'count': 0, 'status': 'failed', 'error': str(e)}
                results['errors'].append(f'步骤{step_num}: {e}')
                self._report_progress(progress_callback, step_name, idx, total_steps,
                                      f'{step_name}同步失败: {e}')

        end_time = datetime.now()
        logger.info(f"指定步骤同步完成，耗时 {(end_time - start_time).total_seconds():.1f}s")
        return results

    def _get_max_sync_date(self, table_name: str) -> str:
        """
        从 t_sync_data_log 查询指定表的最大同步日期。

        注意：只信任 t_sync_data_log 中的记录，因为日志是在单表完整同步成功后
        才刷新写入的。如果日志中无记录，说明该表从未成功完成过同步，应从
        默认起始日期重新同步（INSERT OR REPLACE 可处理重复数据）。

        Parameters
        ----------
        table_name : str
            数据表名（如 t_stock_daily）

        Returns
        -------
        str
            最大同步日期，格式 YYYYMMDD；无记录则返回空字符串
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT MAX(data_date) FROM t_sync_data_log WHERE table_name = ?',
                    (table_name,)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    return str(row[0]).replace('-', '')
                return ''
        except Exception as e:
            logger.warning(f"查询 {table_name} 最大同步日期失败: {e}")
            return ''

    def _get_latest_trade_date(self, before_date: str = '') -> str:
        """
        获取 ≤ before_date 的最近交易日。

        Parameters
        ----------
        before_date : str
            参考日期，格式 YYYYMMDD；为空则取今天

        Returns
        -------
        str
            最近交易日，格式 YYYYMMDD
        """
        if not before_date:
            before_date = datetime.now().strftime('%Y%m%d')
        date_str = f"{before_date[:4]}-{before_date[4:6]}-{before_date[6:8]}"
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT MAX(trade_date) FROM t_trading_date WHERE trade_date <= ?',
                (date_str,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                return str(row[0]).replace('-', '')
            return before_date

    def _calc_incremental_range(self, table_name: str, default_start: str = '20210101') -> tuple:
        """
        计算增量同步的日期范围。

        Parameters
        ----------
        table_name : str
            数据表名
        default_start : str
            无历史记录时的默认起始日期，格式 YYYYMMDD

        Returns
        -------
        tuple
            (s_date, e_date, has_data)，日期格式 YYYYMMDD；has_data=False 表示范围内无交易日需跳过
        """
        e_date = self._get_latest_trade_date()
        s_date = self._get_max_sync_date(table_name)
        if not s_date:
            s_date = default_start
            logger.info(f"{table_name} 无历史记录，从默认起始日期同步: {s_date} → {e_date}")
        else:
            logger.info(f"{table_name} 增量同步: {s_date} → {e_date}")

        # 检查日期范围内是否有交易日
        s_fmt = f"{s_date[:4]}-{s_date[4:6]}-{s_date[6:8]}"
        e_fmt = f"{e_date[:4]}-{e_date[4:6]}-{e_date[6:8]}"
        trade_dates = self.db.get_trade_dates(s_fmt, e_fmt)
        if not trade_dates:
            logger.info(f"{table_name} 日期范围内无交易日，跳过")
            return s_date, e_date, False
        return s_date, e_date, True

    def auto_sync(self, progress_callback=None) -> dict:
        """
        自动同步：全量表全量刷新，增量表从 t_sync_data_log 最大日期同步到今天。

        同步顺序：
        1. t_trading_date（全量）
        2. t_stock_info（全量）
        3. t_stock_in_sw（全量）
        4. t_etf_info（全量）
        5. t_index_info（全量）
        6. t_stock_in_index（增量：最大日期 → 今天）
        7. 调用 _run_tdx_sector_script
        8. t_stock_daily（增量）
        9. t_index_daily（增量）
        10. t_etf_daily（增量）
        11. t_finance_prime（增量）
        12. t_finance_deriv（增量）
        13. t_stock_mktvalue（增量）
        14. t_valuation_data（增量）

        Parameters
        ----------
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        dict
            同步结果汇总
        """
        start_time = datetime.now()
        target_date = self._get_latest_trade_date()
        logger.info(f"开始自动同步（增量模式），目标交易日: {target_date}")

        results = {
            'target_date': target_date,
            'steps': {},
            'errors': [],
        }

        try:
            # ---- 全量表 ----
            self._report_progress(progress_callback, 'trading_dates', 1, 14, '正在同步交易日历（全量）...')
            r = self.sync_trading_dates()
            results['steps']['trading_dates'] = r
            self._report_progress(progress_callback, 'trading_dates', 1, 14,
                                  f'交易日历同步完成，共 {r.get("count", 0)} 条')

            self._report_progress(progress_callback, 'stock_info', 2, 14, '正在同步股票基本信息（全量）...')
            r = self.sync_stock_info()
            results['steps']['stock_info'] = r
            stock_list = r.get('codes', [])
            self._report_progress(progress_callback, 'stock_info', 2, 14,
                                  f'股票基本信息同步完成，共 {r.get("count", 0)} 条')

            self._report_progress(progress_callback, 'shenwan_industry_detail', 3, 14,
                                  '正在同步申万行业分类明细（全量）...')
            r = self.sync_shenwan_industry_detail()
            results['steps']['shenwan_industry_detail'] = r
            self._report_progress(progress_callback, 'shenwan_industry_detail', 3, 14,
                                  f'申万行业分类明细同步完成，共 {r.get("count", 0)} 条')

            self._report_progress(progress_callback, 'etf_info', 4, 14, '正在同步ETF基本信息（全量）...')
            r = self.sync_etf_info()
            results['steps']['etf_info'] = r
            etf_list = r.get('codes', [])
            self._report_progress(progress_callback, 'etf_info', 4, 14,
                                  f'ETF基本信息同步完成，共 {r.get("count", 0)} 条')

            self._report_progress(progress_callback, 'index_info', 5, 14, '正在同步指数基本信息（全量）...')
            r = self.sync_index_info()
            results['steps']['index_info'] = r
            index_list = r.get('codes', [])
            self._report_progress(progress_callback, 'index_info', 5, 14,
                                  f'指数基本信息同步完成，共 {r.get("count", 0)} 条')

            # ---- 增量表：t_stock_in_index ----
            self._report_progress(progress_callback, 'index_constituents', 6, 14,
                                  '正在同步指数成分股（增量）...')
            s_date, e_date, has_data = self._calc_incremental_range('t_stock_in_index')
            if has_data:
                r = self.sync_index_constituents(s_date, e_date)
            else:
                r = {'count': 0, 'status': 'skipped'}
            results['steps']['index_constituents'] = r
            self._report_progress(progress_callback, 'index_constituents', 6, 14,
                                  f'指数成分股同步完成，共 {r.get("count", 0)} 条')

            # ---- 调用通达信板块脚本 ----
            self._report_progress(progress_callback, 'tdx_sector', 7, 14,
                                  '正在调用通达信板块脚本...')
            r = self._run_tdx_sector_script()
            results['steps']['tdx_sector'] = r
            if r['success']:
                self._report_progress(progress_callback, 'tdx_sector', 7, 14, '通达信板块脚本执行完成')
            else:
                self._report_progress(progress_callback, 'tdx_sector', 7, 14,
                                      f'通达信板块脚本执行失败: {r.get("stderr", "")}')
                results['errors'].append('通达信板块脚本执行失败')

            # ---- 增量表：t_stock_daily ----
            self._report_progress(progress_callback, 'stock_daily', 8, 14,
                                  '正在同步股票日频数据（增量）...')
            s_date, e_date, has_data = self._calc_incremental_range('t_stock_daily')
            if has_data:
                r = self.sync_stock_daily(stock_list, s_date, e_date, progress_callback)
            else:
                r = {'records': 0, 'status': 'skipped'}
            results['steps']['stock_daily'] = r
            self._report_progress(progress_callback, 'stock_daily', 8, 14,
                                  f'股票日频数据同步完成，共 {r.get("records", 0)} 条')

            # ---- 增量表：t_index_daily ----
            self._report_progress(progress_callback, 'index_daily', 9, 14,
                                  '正在同步指数日频数据（增量）...')
            s_date, e_date, has_data = self._calc_incremental_range('t_index_daily')
            if has_data:
                r = self.sync_index_daily(index_list, s_date, e_date, progress_callback)
            else:
                r = {'records': 0, 'status': 'skipped'}
            results['steps']['index_daily'] = r
            self._report_progress(progress_callback, 'index_daily', 9, 14,
                                  f'指数日频数据同步完成，共 {r.get("records", 0)} 条')

            # ---- 增量表：t_etf_daily ----
            self._report_progress(progress_callback, 'etf_daily', 10, 14,
                                  '正在同步ETF日频数据（增量）...')
            s_date, e_date, has_data = self._calc_incremental_range('t_etf_daily')
            if has_data:
                r = self.sync_etf_daily(etf_list, s_date, e_date, progress_callback)
            else:
                r = {'records': 0, 'status': 'skipped'}
            results['steps']['etf_daily'] = r
            self._report_progress(progress_callback, 'etf_daily', 10, 14,
                                  f'ETF日频数据同步完成，共 {r.get("records", 0)} 条')

            # ---- 增量表：t_finance_prime ----
            self._report_progress(progress_callback, 'financial_data', 11, 14,
                                  '正在同步财务数据（增量）...')
            s_date, e_date, has_data = self._calc_incremental_range('t_finance_prime')
            if has_data:
                r = self.sync_financial_data(stock_list, s_date, e_date, progress_callback)
            else:
                r = {'count': 0, 'status': 'skipped'}
            results['steps']['financial_data'] = r
            self._report_progress(progress_callback, 'financial_data', 11, 14,
                                  f'财务数据同步完成，共 {r.get("count", 0)} 条')

            # ---- 增量表：t_finance_deriv ----
            self._report_progress(progress_callback, 'finance_deriv_data', 12, 14,
                                  '正在同步财务衍生指标（增量）...')
            s_date, e_date, has_data = self._calc_incremental_range('t_finance_deriv')
            if has_data:
                r = self.sync_finance_deriv_data(stock_list, s_date, e_date, progress_callback)
            else:
                r = {'count': 0, 'status': 'skipped'}
            results['steps']['finance_deriv_data'] = r
            self._report_progress(progress_callback, 'finance_deriv_data', 12, 14,
                                  f'财务衍生指标同步完成，共 {r.get("count", 0)} 条')

            # ---- 增量表：t_stock_mktvalue ----
            self._report_progress(progress_callback, 'stock_mktvalue', 13, 14,
                                  '正在同步每日市值指标（增量）...')
            s_date, e_date, has_data = self._calc_incremental_range('t_stock_mktvalue')
            if has_data:
                r = self.sync_stock_mktvalue(stock_list, s_date, e_date)
            else:
                r = {'count': 0, 'status': 'skipped'}
            results['steps']['stock_mktvalue'] = r
            self._report_progress(progress_callback, 'stock_mktvalue', 13, 14,
                                  f'每日市值指标同步完成，共 {r.get("count", 0)} 条')

            # ---- 增量表：t_valuation_data ----
            self._report_progress(progress_callback, 'valuation_data', 14, 14,
                                  '正在同步估值数据（增量）...')
            s_date, e_date, has_data = self._calc_incremental_range('t_valuation_data')
            if has_data:
                r = self.sync_valuation_data(stock_list, s_date, e_date)
            else:
                r = {'count': 0, 'status': 'skipped'}
            results['steps']['valuation_data'] = r
            self._report_progress(progress_callback, 'valuation_data', 14, 14,
                                  f'估值数据同步完成，共 {r.get("count", 0)} 条')

            # 汇总
            end_time = datetime.now()
            total_records = sum(
                s.get('count', 0) + s.get('records', 0)
                for s in results['steps'].values()
                if isinstance(s, dict)
            )
            self._log_sync('auto_sync', start_time, end_time, total_records, 'success',
                           details=f'自动同步完成，耗时 {(end_time - start_time).total_seconds():.1f}s')
            logger.info(f"自动同步完成，耗时 {(end_time - start_time).total_seconds():.1f}s")

        except Exception as e:
            logger.error(f"自动同步失败: {e}", exc_info=True)
            results['errors'].append(str(e))
            self._log_sync('auto_sync', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))

        self._report_progress(progress_callback, 'done', 14, 14, '自动同步完成')
        return results

    def _execute_step(self, step_num: int, stock_list: list, etf_list: list,
                      index_list: list, start_date: str, end_date: str,
                      progress_callback=None) -> dict:
        """执行单个同步步骤"""
        if step_num == 1:
            return self.sync_trading_dates(start_date, end_date)
        elif step_num == 2:
            r = self.sync_stock_info()
            if r.get('codes'):
                stock_list.clear()
                stock_list.extend(r['codes'])
            return r
        elif step_num == 3:
            return self.sync_shenwan_industry_detail()
        elif step_num == 4:
            return self.sync_stock_daily(stock_list, start_date, end_date, progress_callback)
        elif step_num == 5:
            r = self.sync_etf_info()
            if r.get('codes'):
                etf_list.clear()
                etf_list.extend(r['codes'])
            return r
        elif step_num == 6:
            return self.sync_etf_daily(etf_list, start_date, end_date, progress_callback)
        elif step_num == 7:
            r = self.sync_index_info()
            if r.get('codes'):
                index_list.clear()
                index_list.extend(r['codes'])
            return r
        elif step_num == 8:
            return self.sync_index_constituents(start_date, end_date)
        elif step_num == 9:
            return self.sync_index_daily(index_list, start_date, end_date, progress_callback)
        elif step_num == 10:
            return self.sync_sector_info()
        elif step_num == 11:
            return self.sync_sector_constituents()
        elif step_num == 12:
            return self.sync_financial_data(stock_list, start_date, end_date, progress_callback)
        elif step_num == 13:
            return self.sync_finance_deriv_data(stock_list, start_date, end_date, progress_callback)
        elif step_num == 14:
            return self.sync_stock_mktvalue(stock_list, start_date, end_date)
        elif step_num == 15:
            return self.sync_valuation_data(stock_list, start_date, end_date)
        elif step_num == 16:
            return self.sync_dividend_data(stock_list, start_date, end_date)
        else:
            return {'count': 0, 'status': 'unknown_step'}

    def _get_stock_list_from_db(self) -> list:
        """从数据库获取股票代码列表"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT stock_code FROM t_stock_info')
                return [row['stock_code'] for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"从数据库获取股票列表失败: {e}")
            return []

    def _get_etf_list_from_db(self) -> list:
        """从数据库获取ETF代码列表"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT etf_code FROM t_etf_info')
                return [row['etf_code'] for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"从数据库获取ETF列表失败: {e}")
            return []

    def _get_index_list_from_db(self) -> list:
        """从数据库获取指数代码列表"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT index_code FROM t_index_info')
                return [row['index_code'] for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"从数据库获取指数列表失败: {e}")
            return []

    # ============ 各步骤同步方法 ============

    def sync_trading_dates(self, start_date: str = None, end_date: str = None) -> dict:
        """
        步骤1: 同步交易日历 → t_trading_date

        全量从东财 get_trading_dates_by_year 获取交易日列表（1991年至今），
        不受 start_date/end_date 时间范围影响，每次同步全量替换。

        Returns
        -------
        dict
            同步结果 {'count': int, 'status': str}
        """
        start_time = datetime.now()
        logger.info("开始同步交易日历（全量，1991至今）...")

        try:
            source = self._get_source('trading_dates')
            # 全量同步：从1991年至当前年份，不受时间范围影响
            start_year = 1991
            end_year = datetime.now().year

            dates = source.get_trading_dates(start_year=start_year, end_year=end_year)
            if not dates:
                logger.warning("交易日历为空")
                self._log_sync('trading_dates', start_time, datetime.now(), 0, 'success',
                               details='交易日历为空')
                return {'count': 0, 'status': 'empty'}

            # 统一日期格式为 YYYY-MM-DD
            normalized = []
            for d in dates:
                d_str = str(d)
                if len(d_str) == 8 and d_str.isdigit():
                    d_str = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
                normalized.append(d_str)

            # 写入数据库
            count = self.db.insert_trading_dates(normalized)

            logger.info(f"交易日历同步完成: {count} 条")
            self._log_sync('trading_dates', start_time, datetime.now(), count, 'success')
            return {'count': count, 'status': 'success'}

        except Exception as e:
            logger.error(f"同步交易日历失败: {e}", exc_info=True)
            self._log_sync('trading_dates', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'count': 0, 'status': 'failed', 'error': str(e)}

    def sync_stock_info(self) -> dict:
        """
        步骤2: 同步股票基本信息 → t_stock_info

        从东财 get_symbol_infos(sec_type1=1010, sec_type2=101001) 获取A股列表及基本信息，
        一步到位写入 t_stock_info 表，同时返回代码列表供后续步骤使用。

        Returns
        -------
        dict
            同步结果 {'count': int, 'codes': list, 'status': str}
        """
        start_time = datetime.now()
        logger.info("开始同步股票基本信息...")

        try:
            source = self._get_source('stock_info')
            df = source.get_stock_list()

            if df is None or df.empty:
                logger.warning("数据源返回的股票列表为空")
                self._log_sync('stock_info', start_time, datetime.now(), 0, 'success',
                               details='列表为空')
                return {'count': 0, 'codes': [], 'status': 'empty'}

            # 统一列名映射
            df = apply_column_mapping(df, 'stock_info')

            # stock_code 统一转为内部格式
            if 'stock_code' in df.columns:
                from .symbol_converter import SymbolConverter
                df['stock_code'] = df['stock_code'].apply(
                    lambda x: SymbolConverter.to_internal(str(x)) if '.' in str(x) else str(x)
                )

            # 确保必要列存在
            for col in ['stock_code', 'stock_name']:
                if col not in df.columns:
                    logger.warning(f"股票信息缺少必要列: {col}")
                    self._log_sync('stock_info', start_time, datetime.now(), 0, 'failed',
                                   error_message=f'缺少列 {col}')
                    return {'count': 0, 'codes': [], 'status': 'failed'}

            # 写入数据库
            count = self.db.insert_stock_info(df)

            # 提取代码列表供后续步骤使用
            codes = df['stock_code'].tolist()

            logger.info(f"股票基本信息同步完成: {count} 条")
            self._log_sync('stock_info', start_time, datetime.now(), count, 'success')
            return {'count': count, 'codes': codes, 'status': 'success'}

        except Exception as e:
            logger.error(f"同步股票基本信息失败: {e}", exc_info=True)
            self._log_sync('stock_info', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'count': 0, 'codes': [], 'status': 'failed', 'error': str(e)}

    def sync_shenwan_industry_detail(self) -> dict:
        """
        步骤3: 申万行业分类明细 → t_stock_in_sw

        从本地 docs/ 目录下的申万行业分类Excel文件读取完整行业信息，
        全量替换写入 t_stock_in_sw 表（含一/二/三级行业、行业代码等）。

        Returns
        -------
        dict
            同步结果 {'count': int, 'status': str}
        """
        import os
        start_time = datetime.now()
        logger.info("开始同步申万行业分类明细...")

        try:
            # 查找申万行业分类Excel文件
            docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'docs')
            excel_files = [f for f in os.listdir(docs_dir)
                           if '申万行业' in f and f.endswith('.xlsx') and not f.startswith('~$')]
            if not excel_files:
                logger.warning("未找到申万行业分类Excel文件，跳过明细同步")
                self._log_sync('shenwan_industry_detail', start_time, datetime.now(), 0, 'skipped',
                               details='未找到Excel文件')
                return {'count': 0, 'status': 'skipped', 'reason': '未找到Excel文件'}

            excel_path = os.path.join(docs_dir, excel_files[0])
            logger.info(f"读取申万行业分类明细: {excel_files[0]}")

            df = pd.read_excel(excel_path)

            # 列名映射：Excel列名 → 数据库列名
            col_map = {
                '股票代码': 'stock_code',
                '行业代码': 'industry_code',
                '新版一级行业': 'industry_l1',
                '新版二 级行业': 'industry_l2',
                '新版三级行业': 'industry_l3',
                '交易所': 'exchange',
                '公司简称': 'stock_name',
            }
            # 兼容"新版二级行业"（无空格）和"新版二 级行业"（有空格）
            if '新版二级行业' in df.columns and '新版二 级行业' not in df.columns:
                col_map['新版二级行业'] = 'industry_l2'

            df = df.rename(columns=col_map)

            # 只保留需要的列
            keep_cols = [c for c in ['stock_code', 'industry_code', 'industry_l1',
                                      'industry_l2', 'industry_l3', 'exchange', 'stock_name']
                         if c in df.columns]
            df = df[keep_cols]

            if 'stock_code' not in df.columns:
                logger.warning("Excel文件缺少股票代码列，跳过")
                return {'count': 0, 'status': 'failed', 'reason': '缺少股票代码列'}

            # 去除股票代码为空的行
            df = df.dropna(subset=['stock_code'])

            # 全量替换写入
            count = self.db.replace_stock_in_sw(df)

            logger.info(f"申万行业分类明细同步完成: {count} 条")
            self._log_sync('shenwan_industry_detail', start_time, datetime.now(), count, 'success')
            return {'count': count, 'status': 'success'}

        except Exception as e:
            logger.error(f"同步申万行业分类明细失败: {e}", exc_info=True)
            self._log_sync('shenwan_industry_detail', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'count': 0, 'status': 'failed', 'error': str(e)}

    def sync_stock_daily(self, stock_list, start_date, end_date, progress_callback=None) -> dict:
        """
        步骤5: 同步股票日频数据 → t_stock_daily

        Parameters
        ----------
        stock_list : list
            股票代码列表
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        dict
            同步结果 {'records': int, 'suspended': int, 'status': str}
        """
        start_time = datetime.now()
        logger.info(f"开始同步股票日频数据: {start_date} -> {end_date}, 共 {len(stock_list)} 只")

        try:
            stock_records, suspended_count = self._sync_stock_daily(
                stock_list, start_date, end_date, progress_callback
            )

            logger.info(f"股票日频数据同步完成: {stock_records} 条, 停牌 {suspended_count} 条")
            self._log_sync('stock_daily', start_time, datetime.now(), stock_records, 'success',
                           details=f'记录 {stock_records}, 停牌 {suspended_count}')
            # 刷新 t_sync_data_log，记录当前 t_stock_daily 已有的日期
            self._refresh_sync_data_log('t_stock_daily', 'trade_date')
            return {
                'records': stock_records,
                'suspended': suspended_count,
                'count': len(stock_list),
                'status': 'success',
            }

        except Exception as e:
            logger.error(f"同步股票日频数据失败: {e}", exc_info=True)
            self._log_sync('stock_daily', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'records': 0, 'suspended': 0, 'count': len(stock_list), 'status': 'failed'}

    def sync_etf_info(self) -> dict:
        """
        步骤5: 同步ETF基本信息 → t_etf_info

        从东财 get_symbol_infos(sec_type1=1020, sec_type2=102001) 获取ETF列表及基本信息。

        Returns
        -------
        dict
            同步结果 {'count': int, 'codes': list, 'status': str}
        """
        start_time = datetime.now()
        logger.info("开始同步ETF基本信息...")

        try:
            source = self._get_source('etf_info')
            df = source.get_etf_list()

            if df is None or df.empty:
                logger.warning("数据源返回的ETF列表为空")
                self._log_sync('etf_info', start_time, datetime.now(), 0, 'success',
                               details='列表为空')
                return {'count': 0, 'codes': [], 'status': 'empty'}

            # 统一列名映射
            df = apply_column_mapping(df, 'etf_info')

            # etf_code 统一转为内部格式
            if 'etf_code' in df.columns:
                from .symbol_converter import SymbolConverter
                df['etf_code'] = df['etf_code'].apply(
                    lambda x: SymbolConverter.to_internal(str(x)) if '.' in str(x) else str(x)
                )

            # 写入数据库
            count = self.db.insert_etf_info(df)

            # 提取代码列表供后续步骤使用
            codes = df['etf_code'].tolist() if 'etf_code' in df.columns else []

            logger.info(f"ETF基本信息同步完成: {count} 条")
            self._log_sync('etf_info', start_time, datetime.now(), count, 'success')
            return {'count': count, 'codes': codes, 'status': 'success'}

        except Exception as e:
            logger.error(f"同步ETF基本信息失败: {e}", exc_info=True)
            self._log_sync('etf_info', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'count': 0, 'codes': [], 'status': 'failed', 'error': str(e)}

    def sync_etf_daily(self, etf_list, start_date, end_date, progress_callback=None) -> dict:
        """
        步骤6: 同步ETF日频数据 → t_etf_daily

        Parameters
        ----------
        etf_list : list
            ETF代码列表
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        dict
            同步结果 {'records': int, 'status': str}
        """
        start_time = datetime.now()

        if not etf_list:
            logger.info("ETF列表为空，跳过ETF日频数据同步")
            return {'records': 0, 'count': 0, 'status': 'skipped'}

        logger.info(f"开始同步ETF日频数据: {start_date} -> {end_date}, 共 {len(etf_list)} 只")

        try:
            source = self._get_source('etf_daily')
            etf_records = 0
            batch_size = 1000
            total_etfs = len(etf_list)

            for batch_start in range(0, total_etfs, batch_size):
                batch_codes = etf_list[batch_start:batch_start + batch_size]
                batch_end = min(batch_start + batch_size, total_etfs)

                try:
                    all_frames = []
                    for code in batch_codes:
                        df = source.get_etf_daily(
                            symbol=code,
                            start_date=start_date,
                            end_date=end_date,
                            adjust=1,
                        )
                        if df is None or df.empty:
                            continue

                        df = df.copy()
                        # 统一列名
                        col_rename = {}
                        if 'symbol' in df.columns and 'etf_code' not in df.columns:
                            col_rename['symbol'] = 'etf_code'
                        if 'eob' in df.columns and 'trade_date' not in df.columns:
                            col_rename['eob'] = 'trade_date'
                        if 'trade_time' in df.columns and 'trade_date' not in df.columns:
                            col_rename['trade_time'] = 'trade_date'
                        if col_rename:
                            df = df.rename(columns=col_rename)

                        if 'etf_code' not in df.columns:
                            df['etf_code'] = code
                        else:
                            from .symbol_converter import SymbolConverter
                            df['etf_code'] = df['etf_code'].apply(
                                lambda x: SymbolConverter.to_internal(str(x)) if '.' in str(x) else str(x)
                            )

                        all_frames.append(df)

                    if all_frames:
                        df = pd.concat(all_frames, ignore_index=True)
                        self.db.insert_etf_daily(df)
                        etf_records += len(df)

                except Exception as e:
                    logger.warning(f"获取ETF行情批次失败 [{batch_start}:{batch_end}]: {e}")

                if progress_callback and total_etfs > 0:
                    progress_callback('etf_daily', batch_end, total_etfs,
                                      f'ETF行情: {batch_end}/{total_etfs}')

            logger.info(f"ETF日频数据同步完成: {etf_records} 条")
            self._log_sync('etf_daily', start_time, datetime.now(), etf_records, 'success')
            # 刷新 t_sync_data_log，记录当前 t_etf_daily 已有的日期
            self._refresh_sync_data_log('t_etf_daily', 'trade_date')
            return {'records': etf_records, 'count': len(etf_list), 'status': 'success'}

        except Exception as e:
            logger.error(f"同步ETF日频数据失败: {e}", exc_info=True)
            self._log_sync('etf_daily', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'records': 0, 'count': len(etf_list), 'status': 'failed'}

    def sync_index_info(self) -> dict:
        """
        步骤7: 同步指数基本信息 → t_index_info

        从东财 get_symbol_infos(sec_type1=1060, sec_type2=106001) 获取指数列表及基本信息。

        Returns
        -------
        dict
            同步结果 {'count': int, 'codes': list, 'status': str}
        """
        start_time = datetime.now()
        logger.info("开始同步指数基本信息...")

        try:
            source = self._get_source('index_info')
            df = source.get_index_list()

            if df is None or df.empty:
                logger.warning("数据源返回的指数列表为空")
                self._log_sync('index_info', start_time, datetime.now(), 0, 'success',
                               details='列表为空')
                return {'count': 0, 'codes': [], 'status': 'empty'}

            # 统一列名映射
            df = apply_column_mapping(df, 'index_info')

            # index_code 统一转为内部格式
            if 'index_code' in df.columns:
                from .symbol_converter import SymbolConverter
                df['index_code'] = df['index_code'].apply(
                    lambda x: SymbolConverter.to_internal(str(x)) if '.' in str(x) else str(x)
                )

            # 写入数据库
            count = self.db.insert_index_info(df)

            # 标记核心指数为需要同步（is_sync=1）
            core_indices = list(self.KNOWN_INDEX_CODES)
            marked_count = 0
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                for idx_code in core_indices:
                    cursor.execute(
                        'UPDATE t_index_info SET is_sync = 1 WHERE index_code = ?',
                        (idx_code,)
                    )
                    marked_count += cursor.rowcount
                logger.info(f"已标记 {marked_count} 个核心指数为需要同步")

            # 提取代码列表供后续步骤使用
            codes = df['index_code'].tolist() if 'index_code' in df.columns else []

            logger.info(f"指数基本信息同步完成: {count} 条")
            self._log_sync('index_info', start_time, datetime.now(), count, 'success')
            return {'count': count, 'codes': codes, 'status': 'success'}

        except Exception as e:
            logger.error(f"同步指数基本信息失败: {e}", exc_info=True)
            self._log_sync('index_info', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'count': 0, 'codes': [], 'status': 'failed', 'error': str(e)}

    def sync_index_constituents(self, start_date='20230101', end_date='') -> dict:
        """
        步骤8: 同步指数成分股 → t_stock_in_index

        从 t_index_info 获取 is_sync=1 的指数代码，按交易日遍历调用
        stk_get_index_constituents 获取成分股（含权重、市值）。

        Parameters
        ----------
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD

        Returns
        -------
        dict
            同步结果 {'count': int, 'status': str}
        """
        start_time = datetime.now()
        logger.info("开始同步指数成分股...")

        try:
            if not end_date:
                end_date = datetime.now().strftime('%Y%m%d')

            # 从 t_index_info 获取 is_sync=1 的指数代码
            index_codes = []
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT DISTINCT index_code FROM t_index_info WHERE is_sync = 1')
                index_codes = [row[0] for row in cursor.fetchall()]
            logger.info(f"从 t_index_info 获取到 {len(index_codes)} 个指数")

            # 获取日期范围内的交易日列表
            s_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            e_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
            trade_dates = self.db.get_trade_dates(s_date, e_date)
            if not trade_dates:
                logger.warning("日期范围内无交易日，跳过指数成分股同步")
                self._log_sync('index_constituents', start_time, datetime.now(), 0, 'skipped')
                return {'count': 0, 'status': 'skipped'}
            logger.info(f"日期范围内共 {len(trade_dates)} 个交易日")

            source = self._get_source('index_constituents')
            total_count = 0

            for trade_date in trade_dates:
                day_dfs = []
                for index_code in index_codes:
                    try:
                        df = source.get_index_constituents(index_code, trade_date=trade_date)
                        if df is not None and not df.empty:
                            day_dfs.append(df)
                    except Exception as e:
                        logger.debug(f"获取指数 [{index_code}] {trade_date} 成分股失败: {e}")

                if day_dfs:
                    day_df = pd.concat(day_dfs, ignore_index=True)
                    count = self.db.insert_index_constituent(day_df)
                    total_count += count
                    logger.info(f"交易日 {trade_date} 写入指数成分股: {count} 条")
                logger.debug(f"已完成交易日 {trade_date} 的指数成分股查询")

            logger.info(f"指数成分股同步完成: {total_count} 条")
            self._refresh_sync_data_log('t_stock_in_index', 'trade_date')
            self._log_sync('index_constituents', start_time, datetime.now(), total_count, 'success')
            return {'count': total_count, 'status': 'success'}

        except Exception as e:
            logger.error(f"同步指数成分股失败: {e}", exc_info=True)
            self._log_sync('index_constituents', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'count': 0, 'status': 'failed', 'error': str(e)}

    def sync_index_daily(self, index_list, start_date, end_date, progress_callback=None) -> dict:
        """
        步骤9: 同步指数日频数据 → t_index_daily

        Parameters
        ----------
        index_list : list
            指数代码列表
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        dict
            同步结果 {'records': int, 'status': str}
        """
        start_time = datetime.now()

        if not index_list:
            logger.info("指数列表为空，跳过指数日频数据同步")
            return {'records': 0, 'count': 0, 'status': 'skipped'}

        logger.info(f"开始同步指数日频数据: {start_date} -> {end_date}, 共 {len(index_list)} 只")

        try:
            index_records = self._sync_index_daily(
                index_list, start_date, end_date, progress_callback
            )

            logger.info(f"指数日频数据同步完成: {index_records} 条")
            self._log_sync('index_daily', start_time, datetime.now(), index_records, 'success')
            # 刷新 t_sync_data_log，记录当前 t_index_daily 已有的日期
            self._refresh_sync_data_log('t_index_daily', 'trade_date')
            return {'records': index_records, 'count': len(index_list), 'status': 'success'}

        except Exception as e:
            logger.error(f"同步指数日频数据失败: {e}", exc_info=True)
            self._log_sync('index_daily', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'records': 0, 'count': len(index_list), 'status': 'failed'}

    def _run_tdx_sector_script(self) -> dict:
        """
        通过 subprocess 调用通达信目录下的板块数据脚本。

        通达信 TQ 接口必须在通达信目录下运行，因此通过远程调用独立脚本获取
        板块信息和板块成分股数据，脚本直接写入数据库。

        Returns
        -------
        dict
            {'success': bool, 'stdout': str, 'stderr': str}
        """
        import subprocess
        import sys

        script_path = r"D:\new_tdx_mock\PYPlugins\user\tdxtest1.py"
        logger.info(f"调用通达信板块数据脚本: {script_path}")

        try:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=600,  # 10 分钟超时
            )
            success = result.returncode == 0
            if not success:
                logger.error(f"通达信板块脚本执行失败，返回码: {result.returncode}")
                logger.error(f"stderr: {result.stderr}")
            else:
                logger.info(f"通达信板块脚本执行成功")
                if result.stdout:
                    # 提取关键输出行
                    for line in result.stdout.strip().split('\n'):
                        if any(kw in line for kw in
                               ['获取到', '共解析', 't_stock_list_in_sector', 't_sector_info', '板块类型分布', '数据插入完成']):
                            logger.info(f"  {line.strip()}")

            return {
                'success': success,
                'stdout': result.stdout,
                'stderr': result.stderr,
            }
        except subprocess.TimeoutExpired:
            logger.error("通达信板块脚本执行超时（600秒）")
            return {'success': False, 'stdout': '', 'stderr': 'Timeout expired'}
        except FileNotFoundError:
            logger.error(f"通达信板块脚本不存在: {script_path}")
            return {'success': False, 'stdout': '', 'stderr': f'Script not found: {script_path}'}
        except Exception as e:
            logger.error(f"调用通达信板块脚本异常: {e}")
            return {'success': False, 'stdout': '', 'stderr': str(e)}

    def sync_sector_info(self) -> dict:
        """
        步骤10: 同步板块基本信息 → t_sector_info

        通过 subprocess 调用通达信目录下的脚本获取板块信息并写入数据库。
        通达信 TQ 接口必须在通达信目录下运行，无法在本进程直接调用。

        Returns
        -------
        dict
            同步结果 {'count': int, 'status': str}
        """
        start_time = datetime.now()
        logger.info("开始同步板块基本信息（通过通达信脚本）...")

        try:
            result = self._run_tdx_sector_script()

            if not result['success']:
                raise RuntimeError(f"通达信板块脚本执行失败: {result.get('stderr', '')}")

            # 从数据库读取实际写入数量
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM t_sector_info')
                count = cursor.fetchone()[0]

            logger.info(f"板块基本信息同步完成: {count} 条")
            self._log_sync('sector_info', start_time, datetime.now(), count, 'success')
            return {'count': count, 'status': 'success'}

        except Exception as e:
            logger.error(f"同步板块基本信息失败: {e}", exc_info=True)
            self._log_sync('sector_info', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'count': 0, 'status': 'failed', 'error': str(e)}

    def sync_sector_constituents(self) -> dict:
        """
        步骤11: 同步板块成分股 → t_stock_list_in_sector

        通过 subprocess 调用通达信目录下的脚本获取板块成分股并写入数据库。
        通达信 TQ 接口必须在通达信目录下运行，无法在本进程直接调用。

        Returns
        -------
        dict
            同步结果 {'count': int, 'sector_count': int, 'status': str}
        """
        start_time = datetime.now()
        logger.info("开始同步板块成分股（通过通达信脚本）...")

        try:
            result = self._run_tdx_sector_script()

            if not result['success']:
                raise RuntimeError(f"通达信板块脚本执行失败: {result.get('stderr', '')}")

            # 从数据库读取实际写入数量
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM t_stock_list_in_sector')
                count = cursor.fetchone()[0]
                cursor.execute('SELECT COUNT(DISTINCT sector_code) FROM t_stock_list_in_sector')
                sector_count = cursor.fetchone()[0]

            logger.info(f"板块成分股同步完成: {sector_count} 个板块, {count} 条成分股")
            self._log_sync('sector_constituents', start_time, datetime.now(), count, 'success',
                           details=f'板块 {sector_count}, 成分股 {count}')
            return {'count': count, 'sector_count': sector_count, 'status': 'success'}

        except Exception as e:
            logger.error(f"同步板块成分股失败: {e}", exc_info=True)
            self._log_sync('sector_constituents', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'count': 0, 'sector_count': 0, 'status': 'failed', 'error': str(e)}

    def sync_financial_data(self, stock_list, start_date, end_date, progress_callback=None) -> dict:
        """
        步骤13: 同步财务数据 → t_finance_prime

        从东财 stk_get_finance_deriv_pt 截面查询获取财务衍生指标。

        Parameters
        ----------
        stock_list : list
            股票代码列表
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        dict
            同步结果 {'count': int, 'status': str}
        """
        start_time = datetime.now()
        logger.info(f"开始同步财务数据: {start_date} -> {end_date}")

        # 只同步股票（非指数）的财务数据
        stock_codes = [code for code in stock_list if not self._is_index_code(code)]
        total = len(stock_codes)

        # stk_get_finance_prime_pt 是截面查询，需按交易日遍历
        s_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if len(start_date) == 8 else start_date
        e_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date

        trade_dates = self.db.get_trade_dates(s_date, e_date)
        if not trade_dates:
            logger.warning(f"未找到 {s_date} ~ {e_date} 之间的交易日")
            return {'count': 0, 'stock_count': total, 'status': 'no_data'}

        logger.info(f"财务数据: {len(trade_dates)} 个交易日, {total} 只股票")

        try:
            source = self._get_source('financial_data')
        except ConnectionError as e:
            logger.error(f"财务数据源不可用: {e}")
            return {'count': 0, 'stock_count': total, 'status': 'failed'}

        record_count = 0
        error_count = 0

        for idx, trade_date in enumerate(trade_dates, 1):
            try:
                logger.info(f"财务数据 第 {idx}/{len(trade_dates)} 天: {trade_date}")
                df = source.get_financial_data(
                    symbols=stock_codes,
                    start_date=start_date,
                    end_date=trade_date.replace('-', ''),
                )

                if df is not None and not df.empty:
                    self.db.insert_t_finance_prime(df)
                    record_count += len(df)
                    logger.info(f"财务数据 {trade_date} 获取 {len(df)} 行")
                else:
                    logger.info(f"财务数据 {trade_date} 无数据")

                if progress_callback:
                    progress_callback('financial_data', idx, len(trade_dates),
                                      f'财务数据: {idx}/{len(trade_dates)} 天')

            except Exception as e:
                logger.warning(f"获取财务数据 {trade_date} 失败: {e}")
                error_count += 1

        status = 'success' if error_count == 0 else 'partial'
        logger.info(f"财务数据同步完成: {record_count} 条, 失败 {error_count} 天")
        self._log_sync('financial_data', start_time, datetime.now(), record_count, status,
                       details=f'记录 {record_count}, 失败 {error_count} 天')
        # 刷新 t_sync_data_log，记录当前 t_finance_prime 已有的日期
        self._refresh_sync_data_log('t_finance_prime', 'rpt_date')
        return {'count': record_count, 'stock_count': total, 'error_count': error_count, 'status': status}

    def sync_finance_deriv_data(self, stock_list, start_date, end_date, progress_callback=None) -> dict:
        """
        步骤14: 同步财务衍生指标 → t_finance_deriv

        从东财 stk_get_finance_deriv_pt 截面查询获取财务衍生指标（142个字段）。
        接口每次最多请求20个字段，由数据源层负责分批拼接合并。

        Parameters
        ----------
        stock_list : list
            股票代码列表
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD（作为截面查询日期）
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        dict
            同步结果 {'count': int, 'status': str}
        """
        start_time = datetime.now()
        logger.info(f"开始同步财务衍生指标: {start_date} -> {end_date}")

        # 只同步股票（非指数）的财务衍生指标
        stock_codes = [code for code in stock_list if not self._is_index_code(code)]
        total = len(stock_codes)

        # stk_get_finance_deriv_pt 是截面查询，需按交易日遍历
        s_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if len(start_date) == 8 else start_date
        e_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date

        trade_dates = self.db.get_trade_dates(s_date, e_date)
        if not trade_dates:
            logger.warning(f"未找到 {s_date} ~ {e_date} 之间的交易日")
            return {'count': 0, 'stock_count': total, 'status': 'no_data'}

        logger.info(f"财务衍生指标: {len(trade_dates)} 个交易日, {total} 只股票")

        try:
            source = self._get_source('finance_deriv_data')
        except ConnectionError as e:
            logger.error(f"财务衍生指标数据源不可用: {e}")
            return {'count': 0, 'stock_count': total, 'status': 'failed'}

        record_count = 0
        error_count = 0

        for idx, trade_date in enumerate(trade_dates, 1):
            try:
                logger.info(f"财务衍生指标 第 {idx}/{len(trade_dates)} 天: {trade_date}")
                df = source.get_finance_deriv_data(
                    symbols=stock_codes,
                    start_date=start_date,
                    end_date=trade_date.replace('-', ''),
                )

                if df is not None and not df.empty:
                    self.db.insert_finance_deriv_data(df)
                    record_count += len(df)
                    logger.info(f"财务衍生指标 {trade_date} 获取 {len(df)} 行")
                else:
                    logger.info(f"财务衍生指标 {trade_date} 无数据")

                if progress_callback:
                    progress_callback('finance_deriv_data', idx, len(trade_dates),
                                      f'财务衍生指标: {idx}/{len(trade_dates)} 天')

            except Exception as e:
                logger.warning(f"获取财务衍生指标 {trade_date} 失败: {e}")
                error_count += 1

        status = 'success' if error_count == 0 else 'partial'
        logger.info(f"财务衍生指标同步完成: {record_count} 条, 失败 {error_count} 天")
        self._log_sync('finance_deriv_data', start_time, datetime.now(), record_count, status,
                       details=f'记录 {record_count}, 失败 {error_count} 天')
        # 刷新 t_sync_data_log，记录当前 t_finance_deriv 已有的日期
        self._refresh_sync_data_log('t_finance_deriv', 'rpt_date')
        return {'count': record_count, 'stock_count': total, 'error_count': error_count, 'status': status}

    def sync_stock_mktvalue(self, stock_list, start_date: str, end_date: str) -> dict:
        """
        步骤15: 同步每日市值指标 → t_stock_mktvalue

        从东财 stk_get_daily_mktvalue_pt 截面查询获取市值指标
        （总市值、流通市值、企业价值等），按交易日遍历。

        Parameters
        ----------
        stock_list : list
            股票代码列表
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD

        Returns
        -------
        dict
            同步结果 {'count': int, 'status': str}
        """
        start_time = datetime.now()
        logger.info("开始同步每日市值指标...")

        try:
            source = self._get_source('daily_mktvalue')
            if not source:
                logger.warning("未找到每日市值数据源，跳过")
                self._log_sync('stock_mktvalue', start_time, datetime.now(), 0, 'skipped',
                               details='未找到数据源')
                return {'count': 0, 'status': 'skipped', 'reason': '未找到数据源'}

            # 日期格式：YYYYMMDD -> YYYY-MM-DD
            s_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if len(start_date) == 8 else start_date
            e_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date

            # 获取交易日列表
            trade_dates = self.db.get_trade_dates(s_date, e_date)
            if not trade_dates:
                logger.warning(f"未找到 {s_date} ~ {e_date} 之间的交易日")
                return {'count': 0, 'status': 'no_data'}

            logger.info(f"市值指标: {len(trade_dates)} 个交易日, {len(stock_list)} 只股票")

            # 按交易日遍历，每天一次 _pt 截面请求获取所有标的数据
            total_count = 0
            error_count = 0

            for idx, trade_date in enumerate(trade_dates, 1):
                try:
                    logger.info(f"市值指标 第 {idx}/{len(trade_dates)} 天: {trade_date}")
                    df = source.get_daily_mktvalue_pt_data(
                        symbols=stock_list,
                        trade_date=trade_date,
                    )
                    if df is not None and not df.empty:
                        count = self.db.insert_stock_mktvalue(df)
                        total_count += count
                        logger.info(f"市值指标 {trade_date} 获取 {len(df)} 行, 入库 {count} 条")
                    else:
                        logger.info(f"市值指标 {trade_date} 无数据")
                except Exception as e:
                    logger.warning(f"获取市值指标 {trade_date} 失败: {e}")
                    error_count += 1

                # 请求间隔，避免触发API限流
                if idx < len(trade_dates):
                    time.sleep(0.5)

            status = 'success' if total_count > 0 else 'no_data'
            logger.info(f"每日市值指标同步完成: {total_count} 条, 失败 {error_count} 天")
            self._log_sync('stock_mktvalue', start_time, datetime.now(), total_count, status)
            # 刷新 t_sync_data_log，记录当前 t_stock_mktvalue 已有的日期
            self._refresh_sync_data_log('t_stock_mktvalue', 'trade_date')
            return {'count': total_count, 'status': status}

        except Exception as e:
            logger.error(f"同步每日市值指标失败: {e}", exc_info=True)
            self._log_sync('stock_mktvalue', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'count': 0, 'status': 'failed', 'error': str(e)}

    def sync_valuation_data(self, stock_list, start_date: str, end_date: str) -> dict:
        """
        步骤16: 同步估值数据 → t_valuation_data

        从东财 stk_get_daily_valuation_pt 截面查询获取估值指标（PB/PE/PS/DY等），
        按交易日遍历。

        Parameters
        ----------
        stock_list : list
            股票代码列表
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD

        Returns
        -------
        dict
            同步结果 {'count': int, 'status': str}
        """
        start_time = datetime.now()
        logger.info(f"开始同步估值数据，日期范围: {start_date} ~ {end_date}")

        # 只同步股票（非指数）的估值数据
        stock_codes = [code for code in stock_list if not self._is_index_code(code)]

        try:
            source = self._get_source('valuation_data')
        except ConnectionError as e:
            logger.error(f"估值数据源不可用: {e}")
            return {'count': 0, 'stock_count': len(stock_codes), 'status': 'failed'}

        # 格式化查询日期
        s_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if len(start_date) == 8 else start_date
        e_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date

        # 获取交易日列表
        trade_dates = self.db.get_trade_dates(s_date, e_date)
        if not trade_dates:
            logger.warning(f"未找到 {s_date} ~ {e_date} 之间的交易日")
            return {'count': 0, 'stock_count': len(stock_codes), 'status': 'no_data'}

        logger.info(f"估值数据: {len(trade_dates)} 个交易日, {len(stock_codes)} 只股票")

        # 按交易日遍历，每天一次 _pt 截面请求获取所有标的数据
        record_count = 0
        error_count = 0

        for idx, trade_date in enumerate(trade_dates, 1):
            try:
                logger.info(f"估值数据 第 {idx}/{len(trade_dates)} 天: {trade_date}")
                df = source.get_daily_valuation_pt_data(
                    symbols=stock_codes,
                    trade_date=trade_date,
                )

                if df is not None and not df.empty:
                    # 统一列名映射
                    df = apply_column_mapping(df, 'daily')

                    # stock_code 统一转为内部格式
                    if 'stock_code' in df.columns:
                        from .symbol_converter import SymbolConverter
                        df['stock_code'] = df['stock_code'].apply(
                            lambda x: SymbolConverter.to_internal(str(x)) if '.' in str(x) else str(x)
                        )

                    self.db.insert_valuation_data(df)
                    record_count += len(df)
                    logger.info(f"估值数据 {trade_date} 写入 {len(df)} 条记录")
                else:
                    logger.info(f"估值数据 {trade_date} 无数据")

            except Exception as e:
                logger.warning(f"获取估值数据 {trade_date} 失败: {e}")
                error_count += 1

            # 请求间隔，避免触发API限流
            if idx < len(trade_dates):
                time.sleep(0.5)

        status = 'success' if error_count == 0 else 'partial'
        logger.info(f"估值数据同步完成: {record_count} 条, 失败 {error_count} 天")

        self._log_sync('valuation_data', start_time, datetime.now(), record_count, status,
                       details=f'记录 {record_count}, 失败 {error_count}')
        # 刷新 t_sync_data_log，记录当前 t_valuation_data 已有的日期
        self._refresh_sync_data_log('t_valuation_data', 'trade_date')
        return {'count': record_count, 'stock_count': len(stock_codes), 'error_count': error_count, 'status': status}

    def sync_dividend_data(self, stock_list: list = None, start_date: str = None,
                           end_date: str = None) -> dict:
        """
        步骤17: 同步除权除息数据 → t_dividend_date

        Parameters
        ----------
        stock_list : list, optional
            股票代码列表
        start_date : str, optional
            开始日期
        end_date : str, optional
            结束日期

        Returns
        -------
        dict
            同步结果 {'count': int, 'status': str}
        """
        start_time = datetime.now()
        logger.info("开始同步除权除息数据...")

        logger.warning("当前账号无 GetDividend 除权除息接口访问权限，跳过同步")
        self._log_sync('dividend_data', start_time, datetime.now(), 0, 'skipped',
                       details='无 GetDividend 接口访问权限')
        return {'count': 0, 'status': 'skipped', 'reason': '无 GetDividend 接口访问权限'}

        try:
            source = self._get_source('dividend_data')
            df = source.get_dividend_data(
                symbols=stock_list or [],
                start_date=start_date,
                end_date=end_date,
            )

            if df is None or df.empty:
                logger.warning("除权除息数据为空")
                self._log_sync('dividend_data', start_time, datetime.now(), 0, 'success',
                               details='数据为空')
                return {'count': 0, 'status': 'empty'}

            # 写入数据库
            record_count = self.db.insert_dividend_data(df)

            logger.info(f"除权除息数据同步完成: {record_count} 条")
            self._log_sync('dividend_data', start_time, datetime.now(), record_count, 'success')
            return {'count': record_count, 'status': 'success'}

        except Exception as e:
            logger.error(f"同步除权除息数据失败: {e}")
            self._log_sync('dividend_data', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'count': 0, 'status': 'failed', 'error': str(e)}

    # ============ 内部方法 ============

    def _sync_stock_daily(self, stock_codes, start_date, end_date, progress_callback) -> tuple:
        """
        批量同步股票日K线数据

        通过 SourceRegistry 路由到东财数据源，批量获取行情数据，
        计算 VWAP，填充停牌数据，写入 t_stock_daily 表。

        Returns
        -------
        tuple
            (stock_records, suspended_count)
        """
        stock_records = 0
        suspended_count = 0
        batch_size = 1000
        total_stocks = len(stock_codes)

        try:
            source = self._get_source('stock_daily')
        except ConnectionError as e:
            logger.error(f"股票行情数据源不可用: {e}")
            return 0, 0

        for batch_start in range(0, total_stocks, batch_size):
            batch_codes = stock_codes[batch_start:batch_start + batch_size]
            batch_end = min(batch_start + batch_size, total_stocks)

            try:
                # 批量获取行情数据
                batch_data = source.get_stock_daily_batch(
                    symbols=batch_codes,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=1,  # 前复权
                )

                if not batch_data:
                    if progress_callback and total_stocks > 0:
                        progress_callback('daily_data_stock', batch_end, total_stocks,
                                          f'股票行情: {batch_end}/{total_stocks}')
                    continue

                # 合并所有股票的数据
                all_frames = []
                for code, code_df in batch_data.items():
                    if code_df is None or code_df.empty:
                        continue

                    df = code_df.copy()

                    # 统一列名
                    col_rename = {}
                    if 'symbol' in df.columns and 'stock_code' not in df.columns:
                        col_rename['symbol'] = 'stock_code'
                    if 'eob' in df.columns and 'trade_date' not in df.columns:
                        col_rename['eob'] = 'trade_date'
                    if 'trade_time' in df.columns and 'trade_date' not in df.columns:
                        col_rename['trade_time'] = 'trade_date'
                    if 'pre_close' not in df.columns and 'preClose' in df.columns:
                        col_rename['preClose'] = 'pre_close'
                    if col_rename:
                        df = df.rename(columns=col_rename)

                    # 确保有 stock_code 列，统一为内部格式
                    if 'stock_code' not in df.columns:
                        df['stock_code'] = code
                    else:
                        from .symbol_converter import SymbolConverter
                        df['stock_code'] = df['stock_code'].apply(
                            lambda x: SymbolConverter.to_internal(str(x)) if '.' in str(x) else str(x)
                        )

                    # 计算 VWAP
                    if 'vwap' not in df.columns:
                        df['vwap'] = df.apply(
                            lambda row: self._calculate_vwap(
                                row.get('amount'), row.get('volume'), row.get('pre_close')
                            ), axis=1
                        )

                    # 填充停牌数据
                    df = self._fill_suspended_data(df, code)

                    all_frames.append(df)

                if not all_frames:
                    if progress_callback and total_stocks > 0:
                        progress_callback('daily_data_stock', batch_end, total_stocks,
                                          f'股票行情: {batch_end}/{total_stocks}')
                    continue

                df = pd.concat(all_frames, ignore_index=True)

                # 统计停牌数
                if 'suspend_flag' in df.columns:
                    suspended_count += int(df['suspend_flag'].sum())

                # 写入数据库
                self.db.insert_stock_daily(df)
                stock_records += len(df)

            except Exception as e:
                logger.warning(f"获取股票行情批次失败 [{batch_start}:{batch_end}]: {e}", exc_info=True)

            # 进度回调
            if progress_callback and total_stocks > 0:
                progress_callback('daily_data_stock', batch_end, total_stocks,
                                  f'股票行情: {batch_end}/{total_stocks}')

        return stock_records, suspended_count

    def _sync_index_daily(self, index_codes, start_date, end_date, progress_callback,
                          total_stocks=0) -> int:
        """
        批量同步指数日K线数据

        通过 SourceRegistry 路由到东财数据源，获取行情数据后写入 t_index_daily 表。

        Returns
        -------
        int
            指数记录数
        """
        index_records = 0
        batch_size = 1000
        total_indices = len(index_codes)

        try:
            source = self._get_source('index_daily')
        except ConnectionError as e:
            logger.error(f"指数行情数据源不可用: {e}")
            return 0

        for batch_start in range(0, total_indices, batch_size):
            batch_codes = index_codes[batch_start:batch_start + batch_size]
            batch_end = min(batch_start + batch_size, total_indices)

            try:
                all_frames = []
                for code in batch_codes:
                    df = source.get_index_daily(
                        symbol=code,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    if df is None or df.empty:
                        continue

                    df = df.copy()

                    # 统一列名
                    col_rename = {}
                    if 'symbol' in df.columns and 'index_code' not in df.columns:
                        col_rename['symbol'] = 'index_code'
                    if 'eob' in df.columns and 'trade_date' not in df.columns:
                        col_rename['eob'] = 'trade_date'
                    if 'trade_time' in df.columns and 'trade_date' not in df.columns:
                        col_rename['trade_time'] = 'trade_date'
                    if col_rename:
                        df = df.rename(columns=col_rename)

                    if 'index_code' not in df.columns:
                        df['index_code'] = code
                    else:
                        from .symbol_converter import SymbolConverter
                        df['index_code'] = df['index_code'].apply(
                            lambda x: SymbolConverter.to_internal(str(x)) if '.' in str(x) else str(x)
                        )

                    all_frames.append(df)

                if not all_frames:
                    if progress_callback and total_indices > 0:
                        progress_callback('daily_data_index', batch_end, total_indices,
                                          f'指数行情: {batch_end}/{total_indices}')
                    continue

                df = pd.concat(all_frames, ignore_index=True)

                # 写入数据库
                self.db.insert_index_daily(df)
                index_records += len(df)

            except Exception as e:
                logger.debug(f"获取指数行情批次失败 [{batch_start}:{batch_end}]: {e}")

            # 进度回调
            if progress_callback and total_indices > 0:
                progress_callback('daily_data_index', batch_end, total_indices,
                                  f'指数行情: {batch_end}/{total_indices}')

        return index_records

    def _calculate_vwap(self, amount, volume, pre_close) -> float:
        """计算VWAP：amount/volume，停牌时用pre_close"""
        if volume is None or volume == 0 or pd.isna(volume):
            if pre_close is not None and not pd.isna(pre_close):
                return float(pre_close)
            return 0.0

        if amount is None or pd.isna(amount):
            if pre_close is not None and not pd.isna(pre_close):
                return float(pre_close)
            return 0.0

        vwap = float(amount) / float(volume)
        if vwap <= 0 and pre_close is not None and not pd.isna(pre_close):
            return float(pre_close)

        return vwap

    def _fill_suspended_data(self, df, stock_code) -> pd.DataFrame:
        """填充停牌数据：OHLC用前收盘价，volume=0，suspend_flag=1"""
        if df.empty:
            return df

        df = df.copy()

        # 确保有 pre_close 列
        if 'pre_close' not in df.columns:
            df['pre_close'] = df['close'].shift(1)

        # 通过volume=0判断停牌
        volume_series = df['volume'].fillna(0)
        suspended_mask = volume_series == 0

        if not suspended_mask.any():
            df['suspend_flag'] = 0
            return df

        # 停牌数据填充
        df.loc[suspended_mask, 'open'] = df.loc[suspended_mask, 'pre_close']
        df.loc[suspended_mask, 'high'] = df.loc[suspended_mask, 'pre_close']
        df.loc[suspended_mask, 'low'] = df.loc[suspended_mask, 'pre_close']
        df.loc[suspended_mask, 'close'] = df.loc[suspended_mask, 'pre_close']
        df.loc[suspended_mask, 'volume'] = 0
        df.loc[suspended_mask, 'amount'] = 0

        # 标记停牌
        df['suspend_flag'] = suspended_mask.astype('int64')

        # 对于停牌且pre_close也为空的情况，尝试用前一天的close填充
        null_pre_close = df['pre_close'].isna() & suspended_mask
        if null_pre_close.any():
            df['pre_close'] = df['pre_close'].ffill()
            still_null = df['pre_close'].isna() & suspended_mask
            if still_null.any():
                df.loc[still_null, 'pre_close'] = df['close'].bfill()
                df.loc[still_null, 'open'] = df.loc[still_null, 'pre_close']
                df.loc[still_null, 'high'] = df.loc[still_null, 'pre_close']
                df.loc[still_null, 'low'] = df.loc[still_null, 'pre_close']
                df.loc[still_null, 'close'] = df.loc[still_null, 'pre_close']

        return df

    def _log_sync(self, sync_type, start_time, end_time, record_count, status,
                  error_message='', details=''):
        """记录同步日志到 t_data_sync 表"""
        try:
            self.db.insert_data_sync_log(
                sync_type=sync_type,
                start_time=start_time.strftime('%Y-%m-%d %H:%M:%S') if start_time else None,
                end_time=end_time.strftime('%Y-%m-%d %H:%M:%S') if end_time else None,
                record_count=record_count,
                status=status,
                error_message=error_message,
                details=details,
            )
        except Exception as e:
            logger.error(f"记录同步日志失败: {e}")

    def _refresh_sync_data_log(self, table_name: str, date_column: str = 'trade_date') -> None:
        """
        刷新 t_sync_data_log 表中指定表的日期记录。

        在某个数据表同步完成后调用：
        1. 删除 t_sync_data_log 中该表的所有旧记录
        2. 从该表查询 distinct 日期，重新插入 t_sync_data_log

        这样可以通过 t_sync_data_log 快速查询数据库中每个表已有哪些日期的数据。

        Parameters
        ----------
        table_name : str
            已完成同步的数据表名（如 t_stock_daily）
        date_column : str
            该表的日期字段名，默认为 'trade_date'
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # 步骤1: 删除该表的旧日志记录
                cursor.execute(
                    'DELETE FROM t_sync_data_log WHERE table_name = ?',
                    (table_name,)
                )
                # 步骤2: 从数据表查询 distinct 日期并插入日志
                cursor.execute(
                    f'INSERT INTO t_sync_data_log (table_name, data_date) '
                    f'SELECT DISTINCT ?, {date_column} FROM {table_name}',
                    (table_name,)
                )
                conn.commit()

            # 查询写入数量用于日志
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT COUNT(*) FROM t_sync_data_log WHERE table_name = ?',
                    (table_name,)
                )
                count = cursor.fetchone()[0]
            logger.info(f"已刷新 t_sync_data_log: {table_name} 共 {count} 个日期记录")
        except Exception as e:
            logger.error(f"刷新 t_sync_data_log 失败 (table={table_name}): {e}")


    def _report_progress(self, callback, stage, current, total, message):
        """报告进度"""
        if callback:
            try:
                callback(stage, current, total, message)
            except Exception as e:
                logger.debug(f"进度回调异常: {e}")

    # ============ 辅助方法 ============

    def get_all_index_codes(self) -> set:
        """获取所有指数代码（硬编码 + 数据库中的指数/板块代码）"""
        codes = set(self.KNOWN_INDEX_CODES)

        if self.db:
            try:
                with self.db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT DISTINCT index_code FROM t_stock_in_index')
                    for row in cursor.fetchall():
                        codes.add(row[0])
            except Exception as e:
                logger.warning(f"从数据库获取指数代码失败: {e}")

        return codes

    # 缓存动态指数代码
    _dynamic_index_codes_cache = None
    _dynamic_index_codes_time = None

    def _get_cached_index_codes(self) -> set:
        """获取带缓存的动态指数代码（缓存5分钟）"""
        import time
        now = time.time()
        if (self._dynamic_index_codes_cache is not None
                and self._dynamic_index_codes_time is not None
                and now - self._dynamic_index_codes_time < 300):
            return self._dynamic_index_codes_cache

        codes = self.get_all_index_codes()
        self._dynamic_index_codes_cache = codes
        self._dynamic_index_codes_time = now
        return codes

    def _is_index_code(self, code) -> bool:
        """
        判断是否为指数代码

        优先级：
        1. 硬编码已知指数列表
        2. 数据库 t_stock_in_index 表中的指数
        3. 399开头（深交所指数）
        """
        if not isinstance(code, str):
            return False

        # 1. 硬编码已知指数列表
        if code in self.KNOWN_INDEX_CODES:
            return True

        # 2. 数据库中的指数
        try:
            dynamic_codes = self._get_cached_index_codes()
            if code in dynamic_codes:
                return True
        except Exception:
            pass

        # 3. 399开头的一律视为深交所指数
        code_part = code.split('.')[0] if '.' in code else code
        if code_part.startswith('399') and len(code_part) == 6:
            return True

        return False

    def get_instrument_type(self, stock_code: str) -> str:
        """
        获取标的类型

        Parameters
        ----------
        stock_code : str
            标的代码，如 '000001.SZ'

        Returns
        -------
        str
            标的类型: 'stock', 'index', 'etf', 'fund', 'bond', 'unknown'
        """
        if not isinstance(stock_code, str) or not stock_code:
            return 'unknown'

        # 1. 检查是否为指数
        if self._is_index_code(stock_code):
            return 'index'

        # 2. 代码规则判断
        code_part = stock_code.split('.')[0] if '.' in stock_code else stock_code

        # ETF（常见代码前缀）
        if len(code_part) == 6 and code_part.startswith(('51', '15', '16', '58', '59')):
            return 'etf'

        # 基金
        if len(code_part) == 6 and code_part.startswith('50'):
            return 'fund'

        # 债券
        if len(code_part) == 6 and code_part.startswith(('11', '12', '13')):
            return 'bond'

        return 'stock'

    # ============ 同步后自动 inspect + 补同步闭环 ============

    def _run_sync_inspect_loop(self, start_date: str, end_date: str, results: dict,
                                max_rounds: int = 3):
        """同步后自动检查缺失并补同步，最多 max_rounds 轮"""
        try:
            from .inspector import DataInspector
        except ImportError:
            logger.warning("DataInspector 不可用，跳过同步后检查")
            return

        inspector = DataInspector(self.db)

        for round_num in range(1, max_rounds + 1):
            logger.info(f"同步后检查 第{round_num}轮...")
            report = inspector.inspect(start_date, end_date)

            # 收集所有缺失的代码
            all_missing = set()
            for data_type, details in report.items():
                missing_codes = details.get('missing_codes', [])
                if missing_codes:
                    all_missing.update(missing_codes)
                    logger.info(f"  {data_type}: {len(missing_codes)} 个代码存在缺失")

            if not all_missing:
                logger.info(f"同步后检查 第{round_num}轮: 数据完整，无缺失")
                results['inspect_report'] = report
                break

            logger.info(f"同步后检查 第{round_num}轮: 发现 {len(all_missing)} 个代码缺失，尝试补同步...")

            try:
                missing_list = list(all_missing)
                # 区分股票和指数
                stock_codes = [c for c in missing_list if not self._is_index_code(c)]
                index_codes = [c for c in missing_list if self._is_index_code(c)]

                if stock_codes:
                    stock_records, _ = self._sync_stock_daily(
                        stock_codes, start_date, end_date, None
                    )
                    results.setdefault('resync_rounds', []).append({
                        'round': round_num,
                        'type': 'stock',
                        'missing_count': len(stock_codes),
                        'resync_records': stock_records,
                    })

                if index_codes:
                    index_records = self._sync_index_daily(
                        index_codes, start_date, end_date, None
                    )
                    results.setdefault('resync_rounds', []).append({
                        'round': round_num,
                        'type': 'index',
                        'missing_count': len(index_codes),
                        'resync_records': index_records,
                    })

            except Exception as e:
                logger.error(f"补同步失败: {e}")
                results['inspect_report'] = report
                break
        else:
            logger.warning(f"同步后检查: 已达最大轮次 {max_rounds}，仍有缺失")
            results['inspect_report'] = report


