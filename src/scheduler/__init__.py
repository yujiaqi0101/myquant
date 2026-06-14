"""
任务调度器
=========

基于 APScheduler BackgroundScheduler 实现轻量级任务调度。
飞书"## 任务管理"章节要求："实现任务队列，任务定时执行，失败任务重试"。

设计：
- TaskScheduler：APScheduler BackgroundScheduler 包装
- 失败重试：指数退避 2^n 秒
- 执行日志：写入 data_sync_log 表
- 可扩展：通过 TASK_REGISTRY 注册新任务
"""
import logging
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    BackgroundScheduler = None
    CronTrigger = None

from src.tasks import get_task, list_tasks as _list_tasks, TASK_REGISTRY  # noqa: F401

logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    任务调度器（飞书"## 任务管理"实现）

    用法：
        scheduler = TaskScheduler(db_path)
        scheduler.add_task('daily_sync', '0 17 * * 1-5', 'sync')
        scheduler.start()
    """

    def __init__(self, db_path: str):
        if not HAS_APSCHEDULER:
            raise ImportError(
                "APScheduler 未安装，请运行: pip install apscheduler"
            )
        self.db_path = db_path
        self.scheduler = BackgroundScheduler()
        self._task_meta: Dict[str, Dict] = {}  # name -> {cron, action, retry, ...}

    def add_task(
        self,
        name: str,
        cron: str,
        action: str,
        retry: int = 3,
        **kwargs,
    ) -> None:
        """
        添加一个定时任务

        Parameters
        ----------
        name : str
            任务名（唯一）
        cron : str
            标准 cron 表达式（5 段：分 时 日 月 周）
            例：'0 17 * * 1-5' 表示每个交易日 17:00
        action : str
            任务动作（必须在 TASK_REGISTRY 中）
        retry : int
            失败重试次数（指数退避 2^n 秒）
        **kwargs
            传给任务函数的额外参数
        """
        # 解析 cron
        cron_parts = cron.split()
        if len(cron_parts) != 5:
            raise ValueError(f"cron 表达式必须 5 段：{cron}")

        minute, hour, day, month, day_of_week = cron_parts
        trigger = CronTrigger(
            minute=minute, hour=hour, day=day,
            month=month, day_of_week=day_of_week,
        )

        self.scheduler.add_job(
            func=self._run_with_retry,
            trigger=trigger,
            args=(action, retry, kwargs),
            id=name,
            replace_existing=True,
            name=name,
        )
        self._task_meta[name] = {
            'cron': cron,
            'action': action,
            'retry': retry,
            'kwargs': kwargs,
        }
        logger.info(f"已添加任务: {name} (cron='{cron}', action='{action}', retry={retry})")

    def remove_task(self, name: str) -> bool:
        """移除一个任务"""
        try:
            self.scheduler.remove_job(name)
            self._task_meta.pop(name, None)
            logger.info(f"已移除任务: {name}")
            return True
        except Exception as e:
            logger.warning(f"移除任务 {name} 失败: {e}")
            return False

    def list_tasks(self) -> List[Dict]:
        """列出所有已添加任务"""
        result = []
        for job in self.scheduler.get_jobs():
            name = job.id
            meta = self._task_meta.get(name, {})
            result.append({
                'name': name,
                'cron': meta.get('cron', ''),
                'action': meta.get('action', ''),
                'retry': meta.get('retry', 3),
                'next_run': str(job.next_run_time) if job.next_run_time else None,
            })
        return result

    def run_now(self, name: str) -> Dict:
        """立即运行一个任务（手动触发）"""
        if name not in self._task_meta:
            return {'status': 'failed', 'error': f'任务 {name} 不存在'}
        meta = self._task_meta[name]
        return self._run_with_retry(meta['action'], meta['retry'], meta['kwargs'])

    def start(self) -> None:
        """启动调度器"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info(f"任务调度器已启动，共 {len(self._task_meta)} 个任务")

    def stop(self) -> None:
        """停止调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("任务调度器已停止")

    # ============ 私有方法 ============

    def _run_with_retry(self, action: str, retry: int, kwargs: dict) -> Dict:
        """
        执行任务，失败按指数退避重试

        每次执行都记录到 data_sync_log 表
        """
        from src.data.database import DatabaseManager
        db = DatabaseManager(self.db_path)
        log_id = self._log_start(db, action, kwargs)

        for attempt in range(1, retry + 1):
            try:
                task_func = get_task(action)
                logger.info(f"[Task {action}] 开始执行 (尝试 {attempt}/{retry})")
                result = task_func(self.db_path, **kwargs)
                self._log_finish(db, log_id, 'success', result)
                logger.info(f"[Task {action}] 执行成功")
                return result
            except Exception as e:
                logger.warning(f"[Task {action}] 失败 (尝试 {attempt}/{retry}): {e}")
                if attempt < retry:
                    sleep_seconds = 2 ** (attempt - 1)  # 1, 2, 4 秒
                    time.sleep(sleep_seconds)

        error_msg = f"任务 {action} 失败，已重试 {retry} 次"
        self._log_finish(db, log_id, 'failed', {'error': error_msg})
        logger.error(error_msg)
        return {'status': 'failed', 'error': error_msg}

    def _log_start(self, db, action: str, kwargs: dict) -> int:
        """记录任务开始"""
        try:
            with db.get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO data_sync_log
                    (sync_type, start_time, status, details)
                    VALUES (?, ?, ?, ?)
                    """,
                    (f'task:{action}', datetime.now().isoformat(), 'pending',
                     json.dumps(kwargs, ensure_ascii=False))
                )
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.warning(f"记录任务开始失败: {e}")
            return -1

    def _log_finish(self, db, log_id: int, status: str, result: dict) -> None:
        """记录任务结束"""
        if log_id < 0:
            return
        try:
            record_count = 0
            if isinstance(result, dict):
                record_count = result.get('count', 0)
                inner = result.get('result', {})
                if isinstance(inner, dict):
                    record_count = inner.get('count', record_count)
            with db.get_connection() as conn:
                conn.execute(
                    """
                    UPDATE data_sync_log
                    SET end_time = ?, record_count = ?, status = ?
                    WHERE id = ?
                    """,
                    (datetime.now().isoformat(), record_count, status, log_id)
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"记录任务结束失败: {e}")


__all__ = ['TaskScheduler', 'HAS_APSCHEDULER']
