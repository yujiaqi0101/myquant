"""
src/core/risk/checks.py
=======================

风控 Check 抽象基类模块（风控管线核心）。

本模块定义风控管线的两个基础抽象：
    - RiskCheckResult   风控检查结果（dataclass）
    - RiskCheck         风控检查抽象基类（ABC）

设计目标（设计文档第 5 节）：
    1. 统一所有风控 Check 的输入输出契约：check(order, context_data) -> RiskCheckResult
    2. context_data 由 RiskManager 通过 context_provider 注入，屏蔽回测/模拟盘/实盘差异
    3. Check 之间相互独立，可按任意顺序串联（由 RiskManager.add_check 决定执行顺序）
    4. 任一 Check 不通过即拒绝订单，短路返回（不再执行后续 Check）

context_data 约定字段（由 context_provider 提供，缺失时 Check 应安全降级）：
    - current_time   当前时间（datetime/date/str，用于新股上市天数判断）
    - current_price  当前价格（float，用于仓位占比计算）
    - bar            当日 bar 数据（BarEvent 或 dict，含 prev_close/volume 等）
    - stock_info     股票基本信息（dict，含 is_st/list_date/is_suspended/name 等）
    - position       当前 symbol 持仓（Position 或 dict，含 available/quantity）
    - account        账户信息（AccountEvent 或 dict，含 total/daily_pnl_pct）
    - portfolio      全部持仓（dict[symbol->Position] 或 list[Position]）

为兼容 dataclass（BarEvent/Position/AccountEvent）与 dict 两种数据形态，
本模块提供 get_field(obj, key, default) 工具函数，统一属性/键访问。

用法示例：
    from src.core.risk.checks import RiskCheck, RiskCheckResult

    class MyCheck(RiskCheck):
        def check(self, order, context_data):
            price = get_field(context_data.get("bar"), "close", 0.0)
            if price <= 0:
                return RiskCheckResult.passed(self.name)
            return RiskCheckResult(self.name, passed=True)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.core.types import Order


# ---------------------------------------------------------------------------
# 工具函数：兼容 dict / dataclass 的字段访问
# ---------------------------------------------------------------------------


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    """安全读取对象字段，兼容 dict 与 dataclass/普通对象。

    context_data 中的 bar/stock_info/position/account/portfolio 字段，
    在不同运行模式下可能是 dataclass（如回测直接传 BarEvent/Position）
    或 dict（如实盘从 API 返回的 JSON）。本函数统一两种访问方式，
    避免 Check 代码中遍布 isinstance 判断。

    Args:
        obj:  待读取对象（dict 或任意对象，可为 None）
        key:  字段名（dict 的键 或 对象属性名）
        default: 字段缺失时的返回值

    Returns:
        字段值；obj 为 None 或字段不存在时返回 default

    用法：
        bar = context_data.get("bar")
        prev_close = get_field(bar, "prev_close", None)
    """
    # obj 为 None 直接返回默认值，避免 AttributeError
    if obj is None:
        return default
    # dict 用 .get 访问
    if isinstance(obj, dict):
        return obj.get(key, default)
    # 其他对象用 getattr 访问，缺失时返回 default
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# 风控检查结果
# ---------------------------------------------------------------------------


@dataclass
class RiskCheckResult:
    """风控检查结果。

    每个 RiskCheck.check() 必须返回本类型，RiskManager 据此决定是否继续。

    Attributes:
        passed:      是否通过（True=放行，False=拒绝订单）
        check_name:  执行检查的 Check 名称（用于日志/拒绝原因定位）
        reason:      拒绝原因（passed=False 时填写，便于策略/日志排查；
                     passed=True 时通常为 None）
    """

    passed: bool
    check_name: str
    reason: Optional[str] = None

    # ----- 便捷构造方法 -----

    @classmethod
    def passed_result(cls, check_name: str) -> "RiskCheckResult":
        """构造"通过"结果。"""
        return cls(passed=True, check_name=check_name, reason=None)

    @classmethod
    def rejected(cls, check_name: str, reason: str) -> "RiskCheckResult":
        """构造"拒绝"结果。"""
        return cls(passed=False, check_name=check_name, reason=reason)

    def __bool__(self) -> bool:
        """支持 if result: 语法，等价于 result.passed。"""
        return self.passed


# ---------------------------------------------------------------------------
# RiskCheck 抽象基类
# ---------------------------------------------------------------------------


class RiskCheck(ABC):
    """风控检查抽象基类。

    所有具体风控 Check 必须继承本类并实现 check() 方法。
    Check 是无状态（或自管理状态）的检查单元，由 RiskManager 按添加顺序串联执行。

    上下文数据来源：
        check() 的 context_data 参数由 RiskManager 在调用前组装：
            1. 优先使用 check_order(order, context_data) 调用时传入的 context_data
            2. 若未传入，则调用 context_provider() 获取最新上下文
        Check 不应自行访问引擎内部，所有依赖数据通过 context_data 获取。

    Attributes:
        name: Check 名称（默认用类名；子类可在 __init__ 中覆盖或设置类属性）
    """

    def __init__(self, name: str = "") -> None:
        """初始化 Check。

        Args:
            name: Check 名称，空字符串时默认用类名（便于日志定位）
        """
        # 名称：传入则用传入值，否则用类名
        self.name: str = name if name else type(self).__name__

    @abstractmethod
    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """执行风控检查（子类必须实现）。

        Args:
            order:         待检查订单（含 symbol/direction/volume 等字段）
            context_data:  上下文数据（含 current_time/bar/stock_info/position 等）

        Returns:
            RiskCheckResult：passed=True 放行，passed=False 拒绝（附带 reason）

        实现建议：
            1. 优先判断订单方向是否需要检查（如涨停Check只查买入）
            2. 依赖字段缺失时安全降级（返回 passed=True 并记日志），避免阻塞主流程
            3. reason 文案包含 symbol 与关键数值，便于排查
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<RiskCheck {self.name}>"
