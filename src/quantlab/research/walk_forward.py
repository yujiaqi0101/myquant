import copy

from dataclasses import (
    dataclass,
    field
)
from typing import Dict, List

from .result import (
    ExperimentResult
)


@dataclass
class WalkForwardWindow:

    # 单个 train/test 窗口
    # 训练：用 train 段找最佳 params
    # 测试：用 best params 跑 test 段
    # 这是 WalkForward 的最小单元

    train_start: object

    train_end: object

    test_start: object

    test_end: object

    best_params: Dict = field(
        default_factory=dict
    )

    train_score: float = 0.0

    test_result: ExperimentResult = None


@dataclass
class WalkForwardResult:

    windows: List[WalkForwardWindow]

    # 把所有 test 段的 equity 拼起来
    # = 真实滚动表现
    stitched_equity_curve: List[float]

    stitched_timestamps: List

    avg_test_sharpe: float

    avg_test_return: float

    summary: Dict = field(
        default_factory=dict
    )


class WalkForward:

    # Walk Forward：把"未来"留给 test
    #
    # 例如：train=3 年, test=1 年, step=1 年
    #   Window 1: train[2018-2020]  test[2021]
    #   Window 2: train[2019-2021]  test[2022]
    #   Window 3: train[2020-2022]  test[2023]
    #   ...
    # 把所有 test 段的 equity 拼起来 → 真实滚动表现
    #
    # V1：基于已有 Optimizer
    # V2：换 genetic / bayesian
    # V3：加 purged CV

    def __init__(
        self,

        train_bars,

        test_bars,

        step_bars=None,

        scorer=None
    ):

        self.train_bars = train_bars

        self.test_bars = test_bars

        self.step_bars = (
            step_bars
            if step_bars is not None
            else test_bars
        )

        # 默认评分：sharpe_score
        from ..statistics import (
            sharpe_score
        )
        self.scorer = (
            scorer or sharpe_score
        )

        # factor cache 必须在 window 切换时清
        # 否则 train 段缓存的 ma20_AAPL(length=200)
        # 会在 test 段被错误复用
        from ..data.cache import (
            factor_cache
        )
        self._factor_cache = (
            factor_cache
        )

    def _slice_by_index(
        self, data, start, end
    ):

        # 按 index 截取 data[symbol] 的前/中/后段
        first_sym = list(data.keys())[0]

        full_index = data[first_sym].index

        sub_index = (
            full_index[start:end]
        )

        sliced = {}
        for sym, df in data.items():

            sliced[sym] = df.loc[sub_index]

        return sliced

    def run(
        self,
        strategy_cls,

        param_space: Dict,

        data: Dict,

        optimizer_factory=None
    ) -> WalkForwardResult:

        # optimizer_factory(engine_template) -> Optimizer-like
        # 默认：使用 quantlab.optimizer.Optimizer

        from ..optimizer import (
            Optimizer
        )

        first_sym = list(data.keys())[0]

        full_index = data[first_sym].index

        n = len(full_index)

        windows: List[WalkForwardWindow] = []

        stitched_equity = []

        stitched_ts = []

        cursor = self.train_bars

        while (
            cursor + self.test_bars
            <= n
        ):

            # 切到新 window 前必须清 cache
            # 因为 train/test 段长度不同
            # 缓存的 Series 长度不匹配
            self._factor_cache.clear()

            train_start = 0
            train_end = cursor

            test_start = cursor
            test_end = (
                cursor
                + self.test_bars
            )

            train_data = (
                self
                ._slice_by_index(
                    data,
                    train_start,
                    train_end
                )
            )
            test_data = (
                self
                ._slice_by_index(
                    data,
                    test_start,
                    test_end
                )
            )

            # 训练：找 best params
            train_engine = (
                self._build_engine_template()
            )

            if optimizer_factory is None:

                opt = Optimizer(

                    strategy_cls=strategy_cls,

                    engine=copy.deepcopy(
                        train_engine
                    ),

                    scorer=self.scorer
                )

            else:

                opt = optimizer_factory(

                    copy.deepcopy(
                        train_engine
                    )
                )

            train_table = opt.run(

                train_data,
                param_space
            )

            best_params = (
                train_table
                .iloc[0]
                .to_dict()
            )
            best_params.pop(
                "score", None
            )

            # 过滤掉 Optimizer.run 产生的非参数列
            # （source / total_return / sharpe / max_drawdown / error）
            for k in (
                "source",
                "total_return",
                "sharpe",
                "max_drawdown",
                "error",
            ):

                best_params.pop(k, None)

            # pandas to_dict() 会把整数变 float
            # 必须转回 int，否则 rolling(10.0) 报错
            best_params = {
                k: (
                    int(v)
                    if isinstance(v, float)
                    and v.is_integer()
                    else v
                )
                for k, v
                in best_params.items()
            }

            best_score = float(
                train_table
                .iloc[0]["score"]
            )

            # 测试：用 best params 跑 test 段
            test_strategy = (
                strategy_cls(
                    **best_params
                )
            )

            test_engine = (
                self._build_engine_template()
            )

            test_engine.strategy = (
                test_strategy
            )

            from .experiment import (
                Experiment
            )

            test_result = Experiment(

                name=(
                    f"wf_test_"
                    f"{full_index[test_start]}"
                    f"_to_"
                    f"{full_index[test_end - 1]}"
                )
            ).run(

                strategy=test_strategy,

                engine=test_engine,

                data=test_data,

                params=best_params
            )

            wf_win = WalkForwardWindow(
                train_start=(
                    full_index[train_start]
                ),
                train_end=(
                    full_index[train_end - 1]
                ),
                test_start=(
                    full_index[test_start]
                ),
                test_end=(
                    full_index[test_end - 1]
                ),
                best_params=best_params,
                train_score=best_score,
                test_result=test_result
            )

            windows.append(wf_win)

            # 拼接 equity（去掉重复的边界点）
            if stitched_equity:

                stitched_equity.extend(

                    test_result.equity_curve[1:]
                )

                stitched_ts.extend(

                    test_result.timestamps[1:]
                )

            else:

                stitched_equity.extend(
                    test_result.equity_curve
                )
                stitched_ts.extend(
                    test_result.timestamps
                )

            cursor += self.step_bars

        # 汇总
        if windows:

            test_sharpes = [
                w.test_result.metrics.get("sharpe", 0)
                for w in windows
            ]
            test_returns = [
                w.test_result.metrics.get("total_return", 0)
                for w in windows
            ]

            avg_sharpe = (
                sum(test_sharpes)
                / len(test_sharpes)
            )
            avg_return = (
                sum(test_returns)
                / len(test_returns)
            )

        else:

            avg_sharpe = 0.0
            avg_return = 0.0

        return WalkForwardResult(
            windows=windows,
            stitched_equity_curve=stitched_equity,
            stitched_timestamps=stitched_ts,
            avg_test_sharpe=avg_sharpe,
            avg_test_return=avg_return,
            summary={
                "n_windows": len(windows),
                "best_params_each_window": [
                    w.best_params
                    for w in windows
                ]
            }
        )

    def _build_engine_template(self):

        # 子类/外部可覆盖：
        #   在调用 wf.run() 之前设置
        #   wf.engine_template = my_engine_factory()
        # V1：默认从 main 导入需要外部注入
        # 这里提供一个 setter
        if (
            hasattr(self, "_engine_template")
            and self._engine_template
            is not None
        ):

            return copy.deepcopy(
                self._engine_template
            )

        # 无 template：返回 None，让调用方用 optimizer_factory
        return None

    def set_engine_template(self, engine):

        self._engine_template = engine


# ============================================================
# V2.2 WalkForwardEngine 正式版
#
# V1 痛点：
#   - 只用 bars 切分，不是按年
#   - 没有 validation 阶段
#   - 没有 stability score
#   - 没有 parameter drift
#   - 报告只是文本
#
# V2.2 改进：
#   1) WindowGenerator 按年自动切分
#   2) 三阶段：train optimize → validation → test
#   3) Equity stitching：拼接所有 test 段
#   4) Stability score：参数重复率 + 平均排名 + OOS 收益
#   5) Parameter drift：相邻窗口参数距离
#   6) WalkForwardReport：HTML 报告
# ============================================================


from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Dict,
    List,
    Tuple,
    Optional,
    Any,
)
from collections import Counter
import copy
import os

import pandas as pd


@dataclass(slots=True)
class WalkForwardWindowV2:
    # V2.2 单个窗口
    #
    # 三阶段：
    #   1) train_data   → optimizer → top_train
    #   2) top_train    → validation_runner → top_val
    #   3) top_val[0]   → event_engine → test_result
    #
    # 字段：
    #   train_period / test_period:  字符串 "2015-2017"
    #   train_idx_*  / test_idx_*:   索引位置
    #   top_train_params:            train 选出的 top N
    #   top_val_params:              validation 选出的 top K
    #   best_params:                 最终用的（最稳定）
    #   train_score / val_score:     平均评分
    #   test_result:                 test 段回测结果
    #   test_return / test_sharpe:   样本外表现

    train_period: str = ""
    test_period: str = ""

    train_start: Any = None
    train_end: Any = None
    test_start: Any = None
    test_end: Any = None

    top_train_params: List[Dict] = field(
        default_factory=list
    )
    top_val_params: List[Dict] = field(
        default_factory=list
    )

    best_params: Dict = field(
        default_factory=dict
    )

    train_score: float = 0.0
    val_score: float = 0.0

    test_result: Any = None

    test_return: float = 0.0
    test_sharpe: float = 0.0
    test_max_dd: float = 0.0
    test_trades: int = 0


@dataclass(slots=True)
class WalkForwardResultV2:
    # V2.2 最终结果
    #
    # 包含：
    #   windows:                每个窗口的完整结果
    #   stitched_equity_curve:  拼接后的 OOS 权益曲线
    #   stitched_timestamps:    拼接后的时间戳
    #   stitched_metrics:       拼接后曲线的 sharpe/max_dd
    #   stability_score:        参数稳定性综合分
    #   parameter_drift:        相邻窗口参数漂移（欧氏距离）
    #   best_params_freq:       每组 best_params 出现次数
    #   summary:                摘要 dict

    windows: List[WalkForwardWindowV2] = field(
        default_factory=list
    )

    stitched_equity_curve: List[float] = field(
        default_factory=list
    )
    stitched_timestamps: List = field(
        default_factory=list
    )

    stitched_metrics: Dict = field(
        default_factory=dict
    )

    stability_score: float = 0.0
    parameter_drift: float = 0.0
    best_params_freq: Dict = field(
        default_factory=dict
    )

    avg_test_sharpe: float = 0.0
    avg_test_return: float = 0.0
    avg_test_max_dd: float = 0.0

    summary: Dict = field(
        default_factory=dict
    )


class WindowGenerator:
    # 按年切分窗口
    #
    # WindowGenerator(
    #     train_years=3,
    #     test_years=1
    # )
    # 输入：data (Dict[sym, df]) 需带 DatetimeIndex
    # 输出：List[Dict] 描述每个窗口的索引位置
    #
    # 例：
    #   data 范围 2015-01 ~ 2025-01
    #   train_years=3, test_years=1
    #   →
    #     Window 1: train 2015~2017  test 2018
    #     Window 2: train 2016~2018  test 2019
    #     Window 3: train 2017~2019  test 2020
    #     ...
    #
    # 关键：
    #   - 按 calendar year 切（不用 365 天）
    #   - test 段 [test_start, test_end) 左闭右开
    #   - 不足一整 test 年也要跑

    def __init__(
        self,
        train_years: int = 3,
        test_years: int = 1,
    ):

        self.train_years = train_years
        self.test_years = test_years

    def generate(
        self,
        data: Dict,
    ) -> List[Dict]:
        # 生成所有窗口
        #
        # 返回 List[Dict]，每个含：
        #   train_start_idx / train_end_idx
        #   test_start_idx / test_end_idx
        #   train_start_ts / train_end_ts
        #   test_start_ts / test_end_ts
        #   train_period / test_period（字符串）

        if not data:
            return []

        first_sym = list(data.keys())[0]
        full_index = data[first_sym].index

        if len(full_index) == 0:
            return []

        # 用 year 切分
        # 比如 2015-01 ~ 2025-01
        # 起始年 = 2015
        # 结束年 = 2025
        start_year = full_index[0].year
        end_year = full_index[-1].year

        windows: List[Dict] = []

        # 第一个 train 段：[start_year, start_year+train_years)
        # 第一个 test 段：[start_year+train_years, start_year+train_years+test_years)
        # 滑窗：train 起点每年 +1
        train_start_year = start_year
        train_end_year = (
            train_start_year
            + self.train_years
        )
        test_start_year = train_end_year
        test_end_year = (
            test_start_year
            + self.test_years
        )

        while test_end_year <= (
            end_year + 1
        ):

            # 找 train_start_idx
            # 第一个 >= train_start_year-01-01 的位置
            train_start_ts = pd.Timestamp(
                year=train_start_year,
                month=1,
                day=1,
            )
            train_end_ts = pd.Timestamp(
                year=train_end_year,
                month=1,
                day=1,
            )
            test_start_ts = pd.Timestamp(
                year=test_start_year,
                month=1,
                day=1,
            )
            test_end_ts = pd.Timestamp(
                year=test_end_year,
                month=1,
                day=1,
            )

            # 索引位置
            # 用 searchsorted 找最近的位置
            train_start_idx = (
                full_index
                .searchsorted(
                    train_start_ts,
                    side="left"
                )
            )
            train_end_idx = (
                full_index
                .searchsorted(
                    train_end_ts,
                    side="left"
                )
            )
            test_start_idx = (
                full_index
                .searchsorted(
                    test_start_ts,
                    side="left"
                )
            )
            test_end_idx = (
                full_index
                .searchsorted(
                    test_end_ts,
                    side="left"
                )
            )

            # 防止越界
            n = len(full_index)
            train_start_idx = max(
                0, min(train_start_idx, n)
            )
            train_end_idx = max(
                0, min(train_end_idx, n)
            )
            test_start_idx = max(
                0, min(test_start_idx, n)
            )
            test_end_idx = max(
                0, min(test_end_idx, n)
            )

            # 至少要 1 根 bar
            if (
                train_end_idx
                <= train_start_idx
            ):
                break

            if (
                test_end_idx
                <= test_start_idx
            ):
                break

            windows.append({
                "train_start_idx": (
                    train_start_idx
                ),
                "train_end_idx": (
                    train_end_idx
                ),
                "test_start_idx": (
                    test_start_idx
                ),
                "test_end_idx": (
                    test_end_idx
                ),
                "train_start_ts": (
                    full_index[train_start_idx]
                ),
                "train_end_ts": (
                    full_index[
                        min(
                            train_end_idx - 1,
                            n - 1
                        )
                    ]
                ),
                "test_start_ts": (
                    full_index[test_start_idx]
                ),
                "test_end_ts": (
                    full_index[
                        min(
                            test_end_idx - 1,
                            n - 1
                        )
                    ]
                ),
                "train_period": (
                    f"{train_start_year}"
                    f"-{train_end_year - 1}"
                ),
                "test_period": (
                    f"{test_start_year}"
                ),
            })

            # 滑窗
            train_start_year += 1
            train_end_year += 1
            test_start_year += 1
            test_end_year += 1

        return windows

    def slice_data(
        self,
        data: Dict,
        start_idx: int,
        end_idx: int,
    ) -> Dict:
        # 按 idx 范围切 data
        sliced = {}
        first_sym = list(data.keys())[0]
        sub_index = (
            data[first_sym]
            .index[start_idx:end_idx]
        )
        for sym, df in data.items():

            sliced[sym] = df.loc[sub_index]

        return sliced


class WalkForwardRunner:
    # V2.2 正式版
    #
    # 集成：
    #   - ParallelOptimizer（V2.1 多进程）
    #   - ValidationRunner（V1.8 双引擎验证）
    #   - EventEngine（精确回测）
    #
    # 三阶段：
    #   1) Train  → optimizer.run(train_data)
    #                → top_train_params（top_k）
    #   2) Val    → validation_runner.validate_top_n(...)
    #                → top_val_params（consistency OK）
    #   3) Test   → event_engine.run(best_params, test_data)
    #                → test_result
    #
    # 输出：WalkForwardResultV2
    #   - stitched_equity_curve（所有 test 段拼接）
    #   - stability_score
    #   - parameter_drift

    def __init__(
        self,
        optimizer,
        validation_runner,
        event_engine,
        train_years: int = 3,
        test_years: int = 1,
        top_train: int = 5,
        top_val: int = 1,
    ):

        self.optimizer = optimizer
        self.validation_runner = (
            validation_runner
        )
        self.event_engine = event_engine
        self.train_years = train_years
        self.test_years = test_years
        self.top_train = top_train
        self.top_val = top_val

        self.window_generator = WindowGenerator(
            train_years=train_years,
            test_years=test_years,
        )

    def run(
        self,
        data: Dict,
        param_space: Dict,
    ) -> WalkForwardResultV2:
        # 跑完整 walk forward
        #
        # 每个 window：
        #   1) 切 train_data / test_data
        #   2) 清 factor_cache（关键！）
        #   3) optimizer.run(train_data) → top_train
        #   4) validation_runner.validate_top_n → top_val
        #   5) best_params = top_val[0].params
        #   6) event_engine.run(best_params, test_data)
        #   7) 记录 WalkForwardWindowV2
        #   8) 拼接 equity
        #
        # 最终：stitched + stability + drift

        # ---- 1) 生成窗口 ----
        windows_meta = (
            self.window_generator
            .generate(data)
        )

        if not windows_meta:
            return WalkForwardResultV2()

        result = WalkForwardResultV2()

        # ---- 2) 逐窗口跑 ----
        for meta in windows_meta:

            # 清 factor_cache
            # 切到新窗口必须清
            # 防止 train 段缓存的 ma_X(length=600)
            # 在 test 段被错误复用
            from ..data.cache import (
                factor_cache
            )
            factor_cache.clear()

            train_data = (
                self
                .window_generator
                .slice_data(
                    data,
                    meta["train_start_idx"],
                    meta["train_end_idx"],
                )
            )
            test_data = (
                self
                .window_generator
                .slice_data(
                    data,
                    meta["test_start_idx"],
                    meta["test_end_idx"],
                )
            )

            # ---- 2.1) Train 优化 ----
            train_df = self.optimizer.run(
                data=train_data,
                param_space=param_space,
            )

            if train_df is None or (
                train_df.empty
            ):
                # 训练失败
                # 该窗口记为空
                win = WalkForwardWindowV2(
                    train_period=meta[
                        "train_period"
                    ],
                    test_period=meta[
                        "test_period"
                    ],
                    train_start=meta[
                        "train_start_ts"
                    ],
                    train_end=meta[
                        "train_end_ts"
                    ],
                    test_start=meta[
                        "test_start_ts"
                    ],
                    test_end=meta[
                        "test_end_ts"
                    ],
                )
                result.windows.append(win)
                continue

            # 提取 top_train
            # train_df 含 params (dict) + score
            top_train_params = (
                self._extract_top_params(
                    train_df, self.top_train
                )
            )

            train_score = (
                float(
                    train_df["score"].max()
                )
                if "score" in train_df.columns
                else 0.0
            )

            # ---- 2.2) Val 验证 ----
            # 用 train_data 跑 top_train
            # 选 consistency OK 的
            val_df = (
                self
                .validation_runner
                .validate_top_n(
                    optimizer_result=train_df,
                    strategy_cls=(
                        self
                        .optimizer
                        .strategy_cls
                    ),
                    data=train_data,
                    top_n=self.top_train,
                )
            )

            top_val_params = []
            if val_df is not None and (
                not val_df.empty
            ):

                # 取 passed == OK
                if "passed" in val_df.columns:

                    ok_df = val_df[
                        val_df["passed"] == "OK"
                    ]

                else:
                    ok_df = val_df

                # 提取 params dict
                # val_df "params" 列是 str
                # 需要从 train_df 找回原 dict
                top_val_params = (
                    self._extract_top_params(
                        ok_df.head(self.top_val),
                        self.top_val,
                        params_as_str=True,
                    )
                )

            val_score = 0.0
            if val_df is not None and (
                not val_df.empty
            ) and (
                "consistency" in val_df.columns
            ):

                val_score = float(
                    val_df["consistency"].max()
                )

            # ---- 2.3) 选 best_params ----
            # 优先 top_val
            # 退而求其次 top_train[0]
            if top_val_params:
                best_params = (
                    top_val_params[0]
                )
            elif top_train_params:
                best_params = (
                    top_train_params[0]
                )
            else:
                # 实在没参数，跳过
                win = WalkForwardWindowV2(
                    train_period=meta[
                        "train_period"
                    ],
                    test_period=meta[
                        "test_period"
                    ],
                    train_start=meta[
                        "train_start_ts"
                    ],
                    train_end=meta[
                        "train_end_ts"
                    ],
                    test_start=meta[
                        "test_start_ts"
                    ],
                    test_end=meta[
                        "test_end_ts"
                    ],
                )
                result.windows.append(win)
                continue

            # 强制 int 参数
            # rolling(10.0) 会报错
            best_params = {
                k: (
                    int(v)
                    if isinstance(
                        v, float
                    )
                    and v.is_integer()
                    else v
                )
                for k, v
                in best_params.items()
            }

            # ---- 2.4) Test 测试 ----
            # event_engine 跑 test 段
            #
            # 关键 bug 修复：
            #   event_engine.strategy 是 init 时绑的
            #   engine.run(strategy=None) 时
            #   不会用 params 重新构造
            #   也不接受 new strategy（除非传 strategy=）
            #
            #   V1.9 Experiment.run() 接受
            #   strategy=None + params={...}
            #   但只更新 self.strategy（如果 strategy is not None）
            #   不传时直接用 self.strategy
            #
            #   所以这里必须：
            #     a) deepcopy event_engine
            #     b) 把 best_params 注入新 strategy
            #     c) 覆盖 engine.strategy
            from .experiment import (
                Experiment
            )

            test_engine_copy = copy.deepcopy(
                self.event_engine
            )

            # 显式构造新 strategy
            # 注入 best_params
            test_strategy = (
                self
                .optimizer
                .strategy_cls(
                    **best_params
                )
            )

            # 覆盖 engine.strategy
            # 之后 engine.run() 用新 strategy
            test_engine_copy.strategy = (
                test_strategy
            )

            test_result = Experiment(
                name=(
                    f"wf_v2_"
                    f"{meta['test_period']}"
                )
            ).run(
                strategy=None,
                engine=test_engine_copy,
                data=test_data,
                params=best_params,
            )

            test_win = WalkForwardWindowV2(
                train_period=meta[
                    "train_period"
                ],
                test_period=meta[
                    "test_period"
                ],
                train_start=meta[
                    "train_start_ts"
                ],
                train_end=meta[
                    "train_end_ts"
                ],
                test_start=meta[
                    "test_start_ts"
                ],
                test_end=meta[
                    "test_end_ts"
                ],
                top_train_params=(
                    top_train_params
                ),
                top_val_params=(
                    top_val_params
                ),
                best_params=best_params,
                train_score=train_score,
                val_score=val_score,
                test_result=test_result,
                test_return=(
                    test_result.metrics.get(
                        "total_return", 0.0
                    )
                ),
                test_sharpe=(
                    test_result.metrics.get(
                        "sharpe", 0.0
                    )
                ),
                test_max_dd=(
                    test_result.metrics.get(
                        "max_drawdown", 0.0
                    )
                ),
                test_trades=(
                    test_result.metrics.get(
                        "trade_count", 0
                    )
                ),
            )
            result.windows.append(test_win)

            # ---- 2.5) Stitching ----
            # 拼接 equity_curve
            # 关键：去掉重复的边界点
            eq = test_result.equity_curve
            ts = test_result.timestamps

            if not eq:
                continue

            if (
                result
                .stitched_equity_curve
            ):
                # 跳过第一个（和上一窗口尾点重复）
                if len(eq) > 1:
                    result.stitched_equity_curve.extend(
                        eq[1:]
                    )
                if (
                    ts
                    and len(ts) > 1
                ):
                    result.stitched_timestamps.extend(
                        ts[1:]
                    )
            else:
                result.stitched_equity_curve.extend(
                    eq
                )
                if ts:
                    result.stitched_timestamps.extend(
                        ts
                    )

        # ---- 3) 汇总指标 ----
        if result.windows:
            test_sharpes = [
                w.test_sharpe
                for w in result.windows
                if w.test_result
            ]
            test_returns = [
                w.test_return
                for w in result.windows
                if w.test_result
            ]
            test_dds = [
                w.test_max_dd
                for w in result.windows
                if w.test_result
            ]

            if test_sharpes:
                result.avg_test_sharpe = (
                    sum(test_sharpes)
                    / len(test_sharpes)
                )
            if test_returns:
                result.avg_test_return = (
                    sum(test_returns)
                    / len(test_returns)
                )
            if test_dds:
                result.avg_test_max_dd = (
                    sum(test_dds)
                    / len(test_dds)
                )

        # ---- 4) Stitched metrics ----
        if result.stitched_equity_curve:
            from ..analytics import (
                sharpe_ratio,
                max_drawdown,
                total_return,
            )
            eq = (
                result.stitched_equity_curve
            )
            result.stitched_metrics = {
                "sharpe": round(
                    sharpe_ratio(eq), 3
                ),
                "max_drawdown": round(
                    max_drawdown(eq) * 100, 2
                ),
                "total_return": round(
                    total_return(eq) * 100, 2
                ),
                "n_points": len(eq),
            }

        # ---- 5) Stability score ----
        # 综合：
        #   a) 参数重复率：最频繁的 best_params 占多少
        #   b) 平均排名：best_params 在 val 阶段的平均 rank
        #   c) OOS 收益：avg_test_return
        # 简单加权：(a*0.4 + b*0.3 + c*0.3) 归一化
        result.best_params_freq = (
            self._compute_params_freq(
                result.windows
            )
        )
        result.stability_score = (
            self._compute_stability_score(
                result
            )
        )
        result.parameter_drift = (
            self._compute_parameter_drift(
                result.windows
            )
        )

        # ---- 6) Summary ----
        result.summary = {
            "n_windows": len(
                result.windows
            ),
            "n_passed": sum(
                1
                for w in result.windows
                if w.test_result
            ),
            "train_years": self.train_years,
            "test_years": self.test_years,
            "best_params_each_window": [
                w.best_params
                for w in result.windows
            ],
        }

        return result

    # ----------------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------------

    def _extract_top_params(
        self,
        df,
        n: int,
        params_as_str: bool = False,
        param_keys: List[str] = None,
    ) -> List[Dict]:
        # 从 optimizer / validation DataFrame 提取 top n 组 params
        #
        # 关键：
        #   ParallelOptimizer.run 返回的 DataFrame
        #   把 {'params': {'fast': 10, 'slow': 60}}
        #   自动展平为 fast / slow 单独列
        #   （pandas 嵌套 dict 转列的行为）
        #
        #   所以"params"列通常不存在
        #   必须从所有非指标列重建 params dict
        #
        #   ValidationRunner.validate_top_n 返回的
        #   DataFrame 含 'params' 列（str）
        #   用 ast.literal_eval 反解
        #
        # param_keys:
        #   None → 自动推断（除指标列）
        #   显式传入 → 严格用传入的列名

        if df is None or df.empty:
            return []

        # 按 score 倒序
        if "score" in df.columns:
            sorted_df = (
                df
                .sort_values(
                    "score",
                    ascending=False
                )
                .head(n)
                .reset_index(drop=True)
            )
        else:
            sorted_df = df.head(n)

        # 自动推断 param_keys
        # 排除所有指标列
        if param_keys is None:

            EXCLUDE = {
                "score",
                "source",
                "total_return",
                "sharpe",
                "max_drawdown",
                "error",
                "early_kill",
                "trade_count",
                "final_equity",
                "rank",
                "consistency",
                "passed",
                "params",
            }
            param_keys = [
                c for c
                in sorted_df.columns
                if c not in EXCLUDE
            ]

        result = []
        for _, row in sorted_df.iterrows():

            # ---- 路径 1: val_df ----
            # 含 'params' 列（str）
            if (
                params_as_str
                and "params" in row
                and isinstance(
                    row["params"], str
                )
            ):

                import ast
                try:

                    p = ast.literal_eval(
                        row["params"]
                    )
                except Exception:

                    continue

                if not isinstance(p, dict):
                    continue

                result.append(p)
                continue

            # ---- 路径 2: train_df ----
            # pandas 展平了嵌套 dict
            # 用 param_keys 重建
            if not param_keys:
                continue

            p = {
                k: row[k]
                for k in param_keys
                if k in row
            }
            if not p:
                continue

            result.append(p)

        return result

    def _compute_params_freq(
        self,
        windows: List[WalkForwardWindowV2],
    ) -> Dict:
        # 统计每组 best_params 出现次数
        #
        # key: frozenset(params.items())（顺序无关）
        # value: 次数

        keys = []
        for w in windows:
            if w.best_params:
                keys.append(
                    str(
                        sorted(
                            w.best_params.items()
                        )
                    )
                )

        freq = dict(
            Counter(keys)
        )
        return freq

    def _compute_stability_score(
        self,
        result: WalkForwardResultV2,
    ) -> float:
        # 综合稳定性评分
        #
        # 三因子：
        #   a) param_consistency
        #      = 最频繁 best_params 占比
        #      0~1，1 最稳定
        #   b) oos_return_score
        #      = avg_test_return / 100，截断到 [0, 1]
        #      假设 >100% 才满分
        #   c) n_passed_ratio
        #      = n_passed / n_windows
        #      0~1
        #
        # 加权：0.5 * a + 0.2 * b + 0.3 * c

        n_windows = len(result.windows)
        if n_windows == 0:
            return 0.0

        # a) param_consistency
        freq = result.best_params_freq
        if freq:
            max_freq = max(freq.values())
            param_consistency = (
                max_freq / n_windows
            )
        else:
            param_consistency = 0.0

        # b) oos_return_score
        # 把 avg_test_return (%, 可能负) 转 0~1
        oos_return_score = max(
            0.0,
            min(
                1.0,
                result.avg_test_return / 50.0,
            ),
        )

        # c) n_passed_ratio
        n_passed = sum(
            1
            for w in result.windows
            if w.test_result
        )
        n_passed_ratio = (
            n_passed / n_windows
        )

        score = (
            0.5 * param_consistency
            + 0.2 * oos_return_score
            + 0.3 * n_passed_ratio
        )
        return round(score, 4)

    def _compute_parameter_drift(
        self,
        windows: List[WalkForwardWindowV2],
    ) -> float:
        # 相邻窗口 best_params 的平均欧氏距离
        #
        # 欧氏距离 = sqrt(sum((p_i - q_i)^2))
        # 只对数值型参数算
        # 归一化到参数绝对值的平均

        param_windows = [
            w for w in windows
            if w.best_params
        ]

        if len(param_windows) < 2:
            return 0.0

        distances = []
        for i in range(
            len(param_windows) - 1
        ):
            p1 = param_windows[i].best_params
            p2 = param_windows[
                i + 1
            ].best_params

            common_keys = (
                set(p1.keys())
                & set(p2.keys())
            )
            numeric_keys = [
                k for k in common_keys
                if isinstance(
                    p1[k], (int, float)
                )
                and isinstance(
                    p2[k], (int, float)
                )
            ]

            if not numeric_keys:
                continue

            sq_sum = sum(
                (p1[k] - p2[k]) ** 2
                for k in numeric_keys
            )
            dist = sq_sum ** 0.5

            # 归一化：用参数平均绝对值
            scale = max(
                sum(
                    abs(p1[k])
                    for k in numeric_keys
                )
                / max(len(numeric_keys), 1),
                1e-9,
            )

            distances.append(dist / scale)

        if not distances:
            return 0.0

        return round(
            sum(distances) / len(distances), 4
        )


class WalkForwardReport:
    # V2.2 HTML 报告
    #
    # 输出：reports/wf_report.html
    # 内容：
    #   - OOS equity 曲线（matplotlib）
    #   - 参数变化（每窗口 best_params）
    #   - 样本外指标
    #   - Stability / Drift
    #
    # 关键：用 Agg backend
    # 沙箱里无显示器

    def __init__(self, result: WalkForwardResultV2):
        self.result = result

    def to_html(
        self,
        output_path: str = None,
    ) -> str:
        # 生成 HTML 报告
        #
        # output_path: 写到文件
        # 同时返回 HTML 字符串

        import os

        os.environ.setdefault(
            "MPLBACKEND", "Agg"
        )

        r = self.result

        # 1) Equity 曲线图
        equity_png = self._plot_equity()

        # 2) 参数变化图
        param_png = self._plot_params()

        # 3) HTML 拼装
        stitched = r.stitched_metrics

        windows_rows = ""
        for i, w in enumerate(r.windows):

            bp_str = str(w.best_params)
            windows_rows += (
                "<tr>"
                f"<td>{i + 1}</td>"
                f"<td>{w.train_period}</td>"
                f"<td>{w.test_period}</td>"
                f"<td>{bp_str}</td>"
                f"<td>{w.test_return:.2f}</td>"
                f"<td>{w.test_sharpe:.3f}</td>"
                f"<td>{w.test_max_dd:.2f}</td>"
                f"<td>{w.test_trades}</td>"
                "</tr>"
            )

        params_freq_rows = ""
        for k, v in r.best_params_freq.items():

            params_freq_rows += (
                "<tr>"
                f"<td>{k}</td>"
                f"<td>{v}</td>"
                "</tr>"
            )

        html = f"""
<html>
<head>
<meta charset="utf-8">
<title>Walk-Forward Report V2.2</title>
<style>
  body {{
    font-family: Arial, sans-serif;
    margin: 20px;
    background: #fafafa;
  }}
  h1 {{
    color: #333;
  }}
  h2 {{
    color: #666;
    border-bottom: 1px solid #ddd;
    padding-bottom: 4px;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 10px 0;
  }}
  th, td {{
    border: 1px solid #ccc;
    padding: 6px 10px;
    text-align: left;
  }}
  th {{
    background: #eee;
  }}
  .metric {{
    display: inline-block;
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 10px 16px;
    margin: 6px;
    min-width: 140px;
  }}
  .metric .label {{
    color: #888;
    font-size: 12px;
  }}
  .metric .value {{
    font-size: 20px;
    font-weight: bold;
    color: #333;
  }}
  img {{
    background: #fff;
    border: 1px solid #ddd;
    padding: 8px;
    max-width: 100%;
  }}
</style>
</head>
<body>
<h1>Walk-Forward Report V2.2</h1>

<h2>Stitched OOS Metrics</h2>
<div>
  <div class="metric">
    <div class="label">Sharpe</div>
    <div class="value">
      {stitched.get("sharpe", 0)}
    </div>
  </div>
  <div class="metric">
    <div class="label">Total Return (%)</div>
    <div class="value">
      {stitched.get("total_return", 0)}
    </div>
  </div>
  <div class="metric">
    <div class="label">Max Drawdown (%)</div>
    <div class="value">
      {stitched.get("max_drawdown", 0)}
    </div>
  </div>
  <div class="metric">
    <div class="label">Stability Score</div>
    <div class="value">
      {r.stability_score}
    </div>
  </div>
  <div class="metric">
    <div class="label">Parameter Drift</div>
    <div class="value">
      {r.parameter_drift}
    </div>
  </div>
</div>

<h2>OOS Equity Curve</h2>
<img src="data:image/png;base64,{equity_png}" />

<h2>Parameter Drift Across Windows</h2>
<img src="data:image/png;base64,{param_png}" />

<h2>Windows ({len(r.windows)})</h2>
<table>
  <tr>
    <th>#</th>
    <th>Train Period</th>
    <th>Test Period</th>
    <th>Best Params</th>
    <th>Test Return (%)</th>
    <th>Test Sharpe</th>
    <th>Test MaxDD (%)</th>
    <th>Trades</th>
  </tr>
  {windows_rows}
</table>

<h2>Best Params Frequency</h2>
<table>
  <tr><th>Params</th><th>Count</th></tr>
  {params_freq_rows}
</table>

</body>
</html>
        """

        if output_path:
            import os
            os.makedirs(
                os.path.dirname(
                    output_path
                ),
                exist_ok=True,
            )
            with open(
                output_path, "w",
                encoding="utf-8",
            ) as f:
                f.write(html)

        return html

    def _plot_equity(self) -> str:
        # 画 OOS equity 曲线
        # 返回 base64 PNG
        import base64
        import io

        os.environ.setdefault(
            "MPLBACKEND", "Agg"
        )
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        r = self.result

        fig, ax = plt.subplots(
            figsize=(10, 4)
        )

        if r.stitched_equity_curve:
            ax.plot(
                r.stitched_equity_curve,
                color="steelblue",
                linewidth=1.2,
            )
            ax.set_title(
                "Stitched OOS Equity Curve"
            )
            ax.set_xlabel("Bar")
            ax.set_ylabel("Equity")
            ax.grid(True, alpha=0.3)
        else:
            ax.text(
                0.5, 0.5,
                "No equity data",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )

        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            bbox_inches="tight",
            dpi=80,
        )
        plt.close(fig)

        return base64.b64encode(
            buf.getvalue()
        ).decode("ascii")

    def _plot_params(self) -> str:
        # 画参数变化图
        # 每个数值参数一条线
        import base64
        import io

        os.environ.setdefault(
            "MPLBACKEND", "Agg"
        )
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        r = self.result

        # 收集每个窗口的 params
        param_series: Dict[str, List] = {}

        for w in r.windows:
            if not w.best_params:
                continue

            for k, v in w.best_params.items():

                if not isinstance(
                    v, (int, float)
                ):
                    continue

                if k not in param_series:
                    param_series[k] = []

                param_series[k].append(v)

        fig, ax = plt.subplots(
            figsize=(10, 4)
        )

        if param_series:
            for k, v in param_series.items():

                ax.plot(
                    v,
                    marker="o",
                    label=k,
                    linewidth=1.2,
                )

            ax.set_title(
                "Best Params Across Windows"
            )
            ax.set_xlabel("Window #")
            ax.set_ylabel("Param Value")
            ax.legend()
            ax.grid(True, alpha=0.3)
        else:
            ax.text(
                0.5, 0.5,
                "No params data",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )

        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            bbox_inches="tight",
            dpi=80,
        )
        plt.close(fig)

        return base64.b64encode(
            buf.getvalue()
        ).decode("ascii")
