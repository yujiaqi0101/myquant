"""
quantlab_cli track 子命令单元测试
================================

验证：
- track list / show / leaderboard / search / delete 子动作
- track rebuild-best-perf 重建 strategy_best_perf
- track view 双表显示
- argparse 子解析器能正确解析 track 子动作
"""
import os
import sys
import argparse
import tempfile
import unittest
import unittest.mock
from datetime import datetime
from contextlib import redirect_stdout
import io

# 项目根加入 path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data.database import DatabaseManager
from src.cli.quantlab_cli import (
    setup_track_parser,
    track_quantlab_command,
)
from src.quantlab_adapters import MyquantTracker
from src.quantlab.research.tracker import ExperimentRecord


def _seed_qrecord(db, exp_id, strategy, sharpe, total_return=0.1, tag=""):
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO quantlab_experiments
                (id, name, strategy, params_json, created_at, tag, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (exp_id, f"n_{exp_id}", strategy, "{}", datetime.now().isoformat(), tag, ""),
        )
        conn.execute(
            """
            INSERT INTO quantlab_results
                (experiment_id, final_equity, total_return, sharpe,
                 max_drawdown, trade_count, win_rate, source, extras_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (exp_id, 1.0 + total_return, total_return, sharpe, -0.05, 10, 0.6, "bar", "{}"),
        )


def _parse_track_args(args_list):
    """辅助：用 setup_track_parser 解析子命令。

    注意：argparse 不允许在 setup_track_parser 外另建 subparsers，
    所以这里直接传一个空 parser，让 setup_track_parser 内部创建。
    """
    parser = argparse.ArgumentParser()
    setup_track_parser(parser)
    return parser.parse_args(args_list)


class TestTrackParser(unittest.TestCase):
    """argparse 子解析器能识别 7 个子动作。"""

    def test_list(self):
        args = _parse_track_args(["list", "--limit", "10"])
        self.assertEqual(args.track_action, "list")
        self.assertEqual(args.limit, 10)

    def test_show(self):
        args = _parse_track_args(["show", "--id", "exp1"])
        self.assertEqual(args.track_action, "show")
        self.assertEqual(args.id, "exp1")

    def test_leaderboard(self):
        args = _parse_track_args(["leaderboard", "--sort-by", "sharpe", "--top", "5"])
        self.assertEqual(args.track_action, "leaderboard")
        self.assertEqual(args.sort_by, "sharpe")
        self.assertEqual(args.top, 5)

    def test_search(self):
        args = _parse_track_args([
            "search", "--strategy", "MACross",
            "--sharpe-min", "1.0", "--tag", "t1",
        ])
        self.assertEqual(args.track_action, "search")
        self.assertEqual(args.strategy, "MACross")
        self.assertEqual(args.sharpe_min, 1.0)
        self.assertEqual(args.tag, "t1")

    def test_delete(self):
        args = _parse_track_args(["delete", "--id", "exp1"])
        self.assertEqual(args.track_action, "delete")

    def test_rebuild_best_perf(self):
        args = _parse_track_args(["rebuild-best-perf"])
        self.assertEqual(args.track_action, "rebuild-best-perf")

    def test_view(self):
        args = _parse_track_args(["view", "--strategy", "X", "--limit", "5"])
        self.assertEqual(args.track_action, "view")
        self.assertEqual(args.strategy, "X")
        self.assertEqual(args.limit, 5)


class TestTrackCommand(unittest.TestCase):
    """track_quantlab_command 各子动作的端到端行为（使用临时 db）。"""

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

    def _patch_db_path(self):
        """把 _get_db_path() 替换为返回 self.db_path。"""
        from src.cli import backtest_cli
        return unittest.mock.patch.object(
            backtest_cli, '_get_db_path', return_value=self.db_path,
        )

    def _patch_repo(self, repo_mock):
        """把 ExperimentRepository 替换为 mock。

        track_quantlab_command 内部用 `from src.quantlab.research.repository
        import ExperimentRepository`，因此需要 patch 那个 module。
        """
        from src.quantlab import research
        return unittest.mock.patch.object(
            research.repository,
            'ExperimentRepository',
            return_value=repo_mock,
        )

    def _make_repo(self, df=None, row=None):
        """构造一个 mock repo（list/leaderboard/search 返回 df，get 返回 row，delete 计数）。"""
        import pandas as _pd
        repo = unittest.mock.MagicMock()
        repo.list_all.return_value = df if df is not None else _pd.DataFrame()
        repo.leaderboard.return_value = df if df is not None else _pd.DataFrame()
        repo.search.return_value = df if df is not None else _pd.DataFrame()
        repo.get.return_value = row
        return repo

    def test_list_empty(self):
        args = argparse.Namespace(track_action="list", limit=10)
        repo = self._make_repo()
        with self._patch_db_path(), self._patch_repo(repo):
            buf = io.StringIO()
            with redirect_stdout(buf):
                track_quantlab_command(args)
        self.assertIn("暂无 experiment", buf.getvalue())

    def test_list_with_rows(self):
        import pandas as _pd
        _seed_qrecord(self.db, "e1", "A", sharpe=1.0)
        _seed_qrecord(self.db, "e2", "B", sharpe=2.0)
        df = _pd.DataFrame([
            {"id": "e1", "name": "n1", "strategy": "A",
             "sharpe": 1.0, "total_return": 0.1, "max_drawdown": -0.05,
             "trade_count": 10, "created_at": "2024-01-01"},
            {"id": "e2", "name": "n2", "strategy": "B",
             "sharpe": 2.0, "total_return": 0.2, "max_drawdown": -0.04,
             "trade_count": 8, "created_at": "2024-01-02"},
        ])
        args = argparse.Namespace(track_action="list", limit=10)
        repo = self._make_repo(df=df)
        with self._patch_db_path(), self._patch_repo(repo):
            buf = io.StringIO()
            with redirect_stdout(buf):
                track_quantlab_command(args)
        out = buf.getvalue()
        self.assertIn("Experiment 列表", out)
        self.assertIn("A", out)
        self.assertIn("B", out)

    def test_show_not_found(self):
        args = argparse.Namespace(track_action="show", id="nope")
        repo = self._make_repo(row=None)
        with self._patch_db_path(), self._patch_repo(repo):
            buf = io.StringIO()
            with redirect_stdout(buf):
                track_quantlab_command(args)
        self.assertIn("未找到", buf.getvalue())

    def test_leaderboard_empty(self):
        args = argparse.Namespace(track_action="leaderboard", sort_by="sharpe", top=5)
        repo = self._make_repo()
        with self._patch_db_path(), self._patch_repo(repo):
            buf = io.StringIO()
            with redirect_stdout(buf):
                track_quantlab_command(args)
        self.assertIn("暂无 experiment", buf.getvalue())

    def test_search_empty(self):
        args = argparse.Namespace(
            track_action="search", strategy=None, sharpe_min=None,
            max_dd_max=None, return_min=None, tag=None, limit=20,
        )
        repo = self._make_repo()
        with self._patch_db_path(), self._patch_repo(repo):
            buf = io.StringIO()
            with redirect_stdout(buf):
                track_quantlab_command(args)
        self.assertIn("无匹配", buf.getvalue())

    def test_delete_calls_repo(self):
        """delete 子动作调用 repo.delete(args.id) 并打印成功。"""
        args = argparse.Namespace(track_action="delete", id="e1")
        repo = self._make_repo()
        with self._patch_db_path(), self._patch_repo(repo):
            buf = io.StringIO()
            with redirect_stdout(buf):
                track_quantlab_command(args)
        repo.delete.assert_called_once_with("e1")
        self.assertIn("已删除", buf.getvalue())

    def test_rebuild_best_perf_populates_table(self):
        _seed_qrecord(self.db, "e1", "S1", sharpe=0.5)
        _seed_qrecord(self.db, "e2", "S2", sharpe=1.5)
        args = argparse.Namespace(track_action="rebuild-best-perf")
        with self._patch_db_path():
            buf = io.StringIO()
            with redirect_stdout(buf):
                track_quantlab_command(args)
        out = buf.getvalue()
        self.assertIn("rebuild-best-perf", out)
        self.assertIn("updated=2", out)

        # 验证 strategy_best_perf 表
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT strategy_id, best_experiment_id FROM strategy_best_perf"
            ).fetchall()
        ids = {r["strategy_id"]: r["best_experiment_id"] for r in rows}
        self.assertEqual(ids["S1"], "e1")
        self.assertEqual(ids["S2"], "e2")

    def test_view_marks_best(self):
        _seed_qrecord(self.db, "e1", "S1", sharpe=0.5)
        _seed_qrecord(self.db, "e2", "S1", sharpe=1.5)  # 同 strategy，e2 是 best
        from src.quantlab_adapters import rebuild_all_best_perf
        rebuild_all_best_perf(self.db_path)
        args = argparse.Namespace(
            track_action="view", strategy="S1", tag=None, limit=10,
        )
        with self._patch_db_path():
            buf = io.StringIO()
            with redirect_stdout(buf):
                track_quantlab_command(args)
        out = buf.getvalue()
        # e2 行应被标 ★
        self.assertIn("★", out)
        self.assertIn("S1", out)


if __name__ == '__main__':
    unittest.main()
