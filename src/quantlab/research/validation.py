"""
ValidationRunner - V1.8

设计：
  ValidationRunner(fast_engine, precise_engine)
  ├── validate(strategy_cls, params, data)
  │     单参数双引擎验证
  │     return ValidationResult
  │
  └── validate_top_n(optimizer_result, strategy_cls, data, top_n)
        批量验证 top N 参数
        算 consistency_score
        consistency < 0.8 淘汰
        写 validation_report.csv

核心思想：
  VectorBT 很快但不精确
  EventEngine 精确但慢
  先用 VBT 搜索出 Top N
  再用 EventEngine 验证
  双引擎不一致的策略 = 存在：
    - 未来函数
    - 执行逻辑错误
    - 仓位估算错误
  → 直接淘汰
"""

import os
from dataclasses import (
    dataclass,
    field,
)
from typing import Dict, List, Any

import pandas as pd


@dataclass(slots=True)
class ValidationResult:

    # 单组参数的双引擎验证结果

    params: Dict

    fast_result: Any

    precise_result: Any

    return_diff: float

    sharpe_diff: float

    trade_diff: int

    consistency_score: float

    passed: bool

    @property
    def fast_sharpe(self) -> float:

        return (
            self.fast_result.sharpe
            if self.fast_result
            else 0.0
        )

    @property
    def precise_sharpe(self) -> float:

        return (
            self.precise_result.sharpe
            if self.precise_result
            else 0.0
        )


class ValidationRunner:

    # 双引擎验证器
    #
    # 构造时注入 fast/precise engine
    # 后续 validate / validate_top_n 都用同一对引擎

    def __init__(
        self,
        fast_engine,
        precise_engine,
        consistency_threshold: float = 0.8,
    ):

        self.fast_engine = fast_engine
        self.precise_engine = precise_engine

        # 一致性淘汰线
        # consistency_score < 0.8 直接淘汰
        # 原因：双引擎差距 > 20% 几乎一定有 bug
        self.consistency_threshold = (
            consistency_threshold
        )

    # ----------------------------------------------------------------
    # 单参数验证
    # ----------------------------------------------------------------

    def validate(
        self,
        strategy_cls,
        params: Dict,
        data: Dict,
    ) -> ValidationResult:

        # 单组参数
        # 1) fast_engine 跑一次
        # 2) precise_engine 跑一次
        # 3) 算 return_diff / sharpe_diff / trade_diff
        # 4) 算 consistency_score = 1 - |sharpe差 / max(双方sharpe)|
        # 5) 决定 passed

        strategy = strategy_cls(**params)

        fast_res = self.fast_engine.run(
            strategy=strategy,
            data=data,
            params=params,
        )
        precise_res = (
            self.precise_engine.run(
                strategy=strategy,
                data=data,
                params=params,
            )
        )

        return_diff = abs(
            fast_res.total_return
            - precise_res.total_return
        )
        sharpe_diff = abs(
            fast_res.sharpe
            - precise_res.sharpe
        )
        trade_diff = abs(
            fast_res.trade_count
            - precise_res.trade_count
        )

        # consistency_score
        #   = 1 - relative_error
        # relative_error = |a - b| / max(|a|, |b|, eps)
        # 用 sharpe 计算（最关键指标）
        eps = 1e-6
        denom = max(
            abs(fast_res.sharpe),
            abs(precise_res.sharpe),
            eps,
        )
        rel_err = (
            abs(
                fast_res.sharpe
                - precise_res.sharpe
            )
            / denom
        )
        # 截断到 [0, 1]
        rel_err = min(rel_err, 1.0)

        consistency = 1.0 - rel_err

        passed = (
            consistency
            >= self.consistency_threshold
        )

        return ValidationResult(
            params=params,
            fast_result=fast_res,
            precise_result=precise_res,
            return_diff=return_diff,
            sharpe_diff=sharpe_diff,
            trade_diff=trade_diff,
            consistency_score=consistency,
            passed=passed,
        )

    # ----------------------------------------------------------------
    # 批量验证
    # ----------------------------------------------------------------

    def validate_top_n(
        self,
        optimizer_result: pd.DataFrame,
        strategy_cls,
        data: Dict,
        top_n: int = 10,
        param_keys: List[str] = None,
        output_csv: str = None,
    ) -> pd.DataFrame:

        # 批量验证 top N 参数
        #
        # optimizer_result 是 Optimizer.run() 返回的 DataFrame
        #   列: fast, slow, score, source, total_return, ...
        # 按 score 排序后取 top_n
        # 对每组参数调用 validate() 拿 ValidationResult
        # 拼成 DataFrame
        # consistency < threshold 的标记 passed=False
        # 写 CSV（可选）

        if optimizer_result is None:

            return pd.DataFrame()

        # 按 score 倒序
        sorted_df = (
            optimizer_result
            .sort_values(
                "score",
                ascending=False
            )
            .head(top_n)
            .reset_index(drop=True)
        )

        # 默认 param_keys = 除指标列外的所有列
        if param_keys is None:

            exclude = {
                "score",
                "source",
                "total_return",
                "sharpe",
                "max_drawdown",
                "error",
            }
            param_keys = [
                k for k
                in sorted_df.columns
                if k not in exclude
            ]

        rows: List[Dict] = []

        for idx, opt_row in (
            sorted_df.iterrows()
        ):

            params = {
                k: int(v)
                if (
                    isinstance(v, float)
                    and v.is_integer()
                )
                else v
                for k, v
                in opt_row.items()
                if k in param_keys
            }

            try:

                vr = self.validate(
                    strategy_cls=strategy_cls,
                    params=params,
                    data=data,
                )

                rows.append({
                    "rank": idx + 1,
                    "params": str(params),
                    "fast_return": (
                        vr.fast_result.total_return
                    ),
                    "event_return": (
                        vr.precise_result.total_return
                    ),
                    "return_diff": (
                        round(vr.return_diff, 2)
                    ),
                    "fast_sharpe": (
                        round(
                            vr.fast_result.sharpe, 3
                        )
                    ),
                    "event_sharpe": (
                        round(
                            vr.precise_result.sharpe, 3
                        )
                    ),
                    "sharpe_diff": (
                        round(vr.sharpe_diff, 3)
                    ),
                    "fast_trades": (
                        vr.fast_result.trade_count
                    ),
                    "event_trades": (
                        vr.precise_result.trade_count
                    ),
                    "trade_diff": (
                        vr.trade_diff
                    ),
                    "consistency": (
                        round(
                            vr.consistency_score, 4
                        )
                    ),
                    "passed": (
                        "OK"
                        if vr.passed
                        else "ELIMINATED"
                    ),
                })

            except Exception as e:

                rows.append({
                    "rank": idx + 1,
                    "params": str(params),
                    "fast_return": None,
                    "event_return": None,
                    "return_diff": None,
                    "fast_sharpe": None,
                    "event_sharpe": None,
                    "sharpe_diff": None,
                    "fast_trades": None,
                    "event_trades": None,
                    "trade_diff": None,
                    "consistency": 0.0,
                    "passed": (
                        f"ERROR: {e}"
                    ),
                })

        df = pd.DataFrame(rows)

        # 写 CSV
        if output_csv:

            os.makedirs(
                os.path.dirname(
                    output_csv
                ) or ".",
                exist_ok=True,
            )
            df.to_csv(
                output_csv,
                index=False,
                encoding="utf-8-sig",
            )

        return df

    def summary(self, df: pd.DataFrame) -> str:

        out = []
        out.append("=" * 60)
        out.append(
            "  ValidationRunner: 双引擎 TopN 验证"
        )
        out.append("=" * 60)

        if df.empty:

            out.append("  (no data)")
            return "\n".join(out)

        out.append(
            f"  Total: {len(df)}"
            f"  Passed: "
            f"{(df['passed'] == 'OK').sum()}"
            f"  Eliminated: "
            f"{(df['passed'] == 'ELIMINATED').sum()}"
        )
        out.append(
            f"  Consistency threshold: "
            f"{self.consistency_threshold}"
        )
        out.append("")

        out.append(
            f"  {'#':>3}  "
            f"{'fast_sharpe':>10}  "
            f"{'event_sharpe':>12}  "
            f"{'diff':>8}  "
            f"{'consist':>8}  "
            f"status"
        )
        out.append("-" * 60)

        for _, r in df.iterrows():

            out.append(
                f"  {int(r['rank']):>3d}  "
                f"{(r['fast_sharpe'] or 0):>10.3f}  "
                f"{(r['event_sharpe'] or 0):>12.3f}  "
                f"{(r['sharpe_diff'] or 0):>8.3f}  "
                f"{(r['consistency'] or 0):>8.3f}  "
                f"{r['passed']}"
            )

        out.append("=" * 60)
        return "\n".join(out)
