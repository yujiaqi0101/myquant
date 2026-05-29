"""
多因子分层回测引擎
==================

实现20轮多因子组合的分层回测，每轮包含7个滚动批次，
使用风险平价加权合成因子，进行5组分层回测。

主要功能：
- 风险平价权重计算
- 多因子合成
- 5组分层回测（Q1-Q5及多空组合）
- 生成HTML报告

作者: AI Assistant
日期: 2026-05-20
"""

import os
import sys
import json
import random
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Line, Bar, Grid, Page
from pyecharts.commons.utils import JsCode

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 因子池定义
FACTOR_POOL = {
    'momentum': [6, 20],           # alpha_006, alpha_020
    'mean_reversion': [3, 5],      # alpha_003, alpha_005
    'volatility': [7, 8],          # alpha_007, alpha_008
    'volume_anomaly': [9, 14],     # alpha_009, alpha_014
    'correlation': [10, 12],       # alpha_010, alpha_012
}

# 批次定义（回测期/验证期）
BATCH_CONFIG = [
    {'name': 'Batch_1', 'train_start': '2017-01-01', 'train_end': '2019-12-31', 'test_start': '2020-01-01', 'test_end': '2020-12-31'},
    {'name': 'Batch_2', 'train_start': '2018-01-01', 'train_end': '2020-12-31', 'test_start': '2021-01-01', 'test_end': '2021-12-31'},
    {'name': 'Batch_3', 'train_start': '2019-01-01', 'train_end': '2021-12-31', 'test_start': '2022-01-01', 'test_end': '2022-12-31'},
    {'name': 'Batch_4', 'train_start': '2020-01-01', 'train_end': '2022-12-31', 'test_start': '2023-01-01', 'test_end': '2023-12-31'},
    {'name': 'Batch_5', 'train_start': '2021-01-01', 'train_end': '2023-12-31', 'test_start': '2024-01-01', 'test_end': '2024-12-31'},
    {'name': 'Batch_6', 'train_start': '2022-01-01', 'train_end': '2024-12-31', 'test_start': '2025-01-01', 'test_end': '2025-12-31'},
    {'name': 'Batch_7', 'train_start': '2023-01-01', 'train_end': '2025-12-31', 'test_start': '2026-01-01', 'test_end': '2026-12-31'},
]


@dataclass
class BacktestResult:
    """回测结果数据类"""
    portfolio_values: pd.DataFrame = field(default_factory=pd.DataFrame)
    performance: Dict = field(default_factory=dict)
    trade_records: List = field(default_factory=list)
    quintile_returns: Dict = field(default_factory=dict)  # 各分组的收益序列


@dataclass
class RoundResult:
    """单轮回测结果"""
    round_id: int
    factors: List[Tuple[str, int]]  # [(category, factor_id), ...]
    weights: Dict[str, float]
    batch_results: List[Dict]  # 7个批次的结果
    quintile_results: Dict[str, BacktestResult]  # 5组分层回测结果


def risk_parity_weights(factors_dict: Dict[str, pd.Series], price_data: pd.DataFrame) -> Dict[str, float]:
    """
    计算风险平价权重
    
    参数:
        factors_dict: {factor_name: factor_series}，因子值序列，索引为 (trade_date, stock_code)
        price_data: MultiIndex (trade_date, stock_code) 的价格数据
    
    返回:
        weights: {factor_name: weight}，权重和为1
    """
    if not factors_dict:
        return {}
    
    volatilities = {}
    
    for factor_name, factor_series in factors_dict.items():
        try:
            # 按日期分组计算截面标准差的均值
            daily_std = factor_series.groupby(level='trade_date').std()
            avg_volatility = daily_std.mean()
            
            # 处理异常值
            if pd.isna(avg_volatility) or avg_volatility <= 0:
                avg_volatility = 1e-6
            
            volatilities[factor_name] = avg_volatility
        except Exception as e:
            logger.warning(f"计算因子 {factor_name} 波动率时出错: {e}")
            volatilities[factor_name] = 1e-6
    
    # 风险平价公式: weight_i = (1/vol_i) / sum(1/vol_j)
    inv_vols = {name: 1.0 / vol for name, vol in volatilities.items()}
    total_inv_vol = sum(inv_vols.values())
    
    if total_inv_vol <= 0:
        # 如果总和为0，使用等权重
        n = len(factors_dict)
        weights = {name: 1.0 / n for name in factors_dict.keys()}
    else:
        weights = {name: inv_vol / total_inv_vol for name, inv_vol in inv_vols.items()}
    
    return weights


def combine_factors(factors_dict: Dict[str, pd.Series], weights: Dict[str, float]) -> pd.Series:
    """
    按权重合成多因子得分
    
    参数:
        factors_dict: {factor_name: factor_series}
        weights: {factor_name: weight}
    
    返回:
        合成后的因子Series
    """
    if not factors_dict:
        raise ValueError("因子字典为空")
    
    # 标准化每个因子（截面z-score）
    normalized_factors = {}
    for name, factor in factors_dict.items():
        # 按日期分组标准化
        normalized = factor.groupby(level='trade_date').transform(
            lambda x: (x - x.mean()) / (x.std() + 1e-10) if x.std() > 0 else x - x.mean()
        )
        normalized_factors[name] = normalized
    
    # 加权合成
    combined = None
    for name, factor in normalized_factors.items():
        weight = weights.get(name, 0)
        if combined is None:
            combined = factor * weight
        else:
            combined = combined + factor * weight
    
    return combined


def run_quintile_backtest(
    combined_factor: pd.Series,
    price_data: pd.DataFrame,
    n_stocks: int = 50,
    rebalance_freq: int = 5,
    initial_capital: float = 1000000
) -> Dict[str, Dict]:
    """
    5组分层回测
    
    将股票按因子得分分为5组（每组20%），分别回测
    
    参数:
        combined_factor: 合成后的因子值，索引为 (trade_date, stock_code)
        price_data: 价格数据，MultiIndex (trade_date, stock_code)
        n_stocks: 每组持仓股票数量
        rebalance_freq: 调仓频率（交易日）
        initial_capital: 初始资金
    
    返回:
        {
            'Q1_top': backtest_result,      # 得分最高的20%
            'Q2': backtest_result,
            'Q3': backtest_result,
            'Q4': backtest_result,
            'Q5_bottom': backtest_result,   # 得分最低的20%
            'long_short': backtest_result,  # Q1 - Q5 多空组合
        }
    """
    from .backtest import Backtester
    
    results = {}
    
    # 获取交易日列表
    trade_dates = combined_factor.index.get_level_values('trade_date').unique().sort_values()
    
    # 为每个分组创建回测器
    quintile_names = ['Q1_top', 'Q2', 'Q3', 'Q4', 'Q5_bottom']
    
    for quintile_name in quintile_names:
        bt = Backtester(initial_capital=initial_capital)
        bt.load_data(price_data)
        
        # 根据分组筛选因子
        quintile_factor = pd.Series(index=combined_factor.index, dtype=float)
        
        for date in trade_dates:
            try:
                daily_factor = combined_factor.xs(date, level='trade_date')
                
                # 按因子值排序并分5组
                sorted_factor = daily_factor.sort_values(ascending=False)
                n = len(sorted_factor)
                
                if n < 5:
                    continue
                
                # 计算分组边界
                q1_end = int(n * 0.2)
                q2_end = int(n * 0.4)
                q3_end = int(n * 0.6)
                q4_end = int(n * 0.8)
                
                # 根据当前分组选择股票
                if quintile_name == 'Q1_top':
                    selected = sorted_factor.iloc[:q1_end]
                elif quintile_name == 'Q2':
                    selected = sorted_factor.iloc[q1_end:q2_end]
                elif quintile_name == 'Q3':
                    selected = sorted_factor.iloc[q2_end:q3_end]
                elif quintile_name == 'Q4':
                    selected = sorted_factor.iloc[q3_end:q4_end]
                else:  # Q5_bottom
                    selected = sorted_factor.iloc[q4_end:]
                
                # 将该分组的因子值设为原始值，其他设为NaN
                daily_quartile = pd.Series(np.nan, index=daily_factor.index)
                daily_quartile[selected.index] = selected.values
                
                # 赋值回总序列
                for stock_code in daily_quartile.index:
                    quintile_factor.loc[(date, stock_code)] = daily_quartile[stock_code]
                    
            except Exception as e:
                logger.debug(f"处理日期 {date} 时出错: {e}")
                continue
        
        # 运行回测
        try:
            result = bt.run_backtest(quintile_factor, n_stocks=n_stocks, rebalance_freq=rebalance_freq)
            results[quintile_name] = result
        except Exception as e:
            logger.error(f"回测 {quintile_name} 时出错: {e}")
            results[quintile_name] = {'portfolio_values': pd.DataFrame(), 'performance': {}, 'trade_records': []}
    
    # 多空组合回测（Q1 - Q5）
    try:
        bt_ls = Backtester(initial_capital=initial_capital)
        bt_ls.load_data(price_data)
        
        # 构建多空因子：Q1做多，Q5做空
        long_short_factor = pd.Series(index=combined_factor.index, dtype=float)
        
        for date in trade_dates:
            try:
                daily_factor = combined_factor.xs(date, level='trade_date')
                sorted_factor = daily_factor.sort_values(ascending=False)
                n = len(sorted_factor)
                
                if n < 10:
                    continue
                
                q1_end = int(n * 0.2)
                q4_end = int(n * 0.8)
                
                # Q1做多（高因子值），Q5做空（低因子值）
                daily_ls = pd.Series(np.nan, index=daily_factor.index)
                daily_ls[sorted_factor.iloc[:q1_end].index] = sorted_factor.iloc[:q1_end].values
                daily_ls[sorted_factor.iloc[q4_end:].index] = -sorted_factor.iloc[q4_end:].values
                
                for stock_code in daily_ls.index:
                    if not pd.isna(daily_ls[stock_code]):
                        long_short_factor.loc[(date, stock_code)] = daily_ls[stock_code]
                        
            except Exception as e:
                logger.debug(f"处理多空组合日期 {date} 时出错: {e}")
                continue
        
        result_ls = bt_ls.run_backtest(long_short_factor, n_stocks=n_stocks, rebalance_freq=rebalance_freq, long_short=True)
        results['long_short'] = result_ls
    except Exception as e:
        logger.error(f"多空组合回测时出错: {e}")
        results['long_short'] = {'portfolio_values': pd.DataFrame(), 'performance': {}, 'trade_records': []}
    
    return results


def calculate_performance_metrics(portfolio_values: pd.DataFrame) -> Dict:
    """
    计算绩效指标
    
    参数:
        portfolio_values: 包含 'value' 列的DataFrame
    
    返回:
        绩效指标字典
    """
    if portfolio_values.empty or 'value' not in portfolio_values.columns:
        return {
            'total_return': 0,
            'annual_return': 0,
            'annual_volatility': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'calmar_ratio': 0,
        }
    
    values = portfolio_values['value'].values
    
    if len(values) < 2:
        return {
            'total_return': 0,
            'annual_return': 0,
            'annual_volatility': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'calmar_ratio': 0,
        }
    
    returns = np.diff(values) / values[:-1]
    
    # 总收益
    total_return = values[-1] / values[0] - 1
    
    # 年化收益
    n_days = len(values)
    annual_return = (1 + total_return) ** (252 / n_days) - 1
    
    # 年化波动率
    annual_volatility = np.std(returns) * np.sqrt(252)
    
    # 夏普比率
    risk_free_rate = 0.03
    sharpe_ratio = (annual_return - risk_free_rate) / annual_volatility if annual_volatility > 0 else 0
    
    # 最大回撤
    peak = np.maximum.accumulate(values)
    max_drawdown = np.min((values - peak) / peak)
    
    # 卡玛比率
    calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0
    
    return {
        'total_return': total_return,
        'annual_return': annual_return,
        'annual_volatility': annual_volatility,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'calmar_ratio': calmar_ratio,
    }


def check_monotonicity(quintile_results: Dict[str, Dict]) -> Tuple[bool, List[float]]:
    """
    检查分层单调性（Q1收益 > Q2 > Q3 > Q4 > Q5）
    
    参数:
        quintile_results: 5组分层回测结果
    
    返回:
        (是否单调, 各组年化收益列表)
    """
    returns = []
    for name in ['Q1_top', 'Q2', 'Q3', 'Q4', 'Q5_bottom']:
        if name in quintile_results:
            perf = quintile_results[name].get('performance', {})
            annual_return = perf.get('annual_return', 0)
            returns.append(annual_return)
        else:
            returns.append(0)
    
    # 检查是否单调递减
    is_monotonic = all(returns[i] >= returns[i+1] for i in range(len(returns)-1))
    
    return is_monotonic, returns


class MultiFactorQuintileBacktestEngine:
    """
    多因子分层回测引擎
    
    实现20轮多因子组合的分层回测
    """
    
    def __init__(
        self,
        db_path: str = None,
        output_dir: str = None,
        n_rounds: int = 20,
        n_stocks: int = 50,
        rebalance_freq: int = 5,
        initial_capital: float = 1000000,
        seed: int = None
    ):
        """
        初始化引擎
        
        参数:
            db_path: 数据库路径
            output_dir: 报告输出目录
            n_rounds: 回测轮数
            n_stocks: 每组持仓数量
            rebalance_freq: 调仓频率
            initial_capital: 初始资金
            seed: 随机种子
        """
        self.db_path = db_path or r'e:\python_space\myquant\data\aquant.db'
        self.output_dir = output_dir or r'e:\python_space\myquant\reports\backtest\quintile'
        self.n_rounds = n_rounds
        
        # 设置随机种子
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        self.n_stocks = n_stocks
        self.rebalance_freq = rebalance_freq
        self.initial_capital = initial_capital
        
        # 创建输出目录
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        # 初始化数据连接
        self.db = None
        self.calc = None
        self.wq = None
        self.price_data = None
        
        # 存储所有轮次的结果
        self.all_round_results: List[RoundResult] = []
        
        logger.info(f"初始化多因子分层回测引擎")
        logger.info(f"数据库路径: {self.db_path}")
        logger.info(f"输出目录: {self.output_dir}")
        logger.info(f"回测轮数: {n_rounds}")
    
    def initialize_data(self):
        """初始化数据连接"""
        try:
            from src.data.database import DatabaseManager
            from src.factors.calculator import FactorCalculator
            from src.factors.worldquant import WorldQuantFactors
            
            logger.info("正在连接数据库...")
            self.db = DatabaseManager(self.db_path)
            
            # 创建数据加载器适配器
            class DataLoaderAdapter:
                def __init__(self, db):
                    self.db = db
                
                def get_price_data(self):
                    """获取价格数据，返回MultiIndex DataFrame"""
                    df = self.db.get_stock_daily()
                    if not df.empty:
                        # 确保索引是MultiIndex (trade_date, stock_code)
                        if not isinstance(df.index, pd.MultiIndex):
                            df = df.set_index(['trade_date', 'stock_code'])
                    return df
            
            logger.info("正在初始化因子计算器...")
            data_loader = DataLoaderAdapter(self.db)
            self.calc = FactorCalculator(data_loader)
            self.calc.load_data()
            
            logger.info("正在初始化WorldQuant因子...")
            self.wq = WorldQuantFactors(self.calc)
            
            # 加载价格数据（用于回测）
            logger.info("正在加载价格数据...")
            self.price_data = self.calc.price_data
            
            logger.info(f"数据初始化完成，价格数据形状: {self.price_data.shape}")
            logger.info(f"日期范围: {self.price_data.index.get_level_values('trade_date').min()} ~ {self.price_data.index.get_level_values('trade_date').max()}")
            
        except Exception as e:
            logger.error(f"数据初始化失败: {e}")
            raise
    
    def select_random_factors(self, n_factors: int = None) -> List[Tuple[str, int]]:
        """
        从因子池中随机选择因子
        
        参数:
            n_factors: 选择的因子数量（2-4个）
        
        返回:
            [(category, factor_id), ...]
        """
        if n_factors is None:
            n_factors = random.randint(2, 4)
        
        # 从因子池中随机选择
        all_factors = []
        for category, factor_ids in FACTOR_POOL.items():
            for fid in factor_ids:
                all_factors.append((category, fid))
        
        selected = random.sample(all_factors, min(n_factors, len(all_factors)))
        return selected
    
    def calculate_factors(self, factor_list: List[Tuple[str, int]], start_date: str, end_date: str) -> Dict[str, pd.Series]:
        """
        计算指定因子在给定日期范围内的值
        
        参数:
            factor_list: [(category, factor_id), ...]
            start_date: 开始日期
            end_date: 结束日期
        
        返回:
            {factor_name: factor_series}
        """
        factors_dict = {}
        
        for category, factor_id in factor_list:
            factor_name = f"{category}_alpha_{factor_id:03d}"
            
            try:
                logger.info(f"  计算因子: {factor_name}")
                factor_values = self.wq.calculate_factor(factor_id)
                
                # 筛选日期范围
                mask = (factor_values.index.get_level_values('trade_date') >= start_date) & \
                       (factor_values.index.get_level_values('trade_date') <= end_date)
                factor_values = factor_values[mask]
                
                # 去极值和标准化
                factor_values = self._preprocess_factor(factor_values)
                
                factors_dict[factor_name] = factor_values
                
            except Exception as e:
                logger.error(f"  计算因子 {factor_name} 失败: {e}")
                continue
        
        return factors_dict
    
    def _preprocess_factor(self, factor: pd.Series) -> pd.Series:
        """
        因子预处理：去极值、标准化
        
        参数:
            factor: 原始因子值
        
        返回:
            预处理后的因子值
        """
        # 去极值（1%和99%分位数）
        factor = factor.groupby(level='trade_date').transform(
            lambda x: x.clip(lower=x.quantile(0.01), upper=x.quantile(0.99))
        )
        
        # 标准化（z-score）
        factor = factor.groupby(level='trade_date').transform(
            lambda x: (x - x.mean()) / (x.std() + 1e-10) if x.std() > 0 else x - x.mean()
        )
        
        return factor
    
    def run_single_batch(
        self,
        batch_config: Dict,
        combined_factor: pd.Series,
        weights: Dict[str, float]
    ) -> Dict:
        """
        运行单个批次的回测
        
        参数:
            batch_config: 批次配置
            combined_factor: 合成因子
            weights: 因子权重
        
        返回:
            批次回测结果
        """
        batch_name = batch_config['name']
        train_start = batch_config['train_start']
        train_end = batch_config['train_end']
        test_start = batch_config['test_start']
        test_end = batch_config['test_end']
        
        logger.info(f"    运行批次: {batch_name}")
        
        try:
            # 筛选回测期数据
            mask = (combined_factor.index.get_level_values('trade_date') >= train_start) & \
                   (combined_factor.index.get_level_values('trade_date') <= train_end)
            train_factor = combined_factor[mask]
            
            mask_test = (combined_factor.index.get_level_values('trade_date') >= test_start) & \
                        (combined_factor.index.get_level_values('trade_date') <= test_end)
            test_factor = combined_factor[mask_test]
            
            # 筛选回测期的价格数据
            price_mask = (self.price_data.index.get_level_values('trade_date') >= train_start) & \
                         (self.price_data.index.get_level_values('trade_date') <= train_end)
            train_price = self.price_data[price_mask]
            
            price_mask_test = (self.price_data.index.get_level_values('trade_date') >= test_start) & \
                              (self.price_data.index.get_level_values('trade_date') <= test_end)
            test_price = self.price_data[price_mask_test]
            
            # 回测期回测
            from .backtest import Backtester
            bt_train = Backtester(initial_capital=self.initial_capital)
            bt_train.load_data(train_price)
            train_result = bt_train.run_backtest(train_factor, n_stocks=self.n_stocks, rebalance_freq=self.rebalance_freq)
            train_perf = train_result.get('performance', {})
            
            # 验证期回测
            bt_test = Backtester(initial_capital=self.initial_capital)
            bt_test.load_data(test_price)
            test_result = bt_test.run_backtest(test_factor, n_stocks=self.n_stocks, rebalance_freq=self.rebalance_freq)
            test_perf = test_result.get('performance', {})
            
            return {
                'batch_name': batch_name,
                'train_start': train_start,
                'train_end': train_end,
                'test_start': test_start,
                'test_end': test_end,
                'train_return': train_perf.get('total_return', 0),
                'train_sharpe': train_perf.get('sharpe_ratio', 0),
                'train_max_dd': train_perf.get('max_drawdown', 0),
                'test_return': test_perf.get('total_return', 0),
                'test_sharpe': test_perf.get('sharpe_ratio', 0),
                'test_max_dd': test_perf.get('max_drawdown', 0),
            }
            
        except Exception as e:
            logger.error(f"    批次 {batch_name} 回测失败: {e}")
            return {
                'batch_name': batch_name,
                'train_start': train_start,
                'train_end': train_end,
                'test_start': test_start,
                'test_end': test_end,
                'train_return': 0,
                'train_sharpe': 0,
                'train_max_dd': 0,
                'test_return': 0,
                'test_sharpe': 0,
                'test_max_dd': 0,
                'error': str(e)
            }
    
    def run_single_round(self, round_id: int) -> RoundResult:
        """
        运行单轮回测
        
        参数:
            round_id: 轮次ID
        
        返回:
            RoundResult
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"开始第 {round_id:03d} 轮回测")
        logger.info(f"{'='*60}")
        
        # 1. 随机选择因子
        selected_factors = self.select_random_factors()
        logger.info(f"选择的因子: {selected_factors}")
        
        # 2. 计算所有批次的因子数据（使用所有数据计算权重）
        all_start = BATCH_CONFIG[0]['train_start']
        all_end = BATCH_CONFIG[-1]['test_end']
        
        logger.info(f"计算因子数据 ({all_start} ~ {all_end})...")
        factors_dict = self.calculate_factors(selected_factors, all_start, all_end)
        
        if not factors_dict:
            logger.error("没有成功计算任何因子，跳过本轮")
            return RoundResult(
                round_id=round_id,
                factors=selected_factors,
                weights={},
                batch_results=[],
                quintile_results={}
            )
        
        # 3. 计算风险平价权重
        logger.info("计算风险平价权重...")
        weights = risk_parity_weights(factors_dict, self.price_data)
        logger.info(f"权重: {weights}")
        
        # 4. 合成因子
        logger.info("合成多因子...")
        combined_factor = combine_factors(factors_dict, weights)
        
        # 5. 运行7个批次的回测
        logger.info("运行7个批次的滚动回测...")
        batch_results = []
        for batch_config in BATCH_CONFIG:
            batch_result = self.run_single_batch(batch_config, combined_factor, weights)
            batch_results.append(batch_result)
        
        # 6. 5组分层回测（使用第一个批次的回测期进行分层回测）
        logger.info("运行5组分层回测...")
        first_batch = BATCH_CONFIG[0]
        mask = (combined_factor.index.get_level_values('trade_date') >= first_batch['train_start']) & \
               (combined_factor.index.get_level_values('trade_date') <= first_batch['train_end'])
        batch_factor = combined_factor[mask]
        
        price_mask = (self.price_data.index.get_level_values('trade_date') >= first_batch['train_start']) & \
                     (self.price_data.index.get_level_values('trade_date') <= first_batch['train_end'])
        batch_price = self.price_data[price_mask]
        
        quintile_results = run_quintile_backtest(
            batch_factor,
            batch_price,
            n_stocks=self.n_stocks,
            rebalance_freq=self.rebalance_freq,
            initial_capital=self.initial_capital
        )
        
        # 7. 检查分层单调性
        is_mono, returns = check_monotonicity(quintile_results)
        logger.info(f"分层单调性: {is_mono}, 各组收益: {[f'{r:.2%}' for r in returns]}")
        
        round_result = RoundResult(
            round_id=round_id,
            factors=selected_factors,
            weights=weights,
            batch_results=batch_results,
            quintile_results=quintile_results
        )
        
        self.all_round_results.append(round_result)
        
        logger.info(f"第 {round_id:03d} 轮回测完成")
        
        return round_result
    
    def generate_round_report(self, round_result: RoundResult):
        """
        生成单轮HTML报告
        
        参数:
            round_result: 单轮回测结果
        """
        round_id = round_result.round_id
        output_path = Path(self.output_dir) / f"round_{round_id:03d}.html"
        
        logger.info(f"生成第 {round_id:03d} 轮报告: {output_path}")
        
        # 创建报告内容
        html_content = self._render_round_html(round_result)
        
        # 写入文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"报告已生成: {output_path}")
    
    def _render_round_html(self, round_result: RoundResult) -> str:
        """渲染单轮HTML报告"""
        round_id = round_result.round_id
        
        # 生成因子信息表格
        factor_rows = []
        for category, factor_id in round_result.factors:
            factor_name = f"{category}_alpha_{factor_id:03d}"
            weight = round_result.weights.get(factor_name, 0)
            factor_rows.append(f"""
                <tr>
                    <td>{category}</td>
                    <td>Alpha_{factor_id:03d}</td>
                    <td>{weight:.4f}</td>
                </tr>
            """)
        
        # 生成批次结果表格
        batch_rows = []
        for batch in round_result.batch_results:
            batch_rows.append(f"""
                <tr>
                    <td>{batch['batch_name']}</td>
                    <td>{batch['train_start']} ~ {batch['train_end']}</td>
                    <td>{batch['test_start']} ~ {batch['test_end']}</td>
                    <td>{batch['train_return']:.2%}</td>
                    <td>{batch['train_sharpe']:.2f}</td>
                    <td>{batch['train_max_dd']:.2%}</td>
                    <td>{batch['test_return']:.2%}</td>
                </tr>
            """)
        
        # 生成5组分层回测图表
        quintile_chart = self._create_quintile_chart(round_result.quintile_results)
        
        # 检查单调性
        is_mono, returns = check_monotonicity(round_result.quintile_results)
        mono_status = "✓ 通过" if is_mono else "✗ 未通过"
        
        # 生成各组绩效表格
        quintile_rows = []
        quintile_names = ['Q1_top', 'Q2', 'Q3', 'Q4', 'Q5_bottom', 'long_short']
        quintile_labels = ['Q1 (Top 20%)', 'Q2', 'Q3', 'Q4', 'Q5 (Bottom 20%)', 'Long-Short']
        
        for name, label in zip(quintile_names, quintile_labels):
            if name in round_result.quintile_results:
                perf = round_result.quintile_results[name].get('performance', {})
                quintile_rows.append(f"""
                    <tr>
                        <td>{label}</td>
                        <td>{perf.get('total_return', 0):.2%}</td>
                        <td>{perf.get('annual_return', 0):.2%}</td>
                        <td>{perf.get('sharpe_ratio', 0):.2f}</td>
                        <td>{perf.get('max_drawdown', 0):.2%}</td>
                        <td>{perf.get('calmar_ratio', 0):.2f}</td>
                    </tr>
                """)
        
        generate_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多因子分层回测报告 - 第 {round_id:03d} 轮</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
        }}
        .header h1 {{ font-size: 28px; margin-bottom: 10px; }}
        .header .meta {{ font-size: 14px; opacity: 0.9; }}
        .section {{
            background: white;
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .section-title {{
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
            color: #667eea;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background-color: #f8f9fa;
            font-weight: 600;
            color: #555;
        }}
        tr:hover {{ background-color: #f8f9fa; }}
        .chart-container {{ margin: 20px 0; height: 400px; }}
        .mono-pass {{ color: #28a745; font-weight: bold; }}
        .mono-fail {{ color: #dc3545; font-weight: bold; }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .card {{
            background: linear-gradient(135deg, #667eea15, #764ba215);
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}
        .card-value {{ font-size: 24px; font-weight: bold; color: #667eea; }}
        .card-label {{ font-size: 14px; color: #666; margin-top: 5px; }}
        .footer {{
            text-align: center;
            color: #999;
            font-size: 12px;
            margin-top: 30px;
            padding: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>多因子分层回测报告 - 第 {round_id:03d} 轮</h1>
            <div class="meta">
                生成时间: {generate_time} | 多因子分层回测系统
            </div>
        </div>
        
        <!-- 因子信息 -->
        <div class="section">
            <div class="section-title">因子组合与风险平价权重</div>
            <table>
                <thead>
                    <tr>
                        <th>因子类别</th>
                        <th>因子编号</th>
                        <th>风险平价权重</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(factor_rows)}
                </tbody>
            </table>
        </div>
        
        <!-- 批次回测结果 -->
        <div class="section">
            <div class="section-title">7批次滚动回测结果</div>
            <table>
                <thead>
                    <tr>
                        <th>批次</th>
                        <th>回测期</th>
                        <th>验证期</th>
                        <th>回测收益</th>
                        <th>回测夏普</th>
                        <th>回测最大回撤</th>
                        <th>验证期收益</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(batch_rows)}
                </tbody>
            </table>
        </div>
        
        <!-- 分层单调性 -->
        <div class="section">
            <div class="section-title">分层单调性检验</div>
            <div class="summary-cards">
                <div class="card">
                    <div class="card-value">{mono_status}</div>
                    <div class="card-label">单调性检验结果</div>
                </div>
                <div class="card">
                    <div class="card-value">{returns[0]:.2%}</div>
                    <div class="card-label">Q1 (Top) 年化收益</div>
                </div>
                <div class="card">
                    <div class="card-value">{returns[4]:.2%}</div>
                    <div class="card-label">Q5 (Bottom) 年化收益</div>
                </div>
                <div class="card">
                    <div class="card-value">{returns[0] - returns[4]:.2%}</div>
                    <div class="card-label">Q1-Q5 收益差</div>
                </div>
            </div>
        </div>
        
        <!-- 5组分层回测绩效 -->
        <div class="section">
            <div class="section-title">5组分层回测绩效</div>
            <table>
                <thead>
                    <tr>
                        <th>分组</th>
                        <th>总收益</th>
                        <th>年化收益</th>
                        <th>夏普比率</th>
                        <th>最大回撤</th>
                        <th>卡玛比率</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(quintile_rows)}
                </tbody>
            </table>
        </div>
        
        <!-- 分层收益曲线 -->
        <div class="section">
            <div class="section-title">分层收益曲线对比</div>
            <div id="quintile-chart" class="chart-container"></div>
        </div>
        
        <div class="footer">
            <p>本报告由多因子分层回测系统自动生成 | 数据仅供参考，不构成投资建议</p>
        </div>
    </div>
    
    <script>
        {quintile_chart}
    </script>
</body>
</html>
        """
    
    def _create_quintile_chart(self, quintile_results: Dict[str, Dict]) -> str:
        """创建分层收益曲线图表的JavaScript代码"""
        # 准备数据
        series_data = []
        colors = ['#52c41a', '#73d13d', '#bae637', '#fadb14', '#ff4d4f', '#722ed1']
        names = ['Q1 (Top 20%)', 'Q2', 'Q3', 'Q4', 'Q5 (Bottom 20%)', 'Long-Short']
        keys = ['Q1_top', 'Q2', 'Q3', 'Q4', 'Q5_bottom', 'long_short']
        
        for i, (key, name) in enumerate(zip(keys, names)):
            if key in quintile_results:
                portfolio_df = quintile_results[key].get('portfolio_values', pd.DataFrame())
                if not portfolio_df.empty and 'value' in portfolio_df.columns and 'date' in portfolio_df.columns:
                    dates = portfolio_df['date'].astype(str).tolist()
                    values = (portfolio_df['value'] / portfolio_df['value'].iloc[0] * 100).round(2).tolist()
                    
                    series_data.append({
                        'name': name,
                        'data': values,
                        'color': colors[i]
                    })
        
        if not series_data:
            return "// 无数据"
        
        dates = quintile_results.get('Q1_top', {}).get('portfolio_values', pd.DataFrame()).get('date', [])
        if not isinstance(dates, pd.Series):
            dates = []
        else:
            dates = dates.astype(str).tolist()
        
        # 生成ECharts配置
        series_js = []
        for s in series_data:
            series_js.append(f"""
                {{
                    name: '{s['name']}',
                    type: 'line',
                    data: {s['data']},
                    smooth: true,
                    symbol: 'none',
                    lineStyle: {{ width: 2, color: '{s['color']}' }},
                    itemStyle: {{ color: '{s['color']}' }}
                }}
            """)
        
        return f"""
        var chartDom = document.getElementById('quintile-chart');
        var myChart = echarts.init(chartDom);
        var option = {{
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{ type: 'cross' }}
            }},
            legend: {{
                data: {[s['name'] for s in series_data]},
                top: 10
            }},
            grid: {{
                left: '3%',
                right: '4%',
                bottom: '15%',
                containLabel: true
            }},
            xAxis: {{
                type: 'category',
                data: {dates},
                axisLabel: {{ rotate: 45 }}
            }},
            yAxis: {{
                type: 'value',
                name: '净值',
                scale: true
            }},
            dataZoom: [
                {{ type: 'inside', start: 0, end: 100 }},
                {{ type: 'slider', start: 0, end: 100, bottom: 10 }}
            ],
            series: [{','.join(series_js)}]
        }};
        myChart.setOption(option);
        window.addEventListener('resize', function() {{ myChart.resize(); }});
        """
    
    def generate_summary_report(self):
        """生成综合报告"""
        logger.info("\n生成综合报告...")
        
        output_path = Path(self.output_dir) / "summary.html"
        
        # 统计信息
        total_rounds = len(self.all_round_results)
        
        # 计算单调性成功率
        mono_count = 0
        for result in self.all_round_results:
            is_mono, _ = check_monotonicity(result.quintile_results)
            if is_mono:
                mono_count += 1
        mono_success_rate = mono_count / total_rounds if total_rounds > 0 else 0
        
        # 找出最佳/最差组合
        best_sharpe = -float('inf')
        worst_sharpe = float('inf')
        best_round = None
        worst_round = None
        
        for result in self.all_round_results:
            # 使用多空组合的夏普比率作为评判标准
            ls_perf = result.quintile_results.get('long_short', {}).get('performance', {})
            sharpe = ls_perf.get('sharpe_ratio', 0)
            
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_round = result
            if sharpe < worst_sharpe:
                worst_sharpe = sharpe
                worst_round = result
        
        # 生成汇总表格
        summary_rows = []
        for result in self.all_round_results:
            is_mono, returns = check_monotonicity(result.quintile_results)
            ls_perf = result.quintile_results.get('long_short', {}).get('performance', {})
            
            factor_names = [f"{cat}_alpha_{fid:03d}" for cat, fid in result.factors]
            
            summary_rows.append(f"""
                <tr>
                    <td>{result.round_id}</td>
                    <td>{', '.join(factor_names)}</td>
                    <td>{'✓' if is_mono else '✗'}</td>
                    <td>{returns[0]:.2%}</td>
                    <td>{returns[4]:.2%}</td>
                    <td>{returns[0] - returns[4]:.2%}</td>
                    <td>{ls_perf.get('sharpe_ratio', 0):.2f}</td>
                    <td>{ls_perf.get('total_return', 0):.2%}</td>
                </tr>
            """)
        
        generate_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多因子分层回测综合报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
        }}
        .header h1 {{ font-size: 28px; margin-bottom: 10px; }}
        .header .meta {{ font-size: 14px; opacity: 0.9; }}
        .section {{
            background: white;
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .section-title {{
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
            color: #667eea;
        }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .card {{
            background: linear-gradient(135deg, #667eea15, #764ba215);
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}
        .card-value {{ font-size: 24px; font-weight: bold; color: #667eea; }}
        .card-label {{ font-size: 14px; color: #666; margin-top: 5px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background-color: #f8f9fa;
            font-weight: 600;
            color: #555;
        }}
        tr:hover {{ background-color: #f8f9fa; }}
        .best {{ background-color: #e8f5e9 !important; }}
        .worst {{ background-color: #ffebee !important; }}
        .footer {{
            text-align: center;
            color: #999;
            font-size: 12px;
            margin-top: 30px;
            padding: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>多因子分层回测综合报告</h1>
            <div class="meta">
                生成时间: {generate_time} | 共 {total_rounds} 轮回测
            </div>
        </div>
        
        <!-- 汇总统计 -->
        <div class="section">
            <div class="section-title">汇总统计</div>
            <div class="summary-cards">
                <div class="card">
                    <div class="card-value">{total_rounds}</div>
                    <div class="card-label">总回测轮数</div>
                </div>
                <div class="card">
                    <div class="card-value">{mono_success_rate:.1%}</div>
                    <div class="card-label">分层单调性成功率</div>
                </div>
                <div class="card">
                    <div class="card-value">{best_sharpe:.2f}</div>
                    <div class="card-label">最佳组合夏普比率</div>
                </div>
                <div class="card">
                    <div class="card-value">{worst_sharpe:.2f}</div>
                    <div class="card-label">最差组合夏普比率</div>
                </div>
            </div>
        </div>
        
        <!-- 最佳组合 -->
        <div class="section">
            <div class="section-title">最佳因子组合 (夏普比率最高)</div>
            <p>轮次: {best_round.round_id if best_round else 'N/A'}</p>
            <p>因子: {', '.join([f"{cat}_alpha_{fid:03d}" for cat, fid in (best_round.factors if best_round else [])])}</p>
            <p>多空夏普: {best_sharpe:.2f}</p>
        </div>
        
        <!-- 最差组合 -->
        <div class="section">
            <div class="section-title">最差因子组合 (夏普比率最低)</div>
            <p>轮次: {worst_round.round_id if worst_round else 'N/A'}</p>
            <p>因子: {', '.join([f"{cat}_alpha_{fid:03d}" for cat, fid in (worst_round.factors if worst_round else [])])}</p>
            <p>多空夏普: {worst_sharpe:.2f}</p>
        </div>
        
        <!-- 所有轮次汇总 -->
        <div class="section">
            <div class="section-title">所有轮次汇总</div>
            <table>
                <thead>
                    <tr>
                        <th>轮次</th>
                        <th>因子组合</th>
                        <th>单调性</th>
                        <th>Q1收益</th>
                        <th>Q5收益</th>
                        <th>Q1-Q5差</th>
                        <th>多空夏普</th>
                        <th>多空收益</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(summary_rows)}
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            <p>本报告由多因子分层回测系统自动生成 | 数据仅供参考，不构成投资建议</p>
        </div>
    </div>
</body>
</html>
        """
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"综合报告已生成: {output_path}")
    
    def run_all_rounds(self):
        """运行所有轮次的回测"""
        logger.info(f"\n{'='*60}")
        logger.info(f"开始运行 {self.n_rounds} 轮多因子分层回测")
        logger.info(f"{'='*60}\n")
        
        # 初始化数据
        self.initialize_data()
        
        # 运行每一轮
        for round_id in range(1, self.n_rounds + 1):
            try:
                round_result = self.run_single_round(round_id)
                self.generate_round_report(round_result)
                
                # 每5轮输出一次进度
                if round_id % 5 == 0:
                    logger.info(f"\n已完成 {round_id}/{self.n_rounds} 轮")
                    
            except Exception as e:
                logger.error(f"第 {round_id} 轮回测失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
                continue
        
        # 生成综合报告
        self.generate_summary_report()
        
        logger.info(f"\n{'='*60}")
        logger.info(f"所有 {self.n_rounds} 轮回测完成！")
        logger.info(f"报告目录: {self.output_dir}")
        logger.info(f"{'='*60}")


def main():
    """主函数"""
    # 创建引擎实例
    engine = MultiFactorQuintileBacktestEngine(
        db_path=r'e:\python_space\myquant\data\aquant.db',
        output_dir=r'e:\python_space\myquant\reports\backtest\quintile',
        n_rounds=20,
        n_stocks=50,
        rebalance_freq=5,
        initial_capital=1000000
    )
    
    # 运行所有回测
    engine.run_all_rounds()


if __name__ == '__main__':
    main()
