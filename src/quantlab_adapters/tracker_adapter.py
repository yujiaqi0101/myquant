"""
src/quantlab_adapters/tracker_adapter.py
======================================

MyquantTracker — 把 quantlab 实验写入 myquant aquant.db。

设计目标：
    - 复用 quantlab ExperimentTracker 的注册/run/search/leaderboard 全部 API
    - 入库走 myquant DatabaseManager（自动创建 4 张 quantlab_* 表）
    - 与 research.db 互通：可通过参数切换持久化层

用法：
    from src.quantlab_adapters import MyquantTracker
    from src.quantlab.research.tracker import ExperimentRecord

    tracker = MyquantTracker(
        strategy_registry={"MACross": MACrossStrategy},
        db_path="data/aquant.db",   # 用 myquant 的 aquant.db
    )
    record = ExperimentRecord(
        name="ma_test", strategy_name="MACross",
        params={"fast": 20, "slow": 60},
    )
    result = tracker.run(record=record, engine=engine, data=data)

验证：
    python -m pytest tests/test_tracker_adapter.py -v
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Optional, Type


class MyquantTracker:
    """
    把 quantlab 实验结果写入 myquant aquant.db 的 4 张 quantlab_* 表。

    与 quantlab 原生 ExperimentTracker 的关系：
        - API 子集：register_strategy / run / search / leaderboard
        - 不依赖 src/quantlab/research/database.py
        - 不依赖 src/quantlab/research/repository.py
        - 直接用 myquant DatabaseManager 操作 aquant.db
    """

    def __init__(
        self,
        strategy_registry: Optional[Dict[str, Type]] = None,
        db_path: str = "data/aquant.db",
    ):
        self.strategy_registry = dict(strategy_registry or {})
        self.db_path = db_path

    # ------------------------------------------------------------------
    # 策略注册
    # ------------------------------------------------------------------
    def register_strategy(self, name: str, cls: Type) -> None:
        self.strategy_registry[name] = cls

    # ------------------------------------------------------------------
    # 跑一次实验
    # ------------------------------------------------------------------
    def run(
        self,
        record: Any,             # ExperimentRecord
        engine: Any,
        data: Any,
    ) -> Dict[str, Any]:
        """
        跑一次回测并把结果写入 myquant aquant.db。

        Returns
        -------
        dict
            含 backtest_result 字段，与 ExperimentResultV2.metrics() 风格类似
        """
        # 1) 取 strategy cls
        cls = self.strategy_registry.get(record.strategy_name)
        if cls is None:
            raise KeyError(
                f"strategy not registered: {record.strategy_name}. "
                f"known: {list(self.strategy_registry)}"
            )

        # 2) 构造 strategy
        strategy = cls(**record.params)

        # 3) 跑回测
        # quantlab 框架 engine.run() 接受 strategy= 覆盖 self.strategy
        backtest_result = engine.run(
            strategy=strategy,
            data=data,
        )

        # 4) 抽 metrics
        metrics = self._extract_metrics(backtest_result)

        # 5) 入库 aquant.db
        self._save(record, metrics)

        return {
            "experiment": record,
            "backtest_result": backtest_result,
            "metrics": metrics,
        }

    # ------------------------------------------------------------------
    # 内部：抽 metrics
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_metrics(br: Any) -> Dict[str, Any]:
        """从 quantlab BacktestResult 抽核心指标。"""
        out: Dict[str, Any] = {}
        for attr in (
            "total_return",
            "sharpe",
            "max_drawdown",
            "trade_count",
            "win_rate",
            "final_equity",
            "source",
        ):
            if hasattr(br, attr):
                out[attr] = getattr(br, attr)
        return out

    # ------------------------------------------------------------------
    # 内部：写入 4 张 quantlab_* 表
    # ------------------------------------------------------------------
    def _save(self, record: Any, metrics: Dict[str, Any]) -> None:
        from src.data.database import DatabaseManager

        dbm = DatabaseManager(self.db_path)
        with dbm.get_connection() as conn:
            cur = conn.cursor()

            # 1) quantlab_experiments
            cur.execute(
                """
                INSERT OR REPLACE INTO quantlab_experiments
                (id, name, strategy, params_json, created_at, tag, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.name,
                    record.strategy_name,
                    json.dumps(
                        record.params, sort_keys=True,
                        ensure_ascii=False,
                    ),
                    record.created_at,
                    getattr(record, "tag", "") or "",
                    getattr(record, "note", "") or "",
                ),
            )

            # 2) quantlab_results
            cur.execute(
                """
                INSERT INTO quantlab_results
                (experiment_id, final_equity, total_return, sharpe,
                 max_drawdown, trade_count, win_rate, source, extras_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    float(metrics.get("final_equity", 0) or 0),
                    float(metrics.get("total_return", 0) or 0),
                    float(metrics.get("sharpe", 0) or 0),
                    float(metrics.get("max_drawdown", 0) or 0),
                    int(metrics.get("trade_count", 0) or 0),
                    float(metrics.get("win_rate", 0) or 0),
                    str(metrics.get("source", "") or ""),
                    json.dumps(metrics, ensure_ascii=False),
                ),
            )

    # ------------------------------------------------------------------
    # search 过滤
    # ------------------------------------------------------------------
    def search(
        self,
        strategy: Optional[str] = None,
        sharpe_min: Optional[float] = None,
        max_dd_max: Optional[float] = None,
        return_min: Optional[float] = None,
        tag: Optional[str] = None,
    ):
        """从 quantlab_results 联表查实验，支持 sharpe/dd/return/strategy/tag 过滤。"""
        from src.data.database import DatabaseManager
        import pandas as pd

        dbm = DatabaseManager(self.db_path)
        with dbm.get_connection() as conn:
            sql = """
                SELECT e.id, e.name, e.strategy, e.params_json,
                       e.created_at, e.tag, e.note,
                       r.final_equity, r.total_return, r.sharpe,
                       r.max_drawdown, r.trade_count, r.win_rate,
                       r.source
                FROM quantlab_experiments e
                JOIN quantlab_results r ON r.experiment_id = e.id
                WHERE 1=1
            """
            params: list = []
            if strategy:
                sql += " AND e.strategy = ?"
                params.append(strategy)
            if sharpe_min is not None:
                sql += " AND r.sharpe >= ?"
                params.append(float(sharpe_min))
            if max_dd_max is not None:
                # max_drawdown 为负数或正数表示回撤幅度
                sql += " AND r.max_drawdown >= ?"
                params.append(float(-abs(max_dd_max)))
            if return_min is not None:
                sql += " AND r.total_return >= ?"
                params.append(float(return_min))
            if tag:
                sql += " AND e.tag = ?"
                params.append(tag)
            sql += " ORDER BY r.sharpe DESC"
            rows = conn.execute(sql, params).fetchall()

            if not rows:
                return pd.DataFrame()

            return pd.DataFrame([dict(r) for r in rows])

    # ------------------------------------------------------------------
    # leaderboard
    # ------------------------------------------------------------------
    def leaderboard(
        self,
        sort_by: str = "sharpe",
        top: int = 10,
    ):
        """Top N 实验。"""
        from src.data.database import DatabaseManager
        import pandas as pd

        dbm = DatabaseManager(self.db_path)
        with dbm.get_connection() as conn:
            # 允许排序的列（防注入）
            sort_col = (
                "r.sharpe" if sort_by == "sharpe" else
                "r.total_return" if sort_by in ("total_return", "return") else
                "r.max_drawdown" if sort_by in ("max_drawdown", "max_dd") else
                "r.trade_count" if sort_by == "trade_count" else
                "r.sharpe"
            )
            order = "DESC"
            if sort_by in ("max_drawdown", "max_dd"):
                # max_dd 小的好，但负数越大代表回撤越大
                order = "ASC" if sort_by == "max_dd_asc" else "DESC"

            sql = f"""
                SELECT e.id, e.name, e.strategy, e.params_json,
                       e.created_at, e.tag,
                       r.final_equity, r.total_return, r.sharpe,
                       r.max_drawdown, r.trade_count, r.win_rate
                FROM quantlab_experiments e
                JOIN quantlab_results r ON r.experiment_id = e.id
                ORDER BY {sort_col} {order}
                LIMIT ?
            """
            rows = conn.execute(sql, (int(top),)).fetchall()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([dict(r) for r in rows])

    # ------------------------------------------------------------------
    # 列出所有
    # ------------------------------------------------------------------
    def list_all(self):
        """返回 aquant.db 中所有实验的 DataFrame。"""
        return self.search()
