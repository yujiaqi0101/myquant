"""
小市值策略 — myquant框架版
=========================

基于东财掘金【小市值优化策略V2(异动止盈)】改写适配myquant统一回测框架。

策略逻辑：
1. 每月第一个交易日：六步选股(市值→流动性→波动率/动量→行业分散) → 卖出非目标 → 买入新目标
2. 每日：异动检测+移动止盈、个股止损(10%)
3. 风控：净值回撤降仓、中证1000 MA60趋势过滤

数据来源：FactorService（东财掘金API） + market_data
"""

import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Set, Tuple
from collections import defaultdict

from src.engine import BaseStrategy, register_strategy
from src.engine.types import Order, Direction, Context, Position
from src.engine.exit_checker import ExitChecker, ExitCheckResult

logger = logging.getLogger(__name__)


@register_strategy
class SmallCapStrategy(BaseStrategy):
    """
    小市值策略（东财掘金版改写）

    买入逻辑：每月第一个交易日，六步筛选后等权买入
    卖出逻辑：非目标持仓卖出(重叠保留)、异动止盈、止损

    参数：
    - top_n: 持仓数量(默认30)
    - min_market_cap: 市值下限/亿(默认15)
    - max_market_cap: 市值上限/亿(默认200)
    - min_turn_rate: 最低换手率%(默认1.0)
    - min_daily_amount: 最低日均成交额/万元(默认500)
    - max_20d_volatility: 20日波动率上限(默认0.05)
    - min_20d_return: 20日涨幅下限(默认-0.10)
    - max_same_industry: 同行业最大持仓(默认3)
    - min_listed_days: 最少上市天数(默认60)

    风控参数：
    - dd_reduce: 减仓回撤阈值(默认0.10=10%)
    - dd_clear: 清仓回撤阈值(默认0.20=20%)
    - reduce_ratio: 减仓比例(默认0.50)
    - recover_threshold: 恢复满仓净值(默认0.90)
    - use_market_trend: 启用市场趋势过滤(默认True)
    - market_index: 趋势参考指数(默认000852.SH=中证1000)
    - market_ma_period: 均线周期(默认60)
    - below_ma_factor: 均线下方仓位系数(默认0.75)

    异动止盈参数：
    - surge_lookback: 异动检测回溯天数(默认5)
    - surge_threshold: 5日涨幅阈值(默认0.25=25%)
    - surge_ratio_threshold: 加速比阈值(默认0.60)
    - surge_trend_lookback: 趋势对比窗口(默认20)
    - trailing_stop_pct: 移动止盈回落比例(默认0.05=5%)
    - surge_min_hold_days: 最低持有天数(默认5)
    - stop_loss: 个股止损比例(默认0.10=10%)
    """

    name = "small_cap"
    description = (
        "小市值策略 — 六步选股(市值/流动性/波动率/动量/行业分散)"
        " + 异动止盈 + 净值风控 + 市场趋势过滤，月度调仓"
    )

    default_params = {
        **BaseStrategy.default_params,
        # 选股参数
        'top_n': 30,
        'min_market_cap': 15.0,            # 亿
        'max_market_cap': 200.0,            # 亿
        'min_turn_rate': 1.0,               # %
        'min_daily_amount': 500.0,          # 万元
        'max_20d_volatility': 0.05,
        'min_20d_return': -0.10,
        'max_same_industry': 3,
        'min_listed_days': 60,
        # 风控参数
        'dd_reduce': 0.10,
        'dd_clear': 0.20,
        'reduce_ratio': 0.50,
        'recover_threshold': 0.90,
        'use_market_trend': True,
        'market_index': '000852.SH',        # 中证1000
        'market_ma_period': 60,
        'below_ma_factor': 0.75,
        # 异动止盈参数
        'surge_lookback': 5,
        'surge_threshold': 0.25,
        'surge_ratio_threshold': 0.60,
        'surge_trend_lookback': 20,
        'trailing_stop_pct': 0.05,
        'surge_min_hold_days': 5,
        # 个股止损
        'stop_loss': 0.10,
    }

    # ================================================================
    # 初始化
    # ================================================================

    def on_init(self, context: Context):
        """策略初始化"""
        from src.factors.factor_service import FactorService

        # 交易日历
        all_dates = context.full_data.index.get_level_values(0).unique()
        self._trade_calendar = sorted([str(d)[:10] for d in all_dates])

        # 因子服务（东财数据源）
        self._factor_service = FactorService(data_source='eastmoney')

        # 止损检查器
        self._exit_checker = ExitChecker({
            'stop_loss': self.params.get('stop_loss', 0.10),
            'take_profit': 0,      # 不使用固定止盈，由异动止盈替代
            'trailing_stop': 0,
            'max_holding_days': 0,
        })

        # 状态变量
        self._prev_month = None           # 上次调仓月份
        self._pending_targets: List[str] = []  # 本月目标股票
        self._peak_nav = 1.0              # 历史最高净值
        self._risk_mode = "normal"        # normal / reduced / cleared

        # 价格缓冲区: {stock_code: [price1, price2, ...]} 最近30天收盘价
        self._price_buffer: Dict[str, List[float]] = defaultdict(list)
        self._price_buffer_maxlen = 35    # 保留最多35天(20日窗口+5日异动+安全余量)

        # 指数价格缓冲区 (中证1000)
        self._index_prices: List[float] = []

        # 异动止盈状态
        self._entry_info: Dict[str, dict] = {}    # {symbol: {entry_date, entry_price}}
        self._surge_peaks: Dict[str, float] = {}  # {symbol: peak_price}
        self._surge_mode: Set[str] = set()        # 异动监控中的股票
        self._surge_sold_history: Dict[str, str] = {}  # 本月已止盈卖出
        self._surge_total_count: int = 0               # 累计异动止盈次数(不清零)

        # 预加载指数数据
        self._preload_index_data(context)

        # 预热价格缓冲区（从warmup数据填充，避免首月波动率过滤失效）
        self._warmup_price_buffer(context)

        logger.info(
            "SmallCapStrategy 初始化完成 | 交易日历%d天 | "
            "持仓%d只 | 市值%.0f~%.0f亿 | 换手>=%.1f%% | 波动<%.0f%% | "
            "异动止盈:%d日>%.0f%% 加速比>%.0f%% 回落%.0f%%",
            len(self._trade_calendar), self.params['top_n'],
            self.params['min_market_cap'], self.params['max_market_cap'],
            self.params['min_turn_rate'], self.params['max_20d_volatility'] * 100,
            self.params['surge_lookback'], self.params['surge_threshold'] * 100,
            self.params['surge_ratio_threshold'] * 100,
            self.params['trailing_stop_pct'] * 100,
        )

    def _preload_index_data(self, context: Context):
        """从full_data预加载中证1000指数收盘价"""
        index_code = self.params.get('market_index', '000852.SH')
        full_data = context.full_data

        if full_data is not None and index_code in full_data.index.get_level_values(1):
            idx_data = full_data.xs(index_code, level='stock_code')
            self._index_prices = idx_data['close'].astype(float).tolist()
            logger.info(f"  预加载 {index_code} 指数数据: {len(self._index_prices)} 天")

    def _warmup_price_buffer(self, context: Context):
        """从full_data预热价格缓冲区，避免首月波动率/动量过滤无历史数据"""
        full_data = context.full_data
        if full_data is None or full_data.empty:
            return

        maxlen = self._price_buffer_maxlen
        # 按股票分组取最近N个收盘价
        grouped = full_data.groupby(level='stock_code')['close']
        count = 0
        for code, series in grouped:
            prices = series.astype(float).dropna().tolist()
            if len(prices) >= 5:  # 至少需要一些数据
                self._price_buffer[code] = prices[-maxlen:]
                count += 1
        logger.info(f"  预热价格缓冲区: {count} 只股票")

    # ================================================================
    # 每日调用
    # ================================================================

    def on_bar(self, context: Context) -> List[Order]:
        """每日调用"""
        date = str(context.date)[:10]
        current_month = date[:7]
        orders: List[Order] = []

        # ---- 更新价格缓冲区 ----
        self._update_price_buffer(context)

        # ---- Step 1: 异动检测 + 移动止盈 (每日优先) ----
        surge_orders = self._check_surge_stop(context, date)
        orders.extend(surge_orders)

        # 获取被止盈卖出的股票（本月不重新买入）
        surge_sold_today = {o.stock_code for o in surge_orders}

        # ---- Step 2: 月度调仓 ----
        if self._is_first_trading_day_of_month(date):
            logger.info("\n%s [月度调仓 #%d]", date,
                        getattr(self, '_rebalance_count', 0) + 1)
            self._rebalance_count = getattr(self, '_rebalance_count', 0) + 1

            # 2a. 选股
            targets = self._select_targets(context, date)
            self._pending_targets = targets

            # 2b. 卖出非目标持仓（重叠保留，减少交易成本）
            sell_orders = self._sell_non_targets(context, targets, surge_sold_today)
            orders.extend(sell_orders)

            # 2c. 买入新目标（等权）
            buy_orders = self._buy_targets(context, targets, date)
            orders.extend(buy_orders)

            self._prev_month = current_month
            # 新月开始，清理止盈历史
            self._surge_sold_history.clear()

        return orders

    # ================================================================
    # 出场检查（引擎每日对每个持仓调用）
    # ================================================================

    def exit_checker(self, context: Context, position: Position) -> Optional[ExitCheckResult]:
        """个股止损检查（异动止盈在on_bar中处理）"""
        # 标准止损检查
        result = self._exit_checker.check_all(context, position)
        if result is not None:
            return result

        # 异动止盈的股票：如果已在surge_mode中触发卖出，不再重复
        # （surge止盈在on_bar中执行，这里只做标准止损）
        return None

    # ================================================================
    # 交易日判断
    # ================================================================

    def _is_first_trading_day_of_month(self, date: str) -> bool:
        """判断是否为某月第一个交易日"""
        month = date[:7]
        return month != self._prev_month

    # ================================================================
    # 价格缓冲区
    # ================================================================

    def _update_price_buffer(self, context: Context):
        """更新每只股票的收盘价缓冲区（滑动窗口）"""
        maxlen = self._price_buffer_maxlen
        for code, data in context.market_data.items():
            close = data.get('close', 0)
            if close <= 0:
                continue
            buf = self._price_buffer[code]
            buf.append(float(close))
            if len(buf) > maxlen:
                self._price_buffer[code] = buf[-maxlen:]

    # ================================================================
    # 六步选股
    # ================================================================

    def _select_targets(self, context: Context, date: str) -> List[str]:
        """六步选股流程，返回目标股票列表"""
        params = self.params

        # ---- Step 1: 股票池初筛 ----
        # 引擎已过滤ST/停牌/次新(通过market_filter)
        # 额外过滤：仅保留主板/中小板/创业板/科创板
        all_codes = list(context.market_data.keys())
        valid_codes = [
            c for c in all_codes
            if c.split('.')[0][:2] in ('60', '00', '30', '68')
        ]
        logger.info("[1/6] 股票池: %d只 (全市场%d只)", len(valid_codes), len(all_codes))

        if len(valid_codes) < params['top_n'] * 2:
            logger.warning("  候选不足，使用全部可交易股票")
            valid_codes = all_codes

        # ---- Step 2: 市值筛选 ----
        logger.info("[2/6] 市值筛选...")
        circ_mv = self._factor_service.get_factor('circ_mv', date, stock_pool=valid_codes)
        if not circ_mv:
            logger.warning("  市值数据为空，降级为纯流动性选股")
            return self._fallback_selection(context, valid_codes)

        min_mv = params['min_market_cap'] * 1e8   # 亿→元
        max_mv = params['max_market_cap'] * 1e8

        candidates = {
            c: mv for c, mv in circ_mv.items()
            if min_mv <= mv <= max_mv
        }
        logger.info("  市值筛选: %d只 (%.0f~%.0f亿)", len(candidates),
                    params['min_market_cap'], params['max_market_cap'])

        if len(candidates) < params['top_n'] * 2:
            logger.warning("  候选不足，放宽市值限制")
            sorted_mv = sorted(circ_mv.items(), key=lambda x: x[1])
            candidates = dict(sorted_mv[:params['top_n'] * 5])

        candidate_codes = list(candidates.keys())

        # ---- Step 3: 流动性过滤 ----
        logger.info("[3/6] 流动性过滤...")
        qualified = self._filter_liquidity(context, candidate_codes, candidates)
        logger.info("  流动性过滤: %d只", len(qualified))

        # ---- Step 4: 波动率 & 动量过滤 ----
        logger.info("[4/6] 波动率/动量过滤...")
        pre_filter = list(qualified)
        qualified = self._filter_volatility_momentum(qualified, params)
        logger.info("  波动率/动量过滤: %d只", len(qualified))

        if len(qualified) < params['top_n']:
            logger.warning("  候选不足%d只, 跳过波动率过滤", params['top_n'])
            qualified = pre_filter

        # ---- Step 5: 按市值排序 + 行业分散 ----
        logger.info("[5/6] 行业分散选股...")
        sorted_codes = sorted(qualified, key=lambda c: candidates.get(c, float('inf')))

        # 获取行业信息
        industry_map = self._get_industry_map(sorted_codes, date)

        selected = []
        industry_count: Dict[str, int] = defaultdict(int)
        max_same = params['max_same_industry']

        for code in sorted_codes:
            ind = industry_map.get(code, 'unknown')
            if industry_count[ind] >= max_same:
                continue
            selected.append(code)
            industry_count[ind] += 1
            if len(selected) >= params['top_n']:
                break

        # 不够则补充
        if len(selected) < params['top_n']:
            for code in sorted_codes:
                if code not in selected:
                    selected.append(code)
                    if len(selected) >= params['top_n']:
                        break

        # ---- Step 6: 涨跌停过滤(买入侧) ----
        logger.info("[6/6] 涨跌停过滤...")
        selected = self._filter_limit_up(context, selected)

        logger.info("  最终选股: %d只", len(selected))
        return selected

    # ================================================================
    # 流动性过滤
    # ================================================================

    def _filter_liquidity(
        self,
        context: Context,
        codes: List[str],
        mv_map: Dict[str, float],
    ) -> List[str]:
        """换手率 & 日均成交额过滤"""
        params = self.params
        min_turn = params['min_turn_rate'] / 100.0  # % -> 小数
        min_amount = params['min_daily_amount'] * 1e4  # 万元 → 元

        qualified = []
        for code in codes:
            data = context.market_data.get(code)
            if data is None:
                continue

            amount = data.get('amount', 0)
            if not amount or amount <= 0:
                continue

            # 日均成交额过滤
            if amount < min_amount:
                continue

            # 换手率 = 成交额 / 流通市值
            mv = mv_map.get(code, 0)
            if mv > 0:
                turnover = amount / mv
                if turnover < min_turn:
                    continue

            qualified.append(code)

        return qualified

    # ================================================================
    # 波动率 & 动量过滤
    # ================================================================

    def _filter_volatility_momentum(
        self,
        codes: List[str],
        params: dict,
    ) -> List[str]:
        """20日波动率和20日涨幅过滤"""
        max_vol = params['max_20d_volatility']
        min_ret = params['min_20d_return']

        qualified = []
        for code in codes:
            prices = self._price_buffer.get(code, [])
            if len(prices) < 20:
                continue

            closes = np.array(prices[-21:])  # p[-21:]=最近21天, 计算20个日收益率
            # len(prices) >= 20 已在上方保证, closes 至少有20个元素
            returns = np.diff(closes) / closes[:-1]
            volatility = np.std(returns[-20:])
            ret_20d = (closes[-1] / closes[-20] - 1) if len(closes) >= 20 else (closes[-1] / closes[0] - 1)

            if volatility <= max_vol and ret_20d >= min_ret:
                qualified.append(code)

        return qualified

    # ================================================================
    # 行业映射
    # ================================================================

    def _get_industry_map(self, codes: List[str], date: str) -> Dict[str, str]:
        """获取股票的行业分类（带缓存）"""
        # 懒加载行业映射缓存
        if not hasattr(self, '_industry_cache'):
            self._industry_cache: Dict[str, str] = {}
            try:
                from src.data.database import DatabaseManager
                from config.config import DATABASE_CONFIG
                db = DatabaseManager(DATABASE_CONFIG.get('path', 'data/aquant.db'))
                df = db.get_stock_info()
                if df is not None and not df.empty and 'industry' in df.columns:
                    for _, row in df.iterrows():
                        code = row.get('stock_code', '')
                        industry = row.get('industry', '')
                        if code and industry:
                            self._industry_cache[code] = str(industry)
            except Exception:
                pass

        # 从缓存构建结果，降级为板块前缀
        industry_map = {}
        for code in codes:
            if code in self._industry_cache:
                industry_map[code] = self._industry_cache[code]
            else:
                prefix = code.split('.')[0][:2]
                industry_map[code] = f"board_{prefix}"

        return industry_map

    # ================================================================
    # 涨跌停过滤
    # ================================================================

    def _filter_limit_up(self, context: Context, selected: List[str]) -> List[str]:
        """过滤涨停股（不可买入）"""
        filtered = []
        limit_up_count = 0

        for code in selected:
            data = context.market_data.get(code)
            if data is None:
                continue

            # 引擎设置的tradable标记
            tradable = data.get('tradable', True)
            if not tradable:
                # 判断是涨停还是跌停
                pre_close = data.get('pre_close', 0)
                close = data.get('close', 0)
                if pre_close > 0 and close >= pre_close * 1.095:
                    limit_up_count += 1
                    continue
                if pre_close > 0 and close <= pre_close * 0.905:
                    # 跌停不影响买入过滤
                    pass

            filtered.append(code)

        if limit_up_count > 0:
            logger.info("  涨停排除: %d只", limit_up_count)

        return filtered

    # ================================================================
    # 降级选股
    # ================================================================

    def _fallback_selection(self, context: Context, codes: List[str]) -> List[str]:
        """市值数据缺失时的降级选股：仅按成交额排序选小市值"""
        amount_map = {}
        for code in codes:
            data = context.market_data.get(code)
            if data:
                amount = data.get('amount', 0)
                if amount > 0:
                    amount_map[code] = amount

        if not amount_map:
            # 随机选
            return codes[:self.params['top_n']]

        sorted_codes = sorted(amount_map, key=amount_map.get)
        return sorted_codes[:self.params['top_n']]

    # ================================================================
    # 仓位计算 (风控 + 市场趋势)
    # ================================================================

    def _calc_position_pct(self, context: Context) -> float:
        """计算目标仓位比例"""
        params = self.params

        # 更新最高净值
        nav_ratio = context.total_value / context.history[0].total_value if context.history else 1.0
        if nav_ratio > self._peak_nav:
            self._peak_nav = nav_ratio

        drawdown = (nav_ratio - self._peak_nav) / self._peak_nav if self._peak_nav > 0 else 0

        # 净值风控
        if drawdown <= -params['dd_clear']:
            self._risk_mode = "cleared"
            target_pct = 0.18
            logger.info("[风控] 回撤%.1f%% >= %.0f%%, 仓位→18%%",
                        abs(drawdown) * 100, params['dd_clear'] * 100)
        elif drawdown <= -params['dd_reduce']:
            self._risk_mode = "reduced"
            target_pct = 0.48
            logger.info("[风控] 回撤%.1f%% >= %.0f%%, 仓位→48%%",
                        abs(drawdown) * 100, params['dd_reduce'] * 100)
        elif nav_ratio >= params['recover_threshold'] and self._risk_mode != "normal":
            self._risk_mode = "normal"
            target_pct = 0.98
            logger.info("[风控] 净值恢复至%.3f, 恢复满仓", nav_ratio)
        else:
            target_pct = 0.98

        # 市场趋势过滤
        if params.get('use_market_trend', True):
            trend_factor = self._check_market_trend()
            target_pct *= trend_factor
            if trend_factor < 1.0:
                logger.info("[市场趋势] 中证1000在MA%d下方, 仓位×%.0f%% → %.0f%%",
                            params['market_ma_period'],
                            trend_factor * 100, target_pct * 100)

        return target_pct

    def _check_market_trend(self) -> float:
        """检查中证1000是否在MA60上方，返回仓位因子"""
        params = self.params
        ma_period = params['market_ma_period']

        if len(self._index_prices) < ma_period:
            return 1.0

        recent = self._index_prices[-ma_period:]
        ma = sum(recent) / len(recent)
        current = self._index_prices[-1]

        if current < ma:
            return params['below_ma_factor']
        return 1.0

    # ================================================================
    # 卖出非目标持仓
    # ================================================================

    def _sell_non_targets(
        self,
        context: Context,
        targets: List[str],
        surge_sold_today: Set[str],
    ) -> List[Order]:
        """卖出不在目标列表中的持仓（重叠保留）"""
        target_set = set(targets)
        orders = []
        keep_count = 0
        sell_count = 0
        surge_skip = 0

        for code, pos in list(context.positions.items()):
            if pos.quantity <= 0:
                continue

            # 在目标列表中 → 保留
            if code in target_set:
                keep_count += 1
                continue

            # 异动监控中 → 保留，由异动止盈处理
            if code in self._surge_mode:
                surge_skip += 1
                continue

            # 今日已被异动止盈卖出 → 跳过
            if code in surge_sold_today:
                continue

            orders.append(Order(
                stock_code=code,
                direction=Direction.SHORT,
                quantity=pos.quantity,
                reason="月度调仓卖出(非目标)",
            ))
            sell_count += 1

        parts = [f"卖出{sell_count}只"]
        if keep_count:
            parts.append(f"保留{keep_count}只")
        if surge_skip:
            parts.append(f"异动保留{surge_skip}只")
        logger.info("  [卖出] %s", ", ".join(parts))

        return orders

    # ================================================================
    # 买入新目标
    # ================================================================

    def _buy_targets(
        self,
        context: Context,
        targets: List[str],
        date: str,
    ) -> List[Order]:
        """等权买入目标股票（跳过已持有和已止盈）"""
        held_codes = {c for c, p in context.positions.items() if p.quantity > 0}

        # 过滤：已持有 / 本月已止盈 / 异动监控中
        new_buys = []
        for code in targets:
            if code in held_codes:
                continue
            if code in self._surge_sold_history:
                continue
            new_buys.append(code)

        keep_count = len(targets) - len(new_buys)
        if keep_count > 0:
            logger.info("  [买入] 已持有%d只跳过, 买入%d只新股", keep_count, len(new_buys))

        if not new_buys:
            logger.info("  [买入] 无需买入")
            return []

        # 计算仓位
        target_pos_pct = self._calc_position_pct(context)
        per_stock_pct = target_pos_pct / max(len(new_buys), 1)
        total_value = context.total_value

        orders = []
        for code in new_buys:
            data = context.market_data.get(code)
            if data is None:
                continue

            close = data.get('close', 0)
            if close <= 0:
                continue

            # 涨停跳过
            tradable = data.get('tradable', True)
            if not tradable:
                continue

            target_value = total_value * per_stock_pct
            qty = int(target_value / close / 100) * 100
            if qty >= 100:
                orders.append(Order(
                    stock_code=code,
                    direction=Direction.LONG,
                    quantity=qty,
                    reason="小市值选股买入",
                ))
                # 记录入场
                self._entry_info[code] = {
                    'entry_date': date,
                    'entry_price': float(close),
                }

        logger.info("  [买入] %d只, 每只%.1f%%仓位", len(orders), per_stock_pct * 100)
        return orders

    # ================================================================
    # 异动检测 + 移动止盈
    # ================================================================

    def _check_surge_stop(self, context: Context, date: str) -> List[Order]:
        """
        每日检查持仓:
        1. 计算5日涨幅和加速比
        2. 触发异动→进入监控
        3. 监控中→更新峰值, 回落后止盈
        """
        params = self.params
        surge_orders = []
        positions = context.positions

        if not positions:
            return surge_orders

        # 初始化入场记录
        for code in positions:
            if code not in self._entry_info and positions[code].quantity > 0:
                self._entry_info[code] = {
                    'entry_date': date,
                    'entry_price': positions[code].entry_price,
                }

        surge_sold_today: Set[str] = set()

        for code, pos in list(positions.items()):
            if pos.quantity <= 0:
                continue

            prices = self._price_buffer.get(code, [])
            lookback = params['surge_lookback']
            trend_lb = params['surge_trend_lookback']

            if len(prices) < trend_lb + 1:
                continue

            current_price = prices[-1]
            price_5d_ago = prices[-lookback - 1] if len(prices) >= lookback + 1 else prices[0]
            price_20d_ago = prices[-trend_lb - 1] if len(prices) >= trend_lb + 1 else prices[0]

            ret_5d = (current_price / price_5d_ago - 1) if price_5d_ago > 0 else 0
            ret_20d = (current_price / price_20d_ago - 1) if price_20d_ago > 0 else 0

            # 加速比
            if ret_20d > 0.03:
                surge_ratio = ret_5d / ret_20d
            elif ret_5d > params['surge_threshold']:
                surge_ratio = 1.0
            else:
                surge_ratio = 0.0

            # 最低持有天数
            entry = self._entry_info.get(code, {})
            entry_date_str = entry.get('entry_date', date)
            try:
                entry_dt = pd.to_datetime(entry_date_str)
                today_dt = pd.to_datetime(date)
                hold_days = (today_dt - entry_dt).days
            except Exception:
                hold_days = 999

            # ---- 进入异动监控 ----
            if code not in self._surge_mode and hold_days >= params['surge_min_hold_days']:
                is_surge = (
                    ret_5d >= params['surge_threshold'] and
                    surge_ratio >= params['surge_ratio_threshold']
                )
                if is_surge:
                    self._surge_mode.add(code)
                    self._surge_peaks[code] = current_price
                    logger.info(
                        "  [异动预警] %s 5日涨幅%.1f%% 加速比%.0f%% → 启动移动止盈",
                        code, ret_5d * 100, surge_ratio * 100,
                    )

            # ---- 异动监控: 更新峰值 + 检查回落 ----
            if code in self._surge_mode:
                peak = self._surge_peaks.get(code, current_price)
                if current_price > peak:
                    self._surge_peaks[code] = current_price
                    peak = current_price

                drawdown_from_peak = (current_price - peak) / peak if peak > 0 else 0

                if drawdown_from_peak <= -params['trailing_stop_pct']:
                    surge_orders.append(Order(
                        stock_code=code,
                        direction=Direction.SHORT,
                        quantity=pos.quantity,
                        reason=f"移动止盈: 峰值{peak:.2f}回落{abs(drawdown_from_peak)*100:.1f}%",
                    ))
                    surge_sold_today.add(code)
                    self._surge_sold_history[code] = date
                    self._surge_total_count += 1  # 累计计数，不清零
                    logger.info(
                        "  [移动止盈] %s 峰值%.2f 回落%.1f%% → 止盈卖出",
                        code, peak, abs(drawdown_from_peak) * 100,
                    )

        # 清理已卖出的异动状态
        for code in surge_sold_today:
            self._surge_mode.discard(code)
            self._surge_peaks.pop(code, None)

        # 清理不再持仓的异动状态
        held_codes = set(positions.keys())
        for code in list(self._surge_mode):
            if code not in held_codes:
                self._surge_mode.discard(code)
                self._surge_peaks.pop(code, None)

        return surge_orders

    # ================================================================
    # 成交回调
    # ================================================================

    def on_order_filled(self, context: Context, trade: 'TradeRecord'):
        """订单成交回调 — 更新入场信息"""
        if trade.action == 'open':
            self._entry_info[trade.stock_code] = {
                'entry_date': str(trade.date)[:10],
                'entry_price': trade.price,
            }

    def on_stop(self, context: Context):
        """回测结束"""
        logger.info("回测结束 | 异动止盈触发: %d次", self._surge_total_count)
