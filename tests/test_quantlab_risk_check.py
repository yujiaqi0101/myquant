"""
A 股 RiskCheck 集合单元测试。

覆盖：
    - LimitUpCheck       : 涨停日 buy 拒单；非涨停日 buy 通过
    - LimitDownCheck     : 跌停日 sell 拒单
    - STFilterCheck      : ST 股拒单；正常股通过
    - TPlusOneCheck      : 当日 buy 后当日 sell 拒单；T+1 后 sell 通过
    - NewStockCheck      : 上市 30 天拒单；上市 200 天通过
    - SuspendCheck       : suspend_flag=1 拒单；=0 通过
    - build_ashare_risk_manager : 默认配置下 ≥ 8 个 check
"""

import os
import sys
from datetime import date, timedelta

# 让 D:\python_workspace\myquant\src 加入 sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import unittest  # noqa: E402

from src.quantlab.core.order import Order  # noqa: E402

from src.quantlab_extras.limit_filter import (  # noqa: E402
    LimitUpCheck,
    LimitDownCheck,
)
from src.quantlab_extras.st_filter import (  # noqa: E402
    STFilterCheck,
)
from src.quantlab_extras.t_plus_one import (  # noqa: E402
    TPlusOneCheck,
)
from src.quantlab_extras.new_stock import (  # noqa: E402
    NewStockCheck,
)
from src.quantlab_extras.suspend import (  # noqa: E402
    SuspendCheck,
)
from src.quantlab_extras.factory import (  # noqa: E402
    build_ashare_risk_manager,
    build_ashare_execution,
)


# ---------- 测试辅助 ----------

def _order(symbol: str, qty: int) -> Order:
    return Order(symbol=symbol, quantity=qty)


# ---------- TestLimitChecks ----------

class TestLimitUpCheck(unittest.TestCase):

    def test_reject_buy_on_limit_up(self):
        """主板涨停日 buy -> 拒单"""
        check = LimitUpCheck()
        ctx = {
            "market_data": {
                "600000": {
                    "pre_close": 10.00,
                    "close": 11.00,  # +10% 涨停
                }
            }
        }
        self.assertFalse(check.check(_order("600000", 100), ctx))

    def test_allow_buy_on_normal_day(self):
        """主板非涨停日 buy -> 通过"""
        check = LimitUpCheck()
        ctx = {
            "market_data": {
                "600000": {
                    "pre_close": 10.00,
                    "close": 10.50,  # +5%
                }
            }
        }
        self.assertTrue(check.check(_order("600000", 100), ctx))

    def test_chinext_limit_up_20pct(self):
        """创业板涨停 20% 才拒"""
        check = LimitUpCheck()
        ctx_chinext = {
            "market_data": {
                "300750": {
                    "pre_close": 100.00,
                    "close": 120.00,  # +20% 涨停
                }
            }
        }
        self.assertFalse(check.check(_order("300750", 100), ctx_chinext))

        ctx_normal = {
            "market_data": {
                "300750": {
                    "pre_close": 100.00,
                    "close": 115.00,  # +15% 不算涨停
                }
            }
        }
        self.assertTrue(check.check(_order("300750", 100), ctx_normal))


class TestLimitDownCheck(unittest.TestCase):

    def test_reject_sell_on_limit_down(self):
        """主板跌停日 sell -> 拒单"""
        check = LimitDownCheck()
        ctx = {
            "market_data": {
                "000001": {
                    "pre_close": 10.00,
                    "close": 9.00,  # -10% 跌停
                }
            }
        }
        self.assertFalse(check.check(_order("000001", -100), ctx))

    def test_allow_sell_on_normal_day(self):
        check = LimitDownCheck()
        ctx = {
            "market_data": {
                "000001": {
                    "pre_close": 10.00,
                    "close": 9.50,  # -5%
                }
            }
        }
        self.assertTrue(check.check(_order("000001", -100), ctx))


# ---------- TestSTFilterCheck ----------

class TestSTFilterCheck(unittest.TestCase):

    def test_reject_st_stock(self):
        check = STFilterCheck()
        ctx = {
            "stock_info": {
                "600519": {"name": "ST茅台", "industry": "白酒"},
            }
        }
        self.assertFalse(check.check(_order("600519", 100), ctx))

    def test_reject_starmark_stock(self):
        check = STFilterCheck()
        ctx = {
            "stock_info": {
                "000001": {"name": "*ST平安", "industry": "金融"},
            }
        }
        self.assertFalse(check.check(_order("000001", 100), ctx))

    def test_reject_delisted_stock(self):
        check = STFilterCheck()
        ctx = {
            "stock_info": {
                "600000": {"name": "退市浦发", "industry": "金融"},
            }
        }
        self.assertFalse(check.check(_order("600000", -100), ctx))

    def test_allow_normal_stock(self):
        check = STFilterCheck()
        ctx = {
            "stock_info": {
                "600519": {"name": "贵州茅台", "industry": "白酒"},
            }
        }
        self.assertTrue(check.check(_order("600519", 100), ctx))


# ---------- TestTPlusOneCheck ----------

class _FakeFill:
    def __init__(self, symbol: str, quantity: int):
        self.symbol = symbol
        self.quantity = quantity


class TestTPlusOneCheck(unittest.TestCase):

    def test_reject_sell_same_day_after_buy(self):
        check = TPlusOneCheck()
        ctx = {"current_date": "2024-01-15"}

        # 模拟当日买入
        check.update_after_fill(
            _FakeFill("600000", 100),
            {"current_date": "2024-01-15"},
        )
        # 同日卖出 -> 拒单
        self.assertFalse(check.check(_order("600000", -100), ctx))

    def test_allow_sell_next_day(self):
        check = TPlusOneCheck()
        # 模拟 1/15 买入
        check.update_after_fill(
            _FakeFill("600000", 100),
            {"current_date": "2024-01-15"},
        )
        # 1/16 卖出 -> 通过
        ctx = {"current_date": "2024-01-16"}
        self.assertTrue(check.check(_order("600000", -100), ctx))


# ---------- TestNewStockCheck ----------

class TestNewStockCheck(unittest.TestCase):

    def test_reject_within_60_days(self):
        check = NewStockCheck(min_days=60)
        today = date(2024, 6, 1)
        list_date = (today - timedelta(days=30)).isoformat()
        ctx = {
            "current_date": today.isoformat(),
            "market_data": {
                "301000": {"list_date": list_date}
            }
        }
        self.assertFalse(check.check(_order("301000", 100), ctx))

    def test_allow_after_60_days(self):
        check = NewStockCheck(min_days=60)
        today = date(2024, 6, 1)
        list_date = (today - timedelta(days=200)).isoformat()
        ctx = {
            "current_date": today.isoformat(),
            "market_data": {
                "301000": {"list_date": list_date}
            }
        }
        self.assertTrue(check.check(_order("301000", 100), ctx))


# ---------- TestSuspendCheck ----------

class TestSuspendCheck(unittest.TestCase):

    def test_reject_when_suspended(self):
        check = SuspendCheck()
        ctx = {
            "market_data": {
                "600000": {"suspend_flag": 1}
            }
        }
        self.assertFalse(check.check(_order("600000", 100), ctx))

    def test_allow_when_normal(self):
        check = SuspendCheck()
        ctx = {
            "market_data": {
                "600000": {"suspend_flag": 0}
            }
        }
        self.assertTrue(check.check(_order("600000", 100), ctx))


# ---------- TestFactory ----------

class TestBuildAshareRiskManager(unittest.TestCase):

    def test_default_has_at_least_8_checks(self):
        rm = build_ashare_risk_manager()
        # 6 个 A 股 check + OrderSizeCheck + KillSwitch = 8
        self.assertGreaterEqual(len(rm.checks), 8)

    def test_check_names_cover_all_ashare_cases(self):
        rm = build_ashare_risk_manager()
        names = {c.name for c in rm.checks}
        for must_have in (
            "LIMIT_UP",
            "LIMIT_DOWN",
            "ST_FILTER",
            "T_PLUS_ONE",
            "NEW_STOCK",
            "SUSPEND",
            "ORDER_SIZE",
            "KILL_SWITCH",
        ):
            self.assertIn(must_have, names)

    def test_can_disable_some_checks(self):
        rm = build_ashare_risk_manager(
            enable_st_filter=False,
            enable_suspend_filter=False,
        )
        names = {c.name for c in rm.checks}
        self.assertNotIn("ST_FILTER", names)
        self.assertNotIn("SUSPEND", names)
        # 但其它默认 check 仍在
        self.assertIn("LIMIT_UP", names)
        self.assertIn("KILL_SWITCH", names)


class TestBuildAshareExecution(unittest.TestCase):

    def test_default_lot_size_100(self):
        execution = build_ashare_execution()
        self.assertEqual(execution.lot_size, 100)
        # commission / slippage 挂在对象上
        self.assertAlmostEqual(execution.commission.rate, 0.00025)
        self.assertAlmostEqual(execution.slippage.rate, 0.0001)


if __name__ == "__main__":
    unittest.main()
