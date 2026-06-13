"""
ParallelOptimizer - V2.1.1

多进程并行网格搜索 + 三个性能优化：

1) initializer 全局 data
   旧版每次 submit 把 data 序列化一次
   11250 组 → 11250 次拷贝 → 巨慢
   新版：主进程 initializer 一次
         子进程通过 _WORKER_DATA 全局变量读
         序列化 0 次

2) early_filter
   旧版：每组都跑完整回测
   新版：先跑 30% 数据（early_split）
         如果 early_sharpe < 0 或 early_ret < 0
         直接淘汰，不跑 full
   经验：80% 参数会被早死

3) top_k
   旧版：内存里塞 11250 行
   新版：只保留 Sharpe 最高的 k 组
         用 min-heap，O(n log k)

设计：
- 不用 lambda factory
  改成 engine_spec=(type, kwargs) 元组
  worker 内按 type 派发，避免 pickling 闭包
- 不用 class 传 strategy
  改成 strategy_path="pkg.mod.Class"
  worker 内 importlib 拿 class
"""

import os
import importlib
import heapq
import pandas as pd

from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)

from .core.base_engine import (
    BaseBacktestEngine,
)
from .optimizer import (
    generate_param_grid,
)


# ============================================================
# Worker 进程全局变量
# 由 _init_worker 一次性初始化
# ============================================================

_WORKER_DATA = None
_WORKER_ENGINE = None
_WORKER_STRATEGY_CLS = None
_WORKER_EARLY_SPLIT = 0.3


def _init_worker(data, engine_spec, strategy_path, early_split):
    # 进程内 init
    # 只做一次：data 一次性塞进 worker 内存
    # engine 也构造一次

    global _WORKER_DATA
    global _WORKER_ENGINE
    global _WORKER_STRATEGY_CLS
    global _WORKER_EARLY_SPLIT

    _WORKER_DATA = data
    _WORKER_EARLY_SPLIT = early_split

    # 构造 engine
    # 按 type 派发
    _WORKER_ENGINE = _build_engine(engine_spec)

    # 拿 strategy class
    # "quantlab.signals" + "MACrossStrategy"
    module_path, cls_name = (
        strategy_path.rsplit(".", 1)
    )
    mod = importlib.import_module(
        module_path
    )
    _WORKER_STRATEGY_CLS = getattr(
        mod, cls_name
    )

    # 子进程 spawn 后 factor_cache 是 fresh
    # 但 main 进程可能被 stage 8 verification 污染过
    # 强制清空一次
    try:

        from .data.cache import (
            factor_cache,
        )

        factor_cache.clear()

    except Exception:

        pass

    # 预热 numba / vectorbt
    # 子进程第一次 JIT 偶尔 SIGABRT
    # 提前跑一次 dummy backtest
    # 触发 numba 编译、VectorBT 内部 cache
    # 但预热 + factor_cache 时序复杂
    # 暂时关掉，看 basic flow
    # try:
    #
    #     _warmup_engine()
    #
    # except Exception:
    #
    #     pass
    pass


def _warmup_engine():
    # 子进程预热
    # 跑一次最小 backtest
    # 让 numba JIT、VectorBT 内部 state 准备好
    # 否则第一个真任务偶发 SIGABRT
    #
    # 关键：预热前后清 factor_cache
    # 否则缓存的短 Series 会被后续 full 任务错误命中
    # 触发 "identically-labeled Series" 错误

    if (
        not _WORKER_DATA
        or not _WORKER_ENGINE
    ):
        return

    try:

        from .data.cache import (
            factor_cache,
        )

        factor_cache.clear()

        first_sym = next(
            iter(_WORKER_DATA.keys())
        )
        mini_data = {
            first_sym: (
                _WORKER_DATA[first_sym]
                .iloc[:50]
                .copy()
            )
        }

        strat = _WORKER_STRATEGY_CLS()
        _WORKER_ENGINE.run(
            strategy=strat,
            data=mini_data,
            params={},
        )

        # 预热完清空 cache
        # 防止短 bars 的因子污染 full 阶段
        factor_cache.clear()

    except Exception:

        pass


def _build_engine(engine_spec):
    # engine_spec = (type_str, kwargs_dict)
    #
    # "vectorbt"  → VectorBTAdapter
    # "bar"       → BarEngine
    # "event"     → EventEngine

    if not isinstance(engine_spec, tuple):

        raise ValueError(
            "engine_spec must be (type, kwargs)"
        )

    engine_type, kwargs = engine_spec

    if engine_type == "vectorbt":

        from .adapters import (
            VectorBTAdapter
        )
        return VectorBTAdapter(**kwargs)

    if engine_type == "bar":

        from .engine import BarEngine
        return BarEngine(**kwargs)

    if engine_type == "event":

        from .engine import (
            EventEngine
        )
        return EventEngine(**kwargs)

    raise ValueError(
        f"unknown engine type: {engine_type}"
    )


def _slice_data(data, ratio):
    # 拿前 ratio 比例的 data
    # 用于 early filter

    sliced = {}

    for sym, df in data.items():

        n = max(int(len(df) * ratio), 30)
        sliced[sym] = df.iloc[:n].copy()

    return sliced


def _min_bars_for_strategy(params):
    # 自动推算最小 bars
    # 找 params 里所有 'period' / 'slow' / 'long' / 'window'
    # 之类的键，取最大

    keys_long = (
        "slow",
        "long",
        "window",
        "lookback",
        "period",
    )
    max_v = 0

    for k, v in params.items():

        if any(
            k.endswith(suffix)
            or k.startswith(suffix)
            for suffix in keys_long
        ):

            try:
                max_v = max(max_v, int(v))
            except (TypeError, ValueError):
                pass

    # 默认 30
    return max(max_v, 30)


def _evaluate_one(params):
    # 进程内工作函数
    # 用 _WORKER_* 全局变量
    # 不传 data、不传 engine、不传 class

    try:

        # 清 factor_cache
        # 关键：因子缓存是 module-level singleton
        # 跨 _evaluate_one 调用会污染
        # 比如：
        #   eval 1 算 ma(60) on 200 bars → 缓存
        #   eval 2 算 ma(60) on 300 bars → hit 200 bars 错位
        try:

            from .data.cache import (
                factor_cache,
            )

            factor_cache.clear()

        except Exception:

            pass

        strategy = _WORKER_STRATEGY_CLS(
            **params
        )

        # ---- 1) Early filter ----
        # 用前 30% 数据先跑
        # 收益/score < 0 → 早死
        if (
            _WORKER_EARLY_SPLIT
            and _WORKER_EARLY_SPLIT > 0
            and _WORKER_EARLY_SPLIT < 1
        ):

            early_data = _slice_data(
                _WORKER_DATA,
                _WORKER_EARLY_SPLIT,
            )

            early_result = (
                _WORKER_ENGINE.run(
                    strategy=strategy,
                    data=early_data,
                    params=params,
                )
            )

            if (
                not early_result.ok()
                or early_result.total_return < 0
                or early_result.sharpe < 0
            ):

                return {
                    "params": params,
                    "score": float("-inf"),
                    "early_kill": True,
                    "early_return": (
                        early_result.total_return
                        if early_result.ok()
                        else None
                    ),
                    "early_sharpe": (
                        early_result.sharpe
                        if early_result.ok()
                        else None
                    ),
                }

        # ---- 2) Full run ----
        # 关键：early filter 跑过一遍后
        # factor_cache 里被填了"短数据"的 Series
        # （例如 rsi(9) on 90 bars）
        # 必须在 full run 前再清一次
        # 否则 full run 命中"短 Series" cache
        # 和 300 bars 的 data index 不匹配
        # 导致所有 signal == 0，trades == 0
        try:

            from .data.cache import (
                factor_cache,
            )

            factor_cache.clear()

        except Exception:

            pass

        result = _WORKER_ENGINE.run(
            strategy=strategy,
            data=_WORKER_DATA,
            params=params,
        )

        if not result.ok():

            return {
                "params": params,
                "score": float("-inf"),
                "error": (
                    result.error or "unknown"
                ),
            }

        row = {}
        # 展平 params（dict 放进 row 会让 df 显示很乱）
        for k, v in params.items():
            row[k] = v
        row["score"] = result.sharpe
        row["source"] = result.source
        row["total_return"] = (
            result.total_return
        )
        row["sharpe"] = result.sharpe
        row["max_drawdown"] = (
            result.max_drawdown
        )
        row["trade_count"] = (
            result.trade_count
        )
        row["final_equity"] = (
            result.final_equity
        )

        return row

    except Exception as e:

        return {
            "params": params,
            "score": float("-inf"),
            "error": repr(e),
        }


# ============================================================
# ParallelOptimizer 主类
# ============================================================

class ParallelOptimizer:

    # 三档优化全开：
    #   - initializer（不传 data）
    #   - early_filter（早死）
    #   - top_k（内存上限）

    def __init__(
        self,
        strategy_cls,
        engine_spec,
        max_workers: int = None,
        top_k: int = 0,
        early_split: float = 0.3,
    ):

        # strategy_cls: 策略类
        # engine_spec: ("vectorbt", {"fees": 0.0003})
        # top_k: 0 = 不限
        # early_split: 0~1, 0 = 关闭

        self.strategy_cls = strategy_cls
        self.engine_spec = engine_spec
        self.max_workers = (
            max_workers
            or os.cpu_count()
            or 4
        )
        self.top_k = top_k
        self.early_split = early_split

        # 解析 strategy 路径
        # 全限定名：pkg.mod.Class
        self.strategy_path = (
            f"{strategy_cls.__module__}"
            f".{strategy_cls.__name__}"
        )

    def _worker_init(self):

        # ProcessPoolExecutor 的 initializer
        # 用闭包传参
        # 这是 ProcessPool 的标准模式

        data = self._data
        return _init_worker(
            data=data,
            engine_spec=self.engine_spec,
            strategy_path=self.strategy_path,
            early_split=self.early_split,
        )

    def run(
        self,
        data,
        param_space: dict,
    ) -> pd.DataFrame:

        # ---- 1) 准备 ----
        self._data = data
        combos = list(
            generate_param_grid(param_space)
        )

        n = len(combos)

        if n == 0:

            return pd.DataFrame()

        # ---- 2) 并行 ----
        # 默认 ProcessPool
        # 但 VBT + numba 在子进程偶发 SIGABRT
        # 这种情况下用 ThreadPool（numba 内部会释放 GIL）
        executor_cls = (
            ThreadPoolExecutor
            if os.environ.get(
                "PARALLEL_USE_THREAD", "0"
            ) == "1"
            else ProcessPoolExecutor
        )
        with executor_cls(
            max_workers=self.max_workers,
            initializer=_init_worker,
            initargs=(
                data,
                self.engine_spec,
                self.strategy_path,
                self.early_split,
            ),
        ) as ex:

            futures = {
                ex.submit(
                    _evaluate_one, params
                ): i
                for i, params in enumerate(combos)
            }

            # ---- 3) 收集（top_k）----
            # 用 min-heap
            # 始终保持 k 个最高 score
            # 加 idx 防 score 相等时比 dict 报错
            # 拒绝 -inf / 负分（连 -inf 也算"垃圾参数"）
            if self.top_k > 0:

                heap = []
                counter = 0

                for fut in as_completed(futures):

                    row = fut.result()
                    score = row.get(
                        "score", float("-inf")
                    )

                    # -inf = 早死 / NaN 都不要
                    # 但允许负分（数据噪声）
                    if (
                        not isinstance(
                            score, (int, float)
                        )
                        or score != score  # NaN
                        or score == float("-inf")
                    ):
                        continue

                    if (
                        len(heap)
                        < self.top_k
                    ):
                        heapq.heappush(
                            heap,
                            (score, counter, row),
                        )
                        counter += 1

                    elif (
                        score
                        > heap[0][0]
                    ):
                        heapq.heapreplace(
                            heap,
                            (score, counter, row),
                        )
                        counter += 1

                rows = [
                    r
                    for _, _, r in sorted(
                        heap,
                        key=lambda x: -x[0],
                    )
                ]

            else:

                for fut in as_completed(futures):

                    rows.append(fut.result())

        if not rows:

            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # 排序（top_k 模式下已排过）
        if self.top_k <= 0:

            df = df.sort_values(
                "score",
                ascending=False,
            ).reset_index(drop=True)

        return df

    def evaluate(
        self,
        data,
        params: dict,
    ):
        # 单次评估（不开进程）
        # 用于 API 一致性 + 调试

        engine = _build_engine(self.engine_spec)
        strategy = self.strategy_cls(
            **params
        )
        result = engine.run(
            strategy=strategy,
            data=data,
            params=params,
        )

        if not result.ok():

            return {
                "params": params,
                "score": float("-inf"),
                "error": result.error,
            }

        return {
            "params": params,
            "score": result.sharpe,
            "result": result,
        }
