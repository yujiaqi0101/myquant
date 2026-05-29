"""
收益归因分析
============

实现Brinson归因模型和因子归因分析。
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional


class AttributionAnalyzer:
    """
    收益归因分析器

    将超额收益分解为配置效应、选择效应和交互效应。
    """

    def brinson_attribution(
        self,
        portfolio_weights: pd.DataFrame,
        benchmark_weights: pd.DataFrame,
        stock_returns: pd.DataFrame,
        industry_mapping: Dict[str, str]
    ) -> Dict:
        """
        Brinson归因分析

        Parameters
        ----------
        portfolio_weights : pd.DataFrame
            组合权重，列: stock_code, weight
        benchmark_weights : pd.DataFrame
            基准权重，列: stock_code, weight
        stock_returns : pd.DataFrame
            股票收益率，列: stock_code, return
        industry_mapping : Dict[str, str]
            股票到行业的映射

        Returns
        -------
        Dict
            归因分析结果
        """
        # 合并数据
        port = portfolio_weights.set_index('stock_code')['weight'] if 'stock_code' in portfolio_weights.columns else portfolio_weights
        bench = benchmark_weights.set_index('stock_code')['weight'] if 'stock_code' in benchmark_weights.columns else benchmark_weights
        rets = stock_returns.set_index('stock_code')['return'] if 'stock_code' in stock_returns.columns else stock_returns

        # 构建分析DataFrame
        analysis = pd.DataFrame({
            'w_p': port,
            'w_b': bench.reindex(port.index).fillna(0),
            'r': rets.reindex(port.index).fillna(0),
        })
        analysis['industry'] = analysis.index.map(lambda x: industry_mapping.get(x, '未知'))

        # 计算组合收益和基准收益
        portfolio_return = (analysis['w_p'] * analysis['r']).sum()
        benchmark_return = (analysis['w_b'] * analysis['r']).sum()
        excess_return = portfolio_return - benchmark_return

        # 按行业汇总
        industry_port = analysis.groupby('industry')['w_p'].sum()
        industry_bench = analysis.groupby('industry')['w_b'].sum()
        industry_ret = analysis.groupby('industry').apply(
            lambda x: (x['w_b'] * x['r']).sum() / (x['w_b'].sum() + 1e-10)
        )

        # 配置效应：行业权重的偏离 × 行业基准收益
        allocation_effect = ((industry_port - industry_bench) * industry_ret).sum()

        # 选择效应：行业内个股选择 × 行业组合权重
        selection_effect = 0.0
        for industry, group in analysis.groupby('industry'):
            w_p_i = group['w_p'].sum()
            w_b_i = group['w_b'].sum()
            if w_b_i > 1e-10:
                r_b_i = (group['w_b'] * group['r']).sum() / w_b_i
                r_p_i = (group['w_p'] * group['r']).sum() / (w_p_i + 1e-10)
                selection_effect += w_b_i * (r_p_i - r_b_i)

        # 交互效应
        interaction_effect = excess_return - allocation_effect - selection_effect

        # 行业偏离详情
        industry_deviation = pd.DataFrame({
            'portfolio_weight': industry_port,
            'benchmark_weight': industry_bench,
            'deviation': industry_port - industry_bench,
        }).sort_values('deviation', ascending=False)

        return {
            'total_excess_return': excess_return,
            'allocation_effect': allocation_effect,
            'selection_effect': selection_effect,
            'interaction_effect': interaction_effect,
            'portfolio_return': portfolio_return,
            'benchmark_return': benchmark_return,
            'industry_deviation': industry_deviation,
            'allocation_pct': allocation_effect / excess_return * 100 if abs(excess_return) > 1e-10 else 0,
            'selection_pct': selection_effect / excess_return * 100 if abs(excess_return) > 1e-10 else 0,
        }

    def factor_attribution(
        self,
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
        factor_exposures: pd.DataFrame
    ) -> Dict:
        """
        因子归因分析

        Parameters
        ----------
        portfolio_returns : pd.Series
            组合日收益率
        benchmark_returns : pd.Series
            基准日收益率
        factor_exposures : pd.DataFrame
            因子暴露数据，列: factor_name, active_exposure

        Returns
        -------
        Dict
            因子归因结果
        """
        excess = portfolio_returns - benchmark_returns

        result = {
            'total_excess_return': excess.mean() * 252,
            'factors': {},
        }

        for _, row in factor_exposures.iterrows():
            factor_name = row['factor_name']
            active_exp = row['active_exposure']
            # 简化：假设因子暴露贡献 = 暴露 × 某个因子收益
            # 实际中需要因子收益数据，这里用简化模型
            factor_contribution = active_exp * excess.mean() * 252 * 0.3
            result['factors'][factor_name] = {
                'active_exposure': active_exp,
                'contribution': factor_contribution,
            }

        return result

    def sector_contribution(
        self,
        portfolio_weights: pd.DataFrame,
        benchmark_weights: pd.DataFrame,
        stock_returns: pd.DataFrame,
        industry_mapping: Dict[str, str]
    ) -> pd.DataFrame:
        """
        计算各行业对超额收益的贡献

        Returns
        -------
        pd.DataFrame
            行业贡献明细
        """
        port = portfolio_weights.copy()
        port['industry'] = port['stock_code'].map(lambda x: industry_mapping.get(x, '未知'))
        bench = benchmark_weights.copy()
        bench['industry'] = bench['stock_code'].map(lambda x: industry_mapping.get(x, '未知'))
        rets = stock_returns.copy()

        # 合并
        port = port.set_index('stock_code')
        bench = bench.set_index('stock_code')
        rets = rets.set_index('stock_code') if 'stock_code' in rets.columns else rets

        merged = pd.DataFrame({
            'w_p': port['weight'],
            'w_b': bench['weight'].reindex(port.index).fillna(0),
            'r': rets.reindex(port.index).fillna(0),
            'industry': port['industry'],
        })

        # 按行业计算
        sector_result = []
        for industry, group in merged.groupby('industry'):
            w_p = group['w_p'].sum()
            w_b = group['w_b'].sum()
            r_p = (group['w_p'] * group['r']).sum() / (w_p + 1e-10)
            r_b = (group['w_b'] * group['r']).sum() / (w_b + 1e-10)
            contribution = w_p * r_p - w_b * r_b

            sector_result.append({
                'industry': industry,
                'portfolio_weight': w_p,
                'benchmark_weight': w_b,
                'weight_deviation': w_p - w_b,
                'portfolio_return': r_p,
                'benchmark_return': r_b,
                'contribution': contribution,
            })

        return pd.DataFrame(sector_result).sort_values('contribution', ascending=False)
