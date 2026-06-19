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
        凭证字典，如 {"eastmoney": {"token": "..."}}
    """
    return _CONFIG.get("credentials", {})


# 加载凭证（模块级别，仅加载一次）
_CREDENTIALS = _load_credentials()


def get_credentials(service: str = 'eastmoney') -> dict:
    """
    获取指定服务的凭证信息

    优先级：环境变量 > config.json credentials 字段

    Parameters
    ----------
    service : str
        服务名称，如 'eastmoney'

    Returns
    -------
    dict
        该服务的凭证字典
    """
    creds = _CREDENTIALS.get(service, {})

    if service == 'eastmoney':
        # 东财掘金 token，环境变量优先
        token = os.environ.get("EASTMONEY_TOKEN", creds.get("token", ""))
        return {"token": token}

    return creds

# ============================================================
# 数据源配置
# ============================================================
# 回测/分析一律从数据库读取，缺数据直接报错退出
# 数据同步通过 SourceRegistry 的 DEFAULT_ROUTING 路由到具体数据源（固定，不可配置切换）

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
        "status": "completed",  # 已通过东财掘金实现
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
        "status": "completed",  # 已通过东财掘金实现
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
