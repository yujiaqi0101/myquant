"""
阶段7验证测试：CLI集成与旧代码清理
====================================

验证目标：
    1. 旧引擎目录已删除（src/engine/, src/quantlab/, src/paper_trading/,
       src/quantlab_adapters/, src/quantlab_quintile/, src/quantlab_extras/）
    2. 旧策略目录已删除（除 3a7b2c01 外的所有策略目录）
    3. 新 CLI 模块可正常导入（backtest/strategy/paper/live/result/pool）
    4. main.py 可正常解析 --help（不报导入错误）
    5. strategy --list 可正常显示小市值策略
    6. src.strategies 包导入触发 auto_discover 注册 small_cap
    7. 旧模块的导入会失败（确认旧代码已彻底清理）

运行：
    python -m pytest tests/test_stage7_cli_cleanup.py -v
"""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 1. 旧引擎目录已删除
# ---------------------------------------------------------------------------

DELETED_DIRS = [
    "src/engine",
    "src/quantlab",
    "src/paper_trading",
    "src/quantlab_adapters",
    "src/quantlab_quintile",
    "src/quantlab_extras",
]


@pytest.mark.parametrize("dir_path", DELETED_DIRS)
def test_old_engine_dirs_deleted(dir_path: str) -> None:
    """验证旧引擎目录已删除。"""
    full_path = PROJECT_ROOT / dir_path
    assert not full_path.exists(), f"旧引擎目录应已删除: {dir_path}"


# ---------------------------------------------------------------------------
# 2. 旧策略目录已删除（仅保留 3a7b2c01）
# ---------------------------------------------------------------------------

DELETED_STRATEGY_DIRS = [
    "src/strategies/2c6d5e04",
    "src/strategies/4e8c3d06",
    "src/strategies/5d8e3f02",
    "src/strategies/7f9a4b03",
    "src/strategies/8b3c1d07",
    "src/strategies/9b1f7a05",
]


@pytest.mark.parametrize("dir_path", DELETED_STRATEGY_DIRS)
def test_old_strategy_dirs_deleted(dir_path: str) -> None:
    """验证旧策略目录已删除。"""
    full_path = PROJECT_ROOT / dir_path
    assert not full_path.exists(), f"旧策略目录应已删除: {dir_path}"


def test_small_cap_strategy_dir_preserved() -> None:
    """验证小市值策略目录保留。"""
    strategy_dir = PROJECT_ROOT / "src" / "strategies" / "3a7b2c01"
    assert strategy_dir.exists(), "小市值策略目录应保留"
    assert (strategy_dir / "small_cap.py").exists(), "small_cap.py 应存在"


def test_strategy_map_json_deleted() -> None:
    """验证 _strategy_map.json 已删除（版本控制已彻底删除）。"""
    map_file = PROJECT_ROOT / "src" / "strategies" / "_strategy_map.json"
    assert not map_file.exists(), "_strategy_map.json 应已删除"


# ---------------------------------------------------------------------------
# 3. 新 CLI 模块可正常导入
# ---------------------------------------------------------------------------

CLI_MODULES = [
    "src.cli",
    "src.cli.backtest_cli",
    "src.cli.strategy_cli",
    "src.cli.paper_cli",
    "src.cli.live_cli",
    "src.cli.result_cli",
    "src.cli.pool_cli",
    "src.cli.config_cli",
    "src.cli.data_cli",
    "src.cli.factor_cli",
]


@pytest.mark.parametrize("module_name", CLI_MODULES)
def test_cli_modules_importable(module_name: str) -> None:
    """验证新 CLI 模块可正常导入。"""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"CLI 模块导入失败 {module_name}: {e}")


def test_cli_exports() -> None:
    """验证 cli 包导出所有必要的函数。"""
    from src.cli import (
        setup_backtest_parser,
        run_backtest_command,
        setup_strategy_parser,
        run_strategy_command,
        setup_paper_parser,
        run_paper_subcommand,
        setup_live_parser,
        run_live_subcommand,
        setup_result_parser,
        run_result_command,
        setup_pool_parser,
        run_pool_command,
    )
    # 所有函数应可调用
    assert callable(setup_backtest_parser)
    assert callable(run_backtest_command)
    assert callable(setup_strategy_parser)
    assert callable(run_strategy_command)


# ---------------------------------------------------------------------------
# 4. main.py 可正常解析 --help
# ---------------------------------------------------------------------------

def test_main_help_runs() -> None:
    """验证 main.py --help 不报导入错误。"""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), "--help"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"main.py --help 失败:\nstdout={result.stdout}\nstderr={result.stderr}"
    # 应包含所有子命令
    for cmd in ["config", "data", "factor", "strategy", "backtest", "result", "pool", "paper", "live"]:
        assert cmd in result.stdout, f"子命令 '{cmd}' 应在 --help 输出中"


# ---------------------------------------------------------------------------
# 5. strategy --list 可正常显示
# ---------------------------------------------------------------------------

def test_strategy_list_runs() -> None:
    """验证 strategy --list 可正常执行，显示 small_cap 策略。"""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), "strategy", "--list"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"strategy --list 失败:\nstdout={result.stdout}\nstderr={result.stderr}"
    assert "small_cap" in result.stdout, "strategy --list 应显示 small_cap 策略"


# ---------------------------------------------------------------------------
# 6. src.strategies 自动注册 small_cap
# ---------------------------------------------------------------------------

def test_strategies_auto_discover() -> None:
    """验证导入 src.strategies 后，small_cap 自动注册。"""
    # 清理已注册策略
    from src.core.strategy import _STRATEGY_REGISTRY
    _STRATEGY_REGISTRY.clear()

    # 重新导入 src.strategies 触发 auto_discover
    import src.strategies  # noqa: F401

    from src.core.strategy import get_strategy_class, list_strategies
    names = list_strategies()
    assert "small_cap" in names, f"small_cap 应已注册，当前注册: {names}"

    cls = get_strategy_class("small_cap")
    assert cls is not None
    assert cls.name == "small_cap"


# ---------------------------------------------------------------------------
# 7. 旧模块导入失败（确认彻底清理）
# ---------------------------------------------------------------------------

OLD_MODULES = [
    "src.engine",
    "src.engine.backtest_engine",
    "src.engine.base_strategy",
    "src.quantlab",
    "src.paper_trading",
    "src.paper_trading.engine",
    "src.quantlab_adapters",
    "src.quantlab_quintile",
    "src.quantlab_extras",
]


@pytest.mark.parametrize("module_name", OLD_MODULES)
def test_old_modules_import_fail(module_name: str) -> None:
    """验证旧模块导入会失败（确认旧代码已彻底清理）。"""
    with pytest.raises(ImportError):
        importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# 8. main.py 子命令分发测试
# ---------------------------------------------------------------------------

def test_main_strategy_subcommand_dispatch() -> None:
    """验证 strategy 子命令能正确分发到 run_strategy_command。"""
    from src.cli import run_strategy_command

    # 构造模拟 args
    import argparse
    args = argparse.Namespace(
        list=True,
        show=None,
    )
    # 应不抛出异常
    run_strategy_command(args)


def test_main_backtest_parser_setup() -> None:
    """验证 backtest 子命令参数解析器可正常构建。"""
    import argparse
    from src.cli import setup_backtest_parser

    parser = argparse.ArgumentParser()
    setup_backtest_parser(parser)

    # 模拟解析参数
    args = parser.parse_args([
        "--strategy", "small_cap",
        "--start-date", "2024-01-01",
        "--end-date", "2024-06-30",
        "--initial-capital", "1000000",
    ])
    assert args.strategy == "small_cap"
    assert args.start_date == "2024-01-01"
    assert args.end_date == "2024-06-30"
    assert args.initial_capital == 1_000_000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
