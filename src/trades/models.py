"""
统一交易记录数据模型
====================

定义券商历史交易记录的统一数据结构，以及主流券商 CSV 格式的字段别名映射表。
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple
from enum import Enum


class BrokerFormat(Enum):
    """支持的券商 CSV 格式"""

    HUATAI = 'huatai'        # 华泰证券
    CITIC = 'citic'          # 中信证券
    GUOJIN = 'guojin'        # 国金证券
    EASTMONEY = 'eastmoney'  # 东方财富
    TONGHUASHUN = 'tonghuashun'  # 同花顺
    GENERIC = 'generic'     # 通用格式（自动适配）

    @property
    def display_name(self) -> str:
        names = {
            'huatai': '华泰证券',
            'citic': '中信证券',
            'guojin': '国金证券',
            'eastmoney': '东方财富',
            'tonghuashun': '同花顺',
            'generic': '通用格式',
        }
        return names.get(self.value, self.value)


@dataclass
class TradeRecord:
    """
    统一交易记录模型

    将各券商 CSV 中的交易记录映射为统一格式。
    所有金额单位为元，数量单位为股。
    """

    trade_date: str          # 交易日期 YYYY-MM-DD
    stock_code: str          # 证券代码（归一化为 000001.SZ 格式）
    stock_name: str          # 证券名称
    trade_type: str           # 交易类型 'buy' / 'sell'
    price: float             # 成交价格
    quantity: float           # 成交数量（股，买入为正，卖出为正，方向由 trade_type 决定）
    amount: float             # 成交金额
    commission: float = 0.0  # 手续费/佣金
    stamp_tax: float = 0.0   # 印花税
    transfer_fee: float = 0.0  # 过户费
    other_fee: float = 0.0   # 其他费用
    trade_time: str = ''     # 成交时间
    broker: str = ''         # 券商标识
    account: str = ''        # 资金账号

    @property
    def total_fee(self) -> float:
        """总费用"""
        return self.commission + self.stamp_tax + self.transfer_fee + self.other_fee

    @property
    def net_amount(self) -> float:
        """净金额（买入为负，卖出为正）"""
        if self.trade_type == 'buy':
            return -self.amount - self.total_fee
        else:
            return self.amount - self.total_fee

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# 券商 CSV 字段别名映射表
# ============================================================
# 每个券商的字段可能使用不同列名，此处定义各统一字段对应的别名列表
# CSV 解析器会读取表头，匹配别名来确定字段映射

FIELD_ALIASES: Dict[str, Dict[str, List[str]]] = {
    'huatai': {
        # 华泰特色：成交日期 + 操作 + 成交均价
        'trade_date': ['成交日期'],
        'stock_code': ['证券代码'],
        'stock_name': ['证券名称'],
        'trade_type': ['操作'],
        'price': ['成交均价'],
        'quantity': ['成交数量', '成交股数'],
        'amount': ['成交金额', '成交总额'],
        'commission': ['手续费', '佣金'],
        'stamp_tax': ['印花税'],
        'transfer_fee': ['过户费'],
        'other_fee': ['其他费用', '其他费'],
        'trade_time': ['成交时间', '委托时间'],
        'account': ['资金账号', '股东账号'],
    },
    'citic': {
        # 中信特色：交易日期 + 买卖方向 + 成交价格
        'trade_date': ['交易日期'],
        'stock_code': ['证券代码'],
        'stock_name': ['证券名称'],
        'trade_type': ['买卖方向'],
        'price': ['成交价格'],
        'quantity': ['成交数量'],
        'amount': ['成交金额'],
        'commission': ['手续费', '佣金'],
        'stamp_tax': ['印花税'],
        'transfer_fee': ['过户费'],
        'other_fee': ['其他费用'],
        'trade_time': ['成交时间'],
        'account': ['资金账号'],
    },
    'guojin': {
        # 国金特色：委托日期 + 操作方向
        'trade_date': ['委托日期'],
        'stock_code': ['证券代码'],
        'stock_name': ['证券名称'],
        'trade_type': ['操作方向'],
        'price': ['成交价格', '成交均价'],
        'quantity': ['成交数量'],
        'amount': ['成交金额'],
        'commission': ['手续费', '佣金'],
        'stamp_tax': ['印花税'],
        'transfer_fee': ['过户费'],
        'other_fee': ['其他费用'],
        'trade_time': ['成交时间', '委托时间'],
        'account': ['资金账号'],
    },
    'eastmoney': {
        # 东方财富特色：交易日 + 交易类型
        'trade_date': ['交易日'],
        'stock_code': ['证券代码'],
        'stock_name': ['证券名称'],
        'trade_type': ['交易类型'],
        'price': ['成交均价', '成交价格'],
        'quantity': ['成交数量'],
        'amount': ['成交金额'],
        'commission': ['手续费', '佣金'],
        'stamp_tax': ['印花税'],
        'transfer_fee': ['过户费'],
        'other_fee': ['其他费用'],
        'trade_time': ['成交时间'],
        'account': ['资金账号'],
    },
    'tonghuashun': {
        # 同花顺特色：发生日期 + 证券简称 + 业务名称
        'trade_date': ['发生日期'],
        'stock_code': ['证券代码'],
        'stock_name': ['证券简称', '证券名称'],
        'trade_type': ['业务名称'],
        'price': ['成交价格', '成交均价'],
        'quantity': ['成交数量', '成交股数'],
        'amount': ['成交金额', '发生金额'],
        'commission': ['手续费', '佣金'],
        'stamp_tax': ['印花税'],
        'transfer_fee': ['过户费'],
        'other_fee': ['其他费用'],
        'trade_time': ['成交时间'],
        'account': ['资金账号'],
    },
}

# 交易类型别名映射（将各种"买入/卖出"表述统一为 buy/sell）
TRADE_TYPE_ALIASES: Dict[str, str] = {
    # 买入
    '买入': 'buy',
    '买': 'buy',
    '买入开仓': 'buy',
    '证券买入': 'buy',
    '担保品买入': 'buy',
    '融资买入': 'buy',
    'B': 'buy',
    'b': 'buy',
    'BUY': 'buy',
    # 卖出
    '卖出': 'sell',
    '卖': 'sell',
    '卖出平仓': 'sell',
    '证券卖出': 'sell',
    '担保品卖出': 'sell',
    '融券卖出': 'sell',
    'S': 'sell',
    's': 'sell',
    'SELL': 'sell',
}


def normalize_stock_code(code: str) -> str:
    """
    归一化股票代码为 000001.SZ 格式

    支持输入格式：
    - 000001
    - 000001.SZ
    - SZ000001
    - 600000
    - 600000.SH

    规则（A股）：
    - 6 开头 → 上交所 .SH
    - 0/3 开头 → 深交所 .SZ
    - 8/4 开头 → 北交所 .BJ
    """
    if not code:
        return code
    code = str(code).strip().upper()

    # 已包含交易所后缀
    if '.' in code:
        return code

    # SZ000001 / SH600000 格式
    if code.startswith('SH') or code.startswith('SZ') or code.startswith('BJ'):
        exchange = code[:2]
        num = code[2:]
        return f"{num}.{exchange}"

    # 纯数字代码
    digits = code.lstrip('0') or '0'
    # 补全为6位
    num = code.zfill(6) if len(code) <= 6 else code

    if num.startswith('6'):
        return f"{num}.SH"
    elif num.startswith('0') or num.startswith('3'):
        return f"{num}.SZ"
    elif num.startswith('8') or num.startswith('4'):
        return f"{num}.BJ"
    else:
        # 默认深交所
        return f"{num}.SZ"


def normalize_trade_type(type_str: str) -> str:
    """
    归一化交易类型为 buy/sell

    无法识别的返回空字符串
    """
    if not type_str:
        return ''
    type_str = str(type_str).strip()
    if type_str in TRADE_TYPE_ALIASES:
        return TRADE_TYPE_ALIASES[type_str]
    # 模糊匹配
    for alias, normalized in TRADE_TYPE_ALIASES.items():
        if alias in type_str:
            return normalized
    return ''
