"""
策略管理 CLI 模块
=================

提供策略列表、详情查看等功能。

子命令：
    python main.py strategy --list
    python main.py strategy --show small_cap

策略注册由 src.strategies 包导入时自动完成（auto_discover 扫描子目录）。
"""

import argparse
import inspect
from typing import Any


def setup_strategy_parser(parser: argparse.ArgumentParser) -> None:
    """注册 strategy 子命令参数。"""
    # 列出策略
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出所有可用策略",
    )
    # 查看策略详情
    parser.add_argument(
        "--show", "-s",
        metavar="STRATEGY_NAME",
        help="查看策略详情（显示策略类注释和参数）",
    )


def run_strategy_command(args: argparse.Namespace) -> None:
    """执行策略管理命令。"""
    # 导入 src.strategies 包，触发 auto_discover 自动注册
    # 必须显式 import 一次，否则策略未注册
    import src.strategies  # noqa: F401
    from src.core.strategy import get_strategy_class, list_strategies

    # 1. 列出所有策略
    if args.list:
        names = list_strategies()
        if not names:
            print("\n暂无已注册策略")
            print("提示：请在 src/strategies/ 下创建策略目录并使用 @register_strategy 装饰器")
            return

        print("\n可用策略列表：")
        print("=" * 60)
        for name in names:
            cls = get_strategy_class(name)
            # 取类文档字符串第一行作为描述
            doc = (cls.__doc__ or "").strip().splitlines()[0] if cls.__doc__ else "（无描述）"
            print(f"  {name:<20} {doc[:40]}")
        print("=" * 60)
        print(f"共 {len(names)} 个策略")
        print("\n使用 'python main.py strategy --show <策略名>' 查看详情")
        return

    # 2. 查看策略详情
    if args.show:
        cls = get_strategy_class(args.show)
        if cls is None:
            print(f"错误：未知策略 '{args.show}'")
            print(f"可用策略: {', '.join(list_strategies())}")
            return

        # 类文档字符串
        docstring = inspect.getdoc(cls) or "（无描述）"

        print(f"\n策略: {args.show}")
        print("=" * 60)
        print("\n【策略说明】")
        print(docstring)

        # 类属性（参数默认值）
        print("\n【默认参数（类属性）】")
        print("-" * 40)
        # 收集类自身属性（不含继承自 Strategy 的 name/params）
        default_params = {}
        for k, v in vars(cls).items():
            if k.startswith("_") or k in ("name",):
                continue
            if callable(v) or isinstance(v, (classmethod, staticmethod, property)):
                continue
            default_params[k] = v

        if default_params:
            for k, v in default_params.items():
                print(f"  {k}: {v!r}")
        else:
            print("  （无类属性参数，参数通过 __init__ 的 params 字典传入）")

        # 构造函数签名
        print("\n【构造函数签名】")
        print("-" * 40)
        sig = inspect.signature(cls.__init__)
        print(f"  {cls.__name__}{sig}")

        print("=" * 60)
        return

    # 无参数时显示提示
    print("\n策略管理命令")
    print("=" * 60)
    print("\n可用选项：")
    print("  --list, -l          列出所有可用策略")
    print("  --show <策略名>     查看策略详情")
    print("\n示例：")
    print("  python main.py strategy --list")
    print("  python main.py strategy --show small_cap")
    print("=" * 60)
