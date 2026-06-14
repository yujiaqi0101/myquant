"""
除权除息日同步模块
==================

飞书"## 数据库"章节要求：
> 系统 - 除权除息日 → 东财掘金 (stk_get_dividend)

DataCleaner 在发现新除权事件时，会从该日重新拉取股票日K线
（防止分红/配股后历史数据失真）。
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

import pandas as pd

logger = logging.getLogger(__name__)


class DividendSynchronizer:
    """
    除权除息日同步器

    Usage:
        db = DatabaseManager(db_path)
        eastmoney = EastmoneyConnector(token=...)
        sync = DividendSynchronizer(db, eastmoney)
        sync.sync_all(start_date='2024-01-01')
    """

    def __init__(self, db_manager, eastmoney_connector=None):
        self.db = db_manager
        self.eastmoney = eastmoney_connector

    def sync_all(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbols: Optional[List[str]] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        同步所有股票的除权除息日

        Parameters
        ----------
        start_date : str
            起始日期 'YYYY-MM-DD'，默认 1 年前
        end_date : str
            结束日期 'YYYY-MM-DD'，默认今天
        symbols : list[str]
            股票代码列表（标准格式），默认从数据库读 stock_info
        progress_callback : callable
            进度回调 callback(stock_code, current, total, message)

        Returns
        -------
        dict
            同步结果摘要
        """
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

        if symbols is None:
            symbols = self._get_default_symbols()
        if not symbols:
            return {'status': 'no_symbols', 'count': 0}

        if self.eastmoney is None:
            logger.warning("未配置 eastmoney connector，跳过除权除息同步")
            return {'status': 'skipped', 'count': 0}

        logger.info(f"开始同步除权除息: {start_date} -> {end_date}, {len(symbols)} 只股票")
        total = len(symbols)
        new_events = 0
        error_count = 0
        dividend_df_list = []

        for i, code in enumerate(symbols):
            try:
                # 转换标准格式 → 掘金格式
                gm_symbol = self._to_gm_symbol(code)
                df = self.eastmoney.get_dividend(
                    symbol=gm_symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
                if df is not None and not df.empty:
                    df['stock_code'] = code  # 使用标准格式
                    dividend_df_list.append(df)
                    new_events += len(df)
            except Exception as e:
                logger.debug(f"获取 {code} 除权除息失败: {e}")
                error_count += 1

            if progress_callback and total > 0:
                progress_callback(code, i + 1, total, f'除权除息: {i+1}/{total}')

        # 合并所有除权除息数据并写入数据库
        if dividend_df_list:
            all_df = pd.concat(dividend_df_list, ignore_index=True)
            inserted = self._insert_dividend(all_df)
            logger.info(f"写入 {inserted} 条除权除息记录")
        else:
            inserted = 0

        result = {
            'status': 'success',
            'symbols_processed': total,
            'new_events': new_events,
            'inserted': inserted,
            'errors': error_count,
            'start_date': start_date,
            'end_date': end_date,
        }
        logger.info(f"除权除息同步完成: {result}")
        return result

    def detect_new_events(self, since_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        检测新增除权事件（用于触发重拉取）

        Parameters
        ----------
        since_date : str
            起始日期 'YYYY-MM-DD'，默认 None（仅返回所有事件）

        Returns
        -------
        list[dict]
            新增事件列表，每项包含 stock_code, ex_date 等
        """
        try:
            with self.db.get_connection() as conn:
                if since_date:
                    rows = conn.execute(
                        'SELECT * FROM dividend_date WHERE ex_date >= ? ORDER BY ex_date DESC',
                        (since_date,)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        'SELECT * FROM dividend_date ORDER BY ex_date DESC'
                    ).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"查询除权除息事件失败: {e}")
            return []

    # ============ 私有方法 ============

    def _get_default_symbols(self) -> List[str]:
        """从数据库获取股票列表"""
        try:
            info = self.db.get_stock_info()
            if info.empty:
                return []
            return info['stock_code'].tolist()
        except Exception as e:
            logger.warning(f"获取股票列表失败: {e}")
            return []

    def _to_gm_symbol(self, code: str) -> str:
        """标准格式 → 掘金格式"""
        # 标准格式: SHSE.600000 / SZSE.000001
        if '.' in code:
            return code
        # 6 位代码
        if code.startswith(('6', '9', '5')):
            return f'SHSE.{code}'
        if code.startswith(('0', '3', '2')):
            return f'SZSE.{code}'
        return f'SHSE.{code}'

    def _insert_dividend(self, df: pd.DataFrame) -> int:
        """写入 dividend_date 表"""
        if df.empty:
            return 0

        df = df.copy()
        # 标准化日期
        for col in ['ex_date', 'record_date', 'pay_date']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')

        # 准备列
        if 'dividend_per_share' not in df.columns:
            df['dividend_per_share'] = 0
        if 'split_ratio' not in df.columns:
            df['split_ratio'] = 1.0
        df['source'] = 'eastmoney'

        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                count = 0
                for _, row in df.iterrows():
                    try:
                        cursor.execute(
                            '''
                            INSERT OR REPLACE INTO dividend_date
                            (stock_code, ex_date, record_date, pay_date,
                             dividend_per_share, split_ratio, source)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            ''',
                            (
                                row.get('stock_code'),
                                row.get('ex_date'),
                                row.get('record_date'),
                                row.get('pay_date'),
                                row.get('dividend_per_share', 0),
                                row.get('split_ratio', 1.0),
                                row.get('source', 'eastmoney'),
                            )
                        )
                        count += 1
                    except Exception as e:
                        logger.debug(f"插入除权除息记录失败: {e}")
            return count
        except Exception as e:
            logger.error(f"批量写入除权除息失败: {e}")
            return 0


__all__ = ['DividendSynchronizer']
