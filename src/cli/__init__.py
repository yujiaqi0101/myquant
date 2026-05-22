"""
CLI 模块

提供命令行接口功能。
"""

from .backtest_cli import (
    setup_strategy_parser,
    run_strategy_command,
    setup_backtest_parser,
    run_backtest_command,
    setup_result_parser,
    run_result_command,
)

__all__ = [
    'setup_strategy_parser',
    'run_strategy_command',
    'setup_backtest_parser',
    'run_backtest_command',
    'setup_result_parser',
    'run_result_command',
]
