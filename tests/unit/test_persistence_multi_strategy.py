"""
tests/unit/test_persistence_multi_strategy.py
=============================================

多策略子账户持久化层测试。

覆盖 PersistenceRepository 的多策略子账户功能：
    - 主账户创建（init_main_account）
    - 主账户充值/提取（deposit/withdraw）
    - 子账户添加/删除（add_strategy/remove_strategy）
    - 子账户停用/启用（disable/enable）
    - 子账户资金隔离
    - 持仓/订单/成交/快照按 strategy_name 隔离
    - 子账户资金调整（adjust_strategy_capital）
    - 子账户重置（reset_strategy）

测试原则：
    1. 使用临时文件数据库（tempfile.mkdtemp），不污染项目数据库
    2. 不依赖外部 API，纯数据库 CRUD 测试
    3. 测试结束清理临时数据库文件

作者：余老板
"""

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.core.persistence import PersistenceRepository
from src.core.types import Direction, Order, OrderStatus, Position, PositionDirection
from src.data.database import DatabaseManager


# ---------------------------------------------------------------------------
# MockDB：轻量级数据库管理器（不触发 DatabaseManager 的全表初始化）
# ---------------------------------------------------------------------------


class MockDB:
    """轻量级数据库管理器，仅提供 get_connection() 接口。

    不继承 DatabaseManager，避免触发 _init_database() 创建 35 张表。
    使用临时文件路径，测试结束清理。
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_connection(self):
        """获取连接的上下文管理器（与 DatabaseManager 接口一致）。"""
        import sqlite3
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return _ctx()


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path):
    """临时数据库文件路径。"""
    return str(tmp_path / "test_account.db")


@pytest.fixture
def db(tmp_db_path):
    """MockDB 实例。"""
    return MockDB(tmp_db_path)


@pytest.fixture
def repo(db):
    """PersistenceRepository 实例。"""
    return PersistenceRepository(db)


# ---------------------------------------------------------------------------
# Position 工厂
# ---------------------------------------------------------------------------


def make_position(
    symbol: str = "600000.SH",
    quantity: float = 1000.0,
    avg_price: float = 10.0,
    market_price: float = 11.0,
    direction: PositionDirection = PositionDirection.LONG,
) -> Position:
    """构造 Position 实例。"""
    pos = Position(
        symbol=symbol,
        direction=direction,
        quantity=quantity,
        available=quantity,
        avg_price=avg_price,
        market_price=market_price,
        market_value=quantity * market_price,
        cost=quantity * avg_price,
        pnl=quantity * (market_price - avg_price),
    )
    return pos


def make_order(
    order_id: str = "ord_001",
    symbol: str = "600000.SH",
    direction: str = "buy",
    volume: float = 100.0,
    status: OrderStatus = OrderStatus.FILLED,
) -> Order:
    """构造 Order 实例。"""
    return Order(
        order_id=order_id,
        symbol=symbol,
        direction=Direction(direction),
        volume=volume,
        price_type="market",
        status=status,
        filled_volume=volume if status == OrderStatus.FILLED else 0.0,
        filled_price=10.0 if status == OrderStatus.FILLED else 0.0,
        created_time=datetime(2024, 6, 1, 9, 30, 0),
    )


# ---------------------------------------------------------------------------
# 主账户管理测试
# ---------------------------------------------------------------------------


class TestMainAccount:
    """主账户管理测试。"""

    def test_init_main_account_creates_with_initial_capital(self, repo):
        """主账户创建：初始资金=现金=总资产=峰值。"""
        ok = repo.init_main_account("acc_001", 1_000_000.0)
        assert ok is True

        acct = repo.get_main_account("acc_001")
        assert acct is not None
        assert acct["initial_capital"] == 1_000_000.0
        assert acct["cash"] == 1_000_000.0
        assert acct["allocated_capital"] == 0.0
        assert acct["total_value"] == 1_000_000.0
        assert acct["peak_value"] == 1_000_000.0
        assert acct["available_capital"] == 1_000_000.0
        # strategy_name 为空（主账户不绑定单一策略）
        assert acct["strategy_name"] is None

    def test_init_main_account_duplicate_returns_false(self, repo):
        """重复创建同名主账户失败。"""
        assert repo.init_main_account("acc_001", 1_000_000.0) is True
        assert repo.init_main_account("acc_001", 500_000.0) is False

    def test_deposit_main_account_increases_cash(self, repo):
        """充值：现金/总资产/峰值同步增加。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        ok = repo.deposit_main_account("acc_001", 500_000.0)
        assert ok is True

        acct = repo.get_main_account("acc_001")
        assert acct["cash"] == 1_500_000.0
        assert acct["total_value"] == 1_500_000.0
        assert acct["peak_value"] == 1_500_000.0

    def test_deposit_main_account_nonexistent_returns_false(self, repo):
        """充值不存在的账户失败。"""
        assert repo.deposit_main_account("not_exist", 100_000.0) is False

    def test_deposit_main_account_negative_amount_returns_false(self, repo):
        """充值负金额失败。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        assert repo.deposit_main_account("acc_001", -100.0) is False

    def test_withdraw_main_account_decreases_cash(self, repo):
        """提取：现金/总资产减少（仅限未分配现金）。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        ok = repo.withdraw_main_account("acc_001", 200_000.0)
        assert ok is True

        acct = repo.get_main_account("acc_001")
        assert acct["cash"] == 800_000.0
        assert acct["total_value"] == 800_000.0

    def test_withdraw_main_account_exceeding_available_fails(self, repo):
        """提取超过可用现金失败。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        # 分配 80 万给子账户
        repo.add_strategy("acc_001", "small_cap", 800_000.0)
        # 可用现金仅剩 20 万，提取 30 万应失败
        assert repo.withdraw_main_account("acc_001", 300_000.0) is False

    def test_list_main_accounts(self, repo):
        """列出全部主账户。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.init_main_account("acc_002", 500_000.0)
        accounts = repo.list_main_accounts()
        assert len(accounts) == 2
        assert accounts[0]["account_id"] == "acc_001"
        assert accounts[1]["account_id"] == "acc_002"


# ---------------------------------------------------------------------------
# 子账户策略管理测试
# ---------------------------------------------------------------------------


class TestStrategySubAccount:
    """子账户策略管理测试。"""

    def test_add_strategy_allocates_capital(self, repo):
        """添加子账户：主账户 allocated_capital 增加，可用减少。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        ok = repo.add_strategy("acc_001", "small_cap", 300_000.0)
        assert ok is True

        # 主账户资金状态
        main = repo.get_main_account("acc_001")
        assert main["allocated_capital"] == 300_000.0
        assert main["available_capital"] == 700_000.0
        # cash 不变（cash 是总现金，allocated_capital 是已冻结分配）
        assert main["cash"] == 1_000_000.0

        # 子账户资金状态
        strat = repo.get_strategy("acc_001", "small_cap")
        assert strat is not None
        assert strat["allocated_capital"] == 300_000.0
        assert strat["cash"] == 300_000.0
        assert strat["total_value"] == 300_000.0
        assert strat["enabled"] == 1

    def test_add_strategy_insufficient_available_fails(self, repo):
        """主账户可用现金不足时添加子账户失败。"""
        repo.init_main_account("acc_001", 500_000.0)
        assert repo.add_strategy("acc_001", "small_cap", 600_000.0) is False

    def test_add_strategy_duplicate_fails(self, repo):
        """重复添加同名子账户失败。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        assert repo.add_strategy("acc_001", "small_cap", 300_000.0) is True
        assert repo.add_strategy("acc_001", "small_cap", 200_000.0) is False

    def test_add_strategy_nonexistent_main_fails(self, repo):
        """主账户不存在时添加子账户失败。"""
        assert repo.add_strategy("not_exist", "small_cap", 100_000.0) is False

    def test_multiple_strategies_isolated_capital(self, repo):
        """一个主账户可同时拥有多个策略子账户，资金独立隔离。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "small_cap", 300_000.0)
        repo.add_strategy("acc_001", "pb_roe", 500_000.0)

        # 主账户已分配 80 万，可用 20 万
        main = repo.get_main_account("acc_001")
        assert main["allocated_capital"] == 800_000.0
        assert main["available_capital"] == 200_000.0

        # 两个子账户独立
        assert repo.get_strategy("acc_001", "small_cap")["cash"] == 300_000.0
        assert repo.get_strategy("acc_001", "pb_roe")["cash"] == 500_000.0

    def test_disable_strategy_keeps_data(self, repo):
        """停用子账户：enabled=0，资金和持仓数据保留。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "small_cap", 300_000.0)

        ok = repo.disable_strategy("acc_001", "small_cap")
        assert ok is True

        strat = repo.get_strategy("acc_001", "small_cap")
        assert strat["enabled"] == 0
        # 资金仍保留
        assert strat["cash"] == 300_000.0

    def test_enable_strategy(self, repo):
        """启用已停用的子账户。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "small_cap", 300_000.0)
        repo.disable_strategy("acc_001", "small_cap")

        ok = repo.enable_strategy("acc_001", "small_cap")
        assert ok is True

        strat = repo.get_strategy("acc_001", "small_cap")
        assert strat["enabled"] == 1

    def test_list_strategies_only_enabled_by_default(self, repo):
        """list_strategies 默认仅返回启用的子账户。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "s1", 300_000.0)
        repo.add_strategy("acc_001", "s2", 200_000.0)
        repo.disable_strategy("acc_001", "s2")

        # 默认仅启用
        enabled = repo.list_strategies("acc_001", enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0]["strategy_name"] == "s1"

        # 全部
        all_strats = repo.list_strategies("acc_001", enabled_only=False)
        assert len(all_strats) == 2

    def test_remove_strategy_recovers_capital(self, repo):
        """删除子账户：资金回收主账户，allocated_capital 减少。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "small_cap", 300_000.0)

        # 模拟子账户亏损到 25 万
        repo.update_strategy_state("acc_001", "small_cap", 250_000.0, 250_000.0)

        recovered = repo.remove_strategy("acc_001", "small_cap")
        assert recovered == 250_000.0

        # 子账户已删除
        assert repo.get_strategy("acc_001", "small_cap") is None

        # 主账户 allocated_capital 减回到 0
        main = repo.get_main_account("acc_001")
        assert main["allocated_capital"] == 0.0

    def test_remove_nonexistent_strategy_returns_none(self, repo):
        """删除不存在的子账户返回 None。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        assert repo.remove_strategy("acc_001", "not_exist") is None


# ---------------------------------------------------------------------------
# 持仓/订单/成交/快照按 strategy_name 隔离测试
# ---------------------------------------------------------------------------


class TestStrategyIsolation:
    """持仓/订单/成交/快照按 strategy_name 隔离测试。"""

    def test_positions_isolated_by_strategy(self, repo):
        """不同子账户的持仓互不干扰。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "s1", 300_000.0)
        repo.add_strategy("acc_001", "s2", 300_000.0)

        # s1 持仓 600000.SH
        repo.save_positions(
            "acc_001",
            {"600000.SH": make_position("600000.SH", 1000, 10.0, 11.0)},
            strategy_name="s1",
        )
        # s2 持仓 600001.SH
        repo.save_positions(
            "acc_001",
            {"600001.SH": make_position("600001.SH", 2000, 20.0, 21.0)},
            strategy_name="s2",
        )

        # 按 strategy 加载
        pos_s1 = repo.load_positions("acc_001", "s1")
        pos_s2 = repo.load_positions("acc_001", "s2")
        assert "600000.SH" in pos_s1
        assert "600001.SH" not in pos_s1
        assert "600001.SH" in pos_s2
        assert "600000.SH" not in pos_s2

        # 不指定 strategy 加载全部
        pos_all = repo.load_positions("acc_001", None)
        assert "600000.SH" in pos_all
        assert "600001.SH" in pos_all

    def test_positions_overwrite_same_strategy_only(self, repo):
        """save_positions 仅清空当前 strategy 的持仓，不影响其他 strategy。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "s1", 300_000.0)
        repo.add_strategy("acc_001", "s2", 300_000.0)

        # 两个子账户都持仓 600000.SH
        repo.save_positions(
            "acc_001",
            {"600000.SH": make_position("600000.SH", 1000, 10.0, 11.0)},
            strategy_name="s1",
        )
        repo.save_positions(
            "acc_001",
            {"600000.SH": make_position("600000.SH", 2000, 20.0, 21.0)},
            strategy_name="s2",
        )

        # s1 调仓后只有 600001.SH
        repo.save_positions(
            "acc_001",
            {"600001.SH": make_position("600001.SH", 500, 5.0, 6.0)},
            strategy_name="s1",
        )

        # s2 持仓不受影响
        pos_s2 = repo.load_positions("acc_001", "s2")
        assert "600000.SH" in pos_s2
        assert pos_s2["600000.SH"].quantity == 2000.0

    def test_orders_isolated_by_strategy(self, repo):
        """订单按 strategy_name 隔离保存与查询。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "s1", 300_000.0)
        repo.add_strategy("acc_001", "s2", 300_000.0)

        repo.save_order("acc_001", make_order("o1", "600000.SH"), strategy_name="s1")
        repo.save_order("acc_001", make_order("o2", "600001.SH"), strategy_name="s2")

        orders_s1 = repo.load_orders("acc_001", "s1")
        orders_s2 = repo.load_orders("acc_001", "s2")
        orders_all = repo.load_orders("acc_001", None)

        assert len(orders_s1) == 1
        assert orders_s1[0]["order_id"] == "o1"
        assert orders_s1[0]["strategy_name"] == "s1"
        assert len(orders_s2) == 1
        assert orders_s2[0]["order_id"] == "o2"
        assert len(orders_all) == 2

    def test_snapshots_isolated_by_strategy(self, repo):
        """每日快照按 strategy_name 隔离。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "s1", 300_000.0)
        repo.add_strategy("acc_001", "s2", 300_000.0)

        repo.save_snapshot(
            "acc_001", "2024-06-01",
            {"cash": 250_000.0, "market_value": 60_000.0, "total": 310_000.0,
             "daily_pnl": 10_000.0, "daily_pnl_pct": 0.033, "pnl": 10_000.0, "pnl_pct": 0.033},
            strategy_name="s1",
        )
        repo.save_snapshot(
            "acc_001", "2024-06-01",
            {"cash": 280_000.0, "market_value": 30_000.0, "total": 310_000.0,
             "daily_pnl": 10_000.0, "daily_pnl_pct": 0.033, "pnl": 10_000.0, "pnl_pct": 0.033},
            strategy_name="s2",
        )

        snaps_s1 = repo.load_snapshots("acc_001", "s1")
        snaps_s2 = repo.load_snapshots("acc_001", "s2")
        assert len(snaps_s1) == 1
        assert snaps_s1[0]["cash"] == 250_000.0
        assert len(snaps_s2) == 1
        assert snaps_s2[0]["cash"] == 280_000.0


# ---------------------------------------------------------------------------
# 资金调整与重置测试
# ---------------------------------------------------------------------------


class TestCapitalAdjustment:
    """子账户资金调整与重置测试。"""

    def test_adjust_capital_positive_appends_from_main(self, repo):
        """追加资金：从主账户可用现金转入子账户。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "small_cap", 300_000.0)

        ok = repo.adjust_strategy_capital("acc_001", "small_cap", 100_000.0)
        assert ok is True

        strat = repo.get_strategy("acc_001", "small_cap")
        assert strat["allocated_capital"] == 400_000.0
        assert strat["cash"] == 400_000.0

        main = repo.get_main_account("acc_001")
        assert main["allocated_capital"] == 400_000.0
        assert main["available_capital"] == 600_000.0

    def test_adjust_capital_negative_recovers_to_main(self, repo):
        """回收资金：从子账户现金返还主账户。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "small_cap", 300_000.0)

        ok = repo.adjust_strategy_capital("acc_001", "small_cap", -100_000.0)
        assert ok is True

        strat = repo.get_strategy("acc_001", "small_cap")
        assert strat["cash"] == 200_000.0
        assert strat["allocated_capital"] == 200_000.0

        main = repo.get_main_account("acc_001")
        assert main["allocated_capital"] == 200_000.0
        assert main["available_capital"] == 800_000.0

    def test_adjust_capital_negative_exceeding_cash_fails(self, repo):
        """回收金额超过子账户现金失败。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "small_cap", 300_000.0)

        # 子账户只有 30 万现金，回收 40 万应失败
        assert repo.adjust_strategy_capital("acc_001", "small_cap", -400_000.0) is False

    def test_adjust_capital_positive_exceeding_main_available_fails(self, repo):
        """追加金额超过主账户可用现金失败。"""
        repo.init_main_account("acc_001", 500_000.0)
        repo.add_strategy("acc_001", "small_cap", 300_000.0)

        # 主账户可用仅 20 万，追加 30 万应失败
        assert repo.adjust_strategy_capital("acc_001", "small_cap", 300_000.0) is False

    def test_reset_strategy_clears_history_keeps_capital(self, repo):
        """重置子账户：清空历史，资金回到指定金额。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "small_cap", 300_000.0)

        # 模拟交易后亏损到 25 万
        repo.update_strategy_state("acc_001", "small_cap", 250_000.0, 250_000.0)
        repo.save_positions(
            "acc_001",
            {"600000.SH": make_position("600000.SH", 1000, 10.0, 11.0)},
            strategy_name="small_cap",
        )
        repo.save_order("acc_001", make_order("o1"), strategy_name="small_cap")
        repo.save_snapshot(
            "acc_001", "2024-06-01",
            {"cash": 250_000.0, "market_value": 0, "total": 250_000.0,
             "daily_pnl": 0, "daily_pnl_pct": 0, "pnl": -50_000.0, "pnl_pct": -0.167},
            strategy_name="small_cap",
        )

        # 重置为 30 万（原分配资金）
        ok = repo.reset_strategy("acc_001", "small_cap")
        assert ok is True

        strat = repo.get_strategy("acc_001", "small_cap")
        assert strat["cash"] == 300_000.0
        assert strat["total_value"] == 300_000.0

        # 历史数据已清空
        assert repo.load_positions("acc_001", "small_cap") == {}
        assert repo.load_orders("acc_001", "small_cap") == []
        assert repo.load_snapshots("acc_001", "small_cap") == []

    def test_reset_strategy_with_new_capital(self, repo):
        """重置子账户到指定金额。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        repo.add_strategy("acc_001", "small_cap", 300_000.0)

        ok = repo.reset_strategy("acc_001", "small_cap", new_capital=500_000.0)
        assert ok is True

        strat = repo.get_strategy("acc_001", "small_cap")
        assert strat["cash"] == 500_000.0

    def test_reset_nonexistent_strategy_fails(self, repo):
        """重置不存在的子账户失败。"""
        repo.init_main_account("acc_001", 1_000_000.0)
        assert repo.reset_strategy("acc_001", "not_exist") is False


# ---------------------------------------------------------------------------
# ensure_tables 升级测试
# ---------------------------------------------------------------------------


class TestEnsureTablesUpgrade:
    """ensure_tables 列升级测试（模拟已有表缺少新列的场景）。"""

    def test_ensure_tables_creates_all_tables(self, repo, db):
        """首次调用 ensure_tables 创建全部 6 张表。"""
        # 显式调用 ensure_tables
        repo.ensure_tables()
        with db.get_connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = {t["name"] for t in tables}
            assert "account_info" in table_names
            assert "account_strategies" in table_names
            assert "account_positions" in table_names
            assert "account_orders" in table_names
            assert "account_fills" in table_names
            assert "account_snapshots" in table_names

    def test_ensure_tables_upgrades_old_tables(self, db):
        """已有表（缺新列）能被自动升级。"""
        # 模拟旧表结构（无 strategy_name/allocated_capital）
        with db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE account_info (
                    account_id VARCHAR(64) PRIMARY KEY,
                    strategy_name VARCHAR(100),
                    initial_capital DOUBLE NOT NULL,
                    cash DOUBLE NOT NULL,
                    frozen DOUBLE NOT NULL DEFAULT 0.0,
                    total_value DOUBLE NOT NULL,
                    peak_value DOUBLE NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE account_positions (
                    account_id VARCHAR(64) NOT NULL,
                    symbol VARCHAR(20) NOT NULL,
                    direction VARCHAR(10) NOT NULL,
                    quantity DOUBLE NOT NULL,
                    available DOUBLE NOT NULL,
                    avg_price DOUBLE NOT NULL,
                    market_price DOUBLE NOT NULL,
                    market_value DOUBLE NOT NULL,
                    cost DOUBLE NOT NULL,
                    pnl DOUBLE NOT NULL,
                    today_bought DOUBLE NOT NULL DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (account_id, symbol)
                )
            """)

        # 用 MockDB 创建 repo，ensure_tables 应自动升级
        repo = PersistenceRepository(db)
        repo.ensure_tables()

        # 验证新列已添加
        with db.get_connection() as conn:
            # account_info 应有 allocated_capital
            cols_info = {r[1] for r in conn.execute("PRAGMA table_info(account_info)").fetchall()}
            assert "allocated_capital" in cols_info

            # account_positions 应有 strategy_name
            cols_pos = {r[1] for r in conn.execute("PRAGMA table_info(account_positions)").fetchall()}
            assert "strategy_name" in cols_pos

        # 升级后能正常使用
        ok = repo.init_main_account("acc_001", 1_000_000.0)
        assert ok is True


# ---------------------------------------------------------------------------
# 完整多策略流程集成测试
# ---------------------------------------------------------------------------


class TestMultiStrategyWorkflow:
    """完整多策略流程集成测试：模拟用户从开户到多策略运行的完整路径。"""

    def test_full_workflow(self, repo):
        """完整流程：开户→充值→添加2个策略→运行→查询→调整→停用→恢复→删除。"""
        # 1. 开户（初始 100 万）
        assert repo.init_main_account("acc_001", 1_000_000.0) is True
        main = repo.get_main_account("acc_001")
        assert main["cash"] == 1_000_000.0

        # 2. 充值 50 万
        assert repo.deposit_main_account("acc_001", 500_000.0) is True
        main = repo.get_main_account("acc_001")
        assert main["cash"] == 1_500_000.0
        assert main["available_capital"] == 1_500_000.0

        # 3. 添加 2 个策略子账户
        assert repo.add_strategy("acc_001", "small_cap", 500_000.0) is True
        assert repo.add_strategy("acc_001", "pb_roe", 700_000.0) is True
        main = repo.get_main_account("acc_001")
        assert main["allocated_capital"] == 1_200_000.0
        assert main["available_capital"] == 300_000.0

        # 4. 运行策略 small_cap（模拟产生持仓和快照）
        repo.save_positions(
            "acc_001",
            {"600000.SH": make_position("600000.SH", 1000, 10.0, 11.0)},
            strategy_name="small_cap",
        )
        repo.update_strategy_state("acc_001", "small_cap", 490_000.0, 501_000.0)
        repo.save_snapshot(
            "acc_001", "2024-06-01",
            {"cash": 490_000.0, "market_value": 11_000.0, "total": 501_000.0,
             "daily_pnl": 1_000.0, "daily_pnl_pct": 0.002, "pnl": 1_000.0, "pnl_pct": 0.002},
            strategy_name="small_cap",
        )

        # 5. 运行策略 pb_roe（模拟产生持仓和快照）
        repo.save_positions(
            "acc_001",
            {"600001.SH": make_position("600001.SH", 2000, 20.0, 21.0)},
            strategy_name="pb_roe",
        )
        repo.update_strategy_state("acc_001", "pb_roe", 680_000.0, 702_000.0)
        repo.save_snapshot(
            "acc_001", "2024-06-01",
            {"cash": 680_000.0, "market_value": 42_000.0, "total": 722_000.0,
             "daily_pnl": 22_000.0, "daily_pnl_pct": 0.0314, "pnl": 22_000.0, "pnl_pct": 0.0314},
            strategy_name="pb_roe",
        )

        # 6. 查询：两个子账户持仓互不干扰
        pos_small = repo.load_positions("acc_001", "small_cap")
        pos_pb = repo.load_positions("acc_001", "pb_roe")
        assert "600000.SH" in pos_small
        assert "600001.SH" in pos_pb
        assert "600001.SH" not in pos_small

        # 7. 调整 small_cap 资金：追加 50 万
        assert repo.adjust_strategy_capital("acc_001", "small_cap", 50_000.0) is True
        strat = repo.get_strategy("acc_001", "small_cap")
        assert strat["cash"] == 540_000.0  # 490 + 50
        main = repo.get_main_account("acc_001")
        assert main["available_capital"] == 250_000.0  # 300 - 50

        # 8. 停用 pb_roe
        assert repo.disable_strategy("acc_001", "pb_roe") is True
        # 历史数据保留
        snaps = repo.load_snapshots("acc_001", "pb_roe")
        assert len(snaps) == 1

        # 9. 启用 pb_roe
        assert repo.enable_strategy("acc_001", "pb_roe") is True
        strat = repo.get_strategy("acc_001", "pb_roe")
        assert strat["enabled"] == 1

        # 10. 删除 small_cap（资金回收）
        recovered = repo.remove_strategy("acc_001", "small_cap")
        assert recovered == 540_000.0  # 子账户剩余现金回收
        # small_cap 数据已清空
        assert repo.get_strategy("acc_001", "small_cap") is None
        assert repo.load_positions("acc_001", "small_cap") == {}
        # pb_roe 不受影响
        assert repo.get_strategy("acc_001", "pb_roe") is not None
