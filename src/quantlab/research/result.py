import subprocess

from dataclasses import (
    dataclass,
    field,
    asdict
)
from datetime import datetime
from typing import Dict, List, Any


def _now_iso():

    return (
        datetime
        .now()
        .isoformat(
            timespec="seconds"
        )
    )


def _git_commit():

    try:

        cp = subprocess.run(

            [
                "git",
                "rev-parse",
                "--short",
                "HEAD"
            ],

            capture_output=True,
            text=True,
            timeout=2
        )

        if cp.returncode == 0:

            return cp.stdout.strip()

    except Exception:

        pass

    return "unknown"


@dataclass
class ExperimentResult:

    # 一次实验的全部产物
    #
    # 以后所有东西都返回这个：
    #   - Experiment.run()
    #   - Optimizer.run()        （每行一个 result）
    #   - WalkForward.run()      （每个 test window 一个 result）
    #   - LiveTrading.run()      （每天一个 result）
    #
    # 这样：
    #   - 对比实验
    #   - 报告生成
    #   - 数据库存储
    #   都基于同一个 schema

    name: str = "experiment"

    strategy_name: str = ""

    params: Dict = field(
        default_factory=dict
    )

    metrics: Dict = field(
        default_factory=dict
    )

    equity_curve: List[float] = field(
        default_factory=list
    )

    timestamps: List = field(
        default_factory=list
    )

    run_time: str = field(
        default_factory=_now_iso
    )

    commit_id: str = field(
        default_factory=_git_commit
    )

    # V1.9: 把 tradebook 暴露成一等公民
    # 方便后续 pnl_by_symbol() / closed_trades_by_symbol
    tradebook: Any = None

    extras: Dict = field(
        default_factory=dict
    )

    def to_dict(self):

        return asdict(self)
