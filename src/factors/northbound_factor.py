"""
北向资金净流入因子

核心逻辑：
1. 获取北向资金日度净流入数据（亿元）
2. 使用滚动窗口计算历史均值和标准差（避免未来函数）
3. 计算Z-Score：(当日净流入 - 滚动均值) / 滚动标准差
4. 根据Z-Score生成交易信号

设计原则：
- 无未来函数：只使用当前日期之前的历史数据
- 滚动窗口：动态适应市场变化
- 信号延迟：T日计算信号，T+1日执行
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from src.data.eastmoney_connector import EastmoneyConnector

logger = logging.getLogger(__name__)


class NorthboundCapitalFactor:
    """
    北向资金净流入因子

    使用滚动窗口计算Z-Score，避免未来函数。
    当北向资金净流入显著高于历史均值时看多，显著低于时看空。

    Parameters
    ----------
    window : int
        滚动窗口天数（默认20）
    upper_threshold : float
        看多阈值（Z-Score，默认1.0）
    lower_threshold : float
        看空阈值（Z-Score，默认-1.0）
    """

    def __init__(
        self,
        window: int = 20,
        upper_threshold: float = 1.0,
        lower_threshold: float = -1.0,
    ):
        self.window = window
        self.upper_threshold = upper_threshold
        self.lower_threshold = lower_threshold

        # 历史数据缓存（滚动窗口）
        self._history_data: List[Dict] = []

        # 数据连接器（懒加载）
        self._connector: Optional[EastmoneyConnector] = None

    def _get_connector(self) -> EastmoneyConnector:
        """获取或创建数据连接器"""
        if self._connector is None:
            from config.config import get_credentials
            token = get_credentials('eastmoney').get('token', '')
            if not token:
                raise ValueError("未配置东财掘金 token")
            self._connector = EastmoneyConnector(token=token)
        return self._connector

    def load_history_data(
        self,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """
        加载历史北向资金数据

        Parameters
        ----------
        start_date : str
            开始日期 'YYYY-MM-DD'
        end_date : str
            结束日期 'YYYY-MM-DD'

        Returns
        -------
        pd.DataFrame
            北向资金历史数据
        """
        connector = self._get_connector()
        df = connector.get_northbound_capital(start_date, end_date)

        if df.empty:
            logger.warning(f"未获取到北向资金数据: {start_date} ~ {end_date}")

        return df

    def calculate(
        self,
        current_date: str,
        net_inflow: float,
    ) -> Dict:
        """
        计算当前日期的因子值（滚动窗口，无未来函数）

        关键设计：
        1. 只使用current_date之前的历史数据（包括当日）
        2. 滚动窗口计算，不使用全局统计
        3. 窗口期不足时返回中性信号

        Parameters
        ----------
        current_date : str
            当前日期 'YYYY-MM-DD'
        net_inflow : float
            当日北向资金净流入（亿元）

        Returns
        -------
        Dict
            {
                'date': 日期,
                'net_inflow': 当日净流入,
                'ma': 滚动均值,
                'std': 滚动标准差,
                'z_score': Z分数,
                'signal': 信号 (-1=看空, 0=中性, 1=看多),
                'signal_strength': 信号强度 (z_score绝对值),
            }
        """
        # 更新历史数据（滚动窗口）
        self._history_data.append({
            'date': current_date,
            'value': net_inflow
        })

        # 只保留窗口期内的数据
        if len(self._history_data) > self.window:
            self._history_data.pop(0)

        # 窗口期不足时返回中性信号
        if len(self._history_data) < self.window:
            return {
                'date': current_date,
                'net_inflow': net_inflow,
                'ma': None,
                'std': None,
                'z_score': 0.0,
                'signal': 0,
                'signal_strength': 0.0,
            }

        # 计算滚动统计（无未来函数）
        values = [d['value'] for d in self._history_data]
        ma = np.mean(values)
        std = np.std(values, ddof=1)  # 样本标准差

        # 避免除零
        if std == 0 or np.isnan(std):
            z_score = 0.0
        else:
            z_score = (net_inflow - ma) / std

        # 生成信号
        if z_score > self.upper_threshold:
            signal = 1  # 看多
        elif z_score < self.lower_threshold:
            signal = -1  # 看空
        else:
            signal = 0  # 中性

        return {
            'date': current_date,
            'net_inflow': net_inflow,
            'ma': ma,
            'std': std,
            'z_score': z_score,
            'signal': signal,
            'signal_strength': abs(z_score),
        }

    def batch_calculate(
        self,
        df: pd.DataFrame,
        date_col: str = 'trade_date',
        value_col: str = 'net_inflow',
    ) -> pd.DataFrame:
        """
        批量计算历史因子值（用于回测）

        Parameters
        ----------
        df : pd.DataFrame
            北向资金数据
        date_col : str
            日期列名
        value_col : str
            净流入列名

        Returns
        -------
        pd.DataFrame
            包含因子值的DataFrame
        """
        results = []

        for _, row in df.iterrows():
            date = row[date_col]
            if isinstance(date, pd.Timestamp):
                date = date.strftime('%Y-%m-%d')
            net_inflow = row[value_col]

            result = self.calculate(date, net_inflow)
            results.append(result)

        return pd.DataFrame(results)

    def reset(self):
        """重置历史数据缓存（用于新的回测周期）"""
        self._history_data = []
        logger.info("北向资金因子历史数据已重置")


class NorthboundFactorProvider:
    """
    北向资金因子提供者

    为策略提供统一的北向资金因子数据接口
    """

    def __init__(self, connector: Optional[EastmoneyConnector] = None):
        self._connector = connector
        self._cache: Dict[str, pd.DataFrame] = {}

    def _get_connector(self) -> EastmoneyConnector:
        if self._connector is None:
            from config.config import get_credentials
            token = get_credentials('eastmoney').get('token', '')
            if not token:
                raise ValueError("未配置东财掘金 token")
            self._connector = EastmoneyConnector(token=token)
        return self._connector

    def get_factor_data(
        self,
        start_date: str,
        end_date: str,
        window: int = 20,
        upper_threshold: float = 1.0,
        lower_threshold: float = -1.0,
    ) -> pd.DataFrame:
        """
        获取北向资金因子数据（含Z-Score和信号）

        Parameters
        ----------
        start_date : str
            开始日期
        end_date : str
            结束日期
        window : int
            滚动窗口
        upper_threshold : float
            看多阈值
        lower_threshold : float
            看空阈值

        Returns
        -------
        pd.DataFrame
            因子数据
        """
        cache_key = f"{start_date}_{end_date}_{window}_{upper_threshold}_{lower_threshold}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        # 加载原始数据（需要额外加载窗口期的预热数据）
        # 计算预热期开始日期
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        warmup_start = start_dt - timedelta(days=window * 2)
        warmup_start_str = warmup_start.strftime('%Y-%m-%d')

        connector = self._get_connector()
        raw_df = connector.get_northbound_capital(warmup_start_str, end_date)

        if raw_df.empty:
            return pd.DataFrame()

        # 计算因子
        factor = NorthboundCapitalFactor(
            window=window,
            upper_threshold=upper_threshold,
            lower_threshold=lower_threshold,
        )

        result_df = factor.batch_calculate(raw_df)

        # 过滤到实际回测期
        result_df['date'] = pd.to_datetime(result_df['date'])
        start_dt = pd.to_datetime(start_date)
        result_df = result_df[result_df['date'] >= start_dt].copy()

        # 缓存结果
        self._cache[cache_key] = result_df

        return result_df

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
