"""
模拟交易撮合引擎（Paper Trading Engine）

本文件实现 PaperTradingEngine 类，负责单策略账户的模拟撮合与结算：
- 买入/卖出撮合（含佣金、印花税、过户费计算）
- 次日开盘（next_open）订单的资金冻结/解冻
- 每日收盘结算（持仓市值、总资产、日收益率、最大回撤、净值快照）

引擎只负责执行与计算，不调用策略信号；策略调度由 orchestrator.py 完成。

用法:
    from src.paper_trading.engine import PaperTradingEngine
    engine = PaperTradingEngine(db, '3a7b2c01', 'small_cap', 'v2')
    engine.load_or_init_account()
    engine.execute_buy(stock_code='600000.SH', quantity=100, price=10.0, trade_date='2024-01-02')
    engine.settle_daily('2024-01-02', {'600000.SH': 10.2})
"""

from typing import Dict, List, Optional
import logging

from src.data.database import DatabaseManager
from src.engine.types import Position, Direction
from .config import PAPER_TRADING_CONFIG

logger = logging.getLogger(__name__)


class PaperTradingEngine:
    """
    模拟交易撮合引擎 - 单策略账户

    每个策略账户对应一个 Engine 实例，持有内存中的资金与持仓缓存，
    通过 DatabaseManager 持久化到 paper_* 表。

    Parameters
    ----------
    db : DatabaseManager
        数据库管理器
    strategy_id : str
        策略ID（strategy_versions.strategy_id）
    strategy_name : str
        策略名称
    version : str
        策略版本号（如 'v2'）
    config : dict, optional
        费用参数覆盖，默认使用 PAPER_TRADING_CONFIG
    """

    def __init__(
        self,
        db: DatabaseManager,
        strategy_id: str,
        strategy_name: str,
        version: str,
        config: Optional[Dict] = None,
    ):
        self.db = db
        self.strategy_id = strategy_id
        self.strategy_name = strategy_name
        self.version = version

        # 合并默认参数与传入覆盖
        self.config = {**PAPER_TRADING_CONFIG, **(config or {})}

        # 账户内存状态（load_or_init_account 后填充）
        self.initial_capital: float = self.config['initial_capital']
        self.cash: float = self.initial_capital
        self.frozen_cash: float = 0.0
        self.total_value: float = self.initial_capital
        self.peak_value: float = self.initial_capital

        # 持仓内存缓存：{stock_code: Position}
        self.positions: Dict[str, Position] = {}

        self._loaded = False

    # ------------------------------------------------------------------
    # 账户加载与初始化
    # ------------------------------------------------------------------

    def load_or_init_account(self) -> None:
        """
        从数据库加载账户状态；若不存在则创建初始账户。

        首次运行时初始化 cash=initial_capital, total_value=initial_capital。
        后续运行时从 paper_accounts 读取最新状态，并加载 paper_positions。
        """
        account = self.db.get_paper_account(self.strategy_id)
        if account is None:
            # 初始化新账户
            self.cash = self.initial_capital
            self.frozen_cash = 0.0
            self.total_value = self.initial_capital
            self.peak_value = self.initial_capital
            self._save_account()
            logger.info(
                f"[PaperTrading] 初始化账户 {self.strategy_id} ({self.strategy_name} {self.version})"
                f" 初始资金={self.initial_capital:.2f}"
            )
        else:
            self.initial_capital = account['initial_capital']
            self.cash = account['cash']
            self.frozen_cash = account['frozen_cash']
            self.total_value = account['total_value']
            self.peak_value = account['peak_value']

        # 加载持仓
        self.positions = {}
        for row in self.db.get_paper_positions(self.strategy_id):
            # direction 字段 'long'/'short' 转 Direction 枚举
            direction = Direction.LONG if row['direction'] == 'long' else Direction.SHORT
            self.positions[row['stock_code']] = Position(
                stock_code=row['stock_code'],
                direction=direction,
                quantity=row['quantity'],
                entry_price=row['entry_price'],
                entry_date=row['entry_date'],
                highest_price=row['entry_price'],  # 简化：最高价用入场价初始化
            )

        self._loaded = True

    def _save_account(self) -> None:
        """将内存中的账户状态持久化到 paper_accounts 表"""
        self.db.save_paper_account({
            'strategy_id': self.strategy_id,
            'strategy_name': self.strategy_name,
            'version': self.version,
            'initial_capital': self.initial_capital,
            'cash': self.cash,
            'frozen_cash': self.frozen_cash,
            'total_value': self.total_value,
            'peak_value': self.peak_value,
        })

    # ------------------------------------------------------------------
    # 费用计算
    # ------------------------------------------------------------------

    def calc_buy_cost(self, price: float, quantity: int) -> Dict[str, float]:
        """
        计算买入总成本（含佣金 + 过户费，无印花税）。

        Returns
        -------
        dict
            amount: 成交金额 (price*quantity)
            commission: 佣金（万三，最低5元）
            transfer_fee: 过户费（万分之零点一）
            total_cost: 总支出 = amount + commission + transfer_fee
        """
        amount = price * quantity
        commission = max(amount * self.config['commission_rate'], self.config['min_commission'])
        transfer_fee = amount * self.config['transfer_fee_rate']
        total_cost = amount + commission + transfer_fee
        return {
            'amount': amount,
            'commission': commission,
            'transfer_fee': transfer_fee,
            'total_cost': total_cost,
        }

    def calc_sell_fee(self, price: float, quantity: int) -> Dict[str, float]:
        """
        计算卖出费用（佣金 + 印花税 + 过户费）。

        Returns
        -------
        dict
            amount: 成交金额 (price*quantity)
            commission: 佣金（万三，最低5元）
            stamp_duty: 印花税（千一）
            transfer_fee: 过户费
            total_fee: 总费用
            net_proceeds: 净收入 = amount - total_fee
        """
        amount = price * quantity
        commission = max(amount * self.config['commission_rate'], self.config['min_commission'])
        stamp_duty = amount * self.config['stamp_duty_rate']
        transfer_fee = amount * self.config['transfer_fee_rate']
        total_fee = commission + stamp_duty + transfer_fee
        net_proceeds = amount - total_fee
        return {
            'amount': amount,
            'commission': commission,
            'stamp_duty': stamp_duty,
            'transfer_fee': transfer_fee,
            'total_fee': total_fee,
            'net_proceeds': net_proceeds,
        }

    # ------------------------------------------------------------------
    # 撮合执行
    # ------------------------------------------------------------------

    def execute_buy(
        self,
        stock_code: str,
        quantity: int,
        price: float,
        trade_date: str,
        reason: str = '',
        order_id: Optional[int] = None,
    ) -> bool:
        """
        执行买入撮合（已确定成交价）。

        流程：检查资金 -> 扣减现金 -> 建立持仓 -> 写成交记录 -> 保存账户。
        返回 True 成交，False 拒绝（资金不足/已持仓/价格无效）。
        """
        if not self._loaded:
            raise RuntimeError("Engine 未加载账户，请先调用 load_or_init_account()")

        # 校验：A 股买入须 100 股整数倍
        if quantity <= 0 or quantity % 100 != 0:
            logger.debug(f"[PaperTrading] 买入拒绝 {stock_code}: 数量 {quantity} 非 100 整数倍")
            return False

        # 已有持仓则不加仓（与 backtest_engine 一致，暂不支持加仓）
        if stock_code in self.positions:
            logger.debug(f"[PaperTrading] 买入拒绝 {stock_code}: 已有持仓，不支持加仓")
            return False

        if price <= 0:
            return False

        cost = self.calc_buy_cost(price, quantity)
        if cost['total_cost'] > self.cash:
            logger.debug(
                f"[PaperTrading] 买入拒绝 {stock_code}: 资金不足"
                f" (需 {cost['total_cost']:.2f}, 可用 {self.cash:.2f})"
            )
            return False

        # 扣减现金
        self.cash -= cost['total_cost']

        # 建立持仓
        self.positions[stock_code] = Position(
            stock_code=stock_code,
            direction=Direction.LONG,
            quantity=quantity,
            entry_price=price,
            entry_date=trade_date,
            highest_price=price,
        )
        self.db.save_paper_position({
            'strategy_id': self.strategy_id,
            'stock_code': stock_code,
            'direction': 'long',
            'quantity': quantity,
            'entry_price': price,
            'entry_date': trade_date,
            'current_price': price,
            'value': cost['amount'],
        })

        # 写成交流水
        self.db.insert_paper_trade({
            'order_id': order_id,
            'strategy_id': self.strategy_id,
            'stock_code': stock_code,
            'direction': 'long',
            'quantity': quantity,
            'price': price,
            'amount': cost['amount'],
            'commission': cost['commission'],
            'slippage': cost['transfer_fee'],  # 复用 slippage 字段存过户费
            'trade_date': trade_date,
        })

        self._save_account()
        logger.info(
            f"[PaperTrading] 买入成交 {stock_code} {quantity}股 @{price:.2f}"
            f" 成本 {cost['total_cost']:.2f} ({trade_date})"
        )
        return True

    def execute_sell(
        self,
        stock_code: str,
        quantity: int,
        price: float,
        trade_date: str,
        reason: str = '',
        order_id: Optional[int] = None,
    ) -> bool:
        """
        执行卖出撮合（已确定成交价）。

        流程：检查持仓 -> 计算费用与盈亏 -> 增加现金 -> 删除持仓 -> 写成交记录 -> 保存账户。
        返回 True 成交，False 拒绝（无持仓/数量超/价格无效）。
        """
        if not self._loaded:
            raise RuntimeError("Engine 未加载账户，请先调用 load_or_init_account()")

        if stock_code not in self.positions:
            logger.debug(f"[PaperTrading] 卖出拒绝 {stock_code}: 无持仓")
            return False

        position = self.positions[stock_code]
        if quantity <= 0 or quantity > position.quantity:
            logger.debug(
                f"[PaperTrading] 卖出拒绝 {stock_code}: 数量 {quantity} 超过持仓 {position.quantity}"
            )
            return False

        if price <= 0:
            return False

        fee = self.calc_sell_fee(price, quantity)

        # 增加现金（净收入）
        self.cash += fee['net_proceeds']

        # 计算盈亏
        pnl = (price - position.entry_price) * quantity - fee['total_fee']

        # 更新持仓：全部卖出则删除，部分卖出则更新（简化：默认全部平仓）
        if quantity >= position.quantity:
            self.db.delete_paper_position(self.strategy_id, stock_code)
            del self.positions[stock_code]
        else:
            position.quantity -= quantity
            self.db.save_paper_position({
                'strategy_id': self.strategy_id,
                'stock_code': stock_code,
                'direction': 'long',
                'quantity': position.quantity,
                'entry_price': position.entry_price,
                'entry_date': position.entry_date,
                'current_price': price,
                'value': price * position.quantity,
            })

        # 写成交流水
        self.db.insert_paper_trade({
            'order_id': order_id,
            'strategy_id': self.strategy_id,
            'stock_code': stock_code,
            'direction': 'short',  # 卖出记为 short
            'quantity': quantity,
            'price': price,
            'amount': fee['amount'],
            'commission': fee['commission'],
            'slippage': fee['stamp_duty'] + fee['transfer_fee'],  # 复用 slippage 存印花税+过户费
            'trade_date': trade_date,
        })

        self._save_account()
        logger.info(
            f"[PaperTrading] 卖出成交 {stock_code} {quantity}股 @{price:.2f}"
            f" 净收入 {fee['net_proceeds']:.2f} 盈亏 {pnl:.2f} ({trade_date})"
        )
        return True

    # ------------------------------------------------------------------
    # 次日开盘（next_open）订单的资金冻结/解冻
    # ------------------------------------------------------------------

    def freeze_for_buy(
        self,
        stock_code: str,
        quantity: int,
        price: float,
        trade_date: str,
        reason: str = '',
    ) -> Optional[int]:
        """
        为 next_open 买单冻结资金。

        按当日 close 价预估成本，从 cash 转入 frozen_cash。
        返回 order_id（pending 订单已入库），None 表示冻结失败（资金不足）。
        """
        if quantity <= 0 or quantity % 100 != 0:
            return None
        if stock_code in self.positions:
            return None  # 已持仓不重复买入

        cost = self.calc_buy_cost(price, quantity)
        if cost['total_cost'] > self.cash:
            logger.debug(
                f"[PaperTrading] 冻结失败 {stock_code}: 资金不足"
                f" (需 {cost['total_cost']:.2f}, 可用 {self.cash:.2f})"
            )
            return None

        # 冻结资金
        self.cash -= cost['total_cost']
        self.frozen_cash += cost['total_cost']
        self._save_account()

        # 写 pending 订单
        order_id = self.db.insert_paper_order({
            'strategy_id': self.strategy_id,
            'stock_code': stock_code,
            'direction': 'long',
            'quantity': quantity,
            'price_type': 'next_open',
            'reason': reason,
            'status': 'pending',
            'created_date': trade_date,
        })
        logger.info(
            f"[PaperTrading] 冻结买单 {stock_code} {quantity}股 预估成本 {cost['total_cost']:.2f}"
            f" (order_id={order_id}, {trade_date})"
        )
        return order_id

    def execute_pending_buy(
        self,
        order_id: int,
        stock_code: str,
        quantity: int,
        frozen_amount: float,
        open_price: float,
        trade_date: str,
    ) -> bool:
        """
        撮合昨日冻结的 next_open 买单（用今日 open 价成交）。

        流程：解冻资金 -> 按实际 open 价计算成本 -> 补扣或退回差额 -> 建立持仓。
        资金不足补扣时拒绝成交并退回冻结资金（订单标记 rejected）。
        返回 True 成交，False 拒绝。
        """
        if open_price <= 0:
            # 价格无效，退回冻结资金，订单标记 rejected
            self.frozen_cash -= frozen_amount
            self.cash += frozen_amount
            self._save_account()
            self.db.update_paper_order_status(order_id, 'rejected')
            return False

        actual_cost = self.calc_buy_cost(open_price, quantity)

        # 解冻资金
        self.frozen_cash -= frozen_amount

        # 计算差额：实际成本 - 已冻结金额
        diff = actual_cost['total_cost'] - frozen_amount
        if diff > 0:
            # 需要补扣现金
            if diff > self.cash:
                # 资金不足，拒绝成交，退回冻结资金
                self.cash += frozen_amount
                self._save_account()
                self.db.update_paper_order_status(order_id, 'rejected')
                logger.warning(
                    f"[PaperTrading] Pending买单拒绝 {stock_code}: 补扣资金不足"
                    f" (需补 {diff:.2f}, 可用 {self.cash:.2f})"
                )
                return False
            self.cash -= diff
        else:
            # 退回多余冻结资金
            self.cash += (-diff)

        # 建立持仓
        self.positions[stock_code] = Position(
            stock_code=stock_code,
            direction=Direction.LONG,
            quantity=quantity,
            entry_price=open_price,
            entry_date=trade_date,
            highest_price=open_price,
        )
        self.db.save_paper_position({
            'strategy_id': self.strategy_id,
            'stock_code': stock_code,
            'direction': 'long',
            'quantity': quantity,
            'entry_price': open_price,
            'entry_date': trade_date,
            'current_price': open_price,
            'value': actual_cost['amount'],
        })

        # 写成交流水
        self.db.insert_paper_trade({
            'order_id': order_id,
            'strategy_id': self.strategy_id,
            'stock_code': stock_code,
            'direction': 'long',
            'quantity': quantity,
            'price': open_price,
            'amount': actual_cost['amount'],
            'commission': actual_cost['commission'],
            'slippage': actual_cost['transfer_fee'],
            'trade_date': trade_date,
        })

        # 订单标记已成交
        self.db.update_paper_order_status(order_id, 'filled')
        self._save_account()
        logger.info(
            f"[PaperTrading] Pending买单成交 {stock_code} {quantity}股 @{open_price:.2f}"
            f" 实际成本 {actual_cost['total_cost']:.2f} ({trade_date})"
        )
        return True

    def add_pending_sell_order(
        self,
        stock_code: str,
        quantity: int,
        trade_date: str,
        reason: str = '',
    ) -> Optional[int]:
        """
        为 next_open 卖单登记 pending 订单（卖单不需要冻结资金，次日才扣减持仓）。

        返回 order_id，None 表示登记失败（无持仓）。
        """
        if stock_code not in self.positions:
            return None
        order_id = self.db.insert_paper_order({
            'strategy_id': self.strategy_id,
            'stock_code': stock_code,
            'direction': 'short',
            'quantity': quantity,
            'price_type': 'next_open',
            'reason': reason,
            'status': 'pending',
            'created_date': trade_date,
        })
        logger.info(
            f"[PaperTrading] 登记Pending卖单 {stock_code} {quantity}股"
            f" (order_id={order_id}, {trade_date})"
        )
        return order_id

    # ------------------------------------------------------------------
    # 每日结算
    # ------------------------------------------------------------------

    def settle_daily(self, trade_date: str, day_close_prices: Dict[str, float]) -> Dict:
        """
        每日收盘结算：更新持仓市值、计算总资产与回撤、写净值快照。

        Parameters
        ----------
        trade_date : str
            交易日 (YYYY-MM-DD)
        day_close_prices : dict
            {stock_code: close_price} 当日收盘价

        Returns
        -------
        dict
            结算结果快照
        """
        if not self._loaded:
            raise RuntimeError("Engine 未加载账户")

        # 计算持仓市值，并更新持仓表的 current_price/value
        position_value = 0.0
        for stock_code, position in self.positions.items():
            close_price = day_close_prices.get(stock_code, position.entry_price)
            if close_price > 0:
                # 更新最高价（用于 ATR 动态止盈，此处简化记录）
                if close_price > position.highest_price:
                    position.highest_price = close_price
                # 更新数据库持仓的现价与市值
                self.db.save_paper_position({
                    'strategy_id': self.strategy_id,
                    'stock_code': stock_code,
                    'direction': 'long',
                    'quantity': position.quantity,
                    'entry_price': position.entry_price,
                    'entry_date': position.entry_date,
                    'current_price': close_price,
                    'value': close_price * position.quantity,
                })
            position_value += close_price * position.quantity

        # 计算总资产
        prev_total = self.total_value
        self.total_value = self.cash + self.frozen_cash + position_value

        # 更新峰值与回撤
        if self.total_value > self.peak_value:
            self.peak_value = self.total_value
        max_drawdown = (self.peak_value - self.total_value) / self.peak_value if self.peak_value > 0 else 0.0

        # 日收益率
        daily_return = (self.total_value - prev_total) / prev_total if prev_total > 0 else 0.0

        # 写净值快照
        self.db.insert_paper_snapshot({
            'strategy_id': self.strategy_id,
            'trade_date': trade_date,
            'cash': self.cash,
            'position_value': position_value,
            'total_value': self.total_value,
            'daily_return': daily_return,
            'max_drawdown': max_drawdown,
        })

        # 保存账户
        self._save_account()

        logger.info(
            f"[PaperTrading] 结算 {self.strategy_id} {trade_date}"
            f" 现金={self.cash:.2f} 持仓={position_value:.2f}"
            f" 总资产={self.total_value:.2f} 日收益={daily_return:.2%} 回撤={max_drawdown:.2%}"
        )
        return {
            'trade_date': trade_date,
            'cash': self.cash,
            'frozen_cash': self.frozen_cash,
            'position_value': position_value,
            'total_value': self.total_value,
            'daily_return': daily_return,
            'max_drawdown': max_drawdown,
        }

    # ------------------------------------------------------------------
    # 市场过滤辅助（参考 backtest_engine 实现）
    # ------------------------------------------------------------------

    def is_limit_up(self, close: float, pre_close: float) -> bool:
        """判断涨停：close >= pre_close * limit_up_ratio"""
        if pre_close <= 0:
            return False
        return close >= pre_close * self.config['limit_up_ratio']

    def is_limit_down(self, close: float, pre_close: float) -> bool:
        """判断跌停：close <= pre_close * limit_down_ratio"""
        if pre_close <= 0:
            return False
        return close <= pre_close * self.config['limit_down_ratio']
