# Research Pipeline
#
# 一次研究的标准流程：
#   Signal → Backtest → Optimization → Validation
#          → Walk Forward → Report
#
# V2.3 加：
#   - ExperimentRecord   实验元数据 dataclass
#   - ExperimentResultV2 一次实验 + 全部结果
#   - Database           SQLite 持久化
#   - ExperimentRepository CRUD / search / leaderboard
#   - ExperimentTracker  自动跑 + 自动入库
#
# 这一切只为一个目标：
#   不再"我相信这个策略能赚钱"
#   而是"机器已经证明这个策略能赚钱"

from .result import (
    ExperimentResult
)

from .experiment import (
    Experiment
)

from .report import (
    Report
)

from .walk_forward import (
    WalkForward,
    WalkForwardResult,
    WalkForwardWindow,
)

from .validation import (
    ValidationRunner,
    ValidationResult
)

# V2.3 Experiment Tracking
from .tracker import (
    ExperimentRecord,
    ExperimentResultV2,
    ExperimentTracker,
)

from .repository import (
    ExperimentRepository,
)

from .database import (
    Database,
)


__all__ = [
    "ExperimentResult",
    "Experiment",
    "Report",
    "WalkForward",
    "WalkForwardResult",
    "WalkForwardWindow",
    "ValidationRunner",
    "ValidationResult",
    # V2.3
    "ExperimentRecord",
    "ExperimentResultV2",
    "ExperimentTracker",
    "ExperimentRepository",
    "Database",
]
