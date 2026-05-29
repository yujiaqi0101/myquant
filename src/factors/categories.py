"""
因子分类系统
============

定义因子分类常量和元数据配置。

分类体系：
- 技术指标类：K线形态、成交量异常、VWAP偏离、动量类、均值回复、波动率类、相关性类、情绪类、突破类
- 基本面类：估值因子、盈利因子、成长因子、质量因子

因子数据来源：
- WorldQuant 101 Alphas: 20个精选Alpha因子
- 国泰君安 Alpha191: 23个精选Alpha因子
- 基本面因子: 22个财务指标因子

总计: 65个系统因子
"""

from enum import Enum
from typing import Dict, List, Optional, Union


class FactorCategory(Enum):
    """
    因子分类枚举

    采用技术指标分类法，便于从众多因子中快速定位所需因子。
    """
    # ==================== 技术指标类 ====================
    KLINE_PATTERN = "kline_pattern"           # K线形态：长上影线、长下影线、十字星等
    VOLUME_ANOMALY = "volume_anomaly"         # 成交量异常：放量、缩量、量价背离等
    VWAP_DEVIATION = "vwap_deviation"         # VWAP偏离：价格与VWAP的偏离程度
    MOMENTUM = "momentum"                     # 动量类：趋势强度、价格动量
    MEAN_REVERSION = "mean_reversion"         # 均值回复：价格偏离均值的程度
    VOLATILITY = "volatility"                 # 波动率类：价格波动幅度
    CORRELATION = "correlation"               # 相关性类：价格与成交量、不同价格序列的相关性
    SENTIMENT = "sentiment"                   # 情绪类：市场情绪指标
    BREAKTHROUGH = "breakthrough"             # 突破类：突破均线、突破前期高点/低点

    # ==================== 基本面类 ====================
    VALUATION = "valuation"                   # 估值因子：PE、PB、PS、PCF等
    PROFITABILITY = "profitability"           # 盈利因子：ROE、ROA、毛利率、净利率等
    GROWTH = "growth"                         # 成长因子：净利润增速、营收增速等
    QUALITY = "quality"                       # 质量因子：资产负债率、流动比率等


# 分类中文名称映射
CATEGORY_NAMES: Dict[FactorCategory, str] = {
    FactorCategory.KLINE_PATTERN: "K线形态",
    FactorCategory.VOLUME_ANOMALY: "成交量异常",
    FactorCategory.VWAP_DEVIATION: "VWAP偏离",
    FactorCategory.MOMENTUM: "动量类",
    FactorCategory.MEAN_REVERSION: "均值回复",
    FactorCategory.VOLATILITY: "波动率类",
    FactorCategory.CORRELATION: "相关性类",
    FactorCategory.SENTIMENT: "情绪类",
    FactorCategory.BREAKTHROUGH: "突破类",
    FactorCategory.VALUATION: "估值因子",
    FactorCategory.PROFITABILITY: "盈利因子",
    FactorCategory.GROWTH: "成长因子",
    FactorCategory.QUALITY: "质量因子",
}


# 分类描述
CATEGORY_DESCRIPTIONS: Dict[FactorCategory, str] = {
    FactorCategory.KLINE_PATTERN: "基于K线实体、影线、组合形态构建的因子",
    FactorCategory.VOLUME_ANOMALY: "基于成交量异常变化、量价关系构建的因子",
    FactorCategory.VWAP_DEVIATION: "基于价格与VWAP偏离程度的因子",
    FactorCategory.MOMENTUM: "基于价格趋势强度和动量效应的因子",
    FactorCategory.MEAN_REVERSION: "基于价格偏离均值程度的均值回复因子",
    FactorCategory.VOLATILITY: "基于价格波动幅度和波动率特征的因子",
    FactorCategory.CORRELATION: "基于价格与成交量、不同价格序列相关性的因子",
    FactorCategory.SENTIMENT: "基于市场情绪和行为金融的因子",
    FactorCategory.BREAKTHROUGH: "基于突破技术指标或价格区间的因子",
    FactorCategory.VALUATION: "基于估值指标（PE、PB、PS等）的因子",
    FactorCategory.PROFITABILITY: "基于盈利能力指标（ROE、ROA等）的因子",
    FactorCategory.GROWTH: "基于成长性指标（增速等）的因子",
    FactorCategory.QUALITY: "基于财务质量指标（杠杆率、流动性等）的因子",
}


# ==================== 通用输入输出参数描述 ====================
COMMON_INPUT_PARAMS = """
输入参数:
- calculator: FactorCalculator实例，内含以下数据:
  * price_data: pd.DataFrame, 价格数据(open, high, low, close, volume, vwap等)
  * 索引: (trade_date, stock_code) MultiIndex
  * 返回值: pd.Series, 每日收益率
"""

COMMON_OUTPUT_PARAMS = """
输出参数:
- pd.Series: 因子值序列
  * 索引: (trade_date, stock_code) MultiIndex
  * 值: 标准化后的因子值（通常已做截面排名或标准化处理）
  * 频率: 日频
"""

# ==================== WorldQuant 因子元数据 (101个) ====================
WQ_FACTOR_META: Dict[str, Dict] = {
    # ========== K线形态 (4个) ==========
    "WQ_001": {
        "name": "alpha_001",
        "category": FactorCategory.MOMENTUM,
        "description": "时间序列动量信号强度。基于价格的时间序列变化计算动量信号，捕捉短期趋势。公式：rank(ts_argmax(power(returns < 0, ts_std(close, 5)), 30))，衡量过去30天内收益率小于0的最大波动日期的排名，反映价格动量的时序特征。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(1)",
        "keywords": "动量,时序,信号,趋势,排名",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_009": {
        "name": "alpha_009",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "价格极值条件动量。基于最高价与最低价关系的条件动量因子。公式：sma(((high + low) / 2 - delay(high + low) / 2, 7) * (1 - rank(ts_std(close, 10))))，捕捉价格中枢移动与波动率的关系。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(9)",
        "keywords": "K线,极值,动量,条件,波动率",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_010": {
        "name": "alpha_010",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "价格极值条件动量排名。基于价格极值条件的排名动量。公式：rank(ts_max(((close - open) / sum(delay(close, 1), 2) / 2 - abs((close - delay(close, 1)) / sum(delay(close, 1), 2) / 2)) / delay(close, 1) / volume, 3))，衡量日内价格变化的极值特征。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(10)",
        "keywords": "K线,极值,排名,动量,日内",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_018": {
        "name": "alpha_018",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "开盘收盘价差波动与相关性。基于开盘价与收盘价关系的波动率和相关性因子。公式：close / open，结合日内波动与收盘开盘关系，捕捉日内价格形态。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(18)",
        "keywords": "K线,开盘,收盘,波动,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_020": {
        "name": "alpha_020",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "开盘与高低收盘的偏离。基于开盘价与昨日高低收盘价的偏离程度。公式：(-1 * rank((open - delay(high, 1))) * rank((open - delay(close, 1))) * rank((open - delay(low, 1))))，综合衡量开盘缺口的大小，捕捉跳空高开/低开的交易机会。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(20)",
        "keywords": "K线,开盘,缺口,偏离,跳空",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== 成交量异常 (7个) ==========
    "WQ_002": {
        "name": "alpha_002",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "量价背离相关性。基于收盘价与成交量的负相关性。公式：-1 * correlation(rank(delta(log(volume), 2)), rank((close - open) / open), 6)，衡量成交量变化与价格变化的相关性，负值表示量价背离。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(2)",
        "keywords": "成交量,量价背离,相关性,排名",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_007": {
        "name": "alpha_007",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "ADV20与成交量条件下的价格动量。基于ADV20和成交量条件的价格动量。公式：(adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7)) : -1，在放量时捕捉价格动量的时序排名。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(7)",
        "keywords": "成交量,ADV,动量,条件,时序排名",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_012": {
        "name": "alpha_012",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "成交量变化与价格变化反向。基于成交量变化方向与价格变化方向的反向关系。公式：sign(delta(volume, 1)) * (-1 * delta(close, 1))，放量时做空上涨、做多下跌；缩量时相反。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(12)",
        "keywords": "成交量,量价关系,方向,反向",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_013": {
        "name": "alpha_013",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "收盘价与成交量的协方差。基于收盘价排名与成交量排名的协方差。公式：-1 * rank(covariance(rank(close), rank(volume), 5))，衡量收盘价与成交量的协同变化程度。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(13)",
        "keywords": "成交量,协方差,排名,收盘价",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_015": {
        "name": "alpha_015",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "高价与成交量的相关性累积。基于最高价与成交量的相关性累积。公式：-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3)，捕捉量价相关性的短期趋势。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(15)",
        "keywords": "成交量,高价,相关性,累积",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_016": {
        "name": "alpha_016",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "高价与成交量的协方差。基于最高价排名与成交量排名的协方差。公式：-1 * rank(covariance(rank(high), rank(volume), 5))，与Alpha#13类似但使用最高价，更敏感地反映买方力量。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(16)",
        "keywords": "成交量,高价,协方差,买方力量",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_017": {
        "name": "alpha_017",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "价格动量与成交量排名的复合。基于价格动量与成交量排名的复合因子。公式：(((-1 * rank(ts_rank(close, 10))) * rank(delta(delta(close, 1), 1))) * rank(ts_rank((volume / adv20), 5)))，结合价格动量反转、价格加速度和成交量异常。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(17)",
        "keywords": "成交量,动量,排名,复合,加速度",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== VWAP偏离 (2个) ==========
    "WQ_005": {
        "name": "alpha_005",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "开盘与VWAP均值偏离乘以收盘VWAP偏离。基于开盘价和收盘价相对于VWAP的偏离。公式：(rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))，衡量价格与成交量加权均价的偏离程度。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(5)",
        "keywords": "VWAP,偏离,开盘,收盘,成交量加权",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_011": {
        "name": "alpha_011",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "VWAP与收盘价的极值偏离乘以成交量变化。基于VWAP与收盘价偏离的极值。公式：((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - close), 3))) * rank(delta(volume, 3)))，捕捉VWAP偏离程度与成交量变化的交互效应。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(11)",
        "keywords": "VWAP,偏离,极值,成交量变化",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== 动量类 (2个) ==========
    "WQ_008": {
        "name": "alpha_008",
        "category": FactorCategory.MOMENTUM,
        "description": "开盘与收益的累积乘积动量。基于开盘价与收益率的累积乘积。公式：-1 * rank(sum((open >= delay(open, 1)) ? 0 : power(abs(returns), 2), 5))，捕捉负收益日的累积动量效应。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(8)",
        "keywords": "动量,开盘,收益,累积,乘积",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_019": {
        "name": "alpha_019",
        "category": FactorCategory.MOMENTUM,
        "description": "7日价格变化符号与长期收益排名。基于短期价格方向与长期收益的结合。公式：(-1 * sign(((close - delay(close, 7)) + delta(close, 7)))) * (1 + rank((1 + sum(returns, 250))))，结合短期价格方向与长期收益水平。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(19)",
        "keywords": "动量,短期,长期,方向,收益",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== 相关性类 (3个) ==========
    "WQ_003": {
        "name": "alpha_003",
        "category": FactorCategory.CORRELATION,
        "description": "开盘价与成交量的相关性。基于开盘价与成交量的10日相关性。公式：-1 * correlation(rank(open), rank(volume), 10)，衡量开盘价水平与成交量的相关关系。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(3)",
        "keywords": "相关性,开盘,成交量,排名",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_006": {
        "name": "alpha_006",
        "category": FactorCategory.CORRELATION,
        "description": "开盘价与成交量的相关性（原始）。基于开盘价与成交量的原始相关性。公式：-1 * correlation(open, volume, 10)，与Alpha#3类似但使用原始值而非排名。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(6)",
        "keywords": "相关性,开盘,成交量,原始值",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_014": {
        "name": "alpha_014",
        "category": FactorCategory.CORRELATION,
        "description": "收益变化排名与开盘成交量相关性。基于收益率变化与开盘成交量的相关性。公式：(-1 * rank(delta(returns, 3))) * correlation(open, volume, 10)，结合收益动量与量价关系。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(14)",
        "keywords": "相关性,收益变化,开盘,成交量",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== 均值回复 (1个) ==========
    "WQ_004": {
        "name": "alpha_004",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "低价的时序排名。基于最低价的时序排名。公式：-1 * ts_rank(low, 9)，衡量最低价在9日窗口内的时序排名，偏好近期最低价较低的股票（均值回复）。",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(4)",
        "keywords": "均值回复,低价,时序排名,反转",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== Alpha#21 ~ Alpha#101 (新增) ==========
    "WQ_021": {
        "name": "alpha_021",
        "category": FactorCategory.VOLATILITY,
        "description": "WorldQuant Alpha#21: ((((sum(close, 8) / 8) + stddev(close, 8)) < (sum(close, 2) / 2)) ? (-1 * 1) : (((sum(close, 2) / 2)...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(21)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_022": {
        "name": "alpha_022",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#22: (-1 * (delta(correlation(high, volume, 5), 5) * rank(stddev(close, 20))))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(22)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_023": {
        "name": "alpha_023",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "WorldQuant Alpha#23: (((sum(high, 20) / 20) < high) ? (-1 * delta(high, 2)) : 0)",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(23)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_024": {
        "name": "alpha_024",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "WorldQuant Alpha#24: ((((delta((sum(close, 100) / 100), 100) / delay(close, 100)) < 0.05) || ((delta((sum(close, 100) / 1...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(24)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_025": {
        "name": "alpha_025",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "WorldQuant Alpha#25: rank(((((-1 * returns) * adv20) * vwap) * (high - close)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(25)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_026": {
        "name": "alpha_026",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#26: (-1 * ts_max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(26)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_027": {
        "name": "alpha_027",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#27: ((0.5 < rank((sum(correlation(rank(volume), rank(vwap), 6), 2) / 2.0))) ? (-1 * 1) : 1)",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(27)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_028": {
        "name": "alpha_028",
        "category": FactorCategory.CORRELATION,
        "description": "WorldQuant Alpha#28: scale(((correlation(adv20, low, 5) + ((high + low) / 2)) - close))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(28)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_029": {
        "name": "alpha_029",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#29: (min(product(rank(rank(scale(log(sum(ts_min(rank(rank((-1 * rank(delta((close - 1), 5))))), 2), 1)))...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(29)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_030": {
        "name": "alpha_030",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#30: (((1.0 - rank(((sign((close - delay(close, 1))) + sign((delay(close, 1) - delay(close, 2)))) + sign(...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(30)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_031": {
        "name": "alpha_031",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#31: ((rank(rank(rank(decay_linear((-1 * rank(rank(delta(close, 10)))), 10)))) + rank((-1 * delta(close, ...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(31)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_032": {
        "name": "alpha_032",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "WorldQuant Alpha#32: (scale(((sum(close, 7) / 7) - close)) + (20 * scale(correlation(vwap, delay(close, 5), 230))))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(32)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_033": {
        "name": "alpha_033",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#33: rank((-1 * ((1 - (open / close))^1)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(33)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_034": {
        "name": "alpha_034",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#34: rank(((1 - rank((stddev(returns, 2) / stddev(returns, 5)))) + (1 - rank(delta(close, 1)))))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(34)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_035": {
        "name": "alpha_035",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#35: ((Ts_Rank(volume, 32) * (1 - Ts_Rank(((close + high) - low), 16))) * (1 - Ts_Rank(returns, 32)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(35)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_036": {
        "name": "alpha_036",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#36: (((((2.21 * rank(correlation((close - open), delay(volume, 1), 15))) + (0.7 * rank((open - close))))...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(36)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_037": {
        "name": "alpha_037",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#37: (rank(correlation(delay((open - close), 1), close, 200)) + rank((open - close)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(37)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_038": {
        "name": "alpha_038",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#38: ((-1 * rank(Ts_Rank(close, 10))) * rank((close / open)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(38)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_039": {
        "name": "alpha_039",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#39: ((-1 * rank((delta(close, 7) * (1 - rank(decay_linear((volume / adv20), 9)))))) * (1 + rank(sum(retu...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(39)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_040": {
        "name": "alpha_040",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#40: ((-1 * rank(stddev(high, 10))) * correlation(high, volume, 10))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(40)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_041": {
        "name": "alpha_041",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "WorldQuant Alpha#41: (((high * low)^0.5) - vwap)",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(41)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_042": {
        "name": "alpha_042",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "WorldQuant Alpha#42: (rank((vwap - close)) / rank((vwap + close)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(42)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_043": {
        "name": "alpha_043",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#43: (ts_rank((volume / adv20), 20) * ts_rank((-1 * delta(close, 7)), 8))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(43)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_044": {
        "name": "alpha_044",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#44: (-1 * correlation(high, rank(volume), 5))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(44)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_045": {
        "name": "alpha_045",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#45: (-1 * ((rank((sum(delay(close, 5), 20) / 20)) * correlation(close, volume, 2)) * rank(correlation(su...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(45)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_046": {
        "name": "alpha_046",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#46: ((0.25 < (((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10))) ? (-1 *...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(46)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_047": {
        "name": "alpha_047",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "WorldQuant Alpha#47: ((((rank((1 / close)) * volume) / adv20) * ((high * rank((high - close))) / (sum(high, 5) / 5))) - r...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(47)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_049": {
        "name": "alpha_049",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#49: (((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < (-1 * 0.1)) ?...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(49)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_050": {
        "name": "alpha_050",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#50: (-1 * ts_max(rank(correlation(rank(volume), rank(vwap), 5)), 3))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(50)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_051": {
        "name": "alpha_051",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#51: (-1 * ts_min(rank(low), 9))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(51)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_052": {
        "name": "alpha_052",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#52: (((-1 * delta((close - open), 5)) * rank(correlation(returns, volume, 5))) * sign(delta(close, 5)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(52)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_053": {
        "name": "alpha_053",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "WorldQuant Alpha#53: (-1 * delta((close - high) / (high - low), 9))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(53)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_054": {
        "name": "alpha_054",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "WorldQuant Alpha#54: ((-1 * ((low - close) * (open^5))) / ((low - high) * (close^5)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(54)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_055": {
        "name": "alpha_055",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#55: (-1 * rank((open - ts_sum(close, 10)) * (open - close)) / open)",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(55)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_057": {
        "name": "alpha_057",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "WorldQuant Alpha#57: (0 < ts_min(delta(close, 1), 4)) ? delta(close, 1) : ((ts_max(delta(close, 1), 4) < 0) ? delta(close...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(57)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_060": {
        "name": "alpha_060",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "WorldQuant Alpha#60: (sign(delta(volume, 1)) * (-1 * delta(close, 1)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(60)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_061": {
        "name": "alpha_061",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "WorldQuant Alpha#61: (rank((vwap - ts_min(vwap, 16.1219))) * rank(correlation(vwap, delay(close, 3), 17.2346)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(61)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_062": {
        "name": "alpha_062",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#62: ((rank(correlation(vwap, sum(close, 5), 5.84778))^1.16428) * rank(correlation(rank(open), rank(volum...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(62)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_064": {
        "name": "alpha_064",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#64: ((rank(correlation(sum((open * 0.178404) + (low * 0.532934)), sum(adv20, 26.0715), 4.93316))^1) * ra...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(64)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_065": {
        "name": "alpha_065",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#65: ((rank(correlation((open), sum(adv20, 15.9854), 8.92289))^1) * rank(correlation(rank(close), rank(vo...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(65)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_068": {
        "name": "alpha_068",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#68: ((-1 * ts_rank(correlation(rank(high), rank(volume), 3), 3)) * rank(correlation(high, volume, 3)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(68)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_071": {
        "name": "alpha_071",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "WorldQuant Alpha#71: ((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - close), 3))) * rank(delta(volume, 3)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(71)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_072": {
        "name": "alpha_072",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#72: (rank(decay_linear(correlation(vwap, volume, 4.2439), 16.0019)) - rank(decay_linear(correlation(rank...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(72)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_073": {
        "name": "alpha_073",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#73: max((-1 * rank(delta(close, 7))), rank(ts_rank(close, 15)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(73)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_074": {
        "name": "alpha_074",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#74: ((rank(correlation(close, sum(adv20, 26.0715), 4.93316))^1) * rank(correlation(rank(vwap), rank(volu...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(74)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_075": {
        "name": "alpha_075",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#75: (rank(correlation(vwap, volume, 3.5981))^1) * rank(correlation(rank(close), rank(volume), 3.75563))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(75)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_077": {
        "name": "alpha_077",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#77: (rank(decay_linear(delta(close, 2), 8))^1) * rank(correlation(vwap, volume, 6.71741))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(77)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_078": {
        "name": "alpha_078",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#78: (rank(correlation(close, volume, 3.3477))^1) * rank(correlation(rank(close), rank(volume), 7.4048))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(78)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_081": {
        "name": "alpha_081",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#81: (rank(ts_max(delta(vwap, 3), 5))^1) * rank(correlation(vwap, volume, 9.58142))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(81)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_083": {
        "name": "alpha_083",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#83: (-1 * ((rank(open - ts_sum(close, 10)) * rank(open - close)) / open))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(83)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_085": {
        "name": "alpha_085",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#85: (rank(correlation(vwap, volume, 6.05074))^1) * rank(correlation(rank(close), rank(volume), 6.05074))...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(85)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_086": {
        "name": "alpha_086",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#86: ((-1 * ts_rank(correlation(rank(high), rank(volume), 3), 3)) * rank(correlation(high, volume, 3)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(86)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_088": {
        "name": "alpha_088",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#88: (rank((close - ts_min(close, 12)) / ts_min(close, 12))^1) * rank(correlation(rank(open), rank(volume...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(88)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_092": {
        "name": "alpha_092",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#92: (-1 * ts_rank(decay_linear(correlation(high, rank(volume), 3.5981), 9.20678), 16.0019))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(92)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_094": {
        "name": "alpha_094",
        "category": FactorCategory.MOMENTUM,
        "description": "WorldQuant Alpha#94: (-1 * ((rank(open - ts_sum(close, 10)) * rank(open - close)) / open))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(94)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_095": {
        "name": "alpha_095",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#95: (rank(ts_max(delta(vwap, 3), 5))^1) * rank(correlation(rank(close), rank(volume), 6.84356))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(95)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_096": {
        "name": "alpha_096",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#96: (rank(ts_max(delta(close, 2), 3))^1) * rank(correlation(rank(vwap), rank(volume), 3.75563))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(96)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_098": {
        "name": "alpha_098",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#98: (rank(decay_linear(correlation(vwap, volume, 4.2439), 16.0019))^1) * rank(correlation(rank(open), ra...",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(98)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_099": {
        "name": "alpha_099",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#99: ((rank(ts_max(delta(close, 2), 3))^1) * rank(correlation(rank(close), rank(volume), 6.84356)))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(99)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_101": {
        "name": "alpha_101",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "WorldQuant Alpha#101: ((close - open) / ((high - low) + 0.001))",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(101)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    
    # ========== 行业中性化因子 (21个) ==========
    "WQ_048": {
        "name": "alpha_048",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#48: 加权动量-成交量行业中性化。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(48)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_056": {
        "name": "alpha_056",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#56: 价格动量-行业成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(56)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_058": {
        "name": "alpha_058",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#58: 行业VWAP成交量相关性时序排名。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(58)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_059": {
        "name": "alpha_059",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#59: 行业收盘价成交量相关性时序排名。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(59)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_063": {
        "name": "alpha_063",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#63: 价格突破-行业收盘价成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(63)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_066": {
        "name": "alpha_066",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#66: 价格时序排名-行业VWAP成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(66)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_067": {
        "name": "alpha_067",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#67: 价格极值偏离-行业成交量收盘价相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(67)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_069": {
        "name": "alpha_069",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#69: VWAP变化极值-行业收盘价成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(69)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_070": {
        "name": "alpha_070",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#70: 价格变化极值-行业VWAP成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(70)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_076": {
        "name": "alpha_076",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#76: 行业收盘价成交量相关性衰减。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(76)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_079": {
        "name": "alpha_079",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#79: 价格变化极值-行业VWAP成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(79)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_080": {
        "name": "alpha_080",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#80: 价格时序排名-行业开盘价成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(80)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_082": {
        "name": "alpha_082",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#82: 行业最高价成交量相关性衰减。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(82)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_084": {
        "name": "alpha_084",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#84: 价格突破-行业VWAP成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(84)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_087": {
        "name": "alpha_087",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#87: VWAP成交量相关性-行业收盘价成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(87)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_089": {
        "name": "alpha_089",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#89: 价格动量-行业VWAP成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(89)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_090": {
        "name": "alpha_090",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#90: 价格变化极值-行业VWAP成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(90)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_091": {
        "name": "alpha_091",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#91: 价格变化极值-行业收盘价成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(91)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_093": {
        "name": "alpha_093",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#93: 价格变化极值-行业VWAP成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(93)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_097": {
        "name": "alpha_097",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#97: 价格变化极值-行业VWAP成交量相关性。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(97)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "WQ_100": {
        "name": "alpha_100",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "WorldQuant Alpha#100: 行业VWAP成交量相关性衰减。使用IndNeutralize函数消除行业间系统性差异",
        "source": "worldquant",
        "call_method": "WorldQuantFactors.calculate_factor(100)",
        "keywords": "行业中性化,IndNeutralize,成交量,相关性",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
}


# ==================== 国泰君安 因子元数据 (191个) ====================
GTJ_FACTOR_META: Dict[str, Dict] = {
    # ========== 量价相关因子 (5个) ==========
    "GTJ_001": {
        "name": "alpha_001",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "成交量对数变化与价格变化的相关性。公式：CORR(LOG(VOLUME), DELTA(CLOSE, 1), 6)，衡量成交量变化与价格变化的相关性，捕捉量价配合关系。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(1)",
        "keywords": "成交量,相关性,价格变化,对数",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_002": {
        "name": "alpha_002",
        "category": FactorCategory.MOMENTUM,
        "description": "价格变化的排名变化。公式：RANK(DELTA(CLOSE, 2))，计算收盘价2日变化的截面排名，捕捉短期价格动量。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(2)",
        "keywords": "动量,排名,价格变化,短期",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_003": {
        "name": "alpha_003",
        "category": FactorCategory.CORRELATION,
        "description": "成交量与收盘价的相关性。公式：CORR(VOLUME, CLOSE, 10)，衡量成交量与收盘价的10日相关性。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(3)",
        "keywords": "相关性,成交量,收盘价",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_004": {
        "name": "alpha_004",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "收盘价的时序排名。公式：TSRANK(CLOSE, 10)，收盘价10日时序排名，偏好近期收盘价相对较低的股票。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(4)",
        "keywords": "均值回复,时序排名,收盘价",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_005": {
        "name": "alpha_005",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "开盘与VWAP均值的偏离排名。公式：RANK(OPEN - MEAN(VWAP, 10))，衡量开盘价与VWAP10日均值的偏离程度。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(5)",
        "keywords": "VWAP,偏离,开盘,排名",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== 均值回复因子 (3个) ==========
    "GTJ_006": {
        "name": "alpha_006",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "开盘与成交量的负相关性。公式：-CORR(OPEN, VOLUME, 10)，开盘价与成交量的负相关性，用于均值回复策略。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(6)",
        "keywords": "均值回复,相关性,开盘,成交量",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_007": {
        "name": "alpha_007",
        "category": FactorCategory.MOMENTUM,
        "description": "价格变化与成交量变化的排名乘积。公式：RANK(DELTA(CLOSE, 3)) * RANK(DELTA(VOLUME, 3))，价格变化排名与成交量变化排名的乘积。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(7)",
        "keywords": "动量,排名,价格变化,成交量变化",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_008": {
        "name": "alpha_008",
        "category": FactorCategory.MOMENTUM,
        "description": "开盘收益累积乘积的动量。公式：SUM((OPEN > DELAY(OPEN, 1)) ? 0 : POWER(RET, 2), 5)，负收益日的收益平方累积。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(8)",
        "keywords": "动量,开盘,收益,累积",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== 动量因子 (4个) ==========
    "GTJ_009": {
        "name": "alpha_009",
        "category": FactorCategory.MOMENTUM,
        "description": "5日价格极值条件动量。公式：SMA(((HIGH + LOW) / 2 - DELAY((HIGH + LOW) / 2, 7)) * (1 - RANK(STD(CLOSE, 10))), 7)，价格中枢移动与波动率调整。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(9)",
        "keywords": "动量,极值,价格中枢,波动率",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_010": {
        "name": "alpha_010",
        "category": FactorCategory.MOMENTUM,
        "description": "7日价格变化的非线性动量。公式：RANK(MAX(POWER(DELTA(CLOSE, 7), 2), POWER(DELTA(CLOSE, 1), 2)))，价格变化的非线性度量。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(10)",
        "keywords": "动量,非线性,价格变化",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_011": {
        "name": "alpha_011",
        "category": FactorCategory.MOMENTUM,
        "description": "1日价格变化的时序排名。公式：TSRANK(DELTA(CLOSE, 1), 10)，1日价格变化的10日时序排名。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(11)",
        "keywords": "动量,时序排名,价格变化",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_012": {
        "name": "alpha_012",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "开盘与收盘均值的偏离排名。公式：RANK((OPEN - MEAN(CLOSE, 10)) / MEAN(CLOSE, 10))，开盘价与收盘价均值的相对偏离。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(12)",
        "keywords": "均值回复,开盘,收盘,偏离",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== 波动率因子 (3个) ==========
    "GTJ_013": {
        "name": "alpha_013",
        "category": FactorCategory.VOLATILITY,
        "description": "收盘价的20日标准差排名。公式：RANK(STD(CLOSE, 20))，收盘价20日标准差的截面排名，衡量价格波动率。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(13)",
        "keywords": "波动率,标准差,收盘,排名",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_014": {
        "name": "alpha_014",
        "category": FactorCategory.CORRELATION,
        "description": "开盘与收盘的负相关性。公式：-CORR(OPEN, CLOSE, 10)，开盘价与收盘价的负相关性。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(14)",
        "keywords": "相关性,开盘,收盘",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_015": {
        "name": "alpha_015",
        "category": FactorCategory.VOLATILITY,
        "description": "高低价差的10日标准差排名。公式：RANK(STD(HIGH - LOW, 10))，日内振幅的10日标准差排名。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(15)",
        "keywords": "波动率,标准差,高低价差,振幅",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== 相关性因子 (3个) ==========
    "GTJ_016": {
        "name": "alpha_016",
        "category": FactorCategory.CORRELATION,
        "description": "高价与成交量的负相关性。公式：-CORR(HIGH, VOLUME, 10)，最高价与成交量的负相关性。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(16)",
        "keywords": "相关性,高价,成交量",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_017": {
        "name": "alpha_017",
        "category": FactorCategory.CORRELATION,
        "description": "低价与成交量的负相关性。公式：-CORR(LOW, VOLUME, 10)，最低价与成交量的负相关性。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(17)",
        "keywords": "相关性,低价,成交量",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_018": {
        "name": "alpha_018",
        "category": FactorCategory.CORRELATION,
        "description": "收盘价与成交量的负相关性。公式：-CORR(CLOSE, VOLUME, 10)，收盘价与成交量的负相关性。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(18)",
        "keywords": "相关性,收盘,成交量",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== 成交量因子 (2个) ==========
    "GTJ_019": {
        "name": "alpha_019",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "成交量的1日变化排名。公式：RANK(DELTA(VOLUME, 1))，成交量1日变化的截面排名。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(19)",
        "keywords": "成交量,变化,排名",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_020": {
        "name": "alpha_020",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "5日与20日成交量比值的排名。公式：RANK(SUM(VOLUME, 5) / SUM(VOLUME, 20))，短期与长期成交量比值的排名。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(20)",
        "keywords": "成交量,比值,排名,短期,长期",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== 价格形态因子 (3个) ==========
    "GTJ_021": {
        "name": "alpha_021",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "日内振幅与收盘价的比值。公式：(CLOSE - OPEN) / (HIGH - LOW + 0.001)，日内涨跌幅与振幅的比值，衡量价格方向强度。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(21)",
        "keywords": "K线,振幅,收盘,开盘,方向强度",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_022": {
        "name": "alpha_022",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "收盘开盘价差与收盘价的比值。公式：(CLOSE - OPEN) / CLOSE，日内涨跌幅的相对度量。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(22)",
        "keywords": "K线,收盘,开盘,涨跌幅",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_023": {
        "name": "alpha_023",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "上影线与下影线的比值。公式：(HIGH - MAX(CLOSE, OPEN)) / (MIN(CLOSE, OPEN) - LOW + 0.001)，上影线与下影线的比值，衡量多空力量对比。",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(23)",
        "keywords": "K线,上影线,下影线,多空力量",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },

    # ========== Alpha#24 ~ Alpha#191 (新增) ==========
    "GTJ_024": {
        "name": "alpha_024",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#24: SMA(CLOSE-DELAY(CLOSE,5),5,1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(24)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_025": {
        "name": "alpha_025",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#25: 复合动量因子：结合多窗口动量和成交量变化的复合信号",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(25)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_026": {
        "name": "alpha_026",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#26: (((SUM(CLOSE,7)/7)-CLOSE))+CORR(VWAP,DELAY(CLOSE,5),230))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(26)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_027": {
        "name": "alpha_027",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "国泰君安 Alpha#27: WMA((CLOSE-DELAY(CLOSE,3))/DELAY(CLOSE,3)*100+(CLOSE-DELAY(CLOSE,6))/DELAY(CLOSE...",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(27)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_028": {
        "name": "alpha_028",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#28: 3*SMA(RSV,3,1)-2*SMA(SMA(RSV,3,1),3,1) — KDJ的K值",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(28)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_029": {
        "name": "alpha_029",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "国泰君安 Alpha#29: (CLOSE-DELAY(CLOSE,6))/DELAY(CLOSE,6)*VOLUME",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(29)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_030": {
        "name": "alpha_030",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "国泰君安 Alpha#30: WMA((REGRESI(CLOSE/DELAY(CLOSE)-1,MKT,SMB,HML,60))^2,20)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(30)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_031": {
        "name": "alpha_031",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#31: (CLOSE-MEAN(CLOSE,12))/MEAN(CLOSE,12)*100",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(31)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_032": {
        "name": "alpha_032",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#32: (-1 * SUM(RANK(CORR(RANK(HIGH), RANK(VOLUME), 3)), 3))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(32)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_033": {
        "name": "alpha_033",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#33: 复合量价因子：结合多个量价子信号的复合指标",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(33)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_034": {
        "name": "alpha_034",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#34: MEAN(CLOSE,12)/CLOSE",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(34)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_035": {
        "name": "alpha_035",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#35: (MIN(RANK(DECAYLINEAR(DELTA(OPEN,1),15)),RANK(DECAYLINEAR(CORR(VOLUME,OPEN,17),7...",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(35)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_036": {
        "name": "alpha_036",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#36: RANK(SUM(CORR(RANK(VOLUME), RANK(VWAP)), 6), 2)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(36)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_037": {
        "name": "alpha_037",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#37: (-1 * RANK(((SUM(OPEN,5)*SUM(RET,5))-DELAY(...,10))))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(37)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_038": {
        "name": "alpha_038",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#38: (((SUM(HIGH,20)/20)<HIGH)?(-1*DELTA(HIGH,2)):0)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(38)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_039": {
        "name": "alpha_039",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#39: 复合动量因子：结合多个动量子信号的复合指标",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(39)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_040": {
        "name": "alpha_040",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#40: SUM(上涨日VOLUME,26)/SUM(下跌日VOLUME,26)*100",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(40)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_041": {
        "name": "alpha_041",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#41: (RANK(MAX(DELTA(VWAP,3),5))*-1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(41)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_042": {
        "name": "alpha_042",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#42: ((-1*RANK(STD(HIGH,10)))*CORR(HIGH,VOLUME,10))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(42)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_043": {
        "name": "alpha_043",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#43: SUM(带方向VOLUME,6) — OBV简化版",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(43)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_044": {
        "name": "alpha_044",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#44: TSRANK(DECAYLINEAR(CORR(LOW,MEAN(VOLUME,10),7),6),4)+TSRANK(DECAYLINEAR(DELTA(VW...",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(44)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_045": {
        "name": "alpha_045",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#45: (RANK(DELTA((CLOSE*0.6+OPEN*0.4),1))*RANK(CORR(VWAP,MEAN(VOLUME,150),15)))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(45)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_046": {
        "name": "alpha_046",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#46: (MA3+MA6+MA12+MA24)/(4*CLOSE) — BBI变体",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(46)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_047": {
        "name": "alpha_047",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#47: SMA((TSMAX(HIGH,6)-CLOSE)/(TSMAX(HIGH,6)-TSMIN(LOW,6))*100,9,1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(47)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_048": {
        "name": "alpha_048",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#48: (-1*RANK(3日SIGN和)*SUM(V,5)/SUM(V,20))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(48)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_049": {
        "name": "alpha_049",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#49: 下突破振幅占比(12日)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(49)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_050": {
        "name": "alpha_050",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#50: 下突破占比-上突破占比(12日)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(50)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_051": {
        "name": "alpha_051",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#51: 纯下突破占比(12日)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(51)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_052": {
        "name": "alpha_052",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#52: 26日典型价格推力比×100",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(52)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_053": {
        "name": "alpha_053",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#53: COUNT(上涨,12)/12*100",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(53)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_054": {
        "name": "alpha_054",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#54: (-1*RANK((STD(|C-O|)+(C-O))+CORR(C,O,10)))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(54)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_055": {
        "name": "alpha_055",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#55: 20日累积TR-normalised动量",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(55)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_056": {
        "name": "alpha_056",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#56: 条件判断因子(0/1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(56)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_057": {
        "name": "alpha_057",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#57: SMA(RSV,3,1) — KDJ-K值",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(57)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_058": {
        "name": "alpha_058",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#58: COUNT(上涨,20)/20*100",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(58)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_059": {
        "name": "alpha_059",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#59: 20日真实波动幅度累积",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(59)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_060": {
        "name": "alpha_060",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#60: SUM(量价方向,20)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(60)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_061": {
        "name": "alpha_061",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#61: MAX(两个衰减排名)*-1",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(61)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_062": {
        "name": "alpha_062",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#62: (-1*CORR(HIGH,RANK(VOLUME),5))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(62)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_063": {
        "name": "alpha_063",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#63: SMA(MAX(RET,0),6,1)/SMA(|RET|,6,1)*100 — 6日RSI",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(63)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_064": {
        "name": "alpha_064",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#64: MAX(两个衰减CORR排名)*-1",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(64)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_065": {
        "name": "alpha_065",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#65: MEAN(CLOSE,6)/CLOSE",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(65)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_066": {
        "name": "alpha_066",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#66: (CLOSE-MA6)/MA6*100",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(66)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_067": {
        "name": "alpha_067",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#67: 24日RSI",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(67)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_068": {
        "name": "alpha_068",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#68: SMA(中间价加速度×振幅/VOL,15,2)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(68)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_069": {
        "name": "alpha_069",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#69: DTM/DBM 20日非对称比率",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(69)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_070": {
        "name": "alpha_070",
        "category": FactorCategory.VOLATILITY,
        "description": "国泰君安 Alpha#70: STD(AMOUNT,6)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(70)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_071": {
        "name": "alpha_071",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#71: (CLOSE-MA24)/MA24*100",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(71)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_072": {
        "name": "alpha_072",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#72: SMA(1-RSV,15,1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(72)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_073": {
        "name": "alpha_073",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#73: 复合量价因子*-1",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(73)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_074": {
        "name": "alpha_074",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#74: RANK(CORR(加权价,MA(V,40),7))+RANK(CORR(RANK(VWAP),RANK(V),6))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(74)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_075": {
        "name": "alpha_075",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#75: COUNT(个股涨&大盘跌,50)/COUNT(大盘跌,50)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(75)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_076": {
        "name": "alpha_076",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#76: STD(|RET|/V,20)/MEAN(|RET|/V,20)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(76)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_077": {
        "name": "alpha_077",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#77: MIN(两个衰减排名)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(77)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_078": {
        "name": "alpha_078",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#78: (TYP-MA(TYP,12))/(0.015*MAD) — CCI指标",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(78)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_079": {
        "name": "alpha_079",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#79: 12日RSI",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(79)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_080": {
        "name": "alpha_080",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "国泰君安 Alpha#80: (V-DELAY(V,5))/DELAY(V,5)*100",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(80)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_081": {
        "name": "alpha_081",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#81: SMA(VOLUME,21,2)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(81)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_082": {
        "name": "alpha_082",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#82: SMA(1-RSV,20,1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(82)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_083": {
        "name": "alpha_083",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#83: (-1*RANK(COV(RANK(HIGH),RANK(VOLUME),5)))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(83)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_084": {
        "name": "alpha_084",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#84: SUM(带方向VOLUME,20)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(84)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_085": {
        "name": "alpha_085",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#85: TSRANK(V/MA20V,20)*TSRANK(-DELTA(C,7),8)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(85)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_086": {
        "name": "alpha_086",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#86: 20/10/0 价格加速度三重条件",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(86)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_087": {
        "name": "alpha_087",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#87: 复合量价因子*-1",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(87)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_088": {
        "name": "alpha_088",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#88: 20日百分比动量",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(88)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_089": {
        "name": "alpha_089",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#89: 2*(SMA13-SMA27-SMA10(SMA13-SMA27)) — MACD",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(89)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_090": {
        "name": "alpha_090",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#90: (RANK(CORR(RANK(VWAP),RANK(V),5))*-1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(90)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_091": {
        "name": "alpha_091",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#91: (RANK(C-MAX(C,5))*RANK(CORR(MA(V,40),LOW,5)))*-1",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(91)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_092": {
        "name": "alpha_092",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#92: MAX(两个衰减排名)*-1",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(92)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_093": {
        "name": "alpha_093",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#93: 20日开盘向下突破累积",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(93)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_094": {
        "name": "alpha_094",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#94: SUM(带方向VOLUME,30)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(94)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_095": {
        "name": "alpha_095",
        "category": FactorCategory.VOLATILITY,
        "description": "国泰君安 Alpha#95: STD(AMOUNT,20)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(95)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_096": {
        "name": "alpha_096",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#96: SMA(SMA(RSV,3,1),3,1) — KDJ-D值",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(96)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_097": {
        "name": "alpha_097",
        "category": FactorCategory.VOLATILITY,
        "description": "国泰君安 Alpha#97: STD(VOLUME,10)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(97)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_098": {
        "name": "alpha_098",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#98: 100日MA加速度三重条件",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(98)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_099": {
        "name": "alpha_099",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#99: (-1*RANK(COV(RANK(CLOSE),RANK(VOLUME),5)))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(99)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_100": {
        "name": "alpha_100",
        "category": FactorCategory.VOLATILITY,
        "description": "国泰君安 Alpha#100: STD(VOLUME,20)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(100)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_101": {
        "name": "alpha_101",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#101: 条件判断因子(0/-1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(101)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_102": {
        "name": "alpha_102",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#102: SMA(MAX(dV,0),6,1)/SMA(|dV|,6,1)*100 — 成交量RSI",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(102)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_103": {
        "name": "alpha_103",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#103: ((20-LOWDAY(LOW,20))/20)*100 — 最低价新鲜度",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(103)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_104": {
        "name": "alpha_104",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#104: (-1*DELTA(CORR(HIGH,VOL,5),5)*RANK(STD(CLOSE,20)))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(104)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_105": {
        "name": "alpha_105",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#105: (-1*CORR(RANK(OPEN),RANK(VOLUME),10))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(105)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_106": {
        "name": "alpha_106",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "国泰君安 Alpha#106: CLOSE-DELAY(CLOSE,20)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(106)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_107": {
        "name": "alpha_107",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#107: (-rank(o-prev_h)*rank(o-prev_c)*rank(o-prev_l))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(107)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_108": {
        "name": "alpha_108",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#108: (rank(high-min(high,2))^rank(corr(vwap,ma(v,120),6)))*-1",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(108)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_109": {
        "name": "alpha_109",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#109: SMA(H-L,10,2)/SMA(SMA(H-L,10,2),10,2) — 振幅RSI",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(109)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_110": {
        "name": "alpha_110",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#110: 20日向上推力/向下推力×100",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(110)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_111": {
        "name": "alpha_111",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#111: SMA(A/D,11,2)-SMA(A/D,4,2) — A/D的MACD",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(111)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_112": {
        "name": "alpha_112",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#112: (SUM(上涨差,12)-SUM(下跌差,12))/(SUM(上涨差,12)+SUM(下跌差,12))*100 — CMO",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(112)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_113": {
        "name": "alpha_113",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#113: (-1*复合排名乘积)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(113)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_114": {
        "name": "alpha_114",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#114: rank(delay(振幅比,2))*rank(rank(v))/((振幅比)/(vwap-c))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(114)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_115": {
        "name": "alpha_115",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#115: rank(corr(0.9H+0.1C,ma(v,30),10))^rank(corr(tsr_HL2_4,tsr_v_10,7))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(115)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_116": {
        "name": "alpha_116",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#116: REGBETA(CLOSE,SEQUENCE,20)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(116)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_117": {
        "name": "alpha_117",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#117: tsrank(v,32)*(1-tsrank(c+h-l,16))*(1-tsrank(ret,32))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(117)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_118": {
        "name": "alpha_118",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "国泰君安 Alpha#118: SUM(HIGH-OPEN,20)/SUM(OPEN-LOW,20)*100 — 上影线/下影线比",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(118)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_119": {
        "name": "alpha_119",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#119: 复合相关性因子",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(119)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_120": {
        "name": "alpha_120",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#120: rank(vwap-close)/rank(vwap+close)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(120)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_121": {
        "name": "alpha_121",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#121: (rank(vwap-min(vwap,12))^tsrank(corr(...),3))*-1",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(121)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_122": {
        "name": "alpha_122",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#122: 三重SMA(log(close),13,2)的1日变化率",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(122)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_123": {
        "name": "alpha_123",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#123: 条件判断因子(0/-1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(123)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_124": {
        "name": "alpha_124",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#124: (close-vwap)/decaylinear(rank(ts_max(close,30)),2)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(124)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_125": {
        "name": "alpha_125",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#125: rank(decay_linear(corr_vwap_mv80,20))/rank(decay_linear(delta(0.5C+0.5VWAP,3),16...",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(125)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_126": {
        "name": "alpha_126",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "国泰君安 Alpha#126: (CLOSE+HIGH+LOW)/3 — 典型价格",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(126)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_127": {
        "name": "alpha_127",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#127: sqrt(mean((100*(c-max(c,12))/max(c,12))^2)) — 回撤RMS",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(127)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_128": {
        "name": "alpha_128",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#128: 100-(100/(1+SUM(上涨日TYP*V,14)/SUM(下跌日TYP*V,14))) — MFI",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(128)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_129": {
        "name": "alpha_129",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#129: SUM(下跌差值,12)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(129)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_130": {
        "name": "alpha_130",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#130: rank(decay_linear(corr(HL2,mv40,9),10))/rank(decay_linear(corr(rk_vwap,rk_v,7),3...",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(130)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_131": {
        "name": "alpha_131",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#131: rank(delta(vwap,1))^tsrank(corr(close,mv50,18),18)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(131)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_132": {
        "name": "alpha_132",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#132: MEAN(AMOUNT,20)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(132)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_133": {
        "name": "alpha_133",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "国泰君安 Alpha#133: (20-highday(high,20))/20*100-(20-lowday(low,20))/20*100",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(133)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_134": {
        "name": "alpha_134",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#134: (c-prev_c12)/prev_c12*VOLUME",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(134)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_135": {
        "name": "alpha_135",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#135: SMA(DELAY(CLOSE/DELAY(CLOSE,20),1),20,1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(135)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_136": {
        "name": "alpha_136",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#136: (-rank(delta(ret,3))*corr(open,volume,10))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(136)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_137": {
        "name": "alpha_137",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#137: 16*(价格变化)/TR*MAX(|H-prevC|,|L-prevC|) — Wilders TR-normalised",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(137)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_138": {
        "name": "alpha_138",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#138: 复合相关性因子*-1",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(138)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_139": {
        "name": "alpha_139",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#139: (-1*CORR(OPEN,VOLUME,10))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(139)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_140": {
        "name": "alpha_140",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#140: MIN(rank(衰减(rank_OL_HC,8)),tsr(衰减(corr(...),7),3))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(140)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_141": {
        "name": "alpha_141",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#141: (rank(corr(rank(high),rank(mean(v,15)),9))*-1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(141)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_142": {
        "name": "alpha_142",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#142: (-rank(tsr_c10)*rank(d2_close)*rank(tsr_vrel_5))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(142)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_143": {
        "name": "alpha_143",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#143: 递归上涨累积因子 [STUB/SELF引用]",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(143)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_144": {
        "name": "alpha_144",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#144: 20日下跌日|RET|/AMOUNT均值",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(144)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_145": {
        "name": "alpha_145",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#145: (mean(v,9)-mean(v,26))/mean(v,12)*100 — 成交量偏离率",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(145)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_146": {
        "name": "alpha_146",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#146: 收益率偏差的t统计量变体",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(146)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_147": {
        "name": "alpha_147",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#147: REGBETA(MEAN(CLOSE,12),SEQUENCE(12))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(147)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_148": {
        "name": "alpha_148",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#148: 条件判断因子(0/-1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(148)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_149": {
        "name": "alpha_149",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#149: 大盘下跌日Beta",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(149)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_150": {
        "name": "alpha_150",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "国泰君安 Alpha#150: (CLOSE+HIGH+LOW)/3*VOLUME",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(150)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_151": {
        "name": "alpha_151",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#151: SMA(CLOSE-DELAY(CLOSE,20),20,1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(151)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_152": {
        "name": "alpha_152",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#152: SMA(MEAN(DELAY(SMA(DELAY(CLOSE/DELAY(CLOSE,9),1),9,1),1),12)-MEAN(...,26),9,1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(152)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_153": {
        "name": "alpha_153",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#153: (MA3+MA6+MA12+MA24)/4 — BBI指标",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(153)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_154": {
        "name": "alpha_154",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#154: 条件判断因子(0/1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(154)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_155": {
        "name": "alpha_155",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#155: SMA(VOL,13,2)-SMA(VOL,27,2)-SMA(SMA(VOL,13,2)-SMA(VOL,27,2),10,2) — 成交量MACD",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(155)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_156": {
        "name": "alpha_156",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#156: MAX(两个衰减排名)*-1",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(156)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_157": {
        "name": "alpha_157",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#157: 极复杂嵌套排名因子+TSRANK",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(157)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_158": {
        "name": "alpha_158",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "国泰君安 Alpha#158: (HIGH-LOW)/CLOSE — 振幅比率",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(158)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_159": {
        "name": "alpha_159",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#159: 多窗口KDJ加权平均(6/12/24)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(159)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_160": {
        "name": "alpha_160",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#160: SMA(下跌日STD(CLOSE,20),20,1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(160)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_161": {
        "name": "alpha_161",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#161: MEAN(TR,12) — 12日ATR",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(161)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_162": {
        "name": "alpha_162",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#162: (RSI12-MIN(RSI12,12))/(MAX(RSI12,12)-MIN(RSI12,12)) — Stochastic-RSI",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(162)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_163": {
        "name": "alpha_163",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#163: RANK((-RET*MA(V,20)*VWAP*(HIGH-CLOSE)))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(163)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_164": {
        "name": "alpha_164",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#164: SMA((上涨日1/涨幅-最小值)/(H-L)*100,13,2)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(164)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_165": {
        "name": "alpha_165",
        "category": FactorCategory.VOLATILITY,
        "description": "国泰君安 Alpha#165: MAX(SUMAC(CLOSE-MA48))-MIN(SUMAC(CLOSE-MA48))/STD(CLOSE,48)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(165)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_166": {
        "name": "alpha_166",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#166: 20日收益率偏度统计量",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(166)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_167": {
        "name": "alpha_167",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#167: SUM(上涨差值,12)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(167)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_168": {
        "name": "alpha_168",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#168: (-1*VOLUME/MEAN(VOLUME,20))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(168)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_169": {
        "name": "alpha_169",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#169: SMA(MEAN(DELAY(SMA(dC,9,1),1),12)-MEAN(...,26),10,1) — 差分MACD",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(169)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_170": {
        "name": "alpha_170",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#170: 复合多维度因子",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(170)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_171": {
        "name": "alpha_171",
        "category": FactorCategory.KLINE_PATTERN,
        "description": "国泰君安 Alpha#171: (-(LOW-CLOSE)*OPEN^5)/((CLOSE-HIGH)*CLOSE^5)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(171)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_172": {
        "name": "alpha_172",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#172: MEAN(|DX|,6) — ADX变体",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(172)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_173": {
        "name": "alpha_173",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#173: 3*SMA(C,13,2)-2*SMA^2(C,13,2)+SMA^3(LOG(C),13,2)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(173)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_174": {
        "name": "alpha_174",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#174: SMA(上涨日STD(CLOSE,20),20,1)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(174)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_175": {
        "name": "alpha_175",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#175: MEAN(TR,6) — 6日ATR",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(175)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_176": {
        "name": "alpha_176",
        "category": FactorCategory.VOLUME_ANOMALY,
        "description": "国泰君安 Alpha#176: CORR(RANK(K12),RANK(VOLUME),6)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(176)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_177": {
        "name": "alpha_177",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#177: ((20-HIGHDAY(HIGH,20))/20)*100 — 最高价新鲜度",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(177)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_178": {
        "name": "alpha_178",
        "category": FactorCategory.MEAN_REVERSION,
        "description": "国泰君安 Alpha#178: (CLOSE-DELAY(CLOSE,1))/DELAY(CLOSE,1)*VOLUME",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(178)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_179": {
        "name": "alpha_179",
        "category": FactorCategory.VWAP_DEVIATION,
        "description": "国泰君安 Alpha#179: RANK(CORR(VWAP,V,4))*RANK(CORR(RANK(LOW),RANK(MA(V,50)),12))",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(179)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_180": {
        "name": "alpha_180",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#180: 条件因子：放量时看价格方向，缩量时看成交量",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(180)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_181": {
        "name": "alpha_181",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#181: 个股超额收益累积/基准偏度 — 偏度调整Alpha",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(181)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_182": {
        "name": "alpha_182",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#182: 20日个股与大盘同向运动天数占比",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(182)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_183": {
        "name": "alpha_183",
        "category": FactorCategory.VOLATILITY,
        "description": "国泰君安 Alpha#183: MAX(SUMAC(CLOSE-MA24))-MIN(SUMAC(CLOSE-MA24))/STD(CLOSE,24)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(183)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_184": {
        "name": "alpha_184",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#184: RANK(CORR(DELAY(O-C,1),CLOSE,200))+RANK(O-C)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(184)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_185": {
        "name": "alpha_185",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#185: RANK(-(1-OPEN/CLOSE)^2)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(185)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_186": {
        "name": "alpha_186",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#186: (MEAN(|DX|,6)+DELAY(MEAN(|DX|,6),6))/2 — 平滑ADX",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(186)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_187": {
        "name": "alpha_187",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#187: SUM(开盘向上突破,20)",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(187)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_188": {
        "name": "alpha_188",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#188: ((H-L-SMA(H-L,11,2))/SMA(H-L,11,2))*100 — 振幅偏离率",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(188)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_189": {
        "name": "alpha_189",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#189: MEAN(ABS(CLOSE-MA6),6) — MAD",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(189)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_190": {
        "name": "alpha_190",
        "category": FactorCategory.MOMENTUM,
        "description": "国泰君安 Alpha#190: LOG(上涨/下跌日偏差比) — 收益率不对称性",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(190)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
    "GTJ_191": {
        "name": "alpha_191",
        "category": FactorCategory.CORRELATION,
        "description": "国泰君安 Alpha#191: CORR(MA(V,20),LOW,5)+((H+L)/2)-CLOSE",
        "source": "guotai",
        "call_method": "GuotaiFactors.calculate_factor(191)",
        "keywords": "动量,排名,时序",
        "input_params": COMMON_INPUT_PARAMS.strip(),
        "output_params": COMMON_OUTPUT_PARAMS.strip(),
    },
}


# ==================== 基本面因子元数据 (22个) ====================
FUNDAMENTAL_INPUT_PARAMS = """
输入参数:
- financial_data: pd.DataFrame, 财务数据
  * 索引: stock_code 或 (trade_date, stock_code)
  * 必需字段: 根据具体因子不同，需要相应的财务指标字段
  * 数据来源: 财务报表(资产负债表、利润表、现金流量表)
"""

FUNDAMENTAL_OUTPUT_PARAMS = """
输出参数:
- pd.Series: 因子值序列
  * 索引: stock_code 或 (trade_date, stock_code)
  * 值: 财务指标计算值
  * 频率: 季度/年度（根据财报发布频率）
"""

FUNDAMENTAL_FACTOR_META: Dict[str, Dict] = {
    # ========== 估值因子 (8个) ==========
    "VAL_PE": {
        "name": "PE倒数",
        "category": FactorCategory.VALUATION,
        "description": "市盈率倒数（Earnings Yield）。公式：净利润 / 总市值，衡量每单位市值对应的盈利能力，是PE的倒数，值越大表示估值越低。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_valuation_factors()['PE倒数']",
        "keywords": "估值,PE,市盈率,盈利收益率",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "VAL_PB": {
        "name": "PB倒数",
        "category": FactorCategory.VALUATION,
        "description": "市净率倒数。公式：净资产 / 总市值，每单位市值对应的净资产，PB的倒数，值越大表示估值越低。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_valuation_factors()['PB倒数']",
        "keywords": "估值,PB,市净率,净资产",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "VAL_PS": {
        "name": "PS倒数",
        "category": FactorCategory.VALUATION,
        "description": "市销率倒数。公式：营业收入 / 总市值，每单位市值对应的营业收入，PS的倒数。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_valuation_factors()['PS倒数']",
        "keywords": "估值,PS,市销率,营收",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "VAL_PCF": {
        "name": "PCF倒数",
        "category": FactorCategory.VALUATION,
        "description": "市现率倒数。公式：经营现金流 / 总市值，每单位市值对应的经营现金流，PCF的倒数。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_valuation_factors()['PCF倒数']",
        "keywords": "估值,PCF,市现率,现金流",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "VAL_EP": {
        "name": "EP",
        "category": FactorCategory.VALUATION,
        "description": "净利润/总市值。公式：净利润 / 总市值，与PE倒数相同，衡量盈利收益率。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_valuation_factors()['EP']",
        "keywords": "估值,EP,盈利收益率,净利润",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "VAL_BP": {
        "name": "BP",
        "category": FactorCategory.VALUATION,
        "description": "净资产/总市值。公式：净资产 / 总市值，与PB倒数相同，衡量账面价值比率。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_valuation_factors()['BP']",
        "keywords": "估值,BP,账面价值,净资产",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "VAL_SP": {
        "name": "SP",
        "category": FactorCategory.VALUATION,
        "description": "营业收入/总市值。公式：营业收入 / 总市值，与PS倒数相同，衡量营收收益率。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_valuation_factors()['SP']",
        "keywords": "估值,SP,营收收益率,营业收入",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "VAL_CFP": {
        "name": "CFP",
        "category": FactorCategory.VALUATION,
        "description": "经营现金流/总市值。公式：经营现金流 / 总市值，与PCF倒数相同，衡量现金流收益率。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_valuation_factors()['CFP']",
        "keywords": "估值,CFP,现金流收益率,经营现金流",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },

    # ========== 盈利因子 (5个) ==========
    "PROF_ROE": {
        "name": "ROE",
        "category": FactorCategory.PROFITABILITY,
        "description": "净资产收益率。公式：净利润 / 净资产，衡量股东权益的盈利能力，是核心盈利指标。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_profitability_factors()['ROE']",
        "keywords": "盈利,ROE,净资产收益率,净利润",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "PROF_ROA": {
        "name": "ROA",
        "category": FactorCategory.PROFITABILITY,
        "description": "总资产收益率。公式：净利润 / 总资产，衡量企业总资产的盈利能力。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_profitability_factors()['ROA']",
        "keywords": "盈利,ROA,总资产收益率,净利润",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "PROF_GPM": {
        "name": "GrossMargin",
        "category": FactorCategory.PROFITABILITY,
        "description": "毛利率。公式：(营业收入 - 营业成本) / 营业收入，衡量产品的基础盈利能力。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_profitability_factors()['GrossMargin']",
        "keywords": "盈利,毛利率,营收,成本",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "PROF_NPM": {
        "name": "NetMargin",
        "category": FactorCategory.PROFITABILITY,
        "description": "净利率。公式：净利润 / 营业收入，衡量最终盈利水平。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_profitability_factors()['NetMargin']",
        "keywords": "盈利,净利率,净利润,营收",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "PROF_EBITDA": {
        "name": "EBITDAMargin",
        "category": FactorCategory.PROFITABILITY,
        "description": "EBITDA利润率。公式：EBITDA / 营业收入，衡量息税折旧前盈利能力。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_profitability_factors()['EBITDAMargin']",
        "keywords": "盈利,EBITDA,利润率,息税折旧前",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },

    # ========== 成长因子 (5个) ==========
    "GROW_NP_Q": {
        "name": "NP_Growth_Q",
        "category": FactorCategory.GROWTH,
        "description": "净利润季度同比增速。公式：(本期净利润 - 去年同期净利润) / |去年同期净利润|，衡量净利润的季度同比增长。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_growth_factors()['NP_Growth_Q']",
        "keywords": "成长,净利润,季度同比,增速",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "GROW_REV_Q": {
        "name": "REV_Growth_Q",
        "category": FactorCategory.GROWTH,
        "description": "营业收入季度同比增速。公式：(本期营收 - 去年同期营收) / |去年同期营收|，衡量营收的季度同比增长。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_growth_factors()['REV_Growth_Q']",
        "keywords": "成长,营收,季度同比,增速",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "GROW_NP_Y": {
        "name": "NP_Growth_Y",
        "category": FactorCategory.GROWTH,
        "description": "净利润年度同比增速。公式：(本年净利润 - 去年净利润) / |去年净利润|，衡量净利润的年度同比增长。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_growth_factors()['NP_Growth_Y']",
        "keywords": "成长,净利润,年度同比,增速",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "GROW_REV_Y": {
        "name": "REV_Growth_Y",
        "category": FactorCategory.GROWTH,
        "description": "营业收入年度同比增速。公式：(本年营收 - 去年营收) / |去年营收|，衡量营收的年度同比增长。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_growth_factors()['REV_Growth_Y']",
        "keywords": "成长,营收,年度同比,增速",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "GROW_ASSET": {
        "name": "Asset_Growth",
        "category": FactorCategory.GROWTH,
        "description": "总资产同比增速。公式：(本期总资产 - 上期总资产) / 上期总资产，衡量企业规模扩张速度。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_growth_factors()['Asset_Growth']",
        "keywords": "成长,总资产,增速,规模扩张",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },

    # ========== 质量因子 (4个) ==========
    "QUAL_DEBT": {
        "name": "DebtRatio",
        "category": FactorCategory.QUALITY,
        "description": "资产负债率。公式：总负债 / 总资产，衡量企业财务杠杆水平，值越低财务风险越小。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_quality_factors()['DebtRatio']",
        "keywords": "质量,资产负债率,杠杆,财务风险",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "QUAL_CURRENT": {
        "name": "CurrentRatio",
        "category": FactorCategory.QUALITY,
        "description": "流动比率。公式：流动资产 / 流动负债，衡量短期偿债能力，值越高流动性越好。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_quality_factors()['CurrentRatio']",
        "keywords": "质量,流动比率,短期偿债,流动性",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "QUAL_QUICK": {
        "name": "QuickRatio",
        "category": FactorCategory.QUALITY,
        "description": "速动比率。公式：(流动资产 - 存货) / 流动负债，更严格的短期偿债能力指标。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_quality_factors()['QuickRatio']",
        "keywords": "质量,速动比率,短期偿债,存货",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
    "QUAL_ACCRUAL": {
        "name": "Accrual",
        "category": FactorCategory.QUALITY,
        "description": "应计项/总资产。公式：(净利润 - 经营现金流) / 总资产，衡量盈利质量，值越低盈利质量越高。",
        "source": "fundamental",
        "call_method": "FundamentalFactors.calculate_quality_factors()['Accrual']",
        "keywords": "质量,应计项,盈利质量,现金流",
        "input_params": FUNDAMENTAL_INPUT_PARAMS.strip(),
        "output_params": FUNDAMENTAL_OUTPUT_PARAMS.strip(),
    },
}


# 合并所有因子元数据
ALL_FACTOR_META: Dict[str, Dict] = {
    **WQ_FACTOR_META,
    **GTJ_FACTOR_META,
    **FUNDAMENTAL_FACTOR_META,
}


def get_factor_category(factor_id: str) -> Optional[FactorCategory]:
    """
    获取因子的分类

    Parameters
    ----------
    factor_id : str
        因子ID，如 "WQ_001", "GTJ_001", "VAL_PE"

    Returns
    -------
    FactorCategory or None
        因子分类，如果因子不存在则返回None
    """
    meta = ALL_FACTOR_META.get(factor_id)
    if meta:
        return meta.get("category")
    return None


def get_factor_name(factor_id: str) -> Optional[str]:
    """
    获取因子的名称

    Parameters
    ----------
    factor_id : str
        因子ID

    Returns
    -------
    str or None
        因子名称
    """
    meta = ALL_FACTOR_META.get(factor_id)
    if meta:
        return meta.get("name")
    return None


def get_factor_description(factor_id: str) -> Optional[str]:
    """
    获取因子的描述

    Parameters
    ----------
    factor_id : str
        因子ID

    Returns
    -------
    str or None
        因子描述
    """
    meta = ALL_FACTOR_META.get(factor_id)
    if meta:
        return meta.get("description")
    return None


def get_factor_full_info(factor_id: str) -> Optional[Dict]:
    """
    获取因子的完整信息

    Parameters
    ----------
    factor_id : str
        因子ID

    Returns
    -------
    dict or None
        因子的完整元数据，包含：
        - name: 因子名称
        - category: 因子分类
        - description: 因子描述
        - source: 因子来源(worldquant/guotai/fundamental)
        - call_method: 调用方法
        - keywords: 关键词
        - input_params: 输入参数
        - output_params: 输出参数
    """
    meta = ALL_FACTOR_META.get(factor_id)
    if meta:
        return {
            "factor_id": factor_id,
            **meta
        }
    return None


def get_factors_by_category(category: Union[FactorCategory, str]) -> List[str]:
    """
    按分类获取所有因子ID

    Parameters
    ----------
    category : FactorCategory or str
        因子分类或分类名称

    Returns
    -------
    List[str]
        该分类下的所有因子ID列表
    """
    if isinstance(category, str):
        # 尝试从字符串转换为枚举
        try:
            category = FactorCategory(category)
        except ValueError:
            # 尝试从中文名称查找
            for cat, name in CATEGORY_NAMES.items():
                if name == category:
                    category = cat
                    break
            else:
                return []

    return [
        factor_id
        for factor_id, meta in ALL_FACTOR_META.items()
        if meta.get("category") == category
    ]


def get_factors_by_source(source: str) -> List[str]:
    """
    按来源获取所有因子ID

    Parameters
    ----------
    source : str
        因子来源: 'worldquant', 'guotai', 'fundamental'

    Returns
    -------
    List[str]
        该来源下的所有因子ID列表
    """
    return [
        factor_id
        for factor_id, meta in ALL_FACTOR_META.items()
        if meta.get("source") == source
    ]


def search_factors_by_keyword(keyword: str) -> List[str]:
    """
    按关键词搜索因子

    Parameters
    ----------
    keyword : str
        关键词

    Returns
    -------
    List[str]
        匹配的因子ID列表
    """
    keyword = keyword.lower()
    results = []
    for factor_id, meta in ALL_FACTOR_META.items():
        # 在ID、名称、描述、关键词中搜索
        search_text = f"{factor_id} {meta.get('name', '')} {meta.get('description', '')} {meta.get('keywords', '')}".lower()
        if keyword in search_text:
            results.append(factor_id)
    return results


def get_category_factors_dict() -> Dict[FactorCategory, List[str]]:
    """
    获取所有分类及其对应的因子列表

    Returns
    -------
    Dict[FactorCategory, List[str]]
        分类到因子列表的映射
    """
    result: Dict[FactorCategory, List[str]] = {cat: [] for cat in FactorCategory}

    for factor_id, meta in ALL_FACTOR_META.items():
        category = meta.get("category")
        if category:
            result[category].append(factor_id)

    return result


def get_source_factors_dict() -> Dict[str, List[str]]:
    """
    获取所有来源及其对应的因子列表

    Returns
    -------
    Dict[str, List[str]]
        来源到因子列表的映射
    """
    result: Dict[str, List[str]] = {
        "worldquant": [],
        "guotai": [],
        "fundamental": []
    }

    for factor_id, meta in ALL_FACTOR_META.items():
        source = meta.get("source")
        if source and source in result:
            result[source].append(factor_id)

    return result


def print_factor_categories():
    """打印所有分类及其因子"""
    print("=" * 60)
    print("因子分类体系")
    print("=" * 60)

    category_factors = get_category_factors_dict()

    for category in FactorCategory:
        factors = category_factors.get(category, [])
        if factors:
            print(f"\n【{CATEGORY_NAMES[category]}】({len(factors)}个)")
            print(f"  描述: {CATEGORY_DESCRIPTIONS[category]}")
            print(f"  因子: {', '.join(factors[:10])}{'...' if len(factors) > 10 else ''}")

    print("\n" + "=" * 60)
    print(f"总计: {len(ALL_FACTOR_META)} 个因子")
    print("=" * 60)


def print_factor_list():
    """打印所有因子的详细列表"""
    print("=" * 100)
    print("系统因子列表")
    print("=" * 100)

    source_factors = get_source_factors_dict()

    for source, factors in source_factors.items():
        if not factors:
            continue

        source_name = {
            "worldquant": "WorldQuant 101 Alphas",
            "guotai": "国泰君安 Alpha191",
            "fundamental": "基本面因子"
        }.get(source, source)

        print(f"\n【{source_name}】({len(factors)}个)")
        print("-" * 100)

        for factor_id in sorted(factors):
            meta = ALL_FACTOR_META[factor_id]
            category_name = CATEGORY_NAMES.get(meta.get("category"), "未知")
            print(f"  {factor_id}: {meta['name']}")
            print(f"    分类: {category_name}")
            print(f"    描述: {meta['description'][:80]}...")
            print(f"    调用: {meta['call_method']}")
            print()

    print("=" * 100)
    print(f"总计: {len(ALL_FACTOR_META)} 个因子")
    print("=" * 100)


def print_factor_detail(factor_id: str):
    """打印单个因子的详细信息"""
    info = get_factor_full_info(factor_id)
    if not info:
        print(f"因子 {factor_id} 不存在")
        return

    print("=" * 80)
    print(f"因子详情: {factor_id}")
    print("=" * 80)
    print(f"名称: {info['name']}")
    print(f"分类: {CATEGORY_NAMES.get(info['category'], info['category'])}")
    print(f"来源: {info['source']}")
    print(f"调用方法: {info['call_method']}")
    print(f"关键词: {info['keywords']}")
    print()
    print("描述:")
    print(f"  {info['description']}")
    print()
    print("输入参数:")
    print(info['input_params'])
    print()
    print("输出参数:")
    print(info['output_params'])
    print("=" * 80)


if __name__ == "__main__":
    print_factor_categories()
