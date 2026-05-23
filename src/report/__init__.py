"""
报告模块

提供回测报告生成功能。
"""

from .html_reporter import HTMLReporter, generate_html_report

__all__ = ['HTMLReporter', 'generate_html_report']
