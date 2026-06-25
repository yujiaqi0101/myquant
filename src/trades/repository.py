"""
交易记录数据库仓储
==================

提供交易记录的数据库 CRUD 操作。
"""

import logging
from typing import List, Optional

import pandas as pd

from .models import TradeRecord

logger = logging.getLogger(__name__)


class TradeRepository:
    """
    交易记录数据库仓储

    提供交易记录的批量插入、查询、统计功能。
    """

    def __init__(self, db_manager):
        """
        Parameters
        ----------
        db_manager : DatabaseManager
            数据库管理器实例
        """
        self.db = db_manager

    def insert_records(
        self,
        records: List[TradeRecord],
        source_file: str = '',
        skip_duplicates: bool = True,
    ) -> tuple[int, int]:
        """
        批量插入交易记录

        Parameters
        ----------
        records : List[TradeRecord]
            交易记录列表
        source_file : str
            源 CSV 文件名
        skip_duplicates : bool
            是否跳过重复记录（基于 UNIQUE 约束）

        Returns
        -------
        tuple[int, int]
            (成功插入数, 跳过/失败数)
        """
        if not records:
            return 0, 0

        inserted = 0
        skipped = 0

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            for record in records:
                try:
                    cursor.execute('''
                        INSERT INTO t_broker_trade (
                            trade_date, trade_time, stock_code, stock_name,
                            trade_type, price, quantity, amount,
                            commission, stamp_tax, transfer_fee, other_fee,
                            total_fee, net_amount, broker, account, source_file
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        record.trade_date,
                        record.trade_time,
                        record.stock_code,
                        record.stock_name,
                        record.trade_type,
                        record.price,
                        record.quantity,
                        record.amount,
                        record.commission,
                        record.stamp_tax,
                        record.transfer_fee,
                        record.other_fee,
                        record.total_fee,
                        record.net_amount,
                        record.broker,
                        record.account,
                        source_file,
                    ))
                    inserted += 1
                except Exception as e:
                    if skip_duplicates and 'UNIQUE' in str(e):
                        skipped += 1
                    else:
                        logger.warning(f"插入失败: {record.trade_date} {record.stock_code} - {e}")
                        skipped += 1

        logger.info(f"插入完成: {inserted} 条成功, {skipped} 条跳过")
        return inserted, skipped

    def get_records(
        self,
        broker: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        stock_code: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        查询交易记录

        Parameters
        ----------
        broker : str, optional
            按券商筛选
        start_date : str, optional
            起始日期 YYYY-MM-DD
        end_date : str, optional
            结束日期 YYYY-MM-DD
        stock_code : str, optional
            按股票代码筛选

        Returns
        -------
        pd.DataFrame
            交易记录 DataFrame
        """
        sql = 'SELECT * FROM t_broker_trade WHERE 1=1'
        params = []

        if broker:
            sql += ' AND broker = ?'
            params.append(broker)
        if start_date:
            sql += ' AND trade_date >= ?'
            params.append(start_date)
        if end_date:
            sql += ' AND trade_date <= ?'
            params.append(end_date)
        if stock_code:
            sql += ' AND stock_code = ?'
            params.append(stock_code)

        sql += ' ORDER BY trade_date, stock_code'

        with self.db.get_connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def get_summary(self) -> dict:
        """
        获取交易记录统计摘要

        Returns
        -------
        dict
            统计信息
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 总记录数
            cursor.execute('SELECT COUNT(*) as cnt FROM t_broker_trade')
            total = cursor.fetchone()['cnt']

            if total == 0:
                return {
                    'total_records': 0,
                    'buy_count': 0,
                    'sell_count': 0,
                    'total_buy_amount': 0,
                    'total_sell_amount': 0,
                    'total_fee': 0,
                    'date_range': '',
                    'brokers': [],
                    'stocks': [],
                }

            # 买入/卖出统计
            cursor.execute('''
                SELECT
                    trade_type,
                    COUNT(*) as cnt,
                    SUM(amount) as total_amount,
                    SUM(total_fee) as total_fee
                FROM t_broker_trade
                GROUP BY trade_type
            ''')
            type_stats = {row['trade_type']: dict(row) for row in cursor.fetchall()}

            buy_stats = type_stats.get('buy', {'cnt': 0, 'total_amount': 0, 'total_fee': 0})
            sell_stats = type_stats.get('sell', {'cnt': 0, 'total_amount': 0, 'total_fee': 0})

            # 日期范围
            cursor.execute('SELECT MIN(trade_date) as min_date, MAX(trade_date) as max_date FROM t_broker_trade')
            date_range = cursor.fetchone()

            # 券商列表
            cursor.execute('SELECT DISTINCT broker FROM t_broker_trade WHERE broker IS NOT NULL AND broker != ""')
            brokers = [row['broker'] for row in cursor.fetchall()]

            # 股票数量
            cursor.execute('SELECT COUNT(DISTINCT stock_code) as cnt FROM t_broker_trade')
            stock_count = cursor.fetchone()['cnt']

            # 总费用
            cursor.execute('SELECT SUM(total_fee) as total_fee FROM t_broker_trade')
            total_fee = cursor.fetchone()['total_fee'] or 0

            return {
                'total_records': total,
                'buy_count': buy_stats['cnt'],
                'sell_count': sell_stats['cnt'],
                'total_buy_amount': buy_stats['total_amount'] or 0,
                'total_sell_amount': sell_stats['total_amount'] or 0,
                'total_fee': total_fee,
                'date_range': f"{date_range['min_date']} ~ {date_range['max_date']}",
                'brokers': brokers,
                'stock_count': stock_count,
            }

    def delete_all(self, broker: Optional[str] = None) -> int:
        """
        删除交易记录

        Parameters
        ----------
        broker : str, optional
            指定券商删除，不指定则删除全部

        Returns
        -------
        int
            删除的记录数
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            if broker:
                cursor.execute('DELETE FROM t_broker_trade WHERE broker = ?', (broker,))
            else:
                cursor.execute('DELETE FROM t_broker_trade')
            return cursor.rowcount
