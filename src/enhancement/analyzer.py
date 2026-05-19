"""
指数增强核心分析器
================

整合所有分析维度，提供全面的指数增强分析。
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .metrics import MetricsCalculator
from .attribution import AttributionAnalyzer

logger = logging.getLogger(__name__)


class IndexEnhancementAnalyzer:
    """
    指数增强分析器

    提供10个维度的全面分析：
    1. 收益分析
    2. 行业偏离分析
    3. 市值偏离分析
    4. 个股偏离分析
    5. 因子暴露分析
    6. 跟踪误差与信息比率
    7. Beta与Alpha分析
    8. 盈利能力分析
    9. 风险调整后收益
    10. 回撤与尾部风险
    """

    def __init__(self, db_manager, benchmark_code: str = '000300.SH', execution_logger=None):
        self.db = db_manager
        self.benchmark_code = benchmark_code
        self.execution_logger = execution_logger
        self.metrics = MetricsCalculator()
        self.attribution = AttributionAnalyzer()

    def analyze(
        self,
        portfolio_weights: pd.DataFrame,
        start_date: str,
        end_date: str,
        portfolio_id: str = 'default'
    ) -> Dict:
        """
        执行完整的指数增强分析

        Parameters
        ----------
        portfolio_weights : pd.DataFrame
            组合权重数据，列: trade_date, stock_code, weight
        start_date : str
            开始日期
        end_date : str
            结束日期
        portfolio_id : str
            组合标识

        Returns
        -------
        Dict
            完整分析结果
        """
        print(f"\n{'='*50}")
        print(f"指数增强分析: {portfolio_id} vs {self.benchmark_code}")
        print(f"分析区间: {start_date} ~ {end_date}")
        print(f"{'='*50}")

        # 1. 加载数据
        stock_returns, benchmark_returns, constituent_data, industry_map = self._load_data(
            portfolio_weights, start_date, end_date
        )

        # 2. 计算组合日收益
        portfolio_returns = self._calculate_portfolio_returns(portfolio_weights, stock_returns)

        # 3. 对齐日期
        portfolio_returns, benchmark_returns = self._align_returns(
            portfolio_returns, benchmark_returns
        )

        # 4. 执行各维度分析
        results = {
            'portfolio_id': portfolio_id,
            'benchmark_code': self.benchmark_code,
            'start_date': start_date,
            'end_date': end_date,
        }

        # 维度1-7, 9-10: 指标分析
        full_metrics = self.metrics.full_analysis(portfolio_returns, benchmark_returns)
        results.update(full_metrics)

        # 维度2-4: 偏离分析
        results['deviation'] = self._analyze_deviations(
            portfolio_weights, constituent_data, start_date, end_date
        )

        # 维度5: 因子暴露
        results['factor_exposure'] = self._analyze_factor_exposure(
            portfolio_weights, constituent_data, start_date, end_date
        )

        # 维度8: 盈利能力
        results['profitability'] = self._analyze_profitability(
            portfolio_weights, constituent_data, start_date, end_date
        )

        # Brinson归因
        if industry_map:
            latest_date = str(portfolio_weights['trade_date'].max())[:10]
            latest_pw = portfolio_weights[portfolio_weights['trade_date'] == latest_date][['stock_code', 'weight']].copy()
            latest_bw = constituent_data[constituent_data['trade_date'] == latest_date][['stock_code', 'weight']].copy()
            latest_ret = stock_returns.reset_index()
            if 'trade_date' in latest_ret.columns:
                latest_ret = latest_ret[latest_ret['trade_date'] == latest_date][['stock_code', 'close']].copy()
                latest_ret.columns = ['stock_code', 'return']
                if len(latest_ret) > 1:
                    latest_ret['return'] = latest_ret['return'].pct_change().fillna(0)

            if not latest_ret.empty and len(latest_ret) > 1:
                brinson = self.attribution.brinson_attribution(
                    latest_pw, latest_bw, latest_ret, industry_map
                )
                results['brinson_attribution'] = brinson

        # 打印结果
        self._print_results(results)

        # 保存到数据库
        self._save_results(results, portfolio_id)

        # 记录执行日志
        if self.execution_logger:
            self._log_execution(results, portfolio_id)

        return results

    def _load_data(self, portfolio_weights, start_date, end_date):
        """加载分析所需数据"""
        # 获取股票日频数据
        stock_codes = portfolio_weights['stock_code'].unique().tolist()
        stock_daily = self.db.get_stock_daily(
            stock_codes=stock_codes,
            start_date=start_date,
            end_date=end_date
        )

        # 数据有效性检查：过滤掉没有行情数据的股票代码
        if not stock_daily.empty and isinstance(stock_daily.index, pd.MultiIndex):
            available_codes = stock_daily.index.get_level_values('stock_code').unique().tolist()
            missing_codes = [c for c in stock_codes if c not in available_codes]
            if missing_codes:
                logger.warning(f"以下股票在{start_date}~{end_date}期间无行情数据，已跳过: {missing_codes}")
                stock_codes = available_codes

        # 获取指数日频数据
        index_daily = self.db.get_index_daily(
            index_codes=[self.benchmark_code],
            start_date=start_date,
            end_date=end_date
        )

        if index_daily.empty:
            logger.warning(f"基准指数 {self.benchmark_code} 在{start_date}~{end_date}期间无数据")

        # 获取成分股数据
        constituent = self.db.get_index_constituent_history(
            index_code=self.benchmark_code,
            start_date=start_date,
            end_date=end_date
        )

        # 获取行业映射
        stock_info = self.db.get_stock_info()
        industry_map = dict(zip(stock_info['stock_code'], stock_info['industry'])) if not stock_info.empty else {}

        # 计算收益率
        if not stock_daily.empty and isinstance(stock_daily.index, pd.MultiIndex):
            stock_returns = stock_daily['close'].groupby(level='stock_code').pct_change()
        else:
            stock_returns = pd.Series(dtype=float)

        if not index_daily.empty and isinstance(index_daily.index, pd.MultiIndex):
            # 按index_code分组计算收益率
            benchmark_returns = index_daily['close'].groupby(level='index_code').pct_change()
            # index_daily的MultiIndex是(trade_date, index_code)，groupby后level顺序不变
            # 需要在正确的level上查找index_code
            idx_level_names = benchmark_returns.index.names
            code_level = idx_level_names.index('index_code') if 'index_code' in idx_level_names else 1
            if self.benchmark_code in benchmark_returns.index.get_level_values(code_level):
                benchmark_returns = benchmark_returns.xs(self.benchmark_code, level=code_level)
                # xs()后确保索引是简单的Timestamp，不是tuple
                if isinstance(benchmark_returns.index, pd.MultiIndex):
                    benchmark_returns = benchmark_returns.reset_index(level='index_code', drop=True)
                benchmark_returns.index.name = 'trade_date'
            else:
                benchmark_returns = pd.Series(dtype=float)
        else:
            benchmark_returns = pd.Series(dtype=float)

        return stock_returns, benchmark_returns, constituent, industry_map

    def _calculate_portfolio_returns(self, portfolio_weights, stock_returns):
        """计算组合日收益"""
        if stock_returns.empty:
            return pd.Series(dtype=float)

        # 将portfolio_weights的日期转为与stock_returns一致的格式
        pw = portfolio_weights.copy()
        if 'trade_date' in pw.columns:
            pw['trade_date'] = pd.to_datetime(pw['trade_date'])

        # 获取所有交易日
        trade_dates = sorted(pw['trade_date'].unique())

        # 获取stock_returns的日期范围
        if not stock_returns.empty and isinstance(stock_returns.index, pd.MultiIndex):
            available_dates = stock_returns.index.get_level_values('trade_date').unique()
            trade_dates = [d for d in trade_dates if d in available_dates]

        returns_list = []

        for trade_date in trade_dates:
            day_group = pw[pw['trade_date'] == trade_date]
            daily_ret = 0.0
            total_weight = 0.0

            for _, row in day_group.iterrows():
                stock_code = row['stock_code']
                weight = row['weight']
                try:
                    ret = stock_returns.xs((trade_date, stock_code))
                    if not np.isnan(ret):
                        daily_ret += weight * ret
                        total_weight += weight
                except (KeyError, TypeError):
                    continue

            if total_weight > 0:
                returns_list.append({'trade_date': trade_date, 'return': daily_ret})

        if returns_list:
            df = pd.DataFrame(returns_list).set_index('trade_date')['return']
            return df.sort_index()
        return pd.Series(dtype=float)

    def _align_returns(self, portfolio_returns, benchmark_returns):
        """对齐组合和基准收益率"""
        if portfolio_returns.empty or benchmark_returns.empty:
            return portfolio_returns, benchmark_returns

        # 统一为Timestamp索引
        p_result = portfolio_returns.copy()
        p_result.index = pd.to_datetime(p_result.index)

        b_result = benchmark_returns.copy()
        b_result.index = pd.to_datetime(b_result.index)

        # 如果benchmark仍然是MultiIndex，取第一个level作为日期
        if isinstance(b_result.index, pd.MultiIndex):
            b_result = b_result.reset_index(level=list(range(1, b_result.index.nlevels)), drop=True)
            b_result.index = pd.to_datetime(b_result.index)

        common_idx = p_result.index.intersection(b_result.index)

        if len(common_idx) == 0:
            logger.warning(f"日期对齐失败: portfolio日期范围={p_result.index.min()}~{p_result.index.max()}, "
                          f"benchmark日期范围={b_result.index.min()}~{b_result.index.max()}")
            return p_result, b_result

        return p_result.loc[common_idx], b_result.loc[common_idx]

    def _analyze_deviations(self, portfolio_weights, constituent_data, start_date, end_date):
        """分析行业、市值、个股偏离"""
        result = {}

        # 获取最新的权重数据进行偏离分析
        latest_date = str(portfolio_weights['trade_date'].max())[:10]

        pw = portfolio_weights[portfolio_weights['trade_date'] == latest_date][['stock_code', 'weight']].copy()
        bw = constituent_data[constituent_data['trade_date'] == latest_date][['stock_code', 'weight']].copy()

        # 合并
        merged = pw.merge(bw, on='stock_code', how='outer', suffixes=('_p', '_b')).fillna(0)

        # 个股偏离
        merged['deviation'] = merged['weight_p'] - merged['weight_b']
        top_overweight = merged.nlargest(5, 'deviation')[['stock_code', 'weight_p', 'weight_b', 'deviation']]
        top_underweight = merged.nsmallest(5, 'deviation')[['stock_code', 'weight_p', 'weight_b', 'deviation']]

        result['stock_deviation'] = {
            'top_overweight': top_overweight.to_dict('records'),
            'top_underweight': top_underweight.to_dict('records'),
            'active_weight': merged[~merged['stock_code'].isin(bw['stock_code'])]['weight_p'].sum(),
        }

        # 市值偏离
        if 'market_cap' in constituent_data.columns:
            cap_data = constituent_data[constituent_data['trade_date'] == latest_date][['stock_code', 'market_cap']]
            cap_merged = pw.merge(cap_data, on='stock_code', how='left')
            cap_merged_bw = bw.merge(cap_data, on='stock_code', how='left')

            port_avg_cap = (cap_merged['weight'] * cap_merged['market_cap'].fillna(0)).sum()
            bench_avg_cap = (cap_merged_bw['weight'] * cap_merged_bw['market_cap'].fillna(0)).sum()

            result['market_cap'] = {
                'portfolio_avg_cap': round(port_avg_cap, 2),
                'benchmark_avg_cap': round(bench_avg_cap, 2),
                'deviation': round(port_avg_cap - bench_avg_cap, 2),
            }

        # 估值偏离
        if 'pe_ratio' in constituent_data.columns:
            pe_data = constituent_data[constituent_data['trade_date'] == latest_date][['stock_code', 'pe_ratio']]
            pe_merged = pw.merge(pe_data, on='stock_code', how='left')
            pe_merged_bw = bw.merge(pe_data, on='stock_code', how='left')

            port_avg_pe = (pe_merged['weight'] * pe_merged['pe_ratio'].fillna(0)).sum()
            bench_avg_pe = (pe_merged_bw['weight'] * pe_merged_bw['pe_ratio'].fillna(0)).sum()

            result['valuation'] = {
                'portfolio_avg_pe': round(port_avg_pe, 2),
                'benchmark_avg_pe': round(bench_avg_pe, 2),
                'deviation': round(port_avg_pe - bench_avg_pe, 2),
            }

        return result

    def _analyze_factor_exposure(self, portfolio_weights, constituent_data, start_date, end_date):
        """分析因子暴露"""
        latest_date = str(portfolio_weights['trade_date'].max())[:10]

        pw = portfolio_weights[portfolio_weights['trade_date'] == latest_date][['stock_code', 'weight']].copy()
        bw = constituent_data[constituent_data['trade_date'] == latest_date][['stock_code', 'weight']].copy()

        factors = {}

        # PE因子暴露
        if 'pe_ratio' in constituent_data.columns:
            pe_data = constituent_data[constituent_data['trade_date'] == latest_date][['stock_code', 'pe_ratio']]
            pe_pw = pw.merge(pe_data, on='stock_code', how='left')
            pe_bw = bw.merge(pe_data, on='stock_code', how='left')

            port_pe = (pe_pw['weight'] * pe_pw['pe_ratio'].fillna(0)).sum()
            bench_pe = (pe_bw['weight'] * pe_bw['pe_ratio'].fillna(0)).sum()
            factors['PE'] = {
                'portfolio': round(port_pe, 2),
                'benchmark': round(bench_pe, 2),
                'active': round(port_pe - bench_pe, 2),
            }

        # PB因子暴露
        if 'pb_ratio' in constituent_data.columns:
            pb_data = constituent_data[constituent_data['trade_date'] == latest_date][['stock_code', 'pb_ratio']]
            pb_pw = pw.merge(pb_data, on='stock_code', how='left')
            pb_bw = bw.merge(pb_data, on='stock_code', how='left')

            port_pb = (pb_pw['weight'] * pb_pw['pb_ratio'].fillna(0)).sum()
            bench_pb = (pb_bw['weight'] * pb_bw['pb_ratio'].fillna(0)).sum()
            factors['PB'] = {
                'portfolio': round(port_pb, 2),
                'benchmark': round(bench_pb, 2),
                'active': round(port_pb - bench_pb, 2),
            }

        return factors

    def _analyze_profitability(self, portfolio_weights, constituent_data, start_date, end_date):
        """分析盈利能力"""
        # 基于PE/PB间接评估盈利能力
        result = {}

        latest_date = str(portfolio_weights['trade_date'].max())[:10]
        pw = portfolio_weights[portfolio_weights['trade_date'] == latest_date][['stock_code', 'weight']].copy()
        bw = constituent_data[constituent_data['trade_date'] == latest_date][['stock_code', 'weight']].copy()

        if 'pe_ratio' in constituent_data.columns:
            pe_data = constituent_data[constituent_data['trade_date'] == latest_date][['stock_code', 'pe_ratio']]
            pe_pw = pw.merge(pe_data, on='stock_code', how='left')
            pe_bw = bw.merge(pe_data, on='stock_code', how='left')

            # 低PE通常意味着更高的盈利收益率
            port_earnings_yield = 1.0 / (pe_pw['pe_ratio'].clip(lower=1).mean())
            bench_earnings_yield = 1.0 / (pe_bw['pe_ratio'].clip(lower=1).mean())

            result['earnings_yield'] = {
                'portfolio': round(port_earnings_yield, 4),
                'benchmark': round(bench_earnings_yield, 4),
                'active': round(port_earnings_yield - bench_earnings_yield, 4),
            }

        return result

    def _print_results(self, results):
        """打印分析结果"""
        print(f"\n--- 收益分析 ---")
        print(f"  超额收益: {results.get('excess_return', 0):.2%}")
        print(f"  累计Alpha: {results.get('cumulative_alpha', 0):.2%}")
        print(f"  胜率: {results.get('win_rate', 0):.1%}")
        print(f"  盈亏比: {results.get('profit_loss_ratio', 0):.2f}")

        print(f"\n--- 风险指标 ---")
        print(f"  跟踪误差: {results.get('tracking_error', 0):.2%}")
        print(f"  信息比率: {results.get('information_ratio', 0):.2f}")
        print(f"  Beta: {results.get('beta', 1):.4f}")
        print(f"  Alpha: {results.get('alpha', 0):.2%}")
        print(f"  下行Beta: {results.get('downside_beta', 1):.4f}")

        print(f"\n--- 风险调整后收益 ---")
        print(f"  夏普比率: {results.get('sharpe_ratio', 0):.2f}")
        print(f"  索提诺比率: {results.get('sortino_ratio', 0):.2f}")
        print(f"  卡玛比率: {results.get('calmar_ratio', 0):.2f}")

        print(f"\n--- 回撤与尾部风险 ---")
        print(f"  最大回撤: {results.get('max_drawdown', 0):.2%}")
        print(f"  最大相对回撤: {results.get('max_relative_drawdown', 0):.2%}")
        print(f"  VaR(95%): {results.get('var_95', 0):.2%}")
        print(f"  CVaR(95%): {results.get('cvar_95', 0):.2%}")

        if 'factor_exposure' in results and results['factor_exposure']:
            print(f"\n--- 因子暴露 ---")
            for name, data in results['factor_exposure'].items():
                print(f"  {name}: 组合={data.get('portfolio', 0)}, 基准={data.get('benchmark', 0)}, 主动={data.get('active', 0):+.2f}")

        if 'deviation' in results:
            dev = results['deviation']
            if 'valuation' in dev:
                v = dev['valuation']
                print(f"\n--- 估值偏离 ---")
                print(f"  PE: 组合={v.get('portfolio_avg_pe', 0)}, 基准={v.get('benchmark_avg_pe', 0)}, 偏离={v.get('deviation', 0):+.2f}")

        if 'brinson_attribution' in results:
            ba = results['brinson_attribution']
            print(f"\n--- Brinson归因 ---")
            print(f"  配置效应: {ba.get('allocation_effect', 0):+.2%} ({ba.get('allocation_pct', 0):.1f}%)")
            print(f"  选择效应: {ba.get('selection_effect', 0):+.2%} ({ba.get('selection_pct', 0):.1f}%)")
            print(f"  交互效应: {ba.get('interaction_effect', 0):+.2%}")
            print(f"  总超额收益: {ba.get('total_excess_return', 0):+.2%}")

    def _save_results(self, results, portfolio_id):
        """保存分析结果到数据库"""
        try:
            self.db.insert_portfolio_analysis({
                'analysis_date': results.get('end_date', ''),
                'portfolio_id': portfolio_id,
                'benchmark_code': self.benchmark_code,
                'portfolio_return': results.get('cumulative_alpha', 0) + 1,  # 近似
                'benchmark_return': 1.0,
                'excess_return': results.get('excess_return', 0),
                'tracking_error': results.get('tracking_error', 0),
                'information_ratio': results.get('information_ratio', 0),
                'beta': results.get('beta', 1),
                'alpha': results.get('alpha', 0),
                'max_drawdown': results.get('max_drawdown', 0),
                'max_relative_drawdown': results.get('max_relative_drawdown', 0),
                'attribution_data': results.get('brinson_attribution'),
            })
            print(f"\n  分析结果已保存到数据库")
        except Exception as e:
            logger.error(f"保存分析结果失败: {e}")

    def _log_execution(self, results, portfolio_id):
        """记录执行日志"""
        try:
            self.execution_logger.db.log_execution(
                execution_type='enhancement_analysis',
                factor_name=portfolio_id,
                start_date=results.get('start_date'),
                end_date=results.get('end_date'),
                excess_return=results.get('excess_return'),
                tracking_error=results.get('tracking_error'),
                ir=results.get('information_ratio'),
                beta=results.get('beta'),
                alpha=results.get('alpha'),
                max_drawdown=results.get('max_drawdown'),
                status='success',
                details={
                    'win_rate': results.get('win_rate'),
                    'sharpe': results.get('sharpe_ratio'),
                    'sortino': results.get('sortino_ratio'),
                    'calmar': results.get('calmar_ratio'),
                }
            )
        except Exception as e:
            logger.error(f"记录执行日志失败: {e}")
