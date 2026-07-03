"""
src/core/risk/__init__.py
=========================

风控管线核心包初始化模块。

统一导出风控管线的三个核心抽象：
    - RiskCheck         风控检查抽象基类
    - RiskCheckResult   风控检查结果
    - RiskManager       风控管线管理器（串联 Check）
    - get_field         兼容 dict/dataclass 的字段访问工具

设计文档第 5 节：RiskManager 是事件驱动内核的下单前风控闸门，
位于 context.submit_order() 与 Execution.submit() 之间。
所有 A 股法定风控 Check 实现在 src/risk_checks/ 包中，由工厂函数组装。

用法：
    from src.core.risk import RiskManager, RiskCheck, RiskCheckResult
    from src.risk_checks.factory import build_ashare_risk_manager
    rm = build_ashare_risk_manager()
"""

from src.core.risk.checks import RiskCheck, RiskCheckResult, get_field
from src.core.risk.manager import RiskManager

__all__ = [
    "RiskCheck",
    "RiskCheckResult",
    "RiskManager",
    "get_field",
]
