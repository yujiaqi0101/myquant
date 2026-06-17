"""
多数据源适配器
==============

统一抽象 DataSource 基类，各数据源（东财/通达信/AKShare/Tushare）实现子类。
通过 SourceRegistry 按数据类型路由到最佳数据源。
"""
