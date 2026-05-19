"""
因子筛选模块
===========

提供因子评估、筛选和组合优化功能。
支持按因子分类筛选。
"""

from typing import Dict, List, Optional, Tuple, Union, Set
import pandas as pd
import numpy as np
from scipy.optimize import minimize

from .categories import FactorCategory, get_factor_category, get_factors_by_category


class FactorSelector:
    """
    因子筛选器
    
    提供因子评估、筛选和组合优化功能。
    """
    
    def __init__(
        self,
        ic_threshold: float = 0.02,
        ir_threshold: float = 0.2,
        forward_period: int = 5,
        n_layers: int = 5,
        execution_logger=None
    ):
        """
        初始化因子筛选器
        
        Parameters
        ----------
        ic_threshold : float
            IC阈值
        ir_threshold : float
            IR阈值
        forward_period : int
            预测期（交易日）
        n_layers : int
            分层数
        execution_logger : ExecutionLogger, optional
            执行日志记录器
        """
        self.ic_threshold = ic_threshold
        self.ir_threshold = ir_threshold
        self.forward_period = forward_period
        self.n_layers = n_layers
        self.execution_logger = execution_logger
        
        self._factors: Dict[str, pd.Series] = {}
        self._factor_metrics: Dict[str, Dict] = {}
        self._selected_factors: List[str] = []
        self._factor_categories: Dict[str, FactorCategory] = {}  # 因子分类缓存
    
    def add_factor(self, name: str, factor: pd.Series, category: Optional[FactorCategory] = None):
        """
        添加因子
        
        Parameters
        ----------
        name : str
            因子名称
        factor : pd.Series
            因子值，索引为 (trade_date, stock_code)
        category : FactorCategory, optional
            因子分类，如果不提供则自动从元数据中查找
        """
        self._factors[name] = factor
        
        # 记录因子分类
        if category is not None:
            self._factor_categories[name] = category
        else:
            # 尝试从元数据中查找
            cat = get_factor_category(name)
            if cat is not None:
                self._factor_categories[name] = cat
    
    def add_factors(self, factors: Dict[str, pd.Series], categories: Optional[Dict[str, FactorCategory]] = None):
        """
        批量添加因子
        
        Parameters
        ----------
        factors : Dict[str, pd.Series]
            因子字典
        categories : Dict[str, FactorCategory], optional
            因子分类字典
        """
        self._factors.update(factors)
        
        # 记录分类
        if categories:
            self._factor_categories.update(categories)
        else:
            # 自动查找分类
            for name in factors.keys():
                cat = get_factor_category(name)
                if cat is not None:
                    self._factor_categories[name] = cat
    
    def get_factor_category(self, factor_name: str) -> Optional[FactorCategory]:
        """
        获取因子的分类
        
        Parameters
        ----------
        factor_name : str
            因子名称
        
        Returns
        -------
        FactorCategory or None
            因子分类
        """
        # 优先从缓存获取
        if factor_name in self._factor_categories:
            return self._factor_categories[factor_name]
        
        # 从全局元数据查找
        cat = get_factor_category(factor_name)
        if cat is not None:
            self._factor_categories[factor_name] = cat
        
        return cat
    
    def get_factors_by_category(self, category: Union[FactorCategory, str]) -> List[str]:
        """
        按分类获取所有因子名称
        
        Parameters
        ----------
        category : FactorCategory or str
            因子分类或分类名称
        
        Returns
        -------
        List[str]
            该分类下的所有因子名称列表
        """
        if isinstance(category, str):
            # 尝试转换
            try:
                category = FactorCategory(category)
            except ValueError:
                # 从中文名称查找
                from .categories import CATEGORY_NAMES
                for cat, name in CATEGORY_NAMES.items():
                    if name == category:
                        category = cat
                        break
                else:
                    return []
        
        # 从已添加的因子中筛选
        result = []
        for name in self._factors.keys():
            cat = self.get_factor_category(name)
            if cat == category:
                result.append(name)
        
        return result
    
    def filter_by_categories(self, categories: List[Union[FactorCategory, str]]) -> List[str]:
        """
        按多个分类筛选因子
        
        Parameters
        ----------
        categories : List[FactorCategory or str]
            因子分类列表
        
        Returns
        -------
        List[str]
            符合任一分类的所有因子名称列表
        """
        result = set()
        for category in categories:
            factors = self.get_factors_by_category(category)
            result.update(factors)
        return list(result)
    
    def select_by_category(
        self,
        category: Union[FactorCategory, str],
        method: str = 'ic',
        top_k: int = 5
    ) -> List[str]:
        """
        从指定分类中筛选因子
        
        Parameters
        ----------
        category : FactorCategory or str
            因子分类
        method : str
            筛选方法：'ic', 'ir', 'combined'
        top_k : int
            选取前K个因子
        
        Returns
        -------
        List[str]
            选中的因子名称列表
        """
        # 获取该分类下的所有因子
        category_factors = self.get_factors_by_category(category)
        
        if not category_factors:
            print(f"警告: 分类 '{category}' 下没有因子")
            return []
        
        if not self._factor_metrics:
            raise ValueError("请先使用 evaluate_all_factors() 评估因子")
        
        # 筛选该分类下的有效因子
        valid_factors = {
            name: self._factor_metrics[name] 
            for name in category_factors 
            if name in self._factor_metrics and not np.isnan(self._factor_metrics[name]['IC_mean'])
        }
        
        if not valid_factors:
            print(f"警告: 分类 '{category}' 下的因子没有有效评估指标")
            return []
        
        # 排序
        if method == 'ic':
            sorted_factors = sorted(
                valid_factors.items(),
                key=lambda x: abs(x[1]['IC_mean']),
                reverse=True
            )
        elif method == 'ir':
            sorted_factors = sorted(
                valid_factors.items(),
                key=lambda x: abs(x[1]['IC_IR']),
                reverse=True
            )
        elif method == 'combined':
            def combined_score(item):
                metrics = item[1]
                return abs(metrics['IC_mean']) * 0.5 + abs(metrics['IC_IR']) * 0.5
            
            sorted_factors = sorted(
                valid_factors.items(),
                key=combined_score,
                reverse=True
            )
        else:
            raise ValueError(f"不支持的筛选方法: '{method}'")
        
        # 过滤阈值
        selected = [
            name for name, metrics in sorted_factors
            if abs(metrics['IC_mean']) >= self.ic_threshold and
               abs(metrics['IC_IR']) >= self.ir_threshold
        ]
        
        return selected[:top_k]
    
    def get_category_statistics(self) -> pd.DataFrame:
        """
        获取各分类的因子统计信息
        
        Returns
        -------
        pd.DataFrame
            分类统计报告
        """
        if not self._factor_metrics:
            raise ValueError("请先使用 evaluate_all_factors() 评估因子")
        
        from .categories import CATEGORY_NAMES
        
        stats = []
        for category in FactorCategory:
            factors = self.get_factors_by_category(category)
            if not factors:
                continue
            
            # 获取该分类下因子的指标
            category_metrics = [
                self._factor_metrics[f] for f in factors 
                if f in self._factor_metrics and not np.isnan(self._factor_metrics[f]['IC_mean'])
            ]
            
            if not category_metrics:
                continue
            
            ic_means = [m['IC_mean'] for m in category_metrics]
            ic_ir = [m['IC_IR'] for m in category_metrics]
            
            stats.append({
                'category': CATEGORY_NAMES.get(category, category.value),
                'category_code': category.value,
                'factor_count': len(factors),
                'valid_count': len(category_metrics),
                'avg_ic': np.mean(ic_means),
                'avg_ir': np.mean(ic_ir),
                'max_abs_ic': max(abs(ic) for ic in ic_means),
                'positive_ratio': sum(1 for ic in ic_means if ic > 0) / len(ic_means),
            })
        
        return pd.DataFrame(stats).sort_values('avg_ir', key=abs, ascending=False)
    
    def evaluate_single_factor(
        self,
        factor: pd.Series,
        returns: pd.Series
    ) -> Dict:
        """
        评估单个因子
        
        Parameters
        ----------
        factor : pd.Series
            因子值
        returns : pd.Series
            未来收益
        
        Returns
        -------
        Dict
            评估指标
        """
        # 对齐数据
        aligned = pd.DataFrame({
            'factor': factor,
            'returns': returns
        }).dropna()
        
        if len(aligned) == 0:
            return {
                'IC_mean': np.nan,
                'IC_std': np.nan,
                'IC_IR': np.nan,
                'IC_positive_ratio': np.nan,
            }
        
        # 计算IC（按日期计算相关系数）
        ic_series = aligned.groupby(level='trade_date').apply(
            lambda x: x['factor'].corr(x['returns'], method='spearman')
        )
        
        # 计算分层收益
        layer_returns = self._calculate_layer_returns(aligned)
        
        # 计算换手率
        turnover = self._calculate_turnover(factor)
        
        return {
            'IC_mean': ic_series.mean(),
            'IC_std': ic_series.std(),
            'IC_IR': ic_series.mean() / (ic_series.std() + 1e-10),
            'IC_positive_ratio': (ic_series > 0).mean(),
            'layer_returns': layer_returns,
            'layer_spread': layer_returns[-1] - layer_returns[0] if len(layer_returns) == self.n_layers else np.nan,
            'turnover': turnover,
        }
    
    def _calculate_layer_returns(self, data: pd.DataFrame) -> List[float]:
        """计算分层收益"""
        layer_returns = {i: [] for i in range(self.n_layers)}
        
        for date, group in data.groupby(level='trade_date'):
            if len(group) < self.n_layers * 2:
                continue
            
            try:
                # 按因子值分层
                group = group.copy()
                group['layer'] = pd.qcut(group['factor'], self.n_layers, labels=False, duplicates='drop')
                
                for layer in range(self.n_layers):
                    layer_data = group[group['layer'] == layer]
                    if len(layer_data) > 0:
                        layer_returns[layer].append(layer_data['returns'].mean())
            except Exception:
                continue
        
        return [np.mean(layer_returns[i]) if layer_returns[i] else np.nan for i in range(self.n_layers)]
    
    def _calculate_turnover(self, factor: pd.Series) -> float:
        """计算因子换手率"""
        if isinstance(factor.index, pd.MultiIndex):
            # 按股票分组计算排名变化
            turnover_list = []
            
            for stock_code in factor.index.get_level_values('stock_code').unique():
                try:
                    stock_factor = factor.xs(stock_code, level='stock_code')
                    if len(stock_factor) > 1:
                        # 计算排名变化
                        rank_change = stock_factor.diff().abs().mean()
                        turnover_list.append(rank_change)
                except Exception:
                    continue
            
            return np.mean(turnover_list) if turnover_list else np.nan
        
        return np.nan
    
    def evaluate_all_factors(self, returns: pd.Series) -> Dict[str, Dict]:
        """
        评估所有因子
        
        Parameters
        ----------
        returns : pd.Series
            未来收益
        
        Returns
        -------
        Dict[str, Dict]
            各因子的评估指标
        """
        self._factor_metrics = {}
        
        for name, factor in self._factors.items():
            try:
                metrics = self.evaluate_single_factor(factor, returns)
                self._factor_metrics[name] = metrics
                print(f"已评估因子: {name}, IC={metrics['IC_mean']:.4f}, IR={metrics['IC_IR']:.4f}")

                # 记录到执行日志
                if self.execution_logger:
                    try:
                        self.execution_logger.log_factor_evaluation(name, metrics)
                    except Exception:
                        pass
            except Exception as e:
                print(f"评估因子 {name} 时出错: {e}")
                if self.execution_logger:
                    try:
                        self.execution_logger.log_error('factor_evaluation', name, str(e))
                    except Exception:
                        pass
        
        return self._factor_metrics
    
    def select_factors(
        self,
        method: str = 'ic',
        top_k: int = 10
    ) -> List[str]:
        """
        筛选因子
        
        Parameters
        ----------
        method : str
            筛选方法：
            - 'ic': 基于IC均值
            - 'ir': 基于IR
            - 'combined': 综合IC和IR
        top_k : int
            选取前K个因子
        
        Returns
        -------
        List[str]
            选中的因子名称列表
        """
        if not self._factor_metrics:
            raise ValueError("请先使用 evaluate_all_factors() 评估因子")
        
        # 筛选有效因子
        valid_factors = {
            name: metrics for name, metrics in self._factor_metrics.items()
            if not np.isnan(metrics['IC_mean'])
        }
        
        if method == 'ic':
            # 按IC绝对值排序
            sorted_factors = sorted(
                valid_factors.items(),
                key=lambda x: abs(x[1]['IC_mean']),
                reverse=True
            )
        elif method == 'ir':
            # 按IR绝对值排序
            sorted_factors = sorted(
                valid_factors.items(),
                key=lambda x: abs(x[1]['IC_IR']),
                reverse=True
            )
        elif method == 'combined':
            # 综合IC和IR
            def combined_score(item):
                metrics = item[1]
                return abs(metrics['IC_mean']) * 0.5 + abs(metrics['IC_IR']) * 0.5
            
            sorted_factors = sorted(
                valid_factors.items(),
                key=combined_score,
                reverse=True
            )
        else:
            raise ValueError(f"不支持的筛选方法: '{method}'")
        
        # 过滤阈值
        selected = [
            name for name, metrics in sorted_factors
            if abs(metrics['IC_mean']) >= self.ic_threshold and
               abs(metrics['IC_IR']) >= self.ir_threshold
        ]
        
        self._selected_factors = selected[:top_k]
        
        return self._selected_factors
    
    def ic_weighted_combination(self, returns: pd.Series) -> Tuple[pd.Series, Dict[str, float]]:
        """
        IC加权因子组合
        
        Parameters
        ----------
        returns : pd.Series
            未来收益（用于计算IC）
        
        Returns
        -------
        Tuple[pd.Series, Dict[str, float]]
            组合因子和权重
        """
        if not self._selected_factors:
            raise ValueError("请先使用 select_factors() 选择因子")
        
        # 计算各因子IC
        ic_values = {}
        for name in self._selected_factors:
            factor = self._factors[name]
            aligned = pd.DataFrame({
                'factor': factor,
                'returns': returns
            }).dropna()
            
            if len(aligned) > 0:
                ic = aligned.groupby(level='trade_date').apply(
                    lambda x: x['factor'].corr(x['returns'], method='spearman')
                ).mean()
                ic_values[name] = ic
        
        # 计算权重（IC绝对值归一化）
        total_ic = sum(abs(ic) for ic in ic_values.values())
        weights = {name: abs(ic) / total_ic for name, ic in ic_values.items()}
        
        # 构建组合因子
        combined = None
        for name, weight in weights.items():
            factor = self._factors[name]
            if combined is None:
                combined = factor * weight
            else:
                combined = combined + factor * weight
        
        return combined, weights
    
    def risk_parity_weighting(self) -> Tuple[pd.Series, Dict[str, float]]:
        """
        风险平价加权
        
        Returns
        -------
        Tuple[pd.Series, Dict[str, float]]
            组合因子和权重
        """
        if not self._selected_factors:
            raise ValueError("请先使用 select_factors() 选择因子")
        
        # 获取因子数据
        factor_matrix = pd.DataFrame({
            name: self._factors[name] for name in self._selected_factors
        }).dropna()
        
        # 计算协方差矩阵
        cov_matrix = factor_matrix.cov().values
        
        # 风险平价优化
        n = len(self._selected_factors)
        
        def risk_parity_objective(weights):
            portfolio_var = np.dot(weights.T, np.dot(cov_matrix, weights))
            marginal_risk = np.dot(cov_matrix, weights) / np.sqrt(portfolio_var + 1e-10)
            risk_contrib = weights * marginal_risk
            target_risk = portfolio_var / n
            return np.sum((risk_contrib - target_risk) ** 2)
        
        # 约束条件
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        ]
        bounds = [(0, 1) for _ in range(n)]
        
        # 优化
        result = minimize(
            risk_parity_objective,
            x0=np.ones(n) / n,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints
        )
        
        weights = dict(zip(self._selected_factors, result.x))
        
        # 构建组合因子
        combined = None
        for name, weight in weights.items():
            factor = self._factors[name]
            if combined is None:
                combined = factor * weight
            else:
                combined = combined + factor * weight
        
        return combined, weights
    
    def get_factor_correlation(self) -> pd.DataFrame:
        """
        计算因子相关性矩阵
        
        Returns
        -------
        pd.DataFrame
            相关性矩阵
        """
        if not self._selected_factors:
            raise ValueError("请先使用 select_factors() 选择因子")
        
        factor_matrix = pd.DataFrame({
            name: self._factors[name] for name in self._selected_factors
        }).dropna()
        
        return factor_matrix.corr()
    
    def get_factor_report(self) -> pd.DataFrame:
        """
        生成因子评估报告
        
        Returns
        -------
        pd.DataFrame
            因子评估报告
        """
        if not self._factor_metrics:
            raise ValueError("请先使用 evaluate_all_factors() 评估因子")
        
        report_data = []
        
        for name, metrics in self._factor_metrics.items():
            report_data.append({
                'factor_name': name,
                'IC_mean': metrics['IC_mean'],
                'IC_std': metrics['IC_std'],
                'IC_IR': metrics['IC_IR'],
                'IC_positive_ratio': metrics['IC_positive_ratio'],
                'layer_spread': metrics.get('layer_spread', np.nan),
                'turnover': metrics.get('turnover', np.nan),
                'selected': name in self._selected_factors,
            })
        
        return pd.DataFrame(report_data).sort_values('IC_mean', key=abs, ascending=False)
