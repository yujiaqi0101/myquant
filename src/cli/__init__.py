"""
CLI 模块
========

新版统一引擎的命令行接口。

子命令：
- config : 配置管理（交互式/命令式）
- data   : 数据管理（同步/校验/生成）
- factor : 因子管理（查询/注册/测试）
- strategy : 策略管理（list/show）
- backtest : 回测执行（基于 src/core/engine/BacktestEngine）
- result : 回测结果管理（list/show/export/html/delete）
- pool   : 股票池管理（create/show/add/remove）
- paper  : 模拟盘（基于 src/core/engine/PaperEngine）
- live   : 实盘（基于 src/core/engine/LiveEngine，占位）
"""

from .config_cli import setup_config_parser, run_config_command
from .data_cli import setup_data_parser, run_data_command
from .factor_cli import setup_factor_parser, run_factor_command
from .strategy_cli import setup_strategy_parser, run_strategy_command
from .backtest_cli import setup_backtest_parser, run_backtest_command
from .result_cli import setup_result_parser, run_result_command
from .pool_cli import setup_pool_parser, run_pool_command
from .paper_cli import setup_paper_parser, run_paper_subcommand
from .live_cli import setup_live_parser, run_live_subcommand

__all__ = [
    # 配置 / 数据 / 因子
    "setup_config_parser",
    "run_config_command",
    "setup_data_parser",
    "run_data_command",
    "setup_factor_parser",
    "run_factor_command",
    # 策略 / 回测 / 结果 / 股票池
    "setup_strategy_parser",
    "run_strategy_command",
    "setup_backtest_parser",
    "run_backtest_command",
    "setup_result_parser",
    "run_result_command",
    "setup_pool_parser",
    "run_pool_command",
    # 模拟盘 / 实盘
    "setup_paper_parser",
    "run_paper_subcommand",
    "setup_live_parser",
    "run_live_subcommand",
]
