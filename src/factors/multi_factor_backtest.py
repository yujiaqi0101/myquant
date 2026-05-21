"""
多因子分批回测引擎
==================

实现多因子组合的分批回测逻辑，包含：
- 从5类因子中随机选择因子进行20轮单因子回测
- 5组多因子组合回测（2-4个因子等权合成）
- 7个批次（3年回测 + 1年验证）的滚动回测
- 随机参数化（n_stocks, rebalance_freq, long_short）
- HTML综合报告生成（使用pyecharts）
- 数据库日志记录

使用方式:
    python -m src.factors.multi_factor_backtest
"""

import sys
import os
import random
import time
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.database import DatabaseManager
from src.factors.calculator import FactorCalculator
from src.factors.worldquant import WorldQuantFactors
from src.factors.backtest import Backtester

from pyecharts import options as opts
from pyecharts.charts import Line, Bar, Grid, Scatter

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger('MultiFactorBacktest')

# ==================== 常量定义 ====================

DB_PATH = str(PROJECT_ROOT / 'data' / 'aquant.db')
REPORT_DIR = PROJECT_ROOT / 'reports' / 'backtest'

# 因子类型定义: {类型名: {因子编号: 因子描述}}
FACTOR_TYPES = {
    'momentum': {
        6: 'alpha_006 - 开盘价成交量相关性',
        20: 'alpha_020 - 动量因子',
    },
    'mean_reversion': {
        3: 'alpha_003 - 开盘价成交量排名相关',
        5: 'alpha_005 - VWAP偏离均值回复',
    },
    'volatility': {
        7: 'alpha_007 - 波动率突破',
        8: 'alpha_008 - 开盘价收益变化',
    },
    'volume_anomaly': {
        9: 'alpha_009 - 价格变化方向',
        14: 'alpha_014 - 收益变化量价相关',
    },
    'correlation': {
        10: 'alpha_010 - 价格变化方向排名',
        12: 'alpha_012 - 量价方向因子',
    },
}

# 分批回测配置: (回测开始年, 回测结束年, 验证结束年)
BATCHES = [
    (2017, 2019, 2020),
    (2018, 2020, 2021),
    (2019, 2021, 2022),
    (2020, 2022, 2023),
    (2021, 2023, 2024),
    (2022, 2024, 2025),
    (2023, 2025, 2026),
]

# 随机参数范围
N_STOCKS_CHOICES = [20, 30, 50, 80, 100]
REBALANCE_FREQ_CHOICES = [1, 3, 5, 10, 20]
LONG_SHORT_CHOICES = [True, False]


# ==================== 数据库辅助 ====================

def ensure_report_path_column(db: DatabaseManager):
    """确保 execution_log 表有 report_path 列"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # 检查列是否已存在
            cursor.execute("PRAGMA table_info(execution_log)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'report_path' not in columns:
                cursor.execute("ALTER TABLE execution_log ADD COLUMN report_path TEXT")
                logger.info("已添加 report_path 列到 execution_log 表")
    except Exception as e:
        logger.warning(f"添加 report_path 列时出错: {e}")


# ==================== 多因子分批回测器 ====================

class MultiFactorBacktester:
    """
    多因子分批回测引擎

    支持从5类因子中随机选择因子，进行多轮分批回测，
    生成综合HTML报告并记录数据库日志。
    """

    def __init__(
        self,
        db_path: str = DB_PATH,
        report_dir: Path = REPORT_DIR,
        initial_capital: float = 1_000_000,
        seed: Optional[int] = None,
        max_stocks: int = 500,
    ):
        """
        初始化回测引擎

        Parameters
        ----------
        db_path : str
            数据库路径
        report_dir : Path
            报告输出目录
        initial_capital : float
            初始资金
        seed : int, optional
            随机种子，用于结果复现
        max_stocks : int
            股票池最大数量，按成交额筛选流动性最好的N只股票。
            设为0表示不限制（使用全量股票，注意内存）。
        """
        self.db_path = db_path
        self.report_dir = Path(report_dir)
        self.initial_capital = initial_capital
        self.max_stocks = max_stocks

        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        self.report_dir.mkdir(parents=True, exist_ok=True)

        # 初始化数据库
        self.db = DatabaseManager(db_path)
        ensure_report_path_column(self.db)

        # 所有回测结果汇总
        self.all_results: List[Dict] = []

        logger.info(f"多因子分批回测引擎初始化完成")
        logger.info(f"  数据库: {db_path}")
        logger.info(f"  报告目录: {self.report_dir}")
        logger.info(f"  股票池上限: {max_stocks}")

    # ==================== 数据加载 ====================

    def _select_stock_pool(
        self, start_date: str, end_date: str, n: int
    ) -> List[str]:
        """
        按成交额筛选流动性最好的N只股票

        Parameters
        ----------
        start_date : str
            开始日期
        end_date : str
            结束日期
        n : int
            选取数量

        Returns
        -------
        List[str]
            股票代码列表
        """
        try:
            with self.db.get_connection() as conn:
                query = """
                    SELECT stock_code, SUM(amount) as total_amount
                    FROM stock_daily
                    WHERE trade_date >= ? AND trade_date <= ?
                      AND amount IS NOT NULL AND amount > 0
                    GROUP BY stock_code
                    ORDER BY total_amount DESC
                    LIMIT ?
                """
                cursor = conn.execute(query, (start_date, end_date, n))
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"  股票池筛选失败: {e}")
            return []

    def _load_data_for_period(
        self, start_date: str, end_date: str,
        stock_codes: Optional[List[str]] = None
    ) -> Optional[pd.DataFrame]:
        """
        加载指定日期范围的股票日频数据

        Parameters
        ----------
        start_date : str
            开始日期，如 '2017-01-01'
        end_date : str
            结束日期，如 '2019-12-31'
        stock_codes : list, optional
            限定股票列表

        Returns
        -------
        pd.DataFrame or None
            MultiIndex (trade_date, stock_code) 的 DataFrame
        """
        try:
            logger.info(f"  加载数据: {start_date} ~ {end_date}"
                        + (f" ({len(stock_codes)}只股票)" if stock_codes else ""))
            data = self.db.get_stock_daily(
                start_date=start_date,
                end_date=end_date,
                stock_codes=stock_codes,
            )
            if data.empty:
                logger.warning(f"  数据为空: {start_date} ~ {end_date}")
                return None
            n_stocks = data.index.get_level_values('stock_code').nunique()
            n_dates = data.index.get_level_values('trade_date').nunique()
            logger.info(f"  数据加载完成: {n_dates}个交易日, {n_stocks}只股票, {len(data)}条记录")
            return data
        except Exception as e:
            logger.error(f"  加载数据失败: {e}")
            return None

    # ==================== 因子计算 ====================

    def _calculate_factor(
        self, price_data: pd.DataFrame, factor_id: int
    ) -> Optional[pd.Series]:
        """
        计算单个WorldQuant因子

        Parameters
        ----------
        price_data : pd.DataFrame
            价格数据
        factor_id : int
            因子编号

        Returns
        -------
        pd.Series or None
            因子值序列
        """
        try:
            # 构建一个轻量的 data_loader 适配器
            class PriceDataAdapter:
                """适配器：让 FactorCalculator 能使用已加载的价格数据"""
                def __init__(self, data):
                    self._data = data

                def get_price_data(self):
                    return self._data

                def get_industry_mapping(self):
                    return None

            adapter = PriceDataAdapter(price_data)
            calc = FactorCalculator(adapter)
            calc.load_data()

            wq = WorldQuantFactors(calc)
            factor = wq.calculate_factor(factor_id)

            # 清洗异常值：将 inf/-inf 替换为 NaN
            factor = factor.replace([np.inf, -np.inf], np.nan)

            # 去除NaN
            valid_count = factor.notna().sum()
            total_count = len(factor)
            logger.info(f"    因子 alpha_{factor_id:03d} 计算完成: "
                        f"有效值 {valid_count}/{total_count} "
                        f"({valid_count/total_count*100:.1f}%)")
            return factor

        except Exception as e:
            logger.error(f"    因子 alpha_{factor_id:03d} 计算失败: {e}")
            return None

    def _combine_factors(
        self, factors: List[pd.Series]
    ) -> pd.Series:
        """
        等权合成多个因子

        Parameters
        ----------
        factors : List[pd.Series]
            因子值列表

        Returns
        -------
        pd.Series
            合成后的因子值
        """
        if len(factors) == 1:
            return factors[0]

        # 对齐索引
        aligned = pd.concat(factors, axis=1, join='inner')
        # 等权平均
        combined = aligned.mean(axis=1)
        combined.name = 'combined_factor'

        valid_count = combined.notna().sum()
        total_count = len(combined)
        logger.info(f"    多因子合成完成: {len(factors)}个因子, "
                    f"有效值 {valid_count}/{total_count} "
                    f"({valid_count/total_count*100:.1f}%)")
        return combined

    # ==================== 单次回测 ====================

    def _run_single_backtest(
        self,
        price_data: pd.DataFrame,
        factor: pd.Series,
        n_stocks: int,
        rebalance_freq: int,
        long_short: bool,
    ) -> Optional[Dict]:
        """
        运行单次回测

        Parameters
        ----------
        price_data : pd.DataFrame
            价格数据
        factor : pd.Series
            因子值
        n_stocks : int
            持仓股票数
        rebalance_freq : int
            调仓频率
        long_short : bool
            是否多空策略

        Returns
        -------
        Dict or None
            回测结果
        """
        try:
            # 确保价格数据有 stock_code 列（回测器内部依赖此列）
            if isinstance(price_data.index, pd.MultiIndex):
                price_data = price_data.copy()
                price_data['stock_code'] = price_data.index.get_level_values('stock_code')

            bt = Backtester(initial_capital=self.initial_capital)
            bt.load_data(price_data)
            result = bt.run_backtest(
                factor=factor,
                n_stocks=n_stocks,
                rebalance_freq=rebalance_freq,
                long_short=long_short,
            )
            return result
        except Exception as e:
            logger.error(f"    回测执行失败: {e}")
            return None

    # ==================== 参数随机化 ====================

    @staticmethod
    def _random_params() -> Dict:
        """生成随机回测参数"""
        return {
            'n_stocks': random.choice(N_STOCKS_CHOICES),
            'rebalance_freq': random.choice(REBALANCE_FREQ_CHOICES),
            'long_short': random.choice(LONG_SHORT_CHOICES),
        }

    @staticmethod
    def _random_single_factor() -> Tuple[int, str]:
        """
        随机选择一个因子

        Returns
        -------
        Tuple[int, str]
            (因子编号, 因子类型)
        """
        factor_type = random.choice(list(FACTOR_TYPES.keys()))
        factor_id = random.choice(list(FACTOR_TYPES[factor_type].keys()))
        return factor_id, factor_type

    @staticmethod
    def _random_multi_factors(n_factors: Optional[int] = None) -> List[Tuple[int, str]]:
        """
        随机选择多个因子（来自不同类型）

        Parameters
        ----------
        n_factors : int, optional
            因子数量，默认随机2-4个

        Returns
        -------
        List[Tuple[int, str]]
            [(因子编号, 因子类型), ...]
        """
        if n_factors is None:
            n_factors = random.randint(2, 4)

        # 从不同类型中各选一个
        available_types = list(FACTOR_TYPES.keys())
        random.shuffle(available_types)
        selected_types = available_types[:n_factors]

        factors = []
        for ftype in selected_types:
            factor_id = random.choice(list(FACTOR_TYPES[ftype].keys()))
            factors.append((factor_id, ftype))

        return factors

    # ==================== 分批回测 ====================

    def run_batch_backtest(
        self,
        factor_id: int,
        factor_type: str,
        factor_label: str,
        is_multi: bool = False,
        multi_factor_ids: Optional[List[Tuple[int, str]]] = None,
    ) -> List[Dict]:
        """
        对一个因子执行全部分批回测（7个批次）

        Parameters
        ----------
        factor_id : int
            主因子编号
        factor_type : str
            因子类型
        factor_label : str
            因子标签（用于报告）
        is_multi : bool
            是否多因子组合
        multi_factor_ids : list, optional
            多因子组合中的因子列表

        Returns
        -------
        List[Dict]
            各批次的回测结果
        """
        batch_results = []
        params = self._random_params()

        logger.info(f"  因子: {factor_label}")
        logger.info(f"  参数: n_stocks={params['n_stocks']}, "
                     f"rebalance_freq={params['rebalance_freq']}, "
                     f"long_short={params['long_short']}")

        for batch_idx, (bt_start, bt_end, val_end) in enumerate(BATCHES):
            batch_label = f"批次{batch_idx+1}: {bt_start}-{bt_end}(回测) / {val_end}(验证)"

            bt_start_str = f"{bt_start}-01-01"
            bt_end_str = f"{bt_end}-12-31"
            val_end_str = f"{val_end}-12-31" if val_end < 2026 else f"{val_end}-05-19"

            # 获取股票池（按成交额排序）
            preheat_stocks = self._select_stock_pool(
                f"{bt_start - 2}-01-01", bt_end_str, self.max_stocks
            )
            if not preheat_stocks:
                logger.warning(f"    {batch_label}: 股票池为空，跳过")
                continue

            # 加载回测期数据（含预热期）
            preheat_start = f"{bt_start - 2}-01-01"
            bt_full_data = self._load_data_for_period(
                preheat_start, bt_end_str, stock_codes=preheat_stocks
            )
            if bt_full_data is None:
                continue

            # 计算回测期因子
            if is_multi and multi_factor_ids:
                factor_series_list = []
                success = True
                for fid, ftype in multi_factor_ids:
                    f = self._calculate_factor(bt_full_data, fid)
                    if f is None:
                        success = False
                        break
                    factor_series_list.append(f)
                if not success or not factor_series_list:
                    logger.warning(f"    {batch_label}: 多因子计算失败，跳过")
                    continue
                factor_bt_full = self._combine_factors(factor_series_list)
            else:
                factor_bt_full = self._calculate_factor(bt_full_data, factor_id)

            if factor_bt_full is None:
                logger.warning(f"    {batch_label}: 因子计算失败，跳过")
                continue

            # 截取回测期（去掉预热期）
            bt_data = bt_full_data.loc[
                (bt_full_data.index.get_level_values('trade_date') >= pd.Timestamp(bt_start_str)) &
                (bt_full_data.index.get_level_values('trade_date') <= pd.Timestamp(bt_end_str))
            ]
            factor_bt = factor_bt_full.loc[
                (factor_bt_full.index.get_level_values('trade_date') >= pd.Timestamp(bt_start_str)) &
                (factor_bt_full.index.get_level_values('trade_date') <= pd.Timestamp(bt_end_str))
            ]

            if bt_data.empty or factor_bt.empty:
                logger.warning(f"    {batch_label}: 回测数据为空，跳过")
                continue

            # 执行回测期回测
            bt_result = self._run_single_backtest(
                bt_data, factor_bt,
                params['n_stocks'], params['rebalance_freq'], params['long_short']
            )
            if bt_result is None or bt_result['performance'] is None:
                logger.warning(f"    {batch_label}: 回测失败，跳过")
                continue

            # 加载验证期数据
            val_data = self._load_data_for_period(
                f"{bt_end + 1}-01-01", val_end_str, stock_codes=preheat_stocks
            )
            val_result = None
            if val_data is not None and not val_data.empty:
                # 计算验证期因子（使用回测期尾部数据作为预热）
                val_full_data = pd.concat([bt_data, val_data]).groupby(level=[0, 1]).last()
                if is_multi and multi_factor_ids:
                    factor_val_list = []
                    success = True
                    for fid, ftype in multi_factor_ids:
                        f = self._calculate_factor(val_full_data, fid)
                        if f is None:
                            success = False
                            break
                        factor_val_list.append(f)
                    if not success or not factor_val_list:
                        factor_val = None
                    else:
                        factor_val = self._combine_factors(factor_val_list)
                else:
                    factor_val = self._calculate_factor(val_full_data, factor_id)

                if factor_val is not None:
                    factor_val = factor_val.loc[
                        (factor_val.index.get_level_values('trade_date') > pd.Timestamp(bt_end_str)) &
                        (factor_val.index.get_level_values('trade_date') <= pd.Timestamp(val_end_str))
                    ]
                    if not factor_val.empty:
                        val_result = self._run_single_backtest(
                            val_data, factor_val,
                            params['n_stocks'], params['rebalance_freq'], params['long_short']
                        )

            # 收集结果
            bt_perf = bt_result['performance']
            val_perf = val_result['performance'] if val_result and val_result['performance'] else {}

            result = {
                'factor_id': factor_id,
                'factor_type': factor_type,
                'factor_label': factor_label,
                'is_multi': is_multi,
                'multi_factor_ids': multi_factor_ids,
                'batch_idx': batch_idx + 1,
                'batch_label': batch_label,
                'bt_start': bt_start,
                'bt_end': bt_end,
                'val_end': val_end,
                'params': params,
                'bt_performance': bt_perf,
                'val_performance': val_perf,
                'portfolio_values': bt_result.get('portfolio_values'),
            }
            batch_results.append(result)

            # 记录数据库日志
            self._log_to_db(result)

            logger.info(
                f"    {batch_label}: "
                f"回测 年化收益={bt_perf.get('annual_return', 0):.2%}, "
                f"夏普={bt_perf.get('sharpe_ratio', 0):.2f}, "
                f"最大回撤={bt_perf.get('max_drawdown', 0):.2%}"
                + (f" | 验证 年化收益={val_perf.get('annual_return', 0):.2%}" if val_perf else "")
            )

        return batch_results

    # ==================== 数据库日志 ====================

    def _log_to_db(self, result: Dict):
        """将回测结果记录到数据库"""
        try:
            bt_perf = result['bt_performance']
            val_perf = result['val_performance']
            params = result['params']

            # 构建详细信息
            details = {
                'batch_idx': result['batch_idx'],
                'batch_label': result['batch_label'],
                'is_multi': result['is_multi'],
                'multi_factor_ids': result['multi_factor_ids'],
                'val_performance': val_perf,
            }

            log_id = self.db.log_execution(
                execution_type='multi_factor_batch_backtest',
                status='success',
                start_date=f"{result['bt_start']}-01-01",
                end_date=f"{result['val_end']}-12-31" if result['val_end'] < 2026 else f"{result['val_end']}-05-19",
                factor_name=result['factor_label'],
                factor_category=result['factor_type'],
                n_positions=params['n_stocks'],
                rebalance_freq=params['rebalance_freq'],
                initial_capital=self.initial_capital,
                sharpe=bt_perf.get('sharpe_ratio', 0),
                max_drawdown=bt_perf.get('max_drawdown', 0),
                total_return=bt_perf.get('total_return', 0),
                annual_return=bt_perf.get('annual_return', 0),
                annual_volatility=bt_perf.get('annual_volatility', 0),
                win_rate=bt_perf.get('win_rate', 0),
                details=details,
            )

            result['log_id'] = log_id

        except Exception as e:
            logger.error(f"    数据库日志记录失败: {e}")

    def _update_report_path(self, log_id: int, report_path: str):
        """更新数据库中的报告路径"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE execution_log SET report_path = ? WHERE id = ?",
                    (report_path, log_id)
                )
        except Exception as e:
            logger.warning(f"更新报告路径失败: {e}")

    # ==================== 主流程 ====================

    def run_all(self) -> List[Dict]:
        """
        执行完整的回测流程：
        1. 20轮单因子分批回测
        2. 5组多因子组合分批回测

        Returns
        -------
        List[Dict]
            所有回测结果
        """
        start_time = time.time()
        logger.info("=" * 70)
        logger.info("开始多因子分批回测")
        logger.info("=" * 70)

        # ========== 阶段1: 20轮单因子回测 ==========
        logger.info("\n" + "=" * 70)
        logger.info("阶段1: 20轮单因子分批回测")
        logger.info("=" * 70)

        for round_idx in range(1, 21):
            logger.info(f"\n--- 单因子第 {round_idx}/20 轮 ---")
            factor_id, factor_type = self._random_single_factor()
            factor_label = f"WQ_{factor_id:03d} ({FACTOR_TYPES[factor_type][factor_id]})"

            results = self.run_batch_backtest(
                factor_id=factor_id,
                factor_type=factor_type,
                factor_label=factor_label,
            )
            self.all_results.extend(results)

        # ========== 阶段2: 5组多因子组合回测 ==========
        logger.info("\n" + "=" * 70)
        logger.info("阶段2: 5组多因子组合分批回测")
        logger.info("=" * 70)

        for group_idx in range(1, 6):
            logger.info(f"\n--- 多因子组合第 {group_idx}/5 组 ---")
            multi_factors = self._random_multi_factors()
            factor_ids = [f[0] for f in multi_factors]
            factor_label = " + ".join(
                [f"WQ_{fid:03d}" for fid, ftype in multi_factors]
            )

            # 使用第一个因子的编号作为主标识
            primary_id = factor_ids[0]
            primary_type = multi_factors[0][1]

            results = self.run_batch_backtest(
                factor_id=primary_id,
                factor_type=primary_type,
                factor_label=f"组合[{factor_label}]",
                is_multi=True,
                multi_factor_ids=multi_factors,
            )
            self.all_results.extend(results)

        # ========== 汇总 ==========
        elapsed = time.time() - start_time
        logger.info("\n" + "=" * 70)
        logger.info(f"回测完成! 共 {len(self.all_results)} 条结果, 耗时 {elapsed:.1f}s")
        logger.info("=" * 70)

        return self.all_results

    # ==================== 报告生成 ====================

    def generate_summary_report(self) -> str:
        """
        生成综合HTML报告

        Returns
        -------
        str
            报告文件路径
        """
        if not self.all_results:
            logger.warning("无回测结果，无法生成报告")
            return ""

        logger.info("生成综合HTML报告...")

        report_path = self.report_dir / 'multi_factor_summary.html'
        html_content = self._build_summary_html()

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # 更新所有相关日志的报告路径
        for result in self.all_results:
            if 'log_id' in result:
                self._update_report_path(result['log_id'], str(report_path))

        logger.info(f"综合报告已生成: {report_path}")
        return str(report_path)

    def _build_summary_html(self) -> str:
        """构建综合报告HTML"""
        generate_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 构建数据表格
        table_html = self._build_results_table()
        # 构建图表
        charts_html = self._build_charts()
        # 构建统计卡片
        stats_html = self._build_stats_cards()

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>多因子分批回测综合报告</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #f0f2f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        .header {{
            background: linear-gradient(135deg, #1a237e, #283593);
            color: white;
            padding: 40px;
            border-radius: 16px;
            margin-bottom: 30px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }}
        .header h1 {{ font-size: 32px; margin-bottom: 10px; }}
        .header .meta {{ font-size: 14px; opacity: 0.85; }}
        .section {{
            background: white;
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        }}
        .section-title {{
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 3px solid #1a237e;
            color: #1a237e;
        }}
        .chart-container {{ margin: 20px 0; min-height: 400px; }}
        .footer {{
            text-align: center;
            color: #999;
            font-size: 12px;
            margin-top: 30px;
            padding: 20px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th {{
            background: #1a237e;
            color: white;
            padding: 10px 8px;
            text-align: left;
            position: sticky;
            top: 0;
            z-index: 10;
        }}
        td {{
            padding: 8px;
            border-bottom: 1px solid #eee;
        }}
        tr:hover {{ background: #f5f5f5; }}
        .positive {{ color: #2e7d32; font-weight: bold; }}
        .negative {{ color: #c62828; font-weight: bold; }}
        .tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
        }}
        .tag-single {{ background: #e3f2fd; color: #1565c0; }}
        .tag-multi {{ background: #f3e5f5; color: #7b1fa2; }}
        .scroll-table {{ max-height: 600px; overflow-y: auto; border-radius: 8px; border: 1px solid #e0e0e0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>多因子分批回测综合报告</h1>
            <div class="meta">
                生成时间: {generate_time} | A股量化分析系统<br>
                回测区间: 2017-2026 | 滚动窗口: 3年回测 + 1年验证
            </div>
        </div>

        {stats_html}

        <div class="section">
            <div class="section-title">回测结果明细</div>
            <div class="scroll-table">
                {table_html}
            </div>
        </div>

        <div class="section">
            <div class="section-title">可视化分析</div>
            {charts_html}
        </div>

        <div class="footer">
            <p>本报告由 A股量化分析系统 自动生成 | 数据仅供参考，不构成投资建议</p>
        </div>
    </div>
</body>
</html>"""

    def _build_stats_cards(self) -> str:
        """构建统计卡片"""
        if not self.all_results:
            return ""

        # 汇总统计
        single_results = [r for r in self.all_results if not r['is_multi']]
        multi_results = [r for r in self.all_results if r['is_multi']]

        def avg_metric(results, key):
            vals = [r['bt_performance'].get(key, 0) for r in results if r['bt_performance']]
            return np.mean(vals) if vals else 0

        # 最佳回测
        best_sharpe = max(
            self.all_results,
            key=lambda r: r['bt_performance'].get('sharpe_ratio', -999) if r['bt_performance'] else -999
        )

        return f"""
        <div class="section">
            <div class="section-title">概览统计</div>
            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 20px;">
                <div style="background: #e3f2fd; padding: 20px; border-radius: 12px; text-align: center;">
                    <div style="font-size: 36px; font-weight: bold; color: #1565c0;">{len(self.all_results)}</div>
                    <div style="color: #666;">总回测次数</div>
                </div>
                <div style="background: #e8f5e9; padding: 20px; border-radius: 12px; text-align: center;">
                    <div style="font-size: 36px; font-weight: bold; color: #2e7d32;">{len(single_results)}</div>
                    <div style="color: #666;">单因子回测</div>
                </div>
                <div style="background: #f3e5f5; padding: 20px; border-radius: 12px; text-align: center;">
                    <div style="font-size: 36px; font-weight: bold; color: #7b1fa2;">{len(multi_results)}</div>
                    <div style="color: #666;">多因子组合</div>
                </div>
                <div style="background: #fff3e0; padding: 20px; border-radius: 12px; text-align: center;">
                    <div style="font-size: 36px; font-weight: bold; color: #e65100;">{len(BATCHES)}</div>
                    <div style="color: #666;">滚动批次</div>
                </div>
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px;">
                <div style="background: #fafafa; padding: 20px; border-radius: 12px; border-left: 4px solid #1565c0;">
                    <div style="color: #666; font-size: 14px; margin-bottom: 5px;">平均夏普比率 (回测期)</div>
                    <div style="font-size: 28px; font-weight: bold; color: #1565c0;">
                        {avg_metric(self.all_results, 'sharpe_ratio'):.2f}
                    </div>
                </div>
                <div style="background: #fafafa; padding: 20px; border-radius: 12px; border-left: 4px solid #2e7d32;">
                    <div style="color: #666; font-size: 14px; margin-bottom: 5px;">平均年化收益 (回测期)</div>
                    <div style="font-size: 28px; font-weight: bold; color: #2e7d32;">
                        {avg_metric(self.all_results, 'annual_return'):.2%}
                    </div>
                </div>
                <div style="background: #fafafa; padding: 20px; border-radius: 12px; border-left: 4px solid #c62828;">
                    <div style="color: #666; font-size: 14px; margin-bottom: 5px;">平均最大回撤 (回测期)</div>
                    <div style="font-size: 28px; font-weight: bold; color: #c62828;">
                        {avg_metric(self.all_results, 'max_drawdown'):.2%}
                    </div>
                </div>
            </div>
            <div style="margin-top: 20px; padding: 15px; background: #e8f5e9; border-radius: 8px;">
                <strong>最佳回测:</strong> {best_sharpe.get('factor_label', 'N/A')} |
                批次{best_sharpe.get('batch_idx', 'N/A')} |
                夏普比率: {best_sharpe['bt_performance'].get('sharpe_ratio', 0):.2f} |
                年化收益: {best_sharpe['bt_performance'].get('annual_return', 0):.2%}
            </div>
        </div>
        """

    def _build_results_table(self) -> str:
        """构建结果明细表格"""
        header = """
        <table>
            <thead>
                <tr>
                    <th>序号</th>
                    <th>类型</th>
                    <th>因子</th>
                    <th>批次</th>
                    <th>回测区间</th>
                    <th>持仓数</th>
                    <th>调仓频率</th>
                    <th>多空</th>
                    <th>年化收益(回测)</th>
                    <th>夏普(回测)</th>
                    <th>最大回撤(回测)</th>
                    <th>年化收益(验证)</th>
                    <th>夏普(验证)</th>
                </tr>
            </thead>
            <tbody>
        """

        rows = ""
        for idx, r in enumerate(self.all_results, 1):
            bt_perf = r.get('bt_performance', {})
            val_perf = r.get('val_performance', {})

            tag_class = "tag-multi" if r['is_multi'] else "tag-single"
            tag_text = "多因子" if r['is_multi'] else "单因子"

            # 年化收益颜色
            bt_ar = bt_perf.get('annual_return', 0)
            val_ar = val_perf.get('annual_return', 0) if val_perf else None
            bt_ar_class = "positive" if bt_ar > 0 else "negative" if bt_ar < 0 else ""
            val_ar_class = "positive" if val_ar and val_ar > 0 else "negative" if val_ar and val_ar < 0 else ""

            val_ar_str = f"{val_ar:.2%}" if val_ar is not None else "-"
            val_sharpe = val_perf.get('sharpe_ratio', 0) if val_perf else None
            val_sharpe_str = f"{val_sharpe:.2f}" if val_sharpe is not None else "-"

            rows += f"""
            <tr>
                <td>{idx}</td>
                <td><span class="tag {tag_class}">{tag_text}</span></td>
                <td title="{r['factor_label']}">{r['factor_label'][:30]}</td>
                <td>{r['batch_idx']}</td>
                <td>{r['bt_start']}-{r['bt_end']}</td>
                <td>{r['params']['n_stocks']}</td>
                <td>{r['params']['rebalance_freq']}日</td>
                <td>{"是" if r['params']['long_short'] else "否"}</td>
                <td class="{bt_ar_class}">{bt_ar:.2%}</td>
                <td>{bt_perf.get('sharpe_ratio', 0):.2f}</td>
                <td class="negative">{bt_perf.get('max_drawdown', 0):.2%}</td>
                <td class="{val_ar_class}">{val_ar_str}</td>
                <td>{val_sharpe_str}</td>
            </tr>
            """

        return header + rows + "</tbody></table>"

    def _build_charts(self) -> str:
        """构建可视化图表"""
        charts = []

        # 1. 各批次平均年化收益对比（回测 vs 验证）
        charts.append(self._chart_batch_comparison())

        # 2. 因子类型夏普比率分布
        charts.append(self._chart_factor_type_sharpe())

        # 3. 回测vs验证散点图
        charts.append(self._chart_bt_vs_val_scatter())

        # 4. 参数敏感性分析
        charts.append(self._chart_param_sensitivity())

        return "\n".join(charts)

    def _chart_batch_comparison(self) -> str:
        """各批次平均年化收益对比图"""
        batch_stats = {}
        for r in self.all_results:
            batch = r['batch_idx']
            if batch not in batch_stats:
                batch_stats[batch] = {'bt_returns': [], 'val_returns': []}
            if r['bt_performance']:
                batch_stats[batch]['bt_returns'].append(r['bt_performance'].get('annual_return', 0))
            if r['val_performance']:
                batch_stats[batch]['val_returns'].append(r['val_performance'].get('annual_return', 0))

        x_data = [f"批次{b}" for b in sorted(batch_stats.keys())]
        bt_data = [np.mean(batch_stats[b]['bt_returns']) * 100 if batch_stats[b]['bt_returns'] else 0
                    for b in sorted(batch_stats.keys())]
        val_data = [np.mean(batch_stats[b]['val_returns']) * 100 if batch_stats[b]['val_returns'] else 0
                     for b in sorted(batch_stats.keys())]

        chart_id = "chart_batch_comparison"

        return f"""
        <div class="chart-container" id="{chart_id}" style="height: 400px;"></div>
        <script>
        (function() {{
            var chart = echarts.init(document.getElementById('{chart_id}'));
            chart.setOption({{
                title: {{ text: '各批次平均年化收益对比', left: 'center' }},
                tooltip: {{ trigger: 'axis' }},
                legend: {{ data: ['回测期', '验证期'], top: '8%' }},
                xAxis: {{ type: 'category', data: {json.dumps(x_data)} }},
                yAxis: {{ type: 'value', name: '年化收益(%)', axisLabel: {{ formatter: '{{value}}%' }} }},
                series: [
                    {{
                        name: '回测期',
                        type: 'bar',
                        data: {json.dumps([round(v, 2) for v in bt_data])},
                        itemStyle: {{ color: '#5470c6' }}
                    }},
                    {{
                        name: '验证期',
                        type: 'bar',
                        data: {json.dumps([round(v, 2) for v in val_data])},
                        itemStyle: {{ color: '#91cc75' }}
                    }}
                ],
                grid: {{ bottom: '15%', left: '10%', right: '5%' }}
            }});
            window.addEventListener('resize', function() {{ chart.resize(); }});
        }})();
        </script>
        """

    def _chart_factor_type_sharpe(self) -> str:
        """因子类型夏普比率分布"""
        type_sharpes = {}
        for r in self.all_results:
            ftype = r['factor_type']
            if ftype not in type_sharpes:
                type_sharpes[ftype] = []
            if r['bt_performance']:
                type_sharpes[ftype].append(r['bt_performance'].get('sharpe_ratio', 0))

        type_names = {
            'momentum': '动量类',
            'mean_reversion': '均值回复类',
            'volatility': '波动率类',
            'volume_anomaly': '成交量异常',
            'correlation': '相关性类',
        }

        categories = [type_names.get(k, k) for k in type_sharpes.keys()]
        data = []
        for k, v in type_sharpes.items():
            avg_val = np.mean(v) if v else 0
            data.append({'value': round(avg_val, 2), 'name': type_names.get(k, k)})

        chart_id = "chart_factor_type_sharpe"

        return f"""
        <div class="chart-container" id="{chart_id}" style="height: 400px;"></div>
        <script>
        (function() {{
            var chart = echarts.init(document.getElementById('{chart_id}'));
            chart.setOption({{
                title: {{ text: '各因子类型平均夏普比率', left: 'center' }},
                tooltip: {{ trigger: 'axis' }},
                xAxis: {{
                    type: 'category',
                    data: {json.dumps(categories)},
                    axisLabel: {{ rotate: 15 }}
                }},
                yAxis: {{ type: 'value', name: '夏普比率' }},
                series: [{{
                    type: 'bar',
                    data: {json.dumps(data)},
                    itemStyle: {{
                        color: function(params) {{
                            var colors = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de'];
                            return colors[params.dataIndex % colors.length];
                        }}
                    }},
                    label: {{
                        show: true,
                        position: 'top',
                        formatter: '{{c}}'
                    }}
                }}],
                grid: {{ bottom: '20%', left: '10%', right: '5%' }}
            }});
            window.addEventListener('resize', function() {{ chart.resize(); }});
        }})();
        </script>
        """

    def _chart_bt_vs_val_scatter(self) -> str:
        """回测vs验证年化收益散点图"""
        scatter_data = []
        for r in self.all_results:
            if r['bt_performance'] and r['val_performance']:
                bt_ar = r['bt_performance'].get('annual_return', 0) * 100
                val_ar = r['val_performance'].get('annual_return', 0) * 100
                scatter_data.append({
                    'x': round(bt_ar, 2),
                    'y': round(val_ar, 2),
                    'label': r['factor_label'][:20],
                    'batch': r['batch_idx']
                })

        chart_id = "chart_bt_vs_val"

        return f"""
        <div class="chart-container" id="{chart_id}" style="height: 450px;"></div>
        <script>
        (function() {{
            var chart = echarts.init(document.getElementById('{chart_id}'));
            var data = {json.dumps(scatter_data)};
            chart.setOption({{
                title: {{ text: '回测期 vs 验证期 年化收益', left: 'center' }},
                tooltip: {{
                    formatter: function(p) {{
                        return p.data.label + '<br/>批次' + p.data.batch +
                            '<br/>回测: ' + p.data.x + '%<br/>验证: ' + p.data.y + '%';
                    }}
                }},
                xAxis: {{ type: 'value', name: '回测期年化收益(%)',
                    splitLine: {{ lineStyle: {{ type: 'dashed' }} }} }},
                yAxis: {{ type: 'value', name: '验证期年化收益(%)',
                    splitLine: {{ lineStyle: {{ type: 'dashed' }} }} }},
                series: [{{
                    type: 'scatter',
                    data: data,
                    symbolSize: 10,
                    itemStyle: {{ color: '#5470c6', opacity: 0.7 }},
                    markLine: {{
                        data: [
                            [{{'coord': [-100, -100]}}, {{'coord': [100, 100]}}]
                        ],
                        lineStyle: {{ type: 'dashed', color: '#999' }},
                        label: {{ show: false }}
                    }}
                }}],
                grid: {{ bottom: '15%', left: '12%', right: '5%' }}
            }});
            window.addEventListener('resize', function() {{ chart.resize(); }});
        }})();
        </script>
        """

    def _chart_param_sensitivity(self) -> str:
        """参数敏感性分析图"""
        # 按持仓数分组的平均夏普
        nstocks_sharpe = {}
        freq_sharpe = {}
        for r in self.all_results:
            if not r['bt_performance']:
                continue
            ns = r['params']['n_stocks']
            freq = r['params']['rebalance_freq']
            sharpe = r['bt_performance'].get('sharpe_ratio', 0)

            nstocks_sharpe.setdefault(ns, []).append(sharpe)
            freq_sharpe.setdefault(freq, []).append(sharpe)

        ns_categories = [str(k) for k in sorted(nstocks_sharpe.keys())]
        ns_data = [round(np.mean(v), 2) for v in [nstocks_sharpe[k] for k in sorted(nstocks_sharpe.keys())]]

        freq_categories = [f"{k}日" for k in sorted(freq_sharpe.keys())]
        freq_data = [round(np.mean(v), 2) for v in [freq_sharpe[k] for k in sorted(freq_sharpe.keys())]]

        chart_id = "chart_param_sensitivity"

        return f"""
        <div class="chart-container" id="{chart_id}" style="height: 400px;"></div>
        <script>
        (function() {{
            var chart = echarts.init(document.getElementById('{chart_id}'));
            chart.setOption({{
                title: {{ text: '参数敏感性分析（平均夏普比率）', left: 'center' }},
                tooltip: {{ trigger: 'axis' }},
                legend: {{ data: ['持仓数', '调仓频率'], top: '8%' }},
                grid: [
                    {{ left: '8%', top: '20%', width: '40%', height: '60%' }},
                    {{ right: '8%', top: '20%', width: '40%', height: '60%' }}
                ],
                xAxis: [
                    {{ type: 'category', data: {json.dumps(ns_categories)}, gridIndex: 0, name: '持仓数' }},
                    {{ type: 'category', data: {json.dumps(freq_categories)}, gridIndex: 1, name: '调仓频率' }}
                ],
                yAxis: [
                    {{ type: 'value', name: '夏普比率', gridIndex: 0 }},
                    {{ type: 'value', name: '夏普比率', gridIndex: 1 }}
                ],
                series: [
                    {{
                        name: '持仓数',
                        type: 'bar',
                        data: {json.dumps(ns_data)},
                        xAxisIndex: 0,
                        yAxisIndex: 0,
                        itemStyle: {{ color: '#5470c6' }}
                    }},
                    {{
                        name: '调仓频率',
                        type: 'bar',
                        data: {json.dumps(freq_data)},
                        xAxisIndex: 1,
                        yAxisIndex: 1,
                        itemStyle: {{ color: '#91cc75' }}
                    }}
                ]
            }});
            window.addEventListener('resize', function() {{ chart.resize(); }});
        }})();
        </script>
        """


# ==================== 主入口 ====================

def main():
    """主函数"""
    logger.info("多因子分批回测引擎启动")

    engine = MultiFactorBacktester(
        db_path=DB_PATH,
        report_dir=REPORT_DIR,
        initial_capital=1_000_000,
        seed=42,  # 固定随机种子，便于复现
    )

    # 执行全部回测
    engine.run_all()

    # 生成综合报告
    report_path = engine.generate_summary_report()

    if report_path:
        logger.info(f"报告已保存到: {report_path}")
    else:
        logger.warning("报告生成失败")

    logger.info("全部完成!")


if __name__ == '__main__':
    main()
