"""
因子管理 CLI 模块
================

支持交互式和命令式两种使用方式：
- 交互式: python main.py factor
- 命令式: python main.py factor list --category valuation
"""

import argparse
from typing import Optional

from .interactive import InteractiveMenu, prompt_input


def _list_factors(category: str = None, data_source: str = None, keyword: str = None):
    """列出因子"""
    from src.factors.factor_registry import list_factors, FactorCategory, get_factor_info

    if category:
        try:
            cat = FactorCategory(category)
        except ValueError:
            print(f"未知分类: {category}")
            print(f"可用分类: {[c.value for c in FactorCategory]}")
            return

    factors = list_factors(category=cat if category else None, data_source=data_source)

    if keyword:
        factors = [f for f in factors if keyword.lower() in f.lower() or
                   keyword.lower() in get_factor_info(f).get('description', '').lower()]

    if not factors:
        print("未找到匹配的因子")
        return

    # 按分类分组显示
    from src.factors.factor_registry import FactorCategory
    for cat in FactorCategory:
        cat_factors = [f for f in factors if get_factor_info(f).get('category') == cat]
        if cat_factors:
            print(f"\n【{cat.value}】")
            for name in cat_factors:
                info = get_factor_info(name)
                direction = "↑" if info.get('default_ascending') else "↓"
                sources = ", ".join(info.get('data_sources', []))
                print(f"  {name:20} {direction}  ({sources})")
                print(f"    {info.get('description', '')}")

    print(f"\n共 {len(factors)} 个因子")


def _show_factor_info(name: str):
    """显示因子详情"""
    from src.factors.factor_registry import get_factor_info

    info = get_factor_info(name)
    if not info:
        print(f"未知因子: {name}")
        return

    print(f"\n{'=' * 50}")
    print(f"因子: {name}")
    print(f"{'=' * 50}")
    print(f"  名称: {info.get('name', '')}")
    print(f"  分类: {info.get('category', '')}")
    print(f"  描述: {info.get('description', '')}")
    print(f"  API字段: {info.get('field', '')}")
    print(f"  数据来源: {info.get('source', '')}")
    print(f"  排名方向: {'升序(越小越好)' if info.get('default_ascending') else '降序(越大越好)'}")
    print(f"  支持数据源: {', '.join(info.get('data_sources', []))}")
    print(f"{'=' * 50}")


def _test_factor(name: str, date: str = None):
    """测试因子计算"""
    from src.factors.factor_service import FactorService

    if not date:
        date = prompt_input("查询日期", "2024-01-02")

    print(f"\n测试因子: {name}, 日期: {date}")
    service = FactorService(data_source='eastmoney')

    values = service.get_factor(name, date)
    if not values:
        print("未获取到数据（可能因子不支持或API调用失败）")
        return

    # 统计信息
    import numpy as np
    vals = list(values.values())
    print(f"  有效股票数: {len(vals)}")
    print(f"  均值: {np.mean(vals):.4f}")
    print(f"  中位数: {np.median(vals):.4f}")
    print(f"  标准差: {np.std(vals):.4f}")
    print(f"  最小值: {np.min(vals):.4f}")
    print(f"  最大值: {np.max(vals):.4f}")

    # Top 5
    sorted_vals = sorted(values.items(), key=lambda x: x[1])
    print(f"\n  Top 5 (最小):")
    for code, val in sorted_vals[:5]:
        print(f"    {code}: {val:.4f}")
    print(f"  Bottom 5 (最大):")
    for code, val in sorted_vals[-5:]:
        print(f"    {code}: {val:.4f}")


def _register_factor(name: str, field: str, category: str, description: str = '',
                     ascending: bool = True):
    """注册新因子"""
    from src.factors.factor_registry import register_factor, FactorSource, FactorCategory

    try:
        source = FactorSource.VALUATION if category in ('valuation', '估值') else FactorSource.FINANCIAL
        cat = FactorCategory(category)
    except ValueError:
        print(f"未知分类: {category}")
        print(f"可用分类: {[c.value for c in FactorCategory]}")
        return

    register_factor(
        name=name,
        field=field,
        source=source,
        category=cat,
        description=description or f'{name} 因子',
        default_ascending=ascending,
    )
    print(f"✓ 因子 '{name}' 注册成功")


# ---- 交互式菜单 ----

def _interactive_list():
    _list_factors()


def _interactive_list_by_category():
    from src.factors.factor_registry import FactorCategory
    options = [c.value for c in FactorCategory]
    from .interactive import prompt_choice
    idx = prompt_choice("选择因子分类", options)
    _list_factors(category=options[idx])


def _interactive_search():
    keyword = prompt_input("搜索关键词")
    if keyword:
        _list_factors(keyword=keyword)


def _interactive_info():
    name = prompt_input("因子名称")
    if name:
        _show_factor_info(name)


def _interactive_test():
    name = prompt_input("因子名称")
    if name:
        _test_factor(name)


def _interactive_register():
    print("\n--- 注册新因子 ---")
    name = prompt_input("因子名称（英文）")
    field = prompt_input("API字段名")
    from .interactive import prompt_choice
    options = [c.value for c in __import__('src.factors.factor_registry', fromlist=['FactorCategory']).FactorCategory]
    idx = prompt_choice("因子分类", options)
    desc = prompt_input("因子描述")
    _register_factor(name, field, options[idx], desc)


def run_factor_interactive():
    """运行因子管理交互式菜单"""
    menu = InteractiveMenu("因子管理")
    menu.add_option('1', '列出所有因子', _interactive_list)
    menu.add_option('2', '按分类查看因子', _interactive_list_by_category)
    menu.add_option('3', '搜索因子', _interactive_search)
    menu.add_option('4', '查看因子详情', _interactive_info)
    menu.add_option('5', '测试因子计算', _interactive_test)
    menu.add_option('6', '注册新因子', _interactive_register)
    menu.run()


# ---- argparse 集成 ----

def setup_factor_parser(parser: argparse.ArgumentParser) -> None:
    """配置 factor 子命令的参数"""
    subparsers = parser.add_subparsers(dest='factor_command', help='因子管理子命令')

    # list 子命令
    list_parser = subparsers.add_parser('list', help='列出因子')
    list_parser.add_argument('--category', help='按分类筛选')
    list_parser.add_argument('--source', help='按数据源筛选')
    list_parser.add_argument('--keyword', help='按关键词搜索')

    # info 子命令
    info_parser = subparsers.add_parser('info', help='查看因子详情')
    info_parser.add_argument('--name', required=True, help='因子名称')

    # test 子命令
    test_parser = subparsers.add_parser('test', help='测试因子计算')
    test_parser.add_argument('--name', required=True, help='因子名称')
    test_parser.add_argument('--date', help='查询日期 (YYYY-MM-DD)')

    # register 子命令
    reg_parser = subparsers.add_parser('register', help='注册新因子')
    reg_parser.add_argument('--name', required=True, help='因子名称')
    reg_parser.add_argument('--field', required=True, help='API字段名')
    reg_parser.add_argument('--category', required=True, help='因子分类')
    reg_parser.add_argument('--description', default='', help='因子描述')
    reg_parser.add_argument('--ascending', action='store_true', default=True, help='升序排名')


def run_factor_command(args) -> None:
    """执行 factor 命令"""
    if not hasattr(args, 'factor_command') or not args.factor_command:
        run_factor_interactive()
        return

    cmd = args.factor_command
    if cmd == 'list':
        _list_factors(args.category, args.source, args.keyword)
    elif cmd == 'info':
        _show_factor_info(args.name)
    elif cmd == 'test':
        _test_factor(args.name, args.date)
    elif cmd == 'register':
        _register_factor(args.name, args.field, args.category, args.description, args.ascending)
