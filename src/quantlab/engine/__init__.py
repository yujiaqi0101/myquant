from typing import Dict

import pandas as pd

from ..core.portfolio import Portfolio
from ..core.fill import Fill
from ..core.tradebook import TradeBook
from ..core.base_engine import (
    BaseBacktestEngine,
)
from ..core.backtest_result import (
    BacktestResult,
)
from ..data.cache import factor_cache
from ..data.context import StrategyContext


class BarEngine(BaseBacktestEngine):

    # V3: Multi Asset + Portfolio Construction Layer
    #
    # 完整流水线（每根 bar）：
    #   1) scores   = strategy.signal(ctx).iloc[i-1]      # 前一根 bar 的分数
    #   2) target   = portfolio_constructor.construct(
    #                      scores, timestamp)             # 目标权重
    #   3) orders   = execution.generate_orders(
    #                      portfolio, target, prices)     # 调仓单
    #   4) execute  → 应用滑点、扣佣金、更新 portfolio
    #               → 生成 Fill → 推 TradeBook
    #   5) record   → 每日收盘后记一次权益
    #
    # 关键设计：
    #   - Execution 只产 Order
    #   - BarEngine 才真正修改 Portfolio
    #   - 现金不足时自动降仓

    def __init__(
        self,
        strategy,
        portfolio_constructor,
        execution_model,
        commission_model,
        slippage_model,
        initial_cash=100000
    ):

        self.strategy = strategy

        self.portfolio_constructor = (
            portfolio_constructor
        )

        self.execution_model = (
            execution_model
        )

        self.commission_model = (
            commission_model
        )

        self.slippage_model = (
            slippage_model
        )

        self.initial_cash = initial_cash

    def run(
        self,
        strategy=None,
        data: Dict = None,
        params: Dict = None,
    ) -> BacktestResult:

        # BaseBacktestEngine 协议
        if strategy is not None:

            self.strategy = strategy

        raw = self._run_legacy(data)

        return BacktestResult.from_event_dict(
            raw
        )

    def _run_legacy(self, data: Dict):

        # data: Dict[symbol, DataFrame]
        # 假设所有 symbol 共享相同 index

        symbols = list(data.keys())

        first_df = data[symbols[0]]

        n_bars = len(first_df)

        portfolio = Portfolio(
            self.initial_cash
        )

        tradebook = TradeBook()

        fills = []

        position_qty_per_symbol = {
            sym: [] for sym in symbols
        }

        ctx = StrategyContext(
            data,
            factor_cache
        )

        # 1) 一次性算全 signal
        signal = self.strategy.signal(ctx)

        # 2) 首根 bar：只 record 权益
        first_close = {
            sym: (
                data[sym]
                .iloc[0]["close"]
            )
            for sym in symbols
        }
        portfolio.record(
            first_df.index[0],
            first_close
        )
        for sym in symbols:

            position_qty_per_symbol[sym].append(
                0
            )

        # 3) 逐 bar 推进
        for i in range(1, n_bars):

            bar_open = {
                sym: (
                    data[sym]
                    .iloc[i]["open"]
                )
                for sym in symbols
            }

            bar_close = {
                sym: (
                    data[sym]
                    .iloc[i]["close"]
                )
                for sym in symbols
            }

            timestamp = (
                first_df.index[i]
            )

            # ---- a) 前一根 bar 的 score ----
            prev_scores = (
                signal
                .iloc[i - 1]
                .to_dict()
            )

            # ---- a.5) NaN 信号契约 ----
            # 策略层约定：全 NaN 表示"不操作，继续持有"
            # （与 VectorBTAdapter._build_weights_df 保持一致）
            # 若不加此判断，TopN 用 `v > 0` 过滤会把 NaN 视为不达标
            # → 返回空 weights → matcher 把所有持仓按 target_w=0 卖光
            # → 引擎变成"每天清仓、调仓日再买回"的瞎折腾策略
            valid_scores = [
                v for v in prev_scores.values()
                if v is not None
                and not (
                    isinstance(v, float)
                    and pd.isna(v)
                )
            ]
            if not valid_scores:
                # 全 NaN → 不调仓，只 record 权益，仓位继续持有
                portfolio.record(
                    timestamp,
                    bar_close
                )
                for sym in symbols:
                    position_qty_per_symbol[sym].append(
                        portfolio
                        .get_or_create(sym)
                        .qty
                    )
                continue

            # ---- b) Portfolio Construction ----
            #     scores -> TargetPortfolio
            target = (
                self
                .portfolio_constructor
                .construct(
                    prev_scores,
                    timestamp
                )
            )

            # ---- c) Execution ----
            #     TargetPortfolio -> List[Order]
            orders = (
                self
                .execution_model
                .generate_orders(
                    portfolio,
                    target,
                    bar_open
                )
            )

            # ---- d) 执行 Order ----
            for order in orders:

                sym = order.symbol
                q = order.quantity

                price = bar_open[sym]

                # 滑点
                fill_price = (
                    self
                    .slippage_model
                    .apply(
                        q,
                        price
                    )
                )

                # 佣金
                commission = (
                    self
                    .commission_model
                    .calculate(
                        q,
                        fill_price
                    )
                )

                cost = (
                    q * fill_price
                    + commission
                )

                # 现金不足保护：买入时降仓
                if (
                    q > 0
                    and cost > portfolio.cash
                ):

                    affordable = (
                        portfolio.cash
                        - commission
                    )

                    if affordable <= 0:

                        # 现金全花完
                        q = 0
                    else:

                        # 按能买得起的最大量
                        q = int(
                            affordable
                            / fill_price
                        )
                        cost = (
                            q * fill_price
                            + commission
                        )

                if q == 0:

                    position_qty_per_symbol[
                        sym
                    ].append(
                        portfolio
                        .get_or_create(sym)
                        .qty
                    )
                    continue

                # 扣现金
                portfolio.cash -= cost

                # 更新 Position
                position = (
                    portfolio
                    .get_or_create(sym)
                )
                position.update(
                    q,
                    fill_price
                )

                # 记录 Fill
                fill = Fill(
                    symbol=sym,
                    timestamp=timestamp,
                    quantity=q,
                    price=fill_price,
                    commission=commission
                )
                fills.append(fill)
                tradebook.on_fill(fill)

                position_qty_per_symbol[
                    sym
                ].append(
                    portfolio
                    .get_or_create(sym)
                    .qty
                )

            # 没有订单的 symbol：持仓不变
            for sym in symbols:

                if not any(
                    o.symbol == sym
                    for o in orders
                ):

                    position_qty_per_symbol[
                        sym
                    ].append(
                        portfolio
                        .get_or_create(sym)
                        .qty
                    )

            # ---- e) 收盘 record ----
            portfolio.record(
                timestamp,
                bar_close
            )

        # 4) 重建 closed_trades
        tradebook.rebuild()

        return {
            "portfolio": portfolio,
            "fills": fills,
            "tradebook": tradebook,
            "position_qty": (
                position_qty_per_symbol
            ),
            "signal": signal
        }
