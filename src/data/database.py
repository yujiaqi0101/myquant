"""
SQLite数据库管理模块
===================

提供数据库连接、表管理、数据存取功能。
"""

import sqlite3
import json
import logging
from contextlib import contextmanager
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from pathlib import Path
from enum import Enum

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    SQLite数据库管理器

    提供数据库连接、表创建、数据CRUD操作功能。
    """
    
    # 类级别缓存：记录已初始化的数据库路径
    _initialized_paths: set = set()

    def __init__(self, db_path: str):
        """
        初始化数据库管理器

        Parameters
        ----------
        db_path : str
            数据库文件路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 同一路径只初始化一次表结构
        abs_path = str(self.db_path.resolve())
        if abs_path not in DatabaseManager._initialized_paths:
            self._init_database()
            DatabaseManager._initialized_paths.add(abs_path)

    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_database(self):
        """初始化数据库：创建表和索引"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 股票日频数据表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date DATE NOT NULL,
                    stock_code VARCHAR(20) NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    vwap REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, stock_code)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_stock_daily_code ON stock_daily(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_stock_daily_date ON stock_daily(trade_date)')

            # 指数日频数据表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS index_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date DATE NOT NULL,
                    index_code VARCHAR(20) NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, index_code)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_index_daily_code ON index_daily(index_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_index_daily_date ON index_daily(trade_date)')

            # 股票信息表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) UNIQUE NOT NULL,
                    stock_name VARCHAR(100),
                    industry VARCHAR(100),
                    market_cap REAL,
                    list_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_stock_info_industry ON stock_info(industry)')

            # 执行日志表（增强版）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS execution_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    -- 执行基本信息
                    execution_type VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'success',

                    -- 执行条件
                    start_date DATE,
                    end_date DATE,
                    n_stocks INTEGER,
                    n_days INTEGER,

                    -- 因子/策略信息
                    factor_name VARCHAR(100),
                    factor_category VARCHAR(50),

                    -- 回测参数
                    n_positions INTEGER,
                    rebalance_freq INTEGER,
                    initial_capital REAL,

                    -- 绩效指标
                    ic_mean REAL,
                    ic_std REAL,
                    ir REAL,
                    sharpe REAL,
                    max_drawdown REAL,
                    total_return REAL,
                    annual_return REAL,
                    annual_volatility REAL,
                    win_rate REAL,

                    -- 详细信息
                    details TEXT
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_execution_type ON execution_log(execution_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_execution_factor ON execution_log(factor_name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_execution_timestamp ON execution_log(timestamp)')

            # 最佳记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS best_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category VARCHAR(50) NOT NULL,
                    metric_name VARCHAR(100) NOT NULL,
                    best_value REAL,
                    record_date DATE,
                    execution_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (execution_id) REFERENCES execution_log(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_best_category ON best_records(category)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_best_metric ON best_records(category, metric_name)')

            # 指数成分股/板块成分股表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS index_constituent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    index_code VARCHAR(20) NOT NULL,
                    stock_code VARCHAR(20) NOT NULL,
                    weight REAL NOT NULL,
                    market_cap REAL,
                    pe_ratio REAL,
                    pb_ratio REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(index_code, stock_code)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_constituent_index ON index_constituent(index_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_constituent_stock ON index_constituent(stock_code)')

            # 组合分析结果表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS portfolio_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_date DATE NOT NULL,
                    portfolio_id VARCHAR(50) NOT NULL,
                    benchmark_code VARCHAR(20),
                    portfolio_return REAL,
                    benchmark_return REAL,
                    excess_return REAL,
                    tracking_error REAL,
                    information_ratio REAL,
                    beta REAL,
                    alpha REAL,
                    max_drawdown REAL,
                    max_relative_drawdown REAL,
                    attribution_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(analysis_date, portfolio_id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_analysis_portfolio ON portfolio_analysis(portfolio_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_analysis_date ON portfolio_analysis(analysis_date)')

            # 因子暴露表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS factor_exposure (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date DATE NOT NULL,
                    portfolio_id VARCHAR(50) NOT NULL,
                    factor_name VARCHAR(50) NOT NULL,
                    portfolio_exposure REAL,
                    benchmark_exposure REAL,
                    active_exposure REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, portfolio_id, factor_name)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_exposure_portfolio ON factor_exposure(portfolio_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_exposure_factor ON factor_exposure(factor_name)')

            # ============ 扩展现有表字段（ALTER TABLE） ============
            alter_statements = [
                # stock_daily 新增字段
                'ALTER TABLE stock_daily ADD COLUMN pre_close REAL',
                'ALTER TABLE stock_daily ADD COLUMN suspend_flag INTEGER DEFAULT 0',
                # index_daily 新增字段
                'ALTER TABLE index_daily ADD COLUMN pre_close REAL',
                'ALTER TABLE index_daily ADD COLUMN amount REAL',
                # stock_info 新增字段
                'ALTER TABLE stock_info ADD COLUMN exchange VARCHAR(20)',
                'ALTER TABLE stock_info ADD COLUMN product_type INTEGER',
                'ALTER TABLE stock_info ADD COLUMN float_volume REAL',
                'ALTER TABLE stock_info ADD COLUMN total_volume REAL',
                'ALTER TABLE stock_info ADD COLUMN instrument_status INTEGER DEFAULT 0',
            ]
            for stmt in alter_statements:
                try:
                    cursor.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # 字段已存在，忽略

            # ============ 新增表 ============

            # QMT合约完整信息表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS qmt_instrument (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) UNIQUE NOT NULL,
                    instrument_name VARCHAR(100),
                    exchange_id VARCHAR(20),
                    product_type INTEGER,
                    open_date VARCHAR(20),
                    pre_close REAL,
                    up_stop_price REAL,
                    down_stop_price REAL,
                    float_volume REAL,
                    total_volume REAL,
                    price_tick REAL,
                    instrument_status INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_qmt_instrument_code ON qmt_instrument(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_qmt_instrument_type ON qmt_instrument(product_type)')

            # 数据同步日志表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS data_sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_type VARCHAR(50) NOT NULL,
                    start_time VARCHAR(20),
                    end_time VARCHAR(20),
                    record_count INTEGER DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'pending',
                    error_message TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_log_type ON data_sync_log(sync_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_log_status ON data_sync_log(status)')

            # ============ 估值分析模块表 ============

            # 财务数据表 - 存储资产负债表、利润表、现金流量表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS financial_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) NOT NULL,
                    report_date VARCHAR(20) NOT NULL,
                    table_name VARCHAR(20) NOT NULL,
                    data_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, report_date, table_name)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_code ON financial_data(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_date ON financial_data(report_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_table ON financial_data(table_name)')

            # 估值结果表 - 各估值方法的结果
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS valuation_result (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) NOT NULL,
                    report_date DATE NOT NULL,
                    method VARCHAR(20) NOT NULL,
                    current_value REAL,
                    fair_value_low REAL,
                    fair_value_mid REAL,
                    fair_value_high REAL,
                    implied_price_low REAL,
                    implied_price_mid REAL,
                    implied_price_high REAL,
                    upside_potential REAL,
                    downside_risk REAL,
                    confidence REAL,
                    assumptions TEXT,
                    warnings TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, report_date, method)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_valuation_stock ON valuation_result(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_valuation_date ON valuation_result(report_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_valuation_method ON valuation_result(method)')

            # 估值综合结果表 - 综合估值结果
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS valuation_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) NOT NULL,
                    report_date DATE NOT NULL,
                    weighted_fair_value REAL,
                    fair_value_low REAL,
                    fair_value_high REAL,
                    current_price REAL,
                    deviation_pct REAL,
                    recommendation VARCHAR(20),
                    confidence REAL,
                    methods_used TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, report_date)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_valuation_summary_stock ON valuation_summary(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_valuation_summary_date ON valuation_summary(report_date)')

            # ============ 股票池表 ============
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_pool (
                    pool_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pool_name VARCHAR(100) NOT NULL UNIQUE,
                    pool_code VARCHAR(50),
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_pool_member (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pool_id INTEGER NOT NULL,
                    stock_code VARCHAR(20) NOT NULL,
                    added_date DATE,
                    removed_date DATE,
                    FOREIGN KEY (pool_id) REFERENCES stock_pool(pool_id) ON DELETE CASCADE,
                    UNIQUE(pool_id, stock_code, added_date)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pool_member_pool ON stock_pool_member(pool_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pool_member_stock ON stock_pool_member(stock_code)')

            # ============ 交易日历表 ============
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trade_calendar (
                    trade_date TEXT PRIMARY KEY
                )
            ''')
            # 首次创建时从 stock_daily 填充
            cursor.execute('SELECT COUNT(*) as cnt FROM trade_calendar')
            count = cursor.fetchone()['cnt']
            if count == 0:
                cursor.execute('''
                    INSERT OR IGNORE INTO trade_calendar (trade_date)
                    SELECT DISTINCT trade_date FROM stock_daily
                ''')
                logger.info(f"交易日历表已填充 {cursor.rowcount} 条记录")

            # ============ 因子注册表 ============
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS factor_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    factor_id VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    category VARCHAR(50),
                    source VARCHAR(50),
                    call_method VARCHAR(200),
                    keywords VARCHAR(500),
                    input_params TEXT,
                    output_params TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_factor_registry_id ON factor_registry(factor_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_factor_registry_category ON factor_registry(category)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_factor_registry_source ON factor_registry(source)')

            # ============ 策略版本表 ============
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id VARCHAR(32) NOT NULL,
                    strategy_name VARCHAR(100) NOT NULL,
                    version VARCHAR(20) NOT NULL DEFAULT 'v1',
                    file_path VARCHAR(500) NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(strategy_id, version)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_strategy_versions_name ON strategy_versions(strategy_name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_strategy_versions_active ON strategy_versions(is_active)')

            logger.info(f"数据库初始化完成: {self.db_path}")

    # ============ 股票日频数据操作 ============

    def insert_stock_daily(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """
        批量插入股票日频数据

        Returns
        -------
        int
            插入的记录数
        """
        if df.empty:
            return 0

        df = df.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')

        # 确保必要列存在
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col not in df.columns:
                df[col] = 0.0
        for col in ['amount', 'vwap', 'pre_close']:
            if col not in df.columns:
                df[col] = None
        if 'suspend_flag' not in df.columns:
            df['suspend_flag'] = 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            count = 0

            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('trade_date'), row.get('stock_code'),
                        row.get('open'), row.get('high'), row.get('low'),
                        row.get('close'), row.get('volume'),
                        row.get('amount'), row.get('vwap'),
                        row.get('pre_close'), row.get('suspend_flag')
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO stock_daily
                    (trade_date, stock_code, open, high, low, close, volume, amount, vwap, pre_close, suspend_flag)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条股票日频数据")
        return count

    def get_stock_daily(
        self,
        stock_codes: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fields: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """查询股票日频数据（支持按需查询列，节省内存）"""
        # 动态构建列名，避免 SELECT *
        if fields:
            select_cols = ['trade_date', 'stock_code']
            for f in fields:
                if f not in select_cols:
                    select_cols.append(f)
            sql = f"SELECT {','.join(select_cols)} FROM stock_daily WHERE 1=1"
        else:
            sql = 'SELECT * FROM stock_daily WHERE 1=1'
        params = []

        if stock_codes:
            placeholders = ','.join(['?' for _ in stock_codes])
            sql += f' AND stock_code IN ({placeholders})'
            params.extend(stock_codes)

        if start_date:
            sql += ' AND trade_date >= ?'
            params.append(start_date)

        if end_date:
            sql += ' AND trade_date <= ?'
            params.append(end_date)

        sql += ' ORDER BY trade_date, stock_code'

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        if df.empty:
            return df

        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index(['trade_date', 'stock_code'], inplace=True)
        return df

    def get_stock_info_filtered(self) -> pd.DataFrame:
        """获取股票基本信息（用于选股过滤：ST判断 + 新股判断）"""
        with self.get_connection() as conn:
            df = pd.read_sql_query(
                'SELECT stock_code, stock_name, list_date FROM stock_info',
                conn
            )
        return df

    # ============ 指数日频数据操作 ============

    def insert_index_daily(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入指数日频数据"""
        if df.empty:
            return 0

        df = df.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')

        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col not in df.columns:
                df[col] = 0.0
        for col in ['pre_close', 'amount']:
            if col not in df.columns:
                df[col] = None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            count = 0

            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('trade_date'), row.get('index_code'),
                        row.get('open'), row.get('high'), row.get('low'),
                        row.get('close'), row.get('volume'),
                        row.get('pre_close'), row.get('amount')
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO index_daily
                    (trade_date, index_code, open, high, low, close, volume, pre_close, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条指数日频数据")
        return count

    def get_index_daily(
        self,
        index_codes: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """查询指数日频数据"""
        sql = 'SELECT * FROM index_daily WHERE 1=1'
        params = []

        if index_codes:
            placeholders = ','.join(['?' for _ in index_codes])
            sql += f' AND index_code IN ({placeholders})'
            params.extend(index_codes)

        if start_date:
            sql += ' AND trade_date >= ?'
            params.append(start_date)

        if end_date:
            sql += ' AND trade_date <= ?'
            params.append(end_date)

        sql += ' ORDER BY trade_date, index_code'

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        if not df.empty:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df.set_index(['trade_date', 'index_code'], inplace=True)

        return df

    # ============ 股票信息操作 ============

    def insert_stock_info(self, df: pd.DataFrame) -> int:
        """批量插入股票信息"""
        if df.empty:
            return 0

        df = df.copy()
        if 'list_date' in df.columns:
            # 处理无效日期（如空值、0000-00-00等）
            def safe_parse_date(x):
                if pd.isna(x) or x == '' or x == '0000-00-00' or str(x).startswith('0000'):
                    return None
                try:
                    return pd.to_datetime(x).strftime('%Y-%m-%d')
                except (ValueError, pd.errors.OutOfBoundsDatetime):
                    return None
            df['list_date'] = df['list_date'].apply(safe_parse_date)

        for col in ['stock_name', 'industry', 'market_cap', 'list_date']:
            if col not in df.columns:
                df[col] = None
        for col in ['exchange', 'product_type', 'float_volume', 'total_volume']:
            if col not in df.columns:
                df[col] = None
        if 'instrument_status' not in df.columns:
            df['instrument_status'] = 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = []
            for _, row in df.iterrows():
                rows.append((
                    row.get('stock_code'), row.get('stock_name'),
                    row.get('industry'), row.get('market_cap'), row.get('list_date'),
                    row.get('exchange'), row.get('product_type'),
                    row.get('float_volume'), row.get('total_volume'),
                    row.get('instrument_status')
                ))
            cursor.executemany('''
                INSERT OR REPLACE INTO stock_info
                (stock_code, stock_name, industry, market_cap, list_date,
                 exchange, product_type, float_volume, total_volume, instrument_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', rows)

        logger.info(f"插入 {len(rows)} 条股票信息")
        return len(rows)

    def get_stock_info(self) -> pd.DataFrame:
        """获取股票信息"""
        with self.get_connection() as conn:
            df = pd.read_sql_query('SELECT * FROM stock_info', conn)
        return df

    # ============ 执行日志操作 ============

    def log_execution(self, **kwargs) -> int:
        """
        记录执行日志

        Parameters
        ----------
        **kwargs : 执行日志字段，支持以下字段：
            - execution_type: 执行类型 ('backtest', 'factor_evaluation')
            - status: 状态 ('success', 'failed')
            - start_date, end_date: 数据日期范围
            - n_stocks, n_days: 股票数量、交易日数量
            - factor_name, factor_category: 因子信息
            - n_positions, rebalance_freq, initial_capital: 回测参数
            - ic_mean, ic_std, ir, sharpe, max_drawdown, total_return,
              annual_return, annual_volatility, win_rate: 绩效指标
            - details: JSON格式详细信息

        Returns
        -------
        int
            新记录的ID
        """
        allowed_fields = [
            'execution_type', 'status',
            'start_date', 'end_date', 'n_stocks', 'n_days',
            'factor_name', 'factor_category',
            'n_positions', 'rebalance_freq', 'initial_capital',
            'ic_mean', 'ic_std', 'ir', 'sharpe',
            'max_drawdown', 'total_return', 'annual_return',
            'annual_volatility', 'win_rate', 'details'
        ]

        # 过滤合法字段
        filtered = {k: v for k, v in kwargs.items() if k in allowed_fields}

        # details 如果是dict则转为JSON字符串
        if 'details' in filtered and isinstance(filtered['details'], dict):
            filtered['details'] = json.dumps(filtered['details'], ensure_ascii=False, default=str)

        columns = list(filtered.keys())
        values = list(filtered.values())
        placeholders = ','.join(['?' for _ in columns])
        col_names = ','.join(columns)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'INSERT INTO execution_log ({col_names}) VALUES ({placeholders})',
                values
            )
            log_id = cursor.lastrowid

        logger.info(f"记录执行日志: type={kwargs.get('execution_type')}, factor={kwargs.get('factor_name')}, id={log_id}")
        return log_id

    def get_execution_logs(
        self,
        execution_type: Optional[str] = None,
        factor_name: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """查询执行日志"""
        sql = 'SELECT * FROM execution_log WHERE 1=1'
        params = []

        if execution_type:
            sql += ' AND execution_type = ?'
            params.append(execution_type)

        if factor_name:
            sql += ' AND factor_name = ?'
            params.append(factor_name)

        if status:
            sql += ' AND status = ?'
            params.append(status)

        if start_date:
            sql += ' AND timestamp >= ?'
            params.append(start_date)

        if end_date:
            sql += ' AND timestamp <= ?'
            params.append(end_date)

        sql += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    # ============ 最佳记录操作 ============

    def update_best_record(
        self,
        category: str,
        metric_name: str,
        value: float,
        execution_id: Optional[int] = None
    ) -> bool:
        """
        更新最佳记录

        Parameters
        ----------
        category : str
            类别 ('factor', 'backtest')
        metric_name : str
            指标名称
        value : float
            指标值
        execution_id : int, optional
            关联的执行日志ID

        Returns
        -------
        bool
            是否更新了记录
        """
        # 最大回撤越小越好，其他指标越大越好
        is_lower_better = metric_name in ('max_drawdown',)

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, best_value FROM best_records
                WHERE category = ? AND metric_name = ?
            ''', (category, metric_name))
            row = cursor.fetchone()

            if row:
                current_best = row['best_value']
                should_update = (value < current_best) if is_lower_better else (value > current_best)

                if should_update:
                    cursor.execute('''
                        UPDATE best_records
                        SET best_value = ?, record_date = date('now'), execution_id = ?
                        WHERE category = ? AND metric_name = ?
                    ''', (value, execution_id, category, metric_name))
                    logger.info(f"更新最佳记录: {category}.{metric_name} = {value}")
                    return True
            else:
                cursor.execute('''
                    INSERT INTO best_records (category, metric_name, best_value, record_date, execution_id)
                    VALUES (?, ?, ?, date('now'), ?)
                ''', (category, metric_name, value, execution_id))
                logger.info(f"新增最佳记录: {category}.{metric_name} = {value}")
                return True

        return False

    def get_best_records(self, category: Optional[str] = None) -> pd.DataFrame:
        """查询最佳记录"""
        sql = 'SELECT * FROM best_records'
        params = []

        if category:
            sql += ' WHERE category = ?'
            params.append(category)

        sql += ' ORDER BY category, metric_name'

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    # ============ 工具方法 ============

    def get_trade_dates(self, start_date: str, end_date: str) -> List[str]:
        """获取交易日列表（从 trade_calendar 表查询）"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT trade_date FROM trade_calendar
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
            ''', (start_date, end_date))
            return [row['trade_date'] for row in cursor.fetchall()]

    def get_available_stocks(self, trade_date: str) -> List[str]:
        """获取某日的可交易股票列表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT stock_code FROM stock_daily
                WHERE trade_date = ?
            ''', (trade_date,))
            return [row['stock_code'] for row in cursor.fetchall()]

    def get_data_summary(self) -> Dict[str, Any]:
        """获取数据库数据概览"""
        summary = {}

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) as cnt, MIN(trade_date) as min_date, MAX(trade_date) as max_date FROM stock_daily')
            row = cursor.fetchone()
            summary['stock_daily'] = {
                'count': row['cnt'],
                'start_date': row['min_date'],
                'end_date': row['max_date']
            }

            cursor.execute('SELECT COUNT(*) as cnt, MIN(trade_date) as min_date, MAX(trade_date) as max_date FROM index_daily')
            row = cursor.fetchone()
            summary['index_daily'] = {
                'count': row['cnt'],
                'start_date': row['min_date'],
                'end_date': row['max_date']
            }

            cursor.execute('SELECT COUNT(*) as cnt FROM stock_info')
            summary['stock_info'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM execution_log')
            summary['execution_log'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM best_records')
            summary['best_records'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM index_constituent')
            summary['index_constituent'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM portfolio_analysis')
            summary['portfolio_analysis'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM factor_exposure')
            summary['factor_exposure'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM qmt_instrument')
            summary['qmt_instrument'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM data_sync_log')
            summary['data_sync_log'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM valuation_result')
            summary['valuation_result'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM valuation_summary')
            summary['valuation_summary'] = {'count': cursor.fetchone()['cnt']}

        return summary

    # ============ 指数成分股操作 ============

    def insert_index_constituent(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入指数成分股/板块成分股数据"""
        if df.empty:
            return 0

        df = df.copy()
        # 兼容：如果传入 trade_date 列则忽略
        if 'trade_date' in df.columns:
            df = df.drop(columns=['trade_date'])

        with self.get_connection() as conn:
            count = 0
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('index_code'), row.get('stock_code'),
                        row.get('weight'), row.get('market_cap'), row.get('pe_ratio'), row.get('pb_ratio')
                    ))
                conn.cursor().executemany('''
                    INSERT OR REPLACE INTO index_constituent
                    (index_code, stock_code, weight, market_cap, pe_ratio, pb_ratio)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条指数成分股数据")
        return count

    def get_index_constituent(
        self,
        index_code: str
    ) -> pd.DataFrame:
        """获取某指数/板块的成分股"""
        with self.get_connection() as conn:
            df = pd.read_sql_query('''
                SELECT * FROM index_constituent
                WHERE index_code = ?
                ORDER BY weight DESC
            ''', conn, params=[index_code])
        return df

    def get_index_constituent_history(
        self,
        index_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """获取指数成分股数据（兼容旧接口，忽略日期参数）"""
        sql = 'SELECT * FROM index_constituent WHERE index_code = ?'
        params = [index_code]

        # 兼容：忽略日期参数（表已无 trade_date 列）

        sql += ' ORDER BY weight DESC'

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    # ============ 组合分析结果操作 ============

    def insert_portfolio_analysis(self, data: Dict) -> int:
        """插入组合分析结果"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            attribution = data.get('attribution_data')
            if isinstance(attribution, dict):
                attribution = json.dumps(attribution, ensure_ascii=False, default=str)

            cursor.execute('''
                INSERT OR REPLACE INTO portfolio_analysis
                (analysis_date, portfolio_id, benchmark_code,
                 portfolio_return, benchmark_return, excess_return,
                 tracking_error, information_ratio, beta, alpha,
                 max_drawdown, max_relative_drawdown, attribution_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('analysis_date'), data.get('portfolio_id'), data.get('benchmark_code'),
                data.get('portfolio_return'), data.get('benchmark_return'), data.get('excess_return'),
                data.get('tracking_error'), data.get('information_ratio'),
                data.get('beta'), data.get('alpha'),
                data.get('max_drawdown'), data.get('max_relative_drawdown'), attribution
            ))
            return cursor.lastrowid

    def get_portfolio_analysis(
        self,
        portfolio_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """获取组合分析历史"""
        sql = 'SELECT * FROM portfolio_analysis WHERE portfolio_id = ?'
        params = [portfolio_id]

        if start_date:
            sql += ' AND analysis_date >= ?'
            params.append(start_date)
        if end_date:
            sql += ' AND analysis_date <= ?'
            params.append(end_date)

        sql += ' ORDER BY analysis_date'

        with self.get_connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    # ============ 因子暴露操作 ============

    def insert_factor_exposure(self, df: pd.DataFrame) -> int:
        """批量插入因子暴露数据"""
        if df.empty:
            return 0

        df = df.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')

        with self.get_connection() as conn:
            rows = []
            for _, row in df.iterrows():
                rows.append((
                    row.get('trade_date'), row.get('portfolio_id'), row.get('factor_name'),
                    row.get('portfolio_exposure'), row.get('benchmark_exposure'), row.get('active_exposure')
                ))
            conn.cursor().executemany('''
                INSERT OR REPLACE INTO factor_exposure
                (trade_date, portfolio_id, factor_name, portfolio_exposure, benchmark_exposure, active_exposure)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', rows)
            return len(rows)

    def get_factor_exposure(
        self,
        portfolio_id: str,
        factor_name: Optional[str] = None
    ) -> pd.DataFrame:
        """获取因子暴露历史"""
        sql = 'SELECT * FROM factor_exposure WHERE portfolio_id = ?'
        params = [portfolio_id]

        if factor_name:
            sql += ' AND factor_name = ?'
            params.append(factor_name)

        sql += ' ORDER BY trade_date, factor_name'

        with self.get_connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    # ============ QMT合约信息操作 ============

    def insert_qmt_instruments(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """
        批量插入QMT合约信息

        Parameters
        ----------
        df : pd.DataFrame
            合约信息DataFrame，需包含stock_code列

        Returns
        -------
        int
            插入的记录数
        """
        if df.empty:
            return 0

        df = df.copy()
        for col in ['instrument_name', 'exchange_id', 'product_type', 'open_date',
                     'pre_close', 'up_stop_price', 'down_stop_price',
                     'float_volume', 'total_volume', 'price_tick']:
            if col not in df.columns:
                df[col] = None
        if 'instrument_status' not in df.columns:
            df['instrument_status'] = 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            count = 0

            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('stock_code'), row.get('instrument_name'),
                        row.get('exchange_id'), row.get('product_type'),
                        row.get('open_date'), row.get('pre_close'),
                        row.get('up_stop_price'), row.get('down_stop_price'),
                        row.get('float_volume'), row.get('total_volume'),
                        row.get('price_tick'), row.get('instrument_status')
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO qmt_instrument
                    (stock_code, instrument_name, exchange_id, product_type,
                     open_date, pre_close, up_stop_price, down_stop_price,
                     float_volume, total_volume, price_tick, instrument_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条QMT合约信息")
        return count

    def get_qmt_instruments(self, product_type: Optional[int] = None) -> pd.DataFrame:
        """
        查询QMT合约信息

        Parameters
        ----------
        product_type : int, optional
            产品类型筛选(1股票,2指数,3基金,4ETF)

        Returns
        -------
        pd.DataFrame
            合约信息
        """
        sql = 'SELECT * FROM qmt_instrument WHERE 1=1'
        params = []

        if product_type is not None:
            sql += ' AND product_type = ?'
            params.append(product_type)

        sql += ' ORDER BY stock_code'

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    # ============ 数据同步日志操作 ============

    def insert_data_sync_log(
        self,
        sync_type: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        record_count: int = 0,
        status: str = 'pending',
        error_message: Optional[str] = None,
        details: Optional[str] = None
    ) -> int:
        """
        记录数据同步日志

        Parameters
        ----------
        sync_type : str
            同步类型
        start_time : str, optional
            同步开始时间
        end_time : str, optional
            同步结束时间
        record_count : int
            同步记录数
        status : str
            同步状态
        error_message : str, optional
            错误信息
        details : str, optional
            详细信息

        Returns
        -------
        int
            新记录的ID
        """
        if isinstance(details, dict):
            details = json.dumps(details, ensure_ascii=False, default=str)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO data_sync_log
                (sync_type, start_time, end_time, record_count, status, error_message, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (sync_type, start_time, end_time, record_count, status, error_message, details))
            log_id = cursor.lastrowid

        logger.info(f"记录数据同步日志: type={sync_type}, status={status}, id={log_id}")
        return log_id

    def get_data_sync_logs(
        self,
        sync_type: Optional[str] = None,
        limit: int = 50
    ) -> pd.DataFrame:
        """
        查询数据同步日志

        Parameters
        ----------
        sync_type : str, optional
            同步类型筛选
        limit : int
            返回记录数限制

        Returns
        -------
        pd.DataFrame
            同步日志
        """
        sql = 'SELECT * FROM data_sync_log WHERE 1=1'
        params = []

        if sync_type:
            sql += ' AND sync_type = ?'
            params.append(sync_type)

        sql += ' ORDER BY created_at DESC LIMIT ?'
        params.append(limit)

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    # ============ 估值分析模块操作 ============

    def insert_valuation_result(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """
        批量插入估值结果

        Parameters
        ----------
        df : pd.DataFrame
            估值结果数据
        batch_size : int
            批量插入大小

        Returns
        -------
        int
            插入记录数
        """
        if df.empty:
            return 0

        df = df.copy()
        if 'report_date' in df.columns:
            df['report_date'] = pd.to_datetime(df['report_date']).dt.strftime('%Y-%m-%d')

        # 处理assumptions和warnings字段（转为JSON字符串）
        for col in ['assumptions', 'warnings']:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False, default=str) if isinstance(x, dict) else x)

        with self.get_connection() as conn:
            count = 0
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('stock_code'), row.get('report_date'), row.get('method'),
                        row.get('current_value'), row.get('fair_value_low'), row.get('fair_value_mid'),
                        row.get('fair_value_high'), row.get('implied_price_low'), row.get('implied_price_mid'),
                        row.get('implied_price_high'), row.get('upside_potential'), row.get('downside_risk'),
                        row.get('confidence'), row.get('assumptions'), row.get('warnings')
                    ))
                conn.cursor().executemany('''
                    INSERT OR REPLACE INTO valuation_result
                    (stock_code, report_date, method, current_value, fair_value_low, fair_value_mid,
                     fair_value_high, implied_price_low, implied_price_mid, implied_price_high,
                     upside_potential, downside_risk, confidence, assumptions, warnings)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条估值结果数据")
        return count

    def insert_valuation_summary(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """
        批量插入估值综合结果

        Parameters
        ----------
        df : pd.DataFrame
            估值综合结果数据
        batch_size : int
            批量插入大小

        Returns
        -------
        int
            插入记录数
        """
        if df.empty:
            return 0

        df = df.copy()
        if 'report_date' in df.columns:
            df['report_date'] = pd.to_datetime(df['report_date']).dt.strftime('%Y-%m-%d')

        # 处理methods_used字段（转为JSON字符串）
        if 'methods_used' in df.columns:
            df['methods_used'] = df['methods_used'].apply(lambda x: json.dumps(x, ensure_ascii=False, default=str) if isinstance(x, dict) else x)

        with self.get_connection() as conn:
            count = 0
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('stock_code'), row.get('report_date'), row.get('weighted_fair_value'),
                        row.get('fair_value_low'), row.get('fair_value_high'), row.get('current_price'),
                        row.get('deviation_pct'), row.get('recommendation'), row.get('confidence'),
                        row.get('methods_used')
                    ))
                conn.cursor().executemany('''
                    INSERT OR REPLACE INTO valuation_summary
                    (stock_code, report_date, weighted_fair_value, fair_value_low, fair_value_high,
                     current_price, deviation_pct, recommendation, confidence, methods_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条估值综合结果数据")
        return count

    def get_valuation_result(
        self,
        stock_code: str,
        report_date: Optional[str] = None,
        method: Optional[str] = None
    ) -> pd.DataFrame:
        """
        查询估值结果

        Parameters
        ----------
        stock_code : str
            股票代码
        report_date : str, optional
            报告日期
        method : str, optional
            估值方法

        Returns
        -------
        pd.DataFrame
            估值结果
        """
        sql = 'SELECT * FROM valuation_result WHERE stock_code = ?'
        params = [stock_code]

        if report_date:
            sql += ' AND report_date = ?'
            params.append(report_date)

        if method:
            sql += ' AND method = ?'
            params.append(method)

        sql += ' ORDER BY report_date DESC, method'

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    def get_valuation_summary(
        self,
        stock_code: Optional[str] = None,
        report_date: Optional[str] = None,
        recommendation: Optional[str] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        查询估值综合结果

        Parameters
        ----------
        stock_code : str, optional
            股票代码
        report_date : str, optional
            报告日期
        recommendation : str, optional
            投资建议筛选
        limit : int
            返回记录数限制

        Returns
        -------
        pd.DataFrame
            估值综合结果
        """
        sql = 'SELECT * FROM valuation_summary WHERE 1=1'
        params = []

        if stock_code:
            sql += ' AND stock_code = ?'
            params.append(stock_code)

        if report_date:
            sql += ' AND report_date = ?'
            params.append(report_date)

        if recommendation:
            sql += ' AND recommendation = ?'
            params.append(recommendation)

        sql += ' ORDER BY report_date DESC, stock_code LIMIT ?'
        params.append(limit)

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    # ============ 因子注册表操作 ============

    def sync_factor_registry(self, factor_meta_dict: Dict[str, Dict]) -> int:
        """
        同步因子注册表

        将因子元数据同步到数据库的factor_registry表中。
        如果因子已存在则更新，不存在则插入。

        Parameters
        ----------
        factor_meta_dict : Dict[str, Dict]
            因子元数据字典，格式为 {factor_id: {name, category, description, source, call_method, keywords, input_params, output_params}}

        Returns
        -------
        int
            同步的因子数量
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            count = 0

            for factor_id, meta in factor_meta_dict.items():
                cursor.execute('''
                    INSERT OR REPLACE INTO factor_registry
                    (factor_id, name, description, category, source, call_method, keywords, input_params, output_params, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    factor_id,
                    meta.get('name', ''),
                    meta.get('description', ''),
                    meta.get('category', {}).value if isinstance(meta.get('category'), Enum) else meta.get('category', ''),
                    meta.get('source', ''),
                    meta.get('call_method', ''),
                    meta.get('keywords', ''),
                    meta.get('input_params', ''),
                    meta.get('output_params', '')
                ))
                count += 1

        logger.info(f"同步 {count} 个因子到注册表")
        return count

    def get_factor_registry(
        self,
        factor_id: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        keyword: Optional[str] = None
    ) -> pd.DataFrame:
        """
        查询因子注册表

        Parameters
        ----------
        factor_id : str, optional
            因子ID，精确匹配
        category : str, optional
            分类筛选
        source : str, optional
            来源筛选 (worldquant/guotai/fundamental)
        keyword : str, optional
            关键词搜索（在ID、名称、描述、关键词中搜索）

        Returns
        -------
        pd.DataFrame
            因子注册表数据
        """
        sql = 'SELECT * FROM factor_registry WHERE 1=1'
        params = []

        if factor_id:
            sql += ' AND factor_id = ?'
            params.append(factor_id)

        if category:
            sql += ' AND category = ?'
            params.append(category)

        if source:
            sql += ' AND source = ?'
            params.append(source)

        if keyword:
            sql += ' AND (factor_id LIKE ? OR name LIKE ? OR description LIKE ? OR keywords LIKE ?)'
            keyword_pattern = f'%{keyword}%'
            params.extend([keyword_pattern, keyword_pattern, keyword_pattern, keyword_pattern])

        sql += ' ORDER BY source, factor_id'

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    def get_factor_detail(self, factor_id: str) -> Optional[Dict]:
        """
        获取单个因子的详细信息

        Parameters
        ----------
        factor_id : str
            因子ID

        Returns
        -------
        dict or None
            因子详细信息，如果不存在则返回None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM factor_registry WHERE factor_id = ?', (factor_id,))
            row = cursor.fetchone()

            if row:
                return dict(row)
            return None

    def get_factor_registry_summary(self) -> Dict[str, Any]:
        """
        获取因子注册表统计摘要

        Returns
        -------
        dict
            统计信息，包含：
            - total: 总因子数
            - by_source: 按来源统计
            - by_category: 按分类统计
        """
        summary = {'total': 0, 'by_source': {}, 'by_category': {}}

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 总数
            cursor.execute('SELECT COUNT(*) as cnt FROM factor_registry')
            summary['total'] = cursor.fetchone()['cnt']

            # 按来源统计
            cursor.execute('SELECT source, COUNT(*) as cnt FROM factor_registry GROUP BY source')
            for row in cursor.fetchall():
                summary['by_source'][row['source']] = row['cnt']

            # 按分类统计
            cursor.execute('SELECT category, COUNT(*) as cnt FROM factor_registry GROUP BY category')
            for row in cursor.fetchall():
                summary['by_category'][row['category']] = row['cnt']

        return summary

    # ============ 财务数据操作 ============

    def insert_financial_data(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """
        批量插入财务数据

        Parameters
        ----------
        df : pd.DataFrame
            财务数据，需包含 stock_code, report_date, table_name, data_json 列
        batch_size : int
            批量插入大小

        Returns
        -------
        int
            插入记录数
        """
        if df.empty:
            return 0

        df = df.copy()
        for col in ['stock_code', 'report_date', 'table_name', 'data_json']:
            if col not in df.columns:
                df[col] = None

        with self.get_connection() as conn:
            count = 0
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    data_json = row.get('data_json')
                    if isinstance(data_json, dict):
                        data_json = json.dumps(data_json, ensure_ascii=False, default=str)
                    rows.append((
                        row.get('stock_code'), row.get('report_date'),
                        row.get('table_name'), data_json
                    ))
                conn.cursor().executemany('''
                    INSERT OR REPLACE INTO financial_data
                    (stock_code, report_date, table_name, data_json)
                    VALUES (?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条财务数据")
        return count

    def get_financial_data(
        self,
        stock_codes: Optional[List[str]] = None,
        table_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        查询财务数据

        Parameters
        ----------
        stock_codes : list, optional
            股票代码列表
        table_name : str, optional
            报表名称 (Balance/Income/CashFlow)
        start_date : str, optional
            开始日期
        end_date : str, optional
            结束日期

        Returns
        -------
        pd.DataFrame
            财务数据
        """
        sql = 'SELECT * FROM financial_data WHERE 1=1'
        params = []

        if stock_codes:
            placeholders = ','.join(['?' for _ in stock_codes])
            sql += f' AND stock_code IN ({placeholders})'
            params.extend(stock_codes)

        if table_name:
            sql += ' AND table_name = ?'
            params.append(table_name)

        if start_date:
            sql += ' AND report_date >= ?'
            params.append(start_date)

        if end_date:
            sql += ' AND report_date <= ?'
            params.append(end_date)

        sql += ' ORDER BY stock_code, report_date'

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    def clear_factor_registry(self):
        """清空因子注册表（谨慎使用）"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM factor_registry')
            logger.info("已清空因子注册表")

    def clear_all_data(self):
        """清空所有数据（仅用于测试）"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for table in ['stock_daily', 'index_daily', 'stock_info', 'execution_log', 'best_records',
                          'index_constituent', 'portfolio_analysis', 'factor_exposure',
                          'qmt_instrument', 'data_sync_log', 'valuation_result', 'valuation_summary',
                          'factor_registry', 'financial_data', 'stock_pool', 'stock_pool_member',
                          'trade_calendar']:
                cursor.execute(f'DELETE FROM {table}')
            logger.info("已清空所有数据")

    # ============ 股票池操作 ============

    def create_stock_pool(
        self,
        pool_name: str,
        pool_code: Optional[str] = None,
        description: Optional[str] = None
    ) -> int:
        """
        创建股票池

        Parameters
        ----------
        pool_name : str
            股票池名称（唯一）
        pool_code : str, optional
            股票池代码（如 CSI300）
        description : str, optional
            描述

        Returns
        -------
        int
            新记录的 pool_id，如果已存在则返回 -1
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO stock_pool (pool_name, pool_code, description)
                    VALUES (?, ?, ?)
                ''', (pool_name, pool_code, description))
                pool_id = cursor.lastrowid
                logger.info(f"创建股票池: {pool_name} (id={pool_id})")
                return pool_id
            except sqlite3.IntegrityError:
                logger.warning(f"股票池已存在: {pool_name}")
                return -1

    def delete_stock_pool(self, pool_name: str) -> bool:
        """
        删除股票池及其所有成员

        Parameters
        ----------
        pool_name : str
            股票池名称

        Returns
        -------
        bool
            是否删除成功
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT pool_id FROM stock_pool WHERE pool_name = ?', (pool_name,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"股票池不存在: {pool_name}")
                return False

            pool_id = row['pool_id']
            cursor.execute('DELETE FROM stock_pool_member WHERE pool_id = ?', (pool_id,))
            cursor.execute('DELETE FROM stock_pool WHERE pool_id = ?', (pool_id,))
            logger.info(f"删除股票池: {pool_name}")
            return True

    def list_stock_pools(self) -> List[Dict]:
        """
        列出所有股票池

        Returns
        -------
        list[dict]
            股票池列表，每项包含 pool_name, pool_code, description, member_count, created_at
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.pool_name, p.pool_code, p.description, p.created_at,
                       COUNT(m.id) as member_count
                FROM stock_pool p
                LEFT JOIN stock_pool_member m ON p.pool_id = m.pool_id AND m.removed_date IS NULL
                GROUP BY p.pool_id
                ORDER BY p.created_at DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]

    def get_stock_pool_info(self, pool_name: str) -> Optional[Dict]:
        """
        获取股票池信息

        Parameters
        ----------
        pool_name : str
            股票池名称

        Returns
        -------
        dict or None
            股票池信息
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM stock_pool WHERE pool_name = ?', (pool_name,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_to_stock_pool(
        self,
        pool_name: str,
        stock_codes: List[str],
        added_date: Optional[str] = None
    ) -> int:
        """
        添加股票到股票池

        Parameters
        ----------
        pool_name : str
            股票池名称
        stock_codes : list[str]
            股票代码列表
        added_date : str, optional
            加入日期（默认今天）

        Returns
        -------
        int
            添加的记录数
        """
        if added_date is None:
            added_date = datetime.now().strftime('%Y-%m-%d')

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT pool_id FROM stock_pool WHERE pool_name = ?', (pool_name,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"股票池不存在: {pool_name}")
                return 0

            pool_id = row['pool_id']
            count = 0
            for code in stock_codes:
                try:
                    cursor.execute('''
                        INSERT INTO stock_pool_member (pool_id, stock_code, added_date)
                        VALUES (?, ?, ?)
                    ''', (pool_id, code.strip(), added_date))
                    count += 1
                except sqlite3.IntegrityError:
                    # 已存在则跳过
                    pass

            logger.info(f"向股票池 {pool_name} 添加 {count} 只股票")
            return count

    def remove_from_stock_pool(
        self,
        pool_name: str,
        stock_codes: List[str],
        removed_date: Optional[str] = None
    ) -> int:
        """
        从股票池移除股票（标记 removed_date，不物理删除）

        Parameters
        ----------
        pool_name : str
            股票池名称
        stock_codes : list[str]
            股票代码列表
        removed_date : str, optional
            移除日期（默认今天）

        Returns
        -------
        int
            移除的记录数
        """
        if removed_date is None:
            removed_date = datetime.now().strftime('%Y-%m-%d')

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT pool_id FROM stock_pool WHERE pool_name = ?', (pool_name,))
            row = cursor.fetchone()
            if not row:
                return 0

            pool_id = row['pool_id']
            placeholders = ','.join(['?' for _ in stock_codes])
            cursor.execute(f'''
                UPDATE stock_pool_member
                SET removed_date = ?
                WHERE pool_id = ? AND stock_code IN ({placeholders}) AND removed_date IS NULL
            ''', [removed_date, pool_id] + [c.strip() for c in stock_codes])
            count = cursor.rowcount

            logger.info(f"从股票池 {pool_name} 移除 {count} 只股票")
            return count

    def get_stock_pool_members(
        self,
        pool_name: str,
        trade_date: Optional[str] = None
    ) -> List[str]:
        """
        获取股票池的有效成员列表

        Parameters
        ----------
        pool_name : str
            股票池名称
        trade_date : str, optional
            查询日期（默认返回当前有效成员）
            如果指定日期，返回该日期有效的成员（added_date <= trade_date 且 removed_date IS NULL 或 removed_date > trade_date）

        Returns
        -------
        list[str]
            股票代码列表
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT pool_id FROM stock_pool WHERE pool_name = ?', (pool_name,))
            row = cursor.fetchone()
            if not row:
                return []

            pool_id = row['pool_id']

            if trade_date:
                cursor.execute('''
                    SELECT DISTINCT stock_code FROM stock_pool_member
                    WHERE pool_id = ?
                      AND added_date <= ?
                      AND (removed_date IS NULL OR removed_date > ?)
                    ORDER BY stock_code
                ''', (pool_id, trade_date, trade_date))
            else:
                cursor.execute('''
                    SELECT DISTINCT stock_code FROM stock_pool_member
                    WHERE pool_id = ? AND removed_date IS NULL
                    ORDER BY stock_code
                ''', (pool_id,))

            return [row['stock_code'] for row in cursor.fetchall()]

    def import_index_as_pool(
        self,
        index_code: str,
        pool_name: str,
        description: Optional[str] = None
    ) -> int:
        """
        将指数成分股导入为股票池

        Parameters
        ----------
        index_code : str
            指数代码（如 000300.SH）
        pool_name : str
            股票池名称
        description : str, optional
            描述

        Returns
        -------
        int
            导入的股票数量，-1 表示失败
        """
        # 获取指数成分股
        constituents = self.get_index_constituent(index_code)
        if constituents.empty:
            logger.warning(f"指数 {index_code} 无成分股数据")
            return -1

        stock_codes = constituents['stock_code'].tolist()
        if description is None:
            description = f"从指数 {index_code} 导入，共 {len(stock_codes)} 只成分股"

        # 创建股票池
        pool_id = self.create_stock_pool(pool_name, pool_code=index_code, description=description)
        if pool_id == -1:
            # 股票池已存在，直接添加成员
            pool_id = self.get_stock_pool_info(pool_name)['pool_id']

        # 添加成员
        count = self.add_to_stock_pool(pool_name, stock_codes)
        return count

    def import_csv_as_pool(
        self,
        csv_path: str,
        pool_name: str,
        code_column: str = 'stock_code',
        description: Optional[str] = None
    ) -> int:
        """
        从CSV文件导入股票池

        Parameters
        ----------
        csv_path : str
            CSV文件路径
        pool_name : str
            股票池名称
        code_column : str
            股票代码所在列名
        description : str, optional
            描述

        Returns
        -------
        int
            导入的股票数量
        """
        df = pd.read_csv(csv_path)
        if code_column not in df.columns:
            logger.error(f"CSV文件中找不到列 '{code_column}'，可用列: {list(df.columns)}")
            return -1

        stock_codes = df[code_column].astype(str).str.strip().tolist()
        if description is None:
            description = f"从CSV导入 {csv_path}，共 {len(stock_codes)} 只股票"

        pool_id = self.create_stock_pool(pool_name, description=description)
        if pool_id == -1:
            # 已存在，直接添加
            pass

        return self.add_to_stock_pool(pool_name, stock_codes)

    # ============ 策略版本管理 ============

    def register_strategy_version(
        self,
        strategy_id: str,
        strategy_name: str,
        version: str,
        file_path: str,
        description: str = "",
        is_active: int = 1,
    ) -> int:
        """注册策略版本，返回记录ID"""
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''INSERT OR REPLACE INTO strategy_versions
                   (strategy_id, strategy_name, version, file_path, is_active, description, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                (strategy_id, strategy_name, version, file_path, is_active, description),
            )
            return cursor.lastrowid

    def set_active_version(self, strategy_name: str, version: str) -> bool:
        """设置策略的活跃版本（先全部标为0，再激活指定版本）"""
        with self.get_connection() as conn:
            conn.execute(
                'UPDATE strategy_versions SET is_active = 0 WHERE strategy_name = ?',
                (strategy_name,),
            )
            conn.execute(
                '''UPDATE strategy_versions SET is_active = 1, updated_at = CURRENT_TIMESTAMP
                   WHERE strategy_name = ? AND version = ?''',
                (strategy_name, version),
            )
            return True

    def get_active_strategies(self) -> pd.DataFrame:
        """获取所有活跃策略（is_active=1）"""
        with self.get_connection() as conn:
            return pd.read_sql_query(
                'SELECT * FROM strategy_versions WHERE is_active = 1 ORDER BY strategy_name',
                conn,
            )

    def get_strategy_version(
        self, strategy_name: str, version: str = None
    ) -> Optional[Dict]:
        """获取指定策略版本，version=None时返回活跃版本"""
        with self.get_connection() as conn:
            if version:
                row = conn.execute(
                    '''SELECT * FROM strategy_versions
                       WHERE strategy_name = ? AND version = ?''',
                    (strategy_name, version),
                ).fetchone()
            else:
                row = conn.execute(
                    '''SELECT * FROM strategy_versions
                       WHERE strategy_name = ? AND is_active = 1''',
                    (strategy_name,),
                ).fetchone()
            if row:
                return dict(row)
            return None

    def list_strategy_versions(self, strategy_name: str = None) -> List[Dict]:
        """列出策略所有版本"""
        with self.get_connection() as conn:
            if strategy_name:
                rows = conn.execute(
                    '''SELECT * FROM strategy_versions
                       WHERE strategy_name = ? ORDER BY version DESC''',
                    (strategy_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM strategy_versions ORDER BY strategy_name, version DESC',
                ).fetchall()
            return [dict(r) for r in rows]

    def create_new_strategy_version(
        self,
        strategy_name: str,
        new_version: str,
        new_file_path: str,
        description: str = "",
    ) -> int:
        """
        创建新版本策略
        基于同名策略的现有记录创建，保留相同的 strategy_id
        """
        existing = self.list_strategy_versions(strategy_name)
        if not existing:
            logger.error(f"策略 '{strategy_name}' 不存在，请先注册")
            return -1

        strategy_id = existing[0]['strategy_id']
        # 新版本默认激活，旧版本标为未激活
        self.set_active_version(strategy_name, new_version)
        return self.register_strategy_version(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            version=new_version,
            file_path=new_file_path,
            description=description,
            is_active=1,
        )
