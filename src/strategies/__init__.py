"""
策略模块
========

新版统一引擎策略包。

策略目录结构（已删除版本控制，设计文档 6.4 节）：
    src/strategies/<策略目录>/<策略文件>.py

每个策略文件通过 @register_strategy 装饰器注册到全局注册表，
程序运行时通过 auto_discover 扫描子目录自动导入触发注册。

唯一保留策略：small_cap（位于 3a7b2c01/small_cap.py）
"""

from src.core.strategy import auto_discover

# 自动发现并注册所有策略：扫描 src/strategies/ 下子目录，
# 导入其中所有 .py 文件，触发 @register_strategy 装饰器完成注册。
auto_discover("src.strategies")
