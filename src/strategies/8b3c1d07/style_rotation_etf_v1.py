"""
style_rotation_etf_v1 - 风格轮动 ETF 策略（quantlab SignalStrategy 版）
=====================================================================

参考东财掘金官方示例（2f0e5b5a-.../main.py：上证50/沪深300/中证500 三风格动量轮动），
基于现有数据库表（t_etf_info、t_etf_daily）实现 ETF 间的自动化轮动决策。

策略逻辑
--------
1. 计算每只 ETF 过去 ``momentum_period`` 日的累计收益率（动量）
2. 分数 = 累计收益率（正数表示上涨，负数表示下跌）
3. TopN 构造器按分数降序取前 N 只（负收益的 ETF 会被 score > 0 过滤，不会选中）
4. 非调仓日输出 NaN（引擎理解为"不操作，继续持有"）
5. 数据不足（< momentum_period + 1 根 bar）时输出 0（不参与排名）

数据约定（DataAdapter 注入到 ctx.data[sym]）
-----------------------------------------
- open / high / low / close / volume（来自 t_etf_daily）
- etf_name / listed_date（来自 t_etf_info，风控需要）

资产类型声明
------------
- ``asset_class = "etf"``：告诉数据加载层从 t_etf_daily 表读取数据
- 用户通过 ``--stocks 510050.SH,510300.SH,510500.SH`` 指定具体 ETF
- 不指定 ``--stocks`` 时加载全市场 ETF（数据量大，建议指定）
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from src.quantlab.signals.base import SignalStrategy


class StyleRotationEtfV1(SignalStrategy):
    """
    风格轮动 ETF 策略 V1（quantlab SignalStrategy）

    单标的信号规则：
        1. 计算过去 ``momentum_period`` 日的累计收益率 = close / close.shift(n) - 1
        2. 数据不足时输出 0（不参与排名）

    TopN 截断由 PortfolioConstructor 决定，本类只输出动量分数。

    signal 值 = 累计收益率（正数=上涨，负数=下跌）。
    TopN 构造器只选 score > 0 的标的，因此负收益的 ETF 不会被选中。
    """

    name = "style_rotation_etf"
    description = "风格轮动 ETF 策略 V1 (quantlab) - N日动量轮动"
    asset_class = "etf"

    def __init__(
        self,
        momentum_period: int = 20,
        rebalance_at: str = "month_start",
        top_n: int = 1,
    ):
        # 参数全部为基本类型（int / float / bool / str），可 JSON 序列化
        self.momentum_period = int(momentum_period)
        self.rebalance_at = str(rebalance_at)  # month_start / month_end / week_start / daily
        self.top_n = int(top_n)

        # 入参合理性校验（启动即失败，不要在 .signal() 跑一半才崩）
        if self.momentum_period < 1:
            raise ValueError(f"momentum_period must be >= 1, got {momentum_period}")
        if self.top_n < 1:
            raise ValueError(f"top_n must be >= 1, got {top_n}")
        if self.rebalance_at not in ("month_start", "month_end", "week_start", "daily"):
            raise ValueError(
                f"rebalance_at must be one of month_start/month_end/week_start/daily, got {rebalance_at}"
            )

    # ------------------------------------------------------------------ #
    # SignalStrategy 接口
    # ------------------------------------------------------------------ #
    def signal(
        self,
        ctx,
    ) -> pd.DataFrame:
        # 多标的遍历，严格保持 ctx.data.keys() 顺序
        # 先计算每只 ETF 的每日动量分数
        out: dict[str, pd.Series] = {}
        for sym in ctx.data:
            out[sym] = self._signal_one(ctx, sym)

        df = pd.DataFrame(out)

        # 根据调仓频率，非调仓日设为 NaN（引擎会理解为"不操作，继续持有"）
        # 调仓逻辑由策略控制，引擎不包含任何策略逻辑
        rebalance_dates = self._get_rebalance_dates(df.index)
        non_rebalance_mask = ~df.index.isin(rebalance_dates)
        if self.rebalance_at != "daily":
            df.loc[non_rebalance_mask, :] = float('nan')

        return df

    def _get_rebalance_dates(self, index: pd.DatetimeIndex) -> pd.DatetimeIndex:
        """根据rebalance_at参数识别调仓日（复用 small_cap_v2 的实现逻辑）"""
        dates = pd.Series(index, index=index)

        if self.rebalance_at == "daily":
            return index
        elif self.rebalance_at == "month_start":
            # 每月第一个交易日：月份变化的第一天
            months = dates.dt.month
            years = dates.dt.year
            is_month_start = (months != months.shift(1)) | (years != years.shift(1))
            is_month_start.iloc[0] = True  # 第一天一定是调仓日
            return index[is_month_start.fillna(True)]
        elif self.rebalance_at == "month_end":
            # 每月最后一个交易日：下一天月份不同
            months = dates.dt.month
            years = dates.dt.year
            is_month_end = (months != months.shift(-1)) | (years != years.shift(-1))
            is_month_end.iloc[-1] = True  # 最后一天一定是调仓日
            return index[is_month_end.fillna(True)]
        elif self.rebalance_at == "week_start":
            # 每周第一个交易日（周一是一周开始，但周一可能休市，所以找每周的第一个交易日）
            weeks = dates.dt.isocalendar().week.astype(int)
            years = dates.dt.isocalendar().year.astype(int)
            is_week_start = (weeks != weeks.shift(1)) | (years != years.shift(1))
            is_week_start.iloc[0] = True
            return index[is_week_start.fillna(True)]
        else:
            return index

    # ------------------------------------------------------------------ #
    # 单标逻辑（私有）
    # ------------------------------------------------------------------ #
    def _signal_one(
        self,
        ctx,
        sym: str,
    ) -> pd.Series:
        df = ctx.data[sym]

        # 数据不足时输出 0（不参与排名）
        if len(df) < self.momentum_period + 1:
            return pd.Series(0.0, index=df.index, dtype="float64")

        # 计算 N 日累计收益率（动量）
        # close.shift(momentum_period) 是 momentum_period 天前的收盘价
        # 收益率 = 当前收盘价 / N天前收盘价 - 1
        close = df["close"]
        momentum = close / close.shift(self.momentum_period) - 1

        # 前 momentum_period 根 bar 没有足够的历史数据，输出 0
        momentum = momentum.fillna(0.0)

        return momentum


# ---------------------------------------------------------------------- #
# 工厂方法：方便 ExperimentRecord / CLI 用 kwargs 构造
# ---------------------------------------------------------------------- #
def make_style_rotation_etf_v1(
    momentum_period: int = 20,
    rebalance_at: str = "month_start",
    top_n: int = 1,
) -> StyleRotationEtfV1:
    """显式工厂：避免某些调用方依赖默认参数顺序。"""
    return StyleRotationEtfV1(
        momentum_period=momentum_period,
        rebalance_at=rebalance_at,
        top_n=top_n,
    )


# ---------------------------------------------------------------------- #
# 典型参数网格（给 Optimizer / ParallelOptimizer 用）
# ---------------------------------------------------------------------- #
PARAM_SPACE: dict = {
    # 动量计算周期（日）
    "momentum_period":   [10, 20, 30, 60],
    # 调仓频率
    "rebalance_at":      ["month_start", "month_end", "week_start"],
    # 持仓数（ETF 轮动通常只持 1 只，也可分散到 2-3 只）
    "top_n":             [1, 2, 3],
}
