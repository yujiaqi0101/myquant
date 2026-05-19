"""
风控模块
========

提供风险管理功能，包括：
- 行业分散度控制
- 市值暴露控制
- 过拟合检测
"""

from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np


class RiskManager:
    """
    风险管理器
    
    综合管理投资组合的风险。
    """
    
    def __init__(
        self,
        max_industry_weight: float = 0.3,
        min_industries: int = 5,
        max_large_cap_bias: float = 0.2,
        max_small_cap_bias: float = 0.2,
        max_drawdown_limit: float = 0.15
    ):
        """
        初始化风险管理器
        
        Parameters
        ----------
        max_industry_weight : float
            单个行业最大权重
        min_industries : int
            最少覆盖行业数
        max_large_cap_bias : float
            大盘股最大偏离
        max_small_cap_bias : float
            小盘股最大偏离
        max_drawdown_limit : float
            最大回撤限制
        """
        self.max_industry_weight = max_industry_weight
        self.min_industries = min_industries
        self.max_large_cap_bias = max_large_cap_bias
        self.max_small_cap_bias = max_small_cap_bias
        self.max_drawdown_limit = max_drawdown_limit
    
    def check_industry_diversification(
        self,
        positions: Dict[str, float],
        industry_mapping: Dict[str, str]
    ) -> Dict:
        """
        检查行业分散度
        
        Parameters
        ----------
        positions : Dict[str, float]
            持仓权重，键为股票代码，值为权重
        industry_mapping : Dict[str, str]
            股票-行业映射
        
        Returns
        -------
        Dict
            检查结果
        """
        # 计算各行业权重
        industry_weights = {}
        total_weight = sum(positions.values())
        
        for stock_code, weight in positions.items():
            industry = industry_mapping.get(stock_code, 'Unknown')
            industry_weights[industry] = industry_weights.get(industry, 0) + weight / total_weight
        
        # 检查违规
        violations = []
        
        # 检查单行业权重
        for industry, weight in industry_weights.items():
            if weight > self.max_industry_weight:
                violations.append({
                    'type': 'industry_overweight',
                    'industry': industry,
                    'weight': weight,
                    'limit': self.max_industry_weight,
                })
        
        # 检查行业覆盖数
        if len(industry_weights) < self.min_industries:
            violations.append({
                'type': 'insufficient_industries',
                'current': len(industry_weights),
                'required': self.min_industries,
            })
        
        return {
            'passed': len(violations) == 0,
            'industry_weights': industry_weights,
            'n_industries': len(industry_weights),
            'violations': violations,
        }
    
    def check_market_cap_exposure(
        self,
        positions: Dict[str, float],
        market_cap_data: Dict[str, float],
        benchmark_weights: Optional[Dict[str, float]] = None
    ) -> Dict:
        """
        检查市值暴露
        
        Parameters
        ----------
        positions : Dict[str, float]
            持仓权重
        market_cap_data : Dict[str, float]
            股票-市值映射
        benchmark_weights : Dict[str, float], optional
            基准市值权重分布
        
        Returns
        -------
        Dict
            检查结果
        """
        # 市值分类阈值（亿元）
        large_cap_threshold = 500
        small_cap_threshold = 100
        
        # 计算各市值区间权重
        cap_weights = {'large': 0, 'mid': 0, 'small': 0}
        total_weight = sum(positions.values())
        
        for stock_code, weight in positions.items():
            market_cap = market_cap_data.get(stock_code, 0)
            
            if market_cap >= large_cap_threshold:
                cap_weights['large'] += weight / total_weight
            elif market_cap <= small_cap_threshold:
                cap_weights['small'] += weight / total_weight
            else:
                cap_weights['mid'] += weight / total_weight
        
        # 基准权重
        if benchmark_weights is None:
            benchmark_weights = {'large': 0.4, 'mid': 0.4, 'small': 0.2}
        
        # 计算偏离
        exposures = {}
        violations = []
        
        for cap_class in ['large', 'mid', 'small']:
            exposure = cap_weights[cap_class] - benchmark_weights.get(cap_class, 0)
            exposures[cap_class] = {
                'portfolio_weight': cap_weights[cap_class],
                'benchmark_weight': benchmark_weights.get(cap_class, 0),
                'exposure': exposure,
            }
            
            # 检查偏离
            if cap_class == 'large' and abs(exposure) > self.max_large_cap_bias:
                violations.append({
                    'type': 'large_cap_exposure',
                    'exposure': exposure,
                    'limit': self.max_large_cap_bias,
                })
            elif cap_class == 'small' and abs(exposure) > self.max_small_cap_bias:
                violations.append({
                    'type': 'small_cap_exposure',
                    'exposure': exposure,
                    'limit': self.max_small_cap_bias,
                })
        
        return {
            'passed': len(violations) == 0,
            'cap_weights': cap_weights,
            'exposures': exposures,
            'violations': violations,
        }
    
    def check_drawdown(
        self,
        portfolio_values: np.ndarray
    ) -> Dict:
        """
        检查回撤
        
        Parameters
        ----------
        portfolio_values : np.ndarray
            组合净值序列
        
        Returns
        -------
        Dict
            检查结果
        """
        # 计算最大回撤
        peak = portfolio_values[0]
        max_drawdown = 0
        current_drawdown = 0
        
        for value in portfolio_values:
            if value > peak:
                peak = value
            
            dd = (peak - value) / peak
            current_drawdown = dd
            
            if dd > max_drawdown:
                max_drawdown = dd
        
        violations = []
        if max_drawdown > self.max_drawdown_limit:
            violations.append({
                'type': 'max_drawdown_exceeded',
                'current': max_drawdown,
                'limit': self.max_drawdown_limit,
            })
        
        return {
            'passed': len(violations) == 0,
            'max_drawdown': max_drawdown,
            'current_drawdown': current_drawdown,
            'violations': violations,
        }
    
    def comprehensive_check(
        self,
        positions: Dict[str, float],
        industry_mapping: Dict[str, str],
        market_cap_data: Dict[str, float],
        portfolio_values: Optional[np.ndarray] = None
    ) -> Dict:
        """
        综合风控检查
        
        Parameters
        ----------
        positions : Dict[str, float]
            持仓权重
        industry_mapping : Dict[str, str]
            股票-行业映射
        market_cap_data : Dict[str, float]
            股票-市值映射
        portfolio_values : np.ndarray, optional
            组合净值序列
        
        Returns
        -------
        Dict
            综合检查结果
        """
        results = {
            'passed': True,
            'checks': {},
            'violations': [],
        }
        
        # 行业分散度检查
        industry_check = self.check_industry_diversification(positions, industry_mapping)
        results['checks']['industry_diversification'] = industry_check
        results['violations'].extend(industry_check['violations'])
        
        # 市值暴露检查
        cap_check = self.check_market_cap_exposure(positions, market_cap_data)
        results['checks']['market_cap_exposure'] = cap_check
        results['violations'].extend(cap_check['violations'])
        
        # 回撤检查
        if portfolio_values is not None:
            dd_check = self.check_drawdown(portfolio_values)
            results['checks']['drawdown'] = dd_check
            results['violations'].extend(dd_check['violations'])
        
        results['passed'] = len(results['violations']) == 0
        
        return results
    
    def suggest_rebalance(
        self,
        positions: Dict[str, float],
        industry_mapping: Dict[str, str]
    ) -> List[Dict]:
        """
        建议再平衡方案
        
        Parameters
        ----------
        positions : Dict[str, float]
            当前持仓权重
        industry_mapping : Dict[str, str]
            股票-行业映射
        
        Returns
        -------
        List[Dict]
            再平衡建议
        """
        suggestions = []
        
        # 检查行业分散度
        industry_check = self.check_industry_diversification(positions, industry_mapping)
        
        if not industry_check['passed']:
            for violation in industry_check['violations']:
                if violation['type'] == 'industry_overweight':
                    # 建议减持超配行业
                    industry = violation['industry']
                    excess_weight = violation['weight'] - self.max_industry_weight
                    
                    suggestions.append({
                        'action': 'reduce',
                        'target': 'industry',
                        'industry': industry,
                        'current_weight': violation['weight'],
                        'target_weight': self.max_industry_weight,
                        'adjustment': -excess_weight,
                        'reason': f'行业 {industry} 权重超限',
                    })
        
        return suggestions


class OverfittingDetector:
    """
    过拟合检测器
    
    检测策略是否过拟合。
    """
    
    def __init__(
        self,
        sharpe_decay_threshold: float = 0.5,
        pbo_threshold: float = 0.5
    ):
        """
        初始化过拟合检测器
        
        Parameters
        ----------
        sharpe_decay_threshold : float
            夏普比率衰减阈值
        pbo_threshold : float
            过拟合概率阈值
        """
        self.sharpe_decay_threshold = sharpe_decay_threshold
        self.pbo_threshold = pbo_threshold
    
    def detect_sharpe_decay(
        self,
        in_sample_sharpe: float,
        out_of_sample_sharpe: float
    ) -> Dict:
        """
        检测夏普比率衰减
        
        Parameters
        ----------
        in_sample_sharpe : float
            样本内夏普比率
        out_of_sample_sharpe : float
            样本外夏普比率
        
        Returns
        -------
        Dict
            检测结果
        """
        if in_sample_sharpe <= 0:
            return {
                'decay': 1.0,
                'is_overfitted': True,
                'in_sample_sharpe': in_sample_sharpe,
                'out_of_sample_sharpe': out_of_sample_sharpe,
            }
        
        decay = (in_sample_sharpe - out_of_sample_sharpe) / in_sample_sharpe
        
        return {
            'decay': decay,
            'is_overfitted': decay > self.sharpe_decay_threshold,
            'in_sample_sharpe': in_sample_sharpe,
            'out_of_sample_sharpe': out_of_sample_sharpe,
        }
    
    def calculate_pbo(
        self,
        strategy_returns_list: List[np.ndarray],
        n_splits: int = 10
    ) -> Dict:
        """
        计算过拟合概率（PBO）
        
        使用组合对称交叉验证方法。
        
        Parameters
        ----------
        strategy_returns_list : List[np.ndarray]
            多个策略的收益序列列表
        n_splits : int
            分割次数
        
        Returns
        -------
        Dict
            PBO计算结果
        """
        pbo_scores = []
        
        for _ in range(n_splits):
            # 随机分割数据
            n_strategies = len(strategy_returns_list)
            train_idx = np.random.choice(n_strategies, size=n_strategies // 2, replace=False)
            test_idx = np.array([i for i in range(n_strategies) if i not in train_idx])
            
            # 计算样本内表现
            train_sharpes = [
                np.mean(strategy_returns_list[i]) / (np.std(strategy_returns_list[i]) + 1e-10)
                for i in train_idx
            ]
            
            # 找样本内最优
            best_train_idx = train_idx[np.argmax(train_sharpes)]
            
            # 计算样本外表现
            test_sharpes = [
                np.mean(strategy_returns_list[i]) / (np.std(strategy_returns_list[i]) + 1e-10)
                for i in test_idx
            ]
            
            # 检查样本内最优是否在样本外也最优
            best_test_idx = test_idx[np.argmax(test_sharpes)]
            
            if best_train_idx != best_test_idx:
                pbo_scores.append(1)
            else:
                pbo_scores.append(0)
        
        pbo = np.mean(pbo_scores)
        
        return {
            'pbo': pbo,
            'is_overfitted': pbo > self.pbo_threshold,
            'n_splits': n_splits,
        }
    
    def parameter_sensitivity_analysis(
        self,
        base_params: Dict,
        param_ranges: Dict[str, List],
        evaluate_func,
        sensitivity_threshold: float = 0.3
    ) -> Dict:
        """
        参数敏感性分析
        
        Parameters
        ----------
        base_params : Dict
            基础参数
        param_ranges : Dict[str, List]
            参数变化范围
        evaluate_func : callable
            评估函数，返回夏普比率
        sensitivity_threshold : float
            敏感度阈值
        
        Returns
        -------
        Dict
            敏感性分析结果
        """
        base_result = evaluate_func(**base_params)
        base_sharpe = base_result.get('sharpe_ratio', 0)
        
        sensitivity_results = {}
        
        for param_name, param_values in param_ranges.items():
            sharpes = []
            
            for param_value in param_values:
                params = base_params.copy()
                params[param_name] = param_value
                
                try:
                    result = evaluate_func(**params)
                    sharpes.append(result.get('sharpe_ratio', 0))
                except Exception:
                    sharpes.append(0)
            
            # 计算敏感度
            if len(sharpes) > 0 and np.mean(sharpes) != 0:
                sensitivity = np.std(sharpes) / abs(np.mean(sharpes))
            else:
                sensitivity = 0
            
            sensitivity_results[param_name] = {
                'sensitivity': sensitivity,
                'is_sensitive': sensitivity > sensitivity_threshold,
                'sharpes': sharpes,
                'param_values': param_values,
            }
        
        return sensitivity_results
