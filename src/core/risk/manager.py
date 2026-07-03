"""
src/core/risk/manager.py
========================

RiskManager 风控管线管理器模块。

本模块定义风控管线的编排核心：
    - RiskManager 串联多个 RiskCheck，按添加顺序依次执行

设计目标（设计文档第 5.1 节）：
    1. 风控三层架构：PreTradeCheck → OrderSizeCheck → PortfolioCheck（可选）
    2. 任一 Check 不通过即短路返回 RiskCheckResult(passed=False)，不再执行后续 Check
    3. 通过 context_provider 注入运行时上下文，屏蔽回测/模拟盘/实盘差异
    4. 引擎在 context.submit_order() 内部调用 manager.check_order() 做下单前风控

执行流程：
    策略调用 context.submit_order()
        ↓
    RiskManager.check_order(order)
        ├── 1. 组装 context_data（调用 context_provider 或使用传入参数）
        ├── 2. 依次执行 _checks 列表中的每个 Check
        └── 3. 第一个不通过即返回；全部通过返回 passed=True

用法示例：
    from src.core.risk.manager import RiskManager

    rm = RiskManager()
    rm.add_check(LimitUpCheck())
    rm.add_check(STFilterCheck())
    rm.set_context_provider(lambda: {"bar": ..., "stock_info": ...})

    result = rm.check_order(order)
    if not result:
        # 风控拒绝，订单不进入 Execution
        ...

context_provider 约定：
    一个无参可调用对象，返回 dict（结构见 checks.py 文件头注释）。
    引擎在每次 check_order 前调用它获取最新上下文（行情/持仓/账户实时变化）。
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from src.core.risk.checks import RiskCheck, RiskCheckResult
from src.core.types import Order


logger = logging.getLogger(__name__)


# context_provider 类型：无参可调用对象，返回上下文字典
ContextProvider = Callable[[], Dict[str, Any]]


class RiskManager:
    """风控管线管理器。

    串联多个 RiskCheck，按 add_check 的添加顺序依次执行。
    任一 Check 返回 passed=False 即短路返回，不再执行后续 Check。

    Attributes:
        _checks:            Check 列表（按添加顺序）
        _context_provider:  上下文数据提供者（无参函数，返回 dict）
    """

    def __init__(self) -> None:
        """初始化空的风控管线。"""
        # Check 列表：按 add_check 顺序执行
        self._checks: List[RiskCheck] = []
        # 上下文提供者：check_order 时调用以获取最新行情/持仓/账户
        self._context_provider: Optional[ContextProvider] = None

    # ------------------------------------------------------------------
    # Check 管理
    # ------------------------------------------------------------------

    def add_check(self, check: RiskCheck) -> None:
        """添加一个风控 Check（按添加顺序执行）。

        Args:
            check: RiskCheck 实例

        Raises:
            TypeError: check 不是 RiskCheck 子类实例
        """
        # 类型校验，防止误传入非 Check 对象
        if not isinstance(check, RiskCheck):
            raise TypeError(
                f"add_check 仅接受 RiskCheck 实例，收到 {type(check).__name__}"
            )
        self._checks.append(check)
        logger.debug("RiskManager 添加 Check: %s", check.name)

    def get_check_names(self) -> List[str]:
        """获取所有已注册 Check 的名称（按执行顺序）。

        Returns:
            Check 名称列表
        """
        # 返回副本，避免外部修改内部列表
        return [c.name for c in self._checks]

    # ------------------------------------------------------------------
    # 上下文注入
    # ------------------------------------------------------------------

    def set_context_provider(self, provider: ContextProvider) -> None:
        """注入上下文数据提供者。

        引擎在启动时调用，注入一个无参函数。该函数返回当前最新的上下文字典，
        包含 current_time/bar/stock_info/position/account/portfolio 等字段。
        check_order 在 context_data 缺失时调用它获取上下文。

        Args:
            provider: 无参可调用对象，返回 dict

        Raises:
            TypeError: provider 不可调用
        """
        if not callable(provider):
            raise TypeError("context_provider 必须是可调用对象")
        self._context_provider = provider

    # ------------------------------------------------------------------
    # 风控检查入口
    # ------------------------------------------------------------------

    def check_order(
        self,
        order: Order,
        context_data: Optional[Dict[str, Any]] = None,
    ) -> RiskCheckResult:
        """对订单执行全量风控检查。

        执行逻辑：
            1. 组装 context_data：
               - 优先使用调用方传入的 context_data
               - 否则调用 _context_provider() 获取
               - 两者都没有则用空 dict（Check 应安全降级）
            2. 依次执行 _checks 中每个 Check
            3. 第一个 passed=False 即短路返回
            4. 全部通过返回最后一个 Check 的 passed=True 结果
               （无 Check 时返回 passed=True，相当于无风控）

        Args:
            order:         待检查订单
            context_data:  上下文数据（可选，未提供时调用 context_provider）

        Returns:
            RiskCheckResult：
                - 通过：passed=True
                - 拒绝：passed=False + check_name + reason
        """
        # ----- 1. 组装上下文数据 -----
        if context_data is None:
            # 调用方未传入，向 provider 获取
            if self._context_provider is not None:
                try:
                    context_data = self._context_provider() or {}
                except Exception:
                    # provider 异常不应阻塞订单（降级为空上下文，由 Check 决定放行/拒绝）
                    logger.exception("context_provider 调用异常，使用空上下文")
                    context_data = {}
            else:
                # 既无传入也无 provider，空上下文
                context_data = {}

        # ----- 2. 无 Check 时直接放行 -----
        if not self._checks:
            return RiskCheckResult.passed_result("RiskManager")

        # ----- 3. 依次执行 Check，短路返回 -----
        for check in self._checks:
            try:
                result = check.check(order, context_data)
            except Exception as exc:
                # Check 内部异常：保守拒绝（避免异常订单误放行），记录详细日志
                # 选择"拒绝"而非"放行"是因为风控异常通常意味着数据不可信
                logger.exception(
                    "风控 Check 异常，保守拒绝: check=%s symbol=%s",
                    check.name,
                    getattr(order, "symbol", "?"),
                )
                return RiskCheckResult.rejected(
                    check.name,
                    f"Check 内部异常: {exc}",
                )

            # 不通过即短路返回（不再执行后续 Check）
            if not result.passed:
                logger.info(
                    "风控拒绝: check=%s symbol=%s reason=%s",
                    check.name,
                    getattr(order, "symbol", "?"),
                    result.reason,
                )
                return result

        # ----- 4. 全部通过，返回最后一个结果 -----
        return result

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """已注册 Check 数量。"""
        return len(self._checks)

    def __repr__(self) -> str:
        return f"<RiskManager checks={self.get_check_names()}>"
