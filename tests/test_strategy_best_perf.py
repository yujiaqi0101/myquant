"""
best_perf_updater 单元测试
==========================

验证：
- update_strategy_best_perf() 从 quantlab_results 提炼最佳
- rebuild_all_best_perf() 批量处理
- list_missing_best_perf() 找出未提炼的 strategy
- ensure_best_perf_fresh() 补全缺失 + 重建过期
- strategy_info 行被自动创建
- best_experiment_id / best_sharpe 等关键字段被正确写入
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

# 项目根加入 path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data.database import DatabaseManager
from src.quantlab_adapters.best_perf_updater import (
    update_strategy_best_perf,
    rebuild_all_best_perf,
    list_missing_best_perf,
    ensure_best_perf_fresh,
)


def _seed_exp_result(db, exp_id, strategy, sharpe, total_return=0.1, max_dd=-0.05, source='bar'):
    """往 quantlab_experiments + quantlab_results 各插一条。"""
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO quantlab_experiments
                (id, name, strategy, params_json, created_at, tag, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (exp_id, f"name_{exp_id}", strategy, "{}", datetime.now().isoformat(), "", ""),
        )
        conn.execute(
            """
            INSERT INTO quantlab_results
                (experiment_id, final_equity, total_return, sharpe,
                 max_drawdown, trade_count, win_rate, source, extras_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (exp_id, 1.0 + total_return, total_return, sharpe, max_dd, 10, 0.6, source, "{}"),
        )


def _query_best_perf(db, strategy_id):
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM strategy_best_perf WHERE strategy_id = ?",
            (strategy_id,),
        ).fetchone()
    return dict(row) if row else None


def _query_strategy_info(db, strategy_id):
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM strategy_info WHERE strategy_id = ?",
            (strategy_id,),
        ).fetchone()
    return dict(row) if row else None


class TestUpdateStrategyBestPerf(unittest.TestCase):

    def setUp(self):
        f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        f.close()
        self.db_path = f.name
        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        DatabaseManager._initialized_paths.discard(
            str(self.db.db_path.resolve())
        )
        os.unlink(self.db_path)

    def test_no_results_returns_false(self):
        ok = update_strategy_best_perf(self.db_path, strategy_id="X", strategy_name="X")
        self.assertFalse(ok)
        self.assertIsNone(_query_best_perf(self.db, "X"))

    def test_single_experiment_writes_best(self):
        _seed_exp_result(self.db, "exp1", "MACross", sharpe=1.5, total_return=0.2)
        ok = update_strategy_best_perf(self.db_path, strategy_id="MACross", strategy_name="MACross")
        self.assertTrue(ok)

        row = _query_best_perf(self.db, "MACross")
        self.assertIsNotNone(row)
        self.assertEqual(row["best_experiment_id"], "exp1")
        self.assertAlmostEqual(row["best_sharpe"], 1.5, places=4)
        self.assertEqual(row["best_metric"], "sharpe")
        self.assertEqual(row["best_source"], "bar")
        # strategy_info 被自动创建
        info = _query_strategy_info(self.db, "MACross")
        self.assertIsNotNone(info)
        self.assertEqual(info["strategy_name"], "MACross")

    def test_picks_max_sharpe_across_experiments(self):
        """多个实验 → 取 sharpe 最高者。"""
        _seed_exp_result(self.db, "exp_low", "Momentum", sharpe=0.5)
        _seed_exp_result(self.db, "exp_high", "Momentum", sharpe=2.0)
        _seed_exp_result(self.db, "exp_mid", "Momentum", sharpe=1.0)
        update_strategy_best_perf(self.db_path, strategy_id="Momentum")

        row = _query_best_perf(self.db, "Momentum")
        self.assertEqual(row["best_experiment_id"], "exp_high")
        self.assertAlmostEqual(row["best_sharpe"], 2.0, places=4)

    def test_update_overwrites_previous(self):
        """二次调用覆盖前一记录。"""
        _seed_exp_result(self.db, "exp1", "Rev", sharpe=0.8)
        update_strategy_best_perf(self.db_path, strategy_id="Rev")
        first = _query_best_perf(self.db, "Rev")
        self.assertEqual(first["best_experiment_id"], "exp1")

        # 加新实验并再 update
        _seed_exp_result(self.db, "exp2", "Rev", sharpe=1.2)
        update_strategy_best_perf(self.db_path, strategy_id="Rev")
        second = _query_best_perf(self.db, "Rev")
        self.assertEqual(second["best_experiment_id"], "exp2")
        # 数值刷新到 exp2 对应
        self.assertAlmostEqual(second["best_sharpe"], 1.2, places=4)


class TestRebuildAllBestPerf(unittest.TestCase):

    def setUp(self):
        f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        f.close()
        self.db_path = f.name
        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        DatabaseManager._initialized_paths.discard(
            str(self.db.db_path.resolve())
        )
        os.unlink(self.db_path)

    def test_rebuild_processes_all(self):
        _seed_exp_result(self.db, "e1", "A", sharpe=1.0)
        _seed_exp_result(self.db, "e2", "B", sharpe=2.0)
        _seed_exp_result(self.db, "e3", "C", sharpe=3.0)
        stats = rebuild_all_best_perf(self.db_path)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["updated"], 3)
        self.assertEqual(stats["skipped"], 0)

        for sid in ("A", "B", "C"):
            self.assertIsNotNone(_query_best_perf(self.db, sid))

    def test_rebuild_empty_db(self):
        stats = rebuild_all_best_perf(self.db_path)
        self.assertEqual(stats, {"updated": 0, "skipped": 0, "total": 0})


class TestListMissing(unittest.TestCase):

    def setUp(self):
        f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        f.close()
        self.db_path = f.name
        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        DatabaseManager._initialized_paths.discard(
            str(self.db.db_path.resolve())
        )
        os.unlink(self.db_path)

    def test_lists_strategies_without_best_perf(self):
        _seed_exp_result(self.db, "e1", "Alpha", sharpe=1.0)
        _seed_exp_result(self.db, "e2", "Beta", sharpe=1.5)
        update_strategy_best_perf(self.db_path, strategy_id="Alpha")
        # Beta 缺
        missing = list_missing_best_perf(self.db_path)
        self.assertEqual(missing, ["Beta"])

    def test_empty_after_full_rebuild(self):
        _seed_exp_result(self.db, "e1", "X", sharpe=1.0)
        rebuild_all_best_perf(self.db_path)
        self.assertEqual(list_missing_best_perf(self.db_path), [])


class TestEnsureFresh(unittest.TestCase):
    """启动检查：缺失补全 + 过期重建。"""

    def setUp(self):
        f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        f.close()
        self.db_path = f.name
        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        DatabaseManager._initialized_paths.discard(
            str(self.db.db_path.resolve())
        )
        os.unlink(self.db_path)

    def test_missing_fixed(self):
        _seed_exp_result(self.db, "e1", "S1", sharpe=0.5)
        stats = ensure_best_perf_fresh(self.db_path, expire_after_seconds=999999)
        self.assertEqual(stats["missing_fixed"], 1)
        self.assertEqual(stats["stale_rebuilt"], 0)
        self.assertIsNotNone(_query_best_perf(self.db, "S1"))

    def test_stale_rebuilt(self):
        """last_updated 极旧 → 重建。"""
        _seed_exp_result(self.db, "e1", "S2", sharpe=0.5)
        update_strategy_best_perf(self.db_path, strategy_id="S2")
        # 手动把 last_updated 改成 100 天前
        old_ts = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE strategy_best_perf SET last_updated = ? WHERE strategy_id = ?",
                (old_ts, "S2"),
            )
        # 用 7 天阈值
        stats = ensure_best_perf_fresh(self.db_path, expire_after_seconds=7 * 24 * 3600)
        self.assertEqual(stats["stale_rebuilt"], 1)
        # 重新 update 后 last_updated 变成 CURRENT_TIMESTAMP
        row = _query_best_perf(self.db, "S2")
        self.assertNotEqual(row["last_updated"], old_ts)

    def test_no_action_when_fresh(self):
        _seed_exp_result(self.db, "e1", "S3", sharpe=0.5)
        update_strategy_best_perf(self.db_path, strategy_id="S3")
        stats = ensure_best_perf_fresh(self.db_path, expire_after_seconds=999999)
        self.assertEqual(stats["missing_fixed"], 0)
        self.assertEqual(stats["stale_rebuilt"], 0)


if __name__ == '__main__':
    unittest.main()
