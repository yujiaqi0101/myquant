"""
模拟交易模块（Paper Trading）

提供在每日收盘行情下运行已注册策略、模拟撮合成交、记录账户与净值曲线的能力。

子模块：
- config: 默认参数（初始资金、费率、撮合模式）
- engine: PaperTradingEngine 撮合引擎（单策略账户）
- orchestrator: PaperTradingOrchestrator 多策略每日调度

用法:
    from src.paper_trading import PaperTradingOrchestrator
    orch = PaperTradingOrchestrator()
    orch.run_daily_process('2024-01-02')

CLI:
    python main.py paper run --date 2024-01-02
    python main.py paper status
    python main.py paper positions --strategy small_cap
"""

from .config import PAPER_TRADING_CONFIG
from .engine import PaperTradingEngine
from .orchestrator import PaperTradingOrchestrator

__all__ = [
    'PAPER_TRADING_CONFIG',
    'PaperTradingEngine',
    'PaperTradingOrchestrator',
]
