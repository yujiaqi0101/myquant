"""
V2.3 Experiment Tracking — Database

研究数据库（SQLite）
目录：storage/research.db

四张表：
  - experiments
      实验元数据
      （id, name, strategy, params, created_at）
  - results
      回测核心指标
      （experiment_id, return, sharpe, max_dd, trade_count）
  - walkforward
      Walk-Forward 指标
      （experiment_id, stability_score, wf_return, wf_sharpe）
  - equity_curves    (Phase 6 新增)
      逐 bar 权益曲线（用于事后画图 / Stitching / 复盘）
      （experiment_id, bar_idx, timestamp, equity, drawdown）

为什么用 SQLite：
  - 零部署
  - 几年内单文件就够
  - 不需要 DBA

不要一开始就上 PostgreSQL
"""


import os
import sqlite3
from pathlib import Path
from typing import Optional


# 默认 DB 路径
# 项目根 / storage / research.db
def default_db_path() -> str:

    # 仓库根目录
    # 从 quantlab/research/database.py 向上两级
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    storage = repo_root / "storage"
    storage.mkdir(
        parents=True, exist_ok=True
    )
    return str(
        storage / "research.db"
    )


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS experiments (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    params_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    tag          TEXT DEFAULT '',
    note         TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_experiments_strategy
    ON experiments(strategy);
CREATE INDEX IF NOT EXISTS idx_experiments_created
    ON experiments(created_at);

CREATE TABLE IF NOT EXISTS results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    final_equity  REAL DEFAULT 0,
    total_return  REAL DEFAULT 0,
    sharpe        REAL DEFAULT 0,
    max_drawdown  REAL DEFAULT 0,
    trade_count   INTEGER DEFAULT 0,
    win_rate      REAL DEFAULT 0,
    source        TEXT DEFAULT 'event',
    extras_json   TEXT DEFAULT '{}',
    FOREIGN KEY (experiment_id)
        REFERENCES experiments(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_results_exp
    ON results(experiment_id);
CREATE INDEX IF NOT EXISTS idx_results_sharpe
    ON results(sharpe);
CREATE INDEX IF NOT EXISTS idx_results_return
    ON results(total_return);

CREATE TABLE IF NOT EXISTS walkforward (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   TEXT NOT NULL,
    n_windows       INTEGER DEFAULT 0,
    avg_sharpe      REAL DEFAULT 0,
    avg_return      REAL DEFAULT 0,
    avg_max_dd      REAL DEFAULT 0,
    stitched_sharpe REAL DEFAULT 0,
    stitched_return REAL DEFAULT 0,
    stitched_max_dd REAL DEFAULT 0,
    stability_score REAL DEFAULT 0,
    parameter_drift REAL DEFAULT 0,
    extras_json     TEXT DEFAULT '{}',
    FOREIGN KEY (experiment_id)
        REFERENCES experiments(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_wf_exp
    ON walkforward(experiment_id);
CREATE INDEX IF NOT EXISTS idx_wf_stability
    ON walkforward(stability_score);

-- ============================================================
-- Phase 6 新增：equity_curves 表
-- 存每个实验的逐 bar 权益曲线
-- 方便事后：
--   1) plot 曲线（不必重跑回测）
--   2) 跨实验对比 equity
--   3) Stitched OOS 拼接
-- ============================================================
CREATE TABLE IF NOT EXISTS equity_curves (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    bar_idx       INTEGER NOT NULL,
    timestamp     TEXT NOT NULL,
    equity        REAL DEFAULT 0,
    drawdown      REAL DEFAULT 0,
    daily_return  REAL DEFAULT 0,
    FOREIGN KEY (experiment_id)
        REFERENCES experiments(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_equity_exp
    ON equity_curves(experiment_id);
CREATE INDEX IF NOT EXISTS idx_equity_bar
    ON equity_curves(experiment_id, bar_idx);
"""


class Database:

    # SQLite 连接 + Schema 初始化
    #
    # 线程安全：
    #   SQLite 默认是串行
    #   每次 query 走新 connection
    #   （避免多线程共享 connection 的坑）
    #
    # check_same_thread=False
    #   允许跨线程使用
    #   （pandas / multiprocessing 安全）

    def __init__(
        self,
        db_path: Optional[str] = None,
    ):

        self.db_path = (
            db_path or default_db_path()
        )

        # 确保父目录存在
        # 显式传 db_path 时
        # 不会走 default_db_path()
        # 所以这里单独 mkdir
        Path(self.db_path).parent.mkdir(
            parents=True, exist_ok=True
        )

        # 初始化 schema
        # 启动时建表
        self._init_schema()

    def _init_schema(self):

        with self._connect() as conn:

            conn.executescript(
                SCHEMA_SQL
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:

        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,
        )

        # 启用外键
        # SQLite 默认关
        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        # Row factory
        # 让结果按列名访问
        conn.row_factory = (
            sqlite3.Row
        )

        return conn

    def get_connection(self):

        # 给 Repository 用
        return self._connect()

    def reset(self):

        # 删表重灌
        # 测试用
        with self._connect() as conn:

            conn.executescript("""
                DROP TABLE IF EXISTS equity_curves;
                DROP TABLE IF EXISTS walkforward;
                DROP TABLE IF EXISTS results;
                DROP TABLE IF EXISTS experiments;
            """)
            conn.commit()

        self._init_schema()
