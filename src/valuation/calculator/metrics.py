"""
估值指标计算工具类
提供各类估值指标的计算方法
"""

from typing import List, Optional
import numpy as np


class ValuationMetrics:
    """估值指标计算工具类，所有方法均为静态方法"""

    @staticmethod
    def calculate_pe(price: float, eps: float) -> Optional[float]:
        """
        计算市盈率 (Price-to-Earnings Ratio)

        Args:
            price: 股票价格
            eps: 每股收益 (Earnings Per Share)

        Returns:
            市盈率，如果eps为0或负数则返回None
        """
        if eps is None or eps <= 0:
            return None
        return price / eps

    @staticmethod
    def calculate_pb(price: float, book_value_per_share: float) -> Optional[float]:
        """
        计算市净率 (Price-to-Book Ratio)

        Args:
            price: 股票价格
            book_value_per_share: 每股净资产

        Returns:
            市净率，如果book_value_per_share为0或负数则返回None
        """
        if book_value_per_share is None or book_value_per_share <= 0:
            return None
        return price / book_value_per_share

    @staticmethod
    def calculate_ps(price: float, revenue_per_share: float) -> Optional[float]:
        """
        计算市销率 (Price-to-Sales Ratio)

        Args:
            price: 股票价格
            revenue_per_share: 每股营业收入

        Returns:
            市销率，如果revenue_per_share为0或负数则返回None
        """
        if revenue_per_share is None or revenue_per_share <= 0:
            return None
        return price / revenue_per_share

    @staticmethod
    def calculate_peg(pe: float, growth_rate: float) -> Optional[float]:
        """
        计算市盈增长比 (PEG Ratio)

        Args:
            pe: 市盈率
            growth_rate: 盈利增长率（百分比形式，如20表示20%）

        Returns:
            PEG比率，如果growth_rate为0或负数则返回None
        """
        if pe is None or growth_rate is None or growth_rate <= 0:
            return None
        return pe / growth_rate

    @staticmethod
    def calculate_ev_ebitda(
        market_cap: float,
        net_debt: float,
        ebitda: float
    ) -> Optional[float]:
        """
        计算企业价值倍数 (EV/EBITDA)

        Args:
            market_cap: 市值
            net_debt: 净债务（总债务 - 现金及现金等价物）
            ebitda: 息税折旧摊销前利润

        Returns:
            EV/EBITDA比率，如果ebitda为0或负数则返回None
        """
        if market_cap is None or net_debt is None or ebitda is None:
            return None
        if ebitda <= 0:
            return None
        ev = market_cap + net_debt
        return ev / ebitda

    @staticmethod
    def calculate_dcf(
        free_cash_flow: float,
        growth_rate: float,
        discount_rate: float,
        terminal_growth: float,
        years: int = 5
    ) -> Optional[float]:
        """
        计算现金流折现 (Discounted Cash Flow)

        Args:
            free_cash_flow: 当前自由现金流
            growth_rate: 预测增长率（小数形式，如0.05表示5%）
            discount_rate: 折现率（小数形式，如0.10表示10%）
            terminal_growth: 永续增长率（小数形式）
            years: 预测年数，默认5年

        Returns:
            DCF估值，如果参数无效则返回None
        """
        if free_cash_flow is None or free_cash_flow <= 0:
            return None
        if discount_rate is None or discount_rate <= 0:
            return None
        if growth_rate is None or growth_rate < 0:
            return None
        if terminal_growth is None or terminal_growth < 0:
            return None
        if terminal_growth >= discount_rate:
            return None

        # 计算预测期现金流现值
        pv_fcf = 0.0
        current_fcf = free_cash_flow

        for year in range(1, years + 1):
            current_fcf = current_fcf * (1 + growth_rate)
            pv_fcf += current_fcf / ((1 + discount_rate) ** year)

        # 计算终值 (Gordon Growth Model)
        terminal_value = current_fcf * (1 + terminal_growth) / (discount_rate - terminal_growth)
        pv_terminal = terminal_value / ((1 + discount_rate) ** years)

        return pv_fcf + pv_terminal

    @staticmethod
    def get_percentile_rank(
        current_value: float,
        historical_values: List[float]
    ) -> Optional[float]:
        """
        计算历史分位数

        Args:
            current_value: 当前值
            historical_values: 历史值列表

        Returns:
            分位数（0-100），如果历史数据不足则返回None
        """
        if historical_values is None or len(historical_values) < 5:
            return None
        if current_value is None:
            return None

        # 过滤掉None和无效值
        valid_values = [v for v in historical_values if v is not None and not np.isnan(v)]
        if len(valid_values) < 5:
            return None

        # 计算分位数
        count_below = sum(1 for v in valid_values if v < current_value)
        percentile = (count_below / len(valid_values)) * 100

        return round(percentile, 2)

    @staticmethod
    def calculate_fair_value_from_pe(eps: float, target_pe: float) -> Optional[float]:
        """
        基于目标PE计算合理股价

        Args:
            eps: 每股收益
            target_pe: 目标市盈率

        Returns:
            合理股价
        """
        if eps is None or eps <= 0 or target_pe is None or target_pe <= 0:
            return None
        return eps * target_pe

    @staticmethod
    def calculate_fair_value_from_pb(
        book_value_per_share: float,
        target_pb: float
    ) -> Optional[float]:
        """
        基于目标PB计算合理股价

        Args:
            book_value_per_share: 每股净资产
            target_pb: 目标市净率

        Returns:
            合理股价
        """
        if (book_value_per_share is None or book_value_per_share <= 0 or
            target_pb is None or target_pb <= 0):
            return None
        return book_value_per_share * target_pb

    @staticmethod
    def calculate_fair_value_from_ps(
        revenue_per_share: float,
        target_ps: float
    ) -> Optional[float]:
        """
        基于目标PS计算合理股价

        Args:
            revenue_per_share: 每股营业收入
            target_ps: 目标市销率

        Returns:
            合理股价
        """
        if (revenue_per_share is None or revenue_per_share <= 0 or
            target_ps is None or target_ps <= 0):
            return None
        return revenue_per_share * target_ps
