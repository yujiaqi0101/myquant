"""
src/core/persistence/__init__.py
================================

持久化模块包导出。

本包负责模拟盘/实盘的账户/持仓/订单/成交/快照持久化，
使用 account_* 系列表取代旧的 paper_* 表。

回测模式不使用本模块（纯内存）；模拟盘/实盘每日收盘后调用本模块持久化状态。

阶段4（设计文档第 6.3 节）：
    - PersistenceRepository: account_* 5 张表的 CRUD
"""

from src.core.persistence.repository import PersistenceRepository

__all__ = ["PersistenceRepository"]
