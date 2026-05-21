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

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# 因子池定义
FACTOR_POOL = {
    'momentum': [6, 20],
    'mean_reversion': [3, 5],
    'volatility': [7, 8],
    'volume_anomaly': [9, 14],
    'correlation': [10, 12],
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


def calculate_alpha_factor(price_data: pd.DataFrame, factor_id: int) -> pd.Series:
    """
    根据价格数据计算WorldQuant Alpha因子（简化版本）
    
    参数:
        price_data: MultiIndex (trade_date, stock_code) 的价格数据
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
    
    def rank(x):
        """截面排名"""
        return x.groupby(level='trade_date').rank(pct=True)
    
    # 根据factor_id选择计算逻辑
    if factor_id == 3:  # alpha_003: 日内动量
        factor = rank(open_p) * rank(volume)
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
    elif factor_id == 12:  # alpha_012: 开盘收益
        factor = rank(open_p / close.groupby(level='stock_code').shift(1) - 1)
    elif factor_id == 14:  # alpha_014: 收盘价收益
        factor = rank(close / open_p - 1)
    elif factor_id == 20:  # alpha_020: 开盘-收盘价相关性
        factor = -1 * rank(ts_corr(open_p, close, 5))
    else:
        # 默认因子
        factor = rank(close.groupby(level='stock_code').pct_change(5))
    
    return factor


def risk_parity_weights(factors_dict: Dict[str, pd.Series]) -> Dict[str, float]:
    """计算风险平价权重"""
    if not factors_dict:
        return {}
    
    volatilities = {}
    for factor_name, factor_series in factors_dict.items():
        # 计算截面波动率的均值
        daily_std = factor_series.groupby(level='trade_date').std()
        vol = daily_std.mean()
        volatilities[factor_name] = vol if pd.notna(vol) and vol > 0 else 1.0
    
    # 风险平价: weight = (1/vol) / sum(1/vol)
    inv_vols = {k: 1.0 / v for k, v in volatilities.items()}
    total_inv_vol = sum(inv_vols.values())
    weights = {k: v / total_inv_vol for k, v in inv_vols.items()}
    
    return weights


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
                    commission_rate: float = 0.0003) -> pd.DataFrame:
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
    """
    nav = initial_capital
    nav_list = []  # 用 list 比 dict 更省内存

    current_positions = {}  # stock_code -> shares

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
    """多因子分层回测引擎 V2"""
    
    def __init__(self, db_path: str = None, output_dir: str = None, 
                 n_rounds: int = 20, n_stocks: int = 50, 
                 rebalance_freq: int = 5, seed: int = None):
        
        self.db_path = db_path or r'e:\python_space\myquant\data\aquant.db'
        self.output_dir = output_dir or r'e:\python_space\myquant\reports\backtest\quintile'
        self.n_rounds = n_rounds
        self.n_stocks = n_stocks
        self.rebalance_freq = rebalance_freq
        
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        
        # 创建输出目录
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库连接
        from src.data.database import DatabaseManager
        self.db = DatabaseManager(self.db_path)

        # 加载股票基本信息（用于选股过滤：ST、新股判断）
        self.stock_info = self.db.get_stock_info_filtered()
        logger.info(f"股票信息加载完成: {len(self.stock_info)} 只股票")
        
        logger.info(f"初始化多因子分层回测引擎 V2")
        logger.info(f"数据库路径: {self.db_path}")
        logger.info(f"输出目录: {self.output_dir}")
        logger.info(f"回测轮数: {n_rounds}")
    
    def select_random_factors(self, n_factors: int = None) -> List[Tuple[str, int]]:
        """随机选择因子"""
        if n_factors is None:
            n_factors = random.randint(2, 4)
        
        all_factors = []
        for category, factor_ids in FACTOR_POOL.items():
            for fid in factor_ids:
                all_factors.append((category, fid))
        
        selected = random.sample(all_factors, min(n_factors, len(all_factors)))
        return selected
    
    def run_single_round(self, round_id: int) -> Dict:
        """运行单轮回测"""
        logger.info(f"\n{'='*70}")
        logger.info(f"第 {round_id}/{self.n_rounds} 轮回测")
        logger.info(f"{'='*70}")
        
        # 选择因子
        selected_factors = self.select_random_factors()
        logger.info(f"选中因子: {selected_factors}")
        
        round_results = {
            'round_id': round_id,
            'factors': selected_factors,
            'batches': []
        }
        
        # 运行每个批次
        for batch_config in BATCH_CONFIG:
            batch_name = batch_config['name']
            train_start = batch_config['train_start']
            train_end = batch_config['train_end']
            test_start = batch_config['test_start']
            test_end = batch_config['test_end']
            
            logger.info(f"\n  [{batch_name}] 回测期: {train_start}~{train_end}, 验证期: {test_start}~{test_end}")
            
            try:
                # 加载回测期数据（含预热期）
                train_data = load_batch_data(self.db, train_start, train_end)
                if train_data.empty:
                    logger.warning(f"    回测期数据为空，跳过")
                    continue
                
                # 计算因子（使用含预热期的数据）
                factors_dict = {}
                for category, factor_id in selected_factors:
                    factor_name = f"{category}_alpha_{factor_id:03d}"
                    factor_values = calculate_alpha_factor(train_data, factor_id)
                    if not factor_values.empty:
                        factors_dict[factor_name] = factor_values
                
                if not factors_dict:
                    logger.warning(f"    没有有效因子，跳过")
                    del train_data
                    gc.collect()
                    continue
                
                # 计算风险平价权重
                weights = risk_parity_weights(factors_dict)
                logger.info(f"    风险平价权重: {weights}")
                
                # 保存权重到 round_results（只保存第一批次的权重作为代表）
                if not round_results.get('factor_weights'):
                    round_results['factor_weights'] = weights
                
                # 合成因子
                combined_factor = combine_factors(factors_dict, weights)
                
                # 裁剪预热期：只保留正式回测期内的因子值
                formal_start = pd.Timestamp(train_start)
                idx = combined_factor.index.get_level_values('trade_date')
                combined_factor = combined_factor[idx >= formal_start]
                
                # 同时裁剪价格数据到正式回测期
                price_idx = train_data.index.get_level_values('trade_date')
                train_data = train_data[price_idx >= formal_start]
                
                logger.info(f"    裁剪预热期后因子长度: {len(combined_factor)}, 价格数据: {len(train_data)}")
                
                # 5组分层回测（传入stock_info用于选股过滤）
                quintile_results = run_quintile_backtest(
                    combined_factor, train_data, self.stock_info,
                    self.n_stocks, self.rebalance_freq
                )
                
                # 记录结果
                batch_result = {
                    'batch_name': batch_name,
                    'weights': weights,
                    'quintile_performance': {}
                }
                
                for quintile_name, result in quintile_results.items():
                    perf = result.performance
                    batch_result['quintile_performance'][quintile_name] = {
                        'annual_return': perf.get('annual_return', 0),
                        'sharpe_ratio': perf.get('sharpe_ratio', 0),
                        'max_drawdown': perf.get('max_drawdown', 0),
                        'win_rate': perf.get('win_rate', 0),
                    }
                
                round_results['batches'].append(batch_result)
                
                # 内存管理：释放本批次数据
                del train_data
                del factors_dict
                del combined_factor
                del quintile_results
                gc.collect()
                
            except Exception as e:
                logger.error(f"    批次回测失败: {e}")
                import traceback
                traceback.print_exc()
                continue
        
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
        factor_tags = ''.join([f'<span class="factor-tag">{cat}_alpha_{fid:03d}</span>' for cat, fid in factors])
        
        # 构建因子权重图例（在f-string外部生成，避免嵌套问题）
        legend_items = []
        for cat, fid in factors:
            factor_name = f"{cat}_alpha_{fid:03d}"
            weight = factor_weights.get(factor_name, 0)
            color_hash = abs(hash(cat)) % 16777215
            legend_items.append(f'<div class="legend-item"><span class="legend-color" style="background: #{color_hash:06x};"></span><span>{factor_name}: {weight:.2%}</span></div>')
        factor_legend = ''.join(legend_items)
        
        # 计算JavaScript图表数据（在f-string外部生成，避免语法问题）
        js_batch_names = str([b['batch_name'] for b in batches])
        js_q1_returns = str([float(b['quintile_performance'].get('Q1_top', {}).get('annual_return', 0) * 100) for b in batches])
        js_q5_returns = str([float(b['quintile_performance'].get('Q5_bottom', {}).get('annual_return', 0) * 100) for b in batches])
        js_ls_returns = str([float(b['quintile_performance'].get('long_short', {}).get('annual_return', 0) * 100) for b in batches])
        
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
                    <div class="value">{sum(1 for r in monotonicity_results if r['is_monotonic'])}/{len(monotonicity_results)}</div>
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
        
        html_content += f"""
            </table>
            <p style="margin-top: 15px; color: #666;">
                <strong>单调性通过率: {sum(1 for r in monotonicity_results if r['is_monotonic']) / len(monotonicity_results):.1%}</strong>
            </p>
        </div>
        
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
        
        # 热力图数据: 各批次 × 各分组的平均年化收益
        quintile_names = ['Q1_top', 'Q2', 'Q3', 'Q4', 'Q5_bottom']
        quintile_labels = ['Q1(Top)', 'Q2', 'Q3', 'Q4', 'Q5(Bottom)']
        batch_labels = [b['name'] for b in BATCH_CONFIG]
        
        # 重新计算热力图数据（从all_results原始数据）
        heatmap_values = []  # [batch_idx, quintile_idx, value]
        for bi in range(len(BATCH_CONFIG)):
            for qi, qname in enumerate(quintile_names):
                rets = []
                for result in all_results:
                    batches = result.get('batches', [])
                    if bi < len(batches):
                        qp = batches[bi].get('quintile_performance', {})
                        rets.append(float(qp.get(qname, {}).get('annual_return', 0)) * 100)
                avg_val = round(float(np.mean(rets)), 2) if rets else 0
                heatmap_values.append([bi, qi, avg_val])
        
        js_heatmap_data = json.dumps(heatmap_values)
        js_batch_labels = json.dumps(batch_labels)
        js_quintile_labels = json.dumps(quintile_labels)
        
        # 单调性汇总
        total_mono_checks = 0
        total_mono_pass = 0
        batch_mono_stats = {b['name']: {'total': 0, 'pass': 0} for b in BATCH_CONFIG}
        
        for result in all_results:
            for bi, b in enumerate(result.get('batches', [])):
                qp = b.get('quintile_performance', {})
                returns = []
                for i in range(1, 6):
                    qname = f'Q{i}_top' if i == 1 else (f'Q{i}' if i < 5 else 'Q5_bottom')
                    returns.append(float(qp.get(qname, {}).get('annual_return', 0)))
                passed = all(returns[i] >= returns[i+1] for i in range(len(returns)-1))
                total_mono_checks += 1
                if passed:
                    total_mono_pass += 1
                if bi < len(BATCH_CONFIG):
                    bname = BATCH_CONFIG[bi]['name']
                    batch_mono_stats[bname]['total'] += 1
                    batch_mono_stats[bname]['pass'] += 1
        
        total_mono_rate = round(total_mono_pass / total_mono_checks * 100, 1) if total_mono_checks > 0 else 0
        
        # 生成各批次单调性表格行
        mono_table_rows = ""
        for b in BATCH_CONFIG:
            bname = b['name']
            stats = batch_mono_stats[bname]
            rate = round(stats['pass'] / stats['total'] * 100, 1) if stats['total'] > 0 else 0
            mono_table_rows += f"<tr><td>{bname}</td><td>{stats['total']}</td><td>{stats['pass']}</td><td>{rate}%</td></tr>\n"
        
        # 生成各轮次性能对比表行
        perf_table_rows = ""
        for idx, r in enumerate(round_stats):
            rid = r['round_id']
            factors = r['factors']
            factor_str = ', '.join([f"{cat}_alpha_{fid:03d}" for cat, fid in factors])
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
            <h2>各批次分层收益热力图</h2>
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
            <h3 style="color:#666;">按批次统计</h3>
            <table>
                <tr><th>批次</th><th>检验次数</th><th>通过次数</th><th>通过率</th></tr>
                {mono_table_rows}
            </table>
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
        
        // 热力图: 各批次 × 各分组的平均年化收益
        var heatmapChart = echarts.init(document.getElementById('heatmapChart'));
        heatmapChart.setOption({{
            tooltip: {{
                position: 'top',
                formatter: function(params) {{
                    return params.data[2] + '%';
                }}
            }},
            grid: {{ left: '12%', right: '15%', bottom: '10%', top: '5%' }},
            xAxis: {{ type: 'category', data: {js_batch_labels}, splitArea: {{ show: true }} }},
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
