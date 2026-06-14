#!/usr/bin/env python3
"""
P0 Task 6.5 验证：任务管理（APScheduler）
==========================================
飞书"## 任务管理"要求：
- 实现任务队列
- 任务定时执行
- 失败任务重试
- 失败重试
- 支持将来更多任务的加入
"""
import sys
import os
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_task_registry():
    """验证 TASK_REGISTRY 注册表"""
    print("=" * 60)
    print("Task 6.5 验证 1: TASK_REGISTRY 注册表")
    print("=" * 60)

    from src.tasks import TASK_REGISTRY, register_task, get_task, list_tasks

    # 验证内置任务 sync 已注册
    assert 'sync' in TASK_REGISTRY, "sync 任务未注册"
    print(f"[OK] 内置任务已注册: sync -> {TASK_REGISTRY['sync'].__name__}")

    # 用函数式注册自定义任务
    def custom_task(db_path: str, **kwargs):
        return {'status': 'success'}

    register_task('custom', custom_task)
    assert 'custom' in TASK_REGISTRY, "custom 任务未注册"
    print(f"[OK] 自定义任务已注册: custom -> {TASK_REGISTRY['custom'].__name__}")

    # 列出所有任务
    tasks = list_tasks()
    print(f"[OK] 已注册任务: {tasks}")

    # 清理
    del TASK_REGISTRY['custom']

    print("\n[PASS] TASK_REGISTRY 注册表测试通过\n")


def test_task_scheduler():
    """验证 TaskScheduler 调度器"""
    print("=" * 60)
    print("Task 6.5 验证 2: TaskScheduler 调度器")
    print("=" * 60)

    try:
        from src.scheduler import TaskScheduler, HAS_APSCHEDULER
    except ImportError as e:
        print(f"[SKIP] APScheduler 未安装: {e}")
        return

    if not HAS_APSCHEDULER:
        print("[SKIP] APScheduler 模块不可用")
        return

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        scheduler = TaskScheduler(db_path)

        # 添加任务
        scheduler.add_task(
            name='test_task',
            cron='*/5 * * * *',  # 每 5 分钟
            action='sync',
            retry=2,
        )
        print("[OK] 任务已添加: test_task (cron='*/5 * * * *')")

        # 列出任务
        tasks = scheduler.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]['name'] == 'test_task'
        assert tasks[0]['cron'] == '*/5 * * * *'
        print(f"[OK] 任务列表: {tasks[0]}")

        # 移除任务
        scheduler.remove_task('test_task')
        tasks = scheduler.list_tasks()
        assert len(tasks) == 0
        print("[OK] 任务已移除: test_task")

        print("\n[PASS] TaskScheduler 调度器测试通过\n")
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_failure_retry():
    """验证失败任务重试（指数退避）"""
    print("=" * 60)
    print("Task 6.5 验证 3: 失败任务重试")
    print("=" * 60)

    try:
        from src.scheduler import TaskScheduler, HAS_APSCHEDULER
        from src.tasks import register_task
    except ImportError as e:
        print(f"[SKIP] {e}")
        return

    if not HAS_APSCHEDULER:
        print("[SKIP] APScheduler 不可用")
        return

    # 注册一个会失败的任务
    call_count = [0]

    def always_fail(db_path: str, **kwargs):
        call_count[0] += 1
        raise ValueError("模拟失败")

    register_task('always_fail', always_fail)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        scheduler = TaskScheduler(db_path)
        scheduler.add_task(
            name='fail_test',
            cron='0 0 1 1 *',  # 每年 1 月 1 日（不会真触发）
            action='always_fail',
            retry=3,
        )

        # 手动触发
        start = time.time()
        result = scheduler.run_now('fail_test')
        elapsed = time.time() - start

        # 应该调用 3 次（重试 3 次）
        assert call_count[0] == 3, f"期望 3 次调用，实际 {call_count[0]} 次"
        # 指数退避 1s + 2s = 3s 等待时间
        assert 2.5 < elapsed < 6, f"期望 ~3 秒等待，实际 {elapsed:.2f} 秒"

        # 结果应该是 failed
        assert result['status'] == 'failed', f"期望 status=failed，实际 {result['status']}"

        print(f"[OK] 失败任务被正确重试 {call_count[0]} 次")
        print(f"[OK] 指数退避时间: {elapsed:.2f} 秒（期望 ~3 秒）")
        print(f"[OK] 最终结果: {result['status']}")

        # 清理
        scheduler.remove_task('fail_test')
        from src.tasks import TASK_REGISTRY
        TASK_REGISTRY.pop('always_fail', None)

        print("\n[PASS] 失败任务重试测试通过\n")
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    success = True
    try:
        test_task_registry()
    except Exception as e:
        print(f"[FAIL] TASK_REGISTRY: {e}")
        import traceback
        traceback.print_exc()
        success = False

    try:
        test_task_scheduler()
    except Exception as e:
        print(f"[FAIL] TaskScheduler: {e}")
        import traceback
        traceback.print_exc()
        success = False

    try:
        test_failure_retry()
    except Exception as e:
        print(f"[FAIL] 失败重试: {e}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)
