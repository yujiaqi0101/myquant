"""
模拟交易模块（Paper Trading）- 默认参数配置

本文件定义模拟交易引擎的默认参数，包括初始资金、交易费用率、撮合模式等。
可通过 PaperTradingEngine 构造参数覆盖这些默认值。

用法:
    from src.paper_trading.config import PAPER_TRADING_CONFIG
    initial_capital = PAPER_TRADING_CONFIG['initial_capital']
"""

# 模拟交易默认参数
PAPER_TRADING_CONFIG = {
    # 初始虚拟资金（元人民币）
    'initial_capital': 1_000_000.0,

    # 佣金费率：万三（买卖双向），最低 5 元
    'commission_rate': 0.0003,
    'min_commission': 5.0,

    # 印花税：卖出千一
    'stamp_duty_rate': 0.001,

    # 过户费：双向万分之零点一（简化处理，全部股票都收）
    'transfer_fee_rate': 0.00001,

    # 默认撮合价格模式：'close'（当日收盘价）或 'next_open'（次日开盘价）
    'default_price_type': 'close',

    # 涨跌停阈值（简化处理：主板10%；与 backtest_engine 保持一致）
    'limit_up_ratio': 1.095,     # 涨停线：close >= pre_close * 1.095
    'limit_down_ratio': 0.905,   # 跌停线：close <= pre_close * 0.905

    # 新股过滤：上市未满 N 天不可买入
    'new_stock_min_days': 60,
}
