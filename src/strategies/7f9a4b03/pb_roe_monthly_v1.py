"""
PB+ROE 月度轮动策略

策略逻辑：
1. 每月最后一个交易日：卖出所有持仓
2. 每月第一个交易日：全市场按市净率(PB)排名 + ROE排名，买入综合排名前10%的股票（均仓）
3. 持仓上限100只

数据来源：FactorService（支持多数据源切换）
"""

import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Optional

from src.engine import BaseStrategy, register_strategy
from src.engine.types import Order, Direction, Context

logger = logging.getLogger(__name__)


@register_strategy
class PbRoeMonthlyStrategy(BaseStrategy):
    """
    PB+ROE 月度轮动策略

    买入逻辑：每月第一个交易日，按 PB 排名 + ROE 排名综合选股
    卖出逻辑：每月最后一个交易日，清仓所有持仓

    参数：
    - top_pct: 买入排名前 N% 的股票（默认10%）
    - max_positions: 最大持仓数量（默认100）
    - pb_rank_asc: PB排名方向，True=PB越小排名越高（默认True）
    - roe_rank_asc: ROE排名方向，False=ROE越大排名越高（默认False）
    """

    name = "pb_roe_monthly"
    description = "PB+ROE月度轮动策略 - 月末清仓，月初按PB和ROE综合排名选股买入"

    default_params = {
        **BaseStrategy.default_params,
        'top_pct': 10,           # 买入前10%
        'max_positions': 100,    # 最大持仓100只
        'pb_rank_asc': True,     # PB越小越好
        'roe_rank_asc': False,   # ROE越大越好
        'stop_loss': 0,          # 关闭止损（0表示不启用）
        'take_profit': 0,        # 关闭止盈（0表示不启用）
        'trailing_stop': 0,      # 不使用ATR动态止盈
        'max_holding_days': 0,   # 关闭持仓天数限制（0表示不启用）
    }

    def on_init(self, context: Context):
        """策略初始化"""
        self._prev_month = None
        self._is_first_month = True
        # 初始化因子服务（基本面策略强制使用 eastmoney 数据源）
        from src.factors.factor_service import FactorService
        self._factor_service = FactorService(data_source='eastmoney')
        logger.info("PbRoeMonthlyStrategy 初始化完成")

    def _is_first_trading_day_of_month(self, date: str) -> bool:
        """判断是否为某月的第一个交易日"""
        month = date[:7]  # YYYY-MM
        if month == self._prev_month:
            return False
        return True

    def _is_last_trading_day_of_month(self, date: str, context: Context) -> bool:
        """判断是否为某月的最后一个交易日"""
        # 获取交易日历
        all_trade_dates = context.full_data.index.get_level_values(0).unique()
        all_trade_dates = sorted([str(d)[:10] for d in all_trade_dates])
        
        try:
            idx = all_trade_dates.index(date)
        except ValueError:
            return False

        # 如果是最后一天，或者下一天是新的月份
        if idx == len(all_trade_dates) - 1:
            return True

        next_date = all_trade_dates[idx + 1]
        if next_date[:7] != date[:7]:
            return True

        return False

    def on_bar(self, context: Context) -> List[Order]:
        """每日调用"""
        date = str(context.date)[:10]
        current_month = date[:7]
        orders = []

        # ---- 月末：最后一个交易日，清仓所有持仓 ----
        if self._is_last_trading_day_of_month(date, context):
            if context.positions:
                logger.info(f"\n{date} [月末清仓]")
                # 卖出所有持仓
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

            # 获取当日可交易股票
            available_codes = list(context.market_data.keys())
            if not available_codes:
                return orders

            # 使用 FactorService 获取 PB+ROE 综合排名
            max_positions = self.params.get('max_positions', 100)
            top_pct = self.params.get('top_pct', 10)
            
            # 获取综合排名（全市场范围内）
            combined_ranks = self._factor_service.combined_rank(
                factor_names=['pb', 'roe'],
                date=date,
                directions=[True, False],  # PB升序(越小越好), ROE降序(越大越好)
                stock_pool=None,  # 全市场排名
            )
            
            if not combined_ranks:
                logger.warning(f"  无法获取因子排名，跳过")
                self._prev_month = current_month
                return orders

            # 筛选出在股票池中的股票
            pool_codes = set(available_codes)
            pool_ranks = {code: rank for code, rank in combined_ranks.items() if code in pool_codes}
            
            if not pool_ranks:
                logger.warning(f"  无股票池内排名数据，跳过")
                self._prev_month = current_month
                return orders

            # 取前 top_pct%
            n_select = max(1, int(len(pool_ranks) * top_pct / 100))
            n_select = min(n_select, max_positions)
            
            # 按综合排名排序，取前N
            sorted_stocks = sorted(pool_ranks.items(), key=lambda x: x[1])
            selected = [code for code, _ in sorted_stocks[:n_select]]
            
            logger.info(f"  选股完成: 全市场 {len(combined_ranks)} 只 -> 股票池内 {len(pool_ranks)} 只 -> 选中 {len(selected)} 只（前 {top_pct}%）")

            # 均仓买入
            position_size = 0.98 / max_positions  # 均仓
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
                        reason=f"PB+ROE选股买入"
                    ))

            logger.info(f"  买入 {len(orders)} 只股票")

            self._prev_month = current_month
            return orders

        return orders
