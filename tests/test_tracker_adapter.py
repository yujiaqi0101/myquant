"""
tests/test_tracker_adapter.py
=============================

MyquantTracker + 4 张 quantlab_* 表的端到端测试。

覆盖：
    1) myquant aquant.db 初始化时含 4 张 quantlab_* 表
    2) MyquantTracker.run() 写 1 行 experiments + 1 行 results
    3) MyquantTracker.search() 支持 strategy/sharpe_min/... 过滤
    4) MyquantTracker.leaderboard() 按 sort_by 排序
    5) MyquantTracker.run() 拒绝未注册策略
    6) MyquantTracker.run() 写入后 aquant.db 业务表（stock_daily 等）不受影响

执行：
    python -m pytest tests/test_tracker_adapter.py -v
"""

from __future__ import annotations

import sys
import os
import sqlite3
import tempfile
import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# =========================================================================
# 1) aquant.db 初始化时含 4 张 quantlab_* 表
# =========================================================================
class TestQuantlabTablesInAquant:
    """DatabaseManager init_db() 应创建 4 张 quantlab_* 表。"""

    def test_init_creates_4_quantlab_tables(self, tmp_path):
        from src.data.database import DatabaseManager

        db_path = str(tmp_path / "aquant.db")
        dbm = DatabaseManager(db_path)
        with dbm.get_connection() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name LIKE 'quantlab_%'"
            ).fetchall()
        table_names = sorted([r["name"] for r in rows])
        expected = sorted([
            "quantlab_experiments",
            "quantlab_results",
            "quantlab_walkforward",
            "quantlab_quintile_results",
        ])
        assert table_names == expected, f"got {table_names}"

    def test_quantlab_experiments_schema(self, tmp_path):
        from src.data.database import DatabaseManager

        db_path = str(tmp_path / "aquant.db")
        dbm = DatabaseManager(db_path)
        with dbm.get_connection() as conn:
            cols = conn.execute(
                "PRAGMA table_info(quantlab_experiments)"
            ).fetchall()
        col_names = [c["name"] for c in cols]
        for c in ("id", "name", "strategy", "params_json",
                  "created_at", "tag", "note"):
            assert c in col_names, f"缺列 {c}"

    def test_quantlab_results_fk(self, tmp_path):
        """quantlab_results.experiment_id 应有外键 → experiments.id"""
        from src.data.database import DatabaseManager

        db_path = str(tmp_path / "aquant.db")
        dbm = DatabaseManager(db_path)
        with dbm.get_connection() as conn:
            fk = conn.execute(
                "PRAGMA foreign_key_list(quantlab_results)"
            ).fetchall()
        fk_list = [(r["from"], r["table"], r["to"]) for r in fk]
        assert ("experiment_id", "quantlab_experiments", "id") in fk_list, \
            f"外键缺失: {fk_list}"


# =========================================================================
# 2) MyquantTracker.run() 写入闭环
# =========================================================================
class TestMyquantTrackerRun:
    """Tracker 跑回测 + 写 aquant.db。"""

    def test_run_writes_1_exp_1_result(self, tmp_path):
        from src.quantlab_adapters import MyquantTracker
        from src.quantlab.research.tracker import ExperimentRecord
        from src.quantlab.core.backtest_result import BacktestResult
        from src.data.database import DatabaseManager

        db_path = str(tmp_path / "aquant.db")

        # Mock 引擎
        class MockEng:
            def run(self, strategy, data, **kw):
                return BacktestResult(
                    equity_curve=[1.0, 1.05, 1.10],
                    total_return=0.10, sharpe=1.5,
                    max_drawdown=-0.05, trade_count=5,
                    win_rate=0.6, final_equity=1.10, source="bar",
                )

        class FakeStrat:
            def __init__(self, **kw):
                pass

        tracker = MyquantTracker(
            strategy_registry={"fake": FakeStrat},
            db_path=db_path,
        )
        rec = ExperimentRecord(
            name="run_test_1", strategy_name="fake",
            params={"p1": 1, "p2": 2},
        )
        result = tracker.run(record=rec, engine=MockEng(), data={})

        # 1) 返回值
        assert result["metrics"]["sharpe"] == 1.5
        # 2) experiments +1
        with DatabaseManager(db_path).get_connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM quantlab_experiments"
            ).fetchone()["c"]
        assert n == 1
        # 3) results +1
        with DatabaseManager(db_path).get_connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM quantlab_results"
            ).fetchone()["c"]
            row = conn.execute(
                "SELECT * FROM quantlab_results"
            ).fetchone()
        assert n == 1
        assert row["sharpe"] == 1.5
        assert row["source"] == "bar"

    def test_run_rejects_unknown_strategy(self, tmp_path):
        from src.quantlab_adapters import MyquantTracker
        from src.quantlab.research.tracker import ExperimentRecord

        db_path = str(tmp_path / "aquant.db")
        tracker = MyquantTracker(
            strategy_registry={}, db_path=db_path,
        )
        rec = ExperimentRecord(
            name="x", strategy_name="unknown", params={}
        )
        with pytest.raises(KeyError):
            tracker.run(record=rec, engine=None, data={})


# =========================================================================
# 3) search / leaderboard
# =========================================================================
class TestMyquantTrackerSearch:
    """search / leaderboard API。"""

    def _setup_tracker(self, tmp_path, n=3):
        from src.quantlab_adapters import MyquantTracker
        from src.quantlab.research.tracker import ExperimentRecord
        from src.quantlab.core.backtest_result import BacktestResult

        db_path = str(tmp_path / "aquant.db")
        tracker = MyquantTracker(strategy_registry={}, db_path=db_path)

        # 直接调 _save
        sharpes = [0.5, 1.2, 2.0]
        for i, s in enumerate(sharpes[:n]):
            rec = ExperimentRecord(
                name=f"e_{i}", strategy_name="MACross",
                params={"p": i}, tag="trend",
            )
            tracker._save(rec, {
                "total_return": s / 10, "sharpe": s,
                "max_drawdown": -0.05, "trade_count": 5,
                "win_rate": 0.5, "final_equity": 1.0 + s / 10,
                "source": "bar",
            })
        return tracker, db_path

    def test_search_all(self, tmp_path):
        tracker, _ = self._setup_tracker(tmp_path, n=3)
        df = tracker.search()
        assert len(df) == 3

    def test_search_strategy_filter(self, tmp_path):
        tracker, _ = self._setup_tracker(tmp_path, n=3)
        df = tracker.search(strategy="MACross")
        assert len(df) == 3
        df2 = tracker.search(strategy="Unknown")
        assert len(df2) == 0

    def test_search_sharpe_min(self, tmp_path):
        tracker, _ = self._setup_tracker(tmp_path, n=3)
        df = tracker.search(sharpe_min=1.0)
        assert len(df) == 2
        df2 = tracker.search(sharpe_min=1.5)
        assert len(df2) == 1

    def test_search_tag(self, tmp_path):
        tracker, _ = self._setup_tracker(tmp_path, n=3)
        df = tracker.search(tag="trend")
        assert len(df) == 3
        df2 = tracker.search(tag="mean_revert")
        assert len(df2) == 0

    def test_leaderboard_sharpe(self, tmp_path):
        tracker, _ = self._setup_tracker(tmp_path, n=3)
        df = tracker.leaderboard(sort_by="sharpe", top=2)
        assert len(df) == 2
        assert df.iloc[0]["sharpe"] == 2.0


# =========================================================================
# 4) 不影响 aquant.db 业务表
# =========================================================================
class TestAquantBusinessTablesIntact:
    """quantlab_* 表不应影响原有 stock_daily / index_daily 等表。"""

    def test_business_tables_still_creatable(self, tmp_path):
        from src.data.database import DatabaseManager

        db_path = str(tmp_path / "aquant.db")
        dbm = DatabaseManager(db_path)
        with dbm.get_connection() as conn:
            # 业务表都应存在
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'quantlab_%' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        names = [r["name"] for r in rows]
        # 至少 stock_daily 还在
        assert "stock_daily" in names
        assert "strategy_versions" in names


# =========================================================================
# runner
# =========================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
