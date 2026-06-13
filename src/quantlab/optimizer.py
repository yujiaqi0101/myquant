"""
Optimizer：参数网格搜索

V2 改造：
- 吃 BaseBacktestEngine
- 通过 BacktestResult.sharpe 等统一字段评分
- 支持 fast 引擎（VectorBT）和 precise 引擎（EventEngine）
- 顶层是 FastOptimizer，封装快筛流程
"""

import copy
import pandas as pd

from itertools import product
from dataclasses import dataclass

from typing import Dict, List

from .core.base_engine import (
    BaseBacktestEngine,
)
from .core.backtest_result import (
    BacktestResult,
)


def generate_param_grid(param_space):

    keys = list(
        param_space.keys()
    )

    values = list(
        param_space.values()
    )

    for combo in product(*values):

        yield dict(
            zip(
                keys,
                combo
            )
        )


class Optimizer:

    # 通用 Optimizer
    # 适配任何 BaseBacktestEngine
    # 评分通过 scorer(BacktestResult) -> float

    def __init__(
        self,
        strategy_cls,
        engine: BaseBacktestEngine,
        scorer=None,
    ):

        self.strategy_cls = (
            strategy_cls
        )
        self.engine = engine
        # 默认评分：sharpe
        self.scorer = scorer or (
            lambda r: r.sharpe
        )

    def evaluate(
        self,
        data,
        params: Dict,
    ):

        strategy = (
            self.strategy_cls(
                **params
            )
        )

        # engine 必须可重置 state
        # （factor_cache / portfolio / tradebook）
        engine = copy.deepcopy(
            self.engine
        )

        # BaseBacktestEngine 协议
        result: BacktestResult = (
            engine.run(
                strategy=strategy,
                data=data,
                params=params,
            )
        )

        if not result.ok():

            # 引擎报错 → score = -inf
            return {
                "params": params,
                "score": float("-inf"),
                "error": (
                    result.error
                    or "unknown"
                ),
            }

        score = self.scorer(result)

        return {
            "params": params,
            "score": score,
            "result": result,
        }

    def run(
        self,
        data,
        param_space: Dict,
    ):

        rows = []

        for params in (
            generate_param_grid(
                param_space
            )
        ):

            ev = self.evaluate(
                data, params
            )

            row = {}
            row.update(params)
            row["score"] = ev["score"]

            if "error" in ev:

                row["error"] = ev["error"]

            if (
                "result" in ev
                and ev["result"] is not None
            ):

                r = ev["result"]
                row["source"] = r.source
                row["total_return"] = (
                    r.total_return
                )
                row["sharpe"] = r.sharpe
                row["max_drawdown"] = (
                    r.max_drawdown
                )

            rows.append(row)

        result = pd.DataFrame(rows)

        result = result.sort_values(
            "score",
            ascending=False,
        ).reset_index(drop=True)

        return result


class FastOptimizer:

    # 快筛 + 精筛 两阶段
    # 用 fast_engine（VectorBT）跑全网格
    # 取 top_n
    # 再用 precise_engine（EventEngine）精确验证
    #
    # 返回双引擎结果表

    def __init__(
        self,
        fast_engine: BaseBacktestEngine,
        precise_engine: BaseBacktestEngine = None,
        top_n: int = 10,
    ):

        self.fast_engine = fast_engine
        self.precise_engine = (
            precise_engine
        )
        self.top_n = top_n

    def run(
        self,
        strategy_cls,
        data,
        param_space: Dict,
    ) -> "TwoStageResult":

        # ---- 1) Fast stage ----
        opt = Optimizer(
            strategy_cls=strategy_cls,
            engine=self.fast_engine,
        )
        fast_df = opt.run(
            data, param_space
        )

        # 取 top_n（score 有效）
        valid = fast_df[
            fast_df["score"]
            != float("-inf")
        ]
        top = valid.head(
            self.top_n
        ).copy()

        # ---- 2) Precise stage ----
        precise_rows = []

        if (
            self.precise_engine
            is not None
        ):

            for _, row in top.iterrows():

                params = {
                    k: int(v)
                    if (
                        isinstance(
                            v, float
                        )
                        and v.is_integer()
                    )
                    else v
                    for k, v in row.items()
                    if k not in (
                        "score",
                        "source",
                        "total_return",
                        "sharpe",
                        "max_drawdown",
                        "error",
                    )
                }

                ev = opt.evaluate(
                    data, params
                )

                precise_rows.append({
                    "params": params,
                    "fast_score": row["score"],
                    "precise_score": ev[
                        "score"
                    ],
                    "fast_sharpe": row.get(
                        "sharpe"
                    ),
                    "precise_sharpe": (
                        ev["result"].sharpe
                        if ev.get("result")
                        else None
                    ),
                    "fast_return": row.get(
                        "total_return"
                    ),
                    "precise_return": (
                        ev["result"].total_return
                        if ev.get("result")
                        else None
                    ),
                })

        precise_df = pd.DataFrame(
            precise_rows
        )

        if not precise_df.empty:

            precise_df = (
                precise_df.sort_values(
                    "precise_score",
                    ascending=False,
                ).reset_index(drop=True)
            )

        return TwoStageResult(
            fast_df=fast_df,
            precise_df=precise_df,
            top_n=self.top_n,
        )


@dataclass
class TwoStageResult:

    fast_df: pd.DataFrame

    precise_df: pd.DataFrame

    top_n: int

    def summary(self) -> str:

        out = []
        out.append("=" * 50)
        out.append(
            f"  FastOptimizer: 两阶段优化 (top_n={self.top_n})"
        )
        out.append("=" * 50)
        out.append("")
        out.append(
            f"  Fast stage: "
            f"{len(self.fast_df)} 组参数"
        )
        if not self.fast_df.empty:

            best = self.fast_df.iloc[0]
            out.append(
                f"    best fast: "
                f"score={best['score']:.3f} "
                f"sharpe={best.get('sharpe', 0):.3f}"
            )

        out.append("")
        out.append(
            f"  Precise stage: "
            f"{len(self.precise_df)} 组候选"
        )
        if not self.precise_df.empty:

            for i, row in (
                self.precise_df.iterrows()
            ):

                p = row["params"]
                fs = row.get(
                    "fast_sharpe", 0
                )
                ps = row.get(
                    "precise_sharpe", 0
                )
                out.append(
                    f"    #{i + 1}: "
                    f"params={p} "
                    f"fast_sharpe={fs:.3f} "
                    f"precise_sharpe={ps:.3f}"
                )

        out.append("=" * 50)
        return "\n".join(out)
