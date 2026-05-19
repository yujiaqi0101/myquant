"""
基本面因子计算器
================

实现估值因子、盈利因子、成长因子、质量因子。

注意：基本面因子依赖于财务数据，当前实现采用以下策略：
1. 估值因子：使用市值数据和财务指标估算（PE=总市值/净利润）
2. 盈利/成长/质量因子：提供计算接口，需要接入财务数据源

数据说明：
- 基本面因子使用前推的财务数据（最近可用的财报数据）
- 数据频率：季度（与财报发布同步）
- 适用于横截面选股
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from .calculator import FactorCalculator
from .categories import FactorCategory, FUNDAMENTAL_FACTOR_META


class FundamentalFactors:
    """
    基本面因子计算器

    实现估值、盈利、成长、质量四类基本面因子。

    Parameters
    ----------
    calculator : FactorCalculator
        因子计算器实例
    """

    def __init__(self, calculator: FactorCalculator):
        self.calculator = calculator
        self._factors: Dict[str, pd.Series] = {}

    def _get_price_data(self) -> pd.DataFrame:
        """获取价格数据"""
        return self.calculator.price_data

    def _close(self) -> pd.Series:
        """获取收盘价"""
        return self.calculator.close()

    def _get_market_cap(self) -> pd.Series:
        """
        获取市值数据

        从data_loader获取市值数据，如果不存在则返回None
        """
        try:
            # 尝试从data_loader获取
            if hasattr(self.calculator.data_loader, 'get_market_cap_data'):
                market_cap_dict = self.calculator.data_loader.get_market_cap_data()
                if market_cap_dict:
                    # 转换为Series
                    close = self._close()
                    market_cap = pd.Series(market_cap_dict, index=close.index.get_level_values('stock_code').unique())
                    # 扩展为与close相同的索引
                    market_cap = market_cap.reindex(close.index.get_level_values('stock_code'))
                    market_cap.index = close.index
                    return market_cap
        except Exception:
            pass
        return None

    # ==================== 估值因子 ====================

    def val_pe(self) -> pd.Series:
        """
        PE倒数 (Earnings Yield)

        计算：净利润_TTM / 总市值
        或：1 / PE_TTM

        注意：由于缺少财务数据，这里使用模拟数据演示计算逻辑
        实际使用时需要从财务数据表获取净利润_TTM
        """
        close = self._close()

        # 获取市值数据
        market_cap = self._get_market_cap()

        # 模拟净利润数据（实际应从财务表获取）
        np.random.seed(42)
        net_profit = close * (1 + np.random.randn(len(close)) * 0.1) * 1e8

        if market_cap is None:
            # 如果没有市值数据，使用收盘价作为代理（仅用于演示）
            # 实际应该使用总市值
            market_cap = close * 1e9  # 假设每股面值1元，总股本1e9

        # 计算PE倒数
        pe_inverse = net_profit / market_cap

        # 去极值
        pe_inverse = self._winsorize(pe_inverse)

        return pe_inverse

    def val_pb(self) -> pd.Series:
        """
        PB倒数

        计算：净资产 / 总市值
        或：1 / PB
        """
        close = self._close()

        # 模拟净资产数据（实际应从财务表获取）
        np.random.seed(43)
        book_value = close * (1.5 + np.random.randn(len(close)) * 0.2) * 1e8

        # 获取市值
        market_cap = self._get_market_cap()
        if market_cap is None:
            market_cap = close * 1e9

        # 计算PB倒数
        pb_inverse = book_value / market_cap

        return self._winsorize(pb_inverse)

    def val_ps(self) -> pd.Series:
        """
        PS倒数

        计算：营业收入_TTM / 总市值
        或：1 / PS_TTM
        """
        close = self._close()

        # 模拟营业收入数据（实际应从财务表获取）
        np.random.seed(44)
        revenue = close * (2 + np.random.randn(len(close)) * 0.3) * 1e8

        # 获取市值
        market_cap = self._get_market_cap()
        if market_cap is None:
            market_cap = close * 1e9

        # 计算PS倒数
        ps_inverse = revenue / market_cap

        return self._winsorize(ps_inverse)

    def val_pcf(self) -> pd.Series:
        """
        PCF倒数 (Price to Cash Flow)

        计算：经营现金流_TTM / 总市值
        """
        close = self._close()

        # 模拟经营现金流数据（实际应从财务表获取）
        np.random.seed(45)
        cash_flow = close * (0.8 + np.random.randn(len(close)) * 0.15) * 1e8

        # 获取市值
        market_cap = self._get_market_cap()
        if market_cap is None:
            market_cap = close * 1e9

        # 计算PCF倒数
        pcf_inverse = cash_flow / market_cap

        return self._winsorize(pcf_inverse)

    def val_ep(self) -> pd.Series:
        """
        EP (Earnings to Price)

        与PE倒数相同，使用净利润/总市值
        """
        return self.val_pe()

    def val_bp(self) -> pd.Series:
        """
        BP (Book to Price)

        与PB倒数相同，使用净资产/总市值
        """
        return self.val_pb()

    def val_sp(self) -> pd.Series:
        """
        SP (Sales to Price)

        与PS倒数相同，使用营业收入/总市值
        """
        return self.val_ps()

    def val_cfp(self) -> pd.Series:
        """
        CFP (Cash Flow to Price)

        与PCF倒数相同，使用经营现金流/总市值
        """
        return self.val_pcf()

    # ==================== 盈利因子 ====================

    def prof_roe(self) -> pd.Series:
        """
        ROE (净资产收益率)

        计算：净利润 / 净资产
        """
        close = self._close()

        # 模拟数据（实际应从财务表获取）
        np.random.seed(46)
        net_profit = close * (0.1 + np.random.randn(len(close)) * 0.03) * 1e8
        book_value = close * 1e9

        roe = net_profit / book_value

        return self._winsorize(roe, limits=(0.01, 0.01))

    def prof_roa(self) -> pd.Series:
        """
        ROA (总资产收益率)

        计算：净利润 / 总资产
        """
        close = self._close()

        # 模拟数据
        np.random.seed(47)
        net_profit = close * (0.1 + np.random.randn(len(close)) * 0.03) * 1e8
        total_assets = close * 1.5e9

        roa = net_profit / total_assets

        return self._winsorize(roa, limits=(0.01, 0.01))

    def prof_gpm(self) -> pd.Series:
        """
        毛利率 (Gross Profit Margin)

        计算：(营业收入 - 营业成本) / 营业收入
        """
        close = self._close()

        # 模拟数据
        np.random.seed(48)
        revenue = close * 2e8
        cost = revenue * (0.6 + np.random.randn(len(close)) * 0.1)

        gpm = (revenue - cost) / revenue

        return self._winsorize(gpm, limits=(0.01, 0.01))

    def prof_npm(self) -> pd.Series:
        """
        净利率 (Net Profit Margin)

        计算：净利润 / 营业收入
        """
        close = self._close()

        # 模拟数据
        np.random.seed(49)
        revenue = close * 2e8
        net_profit = revenue * (0.1 + np.random.randn(len(close)) * 0.05)

        npm = net_profit / revenue

        return self._winsorize(npm, limits=(0.01, 0.01))

    def prof_ebitda_margin(self) -> pd.Series:
        """
        EBITDA利润率

        计算：EBITDA / 营业收入
        """
        close = self._close()

        # 模拟数据
        np.random.seed(50)
        revenue = close * 2e8
        ebitda = revenue * (0.15 + np.random.randn(len(close)) * 0.05)

        margin = ebitda / revenue

        return self._winsorize(margin, limits=(0.01, 0.01))

    # ==================== 成长因子 ====================

    def _calculate_growth(self, current: pd.Series, previous: pd.Series) -> pd.Series:
        """
        计算增长率

        处理负值和零值的情况
        """
        # 避免除以零
        previous_safe = previous.replace(0, np.nan)

        # 计算增长率
        growth = (current - previous_safe) / previous_safe.abs()

        # 限制极端值
        return self._winsorize(growth, limits=(0.05, 0.05))

    def grow_np_q(self) -> pd.Series:
        """
        净利润季度同比增速
        """
        close = self._close()

        # 模拟当前和去年同期净利润
        np.random.seed(51)
        current_np = close * (0.1 + np.random.randn(len(close)) * 0.02) * 1e8
        previous_np = current_np * (0.9 + np.random.randn(len(close)) * 0.1)

        return self._calculate_growth(current_np, previous_np)

    def grow_rev_q(self) -> pd.Series:
        """
        营业收入季度同比增速
        """
        close = self._close()

        # 模拟数据
        np.random.seed(52)
        current_rev = close * 2e8
        previous_rev = current_rev * (0.95 + np.random.randn(len(close)) * 0.1)

        return self._calculate_growth(current_rev, previous_rev)

    def grow_np_y(self) -> pd.Series:
        """
        净利润年度同比增速
        """
        close = self._close()

        # 模拟数据
        np.random.seed(53)
        current_np = close * (0.1 + np.random.randn(len(close)) * 0.02) * 1e8
        previous_np = current_np * (0.85 + np.random.randn(len(close)) * 0.15)

        return self._calculate_growth(current_np, previous_np)

    def grow_rev_y(self) -> pd.Series:
        """
        营业收入年度同比增速
        """
        close = self._close()

        # 模拟数据
        np.random.seed(54)
        current_rev = close * 2e8
        previous_rev = current_rev * (0.9 + np.random.randn(len(close)) * 0.12)

        return self._calculate_growth(current_rev, previous_rev)

    def grow_asset(self) -> pd.Series:
        """
        总资产同比增速
        """
        close = self._close()

        # 模拟数据
        np.random.seed(55)
        current_asset = close * 1.5e9
        previous_asset = current_asset * (0.92 + np.random.randn(len(close)) * 0.08)

        return self._calculate_growth(current_asset, previous_asset)

    # ==================== 质量因子 ====================

    def qual_debt(self) -> pd.Series:
        """
        资产负债率 (Debt Ratio)

        计算：总负债 / 总资产
        注意：质量因子通常取负值（低负债更好）
        """
        close = self._close()

        # 模拟数据
        np.random.seed(56)
        total_assets = close * 1.5e9
        total_liabilities = total_assets * (0.4 + np.random.randn(len(close)) * 0.15)

        debt_ratio = total_liabilities / total_assets

        # 质量因子：低负债更好，所以取负值
        return -self._winsorize(debt_ratio, limits=(0.01, 0.01))

    def qual_current(self) -> pd.Series:
        """
        流动比率 (Current Ratio)

        计算：流动资产 / 流动负债
        高流动比率表示更好的短期偿债能力
        """
        close = self._close()

        # 模拟数据
        np.random.seed(57)
        current_assets = close * 0.8e9
        current_liabilities = current_assets / (1.5 + np.random.randn(len(close)) * 0.5)

        current_ratio = current_assets / current_liabilities

        return self._winsorize(current_ratio, limits=(0.02, 0.02))

    def qual_quick(self) -> pd.Series:
        """
        速动比率 (Quick Ratio)

        计算：(流动资产 - 存货) / 流动负债
        """
        close = self._close()

        # 模拟数据
        np.random.seed(58)
        current_assets = close * 0.8e9
        inventory = current_assets * 0.3
        current_liabilities = (current_assets - inventory) / (1.2 + np.random.randn(len(close)) * 0.4)

        quick_ratio = (current_assets - inventory) / current_liabilities

        return self._winsorize(quick_ratio, limits=(0.02, 0.02))

    def qual_accrual(self) -> pd.Series:
        """
        应计项比率 (Accrual Ratio)

        计算：(净利润 - 经营现金流) / 总资产
        注意：低应计项更好，所以取负值
        """
        close = self._close()

        # 模拟数据
        np.random.seed(59)
        net_profit = close * 0.1 * 1e8
        operating_cf = net_profit * (0.8 + np.random.randn(len(close)) * 0.2)
        total_assets = close * 1.5e9

        accrual = (net_profit - operating_cf) / total_assets

        # 低应计项更好，取负值
        return -self._winsorize(accrual, limits=(0.02, 0.02))

    # ==================== 工具方法 ====================

    def _winsorize(self, series: pd.Series, limits: Tuple[float, float] = (0.01, 0.01)) -> pd.Series:
        """
        去极值处理（按交易日截面分组）

        Parameters
        ----------
        series : pd.Series
            输入序列，索引为 (trade_date, stock_code) 的 MultiIndex
        limits : tuple
            上下限分位数

        Returns
        -------
        pd.Series
            去极值后的序列
        """
        if isinstance(series.index, pd.MultiIndex) and 'trade_date' in series.index.names:
            return series.groupby(level='trade_date').transform(
                lambda x: x.clip(lower=x.quantile(limits[0]), upper=x.quantile(1 - limits[1]))
            )
        lower = series.quantile(limits[0])
        upper = series.quantile(1 - limits[1])
        return series.clip(lower, upper)

    # ==================== 批量计算 ====================

    def calculate_all(self) -> Dict[str, pd.Series]:
        """
        计算所有基本面因子

        Returns
        -------
        Dict[str, pd.Series]
            因子名称到因子值的映射
        """
        print("\n[基本面因子计算]")

        # 估值因子
        print("  计算估值因子...")
        valuation_methods = {
            'VAL_PE': self.val_pe,
            'VAL_PB': self.val_pb,
            'VAL_PS': self.val_ps,
            'VAL_PCF': self.val_pcf,
            'VAL_EP': self.val_ep,
            'VAL_BP': self.val_bp,
            'VAL_SP': self.val_sp,
            'VAL_CFP': self.val_cfp,
        }

        for name, method in valuation_methods.items():
            try:
                self._factors[name] = method()
                print(f"    ✓ {name}")
            except Exception as e:
                print(f"    ✗ {name}: {e}")

        # 盈利因子
        print("  计算盈利因子...")
        profitability_methods = {
            'PROF_ROE': self.prof_roe,
            'PROF_ROA': self.prof_roa,
            'PROF_GPM': self.prof_gpm,
            'PROF_NPM': self.prof_npm,
            'PROF_EBITDA': self.prof_ebitda_margin,
        }

        for name, method in profitability_methods.items():
            try:
                self._factors[name] = method()
                print(f"    ✓ {name}")
            except Exception as e:
                print(f"    ✗ {name}: {e}")

        # 成长因子
        print("  计算成长因子...")
        growth_methods = {
            'GROW_NP_Q': self.grow_np_q,
            'GROW_REV_Q': self.grow_rev_q,
            'GROW_NP_Y': self.grow_np_y,
            'GROW_REV_Y': self.grow_rev_y,
            'GROW_ASSET': self.grow_asset,
        }

        for name, method in growth_methods.items():
            try:
                self._factors[name] = method()
                print(f"    ✓ {name}")
            except Exception as e:
                print(f"    ✗ {name}: {e}")

        # 质量因子
        print("  计算质量因子...")
        quality_methods = {
            'QUAL_DEBT': self.qual_debt,
            'QUAL_CURRENT': self.qual_current,
            'QUAL_QUICK': self.qual_quick,
            'QUAL_ACCRUAL': self.qual_accrual,
        }

        for name, method in quality_methods.items():
            try:
                self._factors[name] = method()
                print(f"    ✓ {name}")
            except Exception as e:
                print(f"    ✗ {name}: {e}")

        print(f"  总计: {len(self._factors)} 个基本面因子")

        return self._factors

    def calculate_valuation_factors(self) -> Dict[str, pd.Series]:
        """仅计算估值因子"""
        factors = {}
        methods = {
            'VAL_PE': self.val_pe,
            'VAL_PB': self.val_pb,
            'VAL_PS': self.val_ps,
            'VAL_PCF': self.val_pcf,
        }
        for name, method in methods.items():
            try:
                factors[name] = method()
            except Exception as e:
                print(f"计算 {name} 时出错: {e}")
        return factors

    def calculate_profitability_factors(self) -> Dict[str, pd.Series]:
        """仅计算盈利因子"""
        factors = {}
        methods = {
            'PROF_ROE': self.prof_roe,
            'PROF_ROA': self.prof_roa,
            'PROF_GPM': self.prof_gpm,
            'PROF_NPM': self.prof_npm,
            'PROF_EBITDA': self.prof_ebitda_margin,
        }
        for name, method in methods.items():
            try:
                factors[name] = method()
            except Exception as e:
                print(f"计算 {name} 时出错: {e}")
        return factors

    def get_factor_info(self, factor_id: str) -> Optional[Dict]:
        """
        获取因子信息

        Parameters
        ----------
        factor_id : str
            因子ID

        Returns
        -------
        dict or None
            因子元数据
        """
        return FUNDAMENTAL_FACTOR_META.get(factor_id)

    def get_factors_by_category(self, category: FactorCategory) -> List[str]:
        """
        按分类获取因子列表

        Parameters
        ----------
        category : FactorCategory
            因子分类

        Returns
        -------
        List[str]
            该分类下的因子ID列表
        """
        return [
            factor_id
            for factor_id, meta in FUNDAMENTAL_FACTOR_META.items()
            if meta.get("category") == category
        ]
