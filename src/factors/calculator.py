"""
因子计算器模块
=============

提供因子计算的基础框架和工具函数。
"""

from typing import Dict, List, Optional, Union, Callable
import pandas as pd
import numpy as np
from functools import wraps


def ts_sum(df: pd.Series, window: int) -> pd.Series:
    """时间序列求和"""
    return df.rolling(window=window, min_periods=1).sum()


def ts_mean(df: pd.Series, window: int) -> pd.Series:
    """时间序列均值"""
    return df.rolling(window=window, min_periods=1).mean()


def ts_std(df: pd.Series, window: int) -> pd.Series:
    """时间序列标准差"""
    return df.rolling(window=window, min_periods=1).std()


def ts_max(df: pd.Series, window: int) -> pd.Series:
    """时间序列最大值"""
    return df.rolling(window=window, min_periods=1).max()


def ts_min(df: pd.Series, window: int) -> pd.Series:
    """时间序列最小值"""
    return df.rolling(window=window, min_periods=1).min()


def ts_argmax(df: pd.Series, window: int) -> pd.Series:
    """时间序列最大值位置"""
    return df.rolling(window=window, min_periods=1).apply(
        lambda x: window - 1 - np.argmax(x) if len(x) > 0 else np.nan
    )


def ts_argmin(df: pd.Series, window: int) -> pd.Series:
    """时间序列最小值位置"""
    return df.rolling(window=window, min_periods=1).apply(
        lambda x: window - 1 - np.argmin(x) if len(x) > 0 else np.nan
    )


def ts_rank(df: pd.Series, window: int) -> pd.Series:
    """时间序列排名（最后一天在窗口内的排名比例）"""
    def rank_func(x):
        if len(x) == 0:
            return np.nan
        return (x.rank().iloc[-1] - 1) / (len(x) - 1) if len(x) > 1 else 0.5
    
    return df.rolling(window=window, min_periods=1).apply(rank_func)


def ts_delta(df: pd.Series, period: int) -> pd.Series:
    """时间序列差分"""
    return df.diff(period)


def ts_delay(df: pd.Series, period: int) -> pd.Series:
    """时间序列滞后"""
    return df.shift(period)


def ts_corr(x: pd.Series, y: pd.Series, window: int) -> pd.Series:
    """时间序列相关性"""
    return x.rolling(window=window, min_periods=1).corr(y)


def ts_cov(x: pd.Series, y: pd.Series, window: int) -> pd.Series:
    """时间序列协方差"""
    return x.rolling(window=window, min_periods=1).cov(y)


def ts_scale(df: pd.Series, window: int = None) -> pd.Series:
    """时间序列标准化"""
    if window is None:
        return (df - df.mean()) / (df.std() + 1e-10)
    else:
        mean = df.rolling(window=window, min_periods=1).mean()
        std = df.rolling(window=window, min_periods=1).std()
        return (df - mean) / (std + 1e-10)


def ts_product(df: pd.Series, window: int) -> pd.Series:
    """时间序列乘积"""
    return df.rolling(window=window, min_periods=1).apply(
        lambda x: np.prod(1 + x) - 1 if len(x) > 0 else np.nan
    )


def ts_regression_resid(x: pd.Series, y: pd.Series, window: int) -> pd.Series:
    """时间序列回归残差"""
    def resid_func(x_vals, y_vals):
        if len(x_vals) < 2:
            return np.nan
        x_mean = np.mean(x_vals)
        y_mean = np.mean(y_vals)
        numerator = np.sum((x_vals - x_mean) * (y_vals - y_mean))
        denominator = np.sum((x_vals - x_mean) ** 2)
        if denominator == 0:
            return np.nan
        beta = numerator / denominator
        alpha = y_mean - beta * x_mean
        return y_vals[-1] - (alpha + beta * x_vals[-1])
    
    result = []
    for i in range(len(x)):
        if i < window - 1:
            result.append(np.nan)
        else:
            result.append(resid_func(x.iloc[i-window+1:i+1].values, y.iloc[i-window+1:i+1].values))
    
    return pd.Series(result, index=x.index)


def rank(df: pd.Series) -> pd.Series:
    """截面排名"""
    return df.groupby(level='trade_date').rank(pct=True)


def scale(df: pd.Series) -> pd.Series:
    """截面标准化"""
    return df.groupby(level='trade_date').transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-10)
    )


def sign(df: pd.Series) -> pd.Series:
    """符号函数"""
    return np.sign(df)


def abs_func(df: pd.Series) -> pd.Series:
    """绝对值"""
    return np.abs(df)


def log(df: pd.Series) -> pd.Series:
    """自然对数"""
    return np.log(np.abs(df) + 1e-10)


def power(df: pd.Series, n: float) -> pd.Series:
    """幂函数"""
    return np.power(np.abs(df) + 1e-10, n)


def ind_neutralize(df: pd.Series, industry: pd.Series = None) -> pd.Series:
    """
    行业中性化处理
    
    在每个行业内对因子值进行标准化（减去行业均值，除以行业标准差），
    消除行业间的系统性差异，使得不同行业的因子值可比。
    
    Parameters
    ----------
    df : pd.Series
        待中性化的因子值序列，索引为 (trade_date, stock_code)
    industry : pd.Series, optional
        行业分类序列，索引与 df 相同。如果为 None，则使用模拟的行业分类
        
    Returns
    -------
    pd.Series
        行业中性化后的因子值序列
    """
    if industry is None:
        # 如果没有提供行业数据，使用股票代码的哈希值模拟行业分类
        # 将股票分为10个行业组
        stock_codes = df.index.get_level_values('stock_code')
        industry = pd.Series(
            [hash(code) % 10 for code in stock_codes],
            index=df.index
        )
    
    # 在每个交易日，按行业分组进行标准化
    def neutralize_group(group):
        # 按行业分组
        result = []
        for ind, sub_group in group.groupby(industry.loc[group.index]):
            mean = sub_group.mean()
            std = sub_group.std()
            if std > 0:
                result.append((sub_group - mean) / std)
            else:
                result.append(sub_group - mean)
        if result:
            out = pd.concat(result)
            # 确保index names与原始数据一致，避免重复
            out.index.names = df.index.names
            return out
        return group
    
    # 按交易日分组处理
    result = df.groupby(level='trade_date', group_keys=False).apply(neutralize_group)
    
    # 确保索引正确：groupby.apply 可能产生重复的 index name
    if isinstance(result.index, pd.MultiIndex):
        # 去除可能重复的 index name
        unique_names = list(dict.fromkeys(result.index.names))
        result.index.names = unique_names
        return result
    else:
        # 如果apply改变了索引结构，需要重新设置
        result.index = df.index
        return result


def decay_linear(df: pd.Series, window: int) -> pd.Series:
    """线性衰减加权平均"""
    weights = np.arange(1, window + 1)
    weights = weights / weights.sum()
    
    return df.rolling(window=window, min_periods=1).apply(
        lambda x: np.sum(x * weights[-len(x):]) if len(x) > 0 else np.nan
    )


def sma(df: pd.Series, window: int, m: int = 1) -> pd.Series:
    """
    递归移动平均 (Recursive Moving Average)
    
    公式: SMA_t = (m * x_t + (window - m) * SMA_{t-1}) / window
    
    当 m=1 时退化为指数衰减加权平均，权重随时间指数递减。
    当 m=window 时等价于简单移动平均 (ts_mean)。
    
    Parameters
    ----------
    df : pd.Series
        输入序列，索引为 (trade_date, stock_code) 的 MultiIndex
    window : int
        窗口大小
    m : int
        平滑系数，默认为1
    
    Returns
    -------
    pd.Series
        递归移动平均结果
    """
    def _sma_group(x):
        """对单只股票计算递归移动平均"""
        values = x.values
        n = len(values)
        result = np.full(n, np.nan)
        if n == 0:
            return pd.Series(result, index=x.index)
        
        # 找到第一个非NaN值作为初始值
        start = 0
        while start < n and np.isnan(values[start]):
            start += 1
        if start >= n:
            return pd.Series(result, index=x.index)
        
        result[start] = values[start]
        for i in range(start + 1, n):
            if np.isnan(values[i]):
                result[i] = result[i - 1]  # NaN时保持前值
            else:
                result[i] = (m * values[i] + (window - m) * result[i - 1]) / window
        return pd.Series(result, index=x.index)
    
    return df.groupby(level='stock_code').transform(_sma_group)


def adv(df: pd.DataFrame, window: int) -> pd.Series:
    """平均成交量"""
    return df.groupby(level='stock_code')['amount'].transform(
        lambda x: x.rolling(window=window, min_periods=1).mean()
    )


class FactorCalculator:
    """
    因子计算器
    
    提供因子计算、预处理和评估功能。
    """
    
    def __init__(self, data_loader):
        """
        初始化因子计算器
        
        Parameters
        ----------
        data_loader : DataLoader
            数据加载器实例
        """
        self.data_loader = data_loader
        self._price_data = None
        self._factors = {}
    
    def load_data(self):
        """加载数据"""
        self._price_data = self.data_loader.get_price_data()
        return self
    
    @property
    def price_data(self) -> pd.DataFrame:
        """获取价格数据"""
        if self._price_data is None:
            self.load_data()
        return self._price_data
    
    def get_series(self, field: str) -> pd.Series:
        """获取指定字段的序列"""
        return self.price_data[field]
    
    def close(self) -> pd.Series:
        """收盘价"""
        return self.get_series('close')
    
    def open(self) -> pd.Series:
        """开盘价"""
        return self.get_series('open')
    
    def high(self) -> pd.Series:
        """最高价"""
        return self.get_series('high')
    
    def low(self) -> pd.Series:
        """最低价"""
        return self.get_series('low')
    
    def volume(self) -> pd.Series:
        """成交量"""
        return self.get_series('volume')
    
    def amount(self) -> pd.Series:
        """成交额"""
        return self.get_series('amount')
    
    def vwap(self) -> pd.Series:
        """成交量加权均价"""
        if 'vwap' in self.price_data.columns:
            vwap = self.get_series('vwap')
            # 如果VWAP有值则使用，否则用近似值
            if vwap.notna().any():
                return vwap
        # 如果没有VWAP或全为NaN，计算近似值
        return (self.high() + self.low() + self.close()) / 3

    def suspend_flag(self) -> pd.Series:
        """停牌标记（1停牌,0正常）"""
        if 'suspend_flag' in self.price_data.columns:
            return self.get_series('suspend_flag')
        # 如果没有停牌标记，默认全部正常交易
        return pd.Series(0, index=self.price_data.index)

    def filter_suspended(self, data: pd.Series) -> pd.Series:
        """
        过滤停牌数据，将停牌日的值设为NaN

        Parameters
        ----------
        data : pd.Series
            原始数据序列

        Returns
        -------
        pd.Series
            停牌日为NaN的数据序列
        """
        flags = self.suspend_flag()
        return data.where(flags == 0)
    
    def returns(self, period: int = 1) -> pd.Series:
        """收益率"""
        return self.close().groupby(level='stock_code').pct_change(period)
    
    def add_factor(self, name: str, factor: pd.Series):
        """添加因子"""
        self._factors[name] = factor
    
    def get_factor(self, name: str) -> pd.Series:
        """获取因子"""
        return self._factors.get(name)
    
    def get_all_factors(self) -> pd.DataFrame:
        """获取所有因子"""
        return pd.DataFrame(self._factors)
    
    def preprocess_factor(
        self,
        factor: pd.Series,
        winsorize: bool = True,
        standardize: bool = True,
        neutralize: bool = False
    ) -> pd.Series:
        """
        因子预处理
        
        Parameters
        ----------
        factor : pd.Series
            原始因子值
        winsorize : bool
            是否去极值
        standardize : bool
            是否标准化
        neutralize : bool
            是否中性化
        
        Returns
        -------
        pd.Series
            预处理后的因子值
        """
        result = factor.copy()
        
        # 去极值
        if winsorize:
            result = result.groupby(level='trade_date').transform(
                lambda x: x.clip(
                    lower=x.quantile(0.01),
                    upper=x.quantile(0.99)
                )
            )
        
        # 标准化
        if standardize:
            result = result.groupby(level='trade_date').transform(
                lambda x: (x - x.mean()) / (x.std() + 1e-10)
            )
        
        # 中性化（简化实现，仅做行业中性）
        if neutralize:
            industry_map = self.data_loader.get_industry_mapping()
            if industry_map:
                # 按日期和行业进行中性化
                result = result.groupby(level='trade_date').transform(
                    lambda x: x - x.mean()
                )
        
        return result
    
    def evaluate_factor(
        self,
        factor: pd.Series,
        forward_period: int = 5,
        n_layers: int = 5
    ) -> Dict:
        """
        评估因子有效性
        
        Parameters
        ----------
        factor : pd.Series
            因子值
        forward_period : int
            预测期
        n_layers : int
            分层数
        
        Returns
        -------
        Dict
            评估指标
        """
        # 计算未来收益
        future_returns = self.close().groupby(level='stock_code').pct_change(forward_period).shift(-forward_period)
        
        # 对齐数据
        aligned = pd.DataFrame({
            'factor': factor,
            'returns': future_returns
        }).dropna()
        
        if len(aligned) == 0:
            return {'IC_mean': np.nan, 'IC_IR': np.nan}
        
        # 计算IC
        ic = aligned.groupby(level='trade_date').apply(
            lambda x: x['factor'].corr(x['returns'])
        )
        
        # 计算分层收益
        layer_returns = self._calculate_layer_returns(aligned, n_layers)
        
        return {
            'IC_mean': ic.mean(),
            'IC_std': ic.std(),
            'IC_IR': ic.mean() / (ic.std() + 1e-10),
            'IC_positive_ratio': (ic > 0).mean(),
            'layer_returns': layer_returns,
            'layer_spread': layer_returns[-1] - layer_returns[0] if len(layer_returns) == n_layers else np.nan,
        }
    
    def _calculate_layer_returns(self, data: pd.DataFrame, n_layers: int) -> List[float]:
        """计算分层收益"""
        layer_returns = []
        
        for date, group in data.groupby(level='trade_date'):
            if len(group) < n_layers:
                continue
            
            # 按因子值分层
            group['layer'] = pd.qcut(group['factor'], n_layers, labels=False, duplicates='drop')
            
            # 计算各层平均收益
            for layer in range(n_layers):
                layer_data = group[group['layer'] == layer]
                if len(layer_data) > 0:
                    if len(layer_returns) <= layer:
                        layer_returns.append([])
                    layer_returns[layer].append(layer_data['returns'].mean())
        
        # 计算各层平均收益
        return [np.mean(returns) if returns else np.nan for returns in layer_returns]
    
    def apply_to_group(self, series: pd.Series, func: Callable, window: int) -> pd.Series:
        """对每个股票应用时间序列函数"""
        return series.groupby(level='stock_code').transform(
            lambda x: func(x, window)
        )
