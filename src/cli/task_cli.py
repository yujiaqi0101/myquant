"""
任务管理 CLI
==========

飞书"## 任务管理"要求的 CLI 接口：
- add    添加定时任务
- remove 删除任务
- list   列出所有任务
- run    立即运行
- log    查看执行日志
- daemon 启停调度器
"""
import argparse
import logging
import json
import sys
from pathlib import Path
from typing import Optional

from ..tasks import list_tasks as list_registered_tasks, get_task as _get_task
from ..scheduler import TaskScheduler, HAS_APSCHEDULER

logger = logging.getLogger(__name__)


def setup_task_parser(subparsers) -> None:
    """注册 task 子命令"""
    if not HAS_APSCHEDULER:
        # 即便 apscheduler 未安装，也注册 parser 让用户能看到错误
        pass

    parser = subparsers.add_parser('task', help='任务管理（飞书"## 任务管理"）')
    task_subparsers = parser.add_subparsers(dest='task_command', help='任务子命令')

    # add
    p_add = task_subparsers.add_parser('add', help='添加定时任务')
    p_add.add_argument('--name', required=True, help='任务名（唯一）')
    p_add.add_argument('--cron', required=True,
                       help='cron 表达式（5 段：分 时 日 月 周），例：0 17 * * 1-5')
    p_add.add_argument('--action', required=True,
                       help=f'任务动作，可选：{list_registered_tasks()}')
    p_add.add_argument('--retry', type=int, default=3, help='失败重试次数（默认 3）')

    # remove
    p_remove = task_subparsers.add_parser('remove', help='删除任务')
    p_remove.add_argument('--name', required=True, help='任务名')

    # list
    task_subparsers.add_parser('list', help='列出所有任务')

    # run
    p_run = task_subparsers.add_parser('run', help='立即运行任务')
    p_run.add_argument('--name', required=True, help='任务名')

    # daemon
    p_daemon = task_subparsers.add_parser('daemon', help='启停调度器')
    p_daemon.add_argument('action', choices=['start', 'stop'],
                          help='start=启动, stop=停止')


def _validate_task_meta(name, cron, action, retry):
    """校验任务元数据（无 apscheduler 时也可用）"""
    if not isinstance(name, str) or not name:
        raise ValueError("任务名必须为非空字符串")
    cron_parts = cron.split()
    if len(cron_parts) != 5:
        raise ValueError(f"cron 表达式必须 5 段：{cron}")
    if action not in _get_task_registry_names():
        raise ValueError(
            f"未知 action: {action!r}，可选：{_get_task_registry_names()}"
        )
    if retry < 0:
        raise ValueError("retry 不能为负")


def _get_task_registry_names() -> set:
    """从 TASK_REGISTRY 收集 action 名（兼容多种结构）"""
    try:
        from src.tasks import TASK_REGISTRY
        return set(TASK_REGISTRY.keys())
    except Exception:
        return set()


def run_task_command(args, db_path: str) -> int:
    """执行 task 子命令"""
    # 1) add/remove/list：仅依赖 TASK_REGISTRY，不依赖 apscheduler
    if args.task_command in ('add', 'remove', 'list'):
        return _run_meta_command(args, db_path)

    # 2) run/daemon：需要 apscheduler
    if not HAS_APSCHEDULER:
        print("[ERROR] APScheduler 未安装，无法执行 run/daemon。")
        print("        请运行: pip install apscheduler")
        print("        或使用 add/remove/list 进行元数据管理（无调度能力）")
        return 1

    scheduler = TaskScheduler(db_path)
    _load_persisted_tasks(scheduler, db_path)

    if args.task_command == 'run':
        result = scheduler.run_now(args.name)
        print(f"[OK] 任务已运行: {args.name}")
        print(f"  result: {result}")
        return 0

    elif args.task_command == 'daemon':
        if args.action == 'start':
            scheduler.start()
            print("[OK] 调度器已启动")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                scheduler.stop()
                print("\n[OK] 调度器已停止")
            return 0
        elif args.action == 'stop':
            scheduler.stop()
            print("[OK] 调度器已停止")
            return 0

    print(f"[ERROR] 未知子命令: {args.task_command}")
    return 1


def _run_meta_command(args, db_path: str) -> int:
    """不依赖 apscheduler 的 add/remove/list"""
    # 读取已持久化的任务
    persist_path = Path(db_path).parent / _PERSIST_FILE
    meta: dict = {}
    if persist_path.exists():
        try:
            with open(persist_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except Exception:
            meta = {}

    if args.task_command == 'add':
        try:
            _validate_task_meta(args.name, args.cron, args.action, args.retry)
        except Exception as e:
            print(f"[ERROR] 添加任务失败: {e}")
            return 1
        meta[args.name] = {
            'cron': args.cron,
            'action': args.action,
            'retry': args.retry,
        }
        try:
            with open(persist_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ERROR] 持久化失败: {e}")
            return 1
        print(f"[OK] 任务已添加: {args.name}")
        print(f"  cron:   {args.cron}")
        print(f"  action: {args.action}")
        print(f"  retry:  {args.retry}")
        return 0

    elif args.task_command == 'remove':
        if args.name not in meta:
            print(f"[ERROR] 任务不存在: {args.name}")
            return 1
        del meta[args.name]
        try:
            with open(persist_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ERROR] 持久化失败: {e}")
            return 1
        print(f"[OK] 任务已移除: {args.name}")
        return 0

    elif args.task_command == 'list':
        if not meta:
            print("当前无任务")
            return 0
        print(f"{'NAME':<20} {'CRON':<20} {'ACTION':<15} {'RETRY':<6} {'NEXT RUN'}")
        print("-" * 80)
        for name, t in meta.items():
            next_run = '-'  # 简化：未启动 scheduler 时无 next_run
            print(f"{name:<20} {t.get('cron', '-'):<20} {t.get('action', '-'):<15} "
                  f"{t.get('retry', 0):<6} {next_run}")
        return 0

    return 1


# ============ 任务持久化（简化版） ============

_PERSIST_FILE = '.task_registry.json'


def _persist_tasks(scheduler, db_path: str) -> None:
    """把任务配置保存到 JSON 文件（apscheduler 模式）"""
    try:
        persist_path = Path(db_path).parent / _PERSIST_FILE
        data = scheduler._task_meta
        with open(persist_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"持久化任务配置失败: {e}")


def _load_persisted_tasks(scheduler, db_path: str) -> None:
    """从 JSON 文件加载任务配置（apscheduler 模式）"""
    try:
        persist_path = Path(db_path).parent / _PERSIST_FILE
        if not persist_path.exists():
            return
        with open(persist_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for name, meta in data.items():
            try:
                scheduler.add_task(
                    name=name,
                    cron=meta['cron'],
                    action=meta['action'],
                    retry=meta.get('retry', 3),
                    **meta.get('kwargs', {}),
                )
            except Exception as e:
                logger.warning(f"加载任务 {name} 失败: {e}")
    except Exception as e:
        logger.warning(f"加载任务配置失败: {e}")


__all__ = ['setup_task_parser', 'run_task_command']
