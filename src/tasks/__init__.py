"""
任务注册表
=========

提供可扩展的任务注册机制，飞书"## 任务管理"章节要求"支持将来更多任务的加入"。

设计原则：
- TASK_REGISTRY：全局任务名 → 任务函数 的映射
- register_task()：注册新任务（Plugin 接口）
- 所有任务签名统一为 (db_path: str, **kwargs) -> dict
"""
from typing import Callable, Dict, List
import logging

logger = logging.getLogger(__name__)

# 全局任务注册表
TASK_REGISTRY: Dict[str, Callable] = {}


def register_task(name: str, func: Callable) -> None:
    """
    注册一个任务到 TASK_REGISTRY

    Parameters
    ----------
    name : str
        任务名（用于 CLI 和调度器）
    func : Callable
        任务函数，签名 (db_path: str, **kwargs) -> dict
    """
    if name in TASK_REGISTRY:
        logger.warning(f"任务 {name} 已存在，将被覆盖")
    TASK_REGISTRY[name] = func
    logger.info(f"已注册任务: {name} -> {func.__name__}")


def get_task(name: str) -> Callable:
    """获取已注册的任务函数"""
    if name not in TASK_REGISTRY:
        raise KeyError(f"任务 {name} 未注册，可用任务: {list(TASK_REGISTRY.keys())}")
    return TASK_REGISTRY[name]


def list_tasks() -> List[str]:
    """列出所有已注册任务"""
    return sorted(TASK_REGISTRY.keys())


# ============ 内置任务：数据采集 ============

def sync_task(db_path: str, start_date: str = '', end_date: str = '', **kwargs) -> dict:
    """
    数据采集任务（包装 DataSynchronizer.sync_all）

    Parameters
    ----------
    db_path : str
        数据库路径
    start_date : str
        起始日期 YYYYMMDD
    end_date : str
        结束日期 YYYYMMDD

    Returns
    -------
    dict
        同步结果摘要
    """
    try:
        from src.data.data_sync import DataSynchronizer
        from src.data.qmt_connector import QMTConnector
        from src.data.database import DatabaseManager
    except ImportError as e:
        logger.error(f"导入失败: {e}")
        return {'status': 'failed', 'error': str(e)}

    db = DatabaseManager(db_path)
    connector = QMTConnector()
    if not connector.is_connected():
        connector.connect()
    if not connector.is_connected():
        return {'status': 'failed', 'error': 'QMT未连接'}

    synchronizer = DataSynchronizer(connector, db)
    result = synchronizer.sync_all(start_date=start_date, end_date=end_date)
    return {'status': 'success', 'result': result}


# 注册内置任务
register_task('sync', sync_task)


__all__ = ['register_task', 'get_task', 'list_tasks', 'TASK_REGISTRY', 'sync_task']
