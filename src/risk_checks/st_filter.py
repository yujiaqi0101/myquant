"""
src/risk_checks/st_filter.py
============================

A 股 ST / *ST / 退市股过滤 Check（迁移自 src/quantlab_extras/st_filter.py）。

ST 股票风险较高（退市风险、流动性差、波动剧烈），策略上一般回避买入。
本 Check 拒绝买入 ST/*ST/退市股票。

判断规则（按优先级）：
    1. stock_info.is_st 字段为 True   -> 拒买（首选，数据源直接标注）
    2. stock_info.name 字段含 "ST"    -> 拒买（兼容旧数据格式）
    3. stock_info.name 以 "退" 开头    -> 拒买（退市整理期股票）

适配新版统一引擎：
    - 输入：Order + context_data（dict）
    - 输出：RiskCheckResult（passed/reason）
    - 数据来源：context_data["stock_info"]（dict，含 is_st/name 字段）

只在买入时过滤（卖出允许，因为持有 ST 股后需要能清仓退出）。

用法：
    from src.risk_checks.st_filter import STFilterCheck
    rm.add_check(STFilterCheck())
"""

import logging
from typing import Any, Dict

from src.core.risk.checks import RiskCheck, RiskCheckResult, get_field
from src.core.types import Direction, Order


logger = logging.getLogger(__name__)


class STFilterCheck(RiskCheck):
    """拒绝买入 ST/*ST/退市股。

    优先用 stock_info.is_st 字段判断（bool）；
    缺失时降级用 stock_info.name 字段做名称匹配（兼容旧数据）。
    """

    def __init__(self, name: str = "STFilterCheck") -> None:
        super().__init__(name)

    @staticmethod
    def _is_st_by_name(name: str) -> bool:
        """根据股票名称判断是否为 ST/退市股。

        Args:
            name: 股票名称（如 "*ST海航" / "退市XXX" / "贵州茅台"）

        Returns:
            True 表示是 ST/退市股
        """
        if not name:
            return False
        # 名称含 "ST"（覆盖 "ST XXX" / "*ST XXX" / "S*ST XXX" 等所有变体）
        if "ST" in name.upper():
            return True
        # 退市整理期股票名称以 "退" 开头
        if name.startswith("退"):
            return True
        return False

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查买入订单的目标股票是否为 ST/退市股。"""
        # 只在买入时过滤；卖出放行（持有 ST 股需能清仓）
        if order.direction is not Direction.BUY:
            return RiskCheckResult.passed_result(self.name)

        # 取股票基本信息（缺失时降级放行）
        stock_info = context_data.get("stock_info")
        if stock_info is None:
            return RiskCheckResult.passed_result(self.name)

        # 优先用 is_st 字段（bool，数据源直接标注）
        is_st = get_field(stock_info, "is_st", None)
        # is_st 为 None 时降级用 name 判断（兼容旧数据格式）
        if is_st is None:
            name = get_field(stock_info, "name", "") or ""
            is_st = self._is_st_by_name(name)

        # is_st 为真 -> 拒买
        if is_st:
            name = get_field(stock_info, "name", "") or ""
            logger.info(
                "STFilterCheck 拒买 %s (name=%s, is_st=%s)",
                order.symbol,
                name,
                is_st,
            )
            return RiskCheckResult.rejected(
                self.name,
                f"{order.symbol} 是 ST/*ST/退市股（name={name}），拒买",
            )
        return RiskCheckResult.passed_result(self.name)
