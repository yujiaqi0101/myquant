"""
src/risk_checks/new_stock.py
============================

A 股新股过滤 Check（迁移自 src/quantlab_extras/new_stock.py）。

上市未满 N 个交易日的股票波动剧烈、容易破发，策略上一般回避。
默认阈值 60 天（约 3 个月），可通过 min_days 参数调整。

适配新版统一引擎：
    - 输入：Order + context_data（dict）
    - 输出：RiskCheckResult（passed/reason）
    - 数据来源：
        - context_data["stock_info"].list_date（上市日期）
        - context_data["current_time"]（当前时间）
    - 计算：(current_time - list_date).days，不足 min_days 则拒买

日期类型兼容：list_date / current_time 支持 date / datetime / ISO 字符串三种格式。

只在买入时过滤（卖出放行，持有新股后需能止损退出）。

用法：
    from src.risk_checks.new_stock import NewStockCheck
    rm.add_check(NewStockCheck(min_days=60))
"""

import logging
from datetime import date, datetime
from typing import Any, Dict

from src.core.risk.checks import RiskCheck, RiskCheckResult, get_field
from src.core.types import Direction, Order


logger = logging.getLogger(__name__)


def _to_date(value: Any) -> date:
    """将多种日期格式统一转换为 date 对象。

    支持的类型：
        - datetime：取 .date()
        - date：直接返回
        - str：用 fromisoformat 解析（兼容 "2024-01-01" / "2024-01-01 00:00:00"）

    Args:
        value: 日期值

    Returns:
        date 对象

    Raises:
        TypeError:  不支持的类型
        ValueError: 字符串格式无法解析
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        # fromisoformat 兼容 "YYYY-MM-DD" 和 "YYYY-MM-DD HH:MM:SS"
        return datetime.fromisoformat(value).date()
    raise TypeError(f"不支持的日期类型: {type(value)}")


class NewStockCheck(RiskCheck):
    """上市 N 日内禁买。

    计算当前日期距离上市日期的自然日天数，不足 min_days 则拒绝买入。
    """

    def __init__(self, min_days: int = 60, name: str = "NewStockCheck") -> None:
        """初始化新股过滤 Check。

        Args:
            min_days: 上市最少天数门槛，默认 60 天
            name: Check 名称
        """
        super().__init__(name)
        # 上市最少天数（强制 int，避免传 float 导致比较异常）
        self.min_days = int(min_days)

    def check(self, order: Order, context_data: Dict[str, Any]) -> RiskCheckResult:
        """检查买入订单的目标股票是否为新股（上市不足 min_days 天）。"""
        # 只在买入时过滤；卖出放行（持有新股需能止损退出）
        if order.direction is not Direction.BUY:
            return RiskCheckResult.passed_result(self.name)

        # 取股票基本信息（缺失时降级放行）
        stock_info = context_data.get("stock_info")
        if stock_info is None:
            return RiskCheckResult.passed_result(self.name)

        # 取上市日期（缺失时降级放行，无上市日期视为非新股）
        list_date_raw = get_field(stock_info, "list_date", None)
        if not list_date_raw:
            return RiskCheckResult.passed_result(self.name)

        # 取当前时间（缺失时降级放行，无法计算上市天数）
        current_time = context_data.get("current_time")
        if current_time is None:
            return RiskCheckResult.passed_result(self.name)

        # 日期解析（格式异常时降级放行，避免阻塞主流程）
        try:
            list_date = _to_date(list_date_raw)
            current_date = _to_date(current_time)
        except (TypeError, ValueError):
            logger.warning(
                "NewStockCheck 跳过 %s：日期解析失败（list_date=%s, current=%s）",
                order.symbol,
                list_date_raw,
                current_time,
            )
            return RiskCheckResult.passed_result(self.name)

        # 计算上市天数（自然日）
        listed_days = (current_date - list_date).days

        # 上市天数不足门槛 -> 拒买
        if listed_days < self.min_days:
            logger.info(
                "NewStockCheck 拒买 %s：上市 %s 天 < %s 天",
                order.symbol,
                listed_days,
                self.min_days,
            )
            return RiskCheckResult.rejected(
                self.name,
                f"{order.symbol} 新股拒买：上市 {listed_days} 天 < "
                f"门槛 {self.min_days} 天（list_date={list_date}）",
            )
        return RiskCheckResult.passed_result(self.name)
