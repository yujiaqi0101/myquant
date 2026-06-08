"""
CLI 模块

提供命令行接口功能。

子命令：
- config: 配置管理（交互式/命令式）
- data: 数据管理（同步/校验/生成）
- factor: 因子管理（查询/注册/测试）
- strategy: 策略管理
- backtest: 回测执行
- result: 结果管理
- pool: 股票池管理
"""

from .backtest_cli import (
    setup_strategy_parser,
    run_strategy_command,
    setup_backtest_parser,
    run_backtest_command,
    setup_result_parser,
    run_result_command,
    setup_pool_parser,
    run_pool_command,
)
from .config_cli import setup_config_parser, run_config_command
from .data_cli import setup_data_parser, run_data_command
from .factor_cli import setup_factor_parser, run_factor_command

__all__ = [
    # 回测/策略/结果/股票池
    'setup_strategy_parser',
    'run_strategy_command',
    'setup_backtest_parser',
    'run_backtest_command',
    'setup_result_parser',
    'run_result_command',
    'setup_pool_parser',
    'run_pool_command',
    # 新增：配置/数据/因子
    'setup_config_parser',
    'run_config_command',
    'setup_data_parser',
    'run_data_command',
    'setup_factor_parser',
    'run_factor_command',
]
