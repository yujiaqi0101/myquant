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
        
        # 每次实例化都检查表结构（CREATE IF NOT EXISTS / ALTER TABLE ADD COLUMN 都是幂等的）
        # 防止数据库文件外部被修改后程序内无法同步 schema
        self._init_database()

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

            # 股票日频数据表 - 对齐东财 history 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_stock_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date DATE NOT NULL,
                    stock_code VARCHAR(20) NOT NULL,
                    bob TIMESTAMP,
                    eob TIMESTAMP,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    position REAL,
                    frequency VARCHAR(20),
                    pre_close REAL,
                    vwap REAL,
                    suspend_flag INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, stock_code)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_stock_daily_code ON t_stock_daily(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_stock_daily_date ON t_stock_daily(trade_date)')

            # 指数日频数据表 - 对齐东财 history 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_index_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date DATE NOT NULL,
                    index_code VARCHAR(20) NOT NULL,
                    bob TIMESTAMP,
                    eob TIMESTAMP,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    position REAL,
                    frequency VARCHAR(20),
                    pre_close REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, index_code)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_index_daily_code ON t_index_daily(index_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_index_daily_date ON t_index_daily(trade_date)')

            # 股票信息表 - 对齐东财 get_symbol_infos(sec_type1=1010) 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_stock_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) UNIQUE NOT NULL,
                    stock_name VARCHAR(100),
                    sec_id VARCHAR(20),
                    sec_type1 INTEGER,
                    sec_type2 INTEGER,
                    board INTEGER,
                    exchange VARCHAR(20),
                    sec_abbr VARCHAR(50),
                    price_tick REAL,
                    trade_n INTEGER,
                    listed_date DATE,
                    delisted_date DATE,
                    delisting_begin_date DATE,
                    industry VARCHAR(100),
                    market_cap REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_stock_info_industry ON t_stock_info(industry)')

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
                CREATE TABLE IF NOT EXISTS t_stock_in_index (
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
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_constituent_index ON t_stock_in_index(index_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_constituent_stock ON t_stock_in_index(stock_code)')

            # 申万行业分类明细表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_stock_in_sw (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) NOT NULL,
                    industry_code VARCHAR(20),
                    industry_l1 VARCHAR(50),
                    industry_l2 VARCHAR(50),
                    industry_l3 VARCHAR(50),
                    exchange VARCHAR(10),
                    stock_name VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sw_stock ON t_stock_in_sw(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sw_l1 ON t_stock_in_sw(industry_l1)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sw_l2 ON t_stock_in_sw(industry_l2)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sw_l3 ON t_stock_in_sw(industry_l3)')

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
                # t_stock_daily 新增字段
                'ALTER TABLE t_stock_daily ADD COLUMN pre_close REAL',
                'ALTER TABLE t_stock_daily ADD COLUMN suspend_flag INTEGER DEFAULT 0',
                # t_index_daily 新增字段
                'ALTER TABLE t_index_daily ADD COLUMN pre_close REAL',
                'ALTER TABLE t_index_daily ADD COLUMN amount REAL',
                # t_stock_info 新增字段（对齐东财 get_symbol_infos）
                'ALTER TABLE t_stock_info ADD COLUMN exchange VARCHAR(20)',
                'ALTER TABLE t_stock_info ADD COLUMN product_type INTEGER',
                'ALTER TABLE t_stock_info ADD COLUMN float_volume REAL',
                'ALTER TABLE t_stock_info ADD COLUMN total_volume REAL',
                'ALTER TABLE t_stock_info ADD COLUMN instrument_status INTEGER DEFAULT 0',
                'ALTER TABLE t_stock_info ADD COLUMN sec_id VARCHAR(20)',
                'ALTER TABLE t_stock_info ADD COLUMN sec_type1 INTEGER',
                'ALTER TABLE t_stock_info ADD COLUMN sec_type2 INTEGER',
                'ALTER TABLE t_stock_info ADD COLUMN board INTEGER',
                'ALTER TABLE t_stock_info ADD COLUMN sec_abbr VARCHAR(50)',
                'ALTER TABLE t_stock_info ADD COLUMN price_tick REAL',
                'ALTER TABLE t_stock_info ADD COLUMN trade_n INTEGER',
                'ALTER TABLE t_stock_info ADD COLUMN listed_date DATE',
                'ALTER TABLE t_stock_info ADD COLUMN delisted_date DATE',
                'ALTER TABLE t_stock_info ADD COLUMN delisting_begin_date DATE',
                # t_etf_info 新增字段（对齐东财 get_symbol_infos）
                'ALTER TABLE t_etf_info ADD COLUMN sec_id VARCHAR(20)',
                'ALTER TABLE t_etf_info ADD COLUMN sec_type1 INTEGER',
                'ALTER TABLE t_etf_info ADD COLUMN sec_type2 INTEGER',
                'ALTER TABLE t_etf_info ADD COLUMN board INTEGER',
                'ALTER TABLE t_etf_info ADD COLUMN exchange VARCHAR(20)',
                'ALTER TABLE t_etf_info ADD COLUMN sec_abbr VARCHAR(50)',
                'ALTER TABLE t_etf_info ADD COLUMN price_tick REAL',
                'ALTER TABLE t_etf_info ADD COLUMN trade_n INTEGER',
                'ALTER TABLE t_etf_info ADD COLUMN listed_date DATE',
                'ALTER TABLE t_etf_info ADD COLUMN delisted_date DATE',
                'ALTER TABLE t_etf_info ADD COLUMN fund_type TEXT',
                'ALTER TABLE t_etf_info ADD COLUMN benchmark_index VARCHAR(20)',
                'ALTER TABLE t_etf_info ADD COLUMN management_fee REAL',
                'ALTER TABLE t_etf_info ADD COLUMN custodian_fee REAL',
                'ALTER TABLE t_etf_info ADD COLUMN management_company TEXT',
                # t_index_info 新增字段（对齐东财 get_symbol_infos）
                'ALTER TABLE t_index_info ADD COLUMN sec_id VARCHAR(20)',
                'ALTER TABLE t_index_info ADD COLUMN sec_type1 INTEGER',
                'ALTER TABLE t_index_info ADD COLUMN sec_type2 INTEGER',
                'ALTER TABLE t_index_info ADD COLUMN board INTEGER',
                'ALTER TABLE t_index_info ADD COLUMN exchange VARCHAR(20)',
                'ALTER TABLE t_index_info ADD COLUMN sec_abbr VARCHAR(50)',
                'ALTER TABLE t_index_info ADD COLUMN price_tick REAL',
                'ALTER TABLE t_index_info ADD COLUMN trade_n INTEGER',
                'ALTER TABLE t_index_info ADD COLUMN listed_date DATE',
                'ALTER TABLE t_index_info ADD COLUMN delisted_date DATE',
                'ALTER TABLE t_index_info ADD COLUMN base_date DATE',
                'ALTER TABLE t_index_info ADD COLUMN base_point REAL',
                'ALTER TABLE t_index_info ADD COLUMN publish_date DATE',
                # t_sector_info 新增字段（对齐东财 get_symbol_infos）
                'ALTER TABLE t_sector_info ADD COLUMN sec_id VARCHAR(20)',
                'ALTER TABLE t_sector_info ADD COLUMN sec_type1 INTEGER',
                'ALTER TABLE t_sector_info ADD COLUMN sec_type2 INTEGER',
                'ALTER TABLE t_sector_info ADD COLUMN exchange VARCHAR(20)',
                'ALTER TABLE t_sector_info ADD COLUMN sec_abbr VARCHAR(50)',
                # t_finance_prime 新增字段（对齐东财 stk_get_finance_prime_pt 财务主要指标）
                'ALTER TABLE t_finance_prime ADD COLUMN pub_date DATE',
                'ALTER TABLE t_finance_prime ADD COLUMN rpt_date DATE',
                'ALTER TABLE t_finance_prime ADD COLUMN eps_basic REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN eps_dil REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN eps_basic_cut REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN eps_dil_cut REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN net_cf_oper_ps REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN bps_pcom_ps REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN ttl_ast REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN ttl_liab REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN share_cptl REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN ttl_inc_oper REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN inc_oper REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN oper_prof REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN ttl_prof REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN ttl_eqy_pcom REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN net_prof_pcom REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN net_prof_pcom_cut REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN roe REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN roe_weight_avg REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN roe_cut REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN roe_weight_avg_cut REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN net_cf_oper REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN eps_yoy REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN inc_oper_yoy REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN ttl_inc_oper_yoy REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN net_prof_pcom_yoy REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN bps_sh REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN net_asset REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN net_prof REAL',
                'ALTER TABLE t_finance_prime ADD COLUMN net_prof_cut REAL',
                # t_valuation_data 新增字段（对齐东财 stk_get_daily_valuation_pt）
                'ALTER TABLE t_valuation_data ADD COLUMN pe_mrq REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pe_1q REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pe_2q REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pe_3q REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pe_ttm_cut REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pe_lyr_cut REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pe_mrq_cut REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pb_lyr REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pb_lyr_1 REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pb_mrq_1 REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pcf_ttm_oper REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pcf_ttm_ncf REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pcf_lyr_oper REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN pcf_lyr_ncf REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN ps_lyr REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN ps_mrq REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN ps_1q REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN ps_2q REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN ps_3q REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN peg_lyr REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN peg_mrq REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN peg_np_cgr REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN dy_ttm REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN dy_lfy REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN dv_ratio REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN dv_ttm REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN market_cap REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN circ_market_cap REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN total_share REAL',
                'ALTER TABLE t_valuation_data ADD COLUMN float_share REAL',
                # t_dividend_date 新增字段（对齐东财 stk_get_dividend）
                'ALTER TABLE t_dividend_date ADD COLUMN pub_date DATE',
                'ALTER TABLE t_dividend_date ADD COLUMN scheme_type TEXT',
                'ALTER TABLE t_dividend_date ADD COLUMN transfer_ratio REAL DEFAULT 0',
                'ALTER TABLE t_dividend_date ADD COLUMN bonus_ratio_ration REAL DEFAULT 0',
                'ALTER TABLE t_dividend_date ADD COLUMN equity_reg_date DATE',
                'ALTER TABLE t_dividend_date ADD COLUMN cash_pay_date DATE',
                'ALTER TABLE t_dividend_date ADD COLUMN share_acct_date DATE',
                'ALTER TABLE t_dividend_date ADD COLUMN share_lst_date DATE',
                'ALTER TABLE t_dividend_date ADD COLUMN cash_af_tax REAL',
                'ALTER TABLE t_dividend_date ADD COLUMN cash_bf_tax REAL',
                'ALTER TABLE t_dividend_date ADD COLUMN bonus_ratio REAL',
                'ALTER TABLE t_dividend_date ADD COLUMN convert_ratio REAL',
                'ALTER TABLE t_dividend_date ADD COLUMN base_date DATE',
                'ALTER TABLE t_dividend_date ADD COLUMN base_share REAL',
                'ALTER TABLE t_dividend_date ADD COLUMN dvd_target TEXT',
                # t_stock_daily 新增字段（对齐东财 history）
                'ALTER TABLE t_stock_daily ADD COLUMN bob TIMESTAMP',
                'ALTER TABLE t_stock_daily ADD COLUMN eob TIMESTAMP',
                'ALTER TABLE t_stock_daily ADD COLUMN position REAL',
                'ALTER TABLE t_stock_daily ADD COLUMN frequency VARCHAR(20)',
                # t_index_daily 新增字段（对齐东财 history）
                'ALTER TABLE t_index_daily ADD COLUMN bob TIMESTAMP',
                'ALTER TABLE t_index_daily ADD COLUMN eob TIMESTAMP',
                'ALTER TABLE t_index_daily ADD COLUMN position REAL',
                'ALTER TABLE t_index_daily ADD COLUMN frequency VARCHAR(20)',
                # t_etf_daily 新增字段（对齐东财 history）
                'ALTER TABLE t_etf_daily ADD COLUMN bob TIMESTAMP',
                'ALTER TABLE t_etf_daily ADD COLUMN eob TIMESTAMP',
                'ALTER TABLE t_etf_daily ADD COLUMN position REAL',
                'ALTER TABLE t_etf_daily ADD COLUMN frequency VARCHAR(20)',
            ]
            for stmt in alter_statements:
                try:
                    cursor.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # 字段已存在，忽略

            # ============ 迁移：旧表 financial_data 重命名为 t_finance_prime ============
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='financial_data'")
            if cursor.fetchone():
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='t_finance_prime'")
                if cursor.fetchone():
                    # 新表已存在，删除旧表
                    cursor.execute('DROP TABLE financial_data')
                else:
                    cursor.execute('ALTER TABLE financial_data RENAME TO t_finance_prime')
                logger.info("旧表 financial_data 已重命名为 t_finance_prime")

            # ============ 迁移：重建 t_finance_prime 表 ============
            # 旧版 t_finance_prime 表字段与当前"财务主要指标"不一致（旧版可能有 report_date
            # 或财务衍生指标字段），需要重建为正确的财务主要指标字段结构
            cursor.execute("PRAGMA table_info(t_finance_prime)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            # 财务主要指标表应有的列
            expected_cols = {
                'id', 'stock_code', 'pub_date', 'rpt_date',
                'eps_basic', 'eps_dil', 'eps_basic_cut', 'eps_dil_cut',
                'net_cf_oper_ps', 'bps_pcom_ps',
                'ttl_ast', 'ttl_liab', 'share_cptl',
                'ttl_inc_oper', 'inc_oper', 'oper_prof', 'ttl_prof',
                'ttl_eqy_pcom', 'net_prof_pcom', 'net_prof_pcom_cut',
                'roe', 'roe_weight_avg', 'roe_cut', 'roe_weight_avg_cut',
                'net_cf_oper', 'eps_yoy', 'inc_oper_yoy', 'ttl_inc_oper_yoy',
                'net_prof_pcom_yoy', 'bps_sh', 'net_asset', 'net_prof', 'net_prof_cut',
                'created_at', 'updated_at',
            }
            needs_rebuild = bool(existing_cols) and (
                # 含旧字段 report_date/stat_date 等
                'report_date' in existing_cols
                or 'stat_date' in existing_cols
                or 'eps_dil2' in existing_cols
                # 缺少财务主要指标关键列
                or 'ttl_ast' not in existing_cols
                or 'ttl_liab' not in existing_cols
                or 'ttl_inc_oper' not in existing_cols
                or 'bps_sh' not in existing_cols
                # 有多余的旧衍生指标列
                or len(existing_cols - expected_cols) > 0
            )
            if needs_rebuild:
                logger.info(f"检测到 t_finance_prime 表结构需重建 (现有 {len(existing_cols)} 列)，正在迁移...")
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS t_finance_prime_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stock_code VARCHAR(20) NOT NULL,
                        pub_date DATE,
                        rpt_date DATE,
                        eps_basic REAL,
                        eps_dil REAL,
                        eps_basic_cut REAL,
                        eps_dil_cut REAL,
                        net_cf_oper_ps REAL,
                        bps_pcom_ps REAL,
                        ttl_ast REAL,
                        ttl_liab REAL,
                        share_cptl REAL,
                        ttl_inc_oper REAL,
                        inc_oper REAL,
                        oper_prof REAL,
                        ttl_prof REAL,
                        ttl_eqy_pcom REAL,
                        net_prof_pcom REAL,
                        net_prof_pcom_cut REAL,
                        roe REAL,
                        roe_weight_avg REAL,
                        roe_cut REAL,
                        roe_weight_avg_cut REAL,
                        net_cf_oper REAL,
                        eps_yoy REAL,
                        inc_oper_yoy REAL,
                        ttl_inc_oper_yoy REAL,
                        net_prof_pcom_yoy REAL,
                        bps_sh REAL,
                        net_asset REAL,
                        net_prof REAL,
                        net_prof_cut REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(stock_code, rpt_date)
                    )
                ''')
                # 删除旧表，重命名新表（旧字段已不再兼容，不做数据迁移，下次运行时会重新拉取）
                cursor.execute('DROP TABLE IF EXISTS t_finance_prime')
                cursor.execute('ALTER TABLE t_finance_prime_new RENAME TO t_finance_prime')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_code ON t_finance_prime(stock_code)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_date ON t_finance_prime(rpt_date)')
                logger.info("t_finance_prime 表重建完成（财务主要指标字段）")

            # ============ 新增表 ============

            # 指数基本信息表 - 对齐东财 get_symbol_infos(sec_type1=1060, sec_type2=106001) 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_index_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    index_code VARCHAR(20) UNIQUE NOT NULL,
                    index_name VARCHAR(100),
                    sec_id VARCHAR(20),
                    sec_type1 INTEGER,
                    sec_type2 INTEGER,
                    board INTEGER,
                    exchange VARCHAR(20),
                    sec_abbr VARCHAR(50),
                    price_tick REAL,
                    trade_n INTEGER,
                    listed_date DATE,
                    delisted_date DATE,
                    base_date DATE,
                    base_point REAL,
                    publish_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_index_info_code ON t_index_info(index_code)')

            # 数据同步日志表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_data_sync (
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
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_log_type ON t_data_sync(sync_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_log_status ON t_data_sync(status)')

            # ============ 估值分析模块表 ============

            # 财务主要指标表 - 对齐东财 stk_get_finance_prime_pt 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_finance_prime (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) NOT NULL,
                    pub_date DATE,
                    rpt_date DATE,
                    eps_basic REAL,
                    eps_dil REAL,
                    eps_basic_cut REAL,
                    eps_dil_cut REAL,
                    net_cf_oper_ps REAL,
                    bps_pcom_ps REAL,
                    ttl_ast REAL,
                    ttl_liab REAL,
                    share_cptl REAL,
                    ttl_inc_oper REAL,
                    inc_oper REAL,
                    oper_prof REAL,
                    ttl_prof REAL,
                    ttl_eqy_pcom REAL,
                    net_prof_pcom REAL,
                    net_prof_pcom_cut REAL,
                    roe REAL,
                    roe_weight_avg REAL,
                    roe_cut REAL,
                    roe_weight_avg_cut REAL,
                    net_cf_oper REAL,
                    eps_yoy REAL,
                    inc_oper_yoy REAL,
                    ttl_inc_oper_yoy REAL,
                    net_prof_pcom_yoy REAL,
                    bps_sh REAL,
                    net_asset REAL,
                    net_prof REAL,
                    net_prof_cut REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, rpt_date)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_code ON t_finance_prime(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_financial_date ON t_finance_prime(rpt_date)')

            # 每日市值指标表 - 对齐东财 stk_get_daily_mktvalue_pt 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_stock_mktvalue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) NOT NULL,
                    trade_date DATE NOT NULL,
                    tot_mv REAL,
                    tot_mv_csrc REAL,
                    a_mv REAL,
                    a_mv_ex_ltd REAL,
                    b_mv REAL,
                    b_mv_ex_ltd REAL,
                    ev REAL,
                    ev_ex_curr REAL,
                    ev_ebitda REAL,
                    equity_value REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, trade_date)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_mktvalue_code ON t_stock_mktvalue(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_mktvalue_date ON t_stock_mktvalue(trade_date)')

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
                CREATE TABLE IF NOT EXISTS t_stock_pool (
                    pool_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pool_name VARCHAR(100) NOT NULL UNIQUE,
                    pool_code VARCHAR(50),
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_stock_in_stock_pool (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pool_id INTEGER NOT NULL,
                    stock_code VARCHAR(20) NOT NULL,
                    added_date DATE,
                    removed_date DATE,
                    FOREIGN KEY (pool_id) REFERENCES t_stock_pool(pool_id) ON DELETE CASCADE,
                    UNIQUE(pool_id, stock_code, added_date)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pool_member_pool ON t_stock_in_stock_pool(pool_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pool_member_stock ON t_stock_in_stock_pool(stock_code)')

            # ============ 交易日历表 ============
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_trading_date (
                    trade_date TEXT PRIMARY KEY
                )
            ''')
            # 首次创建时从 t_stock_daily 填充
            cursor.execute('SELECT COUNT(*) as cnt FROM t_trading_date')
            count = cursor.fetchone()['cnt']
            if count == 0:
                cursor.execute('''
                    INSERT OR IGNORE INTO t_trading_date (trade_date)
                    SELECT DISTINCT trade_date FROM t_stock_daily
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

            # ============ Phase 6: quantlab_* 实验跟踪表 ============
            # 4 张表与 src/quantlab/research/database.py 中 4 张表 schema 保持一致，
            # 以便 MyquantTracker 写入 aquant.db、quantlab 原生 Tracker 写入 research.db
            # 两边可独立运行，也可由 MyquantTracker 桥接。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quantlab_experiments (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    params_json TEXT,
                    created_at TEXT NOT NULL,
                    tag TEXT,
                    note TEXT
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ql_exp_strategy ON quantlab_experiments(strategy)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ql_exp_tag ON quantlab_experiments(tag)')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quantlab_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    final_equity REAL DEFAULT 0,
                    total_return REAL DEFAULT 0,
                    sharpe REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    trade_count INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    source TEXT,
                    extras_json TEXT,
                    FOREIGN KEY (experiment_id) REFERENCES quantlab_experiments(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ql_res_exp ON quantlab_results(experiment_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ql_res_sharpe ON quantlab_results(sharpe)')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quantlab_walkforward (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    n_windows INTEGER DEFAULT 0,
                    avg_sharpe REAL DEFAULT 0,
                    avg_return REAL DEFAULT 0,
                    avg_max_dd REAL DEFAULT 0,
                    stitched_sharpe REAL DEFAULT 0,
                    stitched_return REAL DEFAULT 0,
                    stitched_max_dd REAL DEFAULT 0,
                    stability_score REAL DEFAULT 0,
                    parameter_drift REAL DEFAULT 0,
                    extras_json TEXT,
                    FOREIGN KEY (experiment_id) REFERENCES quantlab_experiments(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ql_wf_exp ON quantlab_walkforward(experiment_id)')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quantlab_quintile_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    factor_name TEXT NOT NULL,
                    q1_sharpe REAL DEFAULT 0,
                    q2_sharpe REAL DEFAULT 0,
                    q3_sharpe REAL DEFAULT 0,
                    q4_sharpe REAL DEFAULT 0,
                    q5_sharpe REAL DEFAULT 0,
                    long_short_sharpe REAL DEFAULT 0,
                    ic REAL DEFAULT 0,
                    ir REAL DEFAULT 0,
                    long_short_return REAL DEFAULT 0,
                    extras_json TEXT,
                    created_at TEXT NOT NULL
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ql_q5_factor ON quantlab_quintile_results(factor_name)')

            # ============ 新增表（spec 要求） ============

            # ETF 基本信息表 - 对齐东财 get_symbol_infos(sec_type1=1020, sec_type2=102001) 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_etf_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    etf_code VARCHAR(20) NOT NULL UNIQUE,
                    etf_name TEXT,
                    sec_id VARCHAR(20),
                    sec_type1 INTEGER,
                    sec_type2 INTEGER,
                    board INTEGER,
                    exchange VARCHAR(20),
                    sec_abbr VARCHAR(50),
                    price_tick REAL,
                    trade_n INTEGER,
                    listed_date DATE,
                    delisted_date DATE,
                    fund_type TEXT,
                    benchmark_index VARCHAR(20),
                    management_fee REAL,
                    custodian_fee REAL,
                    management_company TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_etf_info_code ON t_etf_info(etf_code)')

            # ETF 日频数据表 - 对齐东财 history 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_etf_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date DATE NOT NULL,
                    etf_code VARCHAR(20) NOT NULL,
                    bob TIMESTAMP,
                    eob TIMESTAMP,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    amount REAL,
                    position REAL,
                    frequency VARCHAR(20),
                    pre_close REAL,
                    vwap REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, etf_code)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_etf_daily_code ON t_etf_daily(etf_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_etf_daily_date ON t_etf_daily(trade_date)')

            # 板块基本信息表 - 对齐东财 get_symbol_infos(sec_type1=1070, sec_type2=107001) 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_sector_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sector_code VARCHAR(20) NOT NULL UNIQUE,
                    sector_name TEXT NOT NULL,
                    sec_id VARCHAR(20),
                    sec_type1 INTEGER,
                    sec_type2 INTEGER,
                    exchange VARCHAR(20),
                    sec_abbr VARCHAR(50),
                    sector_type TEXT NOT NULL DEFAULT '概念',
                    parent_sector VARCHAR(20),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_sector_info_code ON t_sector_info(sector_code)')

            # 板块成分股表（与 t_stock_in_index 区分：index=指数+权重，sector=板块成分股）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_stock_list_in_sector (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sector_code VARCHAR(20) NOT NULL,
                    stock_code VARCHAR(20) NOT NULL,
                    in_date DATE,
                    out_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(sector_code, stock_code, in_date)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sector_const_code ON t_stock_list_in_sector(sector_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sector_const_stock ON t_stock_list_in_sector(stock_code)')

            # 除权除息表 - 对齐东财 stk_get_dividend 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_dividend_date (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(20) NOT NULL,
                    ex_date DATE NOT NULL,
                    pub_date DATE,
                    dividend_type TEXT,
                    scheme_type TEXT,
                    per_cash_dividend REAL DEFAULT 0,
                    per_share_dividend REAL DEFAULT 0,
                    per_share_conversion REAL DEFAULT 0,
                    transfer_ratio REAL DEFAULT 0,
                    bonus_ratio_ration REAL DEFAULT 0,
                    allotment_ratio REAL DEFAULT 0,
                    allotment_price REAL DEFAULT 0,
                    equity_reg_date DATE,
                    cash_pay_date DATE,
                    share_acct_date DATE,
                    share_lst_date DATE,
                    cash_af_tax REAL,
                    cash_bf_tax REAL,
                    bonus_ratio REAL,
                    convert_ratio REAL,
                    base_date DATE,
                    base_share REAL,
                    dvd_target TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, ex_date, dividend_type)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_dividend_date_code ON t_dividend_date(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_dividend_date_date ON t_dividend_date(ex_date)')

            # 策略元数据表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id VARCHAR(50) NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT,
                    applicable_scene TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_strategy_info_id ON strategy_info(strategy_id)')

            # 策略标签表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_tag (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id VARCHAR(50) NOT NULL,
                    tag TEXT NOT NULL,
                    UNIQUE(strategy_id, tag),
                    FOREIGN KEY (strategy_id) REFERENCES strategy_info(strategy_id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_strategy_tag_id ON strategy_tag(strategy_id)')

            # 策略最佳表现表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_best_perf (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id VARCHAR(50) NOT NULL,
                    version TEXT NOT NULL DEFAULT 'latest',
                    best_sharpe REAL,
                    best_return REAL,
                    best_max_dd REAL,
                    best_experiment_id TEXT,
                    best_source TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    extras_json TEXT,
                    UNIQUE(strategy_id, version)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_best_perf_id ON strategy_best_perf(strategy_id)')

            # 估值数据表 - 对齐东财 stk_get_daily_valuation_pt 返回字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_valuation_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date DATE NOT NULL,
                    stock_code VARCHAR(20) NOT NULL,
                    pe_ttm REAL,
                    pe_lyr REAL,
                    pe_mrq REAL,
                    pe_1q REAL,
                    pe_2q REAL,
                    pe_3q REAL,
                    pe_ttm_cut REAL,
                    pe_lyr_cut REAL,
                    pe_mrq_cut REAL,
                    pe_1q_cut REAL,
                    pe_2q_cut REAL,
                    pe_3q_cut REAL,
                    pb_lyr REAL,
                    pb_lf REAL,
                    pb_mrq REAL,
                    pcf_ttm_oper REAL,
                    pcf_ttm_ncf REAL,
                    pcf_lyr_oper REAL,
                    pcf_lyr_ncf REAL,
                    ps_ttm REAL,
                    ps_lyr REAL,
                    ps_mrq REAL,
                    ps_1q REAL,
                    ps_2q REAL,
                    ps_3q REAL,
                    peg_lyr REAL,
                    peg_1q REAL,
                    peg_2q REAL,
                    peg_3q REAL,
                    dy_ttm REAL,
                    dy_lfy REAL,
                    market_cap REAL,
                    circ_market_cap REAL,
                    total_share REAL,
                    float_share REAL,
                    total_mv REAL,
                    circ_mv REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, stock_code)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_valuation_date ON t_valuation_data(trade_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_valuation_code ON t_valuation_data(stock_code)')

            # 券商历史交易记录表 - 存储从券商导出CSV导入的交易记录
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS t_broker_trade (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date DATE NOT NULL,
                    trade_time VARCHAR(20),
                    stock_code VARCHAR(20) NOT NULL,
                    stock_name VARCHAR(100),
                    trade_type VARCHAR(10) NOT NULL,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    amount REAL NOT NULL,
                    commission REAL DEFAULT 0,
                    stamp_tax REAL DEFAULT 0,
                    transfer_fee REAL DEFAULT 0,
                    other_fee REAL DEFAULT 0,
                    total_fee REAL DEFAULT 0,
                    net_amount REAL DEFAULT 0,
                    broker VARCHAR(50),
                    account VARCHAR(50),
                    source_file VARCHAR(255),
                    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, stock_code, price, quantity, trade_type)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_broker_trade_date ON t_broker_trade(trade_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_broker_trade_code ON t_broker_trade(stock_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_t_broker_trade_broker ON t_broker_trade(broker)')

            # ============ 确保关键表列齐全：补全因旧 schema 缺失的列 ============
            # 定义每个表所有列的完整定义（name, type, default）
            # 注意：CREATE TABLE IF NOT EXISTS 只会在表不存在时创建；
            #       对已存在的旧表，需要 ALTER TABLE ADD COLUMN 来逐列补齐
            table_columns = {
                't_stock_daily': [
                    ('bob', 'TIMESTAMP', None),
                    ('eob', 'TIMESTAMP', None),
                    ('open', 'REAL', None),
                    ('high', 'REAL', None),
                    ('low', 'REAL', None),
                    ('close', 'REAL', None),
                    ('volume', 'REAL', None),
                    ('amount', 'REAL', None),
                    ('position', 'REAL', None),
                    ('frequency', 'VARCHAR(20)', None),
                    ('pre_close', 'REAL', None),
                    ('vwap', 'REAL', None),
                    ('suspend_flag', 'INTEGER', '0'),
                ],
                't_etf_daily': [
                    ('bob', 'TIMESTAMP', None),
                    ('eob', 'TIMESTAMP', None),
                    ('open', 'REAL', None),
                    ('high', 'REAL', None),
                    ('low', 'REAL', None),
                    ('close', 'REAL', None),
                    ('volume', 'REAL', None),
                    ('amount', 'REAL', None),
                    ('position', 'REAL', None),
                    ('frequency', 'VARCHAR(20)', None),
                    ('pre_close', 'REAL', None),
                    ('vwap', 'REAL', None),
                ],
                't_index_daily': [
                    ('bob', 'TIMESTAMP', None),
                    ('eob', 'TIMESTAMP', None),
                    ('open', 'REAL', None),
                    ('high', 'REAL', None),
                    ('low', 'REAL', None),
                    ('close', 'REAL', None),
                    ('volume', 'REAL', None),
                    ('amount', 'REAL', None),
                    ('position', 'REAL', None),
                    ('frequency', 'VARCHAR(20)', None),
                    ('pre_close', 'REAL', None),
                ],
                't_stock_info': [
                    ('stock_name', 'VARCHAR(100)', None),
                    ('sec_id', 'VARCHAR(20)', None),
                    ('sec_type1', 'INTEGER', None),
                    ('sec_type2', 'INTEGER', None),
                    ('board', 'INTEGER', None),
                    ('exchange', 'VARCHAR(20)', None),
                    ('sec_abbr', 'VARCHAR(50)', None),
                    ('price_tick', 'REAL', None),
                    ('trade_n', 'INTEGER', None),
                    ('listed_date', 'DATE', None),
                    ('delisted_date', 'DATE', None),
                    ('delisting_begin_date', 'DATE', None),
                    ('industry', 'VARCHAR(100)', None),
                    ('market_cap', 'REAL', None),
                ],
                't_etf_info': [
                    ('etf_name', 'TEXT', None),
                    ('sec_id', 'VARCHAR(20)', None),
                    ('sec_type1', 'INTEGER', None),
                    ('sec_type2', 'INTEGER', None),
                    ('board', 'INTEGER', None),
                    ('exchange', 'VARCHAR(20)', None),
                    ('sec_abbr', 'VARCHAR(50)', None),
                    ('price_tick', 'REAL', None),
                    ('trade_n', 'INTEGER', None),
                    ('listed_date', 'DATE', None),
                    ('delisted_date', 'DATE', None),
                    ('fund_type', 'TEXT', None),
                    ('benchmark_index', 'VARCHAR(20)', None),
                    ('management_fee', 'REAL', None),
                    ('custodian_fee', 'REAL', None),
                    ('management_company', 'TEXT', None),
                ],
                't_index_info': [
                    ('index_name', 'VARCHAR(100)', None),
                    ('sec_id', 'VARCHAR(20)', None),
                    ('sec_type1', 'INTEGER', None),
                    ('sec_type2', 'INTEGER', None),
                    ('board', 'INTEGER', None),
                    ('exchange', 'VARCHAR(20)', None),
                    ('sec_abbr', 'VARCHAR(50)', None),
                    ('price_tick', 'REAL', None),
                    ('trade_n', 'INTEGER', None),
                    ('listed_date', 'DATE', None),
                    ('delisted_date', 'DATE', None),
                    ('base_date', 'DATE', None),
                    ('base_point', 'REAL', None),
                    ('publish_date', 'DATE', None),
                ],
                't_sector_info': [
                    ('sector_name', 'TEXT', None),
                    ('sec_id', 'VARCHAR(20)', None),
                    ('sec_type1', 'INTEGER', None),
                    ('sec_type2', 'INTEGER', None),
                    ('board', 'INTEGER', None),
                    ('exchange', 'VARCHAR(20)', None),
                    ('sec_abbr', 'VARCHAR(50)', None),
                ],
                't_valuation_data': [
                    ('pe_ttm', 'REAL', None),
                    ('pe_lyr', 'REAL', None),
                    ('pe_mrq', 'REAL', None),
                    ('pe_1q', 'REAL', None),
                    ('pe_2q', 'REAL', None),
                    ('pe_3q', 'REAL', None),
                    ('pe_ttm_cut', 'REAL', None),
                    ('pe_lyr_cut', 'REAL', None),
                    ('pe_mrq_cut', 'REAL', None),
                    ('pe_1q_cut', 'REAL', None),
                    ('pe_2q_cut', 'REAL', None),
                    ('pe_3q_cut', 'REAL', None),
                    ('pb_lyr', 'REAL', None),
                    ('pb_lf', 'REAL', None),
                    ('pb_mrq', 'REAL', None),
                    ('pcf_ttm_oper', 'REAL', None),
                    ('pcf_ttm_ncf', 'REAL', None),
                    ('pcf_lyr_oper', 'REAL', None),
                    ('pcf_lyr_ncf', 'REAL', None),
                    ('ps_ttm', 'REAL', None),
                    ('ps_lyr', 'REAL', None),
                    ('ps_mrq', 'REAL', None),
                    ('ps_1q', 'REAL', None),
                    ('ps_2q', 'REAL', None),
                    ('ps_3q', 'REAL', None),
                    ('peg_lyr', 'REAL', None),
                    ('peg_1q', 'REAL', None),
                    ('peg_2q', 'REAL', None),
                    ('peg_3q', 'REAL', None),
                    ('dy_ttm', 'REAL', None),
                    ('dy_lfy', 'REAL', None),
                    ('market_cap', 'REAL', None),
                    ('circ_market_cap', 'REAL', None),
                    ('total_share', 'REAL', None),
                    ('float_share', 'REAL', None),
                    ('total_mv', 'REAL', None),
                    ('circ_mv', 'REAL', None),
                ],
            }

            for table, columns in table_columns.items():
                try:
                    cursor.execute(f"PRAGMA table_info({table})")
                    existing = {row[1] for row in cursor.fetchall()}
                    if not existing:
                        continue  # 表不存在，跳过
                    for col_name, col_type, default_val in columns:
                        if col_name not in existing:
                            sql = f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"
                            if default_val is not None:
                                sql += f" DEFAULT {default_val}"
                            try:
                                cursor.execute(sql)
                                logger.info(f"为 {table} 补全列: {col_name}")
                            except sqlite3.OperationalError as e:
                                logger.debug(f"为 {table} 补列 {col_name} 失败(可能已存在): {e}")
                except sqlite3.OperationalError:
                    pass

            logger.info(f"数据库初始化完成: {self.db_path}")

    # ============ 股票日频数据操作 ============

    def insert_stock_daily(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入股票日频数据 - 对齐东财 history 返回字段"""
        if df.empty:
            return 0

        df = df.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')

        # bob/eob 是 pandas Timestamp，需转为字符串
        for col in ['bob', 'eob']:
            if col in df.columns:
                df[col] = df[col].apply(
                    lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(x) and hasattr(x, 'strftime') else (str(x) if pd.notna(x) else None)
                )

        # 确保必要列存在
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col not in df.columns:
                df[col] = 0.0
        for col in ['amount', 'vwap', 'pre_close', 'bob', 'eob', 'position', 'frequency']:
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
                        row.get('bob'), row.get('eob'),
                        row.get('open'), row.get('high'), row.get('low'),
                        row.get('close'), row.get('volume'),
                        row.get('amount'), row.get('position'), row.get('frequency'),
                        row.get('vwap'), row.get('pre_close'), row.get('suspend_flag')
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO t_stock_daily
                    (trade_date, stock_code, bob, eob, open, high, low, close, volume,
                     amount, position, frequency, vwap, pre_close, suspend_flag)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            sql = f"SELECT {','.join(select_cols)} FROM t_stock_daily WHERE 1=1"
        else:
            sql = 'SELECT * FROM t_stock_daily WHERE 1=1'
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
                'SELECT stock_code, stock_name, list_date FROM t_stock_info',
                conn
            )
        return df

    # ============ 指数日频数据操作 ============

    def insert_index_daily(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入指数日频数据 - 对齐东财 history 返回字段"""
        if df.empty:
            return 0

        df = df.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')

        # bob/eob 是 pandas Timestamp，需转为字符串
        for col in ['bob', 'eob']:
            if col in df.columns:
                df[col] = df[col].apply(
                    lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(x) and hasattr(x, 'strftime') else (str(x) if pd.notna(x) else None)
                )

        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col not in df.columns:
                df[col] = 0.0
        for col in ['pre_close', 'amount', 'bob', 'eob', 'position', 'frequency']:
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
                        row.get('bob'), row.get('eob'),
                        row.get('open'), row.get('high'), row.get('low'),
                        row.get('close'), row.get('volume'),
                        row.get('amount'), row.get('position'), row.get('frequency'),
                        row.get('pre_close')
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO t_index_daily
                    (trade_date, index_code, bob, eob, open, high, low, close, volume,
                     amount, position, frequency, pre_close)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        sql = 'SELECT * FROM t_index_daily WHERE 1=1'
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
        """批量插入股票信息 - 对齐东财 get_symbol_infos 返回字段"""
        if df.empty:
            return 0

        df = df.copy()

        # 日期字段安全解析
        def safe_parse_date(x):
            if pd.isna(x) or x == '' or x == '0000-00-00' or str(x).startswith('0000'):
                return None
            try:
                return pd.to_datetime(x).strftime('%Y-%m-%d')
            except (ValueError, pd.errors.OutOfBoundsDatetime):
                return None

        for date_col in ['listed_date', 'delisted_date', 'delisting_begin_date']:
            if date_col in df.columns:
                df[date_col] = df[date_col].apply(safe_parse_date)

        # 兼容旧字段 list_date -> listed_date
        if 'list_date' in df.columns and 'listed_date' not in df.columns:
            df['listed_date'] = df['list_date'].apply(safe_parse_date)

        # 确保必要列存在
        for col in ['stock_code', 'stock_name']:
            if col not in df.columns:
                df[col] = None
        # 东财 API 字段
        for col in ['sec_id', 'sec_type1', 'sec_type2', 'board', 'exchange',
                     'sec_abbr', 'price_tick', 'trade_n', 'listed_date',
                     'delisted_date', 'delisting_begin_date']:
            if col not in df.columns:
                df[col] = None
        # 兼容旧字段
        for col in ['industry', 'market_cap']:
            if col not in df.columns:
                df[col] = None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = []
            for _, row in df.iterrows():
                rows.append((
                    row.get('stock_code'), row.get('stock_name'),
                    row.get('sec_id'), row.get('sec_type1'), row.get('sec_type2'),
                    row.get('board'), row.get('exchange'), row.get('sec_abbr'),
                    row.get('price_tick'), row.get('trade_n'), row.get('listed_date'),
                    row.get('delisted_date'), row.get('delisting_begin_date'),
                    row.get('industry'), row.get('market_cap'),
                ))
            cursor.executemany('''
                INSERT OR REPLACE INTO t_stock_info
                (stock_code, stock_name, sec_id, sec_type1, sec_type2,
                 board, exchange, sec_abbr, price_tick, trade_n,
                 listed_date, delisted_date, delisting_begin_date,
                 industry, market_cap)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', rows)

        logger.info(f"插入 {len(rows)} 条股票信息")
        return len(rows)

    def get_stock_info(self) -> pd.DataFrame:
        """获取股票信息"""
        with self.get_connection() as conn:
            df = pd.read_sql_query('SELECT * FROM t_stock_info', conn)
        return df

    def load_t_stock_pool(self, pool_id: int = None) -> pd.DataFrame:
        """
        加载股票池

        Parameters
        ----------
        pool_id : int, optional
            股票池ID，为空则返回全市场股票

        Returns
        -------
        pd.DataFrame
            股票代码列表
        """
        if pool_id is None:
            # 全市场：从 t_stock_info 获取
            return self.get_stock_info()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 检查股票池是否存在
            cursor.execute('SELECT pool_name FROM t_stock_pool WHERE id = ?', (pool_id,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"股票池 {pool_id} 不存在")
                return pd.DataFrame()

            # 从 t_stock_in_stock_pool 获取成员
            df = pd.read_sql_query(
                'SELECT stock_code FROM t_stock_in_stock_pool WHERE pool_id = ?',
                conn, params=(pool_id,),
            )
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

    # ============ 交易日历操作 ============

    def insert_trading_dates(self, dates: list, batch_size: int = 5000) -> int:
        """
        全量替换交易日历到 t_trading_date 表

        先清空表，再批量插入。每次同步全量替换，确保与接口数据一致。

        Parameters
        ----------
        dates : list
            交易日列表，格式 'YYYY-MM-DD'

        Returns
        -------
        int
            插入的记录数
        """
        if not dates:
            return 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 全量替换：先清空再插入
            cursor.execute('DELETE FROM t_trading_date')
            count = 0
            for i in range(0, len(dates), batch_size):
                batch = dates[i:i + batch_size]
                rows = [(d,) for d in batch]
                cursor.executemany(
                    'INSERT INTO t_trading_date (trade_date) VALUES (?)',
                    rows,
                )
                count += len(rows)

        logger.info(f"全量替换 {count} 条交易日历")
        return count

    # ============ 估值数据操作 ============

    def insert_valuation_data(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入估值数据到 t_valuation_data 表 - 对齐东财 stk_get_daily_valuation_pt 返回字段"""
        if df.empty:
            return 0

        df = df.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')

        # 列名映射
        col_map = {}
        if 'symbol' in df.columns and 'stock_code' not in df.columns:
            col_map['symbol'] = 'stock_code'
        if col_map:
            df = df.rename(columns=col_map)

        for col in ['trade_date', 'stock_code']:
            if col not in df.columns:
                logger.warning(f"估值数据缺少必要列: {col}")
                return 0
        # 东财 API 字段（对齐 stk_get_daily_valuation_pt + stk_get_daily_mktvalue_pt）
        for col in ['pe_ttm', 'pe_lyr', 'pe_mrq', 'pe_1q', 'pe_2q', 'pe_3q',
                     'pe_ttm_cut', 'pe_lyr_cut', 'pe_mrq_cut',
                     'pe_1q_cut', 'pe_2q_cut', 'pe_3q_cut',
                     'pb_lyr', 'pb_lf', 'pb_mrq',
                     'pcf_ttm_oper', 'pcf_ttm_ncf', 'pcf_lyr_oper', 'pcf_lyr_ncf',
                     'ps_ttm', 'ps_lyr', 'ps_mrq', 'ps_1q', 'ps_2q', 'ps_3q',
                     'peg_lyr', 'peg_1q', 'peg_2q', 'peg_3q',
                     'dy_ttm', 'dy_lfy',
                     'market_cap', 'circ_market_cap', 'total_share', 'float_share',
                     'total_mv', 'circ_mv']:
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
                        row.get('trade_date'), row.get('stock_code'),
                        row.get('pe_ttm'), row.get('pe_lyr'), row.get('pe_mrq'),
                        row.get('pe_1q'), row.get('pe_2q'), row.get('pe_3q'),
                        row.get('pe_ttm_cut'), row.get('pe_lyr_cut'), row.get('pe_mrq_cut'),
                        row.get('pe_1q_cut'), row.get('pe_2q_cut'), row.get('pe_3q_cut'),
                        row.get('pb_lyr'), row.get('pb_lf'), row.get('pb_mrq'),
                        row.get('pcf_ttm_oper'), row.get('pcf_ttm_ncf'),
                        row.get('pcf_lyr_oper'), row.get('pcf_lyr_ncf'),
                        row.get('ps_ttm'), row.get('ps_lyr'), row.get('ps_mrq'),
                        row.get('ps_1q'), row.get('ps_2q'), row.get('ps_3q'),
                        row.get('peg_lyr'), row.get('peg_1q'), row.get('peg_2q'), row.get('peg_3q'),
                        row.get('dy_ttm'), row.get('dy_lfy'),
                        row.get('market_cap'), row.get('circ_market_cap'),
                        row.get('total_share'), row.get('float_share'),
                        row.get('total_mv'), row.get('circ_mv'),
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO t_valuation_data
                    (trade_date, stock_code, pe_ttm, pe_lyr, pe_mrq,
                     pe_1q, pe_2q, pe_3q, pe_ttm_cut, pe_lyr_cut, pe_mrq_cut,
                     pe_1q_cut, pe_2q_cut, pe_3q_cut,
                     pb_lyr, pb_lf, pb_mrq,
                     pcf_ttm_oper, pcf_ttm_ncf, pcf_lyr_oper, pcf_lyr_ncf,
                     ps_ttm, ps_lyr, ps_mrq, ps_1q, ps_2q, ps_3q,
                     peg_lyr, peg_1q, peg_2q, peg_3q,
                     dy_ttm, dy_lfy,
                     market_cap, circ_market_cap, total_share, float_share,
                     total_mv, circ_mv)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条估值数据")
        return count

    # ============ 工具方法 ============

    def get_trade_dates(self, start_date: str, end_date: str) -> List[str]:
        """获取交易日列表（从 t_trading_date 表查询）"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT trade_date FROM t_trading_date
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
            ''', (start_date, end_date))
            return [row['trade_date'] for row in cursor.fetchall()]

    def get_available_stocks(self, trade_date: str) -> List[str]:
        """获取某日的可交易股票列表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT stock_code FROM t_stock_daily
                WHERE trade_date = ?
            ''', (trade_date,))
            return [row['stock_code'] for row in cursor.fetchall()]

    def get_data_summary(self) -> Dict[str, Any]:
        """获取数据库数据概览"""
        summary = {}

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) as cnt, MIN(trade_date) as min_date, MAX(trade_date) as max_date FROM t_stock_daily')
            row = cursor.fetchone()
            summary['t_stock_daily'] = {
                'count': row['cnt'],
                'start_date': row['min_date'],
                'end_date': row['max_date']
            }

            cursor.execute('SELECT COUNT(*) as cnt, MIN(trade_date) as min_date, MAX(trade_date) as max_date FROM t_index_daily')
            row = cursor.fetchone()
            summary['t_index_daily'] = {
                'count': row['cnt'],
                'start_date': row['min_date'],
                'end_date': row['max_date']
            }

            cursor.execute('SELECT COUNT(*) as cnt FROM t_stock_info')
            summary['t_stock_info'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM execution_log')
            summary['execution_log'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM best_records')
            summary['best_records'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM t_stock_in_index')
            summary['t_stock_in_index'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM portfolio_analysis')
            summary['portfolio_analysis'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM factor_exposure')
            summary['factor_exposure'] = {'count': cursor.fetchone()['cnt']}

            cursor.execute('SELECT COUNT(*) as cnt FROM t_data_sync')
            summary['t_data_sync'] = {'count': cursor.fetchone()['cnt']}

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
                    INSERT OR REPLACE INTO t_stock_in_index
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
                SELECT * FROM t_stock_in_index
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
        sql = 'SELECT * FROM t_stock_in_index WHERE index_code = ?'
        params = [index_code]

        # 兼容：忽略日期参数（表已无 trade_date 列）

        sql += ' ORDER BY weight DESC'

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    # ============ 申万行业分类操作 ============

    def replace_stock_in_sw(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """
        全量替换申万行业分类明细 → t_stock_in_sw

        先 DELETE 全表，再批量 INSERT。
        """
        if df.empty:
            return 0

        df = df.copy()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM t_stock_in_sw')
            count = 0
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('stock_code'),
                        row.get('industry_code'),
                        row.get('industry_l1'),
                        row.get('industry_l2'),
                        row.get('industry_l3'),
                        row.get('exchange'),
                        row.get('stock_name'),
                    ))
                cursor.executemany('''
                    INSERT INTO t_stock_in_sw
                    (stock_code, industry_code, industry_l1, industry_l2, industry_l3, exchange, stock_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)
            conn.commit()

        logger.info(f"替换写入 {count} 条申万行业分类数据")
        return count

    def get_stock_in_sw(
        self,
        stock_codes: Optional[List[str]] = None,
        industry_l1: Optional[str] = None,
        industry_l2: Optional[str] = None,
        industry_l3: Optional[str] = None,
    ) -> pd.DataFrame:
        """查询申万行业分类明细"""
        sql = 'SELECT * FROM t_stock_in_sw WHERE 1=1'
        params = []
        if stock_codes:
            placeholders = ','.join(['?' for _ in stock_codes])
            sql += f' AND stock_code IN ({placeholders})'
            params.extend(stock_codes)
        if industry_l1:
            sql += ' AND industry_l1 = ?'
            params.append(industry_l1)
        if industry_l2:
            sql += ' AND industry_l2 = ?'
            params.append(industry_l2)
        if industry_l3:
            sql += ' AND industry_l3 = ?'
            params.append(industry_l3)
        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)
        return df

    # ============ ETF 数据操作 ============

    def insert_etf_info(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入 ETF 基本信息到 t_etf_info 表 - 对齐东财 get_symbol_infos 返回字段"""
        if df.empty:
            return 0

        df = df.copy()
        for col in ['etf_code', 'etf_name']:
            if col not in df.columns:
                if col == 'etf_code' and 'stock_code' in df.columns:
                    df['etf_code'] = df['stock_code']
                elif col == 'etf_code' and 'symbol' in df.columns:
                    df['etf_code'] = df['symbol']
                elif col == 'etf_name' and 'stock_name' in df.columns:
                    df['etf_name'] = df['stock_name']
                elif col == 'etf_name' and 'sec_name' in df.columns:
                    df['etf_name'] = df['sec_name']
                else:
                    df[col] = None
        # 东财 API 字段
        for col in ['sec_id', 'sec_type1', 'sec_type2', 'board', 'exchange',
                     'sec_abbr', 'price_tick', 'trade_n', 'listed_date', 'delisted_date']:
            if col not in df.columns:
                df[col] = None
        # 兼容旧字段 list_date -> listed_date, delist_date -> delisted_date
        if 'list_date' in df.columns and 'listed_date' not in df.columns:
            df['listed_date'] = df['list_date']
        if 'delist_date' in df.columns and 'delisted_date' not in df.columns:
            df['delisted_date'] = df['delist_date']
        # 转换 Timestamp 为字符串，SQLite 不支持 Timestamp 类型
        for col in ['listed_date', 'delisted_date']:
            if col in df.columns:
                df[col] = df[col].apply(
                    lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else (str(x) if x is not None and str(x) != 'nan' else None)
                )
        # 扩展字段
        for col in ['fund_type', 'benchmark_index', 'management_fee',
                     'custodian_fee', 'management_company']:
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
                        row.get('etf_code'), row.get('etf_name'),
                        row.get('sec_id'), row.get('sec_type1'), row.get('sec_type2'),
                        row.get('board'), row.get('exchange'), row.get('sec_abbr'),
                        row.get('price_tick'), row.get('trade_n'),
                        row.get('listed_date'), row.get('delisted_date'),
                        row.get('fund_type'), row.get('benchmark_index'),
                        row.get('management_fee'), row.get('custodian_fee'),
                        row.get('management_company'),
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO t_etf_info
                    (etf_code, etf_name, sec_id, sec_type1, sec_type2,
                     board, exchange, sec_abbr, price_tick, trade_n,
                     listed_date, delisted_date, fund_type, benchmark_index,
                     management_fee, custodian_fee, management_company)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条 ETF 信息")
        return count

    def insert_etf_daily(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入 ETF 日频数据到 t_etf_daily 表 - 对齐东财 history 返回字段"""
        if df.empty:
            return 0

        df = df.copy()
        if 'trade_date' in df.columns:
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
        if 'etf_code' not in df.columns and 'stock_code' in df.columns:
            df['etf_code'] = df['stock_code']

        # bob/eob 是 pandas Timestamp，需转为字符串
        for col in ['bob', 'eob']:
            if col in df.columns:
                df[col] = df[col].apply(
                    lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(x) and hasattr(x, 'strftime') else (str(x) if pd.notna(x) else None)
                )

        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col not in df.columns:
                df[col] = 0.0
        for col in ['amount', 'pre_close', 'vwap', 'bob', 'eob', 'position', 'frequency']:
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
                        row.get('trade_date'), row.get('etf_code'),
                        row.get('bob'), row.get('eob'),
                        row.get('open'), row.get('high'), row.get('low'), row.get('close'),
                        row.get('volume'), row.get('amount'),
                        row.get('position'), row.get('frequency'),
                        row.get('pre_close'), row.get('vwap'),
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO t_etf_daily
                    (trade_date, etf_code, bob, eob, open, high, low, close, volume,
                     amount, position, frequency, pre_close, vwap)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条 ETF 日频数据")
        return count

    def get_etf_info(self) -> pd.DataFrame:
        """获取 ETF 信息列表"""
        with self.get_connection() as conn:
            try:
                df = pd.read_sql_query('SELECT * FROM t_etf_info', conn)
            except Exception:
                df = pd.DataFrame()
        return df

    def get_etf_daily(self, etf_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        获取 ETF 日线数据

        Parameters
        ----------
        etf_code : str
            ETF 代码
        start_date : str, optional
            起始日期 (YYYYMMDD)
        end_date : str, optional
            结束日期 (YYYYMMDD)
        """
        sql = 'SELECT * FROM t_etf_daily WHERE etf_code = ?'
        params = [etf_code]
        if start_date:
            sql += ' AND trade_date >= ?'
            params.append(start_date)
        if end_date:
            sql += ' AND trade_date <= ?'
            params.append(end_date)
        sql += ' ORDER BY trade_date'
        with self.get_connection() as conn:
            try:
                df = pd.read_sql_query(sql, conn, params=params)
            except Exception:
                df = pd.DataFrame()
        return df

    # ============ 指数信息操作 ============

    def insert_index_info(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入指数基本信息到 t_index_info 表 - 对齐东财 get_symbol_infos 返回字段"""
        if df.empty:
            return 0

        df = df.copy()
        # 列名映射
        col_map = {}
        if 'symbol' in df.columns and 'index_code' not in df.columns:
            col_map['symbol'] = 'index_code'
        if 'sec_name' in df.columns and 'index_name' not in df.columns:
            col_map['sec_name'] = 'index_name'
        if col_map:
            df = df.rename(columns=col_map)

        for col in ['index_code', 'index_name']:
            if col not in df.columns:
                df[col] = None
        # 东财 API 字段
        for col in ['sec_id', 'sec_type1', 'sec_type2', 'board', 'exchange',
                     'sec_abbr', 'price_tick', 'trade_n', 'listed_date', 'delisted_date']:
            if col not in df.columns:
                df[col] = None
        # 扩展字段
        for col in ['base_date', 'base_point', 'publish_date']:
            if col not in df.columns:
                df[col] = None
        # 转换 Timestamp 为字符串，SQLite 不支持 Timestamp 类型
        for col in ['listed_date', 'delisted_date', 'base_date', 'publish_date']:
            if col in df.columns:
                df[col] = df[col].apply(
                    lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else (str(x) if x is not None and str(x) != 'nan' else None)
                )

        with self.get_connection() as conn:
            cursor = conn.cursor()
            count = 0
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('index_code'), row.get('index_name'),
                        row.get('sec_id'), row.get('sec_type1'), row.get('sec_type2'),
                        row.get('board'), row.get('exchange'), row.get('sec_abbr'),
                        row.get('price_tick'), row.get('trade_n'),
                        row.get('listed_date'), row.get('delisted_date'),
                        row.get('base_date'), row.get('base_point'), row.get('publish_date'),
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO t_index_info
                    (index_code, index_name, sec_id, sec_type1, sec_type2,
                     board, exchange, sec_abbr, price_tick, trade_n,
                     listed_date, delisted_date, base_date, base_point, publish_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条指数信息")
        return count

    # ============ 板块信息操作 ============

    def insert_sector_info(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入板块基本信息到 t_sector_info 表 - 对齐东财 get_symbol_infos 返回字段"""
        if df.empty:
            return 0

        df = df.copy()
        # 列名映射
        col_map = {}
        if 'symbol' in df.columns and 'sector_code' not in df.columns:
            col_map['symbol'] = 'sector_code'
        if 'sec_name' in df.columns and 'sector_name' not in df.columns:
            col_map['sec_name'] = 'sector_name'
        if col_map:
            df = df.rename(columns=col_map)

        for col in ['sector_code', 'sector_name']:
            if col not in df.columns:
                df[col] = None
        # 东财 API 字段
        for col in ['sec_id', 'sec_type1', 'sec_type2', 'exchange', 'sec_abbr']:
            if col not in df.columns:
                df[col] = None
        for col in ['sector_type', 'parent_sector']:
            if col not in df.columns:
                df[col] = None
        if 'sector_type' not in df.columns or df['sector_type'].isna().all():
            df['sector_type'] = '概念'

        with self.get_connection() as conn:
            cursor = conn.cursor()
            count = 0
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('sector_code'), row.get('sector_name'),
                        row.get('sec_id'), row.get('sec_type1'), row.get('sec_type2'),
                        row.get('exchange'), row.get('sec_abbr'),
                        row.get('sector_type'), row.get('parent_sector'),
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO t_sector_info
                    (sector_code, sector_name, sec_id, sec_type1, sec_type2,
                     exchange, sec_abbr, sector_type, parent_sector)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条板块信息")
        return count

    # ============ 板块数据操作 ============

    def insert_sector_constituent(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入板块成分股数据"""
        if df.empty:
            return 0

        df = df.copy()
        for col in ['in_date', 'out_date']:
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
                        row.get('sector_code'), row.get('stock_code'),
                        row.get('in_date'), row.get('out_date')
                    ))
                cursor.executemany('''
                    INSERT OR REPLACE INTO t_stock_list_in_sector
                    (sector_code, stock_code, in_date, out_date)
                    VALUES (?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条板块成分股数据")
        return count

    def get_sector_info(self) -> pd.DataFrame:
        """获取板块信息列表"""
        with self.get_connection() as conn:
            try:
                df = pd.read_sql_query('SELECT * FROM t_sector_info', conn)
            except Exception:
                df = pd.DataFrame()
        return df

    def get_sector_constituent(self, sector_code: str) -> pd.DataFrame:
        """
        获取板块成分股

        Parameters
        ----------
        sector_code : str
            板块代码
        """
        with self.get_connection() as conn:
            try:
                df = pd.read_sql_query(
                    'SELECT * FROM t_stock_list_in_sector WHERE sector_code = ?',
                    conn, params=[sector_code],
                )
            except Exception:
                df = pd.DataFrame()
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
                INSERT INTO t_data_sync
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
        sql = 'SELECT * FROM t_data_sync WHERE 1=1'
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

    def insert_t_finance_prime(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入财务主要指标数据 - 对齐东财 stk_get_finance_prime_pt 返回字段"""
        if df.empty:
            return 0

        df = df.copy()
        # 列名映射
        col_map = {}
        if 'symbol' in df.columns and 'stock_code' not in df.columns:
            col_map['symbol'] = 'stock_code'
        if col_map:
            df = df.rename(columns=col_map)

        # 兼容旧字段 stat_date / report_date -> rpt_date
        if 'rpt_date' not in df.columns:
            for src in ['stat_date', 'report_date']:
                if src in df.columns:
                    df['rpt_date'] = df[src]
                    break

        # 确保必要列存在
        for col in ['stock_code', 'rpt_date']:
            if col not in df.columns:
                df[col] = None
        # 东财 stk_get_finance_prime_pt 完整字段（财务主要指标）
        for col in ['pub_date',
                     'eps_basic', 'eps_dil', 'eps_basic_cut', 'eps_dil_cut',
                     'net_cf_oper_ps', 'bps_pcom_ps',
                     'ttl_ast', 'ttl_liab', 'share_cptl',
                     'ttl_inc_oper', 'inc_oper', 'oper_prof', 'ttl_prof',
                     'ttl_eqy_pcom', 'net_prof_pcom', 'net_prof_pcom_cut',
                     'roe', 'roe_weight_avg', 'roe_cut', 'roe_weight_avg_cut',
                     'net_cf_oper', 'eps_yoy', 'inc_oper_yoy', 'ttl_inc_oper_yoy',
                     'net_prof_pcom_yoy', 'bps_sh', 'net_asset', 'net_prof', 'net_prof_cut']:
            if col not in df.columns:
                df[col] = None

        with self.get_connection() as conn:
            count = 0
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('stock_code'), row.get('pub_date'), row.get('rpt_date'),
                        row.get('eps_basic'), row.get('eps_dil'),
                        row.get('eps_basic_cut'), row.get('eps_dil_cut'),
                        row.get('net_cf_oper_ps'), row.get('bps_pcom_ps'),
                        row.get('ttl_ast'), row.get('ttl_liab'), row.get('share_cptl'),
                        row.get('ttl_inc_oper'), row.get('inc_oper'),
                        row.get('oper_prof'), row.get('ttl_prof'),
                        row.get('ttl_eqy_pcom'), row.get('net_prof_pcom'),
                        row.get('net_prof_pcom_cut'),
                        row.get('roe'), row.get('roe_weight_avg'),
                        row.get('roe_cut'), row.get('roe_weight_avg_cut'),
                        row.get('net_cf_oper'),
                        row.get('eps_yoy'), row.get('inc_oper_yoy'),
                        row.get('ttl_inc_oper_yoy'), row.get('net_prof_pcom_yoy'),
                        row.get('bps_sh'), row.get('net_asset'),
                        row.get('net_prof'), row.get('net_prof_cut'),
                    ))
                conn.cursor().executemany('''
                    INSERT OR REPLACE INTO t_finance_prime
                    (stock_code, pub_date, rpt_date,
                     eps_basic, eps_dil, eps_basic_cut, eps_dil_cut,
                     net_cf_oper_ps, bps_pcom_ps,
                     ttl_ast, ttl_liab, share_cptl,
                     ttl_inc_oper, inc_oper, oper_prof, ttl_prof,
                     ttl_eqy_pcom, net_prof_pcom, net_prof_pcom_cut,
                     roe, roe_weight_avg, roe_cut, roe_weight_avg_cut,
                     net_cf_oper, eps_yoy, inc_oper_yoy, ttl_inc_oper_yoy,
                     net_prof_pcom_yoy, bps_sh, net_asset, net_prof, net_prof_cut)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条财务主要指标数据")
        return count

    def insert_dividend_data(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入除权除息数据到 t_dividend_date 表 - 对齐东财 stk_get_dividend 返回字段"""
        if df is None or df.empty:
            return 0

        df = df.copy()
        # 统一列名
        col_map = {}
        if 'symbol' in df.columns and 'stock_code' not in df.columns:
            col_map['symbol'] = 'stock_code'
        if col_map:
            df = df.rename(columns=col_map)

        # 确保必要列存在
        for col in ['stock_code', 'ex_date']:
            if col not in df.columns:
                df[col] = None
        # 东财 stk_get_dividend 返回字段
        for col in ['pub_date', 'scheme_type', 'equity_reg_date',
                     'cash_pay_date', 'share_acct_date', 'share_lst_date',
                     'cash_af_tax', 'cash_bf_tax', 'bonus_ratio', 'convert_ratio',
                     'base_date', 'base_share', 'dvd_target',
                     # 兼容旧字段
                     'dividend_type', 'per_cash_dividend', 'per_share_dividend',
                     'per_share_conversion', 'transfer_ratio', 'bonus_ratio_ration',
                     'allotment_ratio', 'allotment_price']:
            if col not in df.columns:
                df[col] = None
        # 新旧字段映射：cash_bf_tax -> per_cash_dividend
        if 'cash_bf_tax' in df.columns and df['per_cash_dividend'].isna().all():
            df['per_cash_dividend'] = df['cash_bf_tax']
        if 'bonus_ratio' in df.columns and df['per_share_dividend'].isna().all():
            df['per_share_dividend'] = df['bonus_ratio']
        if 'convert_ratio' in df.columns and df['per_share_conversion'].isna().all():
            df['per_share_conversion'] = df['convert_ratio']

        with self.get_connection() as conn:
            count = 0
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('stock_code', ''),
                        row.get('ex_date', ''),
                        row.get('pub_date'),
                        row.get('dividend_type', 'cash'),
                        row.get('scheme_type'),
                        row.get('per_cash_dividend', 0),
                        row.get('per_share_dividend', 0),
                        row.get('per_share_conversion', 0),
                        row.get('transfer_ratio', 0),
                        row.get('bonus_ratio_ration', 0),
                        row.get('allotment_ratio', 0),
                        row.get('allotment_price', 0),
                        row.get('equity_reg_date'),
                        row.get('cash_pay_date'),
                        row.get('share_acct_date'),
                        row.get('share_lst_date'),
                        row.get('cash_af_tax'),
                        row.get('cash_bf_tax'),
                        row.get('bonus_ratio'),
                        row.get('convert_ratio'),
                        row.get('base_date'),
                        row.get('base_share'),
                        row.get('dvd_target'),
                    ))
                conn.cursor().executemany('''
                    INSERT OR REPLACE INTO t_dividend_date
                    (stock_code, ex_date, pub_date, dividend_type, scheme_type,
                     per_cash_dividend, per_share_dividend, per_share_conversion,
                     transfer_ratio, bonus_ratio_ration, allotment_ratio, allotment_price,
                     equity_reg_date, cash_pay_date, share_acct_date, share_lst_date,
                     cash_af_tax, cash_bf_tax, bonus_ratio, convert_ratio,
                     base_date, base_share, dvd_target)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条除权除息数据")
        return count

    def get_t_finance_prime(
        self,
        stock_codes: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        查询财务主要指标数据

        Parameters
        ----------
        stock_codes : list, optional
            股票代码列表
        start_date : str, optional
            开始日期
        end_date : str, optional
            结束日期

        Returns
        -------
        pd.DataFrame
            财务主要指标数据
        """
        sql = 'SELECT * FROM t_finance_prime WHERE 1=1'
        params = []

        if stock_codes:
            placeholders = ','.join(['?' for _ in stock_codes])
            sql += f' AND stock_code IN ({placeholders})'
            params.extend(stock_codes)

        if start_date:
            sql += ' AND rpt_date >= ?'
            params.append(start_date)

        if end_date:
            sql += ' AND rpt_date <= ?'
            params.append(end_date)

        sql += ' ORDER BY stock_code, rpt_date'

        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        return df

    # ============ 每日市值指标操作 ============

    def insert_stock_mktvalue(self, df: pd.DataFrame, batch_size: int = 5000) -> int:
        """批量插入每日市值指标数据 → t_stock_mktvalue"""
        if df.empty:
            return 0

        df = df.copy()
        col_map = {}
        if 'symbol' in df.columns and 'stock_code' not in df.columns:
            col_map['symbol'] = 'stock_code'
        if col_map:
            df = df.rename(columns=col_map)

        for col in ['stock_code', 'trade_date']:
            if col not in df.columns:
                df[col] = None
        for col in ['tot_mv', 'tot_mv_csrc', 'a_mv', 'a_mv_ex_ltd',
                     'b_mv', 'b_mv_ex_ltd', 'ev', 'ev_ex_curr',
                     'ev_ebitda', 'equity_value']:
            if col not in df.columns:
                df[col] = None

        with self.get_connection() as conn:
            count = 0
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                rows = []
                for _, row in batch.iterrows():
                    rows.append((
                        row.get('stock_code'), row.get('trade_date'),
                        row.get('tot_mv'), row.get('tot_mv_csrc'),
                        row.get('a_mv'), row.get('a_mv_ex_ltd'),
                        row.get('b_mv'), row.get('b_mv_ex_ltd'),
                        row.get('ev'), row.get('ev_ex_curr'),
                        row.get('ev_ebitda'), row.get('equity_value'),
                    ))
                conn.cursor().executemany('''
                    INSERT OR REPLACE INTO t_stock_mktvalue
                    (stock_code, trade_date, tot_mv, tot_mv_csrc,
                     a_mv, a_mv_ex_ltd, b_mv, b_mv_ex_ltd,
                     ev, ev_ex_curr, ev_ebitda, equity_value)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', rows)
                count += len(rows)

        logger.info(f"插入 {count} 条每日市值指标数据")
        return count

    def get_stock_mktvalue(
        self,
        stock_codes: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """查询每日市值指标数据"""
        sql = 'SELECT * FROM t_stock_mktvalue WHERE 1=1'
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
        sql += ' ORDER BY stock_code, trade_date'
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
            for table in ['t_stock_daily', 't_index_daily', 't_stock_info', 'execution_log', 'best_records',
                          't_stock_in_index', 'portfolio_analysis', 'factor_exposure',
                          't_data_sync', 'valuation_result', 'valuation_summary',
                          'factor_registry', 't_finance_prime', 't_stock_pool', 't_stock_in_stock_pool',
                          't_trading_date', 't_dividend_date', 't_etf_info', 't_etf_daily',
                          't_sector_info', 't_stock_list_in_sector', 't_index_info',
                          't_valuation_data', 't_stock_mktvalue']:
                cursor.execute(f'DELETE FROM {table}')
            logger.info("已清空所有数据")

    # ============ 股票池操作 ============

    def create_t_stock_pool(
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
                    INSERT INTO t_stock_pool (pool_name, pool_code, description)
                    VALUES (?, ?, ?)
                ''', (pool_name, pool_code, description))
                pool_id = cursor.lastrowid
                logger.info(f"创建股票池: {pool_name} (id={pool_id})")
                return pool_id
            except sqlite3.IntegrityError:
                logger.warning(f"股票池已存在: {pool_name}")
                return -1

    def delete_t_stock_pool(self, pool_name: str) -> bool:
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
            cursor.execute('SELECT pool_id FROM t_stock_pool WHERE pool_name = ?', (pool_name,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"股票池不存在: {pool_name}")
                return False

            pool_id = row['pool_id']
            cursor.execute('DELETE FROM t_stock_in_stock_pool WHERE pool_id = ?', (pool_id,))
            cursor.execute('DELETE FROM t_stock_pool WHERE pool_id = ?', (pool_id,))
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
                FROM t_stock_pool p
                LEFT JOIN t_stock_in_stock_pool m ON p.pool_id = m.pool_id AND m.removed_date IS NULL
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
            cursor.execute('SELECT * FROM t_stock_pool WHERE pool_name = ?', (pool_name,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_to_t_stock_pool(
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
            cursor.execute('SELECT pool_id FROM t_stock_pool WHERE pool_name = ?', (pool_name,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"股票池不存在: {pool_name}")
                return 0

            pool_id = row['pool_id']
            count = 0
            for code in stock_codes:
                try:
                    cursor.execute('''
                        INSERT INTO t_stock_in_stock_pool (pool_id, stock_code, added_date)
                        VALUES (?, ?, ?)
                    ''', (pool_id, code.strip(), added_date))
                    count += 1
                except sqlite3.IntegrityError:
                    # 已存在则跳过
                    pass

            logger.info(f"向股票池 {pool_name} 添加 {count} 只股票")
            return count

    def remove_from_t_stock_pool(
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
            cursor.execute('SELECT pool_id FROM t_stock_pool WHERE pool_name = ?', (pool_name,))
            row = cursor.fetchone()
            if not row:
                return 0

            pool_id = row['pool_id']
            placeholders = ','.join(['?' for _ in stock_codes])
            cursor.execute(f'''
                UPDATE t_stock_in_stock_pool
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
            cursor.execute('SELECT pool_id FROM t_stock_pool WHERE pool_name = ?', (pool_name,))
            row = cursor.fetchone()
            if not row:
                return []

            pool_id = row['pool_id']

            if trade_date:
                cursor.execute('''
                    SELECT DISTINCT stock_code FROM t_stock_in_stock_pool
                    WHERE pool_id = ?
                      AND added_date <= ?
                      AND (removed_date IS NULL OR removed_date > ?)
                    ORDER BY stock_code
                ''', (pool_id, trade_date, trade_date))
            else:
                cursor.execute('''
                    SELECT DISTINCT stock_code FROM t_stock_in_stock_pool
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
        pool_id = self.create_t_stock_pool(pool_name, pool_code=index_code, description=description)
        if pool_id == -1:
            # 股票池已存在，直接添加成员
            pool_id = self.get_stock_pool_info(pool_name)['pool_id']

        # 添加成员
        count = self.add_to_t_stock_pool(pool_name, stock_codes)
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

        pool_id = self.create_t_stock_pool(pool_name, description=description)
        if pool_id == -1:
            # 已存在，直接添加
            pass

        return self.add_to_t_stock_pool(pool_name, stock_codes)

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
