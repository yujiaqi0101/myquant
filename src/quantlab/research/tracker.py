"""
V2.3 Experiment Tracking — Tracker

实验追踪：
  - ExperimentRecord   实验元数据 dataclass
  - ExperimentResultV2 一次实验 + 结果的完整绑定
  - ExperimentTracker  自动跑 + 自动入库

数据流：

  ExperimentRecord + strategy_cls + engine + data
        |
        v
  ExperimentTracker.run(...)
        |
        |---> engine.run()       -> BacktestResult
        |
        |---> ExperimentResultV2
        |
        '---> repo.save(...)      -> SQLite

为什么这一步极其重要：
  - Random Search / Bayesian Optimization
    几十万组参数
  - 没有 Tracking
    会变成：
      "这个策略为什么好？"
      不知道
      "这个参数哪里来的？"
      不知道
"""


import json
import uuid
from dataclasses import (
    dataclass,
    field,
    asdict,
)
from datetime import datetime
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Type,
)


def _now_iso() -> str:

    return datetime.now().isoformat(
        timespec="seconds"
    )


def _new_id() -> str:

    # 短 id
    # 8 位 hex
    return (
        "exp_"
        + uuid.uuid4().hex[:8]
    )


@dataclass(slots=True)
class ExperimentRecord:

    # V2.3 Experiment（元数据）
    #
    # 字段：
    #   id            唯一 id
    #   name          实验名（用户命名）
    #   strategy_name strategy 类名
    #   params        参数 dict
    #   created_at    创建时间 ISO
    #   tag           标签（可选）
    #   note          备注（可选）

    name: str

    strategy_name: str

    params: Dict

    id: str = field(
        default_factory=_new_id
    )

    created_at: str = field(
        default_factory=_now_iso
    )

    tag: str = ""

    note: str = ""

    def to_dict(self) -> Dict:

        return asdict(self)

    def params_json(self) -> str:

        return json.dumps(
            self.params,
            sort_keys=True,
            ensure_ascii=False,
        )


@dataclass(slots=True)
class ExperimentResultV2:

    # V2.3 ExperimentResult
    #
    # 一次实验 + 全部结果
    #
    # experiment       ExperimentRecord 元数据
    # backtest_result  BacktestResult（V1.x 回测输出）
    # walkforward_result WalkForwardResultV2（可选）
    # validation_result  ValidationResult（可选）

    experiment: ExperimentRecord

    backtest_result: Any = None

    walkforward_result: Any = None

    validation_result: Any = None

    def metrics(self) -> Dict:

        # 从 backtest_result 抽核心指标
        # 方便入库 / 显示
        if self.backtest_result is None:
            return {}

        br = self.backtest_result
        out = {}

        # BacktestResult dataclass
        for attr in (
            "total_return",
            "sharpe",
            "max_drawdown",
            "trade_count",
            "win_rate",
            "final_equity",
            "source",
        ):

            if hasattr(br, attr):
                out[attr] = getattr(
                    br, attr
                )

        return out


class ExperimentTracker:

    # 实验追踪器
    #
    # 用法：
    #   tracker = ExperimentTracker(
    #       strategy_registry={
    #           "MACross": MACrossStrategy,
    #       },
    #       db_path="storage/research.db"
    #   )
    #
    #   record = ExperimentRecord(
    #       name="ma_cross_v1",
    #       strategy_name="MACross",
    #       params={"fast": 20, "slow": 60}
    #   )
    #
    #   result = tracker.run(
    #       record=record,
    #       engine=engine,
    #       data=data
    #   )
    #
    #   # 自动入库
    #   # 之后可以 search / leaderboard
    #
    # 内部：
    #   - 从 strategy_registry 找 strategy cls
    #   - 构造 strategy(**record.params)
    #   - engine.run(strategy, data)
    #   - 包装成 ExperimentResultV2
    #   - repo.save(...)

    def __init__(
        self,
        strategy_registry: Dict[
            str, Type
        ] = None,
        db_path: Optional[str] = None,
        repository: Any = None,
    ):

        # 策略类注册表
        # strategy_name -> strategy class
        #
        # 例如：
        #   {"MACross": MACrossStrategy}
        self.strategy_registry = (
            strategy_registry or {}
        )

        # 延迟 import
        # 避免循环
        from .repository import (
            ExperimentRepository
        )
        from .database import (
            Database,
        )

        # 允许外部传 repo
        # 方便单测
        if repository is not None:
            self.repo = repository
        else:
            db = (
                Database(db_path=db_path)
                if db_path
                else Database()
            )
            self.repo = ExperimentRepository(
                db=db
            )

    def register_strategy(
        self,
        name: str,
        cls: Type,
    ):

        # 动态注册 strategy
        self.strategy_registry[name] = cls

    def run(
        self,
        record: ExperimentRecord,
        engine: Any,
        data: Any,
        walkforward_runner: Any = None,
    ) -> ExperimentResultV2:

        # 跑一次实验
        # 自动入库
        #
        # 参数：
        #   record             ExperimentRecord
        #   engine             BaseBacktestEngine
        #   data               Dict[symbol, DataFrame]
        #   walkforward_runner 可选 WalkForwardRunner
        #                      （如提供，会额外跑 WF）

        # ---- 1) 取 strategy cls ----
        cls = self.strategy_registry.get(
            record.strategy_name
        )
        if cls is None:

            raise KeyError(
                f"strategy not registered: "
                f"{record.strategy_name}. "
                f"known: "
                f"{list(self.strategy_registry)}"
            )

        # ---- 2) 构造 strategy ----
        strategy = cls(**record.params)

        # ---- 3) 跑回测 ----
        # 走 engine.run()
        # engine 接受 strategy= 覆盖 self.strategy
        from ..data.cache import (
            factor_cache,
        )
        factor_cache.clear()

        backtest_result = engine.run(
            strategy=strategy,
            data=data,
        )

        # ---- 4) Walk-Forward（可选）----
        walkforward_result = None
        if walkforward_runner is not None:

            walkforward_result = (
                walkforward_runner.run(
                    data=data,
                    param_space=record.params,
                )
            )

        # ---- 5) 包装 ExperimentResultV2 ----
        result_v2 = ExperimentResultV2(
            experiment=record,
            backtest_result=backtest_result,
            walkforward_result=(
                walkforward_result
            ),
            validation_result=None,
        )

        # ---- 6) 入库 ----
        self.repo.save(result_v2)

        # ---- 7) Phase 6: 保存权益曲线 ----
        if backtest_result is not None and hasattr(
            backtest_result, "equity_curve"
        ):
            try:
                eq = backtest_result.equity_curve
                ts = getattr(backtest_result, "timestamps", None)
                if eq is not None and len(eq) > 0:
                    self.repo.save_equity_curve(
                        record.id, eq, ts
                    )
            except Exception:
                # 入库失败不影响主流程
                pass

        return result_v2

    def search(
        self,
        strategy: Optional[str] = None,
        sharpe_min: Optional[
            float
        ] = None,
        max_dd_max: Optional[
            float
        ] = None,
        return_min: Optional[
            float
        ] = None,
        tag: Optional[str] = None,
        limit: int = 100,
    ):

        # Search API
        # 给 Repository.search
        return self.repo.search(
            strategy=strategy,
            sharpe_min=sharpe_min,
            max_dd_max=max_dd_max,
            return_min=return_min,
            tag=tag,
            limit=limit,
        )

    def leaderboard(
        self,
        sort_by: str = "sharpe",
        top: int = 20,
    ):

        # Leaderboard
        # Top N 实验
        #
        # sort_by:
        #   "sharpe"           按 sharpe 排
        #   "return"           按 total_return
        #   "stability"        按 stability_score（wf）
        #   "max_drawdown"     按 max_dd 升序（小的好）
        return self.repo.leaderboard(
            sort_by=sort_by,
            top=top,
        )
