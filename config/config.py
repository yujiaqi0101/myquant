"""
A股量化分析系统配置文件
"""

import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


def _load_config_json() -> dict:
    """加载 config/config.json 配置文件（模块级缓存，仅加载一次）"""
    config_path = PROJECT_ROOT / "config" / "config.json"
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


# 模块级配置缓存（仅加载一次）
_CONFIG = _load_config_json()


def _load_credentials() -> dict:
    """
    从 config/config.json 的 credentials 字段加载凭证信息

    Returns
    -------
    dict
        凭证字典，如 {"qmt": {"account": "...", ...}, "eastmoney": {"token": "..."}}
    """
    return _CONFIG.get("credentials", {})


# 加载凭证（模块级别，仅加载一次）
_CREDENTIALS = _load_credentials()


def get_credentials(service: str = 'qmt') -> dict:
    """
    获取指定服务的凭证信息

    优先级：环境变量 > config.json credentials 字段

    Parameters
    ----------
    service : str
        服务名称，如 'qmt', 'eastmoney'

    Returns
    -------
    dict
        该服务的凭证字典
    """
    creds = _CREDENTIALS.get(service, {})

    if service == 'qmt':
        # 环境变量优先
        account = os.environ.get("QMT_ACCOUNT", creds.get("account", ""))
        password = os.environ.get("QMT_PASSWORD", creds.get("password", ""))
        qmt_path = os.environ.get("QMT_PATH", creds.get("path", ""))
        return {"account": account, "password": password, "path": qmt_path}

    if service == 'eastmoney':
        # 东财掘金 token，环境变量优先
        token = os.environ.get("EASTMONEY_TOKEN", creds.get("token", ""))
        return {"token": token}

    return creds

# ============================================================
# 数据源配置
# ============================================================
# 通过 config/config.json 的 data_source 字段按数据类型路由
# 例：{"stock_daily": "qmt", "sector_constituents": "tdx", "dividend": "eastmoney"}
# 与飞书"## 数据库"章节表格完全对齐：
#   - 板块成分股来自 tdx
#   - 其它大部分数据来自 eastmoney
#   - 股票日线来自 qmt
#
# CLI 不再支持 --data-source 参数
# 项目约定（hard constraints）：所有市场数据严格从数据库读取，
# 数据库为空时回测直接报错退出，不允许回退到模拟数据。
# AQUANT_DATA_MODE 模式已删除。
#

# 数据源常量
class DataSource:
    DATABASE = "database"      # 本地 SQLite 数据库
    EASTMONEY = "eastmoney"    # 东财掘金 API
    QMT = "qmt"                # 国金 QMT
    TDX = "tdx"                # 通达信


# 默认数据源配置（与 config.example.json 一致）
DEFAULT_DATA_SOURCE_CONFIG = {
    "stock_daily": "qmt",
    "stock_info": "eastmoney",
    "etf_info": "eastmoney",
    "etf_daily": "eastmoney",
    "index_info": "eastmoney",
    "index_constituents": "eastmoney",
    "index_daily": "eastmoney",
    "sector_info": "eastmoney",
    "sector_constituents": "tdx",
    "financial_data": "eastmoney",
    "valuation_data": "eastmoney",
    "trading_dates": "eastmoney",
    "dividend": "eastmoney",
}


def get_data_source_config() -> dict:
    """
    获取数据源配置（按数据类型路由）

    优先级：config.json > DEFAULT_DATA_SOURCE_CONFIG

    Returns
    -------
    dict
        数据源配置字典，键为数据类型，值为数据源名
    """
    file_cfg = _CONFIG.get("data_source", {})
    if not isinstance(file_cfg, dict):
        file_cfg = {}
    # 合并默认配置（用户配置覆盖默认）
    result = dict(DEFAULT_DATA_SOURCE_CONFIG)
    result.update(file_cfg)
    return result


def get_data_source(data_type: str) -> str:
    """
    获取指定数据类型的数据源

    Parameters
    ----------
    data_type : str
        数据类型，如 'stock_daily', 'sector_constituents'

    Returns
    -------
    str
        数据源名（如 'eastmoney', 'qmt', 'tdx'），默认 'database'
    """
    cfg = get_data_source_config()
    return cfg.get(data_type, "database")

# 东财掘金配置（token 从 config.json credentials 字段读取）
EASTMONEY_CONFIG = {
    "enabled": False,
    "default_frequency": "1d",
    "default_adjust": 1,              # 前复权 ADJUST_PREV=1
    "max_rows_per_request": 33000,
    "request_interval": 0.5,          # 流控间隔（秒）
    "retry_attempts": 3,
    "retry_interval": 2.0,
    "cache_enabled": True,
}

def get_data_mode() -> str:
    """
    保留接口用于向后兼容。

    AQUANT_DATA_MODE 已删除，项目约定为 strict 模式（仅数据库）。
    始终返回 "real" 以保持调用方代码兼容。
    """
    return "real"


def is_test_mode() -> bool:
    """
    是否为测试模式（允许回退模拟数据）。

    AQUANT_DATA_MODE 已删除，本项目不允许回退模拟数据，
    始终返回 False。
    """
    return False


def is_real_mode() -> bool:
    """
    判断是否使用真实数据模式。

    AQUANT_DATA_MODE 已删除，始终返回 True。
    """
    return True


# 兼容层：DataMode 类已删除，但保留常量供历史代码使用
class DataMode:
    """兼容 stub：DataMode 已废弃，AQUANT_DATA_MODE 删除后请勿再使用本类。"""
    TEST = "test"
    REAL = "real"
    AUTO = "auto"

# ============================================================
# 目录配置
# ============================================================
# 数据目录
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
EXTERNAL_DATA_DIR = DATA_DIR / "external"
TEST_DATA_DIR = DATA_DIR / "test_data"  # 测试数据目录

# 报告目录
REPORT_DIR = PROJECT_ROOT / "reports"

# 日志目录
LOG_DIR = PROJECT_ROOT / "logs"

# 数据库配置
DATABASE_CONFIG = {
    "type": "sqlite",  # sqlite 或 postgresql
    "path": str(DATA_DIR / "aquant.db"),
}

# 国金QMT配置
_QMT_CREDS = get_credentials('qmt')
QMT_CONFIG = {
    "enabled": False,              # 是否启用QMT数据源
    "account": _QMT_CREDS.get("account", ""),  # 从config.json或环境变量读取
    "password": _QMT_CREDS.get("password", ""),  # 从config.json或环境变量读取
    "path": _QMT_CREDS.get("path", ""),  # QMT安装目录下userdata_mini路径
    "default_start_date": "20230101",  # 默认数据起始日期
    "data_types": ["stock", "index", "etf", "fund"],  # 要同步的数据类型
    "sync_on_startup": False,      # 启动时是否自动同步
    "batch_size": 100,             # 批量写入大小
    "reconnect_attempts": 3,       # 重连次数
    "reconnect_interval": 5,       # 重连间隔（秒）
}

# 市场阶段识别配置
MARKET_STAGE_CONFIG = {
    # 牛熊判断参数
    "ma_long": 250,          # 长期均线周期
    "ma_short": 20,          # 短期均线周期
    
    # 指数个股背离阈值
    "divergence_threshold": 0.3,
    
    # 情绪极端阈值
    "sentiment_extreme_high": 0.8,
    "sentiment_extreme_low": 0.2,
    
    # 关注的指数列表
    "index_codes": [
        "000001.SH",  # 上证指数
        "399001.SZ",  # 深证成指
        "399006.SZ",  # 创业板指
        "000300.SH",  # 沪深300
        "000852.SH",  # 中证1000
    ],
}

# 相似度分析配置
SIMILARITY_CONFIG = {
    # 分析窗口（交易日）
    "windows": [20, 60, 120],
    
    # 相似度阈值
    "similarity_threshold": 0.8,
    
    # 相似度计算方法
    "methods": ["dtw", "cosine", "feature"],
    
    # 深度学习模型配置
    "deep_learning": {
        "enabled": False,  # 默认关闭，需要GPU支持
        "latent_dim": 16,
        "hidden_dim": 64,
        "epochs": 100,
    },
}

# 因子配置
FACTOR_CONFIG = {
    # 因子预处理
    "winsorize_limits": (0.01, 0.01),  # 去极值
    "standardize": True,
    "neutralizing": {
        "industry": True,
        "market_cap": True,
    },
    
    # 因子评估
    "forward_period": 5,      # 预测期（交易日）
    "n_layers": 5,            # 分层数
    
    # 因子筛选
    "ic_threshold": 0.02,     # IC阈值
    "ir_threshold": 0.2,      # IR阈值
    
    # 遗传算法配置
    "genetic_algorithm": {
        "population_size": 100,
        "generations": 50,
        "crossover_prob": 0.5,
        "mutation_prob": 0.2,
    },
    
    # 遗传编程配置
    "genetic_programming": {
        "population_size": 1000,
        "generations": 20,
        "tournament_size": 20,
    },
}

# 风控配置
RISK_CONFIG = {
    # 行业分散度
    "max_industry_weight": 0.3,  # 单行业最大权重
    "min_industries": 5,          # 最少覆盖行业数
    
    # 市值暴露
    "max_large_cap_bias": 0.2,   # 大盘股最大偏离
    "max_small_cap_bias": 0.2,   # 小盘股最大偏离
    "max_mid_cap_bias": 0.15,    # 中盘股最大偏离
    
    # 过拟合检测
    "sharpe_decay_threshold": 0.5,
    "pbo_threshold": 0.5,
}

# 预警配置
ALERT_CONFIG = {
    # 预警阈值
    "market_stage_change": True,
    "divergence_threshold": 0.3,
    "sentiment_extreme": 0.8,
    "factor_ic_decay": 0.5,
    "similarity_pattern": 0.85,
    "drawdown_warning": 0.1,
    
    # 通知方式
    "notification": {
        "console": True,
        "email": False,
        "wechat": False,
    },
}

# 可视化配置
VISUALIZATION_CONFIG = {
    # 颜色方案
    "colors": {
        "bull": "#FF4B4B",
        "bear": "#4B9BFF",
        "neutral": "#FFD93D",
        "warning": "#FF6B6B",
        "normal": "#6BCB77",
    },
    
    # 图表配置
    "chart_height": 600,
    "chart_width": 800,
}

# 估值分析配置
VALUATION_CONFIG = {
    # 估值模型配置
    "models": {
        "financial": {
            "required_roe": 0.10,        # 金融行业要求回报率
            "pb_range": (0.6, 1.5),      # PB合理区间
        },
        "cyclical": {
            "normalized_years": 5,        # 正常化盈利年数
            "pb_range": (0.8, 1.5),
        },
        "consumer": {
            "peg_threshold": 1.5,         # PEG阈值
            "pe_range": (15, 35),
        },
        "technology": {
            "growth_premium": 0.30,       # 成长溢价
            "ps_range": (5, 15),
        },
        "real_estate": {
            "nav_discount": 0.20,         # NAV折让
        },
        "utility": {
            "wacc": 0.08,                 # 加权平均资本成本
            "terminal_growth": 0.02,      # 永续增长率
        },
    },
    
    # 估值权重配置
    "weights": {
        "pe": 0.20,
        "pb": 0.20,
        "ps": 0.10,
        "peg": 0.15,
        "ev_ebitda": 0.15,
        "dcf": 0.20,
    },
    
    # 投资建议阈值
    "recommendation_thresholds": {
        "strong_overweight": -0.30,      # 强烈超配：低估30%+
        "overweight": -0.15,             # 超配：低估15-30%
        "neutral": 0.15,                 # 标配：偏离+-15%
        "underweight": 0.30,             # 低配：高估15-30%
    },
    
    # 数据更新配置
    "data_update": {
        "financial_statement": "quarterly",  # 财报更新频率
        "price_data": "daily",               # 价格更新频率
        "valuation_recalc": "weekly",        # 估值重算频率
    },
}

# 待办事项默认列表
DEFAULT_TODOS = [
    {
        "id": "DATA-001",
        "title": "分钟级行情数据支持",
        "category": "数据层",
        "priority": "medium",
        "status": "pending",
    },
    {
        "id": "DATA-002",
        "title": "基本面数据接入",
        "category": "数据层",
        "priority": "medium",
        "status": "completed",  # 已通过QMT实现
    },
    {
        "id": "DATA-003",
        "title": "宏观数据接入",
        "category": "数据层",
        "priority": "low",
        "status": "pending",
    },
    {
        "id": "DATA-004",
        "title": "获取指数/ETF真实持仓数据",
        "category": "数据层",
        "priority": "high",
        "status": "completed",  # 已通过QMT实现
    },
    {
        "id": "DATA-005",
        "title": "股票历史数据校验与停牌补充",
        "category": "数据层",
        "priority": "high",
        "status": "completed",  # 已实现DataValidator
    },
    {
        "id": "DATA-006",
        "title": "测试数据与真实数据分离",
        "category": "数据层",
        "priority": "high",
        "status": "completed",  # 已实现CSV测试数据
    },
    {
        "id": "TRADE-001",
        "title": "实盘交易接口对接",
        "category": "实盘对接",
        "priority": "low",
        "status": "pending",
    },
    {
        "id": "FEAT-001",
        "title": "深度学习相似度",
        "category": "功能增强",
        "priority": "medium",
        "status": "pending",
    },
    {
        "id": "FEAT-002",
        "title": "遗传编程挖因子",
        "category": "功能增强",
        "priority": "medium",
        "status": "pending",
    },
    {
        "id": "FEAT-003",
        "title": "估值分析模块",
        "category": "功能增强",
        "priority": "high",
        "status": "completed",  # 已实现
    },
]
