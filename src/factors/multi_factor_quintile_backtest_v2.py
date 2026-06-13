"""
多因子分层回测引擎 V2 - 按需加载数据版本
=============================================

解决内存问题：不按批次加载数据，而不是一次性加载全部

主要功能：
- 20轮多因子组合回测
- 风险平价加权
- 5组分层回测（Q1-Q5及多空组合）
- 每轮生成HTML报告
- 按需加载数据（避免内存溢出）
- 集成实时风控（止损/止盈/仓位限制）

=========================================================================
DEPRECATED — 此引擎自 Phase 5 起标记为 deprecated
-------------------------------------------------------------------------
新项目请使用：
    from src.quantlab_quintile import QuintileExperiment

新 QuintileExperiment 基于 quantlab BarEngine 包装：
    - 5 分位独立回测 + 多空对冲 + IC/IR 计算
    - 复用 quantlab 1 套策略多引擎架构
    - 与 SignalStrategy / RiskCheck 完全兼容
    - 输出更标准的 QuintileResult

迁移示例::

    # 旧
    engine = MultiFactorQuintileBacktestEngineV2(...)
    result = engine.run(...)

    # 新
    exp = QuintileExperiment(n_quantiles=5, rebalance_freq=5)
    result = exp.run(factor_data=factor_df, data=quantlab_dict)

迁移指南见 docs/quantlab_integration_guide.md。
本引擎保留运行用于：
    1) 历史报告回溯查询
    2) Phase 5 迁移期的渐进式过渡
    3) 与新 QuintileExperiment 的等价性回归测试
=========================================================================
"""

import os
import sys
import json
import gc
import random
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# 导入风控控制器
from src.risk import RiskController, RiskAction

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# 因子池定义（扩充版）
# 命名格式: ('wq', id) = WorldQuant Alpha, ('gtj', id) = 国泰君安 Alpha
FACTOR_POOL = {
    # 动量类 - 价格趋势类因子
    'momentum': [
        ('wq', 1), ('wq', 2), ('wq', 3),   # WQ: ts_delta, ts_rank, ts_max相关
        ('wq', 9), ('wq', 10), ('wq', 11), ('wq', 12),  # WQ: 动量/相关性
        ('gtj', 9), ('gtj', 10), ('gtj', 11), ('gtj', 12),  # GTJ: 动量因子
    ],
    # 均值回复类 - 短期反转类因子
    'reversal': [
        ('wq', 4), ('wq', 5), ('wq', 6),   # WQ: 均值回复
        ('gtj', 6), ('gtj', 7), ('gtj', 8),  # GTJ: 均值回复
    ],
    # 波动率类 - 波动率/分散度类因子
    'volatility': [
        ('wq', 7), ('wq', 8), ('wq', 22), ('wq', 23),  # WQ: 波动率
        ('gtj', 13), ('gtj', 14), ('gtj', 15),  # GTJ: 波动率因子
    ],
    # 成交量类 - 成交量异常/资金流类因子
    'volume': [
        ('wq', 13), ('wq', 14), ('wq', 15),  # WQ: 成交量因子
        ('gtj', 24), ('gtj', 25), ('gtj', 26),  # GTJ: 成交量因子
    ],
    # 相关性类 - 与其他标的的相关性类因子
    'correlation': [
        ('wq', 16), ('wq', 17), ('wq', 18),  # WQ: 相关性
        ('gtj', 16), ('gtj', 17), ('gtj', 18),  # GTJ: 相关性
    ],
    # 质量类 - 基本面/价值类因子
    'quality': [
        ('wq', 48), ('wq', 56),  # WQ: 行业中性化因子
        ('gtj', 60), ('gtj', 61),  # GTJ: 质量因子
    ],
    # 趋势强度类 - 趋势跟踪类因子
    'trend': [
        ('wq', 24), ('wq', 25), ('wq', 26),  # WQ: 趋势
        ('gtj', 30), ('gtj', 31), ('gtj', 32),  # GTJ: 趋势强度
    ],
    # 形态类 - K线形态/价格位置类因子
    'pattern': [
        ('wq', 30), ('wq', 31), ('wq', 32),  # WQ: 价格形态
        ('gtj', 43), ('gtj', 44), ('gtj', 45),  # GTJ: K线形态
    ],
}

# 批次定义
BATCH_CONFIG = [
    {'name': 'Batch_1', 'train_start': '2017-01-01', 'train_end': '2019-12-31', 'test_start': '2020-01-01', 'test_end': '2020-12-31'},
    {'name': 'Batch_2', 'train_start': '2018-01-01', 'train_end': '2020-12-31', 'test_start': '2021-01-01', 'test_end': '2021-12-31'},
    {'name': 'Batch_3', 'train_start': '2019-01-01', 'train_end': '2021-12-31', 'test_start': '2022-01-01', 'test_end': '2022-12-31'},
    {'name': 'Batch_4', 'train_start': '2020-01-01', 'train_end': '2022-12-31', 'test_start': '2023-01-01', 'test_end': '2023-12-31'},
    {'name': 'Batch_5', 'train_start': '2021-01-01', 'train_end': '2023-12-31', 'test_start': '2024-01-01', 'test_end': '2024-12-31'},
    {'name': 'Batch_6', 'train_start': '2022-01-01', 'train_end': '2024-12-31', 'test_start': '2025-01-01', 'test_end': '2025-12-31'},
    {'name': 'Batch_7', 'train_start': '2023-01-01', 'train_end': '2025-12-31', 'test_start': '2026-01-01', 'test_end': '2026-05-19'},
]


@dataclass
class BacktestResult:
    """回测结果数据类"""
    portfolio_values: pd.DataFrame = field(default_factory=pd.DataFrame)
    performance: Dict = field(default_factory=dict)
    trade_records: List = field(default_factory=list)


def load_batch_data(db, start_date: str, end_date: str, chunk_size: int = 500000) -> pd.DataFrame:
    """加载指定批次的数据（含250个交易日预热期），分块读取避免OOM"""
    from src.data.database import DatabaseManager

    # 计算预热起始日：向前推约375个自然日（覆盖约250个交易日）
    warmup_start = pd.Timestamp(start_date) - timedelta(days=375)
    warmup_start_str = warmup_start.strftime('%Y-%m-%d')

    logger.info(f"  加载数据: {warmup_start_str} ~ {end_date} (含预热期)")

    # 只查询需要的列，节省内存
    fields = ['close', 'open', 'high', 'low', 'volume', 'pre_close', 'suspend_flag']
    select_cols = ['trade_date', 'stock_code']
    for f in fields:
        if f not in select_cols:
            select_cols.append(f)

    sql = f"SELECT {','.join(select_cols)} FROM stock_daily WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date, stock_code"

    # 分块读取，避免一次性分配大数组导致 OOM
    chunks = []
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, (warmup_start_str, end_date))

        while True:
            rows = cursor.fetchmany(chunk_size)
            if not rows:
                break
            chunk = pd.DataFrame(rows, columns=select_cols)
            chunks.append(chunk)

    if not chunks:
        logger.warning("  数据为空")
        return pd.DataFrame()

    df = pd.concat(chunks, ignore_index=True)
    del chunks
    gc.collect()

    # 转换日期列
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df.set_index(['trade_date', 'stock_code'], inplace=True)

    logger.info(f"  数据加载完成: {len(df)} 条记录")
    return df


def calculate_alpha_factor(price_data: pd.DataFrame, factor_source: str, factor_id: int) -> pd.Series:
    """
    根据价格数据计算Alpha因子（支持WorldQuant和国泰君安）
    
    参数:
        price_data: MultiIndex (trade_date, stock_code) 的价格数据
        factor_source: 'wq' (WorldQuant) 或 'gtj' (国泰君安)
        factor_id: 因子编号
    
    返回:
        factor_values: Series，索引为 (trade_date, stock_code)
    """
    close = price_data['close']
    open_p = price_data['open']
    high = price_data['high']
    low = price_data['low']
    volume = price_data['volume']
    
    # 按股票分组计算
    def ts_corr(x, y, window=10):
        """时间序列相关系数"""
        return x.rolling(window).corr(y)
    
    def ts_rank(x, window=10):
        """时间序列排名"""
        return x.rolling(window).apply(lambda s: pd.Series(s).rank().iloc[-1] / len(s) if len(s) > 0 else 0.5)
    
    def ts_delta(x, window=1):
        """时间序列差分"""
        return x.groupby(level='stock_code').diff(window)
    
    def ts_max(x, window=10):
        """时间序列最大值"""
        return x.groupby(level='stock_code').rolling(window).max().reset_index(level=0, drop=True)
    
    def ts_min(x, window=10):
        """时间序列最小值"""
        return x.groupby(level='stock_code').rolling(window).min().reset_index(level=0, drop=True)
    
    def ts_sum(x, window=10):
        """时间序列求和"""
        return x.groupby(level='stock_code').rolling(window).sum().reset_index(level=0, drop=True)
    
    def rank(x):
        """截面排名"""
        return x.groupby(level='trade_date').rank(pct=True)
    
    # 根据因子来源和编号选择计算逻辑
    if factor_source == 'wq':
        # WorldQuant Alpha 因子
        if factor_id == 1:  # alpha_001: 日内收益排名
            factor = rank(ts_corr(close, volume, 6))
        elif factor_id == 2:  # alpha_002: 开盘-最高相关性
            factor = -1 * rank(ts_corr(open_p, high, 3))
        elif factor_id == 3:  # alpha_003: 日内动量
            factor = rank(open_p) * rank(volume)
        elif factor_id == 4:  # alpha_004: 开盘-最低相关性
            factor = -1 * rank(ts_corr(low, volume, 10))
        elif factor_id == 5:  # alpha_005: 开盘-close相关性
            factor = -1 * rank(ts_corr(open_p, close, 10))
        elif factor_id == 6:  # alpha_006: 开盘-成交量相关性
            factor = -1 * rank(ts_corr(open_p, volume, 10))
        elif factor_id == 7:  # alpha_007: 日内收益
            factor = rank(close - open_p)
        elif factor_id == 8:  # alpha_008: 高低点排名
            factor = -1 * rank(ts_rank(high, 10) - ts_rank(low, 10))
        elif factor_id == 9:  # alpha_009: 成交量变化
            factor = rank(volume - volume.groupby(level='stock_code').shift(1))
        elif factor_id == 10:  # alpha_010: 收益排名
            factor = rank(close.groupby(level='stock_code').pct_change())
        elif factor_id == 11:  # alpha_011: 开盘-最高相关性
            factor = rank(ts_corr(high, volume, 6))
        elif factor_id == 12:  # alpha_012: 开盘收益
            factor = rank(open_p / close.groupby(level='stock_code').shift(1) - 1)
        elif factor_id == 13:  # alpha_013: 成交量-收益相关性
            factor = rank(ts_corr(volume, close.groupby(level='stock_code').pct_change(), 5))
        elif factor_id == 14:  # alpha_014: 收盘价收益
            factor = rank(close / open_p - 1)
        elif factor_id == 15:  # alpha_015: 开盘-最高排名
            factor = rank(high / open_p - 1)
        elif factor_id == 16:  # alpha_016: 收盘-最高相关性
            factor = -1 * rank(ts_corr(close, high, 5))
        elif factor_id == 17:  # alpha_017: 收盘-成交量相关性
            factor = -1 * rank(ts_corr(close, volume, 10))
        elif factor_id == 18:  # alpha_018: 开盘-收盘相关性
            factor = -1 * rank(ts_corr(open_p, close, 5))
        elif factor_id == 22:  # alpha_022: 收益标准差
            factor = -1 * rank(close.groupby(level='stock_code').pct_change().rolling(5).std())
        elif factor_id == 23:  # alpha_023: 收益波动
            factor = rank(close.groupby(level='stock_code').pct_change().rolling(20).std())
        elif factor_id == 24:  # alpha_024: 收盘-开盘趋势
            factor = rank(close - open_p)
        elif factor_id == 25:  # alpha_025: 收益排名趋势
            factor = rank(ts_rank(close.groupby(level='stock_code').pct_change(), 9))
        elif factor_id == 26:  # alpha_026: 最高-最低趋势
            factor = rank(high - low)
        elif factor_id == 30:  # alpha_030: 开盘-最低排名
            factor = rank(open_p - low)
        elif factor_id == 31:  # alpha_031: 收盘-最低排名
            factor = rank(close - low)
        elif factor_id == 32:  # alpha_032: 最高-收盘排名
            factor = rank(high - close)
        elif factor_id == 48:  # alpha_048: 行业中性化收益（简化）
            factor = rank(close.groupby(level='stock_code').pct_change(5))
        elif factor_id == 56:  # alpha_056: 行业中性化波动（简化）
            factor = -1 * rank(close.groupby(level='stock_code').pct_change().rolling(10).std())
        else:
            # 默认因子
            factor = rank(close.groupby(level='stock_code').pct_change(5))
    
    elif factor_source == 'gtj':
        # 国泰君安 Alpha 因子（简化实现）
        if factor_id == 6:  # GTJ_006: 均值回复 - 收益反转
            factor = -1 * rank(close.groupby(level='stock_code').pct_change(5))
        elif factor_id == 7:  # GTJ_007: 均值回复 - 开盘反转
            factor = -1 * rank(open_p / close.groupby(level='stock_code').shift(1) - 1)
        elif factor_id == 8:  # GTJ_008: 均值回复 - 成交量反转
            factor = -1 * rank(volume / volume.groupby(level='stock_code').shift(5))
        elif factor_id == 9:  # GTJ_009: 动量 - 5日收益
            factor = rank(close.groupby(level='stock_code').pct_change(5))
        elif factor_id == 10:  # GTJ_010: 动量 - 10日收益
            factor = rank(close.groupby(level='stock_code').pct_change(10))
        elif factor_id == 11:  # GTJ_011: 动量 - 20日收益
            factor = rank(close.groupby(level='stock_code').pct_change(20))
        elif factor_id == 12:  # GTJ_012: 动量 - 开盘动量
            factor = rank(open_p / close.groupby(level='stock_code').shift(5) - 1)
        elif factor_id == 13:  # GTJ_013: 波动率 - 5日波动
            factor = -1 * rank(close.groupby(level='stock_code').pct_change().rolling(5).std())
        elif factor_id == 14:  # GTJ_014: 波动率 - 10日波动
            factor = -1 * rank(close.groupby(level='stock_code').pct_change().rolling(10).std())
        elif factor_id == 15:  # GTJ_015: 波动率 - 20日波动
            factor = -1 * rank(close.groupby(level='stock_code').pct_change().rolling(20).std())
        elif factor_id == 16:  # GTJ_016: 相关性 - 收益-成交量相关
            factor = rank(ts_corr(close.groupby(level='stock_code').pct_change(), volume, 5))
        elif factor_id == 17:  # GTJ_017: 相关性 - 开盘-收盘相关
            factor = rank(ts_corr(open_p, close, 5))
        elif factor_id == 18:  # GTJ_018: 相关性 - 最高-最低相关
            factor = rank(ts_corr(high, low, 5))
        elif factor_id == 24:  # GTJ_024: 成交量 - 5日成交量均值
            factor = rank(volume.groupby(level='stock_code').rolling(5).mean().reset_index(level=0, drop=True))
        elif factor_id == 25:  # GTJ_025: 成交量 - 10日成交量均值
            factor = rank(volume.groupby(level='stock_code').rolling(10).mean().reset_index(level=0, drop=True))
        elif factor_id == 26:  # GTJ_026: 成交量 - 成交量变化率
            factor = rank(volume / volume.groupby(level='stock_code').shift(5))
        elif factor_id == 30:  # GTJ_030: 趋势 - 5日均线偏离
            factor = rank(close / close.groupby(level='stock_code').rolling(5).mean().reset_index(level=0, drop=True) - 1)
        elif factor_id == 31:  # GTJ_031: 趋势 - 10日均线偏离
            factor = rank(close / close.groupby(level='stock_code').rolling(10).mean().reset_index(level=0, drop=True) - 1)
        elif factor_id == 32:  # GTJ_032: 趋势 - 20日均线偏离
            factor = rank(close / close.groupby(level='stock_code').rolling(20).mean().reset_index(level=0, drop=True) - 1)
        elif factor_id == 43:  # GTJ_043: 形态 - 上影线
            factor = rank((high - close) / (high - low + 1e-10))
        elif factor_id == 44:  # GTJ_044: 形态 - 下影线
            factor = rank((close - low) / (high - low + 1e-10))
        elif factor_id == 45:  # GTJ_045: 形态 - 实体比例
            factor = rank(abs(close - open_p) / (high - low + 1e-10))
        elif factor_id == 60:  # GTJ_060: 质量 - 收益稳定性（简化）
            factor = -1 * rank(close.groupby(level='stock_code').pct_change().rolling(20).std())
        elif factor_id == 61:  # GTJ_061: 质量 - 收益一致性（简化）
            factor = rank(ts_corr(close.groupby(level='stock_code').pct_change(), 
                                  close.groupby(level='stock_code').pct_change().shift(1), 10))
        else:
            # 默认因子
            factor = rank(close.groupby(level='stock_code').pct_change(5))
    else:
        # 未知来源，使用默认因子
        factor = rank(close.groupby(level='stock_code').pct_change(5))
    
    return factor


class FactorSelector:
    """因子选择器 - 支持3种选择模式"""
    
    def __init__(self, factor_pool: dict = None):
        self.factor_pool = factor_pool or FACTOR_POOL
    
    def select(self, mode: str, **kwargs) -> List[Tuple[str, int]]:
        """
        选择因子
        
        Parameters
        ----------
        mode : str
            'category': 每类随机选择
            'specified': 用户指定
            'random': 全随机
        
        Returns
        -------
        List[Tuple[str, int]]: [(factor_source, factor_id), ...]
        """
        if mode == 'category':
            return self._select_by_category(kwargs.get('n_per_category', 1))
        elif mode == 'specified':
            return self._select_by_specified(kwargs.get('factors', []))
        elif mode == 'random':
            return self._select_random(kwargs.get('n_total', 4))
        else:
            raise ValueError(f"Unknown factor mode: {mode}")
    
    def _select_by_category(self, n_per_category: int = 1) -> List[Tuple[str, int]]:
        """从每个类别随机选择N个因子"""
        selected = []
        for category, factors in self.factor_pool.items():
            n = min(n_per_category, len(factors))
            selected.extend(random.sample(factors, n))
        return selected
    
    def _select_by_specified(self, factors: List[str]) -> List[Tuple[str, int]]:
        """根据用户指定的因子列表选择"""
        selected = []
        for f in factors:
            # 解析格式: "wq_001" 或 "gtj_030"
            parts = f.lower().split('_')
            if len(parts) == 2:
                source, fid = parts[0], int(parts[1])
                selected.append((source, fid))
        return selected
    
    def _select_random(self, n_total: int = 4) -> List[Tuple[str, int]]:
        """从所有因子中随机选择N个"""
        all_factors = []
        for factors in self.factor_pool.values():
            all_factors.extend(factors)
        n = min(n_total, len(all_factors))
        return random.sample(all_factors, n)


def calculate_factor_weights(factors_dict: Dict[str, pd.Series], 
                            returns: pd.DataFrame = None,
                            method: str = 'risk_parity') -> Dict[str, float]:
    """
    计算因子权重
    
    Parameters
    ----------
    factors_dict : Dict[str, pd.Series]
        各因子值，键为因子名（如 'wq_001'）
    returns : pd.DataFrame
        收益率数据（IC/IR加权时需要）
    method : str
        'equal': 等权
        'risk_parity': 风险平价（波动率倒数加权）
        'ic_weighted': IC加权
        'ir_weighted': IR加权
    
    Returns
    -------
    Dict[str, float]: {因子名: 权重}
    """
    if not factors_dict:
        return {}
    
    if method == 'equal':
        # 等权
        n = len(factors_dict)
        return {name: 1.0/n for name in factors_dict.keys()}
    
    elif method == 'risk_parity':
        # 风险平价 - 波动率倒数加权
        volatilities = {}
        for factor_name, factor_series in factors_dict.items():
            daily_std = factor_series.groupby(level='trade_date').std()
            vol = daily_std.mean()
            volatilities[factor_name] = vol if pd.notna(vol) and vol > 0 else 1.0
        
        inv_vols = {k: 1.0 / v for k, v in volatilities.items()}
        total_inv_vol = sum(inv_vols.values())
        return {k: v / total_inv_vol for k, v in inv_vols.items()}
    
    elif method == 'ic_weighted':
        # IC加权 - 基于IC均值绝对值
        if returns is None:
            logger.warning("IC加权需要收益率数据，回退到等权")
            n = len(factors_dict)
            return {name: 1.0/n for name in factors_dict.keys()}
        
        ics = {}
        for factor_name, factor_series in factors_dict.items():
            # 计算因子与下期收益的IC
            ic = _calc_ic(factor_series, returns)
            ics[factor_name] = abs(ic) if pd.notna(ic) else 0
        
        total_ic = sum(ics.values())
        if total_ic > 0:
            return {k: v / total_ic for k, v in ics.items()}
        else:
            n = len(factors_dict)
            return {name: 1.0/n for name in factors_dict.keys()}
    
    elif method == 'ir_weighted':
        # IR加权 - 基于IR值
        if returns is None:
            logger.warning("IR加权需要收益率数据，回退到等权")
            n = len(factors_dict)
            return {name: 1.0/n for name in factors_dict.keys()}
        
        irs = {}
        for factor_name, factor_series in factors_dict.items():
            ir = _calc_ir(factor_series, returns)
            irs[factor_name] = abs(ir) if pd.notna(ir) else 0
        
        total_ir = sum(irs.values())
        if total_ir > 0:
            return {k: v / total_ir for k, v in irs.items()}
        else:
            n = len(factors_dict)
            return {name: 1.0/n for name in factors_dict.keys()}
    
    else:
        raise ValueError(f"Unknown weight method: {method}")


def _calc_ic(factor: pd.Series, returns: pd.DataFrame, forward_period: int = 1) -> float:
    """计算因子IC（信息系数）"""
    # 简化实现：计算因子与下期收益的相关系数
    factor_df = factor.reset_index()
    factor_df['next_return'] = returns['close'].pct_change(forward_period).shift(-forward_period).values
    ic = factor_df[factor.name].corr(factor_df['next_return'])
    return ic if pd.notna(ic) else 0


def _calc_ir(factor: pd.Series, returns: pd.DataFrame, forward_period: int = 1) -> float:
    """计算因子IR（信息比率）"""
    # 计算滚动IC的均值/标准差
    factor_df = factor.reset_index()
    factor_df['next_return'] = returns['close'].pct_change(forward_period).shift(-forward_period).values
    
    # 按日期分组计算每日IC
    daily_ic = factor_df.groupby('trade_date').apply(
        lambda x: x[factor.name].corr(x['next_return']) if len(x) > 1 else np.nan
    ).dropna()
    
    if len(daily_ic) > 1:
        return daily_ic.mean() / (daily_ic.std() + 1e-10)
    return 0


def risk_parity_weights(factors_dict: Dict[str, pd.Series]) -> Dict[str, float]:
    """计算风险平价权重（兼容旧代码）"""
    return calculate_factor_weights(factors_dict, method='risk_parity')


def combine_factors(factors_dict: Dict[str, pd.Series], weights: Dict[str, float]) -> pd.Series:
    """按权重合成多因子"""
    if not factors_dict or not weights:
        return pd.Series()
    
    # 对每个因子进行截面标准化
    normalized_factors = {}
    for name, factor in factors_dict.items():
        mean = factor.groupby(level='trade_date').transform('mean')
        std = factor.groupby(level='trade_date').transform('std')
        normalized = (factor - mean) / (std + 1e-8)
        normalized_factors[name] = normalized
    
    # 加权合成
    combined = pd.Series(0.0, index=list(normalized_factors.values())[0].index)
    for name, factor in normalized_factors.items():
        weight = weights.get(name, 0)
        combined += factor * weight
    
    return combined


def _calc_group_nav(holdings: Dict[str, set], close_pivot: pd.DataFrame,
                    trade_dates: list, rebalance_dates_set: set,
                    initial_capital: float = 1000000.0,
                    commission_rate: float = 0.0003,
                    risk_controller: 'RiskController' = None) -> pd.DataFrame:
    """
    计算某个分组的净值曲线。

    在每个调仓日等权买入该组的可交易股票，持有到下一个调仓日。
    返回每日净值 DataFrame（列: date, nav）。

    Parameters
    ----------
    holdings : dict
        {调仓日(timestamp): set(股票代码)} 的映射
    close_pivot : pd.DataFrame
        pivot 表 (trade_date x stock_code) -> close，由外部 unstack 一次
    trade_dates : list
        所有交易日（排序后）
    rebalance_dates_set : set
        调仓日集合（用于快速查找）
    initial_capital : float
        初始资金
    commission_rate : float
        佣金费率
    risk_controller : RiskController, optional
        风控控制器，用于实时监控和执行风控规则
    """
    nav = initial_capital
    nav_list = []  # 用 list 比 dict 更省内存

    current_positions = {}  # stock_code -> shares
    entry_prices = {}  # stock_code -> entry_price (用于风控计算)

    for date in trade_dates:
        if date not in close_pivot.index:
            nav_list.append((date, nav))
            continue

        # 计算当前持仓市值
        position_value = 0.0
        for stock_code, shares in current_positions.items():
            if stock_code in close_pivot.columns:
                price = close_pivot.at[date, stock_code]
                if pd.notna(price) and price > 0:
                    position_value += shares * price

        total_value = nav + position_value
        nav_list.append((date, total_value))

        # 风控检查（非调仓日也检查）
        if risk_controller and current_positions:
            date_str = date.strftime('%Y-%m-%d')

            # 检查组合层面风控
            action, target_position, reason = risk_controller.check_portfolio_risk(
                date_str, total_value, position_value / total_value if total_value > 0 else 0
            )

            if action != RiskAction.NONE:
                # 组合风控触发，清仓或减仓
                if action == RiskAction.CLOSE:
                    for stock_code, shares in list(current_positions.items()):
                        if stock_code in close_pivot.columns:
                            price = close_pivot.at[date, stock_code]
                            if pd.notna(price) and price > 0:
                                sell_value = shares * price
                                commission = sell_value * commission_rate
                                nav += sell_value - commission
                                risk_controller.record_exit(stock_code)
                        del current_positions[stock_code]
                    entry_prices.clear()
                    continue  # 跳过当日调仓

            # 检查个股风控
            for stock_code, shares in list(current_positions.items()):
                if stock_code not in close_pivot.columns:
                    continue

                price = close_pivot.at[date, stock_code]
                if pd.isna(price) or price <= 0:
                    continue

                position_ratio = (shares * price) / total_value if total_value > 0 else 0

                action, target_position, reason = risk_controller.check_stock_risk(
                    date_str, stock_code, price, position_ratio
                )

                if action == RiskAction.CLOSE:
                    # 清仓
                    sell_value = shares * price
                    commission = sell_value * commission_rate
                    nav += sell_value - commission
                    del current_positions[stock_code]
                    entry_prices.pop(stock_code, None)
                    risk_controller.record_exit(stock_code)

                elif action == RiskAction.REDUCE:
                    # 减仓
                    target_shares = int((target_position * total_value / price) / 100) * 100
                    if target_shares < shares:
                        reduce_shares = shares - target_shares
                        sell_value = reduce_shares * price
                        commission = sell_value * commission_rate
                        nav += sell_value - commission
                        current_positions[stock_code] = target_shares

        # 调仓日：换仓
        if date in rebalance_dates_set:
            # 卖出旧持仓
            for stock_code, shares in list(current_positions.items()):
                if stock_code in close_pivot.columns:
                    price = close_pivot.at[date, stock_code]
                    if pd.notna(price) and price > 0:
                        sell_value = shares * price
                        commission = sell_value * commission_rate
                        nav += sell_value - commission
                del current_positions[stock_code]
                risk_controller.record_exit(stock_code) if risk_controller else None
            entry_prices.clear()

            # 买入新持仓
            date_holdings = holdings.get(date)
            if not date_holdings:
                continue

            # 过滤掉当日无价格的股票
            tradable = []
            for sc in date_holdings:
                if sc in close_pivot.columns:
                    price = close_pivot.at[date, sc]
                    if pd.notna(price) and price > 0:
                        tradable.append(sc)

            if not tradable:
                continue

            # 等权分配资金
            capital_per_stock = nav / len(tradable)

            for stock_code in tradable:
                price = close_pivot.at[date, stock_code]
                shares = int(capital_per_stock / price / 100) * 100  # 整手
                if shares > 0:
                    buy_value = shares * price
                    commission = buy_value * commission_rate
                    nav -= buy_value + commission
                    current_positions[stock_code] = shares
                    entry_prices[stock_code] = price
                    # 记录买入成本用于风控
                    if risk_controller:
                        date_str = date.strftime('%Y-%m-%d')
                        risk_controller.record_entry(date_str, stock_code, price, shares * price / (nav + shares * price))

    return pd.DataFrame(nav_list, columns=['date', 'nav'])


def _calc_performance(nav_df: pd.DataFrame) -> Dict:
    """根据净值曲线计算绩效指标"""
    if len(nav_df) < 2:
        return {
            'annual_return': 0.0, 'sharpe_ratio': 0.0, 'max_drawdown': 0.0,
            'total_return': 0.0, 'annual_volatility': 0.0, 'calmar_ratio': 0.0,
            'win_rate': 0.0, 'n_trades': 0
        }

    values = nav_df['nav'].values
    returns = np.diff(values) / values[:-1]

    total_return = values[-1] / values[0] - 1
    n_days = len(values)
    annual_return = (1 + total_return) ** (252 / n_days) - 1
    annual_volatility = np.std(returns) * np.sqrt(252) if len(returns) > 0 else 0.0
    risk_free_rate = 0.03
    sharpe_ratio = (annual_return - risk_free_rate) / annual_volatility if annual_volatility > 0 else 0.0

    # 最大回撤
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd

    win_rate = np.sum(returns > 0) / len(returns) if len(returns) > 0 else 0.0

    return {
        'total_return': total_return,
        'annual_return': annual_return,
        'annual_volatility': annual_volatility,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': -max_dd,
        'calmar_ratio': annual_return / max_dd if max_dd > 0 else 0.0,
        'win_rate': win_rate,
        'n_trades': 0,
    }


def run_quintile_backtest(combined_factor: pd.Series, price_data: pd.DataFrame,
                          stock_info: pd.DataFrame,
                          n_stocks: int = 50, rebalance_freq: int = 5,
                          min_list_days: int = 60) -> Dict[str, BacktestResult]:
    """
    5组分层回测（直接计算净值版）

    将股票按因子得分分为5组，每组20%，分别计算等权组合净值。
    每个调仓日动态分组和选股过滤。
    不依赖 Backtester，直接计算分组净值曲线。
    """
    from src.factors.backtest import Backtester

    results = {}

    # 获取所有交易日并排序
    trade_dates = sorted(combined_factor.index.get_level_values('trade_date').unique())
    rebalance_dates = trade_dates[::rebalance_freq]
    rebalance_dates_set = set(rebalance_dates)

    quintile_names = ['Q1_top', 'Q2', 'Q3', 'Q4', 'Q5_bottom']

    # 每个quintile的持仓记录：{调仓日: set(股票代码)}
    quintile_holdings = {qname: {} for qname in quintile_names}
    # 多空组合持仓：{调仓日: {'long': set(...), 'short': set(...)}}
    long_short_holdings = {}

    # 逐调仓日动态分组
    for date in rebalance_dates:
        # 动态构建当日可选股票集合
        valid_stock_set = Backtester.build_stock_filter(stock_info, date, min_list_days=min_list_days)

        # 获取当日因子截面
        try:
            date_factor = combined_factor.xs(date, level='trade_date')
        except KeyError:
            continue

        if date_factor.empty:
            continue

        # 按因子值降序排序
        sorted_factor = date_factor.sort_values(ascending=False)
        n = len(sorted_factor)
        if n < 5:
            continue

        # 分5组边界
        boundaries = [0, n // 5, 2 * n // 5, 3 * n // 5, 4 * n // 5, n]

        # 获取当日截面数据进行日频过滤
        try:
            daily_price = price_data.xs(date, level='trade_date')
        except KeyError:
            daily_price = pd.DataFrame()

        if not daily_price.empty:
            filtered_daily = Backtester.filter_daily(daily_price)
            tradable_stocks = set(filtered_daily.index)
        else:
            tradable_stocks = set(date_factor.index)

        final_tradable = tradable_stocks & valid_stock_set

        for qi, qname in enumerate(quintile_names):
            group_stocks = sorted_factor.iloc[boundaries[qi]:boundaries[qi + 1]].index
            tradable_in_group = set(s for s in group_stocks if s in final_tradable)
            quintile_holdings[qname][date] = tradable_in_group

        # 多空组合
        top_stocks = set(s for s in sorted_factor.iloc[boundaries[0]:boundaries[1]].index if s in final_tradable)
        bottom_stocks = set(s for s in sorted_factor.iloc[boundaries[4]:boundaries[5]].index if s in final_tradable)
        long_short_holdings[date] = {'long': top_stocks, 'short': bottom_stocks}

    # 预构建 close_pivot（只做一次 unstack，所有分组共用）
    logger.info("    构建 close_pivot...")
    close_pivot = price_data['close'].unstack(level='stock_code')

    # 计算每个quintile的净值曲线
    for qname in quintile_names:
        logger.info(f"    回测 {qname}...")

        nav_df = _calc_group_nav(
            quintile_holdings[qname], close_pivot,
            trade_dates, rebalance_dates_set
        )

        performance = _calc_performance(nav_df)

        results[qname] = BacktestResult(
            portfolio_values=nav_df,
            performance=performance,
            trade_records=[]
        )

    # 多空组合净值曲线
    logger.info("    回测多空组合 (Q1 - Q5)...")

    # 多空组合：Q1做多 + Q5做空
    # 简化处理：分别计算Q1和Q5的净值，多空 = Q1_nav - Q5_nav + initial_capital
    q1_nav = _calc_group_nav(
        quintile_holdings['Q1_top'], close_pivot,
        trade_dates, rebalance_dates_set
    )
    q5_nav = _calc_group_nav(
        quintile_holdings['Q5_bottom'], close_pivot,
        trade_dates, rebalance_dates_set
    )

    if not q1_nav.empty and not q5_nav.empty:
        # 多空组合净值 = 初始资金 + (Q1净值 - 初始资金) - (Q5净值 - 初始资金)
        ls_nav = pd.DataFrame({
            'date': q1_nav['date'],
            'nav': q1_nav['nav'].values - q5_nav['nav'].values + 1000000.0
        })
        ls_performance = _calc_performance(ls_nav)

        results['long_short'] = BacktestResult(
            portfolio_values=ls_nav,
            performance=ls_performance,
            trade_records=[]
        )
    else:
        logger.warning("    多空组合数据为空，跳过")
        results['long_short'] = BacktestResult()

    # 释放内存
    del quintile_holdings
    del long_short_holdings
    del close_pivot
    del q1_nav
    del q5_nav
    gc.collect()

    return results


class MultiFactorQuintileBacktestEngineV2:
    """多因子分层回测引擎 V2 - 重构版

    支持自定义时间段、多种因子选择模式、权重方法和调仓策略

    .. deprecated::
        自 Phase 5 起标记为 deprecated。请使用
        :class:`src.quantlab_quintile.QuintileExperiment`。
        旧版保留用于历史回溯和等价性回归。
    """

    def __init__(self,
                 db_path: str = None,
                 output_dir: str = None,
                 # 时间段参数
                 start_date: str = '2020-01-01',
                 end_date: str = '2024-12-31',
                 # 回测轮数
                 n_rounds: int = 20,
                 n_stocks: int = 50,
                 n_random_factors: int = 4,      # random 模式下随机选择的因子总数
                 # 权重参数
                 weight_method: str = 'risk_parity',  # 'equal', 'risk_parity', 'ic_weighted', 'ir_weighted'
                 # 调仓策略参数
                 rebalance_mode: str = 'fixed_days',  # 'fixed_days', 'calendar'
                 rebalance_price: str = 'close',      # 'close', 'next_open'
                 hold_days: int = 5,                   # fixed_days 模式下持仓天数
                 calendar_freq: str = 'month',         # calendar 模式下: 'week', 'month', 'quarter', 'year'
                 calendar_n: int = 1,                  # calendar 模式下: 第N个交易日
                 # 风控参数
                 enable_risk_control: bool = False,    # 是否启用风控
                 stop_loss: float = 0.07,              # 个股止损比例 (-7%)
                 take_profit: float = 0.20,            # 个股止盈比例 (+20%)
                 portfolio_stop: float = 0.10,         # 组合止损比例 (-10%)
                 max_position_per_stock: float = 0.10, # 单股最大仓位 (10%)
                 risk_action: str = 'close',           # 风控操作: 'close', 'reduce', 'halt'
                 # Phase 5 修复：补回 docstring 引用但缺失的参数
                 factor_mode: str = 'category',
                 factor_per_category: int = 1,
                 specified_factors=None,
                 ):
        # Phase 5: deprecation warning
        import warnings as _w
        _w.warn(
            "MultiFactorQuintileBacktestEngineV2 已废弃（Phase 5），"
            "请迁移到 src.quantlab_quintile.QuintileExperiment。",
            DeprecationWarning,
            stacklevel=2,
        )
        """
        初始化多因子分层回测引擎 V2
            随机种子
        factor_mode : str
            因子选择模式: 'category'(每类选N个), 'specified'(指定因子), 'random'(全随机)
        factor_per_category : int
            category 模式下每类选择的因子数
        specified_factors : List[str]
            specified 模式下指定的因子列表，如 ['wq_1', 'gtj_9']
        n_random_factors : int
            random 模式下随机选择的因子总数
        weight_method : str
            权重计算方法: 'equal', 'risk_parity', 'ic_weighted', 'ir_weighted'
        rebalance_mode : str
            调仓模式: 'fixed_days'(固定天数), 'calendar'(日历模式)
        rebalance_price : str
            调仓价格: 'close'(收盘价), 'next_open'(次日开盘价)
        hold_days : int
            fixed_days 模式下持仓天数
        calendar_freq : str
            calendar 模式下: 'week', 'month', 'quarter', 'year'
        calendar_n : int
            calendar 模式下每月/周/季度/年第N个交易日
        enable_risk_control : bool
            是否启用实时风控，默认False
        stop_loss : float
            个股止损比例，默认0.07（-7%）
        take_profit : float
            个股止盈比例，默认0.20（+20%）
        portfolio_stop : float
            组合止损比例，默认0.10（-10%）
        max_position_per_stock : float
            单只股票最大仓位，默认0.10（10%）
        risk_action : str
            风控触发后的操作：'close'(清仓), 'reduce'(减仓), 'halt'(暂停)
        """
        self.db_path = db_path or r'e:\python_space\myquant\data\aquant.db'
        self.n_rounds = n_rounds
        self.n_stocks = n_stocks

        # 时间段参数（设置默认值）
        self.start_date = start_date or '2017-01-01'
        self.end_date = end_date or datetime.now().strftime('%Y-%m-%d')
        # 计算预热期起始日（向前推375个自然日，约250个交易日）
        self.warmup_start = (pd.Timestamp(self.start_date) - timedelta(days=375)).strftime('%Y-%m-%d')

        # 因子选择参数
        self.factor_mode = factor_mode
        self.factor_per_category = factor_per_category
        self.specified_factors = specified_factors or []
        self.n_random_factors = n_random_factors

        # 权重参数
        self.weight_method = weight_method

        # 调仓策略参数
        self.rebalance_mode = rebalance_mode
        self.rebalance_price = rebalance_price
        self.hold_days = hold_days
        self.calendar_freq = calendar_freq
        self.calendar_n = calendar_n

        # 风控参数
        self.enable_risk_control = enable_risk_control
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.portfolio_stop = portfolio_stop
        self.max_position_per_stock = max_position_per_stock
        self.risk_action = risk_action

        # 初始化风控控制器
        self.risk_controller = None
        if enable_risk_control:
            self.risk_controller = RiskController(
                stop_loss=stop_loss,
                take_profit=take_profit,
                portfolio_stop=portfolio_stop,
                max_position_per_stock=max_position_per_stock,
                risk_action=risk_action,
                enable_stop_loss=True,
                enable_take_profit=True,
                enable_portfolio_stop=True,
                enable_position_limit=True,
            )
            logger.info(f"风控控制器已启用: 止损={stop_loss:.1%}, 止盈={take_profit:.1%}, 组合止损={portfolio_stop:.1%}")
        
        # 生成回测ID（基于时间戳）
        self.backtest_id = f"bt_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 输出目录：在用户指定目录下创建以回测ID命名的子文件夹
        base_output_dir = output_dir or r'e:\python_space\myquant\reports\backtest\quintile'
        self.output_dir = str(Path(base_output_dir) / self.backtest_id)
        
        # Phase 5 fix: seed 不再需要（量化场景中随机性不是核心）
        
        # 创建输出目录
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库连接
        from src.data.database import DatabaseManager
        self.db = DatabaseManager(self.db_path)

        # 加载股票基本信息（用于选股过滤：ST、新股判断）
        self.stock_info = self.db.get_stock_info_filtered()
        logger.info(f"股票信息加载完成: {len(self.stock_info)} 只股票")
        
        # 记录配置信息
        logger.info(f"=" * 70)
        logger.info(f"初始化多因子分层回测引擎 V2")
        logger.info(f"=" * 70)
        logger.info(f"数据库路径: {self.db_path}")
        logger.info(f"输出目录: {self.output_dir}")
        logger.info(f"回测期间: {self.start_date} ~ {self.end_date}")
        logger.info(f"预热期起始: {self.warmup_start}")
        logger.info(f"回测轮数: {n_rounds}")
        logger.info(f"因子选择模式: {factor_mode}")
        if factor_mode == 'category':
            logger.info(f"  每类因子数: {factor_per_category}")
        elif factor_mode == 'specified':
            logger.info(f"  指定因子: {specified_factors}")
        elif factor_mode == 'random':
            logger.info(f"  随机因子数: {n_random_factors}")
        logger.info(f"权重方法: {weight_method}")
        logger.info(f"调仓模式: {rebalance_mode}")
        if rebalance_mode == 'fixed_days':
            logger.info(f"  持仓天数: {hold_days}")
        elif rebalance_mode == 'calendar':
            logger.info(f"  调仓频率: {calendar_freq}, 第 {calendar_n} 个交易日")
        logger.info(f"调仓价格: {rebalance_price}")

        # 风控配置信息
        if enable_risk_control:
            logger.info(f"风控配置: 已启用")
            logger.info(f"  个股止损: {stop_loss:.1%}")
            logger.info(f"  个股止盈: {take_profit:.1%}")
            logger.info(f"  组合止损: {portfolio_stop:.1%}")
            logger.info(f"  单股最大仓位: {max_position_per_stock:.1%}")
            logger.info(f"  风控操作: {risk_action}")
        else:
            logger.info(f"风控配置: 未启用")

        logger.info(f"=" * 70)
    
    def get_rebalance_dates(self, trade_dates: List[pd.Timestamp]) -> List[pd.Timestamp]:
        """
        根据 rebalance_mode 生成调仓日期
        
        Parameters
        ----------
        trade_dates : List[pd.Timestamp]
            所有交易日列表（已排序）
        
        Returns
        -------
        List[pd.Timestamp]: 调仓日期列表
        """
        if trade_dates is None or len(trade_dates) == 0:
            return []
        
        trade_dates = sorted(trade_dates)
        
        if self.rebalance_mode == 'fixed_days':
            # 每 hold_days 个交易日调仓
            return trade_dates[::self.hold_days]
        
        elif self.rebalance_mode == 'calendar':
            # 根据 calendar_freq 和 calendar_n 生成调仓日期
            rebalance_dates = []
            
            if self.calendar_freq == 'week':
                # 每周第N个交易日
                for i in range(0, len(trade_dates), 5):  # 每周约5个交易日
                    idx = i + self.calendar_n - 1
                    if idx < len(trade_dates):
                        rebalance_dates.append(trade_dates[idx])
            
            elif self.calendar_freq == 'month':
                # 每月第N个交易日
                current_month = None
                for date in trade_dates:
                    if date.month != current_month:
                        current_month = date.month
                        month_dates = [d for d in trade_dates if d.month == current_month and d.year == date.year]
                        idx = self.calendar_n - 1
                        if idx < len(month_dates):
                            rebalance_dates.append(month_dates[idx])
            
            elif self.calendar_freq == 'quarter':
                # 每季度第N个交易日
                current_quarter = None
                for date in trade_dates:
                    quarter = (date.month - 1) // 3 + 1
                    if quarter != current_quarter:
                        current_quarter = quarter
                        quarter_dates = [d for d in trade_dates 
                                       if (d.month - 1) // 3 + 1 == current_quarter and d.year == date.year]
                        idx = self.calendar_n - 1
                        if idx < len(quarter_dates):
                            rebalance_dates.append(quarter_dates[idx])
            
            elif self.calendar_freq == 'year':
                # 每年第N个交易日
                current_year = None
                for date in trade_dates:
                    if date.year != current_year:
                        current_year = date.year
                        year_dates = [d for d in trade_dates if d.year == current_year]
                        idx = self.calendar_n - 1
                        if idx < len(year_dates):
                            rebalance_dates.append(year_dates[idx])
            
            return rebalance_dates
        
        else:
            raise ValueError(f"Unknown rebalance mode: {self.rebalance_mode}")
    
    def execute_rebalance(self, 
                         current_positions: Dict[str, int],
                         new_selection: set,
                         price_data: pd.DataFrame,
                         date: pd.Timestamp,
                         nav: float,
                         commission_rate: float = 0.0003) -> Tuple[Dict[str, int], float]:
        """
        执行调仓操作
        
        Parameters
        ----------
        current_positions : Dict[str, int]
            当前持仓 {股票代码: 股数}
        new_selection : set
            新的选股结果
        price_data : pd.DataFrame
            价格数据
        date : pd.Timestamp
            调仓日期
        nav : float
            当前现金
        commission_rate : float
            佣金费率
        
        Returns
        -------
        Tuple[Dict[str, int], float]: (新持仓, 新现金)
        """
        # 确定调仓价格
        if self.rebalance_price == 'close':
            price_col = 'close'
        elif self.rebalance_price == 'next_open':
            price_col = 'open'
        else:
            raise ValueError(f"Unknown rebalance price: {self.rebalance_price}")
        
        # 获取当日价格
        try:
            daily_price = price_data.xs(date, level='trade_date')
        except KeyError:
            logger.warning(f"调仓日 {date} 无价格数据")
            return current_positions, nav
        
        # 卖出不在新选股中的持仓
        positions_to_sell = set(current_positions.keys()) - new_selection
        for stock_code in positions_to_sell:
            if stock_code in daily_price.index:
                price = daily_price.loc[stock_code, price_col]
                if pd.notna(price) and price > 0:
                    shares = current_positions[stock_code]
                    sell_value = shares * price
                    commission = sell_value * commission_rate
                    nav += sell_value - commission
            del current_positions[stock_code]
        
        # 计算需要买入的新股票
        positions_to_keep = set(current_positions.keys()) & new_selection
        new_stocks_to_buy = new_selection - positions_to_keep
        
        if not new_stocks_to_buy:
            return current_positions, nav
        
        # 等权分配资金
        total_positions = len(positions_to_keep) + len(new_stocks_to_buy)
        capital_per_stock = nav / len(new_stocks_to_buy) if new_stocks_to_buy else 0
        
        # 买入新股票
        for stock_code in new_stocks_to_buy:
            if stock_code in daily_price.index:
                price = daily_price.loc[stock_code, price_col]
                if pd.notna(price) and price > 0:
                    shares = int(capital_per_stock / price / 100) * 100  # 整手
                    if shares > 0:
                        buy_value = shares * price
                        commission = buy_value * commission_rate
                        nav -= buy_value + commission
                        current_positions[stock_code] = shares
        
        return current_positions, nav
    
    def _run_quintile_backtest_v2(self, 
                                  combined_factor: pd.Series,
                                  price_data: pd.DataFrame,
                                  rebalance_dates: List[pd.Timestamp],
                                  min_list_days: int = 60) -> Dict[str, BacktestResult]:
        """
        5组分层回测 V2（支持新的调仓策略）
        
        Parameters
        ----------
        combined_factor : pd.Series
            合成因子值
        price_data : pd.DataFrame
            价格数据
        rebalance_dates : List[pd.Timestamp]
            调仓日期列表
        min_list_days : int
            最小上市天数
        
        Returns
        -------
        Dict[str, BacktestResult]: 各分组回测结果
        """
        from src.factors.backtest import Backtester
        
        results = {}
        
        # 获取所有交易日
        trade_dates = sorted(combined_factor.index.get_level_values('trade_date').unique())
        rebalance_dates_set = set(rebalance_dates)
        
        quintile_names = ['Q1_top', 'Q2', 'Q3', 'Q4', 'Q5_bottom']
        
        # 每个quintile的持仓记录：{调仓日: set(股票代码)}
        quintile_holdings = {qname: {} for qname in quintile_names}
        # 多空组合持仓：{调仓日: {'long': set(...), 'short': set(...)}}
        long_short_holdings = {}
        
        # 逐调仓日动态分组
        for date in rebalance_dates:
            # 动态构建当日可选股票集合
            valid_stock_set = Backtester.build_stock_filter(self.stock_info, date, min_list_days=min_list_days)
            
            # 获取当日因子截面
            try:
                date_factor = combined_factor.xs(date, level='trade_date')
            except KeyError:
                continue
            
            if date_factor.empty:
                continue
            
            # 按因子值降序排序
            sorted_factor = date_factor.sort_values(ascending=False)
            n = len(sorted_factor)
            if n < 5:
                continue
            
            # 分5组边界
            boundaries = [0, n // 5, 2 * n // 5, 3 * n // 5, 4 * n // 5, n]
            
            # 获取当日截面数据进行日频过滤
            try:
                daily_price = price_data.xs(date, level='trade_date')
            except KeyError:
                daily_price = pd.DataFrame()
            
            if not daily_price.empty:
                filtered_daily = Backtester.filter_daily(daily_price)
                tradable_stocks = set(filtered_daily.index)
            else:
                tradable_stocks = set(date_factor.index)
            
            final_tradable = tradable_stocks & valid_stock_set
            
            for qi, qname in enumerate(quintile_names):
                group_stocks = sorted_factor.iloc[boundaries[qi]:boundaries[qi + 1]].index
                tradable_in_group = set(s for s in group_stocks if s in final_tradable)
                quintile_holdings[qname][date] = tradable_in_group
            
            # 多空组合
            top_stocks = set(s for s in sorted_factor.iloc[boundaries[0]:boundaries[1]].index if s in final_tradable)
            bottom_stocks = set(s for s in sorted_factor.iloc[boundaries[4]:boundaries[5]].index if s in final_tradable)
            long_short_holdings[date] = {'long': top_stocks, 'short': bottom_stocks}
        
        # 预构建 close_pivot（只做一次 unstack，所有分组共用）
        logger.info("    构建 close_pivot...")
        close_pivot = price_data['close'].unstack(level='stock_code')
        
        # 重置风控控制器（每轮回测开始时）
        if self.risk_controller:
            self.risk_controller.reset()
            logger.info(f"    风控控制器已重置")
        
        # 计算每个quintile的净值曲线
        for qname in quintile_names:
            logger.info(f"    回测 {qname}...")
            
            nav_df = _calc_group_nav(
                quintile_holdings[qname], close_pivot,
                trade_dates, rebalance_dates_set,
                risk_controller=self.risk_controller
            )
            
            performance = _calc_performance(nav_df)
            
            results[qname] = BacktestResult(
                portfolio_values=nav_df,
                performance=performance,
                trade_records=[]
            )
        
        # 多空组合净值曲线
        logger.info("    回测多空组合 (Q1 - Q5)...")
        
        # 多空组合：Q1做多 + Q5做空
        q1_nav = _calc_group_nav(
            quintile_holdings['Q1_top'], close_pivot,
            trade_dates, rebalance_dates_set,
            risk_controller=self.risk_controller
        )
        q5_nav = _calc_group_nav(
            quintile_holdings['Q5_bottom'], close_pivot,
            trade_dates, rebalance_dates_set,
            risk_controller=self.risk_controller
        )
        
        if not q1_nav.empty and not q5_nav.empty:
            # 多空组合净值 = 初始资金 + (Q1净值 - 初始资金) - (Q5净值 - 初始资金)
            ls_nav = pd.DataFrame({
                'date': q1_nav['date'],
                'nav': q1_nav['nav'].values - q5_nav['nav'].values + 1000000.0
            })
            ls_performance = _calc_performance(ls_nav)
            
            results['long_short'] = BacktestResult(
                portfolio_values=ls_nav,
                performance=ls_performance,
                trade_records=[]
            )
        else:
            logger.warning("    多空组合数据为空，跳过")
            results['long_short'] = BacktestResult()
        
        # 收集风控报告（如果启用）
        if self.risk_controller:
            risk_report = self.risk_controller.get_risk_report()
            results['risk_report'] = risk_report
            logger.info(f"    风控事件统计: 总数={risk_report.get('total_events', 0)}")
            events_by_type = risk_report.get('events_by_type', {})
            for event_type, count in events_by_type.items():
                logger.info(f"      - {event_type}: {count}")
        
        # 释放内存
        del quintile_holdings
        del long_short_holdings
        del close_pivot
        del q1_nav
        del q5_nav
        gc.collect()
        
        return results
    
    def select_factors(self) -> List[Tuple[str, int]]:
        """
        根据 factor_mode 选择因子
        
        Returns
        -------
        List[Tuple[str, int]]: [(factor_source, factor_id), ...]
            factor_source: 'wq' 或 'gtj'
            factor_id: 因子编号
        """
        selector = FactorSelector(FACTOR_POOL)
        
        if self.factor_mode == 'category':
            selected = selector.select('category', n_per_category=self.factor_per_category)
        elif self.factor_mode == 'specified':
            selected = selector.select('specified', factors=self.specified_factors)
        elif self.factor_mode == 'random':
            selected = selector.select('random', n_total=self.n_random_factors)
        else:
            raise ValueError(f"Unknown factor mode: {self.factor_mode}")
        
        logger.info(f"选中因子: {selected}")
        return selected
    
    def run_single_round(self, round_id: int) -> Dict:
        """
        运行单轮回测
        
        每轮选择一组因子，在指定时间段内进行分层回测
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"第 {round_id}/{self.n_rounds} 轮回测")
        logger.info(f"{'='*70}")
        
        # 选择因子
        selected_factors = self.select_factors()
        
        round_results = {
            'round_id': round_id,
            'factors': selected_factors,
            'batches': []  # 保持兼容，但只会有一个元素
        }
        
        try:
            # 加载数据（含预热期）
            logger.info(f"加载数据: {self.warmup_start} ~ {self.end_date}")
            price_data = load_batch_data(self.db, self.warmup_start, self.end_date)
            if price_data.empty:
                logger.warning("数据为空，跳过")
                return round_results
            
            # 计算因子（使用含预热期的数据）
            factors_dict = {}
            for source, factor_id in selected_factors:
                factor_name = f"{source}_{factor_id:03d}"
                factor_values = calculate_alpha_factor(price_data, source, factor_id)
                if not factor_values.empty:
                    factors_dict[factor_name] = factor_values
            
            if not factors_dict:
                logger.warning("没有有效因子，跳过")
                del price_data
                gc.collect()
                return round_results
            
            # 计算因子权重
            # 计算收益率用于IC/IR加权
            returns = price_data['close'].unstack(level='stock_code').pct_change()
            weights = calculate_factor_weights(factors_dict, returns, self.weight_method)
            logger.info(f"因子权重 ({self.weight_method}): {weights}")
            
            # 保存权重
            round_results['factor_weights'] = weights
            
            # 合成因子
            combined_factor = combine_factors(factors_dict, weights)
            
            # 裁剪预热期：只保留正式回测期内的因子值
            formal_start = pd.Timestamp(self.start_date)
            idx = combined_factor.index.get_level_values('trade_date')
            combined_factor = combined_factor[idx >= formal_start]
            
            # 同时裁剪价格数据到正式回测期
            price_idx = price_data.index.get_level_values('trade_date')
            price_data = price_data[price_idx >= formal_start]
            
            logger.info(f"裁剪预热期后因子长度: {len(combined_factor)}, 价格数据: {len(price_data)}")
            
            # 生成调仓日期
            trade_dates = sorted(combined_factor.index.get_level_values('trade_date').unique())
            rebalance_dates = self.get_rebalance_dates(trade_dates)
            logger.info(f"调仓日期数量: {len(rebalance_dates)}")
            
            # 5组分层回测（使用新的调仓日期生成逻辑）
            quintile_results = self._run_quintile_backtest_v2(
                combined_factor, price_data, rebalance_dates
            )
            
            # 记录结果
            batch_result = {
                'batch_name': 'SinglePeriod',
                'weights': weights,
                'quintile_performance': {}
            }
            
            # 只处理 BacktestResult 对象，跳过 risk_report 等其他键
            for quintile_name, result in quintile_results.items():
                if quintile_name == 'risk_report':
                    continue
                if not hasattr(result, 'performance'):
                    continue
                perf = result.performance
                batch_result['quintile_performance'][quintile_name] = {
                    'annual_return': perf.get('annual_return', 0),
                    'sharpe_ratio': perf.get('sharpe_ratio', 0),
                    'max_drawdown': perf.get('max_drawdown', 0),
                    'win_rate': perf.get('win_rate', 0),
                }
            
            # 收集风控报告到 batch_result
            if 'risk_report' in quintile_results:
                batch_result['risk_report'] = quintile_results['risk_report']
            
            round_results['batches'].append(batch_result)
            
            # 内存管理
            del price_data
            del factors_dict
            del combined_factor
            del quintile_results
            gc.collect()
            
        except Exception as e:
            logger.error(f"回测失败: {e}")
            import traceback
            traceback.print_exc()
        
        return round_results
    
    def run_all_rounds(self):
        """运行所有回测轮次"""
        logger.info(f"\n{'='*70}")
        logger.info(f"开始运行 {self.n_rounds} 轮多因子分层回测")
        logger.info(f"{'='*70}\n")
        
        all_results = []
        
        for round_id in range(1, self.n_rounds + 1):
            result = self.run_single_round(round_id)
            all_results.append(result)
            
            # 生成单轮报告
            self.generate_round_report(result)
        
        # 生成综合报告
        self.generate_summary_report(all_results)
        
        logger.info(f"\n{'='*70}")
        logger.info(f"所有回测完成！")
        logger.info(f"报告目录: {self.output_dir}")
        logger.info(f"{'='*70}\n")
    
    def _generate_risk_report_section(self, batches: List[Dict]) -> str:
        """生成风控报告 HTML 部分"""
        # 从 batches 中查找风控报告
        risk_report = None
        for batch in batches:
            if 'risk_report' in batch:
                risk_report = batch['risk_report']
                break
        
        if not risk_report or risk_report.get('total_events', 0) == 0:
            return ""
        
        total_events = risk_report.get('total_events', 0)
        events_by_type = risk_report.get('events_by_type', {})
        
        stop_loss_count = events_by_type.get('stop_loss', 0)
        take_profit_count = events_by_type.get('take_profit', 0)
        portfolio_stop_count = events_by_type.get('portfolio_stop', 0)
        position_limit_count = events_by_type.get('position_limit', 0)
        
        # 类型映射和颜色
        type_mapping = {
            'stop_loss': ('止损', '#f44336'),
            'take_profit': ('止盈', '#4caf50'),
            'portfolio_stop': ('组合止损', '#ff9800'),
            'position_limit': ('仓位超限', '#9c27b0'),
        }
        
        action_mapping = {
            'close': '清仓',
            'reduce': '减仓',
            'halt': '暂停交易',
            'none': '无操作'
        }
        
        # 生成事件明细行
        event_rows = ""
        recent_events = risk_report.get('recent_events', [])
        for event in recent_events[:20]:  # 最多显示20条
            date = str(event.get('date', ''))[:10]
            event_type_key = event.get('type', '')
            event_type_name, type_color = type_mapping.get(event_type_key, (event_type_key, '#666'))
            stock = event.get('stock', 'N/A')
            trigger = event.get('trigger', 0)
            action = action_mapping.get(event.get('action', ''), event.get('action', ''))
            reason = event.get('reason', '')
            
            trigger_color = 'color: red;' if trigger < 0 else 'color: green;'
            
            event_rows += f"""
                <tr>
                    <td>{date}</td>
                    <td><span style="background: {type_color}20; color: {type_color}; padding: 2px 8px; border-radius: 4px; font-size: 12px;">{event_type_name}</span></td>
                    <td>{stock}</td>
                    <td style="{trigger_color}">{trigger:.2%}</td>
                    <td>{action}</td>
                    <td style="color: #666; font-size: 12px;">{reason}</td>
                </tr>
            """
        
        # 生成饼图数据
        pie_data = []
        for key, (name, color) in type_mapping.items():
            count = events_by_type.get(key, 0)
            if count > 0:
                pie_data.append(f'{{name: "{name}", value: {count}}}')
        pie_data_str = "[" + ", ".join(pie_data) + "]" if pie_data else "[]"
        
        return f"""
        <div class="section">
            <h2>🛡️ 风控报告</h2>
            <div class="summary-grid">
                <div class="summary-item" style="border-left: 4px solid #f44336;">
                    <div class="value" style="color: #f44336;">{stop_loss_count}</div>
                    <div class="label">止损触发</div>
                </div>
                <div class="summary-item" style="border-left: 4px solid #4caf50;">
                    <div class="value" style="color: #4caf50;">{take_profit_count}</div>
                    <div class="label">止盈触发</div>
                </div>
                <div class="summary-item" style="border-left: 4px solid #ff9800;">
                    <div class="value" style="color: #ff9800;">{portfolio_stop_count}</div>
                    <div class="label">组合止损</div>
                </div>
                <div class="summary-item" style="border-left: 4px solid #9c27b0;">
                    <div class="value" style="color: #9c27b0;">{position_limit_count}</div>
                    <div class="label">仓位超限</div>
                </div>
            </div>
            
            <div style="display: flex; gap: 20px; margin-top: 20px;">
                <div style="flex: 1;">
                    <div id="chart-risk" style="width: 100%; height: 250px;"></div>
                </div>
            </div>
            
            <h3 style="margin-top: 20px;">风控事件明细</h3>
            <table>
                <tr>
                    <th>日期</th>
                    <th>类型</th>
                    <th>股票</th>
                    <th>触发值</th>
                    <th>操作</th>
                    <th>原因</th>
                </tr>
                {event_rows}
            </table>
            <p style="margin-top: 10px; color: #666;">显示前 {min(20, len(recent_events))} 条记录，共 {total_events} 条风控事件</p>
        </div>
        
        <script>
            // 风控事件饼图
            var chartRisk = echarts.init(document.getElementById('chart-risk'));
            chartRisk.setOption({{
                title: {{ text: '风控事件分布', left: 'center' }},
                tooltip: {{ trigger: 'item', formatter: '{{b}}: {{c}} ({{d}}%)' }},
                legend: {{ orient: 'vertical', left: 'left' }},
                series: [{{
                    name: '风控事件',
                    type: 'pie',
                    radius: ['30%', '60%'],
                    data: {pie_data_str},
                    itemStyle: {{
                        color: function(params) {{
                            var colorMap = {{'止损': '#f44336', '止盈': '#4caf50', '组合止损': '#ff9800', '仓位超限': '#9c27b0'}};
                            return colorMap[params.name] || '#666';
                        }}
                    }}
                }}]
            }});
        </script>
        """
    
    def generate_round_report(self, round_result: Dict):
        """生成单轮HTML报告（增强版：净值曲线 + 详细绩效 + 单调性检验）"""
        round_id = round_result['round_id']
        factors = round_result['factors']
        batches = round_result['batches']
        factor_weights = round_result.get('factor_weights', {})
        
        # 计算单调性检验结果
        monotonicity_results = []
        for batch in batches:
            perf = batch['quintile_performance']
            returns = [
                perf.get('Q1_top', {}).get('annual_return', 0),
                perf.get('Q2', {}).get('annual_return', 0),
                perf.get('Q3', {}).get('annual_return', 0),
                perf.get('Q4', {}).get('annual_return', 0),
                perf.get('Q5_bottom', {}).get('annual_return', 0),
            ]
            # 检验是否单调递减 Q1 > Q2 > Q3 > Q4 > Q5
            is_monotonic = all(returns[i] >= returns[i+1] for i in range(4))
            monotonicity_results.append({
                'batch': batch['batch_name'],
                'is_monotonic': is_monotonic,
                'returns': returns
            })
        
        # 计算各批次平均绩效
        avg_perf = self._calc_average_performance(batches)
        
        # 构建HTML内容
        factor_tags = ''.join([f'<span class="factor-tag">{source}_{fid:03d}</span>' for source, fid in factors])
        
        # 构建因子权重图例（在f-string外部生成，避免嵌套问题）
        legend_items = []
        for source, fid in factors:
            factor_name = f"{source}_{fid:03d}"
            weight = factor_weights.get(factor_name, 0)
            color_hash = abs(hash(source)) % 16777215
            legend_items.append(f'<div class="legend-item"><span class="legend-color" style="background: #{color_hash:06x};"></span><span>{factor_name}: {weight:.2%}</span></div>')
        factor_legend = ''.join(legend_items)
        
        # 计算JavaScript图表数据（在f-string外部生成，避免语法问题）
        js_batch_names = str([b['batch_name'] for b in batches])
        js_q1_returns = str([float(b['quintile_performance'].get('Q1_top', {}).get('annual_return', 0) * 100) for b in batches])
        js_q5_returns = str([float(b['quintile_performance'].get('Q5_bottom', {}).get('annual_return', 0) * 100) for b in batches])
        js_ls_returns = str([float(b['quintile_performance'].get('long_short', {}).get('annual_return', 0) * 100) for b in batches])
        
        # 生成风控报告 HTML（在 f-string 之前生成）
        risk_report_html = self._generate_risk_report_section(batches)
        
        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>第{round_id}轮多因子分层回测报告</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 15px; font-size: 24px; }}
        h2 {{ color: #555; margin-top: 35px; border-left: 4px solid #4CAF50; padding-left: 10px; }}
        h3 {{ color: #666; margin-top: 20px; }}
        .section {{ margin: 25px 0; padding: 20px; background: #fafafa; border-radius: 6px; }}
        .factor-section {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
        .factor-tag {{ display: inline-block; background: #2196F3; color: white; padding: 8px 15px; border-radius: 20px; font-size: 13px; font-weight: bold; }}
        .weight-badge {{ background: #FF9800; color: white; padding: 3px 8px; border-radius: 10px; font-size: 11px; margin-left: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 13px; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: center; }}
        th {{ background: #4CAF50; color: white; font-weight: bold; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        tr:hover {{ background: #f0f0f0; }}
        .positive {{ color: #4CAF50; font-weight: bold; }}
        .negative {{ color: #f44336; font-weight: bold; }}
        .neutral {{ color: #666; }}
        .metric-card {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 15px 25px; margin: 8px; border-radius: 8px; text-align: center; min-width: 120px; }}
        .metric-value {{ font-size: 22px; font-weight: bold; }}
        .metric-label {{ font-size: 12px; opacity: 0.9; margin-top: 5px; }}
        .chart-container {{ width: 100%; height: 400px; margin: 20px 0; }}
        .chart-row {{ display: flex; gap: 20px; flex-wrap: wrap; }}
        .chart-box {{ flex: 1; min-width: 400px; }}
        .monotonic-pass {{ background: #e8f5e9 !important; }}
        .monotonic-fail {{ background: #ffebee !important; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
        .summary-item {{ background: white; padding: 15px; border-radius: 6px; border: 1px solid #e0e0e0; text-align: center; }}
        .summary-item .value {{ font-size: 24px; font-weight: bold; color: #333; }}
        .summary-item .label {{ font-size: 12px; color: #666; margin-top: 5px; }}
        .legend {{ display: flex; flex-wrap: wrap; gap: 15px; margin: 10px 0; font-size: 12px; }}
        .legend-item {{ display: flex; align-items: center; gap: 5px; }}
        .legend-color {{ width: 20px; height: 12px; border-radius: 2px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>第{round_id}轮多因子分层回测报告</h1>
        
        <div class="section">
            <h2>📊 因子组合与权重</h2>
            <div class="factor-section">
                {factor_tags}
            </div>
            <div class="legend" style="margin-top: 15px;">
                {factor_legend}
            </div>
        </div>
        
        <div class="section">
            <h2>📈 综合绩效概览</h2>
            <div class="summary-grid">
                <div class="summary-item">
                    <div class="value {'positive' if avg_perf['long_short']['annual_return'] > 0 else 'negative'}">{avg_perf['long_short']['annual_return']:.2%}</div>
                    <div class="label">多空年化收益</div>
                </div>
                <div class="summary-item">
                    <div class="value">{avg_perf['long_short']['sharpe_ratio']:.2f}</div>
                    <div class="label">多空夏普比率</div>
                </div>
                <div class="summary-item">
                    <div class="value">{avg_perf['long_short']['max_drawdown']:.2%}</div>
                    <div class="label">多空最大回撤</div>
                </div>
                <div class="summary-item">
                    <div class="value">{sum(1 for r in monotonicity_results if r['is_monotonic']) if monotonicity_results else 0}/{len(monotonicity_results) if monotonicity_results else 0}</div>
                    <div class="label">单调性通过批次</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>📉 各批次收益对比</h2>
            <div id="chart-returns" class="chart-container"></div>
        </div>
        
        <div class="section">
            <h2>📋 详细绩效表</h2>
            <table>
                <tr>
                    <th>批次</th>
                    <th>分组</th>
                    <th>年化收益</th>
                    <th>夏普比率</th>
                    <th>最大回撤</th>
                    <th>胜率</th>
                    <th>单调性</th>
                </tr>
"""
        
        quintile_names = ['Q1_top', 'Q2', 'Q3', 'Q4', 'Q5_bottom', 'long_short']
        quintile_labels = ['Q1(Top)', 'Q2', 'Q3', 'Q4', 'Q5(Bottom)', '多空组合']
        
        for i, batch in enumerate(batches):
            perf = batch['quintile_performance']
            mono = monotonicity_results[i]
            
            for j, (qname, qlabel) in enumerate(zip(quintile_names, quintile_labels)):
                qperf = perf.get(qname, {})
                ann_ret = qperf.get('annual_return', 0)
                sharpe = qperf.get('sharpe_ratio', 0)
                max_dd = qperf.get('max_drawdown', 0)
                win_rate = qperf.get('win_rate', 0)
                
                # 单调性只显示在Q1行
                mono_cell = ''
                if j == 0:
                    mono_status = '✅ 通过' if mono['is_monotonic'] else '❌ 未通过'
                    mono_class = 'monotonic-pass' if mono['is_monotonic'] else 'monotonic-fail'
                    mono_cell = f'<td rowspan="6" class="{mono_class}">{mono_status}</td>'
                
                html_content += f"""
                <tr>
                    <td>{batch['batch_name'] if j == 0 else ''}</td>
                    <td>{qlabel}</td>
                    <td class="{'positive' if ann_ret > 0 else 'negative' if ann_ret < 0 else 'neutral'}">{ann_ret:.2%}</td>
                    <td class="{'positive' if sharpe > 0 else 'negative' if sharpe < 0 else 'neutral'}">{sharpe:.2f}</td>
                    <td class="negative">{max_dd:.2%}</td>
                    <td>{win_rate:.1%}</td>
                    {mono_cell}
                </tr>
"""
        
        html_content += """
            </table>
        </div>
        
        <div class="section">
            <h2>🔬 单调性分析</h2>
            <p>单调性检验：检验因子得分与收益是否存在单调关系，即 Q1收益 ≥ Q2 ≥ Q3 ≥ Q4 ≥ Q5</p>
            <table>
                <tr>
                    <th>批次</th>
                    <th>Q1</th>
                    <th>Q2</th>
                    <th>Q3</th>
                    <th>Q4</th>
                    <th>Q5</th>
                    <th>单调性</th>
                </tr>
"""
        
        for mono in monotonicity_results:
            row_class = 'monotonic-pass' if mono['is_monotonic'] else 'monotonic-fail'
            html_content += f"""
                <tr class="{row_class}">
                    <td>{mono['batch']}</td>
                    <td class="{'positive' if mono['returns'][0] > 0 else 'negative'}">{mono['returns'][0]:.2%}</td>
                    <td class="{'positive' if mono['returns'][1] > 0 else 'negative'}">{mono['returns'][1]:.2%}</td>
                    <td class="{'positive' if mono['returns'][2] > 0 else 'negative'}">{mono['returns'][2]:.2%}</td>
                    <td class="{'positive' if mono['returns'][3] > 0 else 'negative'}">{mono['returns'][3]:.2%}</td>
                    <td class="{'positive' if mono['returns'][4] > 0 else 'negative'}">{mono['returns'][4]:.2%}</td>
                    <td>{'✅ 通过' if mono['is_monotonic'] else '❌ 未通过'}</td>
                </tr>
"""
        
        mono_pass_rate = sum(1 for r in monotonicity_results if r['is_monotonic']) / len(monotonicity_results) if monotonicity_results else 0
        html_content += f"""
            </table>
            <p style="margin-top: 15px; color: #666;">
                <strong>单调性通过率: {mono_pass_rate:.1%}</strong>
            </p>
        </div>
        
        # 风控报告部分
        {risk_report_html}
        
        <div class="section">
            <h2>📝 回测说明</h2>
            <ul>
                <li><strong>分组方式:</strong> 每个调仓日按因子综合得分将全市场股票分为5组，每组20%</li>
                <li><strong>因子加权:</strong> 风险平价加权（波动率倒数加权）</li>
                <li><strong>调仓频率:</strong> 每5个交易日调仓一次</li>
                <li><strong>选股过滤:</strong> 排除ST、上市不满60天、涨跌停、停牌、零成交量</li>
                <li><strong>多空组合:</strong> 做多Q1 + 做空Q5</li>
                <li><strong>交易成本:</strong> 单边万分之三</li>
            </ul>
        </div>
    </div>
    
    <script>
        // 收益对比柱状图
        var chartReturns = echarts.init(document.getElementById('chart-returns'));
        var batches = {js_batch_names};
        var q1Data = {js_q1_returns};
        var q5Data = {js_q5_returns};
        var lsData = {js_ls_returns};
        
        chartReturns.setOption({{
            title: {{ text: '各批次年化收益对比 (%)', left: 'center' }},
            tooltip: {{ trigger: 'axis' }},
            legend: {{ data: ['Q1(Top)', 'Q5(Bottom)', '多空组合'], top: 30 }},
            grid: {{ left: '3%', right: '4%', bottom: '3%', containLabel: true }},
            xAxis: {{ type: 'category', data: batches }},
            yAxis: {{ type: 'value', axisLabel: {{ formatter: '{{value}}%' }} }},
            series: [
                {{ name: 'Q1(Top)', type: 'bar', data: q1Data, itemStyle: {{ color: '#4CAF50' }} }},
                {{ name: 'Q5(Bottom)', type: 'bar', data: q5Data, itemStyle: {{ color: '#f44336' }} }},
                {{ name: '多空组合', type: 'bar', data: lsData, itemStyle: {{ color: '#2196F3' }} }}
            ]
        }});
    </script>
</body>
</html>
"""
        
        # 保存报告
        report_path = Path(self.output_dir) / f"round_{round_id:03d}.html"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"  单轮报告已生成: {report_path}")
    
    def _calc_average_performance(self, batches: List[Dict]) -> Dict:
        """计算各分组的平均绩效"""
        quintile_names = ['Q1_top', 'Q2', 'Q3', 'Q4', 'Q5_bottom', 'long_short']
        avg_perf = {}
        
        for qname in quintile_names:
            metrics = ['annual_return', 'sharpe_ratio', 'max_drawdown', 'win_rate']
            avg_perf[qname] = {}
            
            for metric in metrics:
                values = [b['quintile_performance'].get(qname, {}).get(metric, 0) for b in batches]
                avg_perf[qname][metric] = np.mean(values) if values else 0
        
        return avg_perf
    
    def _aggregate_stats(self, all_results: List[Dict]) -> List[Dict]:
        """聚合所有轮次的统计数据"""
        round_stats = []
        for result in all_results:
            batches = result['batches']
            if not batches:
                continue
            avg_perf = self._calc_average_performance(batches)
            
            # 计算单调性通过率
            mono_pass_count = 0
            for b in batches:
                qp = b.get('quintile_performance', {})
                returns = []
                for i in range(1, 6):
                    qname = f'Q{i}_top' if i == 1 else (f'Q{i}' if i < 5 else 'Q5_bottom')
                    returns.append(float(qp.get(qname, {}).get('annual_return', 0)))
                # 单调性: Q1 >= Q2 >= Q3 >= Q4 >= Q5
                if all(returns[i] >= returns[i+1] for i in range(len(returns)-1)):
                    mono_pass_count += 1
            
            mono_rate = mono_pass_count / len(batches) if batches else 0
            
            round_stats.append({
                'round_id': result['round_id'],
                'factors': result['factors'],
                'n_batches': len(batches),
                'avg_performance': avg_perf,
                'monotonicity_pass_rate': mono_rate,
            })
        return round_stats
    
    def generate_summary_report(self, all_results: List[Dict]):
        """生成综合HTML报告（增强版）"""
        import json
        
        # 聚合统计数据
        round_stats = self._aggregate_stats(all_results)
        if not round_stats:
            logger.warning("无有效回测结果，跳过summary报告生成")
            return
        
        # 计算总体统计
        total_rounds = len(round_stats)
        total_batches = sum(r['n_batches'] for r in round_stats)
        
        avg_ls_return = float(np.mean([r['avg_performance']['long_short']['annual_return'] for r in round_stats])) * 100
        avg_ls_sharpe = float(np.mean([r['avg_performance']['long_short']['sharpe_ratio'] for r in round_stats]))
        avg_ls_drawdown = float(np.mean([r['avg_performance']['long_short']['max_drawdown'] for r in round_stats])) * 100
        avg_mono_rate = float(np.mean([r['monotonicity_pass_rate'] for r in round_stats])) * 100
        
        # 找最佳/最差轮次（按多空年化收益）
        best_idx = max(range(len(round_stats)), key=lambda i: round_stats[i]['avg_performance']['long_short']['annual_return'])
        worst_idx = min(range(len(round_stats)), key=lambda i: round_stats[i]['avg_performance']['long_short']['annual_return'])
        
        # 预计算JavaScript图表数据（避免f-string嵌套问题）
        js_round_labels = json.dumps([f"第{r['round_id']}轮" for r in round_stats])
        js_q1_data = json.dumps([round(float(r['avg_performance']['Q1_top']['annual_return']) * 100, 2) for r in round_stats])
        js_q5_data = json.dumps([round(float(r['avg_performance']['Q5_bottom']['annual_return']) * 100, 2) for r in round_stats])
        js_ls_data = json.dumps([round(float(r['avg_performance']['long_short']['annual_return']) * 100, 2) for r in round_stats])
        
        # 分组名称
        quintile_names = ['Q1_top', 'Q2', 'Q3', 'Q4', 'Q5_bottom']
        quintile_labels = ['Q1(Top)', 'Q2', 'Q3', 'Q4', 'Q5(Bottom)']
        
        # 计算各分组在各轮次中的平均年化收益（用于热力图）
        # 行：轮次，列：分组
        heatmap_values = []  # [round_idx, quintile_idx, value]
        for ri, result in enumerate(all_results):
            batches = result.get('batches', [])
            if batches:
                qp = batches[0].get('quintile_performance', {})
                for qi, qname in enumerate(quintile_names):
                    ret = float(qp.get(qname, {}).get('annual_return', 0)) * 100
                    heatmap_values.append([ri, qi, round(ret, 2)])
        
        js_heatmap_data = json.dumps(heatmap_values)
        js_round_labels_for_heatmap = json.dumps([f"第{r['round_id']}轮" for r in round_stats])
        js_quintile_labels = json.dumps(quintile_labels)
        
        # 单调性汇总
        total_mono_checks = 0
        total_mono_pass = 0
        
        for result in all_results:
            for b in result.get('batches', []):
                qp = b.get('quintile_performance', {})
                returns = []
                for i in range(1, 6):
                    qname = f'Q{i}_top' if i == 1 else (f'Q{i}' if i < 5 else 'Q5_bottom')
                    returns.append(float(qp.get(qname, {}).get('annual_return', 0)))
                passed = all(returns[i] >= returns[i+1] for i in range(len(returns)-1))
                total_mono_checks += 1
                if passed:
                    total_mono_pass += 1
        
        total_mono_rate = round(total_mono_pass / total_mono_checks * 100, 1) if total_mono_checks > 0 else 0
        
        # 生成各轮次性能对比表行
        perf_table_rows = ""
        for idx, r in enumerate(round_stats):
            rid = r['round_id']
            factors = r['factors']
            factor_str = ', '.join([f"{source}_{fid:03d}" for source, fid in factors])
            q1_ret = round(float(r['avg_performance']['Q1_top']['annual_return']) * 100, 2)
            q5_ret = round(float(r['avg_performance']['Q5_bottom']['annual_return']) * 100, 2)
            ls_ret = round(float(r['avg_performance']['long_short']['annual_return']) * 100, 2)
            ls_sharpe = round(float(r['avg_performance']['long_short']['sharpe_ratio']), 2)
            ls_dd = round(float(r['avg_performance']['long_short']['max_drawdown']) * 100, 2)
            mono_rate = round(r['monotonicity_pass_rate'] * 100, 1)
            
            bg_style = ""
            if idx == best_idx:
                bg_style = ' style="background-color: #e8f5e9;"'
            elif idx == worst_idx:
                bg_style = ' style="background-color: #ffebee;"'
            
            perf_table_rows += f"""<tr{bg_style}>
            <td>第{rid}轮</td>
            <td style="font-size:12px;">{factor_str}</td>
            <td>{q1_ret}%</td>
            <td>{q5_ret}%</td>
            <td>{ls_ret}%</td>
            <td>{ls_sharpe}</td>
            <td>{ls_dd}%</td>
            <td>{mono_rate}%</td>
        </tr>\n"""
        
        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>多因子分层回测综合报告</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; border-left: 4px solid #4CAF50; padding-left: 10px; margin-top: 30px; }}
        .cards {{ display: flex; flex-wrap: wrap; gap: 15px; margin: 20px 0; }}
        .card {{ flex: 1; min-width: 180px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        .card.green {{ background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); }}
        .card.blue {{ background: linear-gradient(135deg, #2196F3 0%, #1976D2 100%); }}
        .card.orange {{ background: linear-gradient(135deg, #FF9800 0%, #F57C00 100%); }}
        .card.red {{ background: linear-gradient(135deg, #f44336 0%, #d32f2f 100%); }}
        .card-value {{ font-size: 28px; font-weight: bold; }}
        .card-label {{ font-size: 13px; opacity: 0.9; margin-top: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: center; font-size: 13px; }}
        th {{ background: #4CAF50; color: white; font-weight: bold; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        tr:hover {{ background: #e8f5e9; }}
        .chart-container {{ width: 100%; height: 400px; margin: 20px 0; border: 1px solid #eee; border-radius: 8px; }}
        .heatmap-container {{ width: 100%; height: 350px; margin: 20px 0; border: 1px solid #eee; border-radius: 8px; }}
        .section {{ margin: 25px 0; }}
        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; color: white; }}
        .badge-best {{ background: #4CAF50; }}
        .badge-worst {{ background: #f44336; }}
        .legend {{ margin-top: 5px; font-size: 12px; color: #888; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 多因子分层回测综合报告</h1>
        <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 回测引擎: V2 (风险平价加权)</p>
        
        <div class="section">
            <h2>总体统计</h2>
            <div class="cards">
                <div class="card">
                    <div class="card-value">{total_rounds}</div>
                    <div class="card-label">总轮数</div>
                </div>
                <div class="card blue">
                    <div class="card-value">{total_batches}</div>
                    <div class="card-label">总批次数</div>
                </div>
                <div class="card green">
                    <div class="card-value">{avg_ls_return:.2f}%</div>
                    <div class="card-label">平均多空年化收益</div>
                </div>
                <div class="card green">
                    <div class="card-value">{avg_ls_sharpe:.2f}</div>
                    <div class="card-label">平均多空夏普比率</div>
                </div>
                <div class="card red">
                    <div class="card-value">{avg_ls_drawdown:.2f}%</div>
                    <div class="card-label">平均最大回撤</div>
                </div>
                <div class="card orange">
                    <div class="card-value">{avg_mono_rate:.1f}%</div>
                    <div class="card-label">单调性总通过率</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>各轮次收益对比</h2>
            <div id="barChart" class="chart-container"></div>
        </div>
        
        <div class="section">
            <h2>各轮次分层收益热力图</h2>
            <div id="heatmapChart" class="heatmap-container"></div>
            <p class="legend">颜色说明: 绿色=正收益, 红色=负收益, 颜色越深绝对值越大</p>
        </div>
        
        <div class="section">
            <h2>各轮次性能对比</h2>
            <table>
                <tr>
                    <th>轮次</th>
                    <th>因子组合</th>
                    <th>Q1年化(%)</th>
                    <th>Q5年化(%)</th>
                    <th>多空年化(%)</th>
                    <th>多空夏普</th>
                    <th>最大回撤(%)</th>
                    <th>单调性通过率</th>
                </tr>
                {perf_table_rows}
            </table>
            <p class="legend">
                <span class="badge badge-best">最佳</span> = 多空年化收益最高 
                <span class="badge badge-worst" style="margin-left:10px;">最差</span> = 多空年化收益最低
            </p>
        </div>
        
        <div class="section">
            <h2>单调性检验汇总</h2>
            <p>单调性定义: Q1(Top) ≥ Q2 ≥ Q3 ≥ Q4 ≥ Q5(Bottom) 年化收益递减</p>
            <div class="cards" style="margin-bottom:15px;">
                <div class="card">
                    <div class="card-value">{total_mono_checks}</div>
                    <div class="card-label">总检验次数</div>
                </div>
                <div class="card green">
                    <div class="card-value">{total_mono_pass}</div>
                    <div class="card-label">通过次数</div>
                </div>
                <div class="card orange">
                    <div class="card-value">{total_mono_rate}%</div>
                    <div class="card-label">总通过率</div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // 柱状图: 各轮次Q1/Q5/多空收益对比
        var barChart = echarts.init(document.getElementById('barChart'));
        barChart.setOption({{
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'shadow' }} }},
            legend: {{ data: ['Q1(Top)', 'Q5(Bottom)', '多空组合'], top: 5 }},
            grid: {{ left: '3%', right: '4%', bottom: '3%', containLabel: true }},
            xAxis: {{ type: 'category', data: {js_round_labels} }},
            yAxis: {{ type: 'value', name: '年化收益(%)', axisLabel: {{ formatter: '{{value}}%' }} }},
            series: [
                {{ name: 'Q1(Top)', type: 'bar', data: {js_q1_data}, itemStyle: {{ color: '#4CAF50' }} }},
                {{ name: 'Q5(Bottom)', type: 'bar', data: {js_q5_data}, itemStyle: {{ color: '#f44336' }} }},
                {{ name: '多空组合', type: 'bar', data: {js_ls_data}, itemStyle: {{ color: '#2196F3' }} }}
            ]
        }});
        
        // 热力图: 各轮次 × 各分组的年化收益
        var heatmapChart = echarts.init(document.getElementById('heatmapChart'));
        heatmapChart.setOption({{
            tooltip: {{
                position: 'top',
                formatter: function(params) {{
                    return params.data[2] + '%';
                }}
            }},
            grid: {{ left: '12%', right: '15%', bottom: '10%', top: '5%' }},
            xAxis: {{ type: 'category', data: {js_round_labels_for_heatmap}, splitArea: {{ show: true }} }},
            yAxis: {{ type: 'category', data: {js_quintile_labels}, splitArea: {{ show: true }} }},
            visualMap: {{
                min: -30, max: 30, calculable: true, orient: 'vertical', right: '2%', top: 'center',
                inRange: {{
                    color: ['#d32f2f', '#ffcdd2', '#ffffff', '#c8e6c9', '#2e7d32']
                }},
                text: ['正收益', '负收益']
            }},
            series: [{{
                name: '年化收益',
                type: 'heatmap',
                data: {js_heatmap_data},
                label: {{ show: true, formatter: function(p) {{ return p.data[2] + '%'; }} }},
                emphasis: {{ itemStyle: {{ shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' }} }}
            }}]
        }});
        
        // 窗口大小变化时自适应
        window.addEventListener('resize', function() {{
            barChart.resize();
            heatmapChart.resize();
        }});
    </script>
</body>
</html>"""
        
        # 保存报告
        report_path = Path(self.output_dir) / "summary.html"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"综合报告已生成: {report_path}")


if __name__ == '__main__':
    import sys
    sys.path.insert(0, r'e:\python_space\myquant')
    
    engine = MultiFactorQuintileBacktestEngineV2(seed=42)
    engine.run_all_rounds()
