"""
Qlib Alpha158 算子单元测试
==========================

验证：
- KBar 类（9 个）：KMID, KLEN, KMID2, KUP, KUP2, KLOW, KLOW2, KSFT, KSFT2
- Price/Volume 时序类（5 个）
- Rolling 统计类（6 个）
- Pattern 类（7 个）
- 字典 ALPHA158_FUNCS 索引正确
"""
import os
import sys
import unittest
import numpy as np
import pandas as pd

# 项目根加入 path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.factors.operators import (
    ALPHA158_FUNCS, get_alpha158_func,
)
from src.factors.operators.alpha158 import (
    kbar_kmid, kbar_klen, kbar_kmid2, kbar_kup, kbar_kup2,
    kbar_klow, kbar_klow2, kbar_ksft, kbar_ksft2,
    price_high_n, price_low_n, price_close_n, price_open_n, volume_mean_n,
    rolling_mean, rolling_std, rolling_sum, rolling_skew, rolling_kurt, rolling_qs,
    pattern_roc, pattern_rocr, pattern_rsv, pattern_rsi, pattern_cci,
    pattern_atr, pattern_boll,
)


def _make_ohlcv(n_days: int = 30, n_stocks: int = 3, seed: int = 42):
    """构造 3 只股票、30 天的 K 线 MultiIndex DataFrame

    约束 OHLC 关系：high >= max(open, close), low <= min(open, close)
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range('2024-01-01', periods=n_days, freq='D')
    codes = [f'SHSE.60{i:04d}' for i in range(n_stocks)]
    idx = pd.MultiIndex.from_product([dates, codes], names=['trade_date', 'stock_code'])
    n = n_days * n_stocks

    base = np.cumsum(rng.normal(0, 0.02, n), axis=0) + 10
    open_ = base + rng.normal(0, 0.1, n)
    close = base + rng.normal(0, 0.1, n)
    # 真实 K 线：high >= max(open, close) + 随机影线
    upper_shadow = rng.uniform(0.05, 0.2, n)
    lower_shadow = rng.uniform(0.05, 0.2, n)
    high = np.maximum(open_, close) + upper_shadow
    low = np.minimum(open_, close) - lower_shadow
    volume = rng.uniform(1e5, 1e6, n)
    amount = close * volume

    def _df(arr, name):
        return pd.DataFrame(
            {name: arr},
            index=idx,
        )

    return (
        _df(open_, 'open'),
        _df(high, 'high'),
        _df(low, 'low'),
        _df(close, 'close'),
        _df(volume, 'volume'),
        _df(amount, 'amount'),
    )


class TestKBar(unittest.TestCase):
    """K 线形态 9 个算子"""

    @classmethod
    def setUpClass(cls):
        cls.open_, cls.high, cls.low, cls.close, cls.volume, cls.amount = _make_ohlcv()

    def test_kmid(self):
        s = kbar_kmid(self.open_, self.close)
        self.assertEqual(s.shape, (self.close.size,))
        # 数值范围合理 + 不全为 NaN
        valid = s.dropna()
        self.assertGreater(len(valid), 0)
        # 全部 -1 < x < 1（百分比变化）
        self.assertTrue((valid > -1).all() and (valid < 1).all())

    def test_klen(self):
        s = kbar_klen(self.high, self.low, self.open_)
        self.assertEqual(s.shape, (self.close.size,))
        # KLEN >= 0
        valid = s.dropna()
        self.assertTrue((valid >= 0).all())

    def test_kmid2(self):
        s = kbar_kmid2(self.high, self.low, self.open_, self.close)
        valid = s.replace([np.inf, -np.inf], np.nan).dropna()
        self.assertGreater(len(valid), 0)

    def test_kup_non_negative(self):
        s = kbar_kup(self.high, self.open_, self.close)
        # 转为 Series 取值
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        valid = s.dropna()
        # KUP 永远 >= 0
        self.assertTrue((valid >= 0).all())

    def test_kup2_non_negative(self):
        s = kbar_kup2(self.high, self.low, self.open_, self.close)
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        valid = s.dropna()
        self.assertTrue((valid >= 0).all())

    def test_klow_non_negative(self):
        s = kbar_klow(self.low, self.open_, self.close)
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        valid = s.dropna()
        self.assertTrue((valid >= 0).all())

    def test_klow2_non_negative(self):
        s = kbar_klow2(self.high, self.low, self.open_, self.close)
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        valid = s.dropna()
        self.assertTrue((valid >= 0).all())

    def test_ksft(self):
        s = kbar_ksft(self.high, self.low, self.open_, self.close)
        self.assertEqual(s.shape, (self.close.size,))

    def test_ksft2(self):
        s = kbar_ksft2(self.high, self.low, self.close)
        self.assertEqual(s.shape, (self.close.size,))


class TestPriceVolume(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.open_, cls.high, cls.low, cls.close, cls.volume, cls.amount = _make_ohlcv()

    def test_high_n_shifts(self):
        s = price_high_n(self.high, n=1)
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        manual = self.high.groupby(level='stock_code').shift(1)
        if isinstance(manual, pd.DataFrame):
            manual = manual.iloc[:, 0]
        s_d = s.dropna().sort_index()
        m_d = manual.dropna().sort_index()
        self.assertEqual(len(s_d), len(m_d))
        # 数值应完全相同
        self.assertTrue(np.allclose(s_d.values, m_d.values))

    def test_low_n_shifts(self):
        s = price_low_n(self.low, n=2)
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        manual = self.low.groupby(level='stock_code').shift(2)
        if isinstance(manual, pd.DataFrame):
            manual = manual.iloc[:, 0]
        s_d = s.dropna().sort_index()
        m_d = manual.dropna().sort_index()
        self.assertEqual(len(s_d), len(m_d))
        self.assertTrue(np.allclose(s_d.values, m_d.values))

    def test_close_n_shifts(self):
        s = price_close_n(self.close, n=3)
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        manual = self.close.groupby(level='stock_code').shift(3)
        if isinstance(manual, pd.DataFrame):
            manual = manual.iloc[:, 0]
        s_d = s.dropna().sort_index()
        m_d = manual.dropna().sort_index()
        self.assertTrue(np.allclose(s_d.values, m_d.values))

    def test_open_n_shifts(self):
        s = price_open_n(self.open_, n=4)
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        manual = self.open_.groupby(level='stock_code').shift(4)
        if isinstance(manual, pd.DataFrame):
            manual = manual.iloc[:, 0]
        s_d = s.dropna().sort_index()
        m_d = manual.dropna().sort_index()
        self.assertTrue(np.allclose(s_d.values, m_d.values))

    def test_volume_mean_n(self):
        s = volume_mean_n(self.volume, n=5)
        # 范围合理
        self.assertTrue((s.dropna() > 0).all())


class TestRolling(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.open_, cls.high, cls.low, cls.close, cls.volume, cls.amount = _make_ohlcv()

    def test_rolling_mean(self):
        s = rolling_mean(self.close, n=5)
        self.assertTrue(np.isfinite(s.dropna()).all())

    def test_rolling_std(self):
        s = rolling_std(self.close, n=5)
        # std >= 0
        self.assertTrue((s.dropna() >= 0).all())

    def test_rolling_sum(self):
        s = rolling_sum(self.volume, n=3)
        self.assertTrue((s.dropna() > 0).all())

    def test_rolling_skew(self):
        s = rolling_skew(self.close, n=10)
        # 偏度可以正可负
        self.assertTrue(np.isfinite(s.dropna()).all())

    def test_rolling_kurt(self):
        s = rolling_kurt(self.close, n=10)
        self.assertTrue(np.isfinite(s.dropna()).all())

    def test_rolling_qs(self):
        s = rolling_qs(self.close, n=5, q=0.5)
        # 中位数接近均值
        self.assertTrue(np.isfinite(s.dropna()).all())


class TestPattern(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.open_, cls.high, cls.low, cls.close, cls.volume, cls.amount = _make_ohlcv()

    def test_roc(self):
        s = pattern_roc(self.close, n=5)
        # n 天前未定义时为 NaN
        self.assertEqual(s.shape, (self.close.size,))

    def test_rocr(self):
        s = pattern_rocr(self.close, n=5)
        # ROCR 应接近 1 附近
        valid = s.dropna()
        self.assertTrue((valid > 0.5).all() and (valid < 2.0).all())

    def test_rsv_range(self):
        s = pattern_rsv(self.high, self.low, self.close, n=10)
        # RSV 在 [0, 1] 范围内
        valid = s.dropna()
        self.assertTrue((valid >= 0).all() and (valid <= 1).all())

    def test_rsi_range(self):
        s = pattern_rsi(self.close, n=14)
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        # RSI 范围 [0, 1]（含边界）
        valid = s.dropna()
        self.assertGreater(len(valid), 0)
        self.assertTrue((valid >= 0).all())
        self.assertTrue((valid <= 1).all())

    def test_atr_positive(self):
        s = pattern_atr(self.high, self.low, self.close, n=14)
        self.assertTrue((s.dropna() >= 0).all())


class TestRegistry(unittest.TestCase):
    """ALPHA158_FUNCS 字典索引"""

    def test_kbar_keys(self):
        for k in ('KMID', 'KLEN', 'KMID2', 'KUP', 'KUP2', 'KLOW', 'KLOW2', 'KSFT', 'KSFT2'):
            self.assertIn(k, ALPHA158_FUNCS, f"{k} missing from ALPHA158_FUNCS")

    def test_rolling_keys(self):
        for k in ('MA_N', 'STD_N', 'SUM_N', 'SKEW_N', 'KURT_N', 'QS_N'):
            self.assertIn(k, ALPHA158_FUNCS, f"{k} missing from ALPHA158_FUNCS")

    def test_pattern_keys(self):
        for k in ('ROC_N', 'ROCR_N', 'RSV_N', 'RSI', 'ATR', 'BOLL'):
            self.assertIn(k, ALPHA158_FUNCS, f"{k} missing from ALPHA158_FUNCS")

    def test_get_alpha158_func_lookup(self):
        f = get_alpha158_func('KMID')
        self.assertIs(f, kbar_kmid)
        self.assertIsNone(get_alpha158_func('UNKNOWN'))

    def test_all_callable(self):
        for k, v in ALPHA158_FUNCS.items():
            self.assertTrue(callable(v), f"{k} is not callable")


if __name__ == '__main__':
    unittest.main()
