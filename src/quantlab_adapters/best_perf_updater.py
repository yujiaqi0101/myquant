"""
strategy_best_perf 自动提炼模块
================================

实现 spec Task 11.6：
- 从 quantlab_results 中找出每个 strategy 的最佳实验
- 写入 strategy_best_perf 表
- main.py 启动时调用 ensure_best_perf_fresh() 触发补算
- CLI 端 `quantlab track --rebuild-best-perf` 手动重建

设计要点：
- best metric 默认按 sharpe 排序
- 同一 strategy 多个实验时取 sharpe 最高者
- best_experiment_id / best_source / best_value 等关键字段必填
- 过期（last_updated 早于 quantlab_results 中最近一次写入）→ 重建
- 缺失（strategy_best_perf 中无该 strategy_id）→ 补全
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


def _get_db(db_path: str):
    """统一获取 DatabaseManager 实例。"""
    from src.data.database import DatabaseManager
    return DatabaseManager(db_path)


def _list_strategies_with_results(db) -> List[str]:
    """
    列出 quantlab_results 中出现过的所有 strategy 名称。

    Returns
    -------
    list[str]
        策略名列表（去重，按字典序排序）
    """
    sql = """
        SELECT DISTINCT e.strategy
        FROM quantlab_experiments e
        JOIN quantlab_results r ON r.experiment_id = e.id
        ORDER BY e.strategy
    """
    with db.get_connection() as conn:
        rows = conn.execute(sql).fetchall()
    return [r["strategy"] for r in rows]


def _find_best_experiment(db, strategy_name: str) -> Optional[Dict[str, Any]]:
    """
    找某 strategy 的最佳实验（按 sharpe DESC）。

    Returns
    -------
    dict 或 None
        含 experiment_id / final_equity / total_return / sharpe /
        max_drawdown / source 等字段
    """
    sql = """
        SELECT e.id AS experiment_id, e.strategy,
               r.final_equity, r.total_return, r.sharpe,
               r.max_drawdown, r.trade_count, r.win_rate,
               r.source
        FROM quantlab_experiments e
        JOIN quantlab_results r ON r.experiment_id = e.id
        WHERE e.strategy = ?
        ORDER BY r.sharpe DESC, r.total_return DESC
        LIMIT 1
    """
    with db.get_connection() as conn:
        row = conn.execute(sql, (strategy_name,)).fetchone()
    if row is None:
        return None
    return dict(row)


def _ensure_strategy_info(db, strategy_id: str, strategy_name: str) -> None:
    """
    确保 strategy_info 行存在（best_perf 表 FK 引用）。

    best_perf.strategy_id REFERENCES strategy_info(strategy_id)。
    """
    sql = """
        INSERT OR IGNORE INTO strategy_info
            (strategy_id, strategy_name, description, applicable_scenario)
        VALUES (?, ?, ?, ?)
    """
    with db.get_connection() as conn:
        conn.execute(
            sql,
            (
                strategy_id,
                strategy_name,
                f"策略 {strategy_name}（由 best_perf_updater 自动创建）",
                "auto",
            ),
        )


def update_strategy_best_perf(
    db_path: str,
    strategy_id: str,
    strategy_name: Optional[str] = None,
) -> bool:
    """
    为单个 strategy 更新 best_perf 记录。

    Parameters
    ----------
    db_path : str
        数据库路径
    strategy_id : str
        策略唯一 ID（即 strategy_name，按项目约定用 strategy 字段当主键）
    strategy_name : str, optional
        显示名，默认与 strategy_id 相同

    Returns
    -------
    bool
        True 表示成功写入，False 表示该 strategy 暂无 result
    """
    name = strategy_name or strategy_id
    db = _get_db(db_path)
    best = _find_best_experiment(db, name)
    if best is None:
        logger.debug(f"策略 {name} 无 result，跳过")
        return False

    _ensure_strategy_info(db, strategy_id, name)

    sql = """
        INSERT INTO strategy_best_perf
            (strategy_id, best_experiment_id, best_source,
             best_metric, best_value,
             best_sharpe, best_max_drawdown, best_annual_return,
             last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(strategy_id) DO UPDATE SET
            best_experiment_id = excluded.best_experiment_id,
            best_source = excluded.best_source,
            best_metric = excluded.best_metric,
            best_value = excluded.best_value,
            best_sharpe = excluded.best_sharpe,
            best_max_drawdown = excluded.best_max_drawdown,
            best_annual_return = excluded.best_annual_return,
            last_updated = CURRENT_TIMESTAMP
    """
    with db.get_connection() as conn:
        conn.execute(
            sql,
            (
                strategy_id,
                best["experiment_id"],
                best.get("source") or "",
                "sharpe",
                float(best.get("sharpe") or 0),
                float(best.get("sharpe") or 0),
                float(best.get("max_drawdown") or 0),
                float(best.get("total_return") or 0),
            ),
        )
    logger.info(
        f"[best_perf] {name} -> experiment_id={best['experiment_id']} "
        f"sharpe={best.get('sharpe'):.4f}"
    )
    return True


def rebuild_all_best_perf(db_path: str) -> Dict[str, int]:
    """
    重建全部 strategy 的 best_perf。

    Returns
    -------
    dict
        {"updated": int, "skipped": int, "total": int}
    """
    db = _get_db(db_path)
    strategies = _list_strategies_with_results(db)
    stats = {"updated": 0, "skipped": 0, "total": len(strategies)}
    for s in strategies:
        if update_strategy_best_perf(db_path, strategy_id=s, strategy_name=s):
            stats["updated"] += 1
        else:
            stats["skipped"] += 1
    return stats


def list_missing_best_perf(db_path: str) -> List[str]:
    """
    列出 quantlab_results 中有结果但 strategy_best_perf 中无对应条目的 strategy。

    Returns
    -------
    list[str]
        缺失 best_perf 的 strategy 名称
    """
    db = _get_db(db_path)
    sql = """
        SELECT DISTINCT e.strategy
        FROM quantlab_experiments e
        JOIN quantlab_results r ON r.experiment_id = e.id
        LEFT JOIN strategy_best_perf b ON b.strategy_id = e.strategy
        WHERE b.strategy_id IS NULL
        ORDER BY e.strategy
    """
    with db.get_connection() as conn:
        rows = conn.execute(sql).fetchall()
    return [r["strategy"] for r in rows]


def ensure_best_perf_fresh(
    db_path: str,
    expire_after_seconds: int = 7 * 24 * 3600,
) -> Dict[str, Any]:
    """
    启动检查：补全缺失条目 + 重建过期条目。

    - 缺失：strategy 在 quantlab_results 中有结果但 strategy_best_perf 无对应行
    - 过期：strategy_best_perf.last_updated 早于 expire_after_seconds 秒前

    Parameters
    ----------
    db_path : str
    expire_after_seconds : int
        过期阈值（默认 7 天）

    Returns
    -------
    dict
        {"missing_fixed": int, "stale_rebuilt": int, "skipped": int}
    """
    db = _get_db(db_path)
    stats = {"missing_fixed": 0, "stale_rebuilt": 0, "skipped": 0}

    # 1) 缺失条目
    for s in list_missing_best_perf(db_path):
        if update_strategy_best_perf(db_path, strategy_id=s, strategy_name=s):
            stats["missing_fixed"] += 1
        else:
            stats["skipped"] += 1

    # 2) 过期条目（last_updated 距今超过阈值）
    sql = f"""
        SELECT b.strategy_id
        FROM strategy_best_perf b
        WHERE (julianday('now') - julianday(b.last_updated)) * 86400 > ?
    """
    with db.get_connection() as conn:
        stale_rows = conn.execute(sql, (float(expire_after_seconds),)).fetchall()
    for r in stale_rows:
        sid = r["strategy_id"]
        if update_strategy_best_perf(db_path, strategy_id=sid, strategy_name=sid):
            stats["stale_rebuilt"] += 1
        else:
            stats["skipped"] += 1

    if stats["missing_fixed"] or stats["stale_rebuilt"]:
        logger.info(
            f"[ensure_best_perf_fresh] "
            f"missing_fixed={stats['missing_fixed']} "
            f"stale_rebuilt={stats['stale_rebuilt']} "
            f"skipped={stats['skipped']}"
        )
    return stats


__all__ = [
    "update_strategy_best_perf",
    "rebuild_all_best_perf",
    "list_missing_best_perf",
    "ensure_best_perf_fresh",
]
