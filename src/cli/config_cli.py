"""
配置管理 CLI 模块
================

支持交互式和命令式两种使用方式：
- 交互式: python main.py config
- 命令式: python main.py config --token xxx
"""

import json
import argparse
from pathlib import Path
from typing import Optional

from .interactive import InteractiveMenu, prompt_input


# 统一配置文件路径
CONFIG_PATH = Path(__file__).parent.parent.parent / 'config' / 'config.json'


def _load_config() -> dict:
    """加载统一配置文件"""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_config(data: dict) -> None:
    """保存统一配置文件"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"配置已保存到 {CONFIG_PATH}")


# ---- 命令式操作 ----

def set_eastmoney_token(token: str) -> None:
    """设置东财掘金 Token"""
    config = _load_config()
    config.setdefault("credentials", {}).setdefault("eastmoney", {})["token"] = token
    _save_config(config)
    print(f"东财掘金 Token 已设置")


def set_data_source(source: str) -> None:
    """设置默认数据源"""
    config = _load_config()
    if 'data_source' not in config:
        config['data_source'] = {}
    config['data_source']['source'] = source
    _save_config(config)
    print(f"✓ 默认数据源已设置为: {source}")


def set_log_level(level: str) -> None:
    """设置日志级别"""
    config = _load_config()
    if 'logging' not in config:
        config['logging'] = {}
    config['logging']['level'] = level
    _save_config(config)
    print(f"✓ 日志级别已设置为: {level}")


def show_config() -> None:
    """显示当前配置"""
    print(f"\n{'=' * 50}")
    print("[当前配置]")
    print(f"{'=' * 50}")

    # 凭证信息
    config = _load_config()
    creds = config.get("credentials", {})
    if 'eastmoney' in creds:
        token = creds['eastmoney'].get('token', '')
        masked = token[:8] + '...' + token[-4:] if len(token) > 12 else '***'
        print(f"\n  东财掘金 Token: {masked}")

    # 配置信息
    config = _load_config()
    if 'data_source' in config:
        print(f"\n  默认数据源: {config['data_source'].get('source', '未设置')}")

    if 'logging' in config:
        print(f"  日志级别: {config['logging'].get('level', '未设置')}")

    print(f"\n  配置文件: {CONFIG_PATH}")
    print(f"{'=' * 50}")


# ---- 交互式操作 ----

def _interactive_show_config():
    show_config()


def _interactive_set_token():
    print("\n--- 配置东财掘金 Token ---")
    config = _load_config()
    current = config.get("credentials", {}).get("eastmoney", {}).get("token", "")
    if current:
        masked = current[:8] + '...' + current[-4:] if len(current) > 12 else '***'
        print(f"  当前 Token: {masked}")

    token = prompt_input("请输入新的 Token", current if current else None)
    if token:
        set_eastmoney_token(token)


def _interactive_set_data_source():
    print("\n--- 配置数据源 ---")
    from .interactive import prompt_choice
    options = ['eastmoney (东财掘金 API)', 'database (本地数据库)']
    idx = prompt_choice("请选择默认数据源", options)
    sources = ['eastmoney', 'database']
    set_data_source(sources[idx])


def _interactive_set_log_level():
    print("\n--- 配置日志级别 ---")
    from .interactive import prompt_choice
    options = ['DEBUG (调试)', 'INFO (信息)', 'WARNING (警告)', 'ERROR (错误)']
    idx = prompt_choice("请选择日志级别", options, default=1)
    levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
    set_log_level(levels[idx])


def run_config_interactive():
    """运行配置管理交互式菜单"""
    menu = InteractiveMenu("配置管理")
    menu.add_option('1', '查看当前配置', _interactive_show_config)
    menu.add_option('2', '配置东财掘金 Token', _interactive_set_token)
    menu.add_option('3', '配置数据源', _interactive_set_data_source)
    menu.add_option('4', '配置日志级别', _interactive_set_log_level)
    menu.run()


# ---- argparse 集成 ----

def setup_config_parser(parser: argparse.ArgumentParser) -> None:
    """配置 config 子命令的参数"""
    parser.add_argument('--token', help='设置东财掘金 Token')
    parser.add_argument('--data-source',
                        help='设置默认数据源（eastmoney/database）')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='设置日志级别')
    parser.add_argument('--show', action='store_true', help='显示当前配置')


def run_config_command(args) -> None:
    """执行 config 命令"""
    # 如果没有传任何参数，进入交互模式
    has_args = any([
        args.token,
        args.data_source, args.log_level, args.show
    ])

    if not has_args:
        run_config_interactive()
        return

    # 命令式执行
    if args.show:
        show_config()

    if args.token:
        set_eastmoney_token(args.token)

    if args.data_source:
        set_data_source(args.data_source)

    if args.log_level:
        set_log_level(args.log_level)
