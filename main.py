"""
A股量化分析系统
==============

主入口文件（新版统一引擎架构）。

子命令：
    config    : 配置管理（交互式/命令式）
    data      : 数据管理（同步/校验/生成）
    factor    : 因子管理（查询/注册/测试）
    strategy  : 策略管理（list/show）
    backtest  : 回测执行（基于 src/core/engine/BacktestEngine）
    result    : 回测结果管理（list/show/export/html/delete）
    pool      : 股票池管理（create/show/add/remove）
    paper     : 模拟盘（基于 src/core/engine/PaperEngine）
    live      : 实盘（基于 src/core/engine/LiveEngine，占位）

数据来源：
    回测/分析一律从本地 SQLite 数据库读取，缺数据直接报错退出。
    数据同步通过 SourceRegistry 的 DEFAULT_ROUTING 路由到具体数据源。

示例：
    python main.py strategy --list
    python main.py backtest --strategy small_cap --start-date 2024-01-01 --end-date 2024-06-30
    python main.py paper run --strategy small_cap --date 2024-06-28
"""

import argparse
import logging
import sys
from pathlib import Path

# 添加项目路径到 sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.utils.logger import setup_logger


def main() -> None:
    """主入口：注册子命令并分发。"""
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="A股量化分析系统（新版统一引擎架构）",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # 注册子命令（每个 setup_xxx_parser 负责自己的参数）
    # 注意：paper 和 live 使用 subparsers 注册嵌套子命令，其余使用 parser 模式
    from src.cli import (
        setup_config_parser,
        setup_data_parser,
        setup_factor_parser,
        setup_strategy_parser,
        setup_backtest_parser,
        setup_result_parser,
        setup_pool_parser,
        setup_paper_parser,
        setup_live_parser,
    )

    # config : 配置管理
    config_parser = subparsers.add_parser("config", help="配置管理（交互式/命令式）")
    setup_config_parser(config_parser)

    # data : 数据管理
    data_parser = subparsers.add_parser("data", help="数据管理（同步/校验/生成）")
    setup_data_parser(data_parser)

    # factor : 因子管理
    factor_parser = subparsers.add_parser("factor", help="因子管理（查询/注册/测试）")
    setup_factor_parser(factor_parser)

    # strategy : 策略管理
    strategy_parser = subparsers.add_parser("strategy", help="策略管理（list/show）")
    setup_strategy_parser(strategy_parser)

    # backtest : 回测执行
    backtest_parser = subparsers.add_parser("backtest", help="运行回测（基于新版统一引擎）")
    setup_backtest_parser(backtest_parser)

    # result : 回测结果管理
    result_parser = subparsers.add_parser("result", help="回测结果管理")
    setup_result_parser(result_parser)

    # pool : 股票池管理
    pool_parser = subparsers.add_parser("pool", help="股票池管理")
    setup_pool_parser(pool_parser)

    # paper : 模拟盘（嵌套子命令 run/status/positions/reset/adjust-cash）
    setup_paper_parser(subparsers)

    # live : 实盘（嵌套子命令 run/status，占位）
    setup_live_parser(subparsers)

    # 解析参数
    args = parser.parse_args()

    # 无参数时显示帮助
    if args.command is None:
        parser.print_help()
        return

    # 初始化日志（控制台 + 文件）
    setup_logger(
        level=logging.INFO,
        console=True,
        log_file="aquant.log",
    )

    # 分发子命令
    from src.cli import (
        run_config_command,
        run_data_command,
        run_factor_command,
        run_strategy_command,
        run_backtest_command,
        run_result_command,
        run_pool_command,
        run_paper_subcommand,
        run_live_subcommand,
    )

    dispatch = {
        "config": run_config_command,
        "data": run_data_command,
        "factor": run_factor_command,
        "strategy": run_strategy_command,
        "backtest": run_backtest_command,
        "result": run_result_command,
        "pool": run_pool_command,
        "paper": run_paper_subcommand,
        "live": run_live_subcommand,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return
    handler(args)


if __name__ == "__main__":
    main()
