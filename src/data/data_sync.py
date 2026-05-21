"""
数据同步模块
============

负责从QMT下载数据并写入SQLite数据库。
支持全量同步和增量同步，自动计算VWAP，填充停牌数据。

所有表定义统一由 database.py 管理，本模块不创建任何表。
"""

import logging
import sqlite3
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable

import pandas as pd
import numpy as np

from .qmt_adapter import QMTDataAdapter

logger = logging.getLogger(__name__)


class DataSynchronizer:
    """
    数据同步器

    从QMT数据源同步数据到SQLite数据库，支持全量/增量同步，
    自动计算VWAP，填充停牌数据，批量写入数据库。

    Parameters
    ----------
    qmt_connector : QMTConnector
        QMT数据连接器实例，提供以下方法：
        - get_stock_list_in_sector(sector_name) -> list
        - get_instrument_detail(stock_code) -> dict
        - get_market_data_ex(stock_list, period, start_time, end_time, ...) -> dict
        - get_sector_list() -> list
        - get_financial_data(stock_list, table_list, start_time, end_time) -> dict
        - download_history_data(stock_list, period, start_time, end_time)
        - download_sector_data()
        - download_financial_data(stock_list, table_list, start_time, end_time)
    db_manager : DatabaseManager
        数据库管理器实例，提供以下方法：
        - insert_stock_daily(df) -> int
        - insert_index_daily(df) -> int
        - insert_stock_info(df) -> int
        - insert_qmt_instruments(df) -> int
        - insert_data_sync_log(...) -> int
    """

    # 已知指数代码列表（用于区分股票和指数）
    KNOWN_INDEX_CODES = frozenset({
        '000001.SH', '000300.SH', '000852.SH', '000905.SH',
        '000016.SH', '000015.SH', '399001.SZ', '399006.SZ',
        '399005.SZ', '399300.SZ', '399673.SZ',
    })

    def __init__(self, qmt_connector, db_manager):
        self.qmt = qmt_connector
        self.db = db_manager

    # ============ 公开方法 ============

    def sync_all(self, start_date='20230101', end_date='', progress_callback=None) -> dict:
        """
        全量同步：股票列表 -> 基本信息 -> 行情数据 -> 板块数据 -> 财务数据

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
            'stock_list': {},
            'instruments': {},
            'daily_data': {},
            'sector_data': {},
            'financial_data': {},
            'errors': [],
        }

        try:
            # 1. 同步股票列表
            self._report_progress(progress_callback, 'stock_list', 0, 5, '正在同步股票列表...')
            stock_list = self.sync_stock_list()
            results['stock_list'] = {
                'status': 'success',
                'count': len(stock_list),
            }
            self._report_progress(progress_callback, 'stock_list', 1, 5,
                                  f'股票列表同步完成，共 {len(stock_list)} 条')

            if not stock_list:
                logger.warning("股票列表为空，跳过后续同步")
                results['errors'].append('股票列表为空')
                self._log_sync('full_sync', start_time, datetime.now(), 0, 'failed',
                               error_message='股票列表为空')
                return results

            # 2. 同步合约基本信息
            self._report_progress(progress_callback, 'instruments', 1, 5, '正在同步合约信息...')
            instrument_count = self.sync_instruments(stock_list)
            results['instruments'] = {
                'status': 'success',
                'count': instrument_count,
            }
            self._report_progress(progress_callback, 'instruments', 2, 5,
                                  f'合约信息同步完成，共 {instrument_count} 条')

            # 3. 同步行情数据
            self._report_progress(progress_callback, 'daily_data', 2, 5, '正在同步行情数据...')
            daily_result = self.sync_daily_data(stock_list, start_date, end_date, progress_callback)
            results['daily_data'] = daily_result
            self._report_progress(progress_callback, 'daily_data', 3, 5,
                                  f'行情数据同步完成，股票 {daily_result.get("stock_records", 0)} 条，'
                                  f'指数 {daily_result.get("index_records", 0)} 条')

            # 4. 同步板块数据
            self._report_progress(progress_callback, 'sector_data', 3, 5, '正在同步板块数据...')
            sector_result = self.sync_sector_data()
            results['sector_data'] = sector_result
            self._report_progress(progress_callback, 'sector_data', 4, 5,
                                  f'板块数据同步完成，共 {sector_result.get("sector_count", 0)} 个板块')

            # 5. 同步财务数据
            self._report_progress(progress_callback, 'financial_data', 4, 5, '正在同步财务数据...')
            financial_result = self.sync_financial_data(stock_list, start_date, end_date, progress_callback)
            results['financial_data'] = financial_result
            self._report_progress(progress_callback, 'financial_data', 5, 5,
                                  f'财务数据同步完成，共 {financial_result.get("record_count", 0)} 条')

            end_time = datetime.now()
            total_records = (
                results['stock_list'].get('count', 0) +
                results['instruments'].get('count', 0) +
                results['daily_data'].get('stock_records', 0) +
                results['daily_data'].get('index_records', 0) +
                results['financial_data'].get('record_count', 0)
            )
            self._log_sync('full_sync', start_time, end_time, total_records, 'success',
                           details=f'全量同步完成，耗时 {(end_time - start_time).total_seconds():.1f}s')

            logger.info(f"全量同步完成，耗时 {(end_time - start_time).total_seconds():.1f}s")

        except Exception as e:
            logger.error(f"全量同步失败: {e}", exc_info=True)
            results['errors'].append(str(e))
            self._log_sync('full_sync', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))

        self._report_progress(progress_callback, 'done', 5, 5, '全量同步完成')
        return results

    def sync_stock_list(self) -> list:
        """
        从QMT获取全部A股股票列表

        调用 self.qmt.get_stock_list_in_sector('沪深A股') 获取。

        Returns
        -------
        list
            合约代码列表，如 ['600000.SH', '000001.SZ', ...]
        """
        start_time = datetime.now()
        logger.info("开始同步股票列表...")

        try:
            stock_codes = self.qmt.get_stock_list_in_sector('沪深A股')
            if stock_codes is None or len(stock_codes) == 0:
                logger.warning("QMT返回的股票列表为空")
                self._log_sync('stock_list', start_time, datetime.now(), 0, 'success',
                               details='列表为空')
                return []

            # get_stock_list_in_sector 返回的是 list[str]，直接使用
            logger.info(f"股票列表同步完成，共 {len(stock_codes)} 条")
            self._log_sync('stock_list', start_time, datetime.now(), len(stock_codes), 'success')
            return stock_codes

        except Exception as e:
            logger.error(f"同步股票列表失败: {e}", exc_info=True)
            self._log_sync('stock_list', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return []

    def sync_instruments(self, stock_list) -> int:
        """
        同步合约基本信息到 stock_info 表和 qmt_instrument 表

        对每只股票调用 self.qmt.get_instrument_detail(code) 获取详情，
        然后通过 QMTDataAdapter.transform_instrument_detail() 转换格式，
        最后调用 self.db.insert_stock_info() 和 self.db.insert_qmt_instruments() 写入。

        Parameters
        ----------
        stock_list : list
            合约代码列表

        Returns
        -------
        int
            同步成功的合约数量
        """
        start_time = datetime.now()
        logger.info(f"开始同步合约信息，共 {len(stock_list)} 条...")

        stock_info_rows = []
        qmt_instrument_rows = []
        success_count = 0
        error_count = 0

        for i, code in enumerate(stock_list):
            try:
                detail = self.qmt.get_instrument_detail(code)
                if not detail:
                    error_count += 1
                    continue

                # 使用 QMTDataAdapter 转换为 stock_info 格式
                stock_info_dict = QMTDataAdapter.transform_instrument_detail(detail, code)
                stock_info_rows.append(stock_info_dict)

                # 构建 qmt_instrument 行（使用 QMT 原始字段名映射到 database.py 表字段）
                qmt_instrument_rows.append({
                    'stock_code': code,
                    'instrument_name': detail.get('InstrumentName', ''),
                    'exchange_id': detail.get('ExchangeID', ''),
                    'product_type': detail.get('ProductClassification'),
                    'open_date': self._format_qmt_date(detail.get('OpenDate')),
                    'pre_close': detail.get('PreClose'),
                    'up_stop_price': detail.get('UpperLimit'),
                    'down_stop_price': detail.get('LowerLimit'),
                    'float_volume': detail.get('FloatVolume'),
                    'total_volume': detail.get('TotalVolume'),
                    'price_tick': detail.get('PriceTick'),
                    'instrument_status': 0,
                })

                success_count += 1

            except Exception as e:
                logger.debug(f"获取合约 {code} 信息失败: {e}")
                error_count += 1

        # 批量写入 stock_info
        if stock_info_rows:
            stock_info_df = pd.DataFrame(stock_info_rows)
            self.db.insert_stock_info(stock_info_df)

        # 批量写入 qmt_instrument
        if qmt_instrument_rows:
            qmt_df = pd.DataFrame(qmt_instrument_rows)
            self.db.insert_qmt_instruments(qmt_df)

        logger.info(f"合约信息同步完成: 成功 {success_count}, 失败 {error_count}")
        self._log_sync('instruments', start_time, datetime.now(), success_count,
                       'success' if error_count == 0 else 'partial',
                       details=f'成功 {success_count}, 失败 {error_count}')
        return success_count

    def sync_daily_data(self, stock_list, start_date, end_date, progress_callback=None) -> dict:
        """
        同步日K线数据到 stock_daily 和 index_daily 表

        使用 self.qmt.get_market_data_ex(stock_list, ...) 批量获取行情数据，
        通过 QMTDataAdapter.transform_market_data() 转换格式，
        然后区分股票和指数分别写入。

        Parameters
        ----------
        stock_list : list
            合约代码列表
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        dict
            同步结果，包含 stock_records, index_records, suspended_count 等
        """
        start_time = datetime.now()
        logger.info(f"开始同步行情数据: {start_date} -> {end_date}, 共 {len(stock_list)} 条")

        # 区分股票和指数
        stock_codes = []
        index_codes = []
        for code in stock_list:
            if self._is_index_code(code):
                index_codes.append(code)
            else:
                stock_codes.append(code)

        stock_records = 0
        index_records = 0
        suspended_count = 0

        # ---- 同步股票日K线 ----
        if stock_codes:
            stock_records, stock_suspended = self._sync_stock_daily(
                stock_codes, start_date, end_date, progress_callback
            )
            suspended_count = stock_suspended

        # ---- 同步指数日K线 ----
        if index_codes:
            index_records = self._sync_index_daily(
                index_codes, start_date, end_date, progress_callback,
                total_stocks=len(stock_codes)  # 用于进度偏移
            )

        result = {
            'stock_records': stock_records,
            'index_records': index_records,
            'suspended_count': suspended_count,
            'stock_count': len(stock_codes),
            'index_count': len(index_codes),
        }

        logger.info(f"行情数据同步完成: 股票 {stock_records} 条, 指数 {index_records} 条, "
                     f"停牌 {suspended_count} 条")
        self._log_sync('daily_data', start_time, datetime.now(),
                       stock_records + index_records, 'success',
                       details=f'股票 {stock_records}, 指数 {index_records}, 停牌 {suspended_count}')
        return result

    def sync_index_data(self, start_date: str, end_date: str = '', progress_callback=None) -> int:
        """
        单独同步指数日K线数据

        Parameters
        ----------
        start_date : str
            起始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD，默认为空表示最新
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        int
            同步的指数记录数
        """
        start_time = datetime.now()
        logger.info(f"开始同步指数数据: {start_date} -> {end_date or '最新'}")

        # 获取指数列表
        index_codes = self.qmt.get_index_list()
        if not index_codes:
            logger.warning("指数列表为空")
            return 0

        logger.info(f"获取到 {len(index_codes)} 个指数")

        # 先下载指数历史数据
        logger.info(f"开始下载 {len(index_codes)} 个指数的历史数据...")
        try:
            self.qmt.download_history_data(index_codes, period='1d',
                                          start_time=start_date, end_time=end_date)
        except Exception as e:
            logger.warning(f"批量下载指数历史数据失败: {e}")
        logger.info("指数历史数据下载完成")

        # 同步指数数据
        index_records = self._sync_index_daily(
            index_codes, start_date, end_date, progress_callback
        )

        logger.info(f"指数数据同步完成: {index_records} 条, {len(index_codes)} 个指数")
        self._log_sync('index_daily', start_time, datetime.now(),
                       index_records, 'success',
                       details=f'指数 {index_records} 条, {len(index_codes)} 个')
        return index_records

    def sync_sector_data(self) -> dict:
        """
        同步板块数据和成分股，以及指数成分股权重

        调用 self.qmt.get_sector_list() 获取板块列表，
        调用 self.qmt.get_stock_list_in_sector(sector) 获取每个板块的成分股。
        对已知指数调用 self.qmt.get_index_weight() 获取成分股权重。

        Returns
        -------
        dict
            同步结果，包含 sector_count, constituent_count, index_weight_count 等
        """
        start_time = datetime.now()
        logger.info("开始同步板块数据...")

        try:
            sector_list = self.qmt.get_sector_list()
            if sector_list is None or len(sector_list) == 0:
                logger.warning("板块列表为空")
                self._log_sync('sector_data', start_time, datetime.now(), 0, 'success',
                               details='板块列表为空')
                return {'sector_count': 0, 'constituent_count': 0, 'index_weight_count': 0}

            # get_sector_list 返回的是板块名称列表
            sector_count = len(sector_list)
            constituent_count = 0
            sector_constituent_rows = []

            for sector_name in sector_list:
                try:
                    constituents = self.qmt.get_stock_list_in_sector(sector_name)
                    if constituents and len(constituents) > 0:
                        for stock_code in constituents:
                            sector_constituent_rows.append({
                                'sector_code': sector_name,
                                'stock_code': stock_code,
                            })
                        constituent_count += len(constituents)
                except Exception as e:
                    logger.debug(f"获取板块 [{sector_name}] 成分股失败: {e}")

            # 写入板块成分股到 index_constituent 表（weight为0）
            if sector_constituent_rows:
                sector_df = pd.DataFrame(sector_constituent_rows)
                sector_df = sector_df.rename(columns={'sector_code': 'index_code'})
                sector_df['weight'] = 0.0
                self.db.insert_index_constituent(sector_df)
                logger.info(f"写入板块成分股: {len(sector_constituent_rows)} 条")

            # 同步指数成分股权重
            index_weight_count = 0
            index_constituent_rows = []

            # 先下载指数权重数据
            try:
                logger.info(f"开始下载指数权重数据...")
                self.qmt.download_index_weight(list(self.KNOWN_INDEX_CODES))
                logger.info("指数权重数据下载完成")
            except Exception as e:
                logger.warning(f"下载指数权重数据失败: {e}")

            for index_code in self.KNOWN_INDEX_CODES:
                try:
                    weight_data = self.qmt.get_index_weight(index_code)
                    if weight_data and isinstance(weight_data, dict) and len(weight_data) > 0:
                        for stock_code, weight in weight_data.items():
                            index_constituent_rows.append({
                                'index_code': index_code,
                                'stock_code': stock_code,
                                'weight': float(weight),
                            })
                        index_weight_count += len(weight_data)
                        logger.debug(f"指数 [{index_code}] 成分股 {len(weight_data)} 条")
                except Exception as e:
                    logger.debug(f"获取指数 [{index_code}] 权重失败: {e}")

            # 批量写入指数成分股权重
            if index_constituent_rows:
                index_df = pd.DataFrame(index_constituent_rows)
                self.db.insert_index_constituent(index_df)
                logger.info(f"写入指数成分股权重: {len(index_constituent_rows)} 条")

            result = {
                'sector_count': sector_count,
                'constituent_count': constituent_count,
                'index_weight_count': index_weight_count,
            }

            logger.info(f"板块数据同步完成: {sector_count} 个板块, {constituent_count} 条成分股, "
                        f"{index_weight_count} 条指数权重")
            self._log_sync('sector_data', start_time, datetime.now(),
                           sector_count + constituent_count + index_weight_count, 'success',
                           details=f'板块 {sector_count}, 成分股 {constituent_count}, 指数权重 {index_weight_count}')
            return result

        except Exception as e:
            logger.error(f"同步板块数据失败: {e}", exc_info=True)
            self._log_sync('sector_data', start_time, datetime.now(), 0, 'failed',
                           error_message=str(e))
            return {'sector_count': 0, 'constituent_count': 0, 'index_weight_count': 0, 'error': str(e)}

    def sync_financial_data(self, stock_list, start_date, end_date, progress_callback=None) -> dict:
        """
        同步财务数据

        调用 self.qmt.get_financial_data(stock_list, table_list, start, end) 批量获取，
        通过 QMTDataAdapter.transform_financial_data() 转换格式。

        Parameters
        ----------
        stock_list : list
            合约代码列表
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        dict
            同步结果，包含 record_count 等
        """
        start_time = datetime.now()
        logger.info(f"开始同步财务数据: {start_date} -> {end_date}")

        # 只同步股票（非指数）的财务数据
        stock_codes = [code for code in stock_list if not self._is_index_code(code)]
        total = len(stock_codes)
        record_count = 0
        error_count = 0

        # QMT财务报表类型
        table_list = ['Balance', 'Income', 'CashFlow']

        # 分批处理，每批100只股票
        batch_size = 100
        batch_count = (total + batch_size - 1) // batch_size

        logger.info(f"财务数据分批处理: {total}只股票, {batch_count}批, 每批{batch_size}只")

        for batch_idx in range(batch_count):
            batch_start = batch_idx * batch_size
            batch_end = min(batch_start + batch_size, total)
            batch_codes = stock_codes[batch_start:batch_end]

            try:
                logger.info(f"处理第 {batch_idx + 1}/{batch_count} 批: {len(batch_codes)}只股票")

                # 1. 下载本批财务数据
                try:
                    self.qmt.download_financial_data(
                        batch_codes, table_list, start_date, end_date
                    )
                except Exception as e:
                    logger.warning(f"第 {batch_idx + 1} 批下载失败: {e}")
                    error_count += len(batch_codes)
                    continue

                # 2. 获取本批财务数据
                financial_data = self.qmt.get_financial_data(
                    batch_codes, table_list, start_date, end_date
                )

                if financial_data:
                    # 3. 转换并写入本批数据
                    batch_rows = []
                    for stock_code, stock_tables in financial_data.items():
                        if not isinstance(stock_tables, dict):
                            continue
                        for table_name, table_df in stock_tables.items():
                            if table_df is None or table_df.empty:
                                continue
                            for report_date, row in table_df.iterrows():
                                row_data = row.to_dict()
                                row_data = {
                                    k: (None if (isinstance(v, float) and pd.isna(v)) else v)
                                    for k, v in row_data.items()
                                }
                                batch_rows.append({
                                    'stock_code': stock_code,
                                    'report_date': str(report_date),
                                    'table_name': table_name,
                                    'data_json': row_data,
                                })

                    if batch_rows:
                        financial_df = pd.DataFrame(batch_rows)
                        self.db.insert_financial_data(financial_df)
                        record_count += len(batch_rows)
                        logger.info(f"第 {batch_idx + 1} 批写入 {len(batch_rows)} 条记录")

                if progress_callback:
                    progress_callback('financial_data', batch_end, total,
                                      f'财务数据: {batch_end}/{total}')

            except Exception as e:
                logger.error(f"第 {batch_idx + 1} 批处理失败: {e}")
                error_count += len(batch_codes)

        result = {
            'record_count': record_count,
            'stock_count': total,
            'error_count': error_count,
        }

        logger.info(f"财务数据同步完成: {record_count} 条, 失败 {error_count}")
        self._log_sync('financial_data', start_time, datetime.now(), record_count,
                       'success' if error_count == 0 else 'partial',
                       details=f'记录 {record_count}, 失败 {error_count}')
        return result

    # ============ 内部方法 ============

    def _sync_stock_daily(self, stock_codes, start_date, end_date, progress_callback) -> tuple:
        """
        批量同步股票日K线数据

        先下载历史数据，再使用 get_market_data_ex 批量获取，transform_market_data 转换，
        计算 VWAP，填充停牌数据，写入 stock_daily 表。

        Returns
        -------
        tuple
            (stock_records, suspended_count)
        """
        stock_records = 0
        suspended_count = 0
        batch_size = 100  # 每批100只股票
        total_stocks = len(stock_codes)

        # 先下载所有股票的历史数据
        logger.info(f"开始下载 {total_stocks} 只股票的历史数据...")
        try:
            self.qmt.download_history_data(stock_codes, period='1d', start_time=start_date, end_time=end_date)
        except Exception as e:
            logger.warning(f"批量下载历史数据失败: {e}")
        logger.info("历史数据下载完成")

        for batch_start in range(0, total_stocks, batch_size):
            batch_codes = stock_codes[batch_start:batch_start + batch_size]
            batch_end = min(batch_start + batch_size, total_stocks)

            try:
                # 批量获取行情数据
                qmt_data = self.qmt.get_market_data_ex(
                    batch_codes, period='1d',
                    start_time=start_date, end_time=end_date,
                    dividend_type='front'
                )

                if not qmt_data:
                    # 进度回调
                    if progress_callback and total_stocks > 0:
                        progress_callback('daily_data_stock', batch_end, total_stocks,
                                          f'股票行情: {batch_end}/{total_stocks}')
                    continue

                # 使用 QMTDataAdapter 转换格式
                df = QMTDataAdapter.transform_market_data(qmt_data)
                if df is None or df.empty:
                    if progress_callback and total_stocks > 0:
                        progress_callback('daily_data_stock', batch_end, total_stocks,
                                          f'股票行情: {batch_end}/{total_stocks}')
                    continue

                # 计算VWAP（transform_market_data 已计算，这里做补充处理）
                if 'vwap' not in df.columns or df['vwap'].isna().all():
                    df['vwap'] = df.apply(
                        lambda row: self._calculate_vwap(
                            row.get('amount'), row.get('volume'), row.get('pre_close')
                        ), axis=1
                    )
                else:
                    # 对VWAP为空的行（停牌行）用前收盘价填充
                    mask = df['vwap'].isna() | (df['vwap'] == 0)
                    if mask.any():
                        df.loc[mask, 'vwap'] = df.loc[mask, 'pre_close']

                # 填充停牌数据
                filled_frames = []
                for code in df['stock_code'].unique():
                    code_df = df.loc[df['stock_code'] == code].copy()
                    code_df = self._fill_suspended_data(code_df, code)
                    filled_frames.append(code_df)
                if filled_frames:
                    df = pd.concat(filled_frames, ignore_index=True)

                # 统计停牌数
                if 'suspend_flag' in df.columns:
                    suspended_count += int(df['suspend_flag'].sum())

                # 写入数据库
                self.db.insert_stock_daily(df)
                stock_records += len(df)

            except Exception as e:
                logger.warning(f"获取股票行情批次失败 [{batch_start}:{batch_end}]: {e}", exc_info=True)

            # 进度回调（股票部分占70%）
            if progress_callback and total_stocks > 0:
                progress_callback('daily_data_stock', batch_end, total_stocks,
                                  f'股票行情: {batch_end}/{total_stocks}')

        return stock_records, suspended_count

    def _sync_index_daily(self, index_codes, start_date, end_date, progress_callback,
                          total_stocks=0) -> int:
        """
        批量同步指数日K线数据

        使用 get_market_data_ex 获取，转换格式后写入 index_daily 表。

        Returns
        -------
        int
            指数记录数
        """
        index_records = 0
        batch_size = 50
        total_indices = len(index_codes)

        for batch_start in range(0, total_indices, batch_size):
            batch_codes = index_codes[batch_start:batch_start + batch_size]
            batch_end = min(batch_start + batch_size, total_indices)

            try:
                qmt_data = self.qmt.get_market_data_ex(
                    batch_codes, period='1d',
                    start_time=start_date, end_time=end_date,
                    dividend_type='front'
                )

                if not qmt_data:
                    if progress_callback and total_indices > 0:
                        progress_callback('daily_data_index', batch_end, total_indices,
                                          f'指数行情: {batch_end}/{total_indices}')
                    continue

                df = QMTDataAdapter.transform_market_data(qmt_data)
                if df is None or df.empty:
                    if progress_callback and total_indices > 0:
                        progress_callback('daily_data_index', batch_end, total_indices,
                                          f'指数行情: {batch_end}/{total_indices}')
                    continue

                # 将 stock_code 列重命名为 index_code
                df = df.rename(columns={'stock_code': 'index_code'})

                # 写入数据库
                self.db.insert_index_daily(df)
                index_records += len(df)

            except Exception as e:
                logger.debug(f"获取指数行情批次失败 [{batch_start}:{batch_end}]: {e}")

            # 进度回调（指数部分占30%）
            if progress_callback and total_indices > 0:
                progress_callback('daily_data_index', batch_end, total_indices,
                                  f'指数行情: {batch_end}/{total_indices}')

        return index_records

    def _calculate_vwap(self, amount, volume, pre_close) -> float:
        """
        计算VWAP：amount/volume，停牌时用pre_close

        Parameters
        ----------
        amount : float
            成交额
        volume : float
            成交量
        pre_close : float
            前收盘价

        Returns
        -------
        float
            VWAP值
        """
        if volume is None or volume == 0 or pd.isna(volume):
            # 停牌或无成交，使用前收盘价
            if pre_close is not None and not pd.isna(pre_close):
                return float(pre_close)
            return 0.0

        if amount is None or pd.isna(amount):
            if pre_close is not None and not pd.isna(pre_close):
                return float(pre_close)
            return 0.0

        vwap = float(amount) / float(volume)
        # VWAP合理性检查：如果计算结果异常（如<=0），使用前收盘价
        if vwap <= 0 and pre_close is not None and not pd.isna(pre_close):
            return float(pre_close)

        return vwap

    def _fill_suspended_data(self, df, stock_code) -> pd.DataFrame:
        """
        填充停牌数据：OHLC用前收盘价，volume=0，suspend_flag=1

        优先使用QMT返回的suspendFlag字段判断停牌（0=正常, 1=停牌, -1=复牌），
        如果suspendFlag不可用则回退到volume=0判断。

        Parameters
        ----------
        df : pd.DataFrame
            原始行情数据
        stock_code : str
            股票代码

        Returns
        -------
        pd.DataFrame
            填充停牌后的数据
        """
        if df.empty:
            return df

        df = df.copy()

        # 确保有 pre_close 列
        if 'pre_close' not in df.columns:
            df['pre_close'] = df['close'].shift(1)

        # 优先使用QMT的suspendFlag字段判断停牌
        if 'suspend_flag' in df.columns and df['suspend_flag'].notna().any():
            # QMT suspendFlag: 0=正常, 1=停牌, -1=复牌
            suspended_mask = df['suspend_flag'].fillna(0).astype(int) == 1
        else:
            # 回退：通过volume=0判断停牌
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

        # 标记停牌（保持与原始列类型一致）
        if 'suspend_flag' in df.columns:
            original_dtype = df['suspend_flag'].dtype
        else:
            original_dtype = 'int64'
        df['suspend_flag'] = suspended_mask.astype(original_dtype if isinstance(original_dtype, str) else 'int64')

        # 对于停牌且pre_close也为空的情况，尝试用前一天的close填充
        null_pre_close = df['pre_close'].isna() & suspended_mask
        if null_pre_close.any():
            df['pre_close'] = df['pre_close'].ffill()
            still_null = df['pre_close'].isna() & suspended_mask
            if still_null.any():
                # 如果第一行就是停牌且没有前收盘价，用后一天的close
                df.loc[still_null, 'pre_close'] = df['close'].bfill()
                df.loc[still_null, 'open'] = df.loc[still_null, 'pre_close']
                df.loc[still_null, 'high'] = df.loc[still_null, 'pre_close']
                df.loc[still_null, 'low'] = df.loc[still_null, 'pre_close']
                df.loc[still_null, 'close'] = df.loc[still_null, 'pre_close']

        return df

    def _log_sync(self, sync_type, start_time, end_time, record_count, status,
                  error_message='', details=''):
        """
        记录同步日志到 data_sync_log 表

        通过 self.db.insert_data_sync_log() 写入。

        Parameters
        ----------
        sync_type : str
            同步类型，如 'full_sync', 'stock_list', 'daily_data' 等
        start_time : datetime
            同步开始时间
        end_time : datetime
            同步结束时间
        record_count : int
            同步记录数
        status : str
            状态，'success', 'failed', 'partial', 'running'
        error_message : str
            错误信息
        details : str
            详细信息
        """
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

    def _report_progress(self, callback, stage, current, total, message):
        """报告进度"""
        if callback:
            try:
                callback(stage, current, total, message)
            except Exception as e:
                logger.debug(f"进度回调异常: {e}")

    def get_all_index_codes(self) -> set:
        """
        从数据库动态获取所有指数/板块代码

        Returns
        -------
        set
            指数代码集合
        """
        try:
            conn = sqlite3.connect(self.db.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT index_code FROM index_constituent')
            codes = {row[0] for row in cursor.fetchall()}
            conn.close()
            return codes
        except Exception as e:
            logger.warning(f"从数据库获取指数代码失败: {e}")
            return set()

    # 缓存动态指数代码，避免频繁查库
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
        2. 数据库 index_constituent 表中的指数/板块
        3. 399开头（深交所指数）
        """
        if not isinstance(code, str):
            return False

        # 1. 硬编码已知指数列表
        if code in self.KNOWN_INDEX_CODES:
            return True

        # 2. 数据库中的指数/板块
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

        优先级: 数据库 product_type > 指数判断 > 代码规则

        Parameters
        ----------
        stock_code : str
            标的代码，如 '000001.SZ'

        Returns
        -------
        str
            标的类型: 'stock', 'index', 'etf', 'fund', 'bond', 'future', 'option', 'unknown'
        """
        if not isinstance(stock_code, str) or not stock_code:
            return 'unknown'

        # 1. 检查是否为指数（包括板块）
        if self._is_index_code(stock_code):
            return 'index'

        # 2. 从 qmt_instrument 表查询 product_type
        try:
            df = self.db.get_qmt_instruments()
            if not df.empty and 'stock_code' in df.columns and stock_code in df['stock_code'].values:
                row = df[df['stock_code'] == stock_code].iloc[0]
                product_type = row.get('product_type')
                type_map = {
                    1: 'stock', 2: 'index', 3: 'fund', 4: 'etf',
                    5: 'bond', 6: 'future', 7: 'option',
                }
                result = type_map.get(product_type, 'unknown')
                if result != 'unknown':
                    return result
        except Exception as e:
            logger.debug(f"从数据库获取标的类型失败 [{stock_code}]: {e}")

        # 3. 回退到代码规则判断
        code_part = stock_code.split('.')[0] if '.' in stock_code else stock_code
        exchange = stock_code.split('.')[1] if '.' in stock_code else ''

        # 期货（上海期货交易所后缀 SF）
        if exchange == 'SF':
            return 'future'

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

    @staticmethod
    def _format_qmt_date(value) -> Optional[str]:
        """
        格式化QMT返回的日期值

        QMT的日期可能是毫秒时间戳、字符串或其他格式。

        Parameters
        ----------
        value
            日期值

        Returns
        -------
        str or None
            格式化后的日期字符串 'YYYY-MM-DD'，或 None
        """
        if value is None:
            return None

        if isinstance(value, (int, float)):
            try:
                return pd.to_datetime(value, unit='ms').strftime('%Y-%m-%d')
            except (ValueError, OSError):
                return str(value)

        if isinstance(value, str):
            try:
                return pd.to_datetime(value).strftime('%Y-%m-%d')
            except (ValueError, TypeError):
                return value

        return None
