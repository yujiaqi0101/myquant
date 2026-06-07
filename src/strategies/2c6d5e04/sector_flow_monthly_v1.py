"""
申万一级行业资金流向策略
========================

策略逻辑：
1. 每日计算申万一级行业的主力资金净流入总额，排名取前3
2. 在这些行业中分别选择：
   - 主力净流入最多的股票（Top N）
   - 入选后N日涨幅最多的股票（Top N）
3. 同行业重叠的股票买入1.5份，跨行业重叠各买1份
4. T日收盘计算排名，T+1日开盘价买入
5. 当行业排名变化时调仓
6. 涨停无法买入，跌停无法卖出（由回测引擎自动处理）

数据来源：东财掘金 API（申万行业分类 + 个股资金流向）
"""

import logging
from typing import List, Dict, Optional, Set

from src.engine import BaseStrategy, register_strategy
from src.engine.types import Order, Direction, Context

logger = logging.getLogger(__name__)


@register_strategy
class SectorFlowMonthlyStrategy(BaseStrategy):
    """
    申万一级行业资金流向策略

    买入逻辑：行业排名变化时，次日开盘买入
    卖出逻辑：不在新选中集合中的持仓，次日开盘卖出

    参数：
    - top_n_industries: 最强行业数量（默认3）
    - inflow_top_stocks: 每个行业净流入Top N（默认[3,2,1]）
    - growth_top_stocks: 每个行业涨幅Top N（默认[3,2,1]）
    - growth_days: 入选后N日涨幅（默认3）
    """

    name = "sector_flow_monthly"
    description = "申万一级行业资金流向策略 - 行业轮动+资金流向选股"

    default_params = {
        **BaseStrategy.default_params,
        'top_n_industries': 3,
        'inflow_top_stocks': [3, 2, 1],
        'growth_top_stocks': [3, 2, 1],
        'growth_days': 3,
        'stop_loss': 0.15,
        'take_profit': 0.50,
        'trailing_stop': 0,
        'max_holding_days': 35,
    }

    def on_init(self, context: Context):
        """策略初始化"""
        from src.data.shenwan_connector import ShenwanConnector
        from src.factors.factor_service import FactorService

        self._shenwan = ShenwanConnector()
        self._factor_service = FactorService(data_source='eastmoney')
        self._prev_industry_ranks: Dict[str, float] = {}
        self._prev_industry_names: Dict[str, str] = {}
        self._pending_orders: List[Order] = []  # T日生成的待执行订单
        self._is_first_day = True

        logger.info("SectorFlowMonthlyStrategy 初始化完成")

    def on_bar(self, context: Context) -> List[Order]:
        """每日调用"""
        date = str(context.date)[:10]
        orders = []

        # ---- 执行上一日生成的待执行订单（T+1日开盘买入/卖出）----
        if self._pending_orders:
            orders.extend(self._execute_pending_orders(context))
            self._pending_orders = []

        # ---- T日收盘：计算排名，检查是否需要调仓 ----
        if self._is_first_day:
            self._is_first_day = False
            # 第一天直接计算排名并生成订单
            orders.extend(self._check_and_generate_orders(date, context))
        else:
            orders.extend(self._check_and_generate_orders(date, context))

        return orders

    def _check_and_generate_orders(self, date: str, context: Context) -> List[Order]:
        """检查排名变化并生成调仓订单"""
        orders = []

        # 1. 计算申万一级行业主力资金净流入排名
        logger.info(f"\n{date} [计算行业资金流向]")

        industry_flows = self._shenwan.get_industry_net_flow(date)
        if industry_flows.empty:
            logger.warning("  无法获取行业资金流向数据")
            return orders

        top_n = self.params.get('top_n_industries', 3)
        top_industries = industry_flows.head(top_n)

        # 打印排名
        logger.info(f"  行业排名（前{top_n}）:")
        for rank, (code, flow) in enumerate(top_industries.items(), 1):
            name = self._get_industry_name(code)
            logger.info(f"    #{rank} {name}({code}): {flow:,.0f}")

        # 2. 检查是否需要调仓
        if not self._should_rebalance(top_industries):
            logger.info("  行业排名未变化，无需调仓")
            return orders

        # 3. 在每个行业中选股
        selected = self._select_stocks_by_industry(top_industries, date)

        if not selected:
            logger.warning("  未选出任何股票")
            return orders

        # 4. 生成调仓订单（T日生成，T+1日执行）
        self._pending_orders = self._generate_rebalance_orders(selected, context)

        logger.info(f"  生成 {len(self._pending_orders)} 个待执行订单（次日开盘执行）")

        return orders

    def _execute_pending_orders(self, context: Context) -> List[Order]:
        """执行待执行订单（T+1日）"""
        # 直接返回待执行订单，回测引擎会处理涨跌停
        return self._pending_orders

    def _should_rebalance(self, new_industries) -> bool:
        """检查是否需要调仓（行业排名变化）"""
        if not self._prev_industry_ranks:
            return True

        new_ranks = set(new_industries.index)
        old_ranks = set(self._prev_industry_ranks.keys())

        if new_ranks != old_ranks:
            # 打印变化
            added = new_ranks - old_ranks
            removed = old_ranks - new_ranks
            if added:
                for code in added:
                    logger.info(f"  新增行业: {self._get_industry_name(code)}({code})")
            if removed:
                for code in removed:
                    logger.info(f"  移除行业: {self._get_industry_name(code)}({code})")
            return True

        return False

    def _select_stocks_by_industry(
        self,
        top_industries,
        date: str,
    ) -> Dict[str, float]:
        """
        按行业选股

        Returns
        -------
        Dict[str, float]
            {stock_code: weight}，weight 为份数（1.0 或 1.5）
        """
        selected = {}
        inflow_config = self.params.get('inflow_top_stocks', [3, 2, 1])
        growth_config = self.params.get('growth_top_stocks', [3, 2, 1])
        growth_days = self.params.get('growth_days', 3)

        for rank, (industry_code, _) in enumerate(top_industries.items(), 1):
            industry_name = self._get_industry_name(industry_code)
            n_inflow = inflow_config[rank - 1] if rank <= len(inflow_config) else 1
            n_growth = growth_config[rank - 1] if rank <= len(growth_config) else 1

            logger.info(f"\n  [{industry_name}] 选股 (净流入Top{n_inflow} + 涨幅Top{n_growth})")

            # 获取行业成分股
            constituents = self._shenwan.get_industry_constituents(industry_code, date)
            if not constituents:
                logger.warning(f"    {industry_name} 无成分股")
                continue

            logger.info(f"    成分股: {len(constituents)} 只")

            # 主力净流入最多的股票
            inflow_stocks = self._factor_service.top_n_by_field(
                field='main_net_in',
                symbols=constituents,
                date=date,
                n=n_inflow,
            )
            logger.info(f"    净流入Top{n_inflow}: {inflow_stocks}")

            # 入选后涨幅最多的股票
            growth_stocks = self._factor_service.top_n_growth(
                symbols=constituents,
                date=date,
                n=n_growth,
                days=growth_days,
            )
            logger.info(f"    涨幅Top{n_growth}: {growth_stocks}")

            # 同行业重叠 → 1.5份，不重叠 → 各1份
            for stock in inflow_stocks:
                if stock in growth_stocks:
                    selected[stock] = 1.5
                    logger.info(f"    ★ {stock}: 同行业重叠 → 1.5份")
                else:
                    selected[stock] = 1.0
            for stock in growth_stocks:
                if stock not in inflow_stocks:
                    selected[stock] = 1.0

        logger.info(f"\n  选股完成: 共 {len(selected)} 只")
        for code, weight in sorted(selected.items()):
            logger.info(f"    {code}: {weight}份")

        return selected

    def _generate_rebalance_orders(
        self,
        selected: Dict[str, float],
        context: Context,
    ) -> List[Order]:
        """生成调仓订单"""
        orders = []
        selected_set = set(selected.keys())
        current_holdings = set(context.positions.keys())

        # 1. 卖出不在新选中集合中的持仓
        for code in current_holdings - selected_set:
            pos = context.positions[code]
            orders.append(Order(
                stock_code=code,
                direction=Direction.SHORT,
                quantity=pos.quantity,
                reason=f"行业排名变化-卖出",
            ))

        # 2. 计算目标金额（等权分配）
        total_weight = sum(selected.values())
        if total_weight <= 0:
            return orders

        # 3. 买入新选中的股票
        to_buy = selected_set - current_holdings
        for code in to_buy:
            weight = selected[code]
            target_value = context.total_value * 0.98 * (weight / total_weight)

            data = context.market_data.get(code)
            if data is None:
                continue

            close = data.get('close', 0)
            if close <= 0:
                continue

            qty = int(target_value / close / 100) * 100
            if qty >= 100:
                orders.append(Order(
                    stock_code=code,
                    direction=Direction.LONG,
                    quantity=qty,
                    reason=f"行业资金流向选股-{weight}份",
                ))

        return orders

    def _get_industry_name(self, industry_code: str) -> str:
        """获取行业名称"""
        if industry_code in self._prev_industry_names:
            return self._prev_industry_names[industry_code]

        industries = self._shenwan.get_sw_industries(level=1)
        if not industries.empty:
            self._prev_industry_names = dict(
                zip(industries['industry_code'], industries['industry_name'])
            )
            return self._prev_industry_names.get(industry_code, industry_code)

        return industry_code
