"""
策略最佳表现自动提炼
====================

从 quantlab_experiments + quantlab_results 中按 Sharpe 筛选最佳实验，
写入 strategy_best_perf 表。

支持：
- update_strategy_best_perf(strategy_id) — 单策略更新
- rebuild_all_best_perf() — 全表重建
- list_missing_best_perf() — 找出缺失条目
- ensure_best_perf_fresh() — 启动检查（补缺失 + 重建过期）
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class BestPerfUpdater:
    """
    策略最佳表现自动提炼器

    从 quantlab_experiments 和 quantlab_results 中筛选 Sharpe 最高的实验，
    自动写入 strategy_best_perf 表。
    """

    def __init__(self, db_manager):
        """
        Parameters
        ----------
        db_manager : DatabaseManager
            数据库管理器实例
        """
        self.db = db_manager

    def update_strategy_best_perf(self, strategy_id: str, version: str = 'latest') -> Optional[Dict]:
        """
        更新单个策略的最佳表现

        从 quantlab_experiments + quantlab_results 中找 Sharpe 最高的实验，
        写入 strategy_best_perf 表。

        Parameters
        ----------
        strategy_id : str
            策略ID
        version : str
            版本标签，默认 'latest'

        Returns
        -------
        dict or None
            最佳表现记录，如果无实验数据则返回 None
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # 查找该策略的所有实验
            cursor.execute('''
                SELECT e.id, e.strategy_name, e.created_at,
                       r.sharpe_ratio, r.total_return, r.max_drawdown
                FROM quantlab_experiments e
                LEFT JOIN quantlab_results r ON e.id = r.experiment_id
                WHERE e.strategy_name = ? AND r.sharpe_ratio IS NOT NULL
                ORDER BY r.sharpe_ratio DESC
                LIMIT 1
            ''', (strategy_id,))

            row = cursor.fetchone()
            if not row:
                logger.debug(f"策略 '{strategy_id}' 无实验数据")
                return None

            best = {
                'strategy_id': strategy_id,
                'version': version,
                'best_sharpe': row[3],
                'best_return': row[4],
                'best_max_dd': row[5],
                'best_experiment_id': str(row[0]),
                'best_source': 'quantlab',
                'last_updated': datetime.now().isoformat(),
            }

            # 写入 strategy_best_perf（INSERT OR REPLACE）
            cursor.execute('''
                INSERT OR REPLACE INTO strategy_best_perf
                (strategy_id, version, best_sharpe, best_return, best_max_dd,
                 best_experiment_id, best_source, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                best['strategy_id'], best['version'],
                best['best_sharpe'], best['best_return'], best['best_max_dd'],
                best['best_experiment_id'], best['best_source'], best['last_updated'],
            ))

            logger.info(f"策略 '{strategy_id}' 最佳表现已更新: Sharpe={best['best_sharpe']:.4f}")
            return best

    def rebuild_all_best_perf(self, version: str = 'latest') -> int:
        """
        全表重建：遍历所有有实验的策略，更新最佳表现

        Returns
        -------
        int
            更新的策略数量
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT strategy_name FROM quantlab_experiments')
            strategy_names = [row[0] for row in cursor.fetchall()]

        count = 0
        for strategy_id in strategy_names:
            result = self.update_strategy_best_perf(strategy_id, version)
            if result:
                count += 1

        logger.info(f"全表重建完成: 更新了 {count} 个策略的最佳表现")
        return count

    def list_missing_best_perf(self) -> List[str]:
        """
        找出 strategy_best_perf 表中缺失的策略

        Returns
        -------
        list of str
            缺失的策略ID列表
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT e.strategy_name
                FROM quantlab_experiments e
                LEFT JOIN strategy_best_perf bp ON e.strategy_name = bp.strategy_id
                WHERE bp.strategy_id IS NULL
            ''')
            missing = [row[0] for row in cursor.fetchall()]

        return missing

    def list_stale_best_perf(self, expire_after_seconds: int = 7 * 24 * 3600) -> List[str]:
        """
        找出过期的最佳表现记录

        Parameters
        ----------
        expire_after_seconds : int
            过期时间（秒），默认7天

        Returns
        -------
        list of str
            过期的策略ID列表
        """
        cutoff = (datetime.now() - timedelta(seconds=expire_after_seconds)).isoformat()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT strategy_id FROM strategy_best_perf
                WHERE last_updated < ?
            ''', (cutoff,))
            stale = [row[0] for row in cursor.fetchall()]

        return stale


def ensure_best_perf_fresh(db_manager, expire_after_seconds: int = 7 * 24 * 3600) -> Dict:
    """
    启动检查：补全缺失条目 + 重建过期条目

    Parameters
    ----------
    db_manager : DatabaseManager
        数据库管理器实例
    expire_after_seconds : int
        过期时间（秒），默认7天

    Returns
    -------
    dict
        检查结果，包含 missing_count, stale_count, updated_count
    """
    updater = BestPerfUpdater(db_manager)

    # 1. 补全缺失
    missing = updater.list_missing_best_perf()
    missing_count = len(missing)

    # 2. 重建过期
    stale = updater.list_stale_best_perf(expire_after_seconds)
    stale_count = len(stale)

    # 3. 执行更新
    updated_count = 0
    all_to_update = set(missing + stale)
    for strategy_id in all_to_update:
        result = updater.update_strategy_best_perf(strategy_id)
        if result:
            updated_count += 1

    result = {
        'missing_count': missing_count,
        'stale_count': stale_count,
        'updated_count': updated_count,
    }

    if updated_count > 0:
        logger.info(f"策略最佳表现检查: 补全 {missing_count} 个缺失, 重建 {stale_count} 个过期, 共更新 {updated_count} 个")
    else:
        logger.info("策略最佳表现检查: 所有记录均为最新")

    return result
