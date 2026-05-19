"""
指数成分股数据生成器
===================

生成模拟的指数成分股和组合权重数据。
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime


class IndexConstituentGenerator:
    """
    指数成分股数据生成器

    生成模拟的指数成分股权重数据。
    """

    def __init__(self, db_manager):
        self.db = db_manager
        np.random.seed(42)

    def generate_constituent_data(
        self,
        index_code: str = '000300.SH',
        n_stocks: int = 300,
        start_date: str = '2023-01-01',
        end_date: str = '2023-12-31',
        rebalance_freq: int = 60
    ) -> pd.DataFrame:
        """
        生成指数成分股模拟数据

        使用数据库中已有的股票代码，确保与stock_daily数据一致。
        """
        # 从数据库获取已有股票代码
        stock_info = self.db.get_stock_info()
        if stock_info.empty:
            raise ValueError("数据库中没有股票信息，请先生成基础测试数据")

        available_codes = stock_info['stock_code'].tolist()
        n_stocks = min(n_stocks, len(available_codes))
        stock_codes = available_codes[:n_stocks]

        trade_dates = pd.date_range(start=start_date, end=end_date, freq='B')
        n_days = len(trade_dates)

        # 生成基础权重（模拟市值加权）
        base_weights = np.random.dirichlet(np.ones(n_stocks) * 0.5)
        base_weights = base_weights / base_weights.sum()

        # 基础市值和估值
        base_market_caps = np.random.uniform(100, 5000, n_stocks)
        base_pe = np.random.uniform(8, 40, n_stocks)
        base_pb = np.random.uniform(0.5, 4, n_stocks)

        data = []
        for i, trade_date in enumerate(trade_dates):
            # 每rebalance_freq天调整一次权重
            if i % rebalance_freq == 0:
                weights = base_weights * (1 + np.random.randn(n_stocks) * 0.05)
                weights = np.maximum(weights, 1e-6)
                weights = weights / weights.sum()

                market_caps = base_market_caps * (1 + np.random.randn(n_stocks) * 0.02)
                pe = base_pe * (1 + np.random.randn(n_stocks) * 0.05)
                pb = base_pb * (1 + np.random.randn(n_stocks) * 0.05)

            for j, stock_code in enumerate(stock_codes):
                data.append({
                    'trade_date': trade_date,
                    'index_code': index_code,
                    'stock_code': stock_code,
                    'weight': round(weights[j], 6),
                    'market_cap': round(market_caps[j], 2),
                    'pe_ratio': round(pe[j], 2),
                    'pb_ratio': round(pb[j], 2),
                })

        df = pd.DataFrame(data)

        # 保存到数据库
        self.db.insert_index_constituent(df)

        print(f"  已生成 {n_stocks} 只成分股 × {n_days} 个交易日 = {len(df)} 条记录")
        return df

    def generate_portfolio_weights(
        self,
        index_code: str = '000300.SH',
        n_holdings: int = 50,
        start_date: str = '2023-01-01',
        end_date: str = '2023-12-31',
        rebalance_freq: int = 20,
        deviation_scale: float = 0.02
    ) -> pd.DataFrame:
        """
        生成模拟的组合权重（基于成分股的增强组合）

        Parameters
        ----------
        index_code : str
            指数代码
        n_holdings : int
            持仓数量
        start_date : str
            开始日期
        end_date : str
            结束日期
        rebalance_freq : int
            调仓频率
        deviation_scale : float
            权重偏离幅度

        Returns
        -------
        pd.DataFrame
            组合权重数据
        """
        # 获取成分股数据
        constituent = self.db.get_index_constituent_history(
            index_code=index_code,
            start_date=start_date,
            end_date=end_date
        )

        if constituent.empty:
            raise ValueError(f"未找到指数 {index_code} 的成分股数据")

        trade_dates = sorted(constituent['trade_date'].unique())
        # 确保日期为Timestamp类型
        trade_dates = pd.to_datetime(trade_dates)
        data = []

        for i, trade_date in enumerate(trade_dates):
            # 获取当日成分股（使用Timestamp比较）
            day_constituent = constituent[pd.to_datetime(constituent['trade_date']) == trade_date]

            if i % rebalance_freq == 0:
                # 调仓：随机选择n_holdings只股票
                if len(day_constituent) >= n_holdings:
                    selected = day_constituent.sample(n=n_holdings, weights='weight')
                else:
                    selected = day_constituent

                # 基于基准权重添加偏离（模拟增强）
                raw_weights = selected['weight'].values
                noise = np.random.randn(len(selected)) * deviation_scale
                weights = raw_weights + noise
                weights = np.maximum(weights, 1e-6)
                weights = weights / weights.sum()

                selected_stocks = selected['stock_code'].tolist()
                selected_weights = weights

            for stock_code, weight in zip(selected_stocks, selected_weights):
                data.append({
                    'trade_date': trade_date,
                    'stock_code': stock_code,
                    'weight': round(weight, 6),
                })

        df = pd.DataFrame(data)
        print(f"  已生成组合权重: {n_holdings} 只股票 × {len(trade_dates)} 个交易日")
        return df
