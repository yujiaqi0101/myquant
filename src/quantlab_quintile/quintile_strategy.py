"""
QuintileSignalStrategy — 按因子分位输出 signal 的 SignalStrategy。

每个调仓日，根据 ``factor_data`` 把 symbol 按因子值分 N 桶，
输出 signal DataFrame(date × symbol)：
    - signal=1：当前 symbol 属于目标 quintile（``target_quintile``）
    - signal=0：其他

非调仓日：沿用上次调仓的 signal（避免频繁调仓）。

设计要点：
    - 与 quantlab SignalStrategy 接口一致（signal(ctx) -> DataFrame）
    - 不依赖 quantlab engine 之外的任何状态
    - factor_data 是 ``DataFrame(date × symbol)`` 的因子值
    - rebalance_freq 控制调仓频率
    - direction='high' 表示因子值越大分位越高（Q1=高分位，做多）
      direction='low'  表示因子值越小分位越高
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from src.quantlab.signals.base import SignalStrategy


class QuintileSignalStrategy(SignalStrategy):
    """
    按因子分位输出 signal 的 SignalStrategy。

    Parameters
    ----------
    factor_data : pd.DataFrame
        因子值，index=date, columns=symbol。
    target_quintile : int
        目标 quintile（1=最低因子值, n=最高因子值；或反之，看 direction）
    n_quantiles : int
        分位数量（默认 5）
    direction : str
        'high'（默认）：因子值越大，分位越高 → Q1 是低因子，Qn 是高因子
        'low'：因子值越小，分位越高 → Q1 是高因子，Qn 是低因子
        本项目传统约定：Q1 = 多头组合（高分位）
        所以做多时 target_quintile 选 ``n_quantiles``（高分位），direction='high'
    rebalance_freq : int
        调仓频率（每 N 个 bar 调一次，默认 5）
    min_factor_count : int
        单截面最少要有多少非空因子值才分位（少于则全 0）
    """

    name = "quintile_signal"
    description = "按因子分位输出 signal 的策略"

    def __init__(
        self,
        factor_data: pd.DataFrame,
        target_quintile: int = 1,
        n_quantiles: int = 5,
        direction: str = "high",
        rebalance_freq: int = 5,
        min_factor_count: int = 10,
    ):
        if n_quantiles < 2:
            raise ValueError(f"n_quantiles must be >= 2, got {n_quantiles}")
        if not (1 <= target_quintile <= n_quantiles):
            raise ValueError(
                f"target_quintile must be in [1, {n_quantiles}], got {target_quintile}"
            )
        if direction not in ("high", "low"):
            raise ValueError(f"direction must be 'high' or 'low', got {direction}")
        if rebalance_freq < 1:
            raise ValueError(f"rebalance_freq must be >= 1, got {rebalance_freq}")

        self.factor_data = factor_data
        self.target_quintile = int(target_quintile)
        self.n_quantiles = int(n_quantiles)
        self.direction = direction
        self.rebalance_freq = int(rebalance_freq)
        # 默认 min_factor_count = n_quantiles * 2（保证 qcut 可行）
        # 但如果传入的更小，则尊重用户传入
        if min_factor_count < n_quantiles:
            self.min_factor_count = n_quantiles
        else:
            self.min_factor_count = int(min_factor_count)

        # 预计算：每只 symbol 属于哪个 quintile（按 rebalance 日）
        # 形态: dict[rebalance_date_str, set(symbol)]
        self._quintile_members: Dict[str, set] = {}

    # ------------------------------------------------------------------ #
    # 工具：按 rebalance 日算 quintile
    # ------------------------------------------------------------------ #
    def _build_quintile_map(self) -> None:
        """
        遍历 factor_data 的每个 rebalance 日，按因子值分位，记录
        ``self._quintile_members[rebalance_date] = set(target_quintile 里的 symbol)``。
        """
        fd = self.factor_data
        if fd.empty:
            return

        # rebalance 日：取 fd 的索引，每 rebalance_freq 个取一个
        idx = fd.index
        n = len(idx)
        rebalance_indices = list(range(0, n, self.rebalance_freq))

        for i in rebalance_indices:
            row = fd.iloc[i]
            # 丢掉 NaN
            valid = row.dropna()
            if len(valid) < self.min_factor_count:
                continue

            values = valid.values
            # 用 qcut 分桶
            # 注意：duplicates='drop' 防止大量相同值导致分桶失败
            try:
                bins = pd.qcut(
                    values,
                    q=self.n_quantiles,
                    labels=False,  # 0..n_quantiles-1
                    duplicates="drop",
                )
            except ValueError:
                continue

            # bins 是 array，labels 0..n_quantiles-1
            # 0 = 最低分位
            # n_quantiles-1 = 最高分位
            if self.direction == "high":
                # target_quintile=1 → 最低分位
                target_label = self.target_quintile - 1
            else:
                # direction='low'：target_quintile=1 → 最高分位
                target_label = self.n_quantiles - self.target_quintile

            members = set(
                valid.index[bins == target_label].tolist()
            )
            self._quintile_members[str(idx[i])] = members

    def get_quintile_members(self) -> Dict[str, set]:
        """返回所有调仓日的 quintile 成员映射。"""
        if not self._quintile_members:
            self._build_quintile_map()
        return self._quintile_members

    # ------------------------------------------------------------------ #
    # SignalStrategy 接口
    # ------------------------------------------------------------------ #
    def signal(
        self,
        ctx,
    ) -> pd.DataFrame:
        """
        输出 signal DataFrame(date × symbol)：
            - 调仓日：symbol ∈ target_quintile → 1，否则 0
            - 非调仓日：沿用最近一次调仓的 signal
        """
        # 先确保 _quintile_members 已构建
        if not self._quintile_members:
            self._build_quintile_map()

        # 拿 ctx.data 的 symbol 列表（保留顺序）
        symbols = list(ctx.data.keys())
        if not symbols:
            return pd.DataFrame()

        # 拿统一的 index
        first_df = ctx.data[symbols[0]]
        bar_index = first_df.index

        # 找出每个 rebalance 日对应的 bar 位置
        # rebalance_dates 是 _quintile_members 的 key
        rebalance_dates = sorted(self._quintile_members.keys())

        # 初始化：全 0
        signal = pd.DataFrame(
            0,
            index=bar_index,
            columns=symbols,
            dtype="int8",
        )

        # 对每个 rebalance 日，把对应的 bar 区间（[t, t+rebalance_freq)）填入目标 quintile
        rb_ts_list = [pd.Timestamp(d) for d in rebalance_dates]

        # 把 rb_ts_list 对齐到 bar_index
        # 找每个 rb_ts 在 bar_index 中的位置
        rb_positions = bar_index.searchsorted(rb_ts_list, side="left")

        for rb_pos, rb_date in zip(rb_positions, rebalance_dates):
            members = self._quintile_members[rb_date]
            # 调仓区间：[rb_pos, rb_pos + rebalance_freq)
            end_pos = min(rb_pos + self.rebalance_freq, len(bar_index))
            if rb_pos >= len(bar_index):
                continue

            for sym in symbols:
                if sym in members:
                    signal.iloc[rb_pos:end_pos, signal.columns.get_loc(sym)] = 1
                else:
                    signal.iloc[rb_pos:end_pos, signal.columns.get_loc(sym)] = 0

        return signal


__all__ = ["QuintileSignalStrategy"]
