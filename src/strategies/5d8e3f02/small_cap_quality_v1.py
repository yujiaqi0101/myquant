"""
小盘股质量策略

策略逻辑：
1. 每月最后一个交易日：卖出所有持仓
2. 每月第一个交易日：按以下条件选股
   - 质量因子过滤：ROE > 5%, PB < 3, 营收增长 > 0
   - 按流通市值从小到大排序，取前N只（小盘股优先）
3. 持仓20只，均仓买入
4. 股票池：全市场，剔除ST/退市/次新股
5. 每日止损/止盈检查（8%/25%）

数据来源：FactorService（本地数据库）
"""

import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Optional

from src.engine import BaseStrategy, register_strategy
from src.engine.types import Order, Direction, Context
from src.engine.exit_checker import ExitChecker

logger = logging.getLogger(__name__)


@register_strategy
class SmallCapQualityStrategy(BaseStrategy):
    """
    小盘股质量策略

    买入逻辑：每月第一个交易日，质量因子过滤后按流通市值升序选股
    卖出逻辑：每月最后一个交易日，清仓所有持仓
    风控逻辑：每日检查止损（-8%）和止盈（+25%）

    参数：
    - n_positions: 持仓数量（默认20）
    - roe_threshold: ROE最低阈值（默认0.05，即5%）
    - pb_threshold: PB最高阈值（默认3.0）
    - revenue_growth_threshold: 营收增长最低阈值（默认0）
    - max_circ_mv: 流通市值上限（亿元，默认500）
    - stop_loss: 止损比例（默认0.08，即-8%）
    - take_profit: 止盈比例（默认0.25，即+25%）
    """

    name = "small_cap_quality"
    description = "小盘股质量策略 - 质量因子过滤+流通市值排序，月度调仓，带止损止盈"

    default_params = {
        **BaseStrategy.default_params,
        'n_positions': 20,                    # 持仓数量
        'roe_threshold': 0.05,                # ROE > 5%
        'pb_threshold': 3.0,                  # PB < 3
        'revenue_growth_threshold': 0,        # 营收增长 > 0
        'max_circ_mv': 500,                   # 流通市值上限（亿元）
        'stop_loss': 0.08,                    # 止损 -8%
        'take_profit': 0.25,                  # 止盈 +25%
    }

    def on_init(self, context: Context):
        """策略初始化"""
        # 从 full_data 提取交易日历（仅在 on_init 阶段可用）
        all_dates = context.full_data.index.get_level_values(0).unique()
        self._trade_calendar = sorted([str(d)[:10] for d in all_dates])

        # 初始化因子服务（从本地数据库获取基本面数据）
        from src.factors.factor_service import FactorService
        self._factor_service = FactorService(data_source='database')

        # 初始化止损止盈检查器
        self._exit_checker = ExitChecker({
            'stop_loss': self.params.get('stop_loss', 0),
            'take_profit': self.params.get('take_profit', 0),
        })

        logger.info("SmallCapQualityStrategy 初始化完成，交易日历 %d 天", len(self._trade_calendar))

    def exit_checker(self, context: Context, position: 'Position'):
        """每日止损止盈检查"""
        return self._exit_checker.check_all(context, position)

    def _is_first_trading_day_of_month(self, date: str) -> bool:
        """
        判断是否为某月的第一个交易日

        通过交易日历中前一个交易日的月份对比来判断，无需外部状态。
        """
        try:
            idx = self._trade_calendar.index(date)
        except ValueError:
            return False

        if idx == 0:
            return True

        prev_date = self._trade_calendar[idx - 1]
        return prev_date[:7] != date[:7]

    def _is_last_trading_day_of_month(self, date: str) -> bool:
        """
        判断是否为某月的最后一个交易日

        通过交易日历中下一个交易日的月份对比来判断。
        """
        try:
            idx = self._trade_calendar.index(date)
        except ValueError:
            return False

        if idx == len(self._trade_calendar) - 1:
            return True

        next_date = self._trade_calendar[idx + 1]
        return next_date[:7] != date[:7]

    def _cleanup_stuck_positions(self, context: Context) -> List[Order]:
        """
        清理遗留的"死仓"（上月跌停未卖出的持仓）

        月初建仓前先尝试清掉残留持仓，避免永远留在账户中。
        """
        orders = []
        for code in list(context.positions.keys()):
            pos = context.positions[code]
            orders.append(Order(
                stock_code=code,
                direction=Direction.SHORT,
                quantity=pos.quantity,
                reason=f"月初清理遗留持仓"
            ))
        if orders:
            logger.info(f"  清理遗留持仓: {len(orders)} 只")
        return orders

    def _filter_quality_stocks(
        self,
        date: str,
        available_codes: List[str],
    ) -> List[str]:
        """
        质量因子过滤

        条件：
        - ROE > roe_threshold
        - PB < pb_threshold
        - 营收增长 > revenue_growth_threshold

        Returns
        -------
        List[str]
            通过过滤的股票代码列表
        """
        roe_threshold = self.params.get('roe_threshold', 0.05)
        pb_threshold = self.params.get('pb_threshold', 3.0)
        revenue_growth_threshold = self.params.get('revenue_growth_threshold', 0)

        # 获取因子数据
        roe_data = self._factor_service.get_factor('roe', date)
        pb_data = self._factor_service.get_factor('pb', date)
        revenue_data = self._factor_service.get_factor('revenue_growth_q', date)

        if not roe_data or not pb_data:
            logger.warning(f"  质量因子数据为空，跳过过滤")
            return available_codes

        qualified = []

        for code in available_codes:
            # ROE 过滤
            roe = roe_data.get(code, float('nan'))
            if pd.isna(roe) or roe <= roe_threshold:
                continue

            # PB 过滤
            pb = pb_data.get(code, float('nan'))
            if pd.isna(pb) or pb <= 0 or pb >= pb_threshold:
                continue

            # 营收增长过滤（可选）
            if revenue_data:
                revenue_growth = revenue_data.get(code, float('nan'))
                if pd.isna(revenue_growth) or revenue_growth <= revenue_growth_threshold:
                    continue

            qualified.append(code)

        logger.info(f"  质量因子过滤: {len(available_codes)} -> {len(qualified)} 只")
        return qualified

    def _select_small_cap_stocks(
        self,
        date: str,
        candidate_codes: List[str],
    ) -> List[str]:
        """
        按流通市值从小到大排序选股

        Parameters
        ----------
        date : str
            查询日期
        candidate_codes : List[str]
            候选股票列表

        Returns
        -------
        List[str]
            选中的股票代码列表
        """
        n_positions = self.params.get('n_positions', 20)
        max_circ_mv = self.params.get('max_circ_mv', 500)  # 亿元

        # 获取流通市值数据（单位：元，需转换为亿元）
        circ_mv_data = self._factor_service.get_factor('circ_mv', date, stock_pool=candidate_codes)

        if not circ_mv_data:
            logger.warning(f"  流通市值数据为空，跳过选股")
            return []

        # 过滤：流通市值上限
        max_mv_yuan = max_circ_mv * 1e8  # 亿元 -> 元
        filtered = {
            code: mv for code, mv in circ_mv_data.items()
            if not pd.isna(mv) and mv > 0 and mv <= max_mv_yuan
        }

        if not filtered:
            logger.warning(f"  无股票满足流通市值条件（< {max_circ_mv}亿）")
            return []

        # 按流通市值升序排序（小盘股优先）
        sorted_stocks = sorted(filtered.items(), key=lambda x: x[1])
        selected = [code for code, _ in sorted_stocks[:n_positions]]

        # 打印选中股票的流通市值信息
        if selected:
            mv_min = filtered[selected[0]] / 1e8
            mv_max = filtered[selected[-1]] / 1e8
            logger.info(f"  流通市值选股: {len(filtered)} 只候选 -> 选中 {len(selected)} 只")
            logger.info(f"  流通市值范围: {mv_min:.1f}亿 ~ {mv_max:.1f}亿")

        return selected

    def on_bar(self, context: Context) -> List[Order]:
        """每日调用"""
        date = str(context.date)[:10]
        orders = []

        # ---- 月末：最后一个交易日，清仓所有持仓 ----
        if self._is_last_trading_day_of_month(date):
            if context.positions:
                logger.info(f"\n{date} [月末清仓]")
                for code in list(context.positions.keys()):
                    pos = context.positions[code]
                    orders.append(Order(
                        stock_code=code,
                        direction=Direction.SHORT,
                        quantity=pos.quantity,
                        reason=f"月末清仓"
                    ))
                logger.info(f"  清仓 {len(orders)} 只股票")
            return orders

        # ---- 月初：第一个交易日，选股买入 ----
        if self._is_first_trading_day_of_month(date):
            logger.info(f"\n{date} [月初建仓]")

            # 第一步：清理上月遗留的死仓（跌停未卖出的持仓）
            cleanup_orders = self._cleanup_stuck_positions(context)
            orders.extend(cleanup_orders)

            # 获取当日可交易股票
            available_codes = list(context.market_data.keys())
            if not available_codes:
                return orders

            # 第二步：质量因子过滤
            qualified = self._filter_quality_stocks(date, available_codes)
            if not qualified:
                logger.warning(f"  质量因子过滤后无股票，跳过")
                return orders

            # 第三步：按流通市值排序选股
            selected = self._select_small_cap_stocks(date, qualified)
            if not selected:
                logger.warning(f"  选股结果为空，跳过")
                return orders

            # 均仓买入
            n_positions = self.params.get('n_positions', 20)
            position_size = 0.98 / n_positions
            target_value_per_stock = context.total_value * position_size

            for code in selected:
                data = context.market_data.get(code)
                if data is None:
                    continue

                close = data.get('close', 0)
                if close <= 0:
                    continue

                # 计算目标数量（基于目标金额）
                qty = int(target_value_per_stock / close / 100) * 100

                if qty >= 100:
                    orders.append(Order(
                        stock_code=code,
                        direction=Direction.LONG,
                        quantity=qty,
                        reason=f"小盘股质量选股买入"
                    ))

            logger.info(f"  买入 {len(orders) - len(cleanup_orders)} 只股票")

            return orders

        return orders
