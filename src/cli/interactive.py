"""
交互式菜单框架
==============

提供通用的交互式命令行菜单功能。

使用示例：
    menu = InteractiveMenu("配置管理")
    menu.add_option('1', '查看配置', show_config)
    menu.add_option('2', '修改配置', edit_config)
    menu.run()
"""

from typing import Callable, Dict, List, Tuple, Optional


class InteractiveMenu:
    """
    交互式菜单基类

    提供编号选择式的交互菜单，支持：
    - 添加选项（编号 + 描述 + 处理函数）
    - 循环显示菜单直到用户选择退出
    - 输入验证和错误提示
    """

    def __init__(self, title: str):
        """
        Parameters
        ----------
        title : str
            菜单标题
        """
        self.title = title
        self._options: Dict[str, Tuple[str, Callable]] = {}
        self._sorted_keys: List[str] = []

    def add_option(self, key: str, description: str, handler: Callable) -> 'InteractiveMenu':
        """
        添加菜单选项

        Parameters
        ----------
        key : str
            选项编号，如 '1', '2', 'a'
        description : str
            选项描述
        handler : Callable
            选择后执行的函数（无参数）

        Returns
        -------
        InteractiveMenu
            返回自身，支持链式调用
        """
        self._options[key] = (description, handler)
        if key not in self._sorted_keys:
            self._sorted_keys.append(key)
        return self

    def run(self) -> None:
        """运行菜单循环"""
        while True:
            self._print_menu()
            choice = input(f"\n请选择操作 [0-{len(self._sorted_keys)}]: ").strip()

            if choice == '0':
                print(f"退出 {self.title}")
                break

            if choice in self._options:
                _, handler = self._options[choice]
                try:
                    handler()
                except KeyboardInterrupt:
                    print("\n操作已取消")
                except Exception as e:
                    print(f"错误: {e}")
            else:
                print("无效选择，请重试")

    def _print_menu(self) -> None:
        """打印菜单"""
        print(f"\n{'=' * 50}")
        print(f"[{self.title}]")
        print(f"{'=' * 50}")
        print("可用操作：")
        for key in self._sorted_keys:
            desc, _ = self._options[key]
            print(f"  {key}. {desc}")
        print("  0. 退出")


def prompt_input(prompt: str, default: str = None) -> str:
    """
    带默认值的输入提示

    Parameters
    ----------
    prompt : str
        提示文本
    default : str, optional
        默认值

    Returns
    -------
    str
        用户输入或默认值
    """
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    else:
        return input(f"{prompt}: ").strip()


def prompt_choice(prompt: str, options: List[str], default: int = None) -> int:
    """
    带选项的输入提示

    Parameters
    ----------
    prompt : str
        提示文本
    options : List[str]
        选项列表
    default : int, optional
        默认选项索引

    Returns
    -------
    int
        用户选择的索引（0-based）
    """
    for i, opt in enumerate(options):
        marker = " (默认)" if default is not None and i == default else ""
        print(f"  {i + 1}. {opt}{marker}")

    while True:
        try:
            result = input(f"\n{prompt} [1-{len(options)}]: ").strip()
            if not result and default is not None:
                return default
            idx = int(result) - 1
            if 0 <= idx < len(options):
                return idx
            print(f"请输入 1-{len(options)} 之间的数字")
        except ValueError:
            print("请输入有效数字")


def prompt_confirm(prompt: str, default: bool = False) -> bool:
    """
    确认提示

    Parameters
    ----------
    prompt : str
        提示文本
    default : bool
        默认值

    Returns
    -------
    bool
        用户确认结果
    """
    hint = "[Y/n]" if default else "[y/N]"
    result = input(f"{prompt} {hint}: ").strip().lower()
    if not result:
        return default
    return result in ('y', 'yes', '是')
