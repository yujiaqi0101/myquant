"""
V2.3 Experiment Tracking — Repository

实验仓库（CRUD）：
  - save(experiment_result)     插入 / 更新
  - get(experiment_id)          按 id 查
  - delete(experiment_id)       按 id 删
  - list_all()                  全部
  - search(strategy, ...)       条件查询
  - leaderboard(sort_by, top)   Top N

数据流：
  ExperimentResultV2
        |
        v
  Repository.save(...)
        |
        |---> experiments 表（insert / upsert）
        |---> results 表（insert）
        '---> walkforward 表（insert, 如果有）
"""


import json
import sqlite3
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import pandas as pd


class ExperimentRepository:

    def __init__(self, db: Any):

        self.db = db

    # ----------------------------------------------------------------
    # 写：save / delete
    # ----------------------------------------------------------------

    def save(
        self,
        result: Any,
    ) -> str:

        # 存一次实验
        #
        # 入三张表：
        #   1) experiments   元数据
        #   2) results       核心指标
        #   3) walkforward   WF 指标（如果有）
        #
        # 返回 experiment.id

        if hasattr(result, "experiment"):
            # ExperimentResultV2
            record = result.experiment
            br = result.backtest_result
            wf = result.walkforward_result
        else:
            # 直接传 ExperimentRecord
            record = result
            br = None
            wf = None

        with self.db.get_connection() as conn:

            # ---- 1) experiments ----
            conn.execute(
                """
                INSERT OR REPLACE INTO experiments
                (id, name, strategy, params_json,
                 created_at, tag, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.name,
                    record.strategy_name,
                    record.params_json(),
                    record.created_at,
                    record.tag,
                    record.note,
                ),
            )

            # ---- 2) results ----
            if br is not None:

                metrics = (
                    self._extract_metrics(
                        br
                    )
                )
                conn.execute(
                    """
                    INSERT INTO results
                    (experiment_id, final_equity,
                     total_return, sharpe,
                     max_drawdown, trade_count,
                     win_rate, source,
                     extras_json)
                    VALUES (?, ?, ?, ?, ?,
                            ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        metrics.get(
                            "final_equity", 0
                        ),
                        metrics.get(
                            "total_return", 0
                        ),
                        metrics.get(
                            "sharpe", 0
                        ),
                        metrics.get(
                            "max_drawdown", 0
                        ),
                        metrics.get(
                            "trade_count", 0
                        ),
                        metrics.get(
                            "win_rate", 0
                        ),
                        metrics.get(
                            "source", "event"
                        ),
                        json.dumps(
                            metrics.get(
                                "extras", {}
                            ),
                            ensure_ascii=False,
                        ),
                    ),
                )

            # ---- 3) walkforward ----
            if wf is not None:

                wf_row = (
                    self._extract_wf(wf)
                )
                conn.execute(
                    """
                    INSERT INTO walkforward
                    (experiment_id, n_windows,
                     avg_sharpe, avg_return,
                     avg_max_dd, stitched_sharpe,
                     stitched_return,
                     stitched_max_dd,
                     stability_score,
                     parameter_drift,
                     extras_json)
                    VALUES (?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        wf_row.get(
                            "n_windows", 0
                        ),
                        wf_row.get(
                            "avg_sharpe", 0
                        ),
                        wf_row.get(
                            "avg_return", 0
                        ),
                        wf_row.get(
                            "avg_max_dd", 0
                        ),
                        wf_row.get(
                            "stitched_sharpe", 0
                        ),
                        wf_row.get(
                            "stitched_return", 0
                        ),
                        wf_row.get(
                            "stitched_max_dd", 0
                        ),
                        wf_row.get(
                            "stability_score", 0
                        ),
                        wf_row.get(
                            "parameter_drift", 0
                        ),
                        json.dumps(
                            wf_row.get(
                                "extras", {}
                            ),
                            ensure_ascii=False,
                        ),
                    ),
                )

        return record.id

    def delete(
        self,
        experiment_id: str,
    ):

        # 删实验
        # ON DELETE CASCADE 自动清 results / walkforward / equity_curves
        with self.db.get_connection() as conn:

            conn.execute(
                """
                DELETE FROM experiments
                WHERE id = ?
                """,
                (experiment_id,),
            )

    def save_equity_curve(
        self,
        experiment_id: str,
        equity_curve,
        timestamps=None,
    ) -> int:
        """
        Phase 6 新增：保存逐 bar 权益曲线。

        Parameters
        ----------
        experiment_id : str
            实验 id
        equity_curve : array-like
            权益序列（每根 bar 一个值）
        timestamps : array-like, optional
            对应时间戳；为空则用 bar_idx 0,1,2,...

        Returns
        -------
        int
            写入的行数
        """
        import math as _math
        from datetime import datetime as _dt

        n = len(equity_curve)
        if n == 0:
            return 0

        # 计算 drawdown
        peak = equity_curve[0]
        equities = []
        drawdowns = []
        daily_returns = []
        prev = equity_curve[0]
        for i, eq in enumerate(equity_curve):
            if eq > peak:
                peak = eq
            dd = (eq - peak) / peak if peak > 0 else 0.0
            equities.append(eq)
            drawdowns.append(dd)
            if prev > 0 and i > 0:
                daily_returns.append((eq - prev) / prev)
            else:
                daily_returns.append(0.0)
            prev = eq

        # 时间戳
        ts_list = []
        if timestamps is None or len(timestamps) != n:
            for i in range(n):
                ts_list.append(str(i))
        else:
            for ts in timestamps:
                if hasattr(ts, "isoformat"):
                    ts_list.append(ts.isoformat())
                else:
                    ts_list.append(str(ts))

        rows = []
        for i in range(n):
            eq_v = equities[i]
            if eq_v is None or (isinstance(eq_v, float) and _math.isnan(eq_v)):
                eq_v = 0.0
            dd_v = drawdowns[i]
            if dd_v is None or (isinstance(dd_v, float) and _math.isnan(dd_v)):
                dd_v = 0.0
            dr_v = daily_returns[i]
            if dr_v is None or (isinstance(dr_v, float) and _math.isnan(dr_v)):
                dr_v = 0.0
            rows.append((
                experiment_id,
                i,
                ts_list[i],
                float(eq_v),
                float(dd_v),
                float(dr_v),
            ))

        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM equity_curves WHERE experiment_id = ?",
                         (experiment_id,))
            conn.executemany(
                """
                INSERT INTO equity_curves
                (experiment_id, bar_idx, timestamp,
                 equity, drawdown, daily_return)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        return n

    def get_equity_curve(
        self,
        experiment_id: str,
    ) -> "pd.DataFrame":
        """
        Phase 6 新增：读取逐 bar 权益曲线。

        Returns
        -------
        pd.DataFrame
            columns=[bar_idx, timestamp, equity, drawdown, daily_return]
            按 bar_idx 升序
        """
        with self.db.get_connection() as conn:
            df = pd.read_sql_query(
                """
                SELECT bar_idx, timestamp, equity,
                       drawdown, daily_return
                FROM equity_curves
                WHERE experiment_id = ?
                ORDER BY bar_idx ASC
                """,
                conn,
                params=(experiment_id,),
            )
        return df

    # ----------------------------------------------------------------
    # 读：get / list_all
    # ----------------------------------------------------------------

    def get(
        self,
        experiment_id: str,
    ) -> Optional[Dict]:

        with self.db.get_connection() as conn:

            row = conn.execute(
                """
                SELECT
                    e.id, e.name, e.strategy,
                    e.params_json, e.created_at,
                    e.tag, e.note,
                    r.final_equity, r.total_return,
                    r.sharpe, r.max_drawdown,
                    r.trade_count, r.win_rate,
                    r.source, r.extras_json
                FROM experiments e
                LEFT JOIN results r
                    ON e.id = r.experiment_id
                WHERE e.id = ?
                """,
                (experiment_id,),
            ).fetchone()

        if row is None:
            return None

        d = dict(row)
        # params_json -> dict
        try:
            d["params"] = json.loads(
                d.pop("params_json", "{}")
            )
        except Exception:
            d["params"] = {}
        try:
            d["extras"] = json.loads(
                d.pop("extras_json", "{}")
            )
        except Exception:
            d["extras"] = {}
        return d

    def list_all(
        self, limit: int = 1000
    ) -> pd.DataFrame:

        # 全部实验
        with self.db.get_connection() as conn:

            df = pd.read_sql_query(
                """
                SELECT
                    e.id, e.name, e.strategy,
                    e.params_json, e.created_at,
                    e.tag, e.note,
                    r.final_equity, r.total_return,
                    r.sharpe, r.max_drawdown,
                    r.trade_count, r.win_rate,
                    r.source
                FROM experiments e
                LEFT JOIN results r
                    ON e.id = r.experiment_id
                ORDER BY e.created_at DESC
                LIMIT ?
                """,
                conn,
                params=(limit,),
            )

        if "params_json" in df.columns:
            df["params"] = df["params_json"].apply(
                lambda x: self._safe_json(
                    x
                )
            )
            df = df.drop(
                columns=["params_json"]
            )

        return df

    # ----------------------------------------------------------------
    # Search
    # ----------------------------------------------------------------

    def search(
        self,
        strategy: Optional[str] = None,
        sharpe_min: Optional[
            float
        ] = None,
        max_dd_max: Optional[
            float
        ] = None,
        return_min: Optional[
            float
        ] = None,
        tag: Optional[str] = None,
        limit: int = 100,
    ) -> pd.DataFrame:

        # 条件查询
        #
        # sharpe_min     sharpe >= X
        # max_dd_max     |max_dd| <= X
        #               （用户传正数）
        # return_min     total_return >= X
        # tag            按 tag 过滤

        where = []
        params: List = []

        if strategy is not None:
            where.append(
                "e.strategy = ?"
            )
            params.append(strategy)
        if tag is not None:
            where.append("e.tag = ?")
            params.append(tag)
        if sharpe_min is not None:
            where.append(
                "r.sharpe >= ?"
            )
            params.append(sharpe_min)
        if max_dd_max is not None:
            # max_dd 是负数（或 0）
            # max_dd_max 是正数（用户语义 = 最大可接受回撤）
            # 例：用户传 0.05 = 允许最大 5% 回撤
            #     max_drawdown >= -0.05
            where.append(
                "r.max_drawdown >= ?"
            )
            params.append(-max_dd_max)
        if return_min is not None:
            where.append(
                "r.total_return >= ?"
            )
            params.append(return_min)

        sql = """
            SELECT
                e.id, e.name, e.strategy,
                e.params_json, e.created_at,
                e.tag, e.note,
                r.final_equity, r.total_return,
                r.sharpe, r.max_drawdown,
                r.trade_count, r.win_rate,
                r.source
            FROM experiments e
            LEFT JOIN results r
                ON e.id = r.experiment_id
        """
        if where:
            sql += " WHERE " + " AND ".join(
                where
            )
        sql += (
            " ORDER BY r.sharpe DESC "
            "LIMIT ?"
        )
        params.append(limit)

        with self.db.get_connection() as conn:

            df = pd.read_sql_query(
                sql, conn, params=tuple(
                    params
                )
            )

        if not df.empty and (
            "params_json" in df.columns
        ):
            df["params"] = df[
                "params_json"
            ].apply(
                lambda x: self._safe_json(
                    x
                )
            )
            df = df.drop(
                columns=["params_json"]
            )

        return df

    # ----------------------------------------------------------------
    # Leaderboard
    # ----------------------------------------------------------------

    def leaderboard(
        self,
        sort_by: str = "sharpe",
        top: int = 20,
    ) -> pd.DataFrame:

        # Top N 策略榜
        #
        # sort_by:
        #   "sharpe"        降序
        #   "return"        降序
        #   "stability"     降序（按 wf.stability_score）
        #   "max_drawdown"  升序（小的好）

        asc = False
        col_sql = "r.sharpe"

        if sort_by == "sharpe":
            asc = False
            col_sql = "r.sharpe"
        elif sort_by == "return":
            asc = False
            col_sql = "r.total_return"
        elif sort_by == "max_drawdown":
            # MaxDD 是负数
            # 数值越大（越接近 0）= 跌幅越小 = 越好
            # 所以降序排
            asc = False
            col_sql = "r.max_drawdown"
        elif sort_by == "stability":
            asc = False
            col_sql = (
                "wf.stability_score"
            )
        else:
            asc = False
            col_sql = "r.sharpe"

        # 拼 SQL
        if sort_by == "stability":
            sql = """
                SELECT
                    e.id, e.name, e.strategy,
                    e.params_json, e.created_at,
                    r.sharpe, r.total_return,
                    r.max_drawdown,
                    r.trade_count,
                    wf.n_windows,
                    wf.stability_score,
                    wf.parameter_drift,
                    wf.avg_return,
                    wf.avg_sharpe
                FROM experiments e
                LEFT JOIN results r
                    ON e.id = r.experiment_id
                LEFT JOIN walkforward wf
                    ON e.id = wf.experiment_id
                WHERE wf.stability_score IS NOT NULL
                ORDER BY wf.stability_score DESC
                LIMIT ?
            """
        else:
            sql = f"""
                SELECT
                    e.id, e.name, e.strategy,
                    e.params_json, e.created_at,
                    r.sharpe, r.total_return,
                    r.max_drawdown,
                    r.trade_count,
                    wf.stability_score,
                    wf.parameter_drift
                FROM experiments e
                LEFT JOIN results r
                    ON e.id = r.experiment_id
                LEFT JOIN walkforward wf
                    ON e.id = wf.experiment_id
                WHERE r.sharpe IS NOT NULL
                ORDER BY {col_sql} {'ASC' if asc else 'DESC'}
                LIMIT ?
            """

        with self.db.get_connection() as conn:

            df = pd.read_sql_query(
                sql, conn, params=(top,)
            )

        if not df.empty and (
            "params_json" in df.columns
        ):
            df["params"] = df[
                "params_json"
            ].apply(
                lambda x: self._safe_json(
                    x
                )
            )
            df = df.drop(
                columns=["params_json"]
            )

        return df

    # ----------------------------------------------------------------
    # 工具
    # ----------------------------------------------------------------

    @staticmethod
    def _extract_metrics(
        br: Any,
    ) -> Dict:

        # 从 BacktestResult / ExperimentResult 抽指标
        out = {}

        for attr in (
            "final_equity",
            "total_return",
            "sharpe",
            "max_drawdown",
            "trade_count",
            "win_rate",
            "source",
        ):

            if hasattr(br, attr):
                out[attr] = getattr(
                    br, attr
                )

        # ExperimentResult 兼容
        if hasattr(br, "metrics"):
            try:
                m = br.metrics
                if isinstance(m, dict):
                    for k, v in m.items():
                        if k not in out:
                            out[k] = v
            except Exception:
                pass

        return out

    @staticmethod
    def _extract_wf(
        wf: Any,
    ) -> Dict:

        # 从 WalkForwardResultV2 抽指标
        out = {}

        for attr in (
            "n_windows",
            "avg_sharpe",
            "avg_return",
            "avg_max_dd",
            "stability_score",
            "parameter_drift",
        ):

            # 直接属性
            if hasattr(wf, attr):
                out[attr] = getattr(
                    wf, attr
                )

        # stitched_metrics 兼容
        if hasattr(
            wf, "stitched_metrics"
        ) and isinstance(
            wf.stitched_metrics, dict
        ):
            sm = wf.stitched_metrics
            if (
                "sharpe"
                not in out
            ):
                out["stitched_sharpe"] = (
                    sm.get("sharpe", 0)
                )
            if (
                "total_return"
                not in out
            ):
                out["stitched_return"] = (
                    sm.get(
                        "total_return", 0
                    )
                )
            if (
                "max_drawdown"
                not in out
            ):
                out["stitched_max_dd"] = (
                    sm.get(
                        "max_drawdown", 0
                    )
                )

        return out

    @staticmethod
    def _safe_json(s: str) -> Dict:

        try:
            return json.loads(s or "{}")
        except Exception:
            return {}
