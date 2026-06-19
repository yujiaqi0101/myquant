"""
数据质量检查器
==============

检查数据库中数据的完整性和一致性，发现缺失数据。
支持多表检查：stock_daily / index_daily / etf_daily / t_finance_prime 等。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class DataInspector:
    """
    数据质量检查器

    检查数据库中数据的缺失情况，输出缺失报告。
    """

    # 需要检查的表配置：{数据类型: (表名, 代码列, 日期列)}
    TABLE_CONFIG = {
        'stock_daily': ('t_stock_daily', 'stock_code', 'trade_date'),
        'index_daily': ('t_index_daily', 'index_code', 'trade_date'),
        'etf_daily': ('t_etf_daily', 'etf_code', 'trade_date'),
        't_finance_prime': ('t_finance_prime', 'stock_code', 'rpt_date'),
    }

    def __init__(self, db_manager):
        """
        Parameters
        ----------
        db_manager : DatabaseManager
            数据库管理器实例
        """
        self.db = db_manager

    def inspect(self, start_date: str = None, end_date: str = None,
                data_types: List[str] = None) -> Dict[str, Dict]:
        """
        检查数据缺失情况

        Parameters
        ----------
        start_date : str
            开始日期 'YYYY-MM-DD'
        end_date : str
            结束日期 'YYYY-MM-DD'
        data_types : list of str
            要检查的数据类型列表，默认检查全部

        Returns
        -------
        dict
            缺失报告，格式：
            {
                'stock_daily': {
                    'total_codes': 5000,
                    'missing_codes': ['000001.SZ', ...],
                    'missing_details': {'000001.SZ': {'expected': 244, 'actual': 200, 'missing_dates': 44}},
                    'summary': '5000只股票中50只存在缺失'
                },
                ...
            }
        """
        if data_types is None:
            data_types = list(self.TABLE_CONFIG.keys())

        report = {}
        for data_type in data_types:
            if data_type not in self.TABLE_CONFIG:
                logger.warning(f"未知的数据类型: {data_type}")
                continue
            report[data_type] = self._inspect_table(data_type, start_date, end_date)

        return report

    def _inspect_table(self, data_type: str, start_date: str, end_date: str) -> Dict:
        """检查单个表的数据缺失情况"""
        table_name, code_col, date_col = self.TABLE_CONFIG[data_type]

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 获取该表中所有代码
            cursor.execute(f"SELECT DISTINCT {code_col} FROM {table_name}")
            codes = [row[0] for row in cursor.fetchall()]

            if not codes:
                return {
                    'total_codes': 0,
                    'missing_codes': [],
                    'missing_details': {},
                    'summary': f'{table_name} 表为空'
                }

            # 获取交易日历
            trading_dates = self._get_trading_dates(start_date, end_date, cursor)
            if not trading_dates:
                return {
                    'total_codes': len(codes),
                    'missing_codes': [],
                    'missing_details': {},
                    'summary': f'{table_name}: 无法获取交易日历'
                }

            expected_count = len(trading_dates)
            missing_details = {}
            missing_codes = []

            # 检查每个代码的数据完整性
            for code in codes:
                cursor.execute(
                    f"SELECT COUNT(DISTINCT {date_col}) FROM {table_name} WHERE {code_col} = ?",
                    (code,)
                )
                actual_count = cursor.fetchone()[0]

                if actual_count < expected_count * 0.9:  # 允许10%的容差（停牌等）
                    missing_count = expected_count - actual_count
                    missing_details[code] = {
                        'expected': expected_count,
                        'actual': actual_count,
                        'missing_dates': missing_count,
                    }
                    missing_codes.append(code)

            summary = f'{len(codes)}个代码中{len(missing_codes)}个存在缺失'
            if missing_codes:
                summary += f'（缺失>10%: {missing_codes[:10]}{"..." if len(missing_codes) > 10 else ""}）'

            return {
                'total_codes': len(codes),
                'missing_codes': missing_codes,
                'missing_details': missing_details,
                'summary': summary,
            }

    def _get_trading_dates(self, start_date: str, end_date: str, cursor) -> List[str]:
        """从 t_trading_date 表获取交易日列表"""
        try:
            sql = "SELECT trade_date FROM t_trading_date"
            params = []
            if start_date:
                sql += " WHERE trade_date >= ?"
                params.append(start_date)
            if end_date:
                if params:
                    sql += " AND trade_date <= ?"
                else:
                    sql += " WHERE trade_date <= ?"
                params.append(end_date)
            sql += " ORDER BY trade_date"
            cursor.execute(sql, params)
            return [row[0] for row in cursor.fetchall()]
        except Exception:
            # t_trading_date 表可能不存在，回退到从 t_stock_daily 推断
            try:
                sql = "SELECT DISTINCT trade_date FROM t_stock_daily"
                params = []
                if start_date:
                    sql += " WHERE trade_date >= ?"
                    params.append(start_date)
                if end_date:
                    if params:
                        sql += " AND trade_date <= ?"
                    else:
                        sql += " WHERE trade_date <= ?"
                    params.append(end_date)
                sql += " ORDER BY trade_date"
                cursor.execute(sql, params)
                return [row[0] for row in cursor.fetchall()]
            except Exception:
                return []

    def inspect_quick(self) -> Dict[str, Dict]:
        """
        快速检查：只统计各表的记录数和代码数

        Returns
        -------
        dict
            各表的统计信息
        """
        report = {}
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            for data_type, (table_name, code_col, date_col) in self.TABLE_CONFIG.items():
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    total_records = cursor.fetchone()[0]
                    cursor.execute(f"SELECT COUNT(DISTINCT {code_col}) FROM {table_name}")
                    total_codes = cursor.fetchone()[0]
                    cursor.execute(f"SELECT MIN({date_col}), MAX({date_col}) FROM {table_name}")
                    row = cursor.fetchone()
                    date_range = f"{row[0]} ~ {row[1]}" if row[0] else "N/A"
                    report[data_type] = {
                        'table': table_name,
                        'total_records': total_records,
                        'total_codes': total_codes,
                        'date_range': date_range,
                    }
                except Exception as e:
                    report[data_type] = {
                        'table': table_name,
                        'error': str(e),
                    }
        return report

    def print_report(self, report: Dict):
        """打印缺失报告"""
        print("\n" + "=" * 60)
        print("数据质量检查报告")
        print("=" * 60)
        for data_type, details in report.items():
            print(f"\n[{data_type}]")
            if 'summary' in details:
                print(f"  {details['summary']}")
                print(f"  总代码数: {details.get('total_codes', 0)}")
                print(f"  缺失代码数: {len(details.get('missing_codes', []))}")
            elif 'error' in details:
                print(f"  错误: {details['error']}")
            else:
                print(f"  记录数: {details.get('total_records', 0)}")
                print(f"  代码数: {details.get('total_codes', 0)}")
                print(f"  日期范围: {details.get('date_range', 'N/A')}")
        print("\n" + "=" * 60)
