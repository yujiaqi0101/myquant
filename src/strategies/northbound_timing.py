"""
北向资金择时策略

核心逻辑：
1. 每日获取北向资金净流入数据
2. 使用滚动窗口计算Z-Score（避免未来函数）
3. Z-Score > upper_threshold: 生成买入信号
4. Z-Score < lower_threshold: 生成卖出信号
5. 信号次日开盘价执行（避免偷价）

设计原则：
- 无未来函数：所有计算基于历史数据
- 满仓/空仓：简化仓位管理
- 信号延迟：T日信号，T+1日执行

参考：视频中的北向资金择时案例（2014.11-2021.6，年化24%）
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

import pandas as pd

from src.engine import BaseStrategy, register_strategy
from src.engine.types import Order, Direction, Context
from src.factors.northbound_factor import NorthboundCapitalFactor, NorthboundFactorProvider

logger = logging.getLogger(__name__)


@register_strategy
class NorthboundTimingStrategy(BaseStrategy):
    """
    北向资金择时策略

    基于北向资金净流入的滚动窗口Z-Score生成买卖信号。
    当北向资金显著流入时看多，显著流出时看空。

    Parameters
    ----------
    window : int
        滚动窗口天数（默认20）
    upper_threshold : float
        看多阈值（Z-Score，默认1.0）
    lower_threshold : float
        看空阈值（Z-Score，默认-1.0）
    index_code : str
        跟踪的指数代码（默认000300.SH，沪深300）
    execution_price : str
        执行价格类型（默认next_open，次日开盘价）

    信号逻辑：
    - Z-Score > upper_threshold: 买入信号（满仓）
    - Z-Score < lower_threshold: 卖出信号（空仓）
    - 其他: 维持当前仓位
    """

    name = "northbound_timing"
    description = "北向资金择时策略 - 基于滚动窗口Z-Score生成买卖信号"

    default_params = {
        **BaseStrategy.default_params,
        'window': 20,                    # 滚动窗口天数
        'upper_threshold': 1.0,          # 看多阈值（Z-Score）
        'lower_threshold': -1.0,         # 看空阈值（Z-Score）
        'index_code': '000300.SH',       # 跟踪指数（沪深300）
        'execution_price': 'next_open',  # 次日开盘价执行（避免偷价）
        # 关闭引擎级出场检查
        'stop_loss': 0,                  # 关闭止损
        'take_profit': 0,                # 关闭止盈
        'trailing_stop': 0,              # 关闭ATR动态止盈
        'max_holding_days': 0,           # 关闭持仓天数限制
    }

    def on_init(self, context: Context):
        """
        策略初始化

        加载历史北向资金数据并预计算因子值
        """
        window = self.params.get('window', 20)
        upper = self.params.get('upper_threshold', 1.0)
        lower = self.params.get('lower_threshold', -1.0)

        # 初始化因子计算器
        self._factor = NorthboundCapitalFactor(
            window=window,
            upper_threshold=upper,
            lower_threshold=lower,
        )

        # 初始化因子数据提供者
        self._provider = NorthboundFactorProvider()

        # 当前信号状态（0=空仓，1=满仓）
        self._current_position = 0

        # 预加载历史因子数据
        self._load_factor_data(context)

        logger.info(f"NorthboundTimingStrategy 初始化完成")
        logger.info(f"  窗口: {window}天, 看多阈值: {upper}, 看空阈值: {lower}")

    def _load_factor_data(self, context: Context):
        """预加载历史因子数据"""
        # 获取回测日期范围
        all_dates = context.full_data.index.get_level_values(0).unique()
        if len(all_dates) == 0:
            return

        start_date = str(all_dates[0])[:10]
        end_date = str(all_dates[-1])[:10]

        # 额外加载预热期数据
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        warmup_start = start_dt - timedelta(days=self.params['window'] * 2)
        warmup_start_str = warmup_start.strftime('%Y-%m-%d')

        try:
            self._factor_df = self._provider.get_factor_data(
                start_date=warmup_start_str,
                end_date=end_date,
                window=self.params['window'],
                upper_threshold=self.params['upper_threshold'],
                lower_threshold=self.params['lower_threshold'],
            )

            if not self._factor_df.empty:
                # 转换为字典格式便于查询
                self._factor_dict = {}
                for _, row in self._factor_df.iterrows():
                    date_str = row['date'].strftime('%Y-%m-%d') if isinstance(row['date'], pd.Timestamp) else str(row['date'])[:10]
                    self._factor_dict[date_str] = row.to_dict()

                logger.info(f"  因子数据加载完成: {len(self._factor_dict)} 个交易日")
            else:
                self._factor_dict = {}
                logger.warning("  未获取到因子数据")

        except Exception as e:
            logger.error(f"  因子数据加载失败: {e}")
            self._factor_dict = {}

    def on_bar(self, context: Context) -> List[Order]:
        """
        每日交易逻辑

        根据北向资金因子信号生成买卖订单
        """
        orders = []
        date = str(context.date)[:10]

        # 获取当日因子值
        factor_data = self._factor_dict.get(date)
        if factor_data is None:
            logger.warning(f"{date}: 无因子数据，跳过")
            return orders

        signal = factor_data.get('signal', 0)
        z_score = factor_data.get('z_score', 0)
        net_inflow = factor_data.get('net_inflow', 0)

        # 记录日志
        logger.info(f"\n{date} [北向资金信号]")
        logger.info(f"  净流入: {net_inflow:.2f}亿元, Z-Score: {z_score:.2f}, 信号: {signal}")

        # 生成交易信号
        if signal == 1 and self._current_position == 0:
            # 看多信号，买入
            logger.info(f"  → 买入信号（Z-Score {z_score:.2f} > {self.params['upper_threshold']}）")
            orders.extend(self._buy(context))
            self._current_position = 1

        elif signal == -1 and self._current_position == 1:
            # 看空信号，卖出
            logger.info(f"  → 卖出信号（Z-Score {z_score:.2f} < {self.params['lower_threshold']}）")
            orders.extend(self._sell(context))
            self._current_position = 0

        else:
            # 维持当前仓位
            action = "持仓" if self._current_position == 1 else "空仓"
            logger.info(f"  → 维持{action}")

        return orders

    def _buy(self, context: Context) -> List[Order]:
        """生成买入订单（满仓）"""
        orders = []

        # 获取指数ETF代码
        index_code = self.params.get('index_code', '000300.SH')

        # 检查是否已有持仓
        if index_code in context.positions:
            logger.info(f"  已有持仓，不重复买入")
            return orders

        # 计算买入金额（满仓）
        available_cash = context.cash
        if available_cash <= 0:
            logger.warning(f"  可用资金不足: {available_cash}")
            return orders

        # 获取当前价格
        data = context.market_data.get(index_code)
        if data is None:
            logger.warning(f"  无法获取 {index_code} 行情数据")
            return orders

        price = data.get('close', 0)
        if price <= 0:
            logger.warning(f"  无效价格: {price}")
            return orders

        # 计算买入数量（考虑手续费）
        commission_rate = self.params.get('commission_rate', 0.0003)
        max_amount = available_cash / (1 + commission_rate)
        quantity = int(max_amount / price / 100) * 100  # 向下取整到100股

        if quantity < 100:
            logger.warning(f"  可买数量不足: {quantity}")
            return orders

        orders.append(Order(
            stock_code=index_code,
            direction=Direction.LONG,
            quantity=quantity,
            reason=f"北向资金看多信号（Z-Score触发）"
        ))

        logger.info(f"  买入 {index_code}: {quantity}股 @ {price:.2f}")
        return orders

    def _sell(self, context: Context) -> List[Order]:
        """生成卖出订单（清仓）"""
        orders = []

        # 获取指数ETF代码
        index_code = self.params.get('index_code', '000300.SH')

        # 检查是否有持仓
        if index_code not in context.positions:
            logger.info(f"  无持仓，无需卖出")
            return orders

        position = context.positions[index_code]
        quantity = position.quantity

        if quantity <= 0:
            logger.warning(f"  持仓数量无效: {quantity}")
            return orders

        orders.append(Order(
            stock_code=index_code,
            direction=Direction.SHORT,
            quantity=quantity,
            reason=f"北向资金看空信号（Z-Score触发）"
        ))

        logger.info(f"  卖出 {index_code}: {quantity}股")
        return orders

    def on_exit(self, context: Context) -> List[Order]:
        """
        策略结束时的处理

        清仓所有持仓
        """
        orders = []
        index_code = self.params.get('index_code', '000300.SH')

        if index_code in context.positions:
            position = context.positions[index_code]
            orders.append(Order(
                stock_code=index_code,
                direction=Direction.SHORT,
                quantity=position.quantity,
                reason="策略结束清仓"
            ))
            logger.info(f"策略结束，清仓 {index_code}: {position.quantity}股")

        return orders
