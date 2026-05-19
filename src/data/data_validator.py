"""
数据校验模块
============

检查数据完整性，识别缺失和停牌数据，生成校验报告。
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class DataValidator:
    """
    数据校验器

    检查数据库中数据的完整性，识别缺失交易日、停牌股票、数据异常等问题。

    Parameters
    ----------
    db_manager : DatabaseManager
        数据库管理器实例
    """

    def __init__(self, db_manager):
        self.db = db_manager

    def check_data_integrity(self, start_date, end_date) -> dict:
        """
        全面检查数据完整性，返回报告

        Parameters
        ----------
        start_date : str
            开始日期，格式 YYYY-MM-DD 或 YYYYMMDD
        end_date : str
            结束日期，格式 YYYY-MM-DD 或 YYYYMMDD

        Returns
        -------
        dict
            完整性报告，包含以下字段：
            - stock_data: 股票数据检查结果
            - index_data: 指数数据检查结果
            - stock_info: 股票信息检查结果
            - suspended: 停牌数据统计
            - missing_dates: 缺失交易日统计
            - anomalies: 数据异常统计
        """
        start_date = self._normalize_date(start_date)
        end_date = self._normalize_date(end_date)

        logger.info(f"开始数据完整性检查: {start_date} -> {end_date}")
        report = {
            'check_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'start_date': start_date,
            'end_date': end_date,
            'stock_data': {},
            'index_data': {},
            'stock_info': {},
            'suspended': {},
            'missing_dates': {},
            'anomalies': {},
        }

        # 1. 检查股票数据
        report['stock_data'] = self._check_stock_data(start_date, end_date)

        # 2. 检查指数数据
        report['index_data'] = self._check_index_data(start_date, end_date)

        # 3. 检查股票信息
        report['stock_info'] = self._check_stock_info()

        # 4. 检查停牌数据
        suspended_stocks = self.find_suspended_stocks(start_date, end_date)
        report['suspended'] = {
            'suspended_stock_count': len(suspended_stocks),
            'suspended_stocks_sample': suspended_stocks[:50],  # 最多展示50条
        }

        # 5. 检查缺失交易日
        missing_dates = self._check_missing_dates_overall(start_date, end_date)
        report['missing_dates'] = {
            'missing_date_count': len(missing_dates),
            'missing_dates': missing_dates[:30],  # 最多展示30条
        }

        # 6. 检查数据异常
        report['anomalies'] = self._check_data_anomalies(start_date, end_date)

        logger.info("数据完整性检查完成")
        return report

    def check_stock_data_continuity(self, stock_code, start_date, end_date) -> dict:
        """
        检查单只股票数据连续性

        Parameters
        ----------
        stock_code : str
            股票代码
        start_date : str
            开始日期，格式 YYYY-MM-DD 或 YYYYMMDD
        end_date : str
            结束日期，格式 YYYY-MM-DD 或 YYYYMMDD

        Returns
        -------
        dict
            连续性检查结果，包含以下字段：
            - stock_code: 股票代码
            - start_date: 开始日期
            - end_date: 结束日期
            - total_records: 总记录数
            - missing_dates: 缺失的交易日列表
            - missing_count: 缺失天数
            - suspended_dates: 停牌日期列表
            - suspended_count: 停牌天数
            - first_date: 数据首日
            - last_date: 数据末日
            - is_continuous: 是否连续（无缺失）
        """
        start_date = self._normalize_date(start_date)
        end_date = self._normalize_date(end_date)

        # 获取该股票在日期范围内的数据
        with self.db.get_connection() as conn:
            df = pd.read_sql_query('''
                SELECT trade_date, volume, close, open, high, low
                FROM stock_daily
                WHERE stock_code = ? AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
            ''', conn, params=[stock_code, start_date, end_date])

        if df.empty:
            return {
                'stock_code': stock_code,
                'start_date': start_date,
                'end_date': end_date,
                'total_records': 0,
                'missing_dates': [],
                'missing_count': 0,
                'suspended_dates': [],
                'suspended_count': 0,
                'first_date': None,
                'last_date': None,
                'is_continuous': False,
                'error': '无数据',
            }

        df['trade_date'] = pd.to_datetime(df['trade_date'])

        # 获取该日期范围内的所有交易日（以全市场交易日为基准）
        all_trade_dates = self._get_all_trade_dates(start_date, end_date)

        # 找出缺失的交易日
        existing_dates = set(df['trade_date'].dt.strftime('%Y-%m-%d').tolist())
        missing_dates = [d for d in all_trade_dates if d not in existing_dates]

        # 找出停牌日期（volume为0或None）
        volume_series = df['volume'].fillna(0)
        suspended_mask = volume_series == 0
        suspended_df = df[suspended_mask]
        suspended_dates = suspended_df['trade_date'].dt.strftime('%Y-%m-%d').tolist()

        first_date = df['trade_date'].min().strftime('%Y-%m-%d')
        last_date = df['trade_date'].max().strftime('%Y-%m-%d')

        return {
            'stock_code': stock_code,
            'start_date': start_date,
            'end_date': end_date,
            'total_records': len(df),
            'missing_dates': missing_dates,
            'missing_count': len(missing_dates),
            'suspended_dates': suspended_dates,
            'suspended_count': len(suspended_dates),
            'first_date': first_date,
            'last_date': last_date,
            'is_continuous': len(missing_dates) == 0,
        }

    def find_suspended_stocks(self, start_date, end_date) -> list:
        """
        找出指定日期范围内的停牌股票

        Parameters
        ----------
        start_date : str
            开始日期，格式 YYYY-MM-DD 或 YYYYMMDD
        end_date : str
            结束日期，格式 YYYY-MM-DD 或 YYYYMMDD

        Returns
        -------
        list
            停牌股票信息列表，每项包含 stock_code, suspended_dates, suspended_count
        """
        start_date = self._normalize_date(start_date)
        end_date = self._normalize_date(end_date)

        with self.db.get_connection() as conn:
            # 找出在日期范围内有停牌记录的股票
            df = pd.read_sql_query('''
                SELECT stock_code, trade_date, volume
                FROM stock_daily
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY stock_code, trade_date
            ''', conn, params=[start_date, end_date])

        if df.empty:
            return []

        # 标记停牌：volume为0或NULL
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
        suspended = df[df['volume'] == 0]

        if suspended.empty:
            return []

        # 按股票分组
        result = []
        for stock_code, group in suspended.groupby('stock_code'):
            dates = group['trade_date'].tolist()
            result.append({
                'stock_code': stock_code,
                'suspended_dates': dates,
                'suspended_count': len(dates),
            })

        # 按停牌天数降序排列
        result.sort(key=lambda x: x['suspended_count'], reverse=True)
        return result

    def find_missing_dates(self, stock_code, start_date, end_date) -> list:
        """
        找出缺失的交易日

        Parameters
        ----------
        stock_code : str
            股票代码
        start_date : str
            开始日期，格式 YYYY-MM-DD 或 YYYYMMDD
        end_date : str
            结束日期，格式 YYYY-MM-DD 或 YYYYMMDD

        Returns
        -------
        list
            缺失的交易日列表，格式 ['YYYY-MM-DD', ...]
        """
        start_date = self._normalize_date(start_date)
        end_date = self._normalize_date(end_date)

        # 获取该股票已有的交易日
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT trade_date FROM stock_daily
                WHERE stock_code = ? AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
            ''', (stock_code, start_date, end_date))
            existing_dates = set(row['trade_date'] for row in cursor.fetchall())

        # 获取全市场交易日
        all_trade_dates = self._get_all_trade_dates(start_date, end_date)

        # 找出缺失的
        missing = [d for d in all_trade_dates if d not in existing_dates]
        return missing

    def get_data_summary(self) -> dict:
        """
        获取数据概览统计

        Returns
        -------
        dict
            数据概览，包含各表的记录数、日期范围等信息
        """
        summary = self.db.get_data_summary()

        # 补充更详细的统计信息
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 股票数量（按交易所）
            cursor.execute('''
                SELECT
                    CASE
                        WHEN stock_code LIKE '%.SH' THEN '上交所'
                        WHEN stock_code LIKE '%.SZ' THEN '深交所'
                        ELSE '其他'
                    END as exchange,
                    COUNT(DISTINCT stock_code) as count
                FROM stock_info
                GROUP BY exchange
            ''')
            summary['stocks_by_exchange'] = {
                row['exchange']: row['count'] for row in cursor.fetchall()
            }

            # 行业分布
            cursor.execute('''
                SELECT industry, COUNT(*) as count
                FROM stock_info
                WHERE industry IS NOT NULL AND industry != ''
                GROUP BY industry
                ORDER BY count DESC
                LIMIT 20
            ''')
            summary['industry_distribution'] = {
                row['industry']: row['count'] for row in cursor.fetchall()
            }

            # 最近同步日志
            cursor.execute('''
                SELECT sync_type, start_time, end_time, record_count, status
                FROM data_sync_log
                ORDER BY id DESC
                LIMIT 10
            ''')
            sync_logs = []
            for row in cursor.fetchall():
                sync_logs.append({
                    'sync_type': row['sync_type'],
                    'start_time': row['start_time'],
                    'end_time': row['end_time'],
                    'record_count': row['record_count'],
                    'status': row['status'],
                })
            summary['recent_sync_logs'] = sync_logs

            # 每日数据量趋势（最近30天）
            cursor.execute('''
                SELECT trade_date, COUNT(DISTINCT stock_code) as stock_count,
                       COUNT(*) as record_count
                FROM stock_daily
                WHERE trade_date >= date('now', '-30 days')
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT 30
            ''')
            daily_trend = []
            for row in cursor.fetchall():
                daily_trend.append({
                    'trade_date': row['trade_date'],
                    'stock_count': row['stock_count'],
                    'record_count': row['record_count'],
                })
            summary['daily_trend_30d'] = daily_trend

        return summary

    def validate_and_report(self, start_date, end_date) -> str:
        """
        生成可读的数据校验报告

        Parameters
        ----------
        start_date : str
            开始日期，格式 YYYY-MM-DD 或 YYYYMMDD
        end_date : str
            结束日期，格式 YYYY-MM-DD 或 YYYYMMDD

        Returns
        -------
        str
            可读的校验报告文本
        """
        start_date = self._normalize_date(start_date)
        end_date = self._normalize_date(end_date)

        report = self.check_data_integrity(start_date, end_date)
        lines = []

        lines.append("=" * 60)
        lines.append("数据完整性校验报告")
        lines.append("=" * 60)
        lines.append(f"检查时间: {report['check_time']}")
        lines.append(f"检查范围: {report['start_date']} -> {report['end_date']}")
        lines.append("")

        # 股票数据
        sd = report['stock_data']
        lines.append("-" * 40)
        lines.append("[1] 股票日频数据")
        lines.append(f"    总记录数: {sd.get('total_records', 0):,}")
        lines.append(f"    股票数量: {sd.get('stock_count', 0):,}")
        lines.append(f"    交易日数: {sd.get('trade_date_count', 0):,}")
        lines.append(f"    日期范围: {sd.get('first_date', 'N/A')} -> {sd.get('last_date', 'N/A')}")
        lines.append(f"    每日平均股票数: {sd.get('avg_stocks_per_day', 0):.0f}")

        # 指数数据
        idx = report['index_data']
        lines.append("")
        lines.append("-" * 40)
        lines.append("[2] 指数日频数据")
        lines.append(f"    总记录数: {idx.get('total_records', 0):,}")
        lines.append(f"    指数数量: {idx.get('index_count', 0):,}")
        lines.append(f"    日期范围: {idx.get('first_date', 'N/A')} -> {idx.get('last_date', 'N/A')}")

        # 股票信息
        si = report['stock_info']
        lines.append("")
        lines.append("-" * 40)
        lines.append("[3] 股票基本信息")
        lines.append(f"    股票总数: {si.get('total_stocks', 0):,}")
        lines.append(f"    有行业信息: {si.get('with_industry', 0):,}")
        lines.append(f"    缺少行业信息: {si.get('without_industry', 0):,}")

        # 停牌数据
        sp = report['suspended']
        lines.append("")
        lines.append("-" * 40)
        lines.append("[4] 停牌数据")
        lines.append(f"    停牌股票数: {sp.get('suspended_stock_count', 0):,}")
        if sp.get('suspended_stocks_sample'):
            lines.append("    停牌股票示例:")
            for item in sp['suspended_stocks_sample'][:10]:
                lines.append(f"      {item['stock_code']}: 停牌 {item['suspended_count']} 天")

        # 缺失交易日
        md = report['missing_dates']
        lines.append("")
        lines.append("-" * 40)
        lines.append("[5] 缺失交易日")
        lines.append(f"    缺失天数: {md.get('missing_date_count', 0)}")
        if md.get('missing_dates'):
            lines.append(f"    缺失日期: {', '.join(md['missing_dates'][:10])}")
            if len(md['missing_dates']) > 10:
                lines.append(f"    ... 共 {len(md['missing_dates'])} 天")

        # 数据异常
        an = report['anomalies']
        lines.append("")
        lines.append("-" * 40)
        lines.append("[6] 数据异常")
        lines.append(f"    价格为负的记录: {an.get('negative_price_count', 0):,}")
        lines.append(f"    成交量异常记录: {an.get('abnormal_volume_count', 0):,}")
        lines.append(f"    OHLC异常记录: {an.get('ohlc_anomaly_count', 0):,}")

        # 总结
        lines.append("")
        lines.append("=" * 60)
        issues = []
        if md.get('missing_date_count', 0) > 0:
            issues.append(f"存在 {md['missing_date_count']} 天缺失交易日")
        if an.get('negative_price_count', 0) > 0:
            issues.append(f"存在 {an['negative_price_count']} 条负价格记录")
        if an.get('ohlc_anomaly_count', 0) > 0:
            issues.append(f"存在 {an['ohlc_anomaly_count']} 条OHLC异常记录")

        if issues:
            lines.append("发现问题:")
            for issue in issues:
                lines.append(f"  - {issue}")
        else:
            lines.append("数据完整性良好，未发现明显问题。")
        lines.append("=" * 60)

        return "\n".join(lines)

    # ============ 内部方法 ============

    def _normalize_date(self, date_str) -> str:
        """标准化日期格式为 YYYY-MM-DD"""
        if not date_str:
            return ''
        date_str = str(date_str).strip()
        # 去除可能的时间部分
        if ' ' in date_str:
            date_str = date_str.split(' ')[0]
        # YYYYMMDD -> YYYY-MM-DD
        if len(date_str) == 8 and date_str.isdigit():
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        return date_str

    def _get_all_trade_dates(self, start_date, end_date) -> list:
        """
        获取全市场交易日列表

        以stock_daily表中所有不重复的trade_date为基准，
        如果数据库为空则返回空列表。

        Parameters
        ----------
        start_date : str
            开始日期 YYYY-MM-DD
        end_date : str
            结束日期 YYYY-MM-DD

        Returns
        -------
        list
            交易日列表 ['YYYY-MM-DD', ...]
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT trade_date FROM stock_daily
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
            ''', (start_date, end_date))
            return [row['trade_date'] for row in cursor.fetchall()]

    def _check_stock_data(self, start_date, end_date) -> dict:
        """检查股票日频数据"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT
                    COUNT(*) as total_records,
                    COUNT(DISTINCT stock_code) as stock_count,
                    COUNT(DISTINCT trade_date) as trade_date_count,
                    MIN(trade_date) as first_date,
                    MAX(trade_date) as last_date
                FROM stock_daily
                WHERE trade_date BETWEEN ? AND ?
            ''', (start_date, end_date))
            row = cursor.fetchone()

            total_records = row['total_records'] or 0
            stock_count = row['stock_count'] or 0
            trade_date_count = row['trade_date_count'] or 0
            avg_stocks = total_records / trade_date_count if trade_date_count > 0 else 0

            # 检查数据稀疏度：找出交易日数少于50%的股票
            cursor.execute('''
                SELECT stock_code, COUNT(DISTINCT trade_date) as days
                FROM stock_daily
                WHERE trade_date BETWEEN ? AND ?
                GROUP BY stock_code
                HAVING days < ?
                ORDER BY days ASC
                LIMIT 20
            ''', (start_date, end_date, max(trade_date_count * 0.5, 1)))
            sparse_stocks = [row['stock_code'] for row in cursor.fetchall()]

        return {
            'total_records': total_records,
            'stock_count': stock_count,
            'trade_date_count': trade_date_count,
            'first_date': row['first_date'],
            'last_date': row['last_date'],
            'avg_stocks_per_day': avg_stocks,
            'sparse_stocks': sparse_stocks,
            'sparse_stock_count': len(sparse_stocks),
        }

    def _check_index_data(self, start_date, end_date) -> dict:
        """检查指数日频数据"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT
                    COUNT(*) as total_records,
                    COUNT(DISTINCT index_code) as index_count,
                    COUNT(DISTINCT trade_date) as trade_date_count,
                    MIN(trade_date) as first_date,
                    MAX(trade_date) as last_date
                FROM index_daily
                WHERE trade_date BETWEEN ? AND ?
            ''', (start_date, end_date))
            row = cursor.fetchone()

        return {
            'total_records': row['total_records'] or 0,
            'index_count': row['index_count'] or 0,
            'trade_date_count': row['trade_date_count'] or 0,
            'first_date': row['first_date'],
            'last_date': row['last_date'],
        }

    def _check_stock_info(self) -> dict:
        """检查股票基本信息"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) as cnt FROM stock_info')
            total = cursor.fetchone()['cnt']

            cursor.execute('''
                SELECT COUNT(*) as cnt FROM stock_info
                WHERE industry IS NOT NULL AND industry != ''
            ''')
            with_industry = cursor.fetchone()['cnt']

        return {
            'total_stocks': total,
            'with_industry': with_industry,
            'without_industry': total - with_industry,
        }

    def _check_missing_dates_overall(self, start_date, end_date) -> list:
        """
        检查整体缺失交易日

        以数据中最多的股票覆盖的交易日为基准，
        找出某些交易日股票数量明显偏少的情况。

        Returns
        -------
        list
            可疑缺失的交易日列表
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 获取每日股票数量
            cursor.execute('''
                SELECT trade_date, COUNT(DISTINCT stock_code) as stock_count
                FROM stock_daily
                WHERE trade_date BETWEEN ? AND ?
                GROUP BY trade_date
                ORDER BY trade_date
            ''', (start_date, end_date))
            rows = cursor.fetchall()

        if not rows:
            return []

        # 计算中位数股票数
        counts = [row['stock_count'] for row in rows]
        if not counts:
            return []

        median_count = float(np.median(counts))

        # 找出股票数量明显偏少的日期（低于中位数的50%）
        threshold = median_count * 0.5
        sparse_dates = [
            row['trade_date'] for row in rows
            if row['stock_count'] < threshold
        ]

        return sparse_dates

    def _check_data_anomalies(self, start_date, end_date) -> dict:
        """检查数据异常"""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 负价格记录
            cursor.execute('''
                SELECT COUNT(*) as cnt FROM stock_daily
                WHERE trade_date BETWEEN ? AND ?
                AND (open < 0 OR high < 0 OR low < 0 OR close < 0)
            ''', (start_date, end_date))
            negative_price_count = cursor.fetchone()['cnt']

            # 成交量异常（负数）
            cursor.execute('''
                SELECT COUNT(*) as cnt FROM stock_daily
                WHERE trade_date BETWEEN ? AND ?
                AND volume < 0
            ''', (start_date, end_date))
            abnormal_volume_count = cursor.fetchone()['cnt']

            # OHLC异常：low > high 或 open/high/low/close 为0但volume > 0
            cursor.execute('''
                SELECT COUNT(*) as cnt FROM stock_daily
                WHERE trade_date BETWEEN ? AND ?
                AND (low > high
                     OR (close = 0 AND volume > 0)
                     OR (open = 0 AND volume > 0))
            ''', (start_date, end_date))
            ohlc_anomaly_count = cursor.fetchone()['cnt']

        return {
            'negative_price_count': negative_price_count,
            'abnormal_volume_count': abnormal_volume_count,
            'ohlc_anomaly_count': ohlc_anomaly_count,
        }
