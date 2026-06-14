"""
test_task_cli.py
================

单元测试 src/cli/task_cli.py 的 task 子命令：
- add: 注册 cron 任务（不需要 apscheduler）
- remove: 删除任务（不需要 apscheduler）
- list: 列出任务（不需要 apscheduler）
- run: 立即执行任务（需要 apscheduler，否则跳过）
- daemon start/stop: 调度器启停（需要 apscheduler，否则跳过）
"""
import sys, os, tempfile, argparse, json
sys.path.insert(0, '.')
from src.cli.task_cli import setup_task_parser, run_task_command
from src.scheduler import HAS_APSCHEDULER

import pytest


def _make_args(args_dict):
    return argparse.Namespace(**args_dict)


def test_parser_setup():
    """CLI parser 能正常注册"""
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest='cmd')
    setup_task_parser(subs)
    args = p.parse_args(['task', 'add', '--name', 't1', '--cron', '0 17 * * 1-5', '--action', 'sync_task'])
    assert args.task_command == 'add'
    assert args.name == 't1'
    assert args.cron == '0 17 * * 1-5'
    assert args.action == 'sync_task'


def test_add_list_remove(tmp_path):
    """任务增删查（不依赖 apscheduler）"""
    db_path = str(tmp_path / 'aquant.db')
    persist_path = tmp_path / '.task_registry.json'

    # 1) add
    args = _make_args({
        'task_command': 'add',
        'name': 'daily_sync',
        'cron': '0 17 * * 1-5',
        'action': 'sync',
        'retry': 3,
    })
    rc = run_task_command(args, db_path)
    assert rc == 0
    assert persist_path.exists()
    saved = json.loads(persist_path.read_text(encoding='utf-8'))
    assert 'daily_sync' in saved

    # 2) list
    args = _make_args({'task_command': 'list'})
    rc = run_task_command(args, db_path)
    assert rc == 0

    # 3) remove
    args = _make_args({'task_command': 'remove', 'name': 'daily_sync'})
    rc = run_task_command(args, db_path)
    assert rc == 0
    saved = json.loads(persist_path.read_text(encoding='utf-8'))
    assert 'daily_sync' not in saved

    # 4) remove 第二次（任务不存在）
    args = _make_args({'task_command': 'remove', 'name': 'daily_sync'})
    rc = run_task_command(args, db_path)
    assert rc == 1


def test_add_invalid_cron(tmp_path):
    """非法 cron 表达式应被拒绝"""
    db_path = str(tmp_path / 'aquant.db')
    args = _make_args({
        'task_command': 'add',
        'name': 'bad',
        'cron': '0 0 0',  # 只有 3 段
        'action': 'sync',
        'retry': 3,
    })
    rc = run_task_command(args, db_path)
    assert rc == 1


def test_add_invalid_action(tmp_path):
    """未知 action 应被拒绝"""
    db_path = str(tmp_path / 'aquant.db')
    args = _make_args({
        'task_command': 'add',
        'name': 'bad',
        'cron': '0 17 * * 1-5',
        'action': 'unknown_action_xyz',
        'retry': 3,
    })
    rc = run_task_command(args, db_path)
    assert rc == 1


@pytest.mark.skipif(not HAS_APSCHEDULER, reason="APScheduler 未安装")
def test_run_task(tmp_path):
    """run 子命令：立即执行（需要 apscheduler）"""
    from src.tasks import register_task
    def fake_action(kwargs=None):
        return {'ok': True, 'kwargs': kwargs or {}}
    register_task('test_fake', fake_action)

    db_path = str(tmp_path / 'aquant.db')
    # 先添加
    args = _make_args({
        'task_command': 'add',
        'name': 't1',
        'cron': '*/5 * * * *',
        'action': 'test_fake',
        'retry': 1,
    })
    run_task_command(args, db_path)

    # 然后 run
    args = _make_args({'task_command': 'run', 'name': 't1'})
    rc = run_task_command(args, db_path)
    assert rc == 0


@pytest.mark.skipif(not HAS_APSCHEDULER, reason="APScheduler 未安装")
def test_daemon_stop(tmp_path):
    """daemon stop（需要 apscheduler）"""
    db_path = str(tmp_path / 'aquant.db')
    args = _make_args({'task_command': 'daemon', 'action': 'stop'})
    rc = run_task_command(args, db_path)
    assert rc == 0


def test_run_without_apscheduler(tmp_path):
    """无 apscheduler 时 run/daemon 应返回错误"""
    if HAS_APSCHEDULER:
        pytest.skip("apscheduler 已安装，跳过本测试")
    db_path = str(tmp_path / 'aquant.db')
    args = _make_args({'task_command': 'run', 'name': 'x'})
    rc = run_task_command(args, db_path)
    assert rc == 1
