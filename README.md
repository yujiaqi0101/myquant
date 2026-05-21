# A股量化分析系统

一个专注于分析的A股量化研究平台，提供市场阶段识别、股票走势相似度分析、因子组合筛选与回测、指数增强分析等功能。支持通过国金QMT接口获取真实行情数据。

## 功能特性

### 📈 市场阶段识别
- 牛熊判断（基于多均线系统）
- 指数与个股关系分析（背离度计算）
- 板块轮动识别
- 市场情绪指标
- 龙头股识别

### 🔍 相似度分析
- DTW动态时间规整相似度
- 余弦相似度
- 特征向量相似度
- 混合相似度方法
- 历史相似时间段查找

### 📊 因子分析
- **WorldQuant 101因子**：20个短周期量价因子
- **国泰君安191因子**：23个短周期价量因子
- **基本面因子**：估值因子（PE/PB/PS/PCF）、盈利因子（ROE/ROA）、成长因子、质量因子
- **因子分类体系**：
  - 技术指标类：K线形态、成交量异常、VWAP偏离、动量类、均值回复、波动率类、相关性类
  - 基本面类：估值因子、盈利因子、成长因子、质量因子
- 因子评估（IC、IR、分层收益）
- 因子筛选与组合优化（支持按分类筛选）
- IC加权、风险平价加权
- 停牌数据过滤

### 💰 回测分析
- 因子回测框架
- 策略绩效评估
- 交易成本模拟
- **HTML报告生成**：使用 ECharts 生成交互式报告
  - 净值曲线（可缩放、悬停查看）
  - 回撤曲线
  - 绩效指标汇总表
  - 交易记录明细
  - 交易统计

### 🧪 多因子回测引擎
- **V2引擎（推荐）**：多因子分层回测
  - **扩充因子池**：8类因子（动量/均值回复/波动率/成交量/相关性/质量/趋势/形态），来自 alpha101/alpha191
  - **3种因子选择模式**：
    - `category`：每类随机选择（可指定每类因子数量）
    - `specified`：用户指定具体因子列表
    - `random`：从全部因子池中完全随机选择
  - **4种权重算法**：
    - `equal`：等权加权
    - `risk_parity`：风险平价加权
    - `ic_weighted`：IC加权（基于历史IC值）
    - `ir_weighted`：IR加权（基于历史IR值）
  - **时间段控制**：`--start-date`/`--end-date` 灵活指定回测区间
  - **调仓策略**：
    - `fixed_days`：固定持有N天后调仓
    - `calendar`：日历驱动调仓（每日/每周/每月第N个交易日）
  - **调仓价格**：`close`（收盘价）、`next_open`（次日开盘价）
  - 5组分层回测（Q1-Q5及多空组合）
  - 按需加载数据（避免内存溢出）
  - ST/新股动态过滤
  - 单调性检验（因子分层收益单调性）
  - 增强HTML报告（ECharts交互式图表）
  - 综合Summary报表（统计卡片、收益对比、热力图、单调性汇总）
- **V1引擎**：多因子分批回测
  - 20轮单因子 + 5组多因子组合分批回测
  - pyecharts生成综合HTML报告
  - 数据库日志记录

### 🛡️ 风控系统
- 行业分散度控制
- 市值暴露控制
- 过拟合检测
- 回撤监控

### 📉 指数增强分析
- **收益分析**：超额收益、累计Alpha、胜率、盈亏比
- **风险指标**：跟踪误差、信息比率、Beta、Alpha、下行Beta
- **风险调整后收益**：夏普比率、索提诺比率、卡玛比率、特雷诺比率
- **回撤与尾部风险**：最大回撤、最大相对回撤、VaR、CVaR、偏度、峰度
- **偏离分析**：行业偏离、市值偏离、个股偏离、估值偏离
- **因子暴露分析**：PE/PB因子暴露对比
- **Brinson归因**：配置效应、选择效应、交互效应分解

### 💎 估值分析
- **行业差异化估值模型**：
  - 金融行业：PB-ROE模型
  - 消费行业：PE/PEG模型
  - 周期行业：PB/EV-EBITDA模型
  - 科技行业：PEG/PS模型
  - 房地产：NAV模型
  - 公用事业：PE/DCF模型
- **合理市值区间估算**：基于历史分位数和行业比较
- **投资建议生成**：强烈超配/超配/标配/低配/强烈低配
- **估值结果持久化**：支持历史估值回溯
- **新闻情感分析接口**：预留NLP扩展接口

### 🔗 国金QMT集成
- 通过QMT接口获取股票、指数、基金、ETF真实行情数据
- 自动同步合约基本信息（名称、行业、市值、股本等）
- 板块数据和成分股自动获取
- 财务数据（资产负债表、利润表、现金流量表）同步
- 数据完整性校验与停牌数据自动补充
- 增量同步支持

### 💾 SQLite数据库支持
- 股票日频数据存储（含前收盘价、停牌标记）
- 指数日频数据存储
- 股票信息管理（含交易所、产品类型、流通股本等）
- 指数成分股数据
- QMT合约完整信息
- 板块及成分股数据
- 财务数据存储
- 组合分析结果存储
- 因子暴露数据存储
- 数据同步日志

### 📝 执行日志系统
- 自动记录每次执行的条件和结果
- 支持按因子、类型、状态筛选查询
- 自动更新最佳指标记录
- 便于快速找到历史最优参数组合

### 📋 运行日志系统
- **控制台输出**：带颜色的实时日志（INFO绿色、WARNING黄色、ERROR红色）
- **文件记录**：按天轮转，保留30天，存储在 `logs/aquant_YYYYMMDD.log`
- **日志级别**：支持 DEBUG/INFO/WARNING/ERROR 四级
- **命令行控制**：`--log-level` 设置级别，`--no-log-file` 仅控制台输出

### 🔀 测试数据与真实数据分离
- **测试数据**：存储在 `data/test_data/` 目录的CSV文件中，不写入数据库
- **真实数据**：存储在SQLite数据库中，通过QMT同步或手动导入
- **环境变量切换**：通过 `AQUANT_DATA_MODE` 环境变量选择数据源
- **清晰区分**：运行时会明确显示当前使用的数据源，避免混淆

## 项目结构

```
aquant/
├── config/                 # 配置文件
│   ├── config.py          # 主配置文件
│   └── credentials.json   # 敏感信息（账号密码等）
├── data/                   # 数据目录
│   ├── aquant.db          # SQLite数据库（存储真实数据）
│   └── test_data/         # 测试数据目录（CSV文件）
│       ├── stock_info.csv  # 股票信息
│       ├── stock_daily.csv # 股票日频数据
│       └── index_daily.csv # 指数日频数据
├── logs/                   # 日志目录
│   └── aquant_YYYYMMDD.log # 运行日志（保留30天）
├── src/                    # 源代码
│   ├── data/              # 数据模块
│   │   ├── adapter.py     # 数据适配器
│   │   ├── database.py    # 数据库管理器
│   │   ├── db_adapter.py  # 数据库适配器
│   │   ├── loader.py      # 数据加载器
│   │   ├── test_data_generator.py  # 测试数据生成器（CSV导出）
│   │   ├── qmt_connector.py  # QMT接口连接器
│   │   ├── qmt_adapter.py    # QMT数据适配器
│   │   ├── data_sync.py      # 数据同步模块
│   │   └── data_validator.py # 数据校验模块
│   ├── factors/           # 因子模块
│   │   ├── calculator.py  # 因子计算器
│   │   ├── worldquant.py  # WorldQuant因子
│   │   ├── guotai.py      # 国泰君安因子
│   │   ├── fundamental.py # 基本面因子
│   │   ├── categories.py  # 因子分类系统
│   │   ├── selector.py    # 因子筛选器
│   │   ├── backtest.py    # 回测器
│   │   ├── report_generator.py  # HTML报告生成器
│   │   ├── execution_logger.py  # 执行日志记录器
│   │   ├── multi_factor_backtest.py  # 多因子分批回测引擎V1
│   │   ├── multi_factor_quintile_backtest.py  # 多因子分层回测V1
│   │   ├── multi_factor_quintile_backtest_v2.py  # 多因子分层回测引擎V2（推荐）
│   │   └── simple_quintile_backtest.py  # 简单分层回测(已废弃)
│   ├── analysis/          # 分析模块
│   │   ├── market_stage.py # 市场阶段识别
│   │   └── similarity.py  # 相似度分析
│   ├── enhancement/       # 指数增强模块
│   │   ├── analyzer.py    # 核心分析器
│   │   ├── metrics.py     # 指标计算器
│   │   ├── attribution.py # 收益归因分析
│   │   └── data_generator.py  # 成分股数据生成器
│   ├── risk/              # 风控模块
│   │   └── risk_manager.py
│   ├── valuation/         # 估值分析模块
│   │   ├── analyzer.py    # 估值分析主入口
│   │   ├── calculator/    # 估值计算器
│   │   │   ├── valuation_calculator.py
│   │   │   └── metrics.py
│   │   ├── models/        # 估值模型
│   │   │   ├── base.py
│   │   │   ├── financial.py
│   │   │   ├── consumer.py
│   │   │   ├── cyclical.py
│   │   │   ├── technology.py
│   │   │   ├── real_estate.py
│   │   │   └── utility.py
│   │   ├── estimator/     # 合理价值估算
│   │   │   └── fair_value_estimator.py
│   │   └── sentiment/     # 情感分析接口
│   │       └── news_sentiment.py
│   ├── utils/             # 工具模块
│   │   └── logger.py      # 日志工具
│   └── visualization/     # 可视化模块
│       └── dashboard.py   # Streamlit仪表盘
├── tests/                  # 测试文件
│   ├── test_all.py
│   └── test_database.py
├── main.py                 # 主入口
└── requirements.txt        # 依赖文件
```

## 数据库表结构

| 表名 | 说明 |
|------|------|
| stock_daily | 股票日频数据（开高低收、成交量、前收盘价、停牌标记等） |
| index_daily | 指数日频数据（开高低收、成交量、前收盘价、成交额） |
| stock_info | 股票基本信息（代码、名称、行业、市值、交易所、产品类型等） |
| index_constituent | 指数成分股数据（权重、市值、PE、PB等） |
| qmt_instrument | QMT合约完整信息（名称、交易所、股本、涨跌停价等） |
| data_sync_log | 数据同步日志 |
| execution_log | 执行日志（执行条件、参数、绩效指标） |
| best_records | 最佳指标记录 |
| portfolio_analysis | 组合分析结果 |
| factor_exposure | 因子暴露数据 |
| valuation_result | 估值结果（各估值方法） |
| valuation_summary | 估值综合结果 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

> **注意**：`xtquant` 需要安装国金QMT交易端后才能使用。如果不需要QMT数据源，可以跳过xtquant安装。

### 2. 环境变量配置

系统通过 `AQUANT_DATA_MODE` 环境变量控制运行时数据行为：

```bash
# Linux/Mac
export AQUANT_DATA_MODE=test   # 测试模式：优先数据库，为空则回退模拟数据
export AQUANT_DATA_MODE=real   # 真实模式：仅数据库，为空则报错
export AQUANT_DATA_MODE=auto   # 自动检测（默认，行为同test）

# Windows
set AQUANT_DATA_MODE=test
```

### 3. 生成测试数据

```bash
cd aquant
python main.py --generate-test-data
```

测试数据会生成到 `data/test_data/` 目录：
- `stock_info.csv` - 股票信息（100只股票）
- `stock_daily.csv` - 股票日频数据（100只 × 250个交易日）
- `index_daily.csv` - 指数日频数据（5个主要指数 × 250个交易日）

### 4. 使用测试数据运行

```bash
# 方式1：设置环境变量
export AQUANT_DATA_MODE=test
python main.py

# 方式2：使用命令行参数
python main.py --source test
```

### 5. 使用真实数据运行

```bash
# 方式1：设置环境变量
export AQUANT_DATA_MODE=real
python main.py

# 方式2：使用命令行参数
python main.py --source real

# 方式3：使用QMT同步数据（账号密码从config/credentials.json读取）
python main.py --sync --start-date 20230101
# 或通过命令行指定账号密码
# python main.py --sync --account 你的账号 --password 你的密码 --start-date 20230101
```

### 6. 仅同步数据

```bash
python main.py --sync --start-date 20230101
```

### 7. 仅校验数据完整性

```bash
python main.py --validate --start-date 20230101
```

### 8. 启动可视化界面

```bash
cd aquant
streamlit run src/visualization/dashboard.py
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--source` | 数据模式：test=测试模式(优先数据库,可回退模拟) / real=真实模式(仅数据库) | 根据环境变量AQUANT_DATA_MODE |
| `--sync` | 仅同步数据 | False |
| `--validate` | 仅校验数据完整性 | False |
| `--generate-test-data` | 仅生成测试数据CSV | False |
| `--start-date` | 数据起始日期 (YYYYMMDD) | 20230101 |
| `--end-date` | 数据结束日期 (YYYYMMDD) | 最新 |
| `--account` | QMT交易账号 | - |
| `--password` | QMT交易密码 | - |
| `--n-stocks` | 测试数据股票数量 | 100 |
| `--n-days` | 测试数据天数 | 250 |
| `--log-level` | 日志级别 (DEBUG/INFO/WARNING/ERROR) | INFO |
| `--no-log-file` | 禁用日志文件输出（仅控制台） | False |
| `--quintile-backtest` | 运行多因子分层回测V2（推荐） | False |
| `--multi-factor-backtest` | 运行多因子分批回测V1 | False |
| `--n-rounds` | 回测轮数 | 20 |
| `--bt-n-stocks` | 回测分组股票数 | 50 |
| `--seed` | 随机种子 | None |
| `--output-dir` | 报告输出目录 | reports/backtest/quintile |
| `--max-stocks` | V1回测股票池上限 | 500 |
| `--factor-mode` | 因子选择模式：`category`/`specified`/`random` | category |
| `--factors-per-category` | 每类因子数量（category模式） | 2 |
| `--factors` | 指定因子列表，逗号分隔（specified模式） | - |
| `--n-factors` | 随机因子数量（random模式） | 8 |
| `--weight-method` | 权重算法：`equal`/`risk_parity`/`ic_weighted`/`ir_weighted` | equal |
| `--rebalance-mode` | 调仓模式：`fixed_days`/`calendar` | fixed_days |
| `--rebalance-price` | 调仓价格：`close`/`next_open` | close |
| `--hold-days` | 固定持有天数（fixed_days模式） | 5 |
| `--calendar-freq` | 日历频率：`daily`/`weekly`/`monthly`（calendar模式） | monthly |
| `--calendar-n` | 日历第N个交易日（calendar模式） | 1 |

## 数据模式说明

### 核心原则

**数据库中的市场数据（标的、K线等）必须是干净的、可信任的，模拟数据绝不写入数据库。**

### 测试模式 (test / auto)

- **数据读取**：优先从数据库读取市场数据，数据库为空时回退到模拟数据（CSV文件）
- **数据写入**：模拟数据（测试标的、K线等）**绝不写入数据库**
- **运行结果**：执行日志、分析结果等运行产出**正常写入数据库**（这些不是测试数据）
- **适用场景**：
  - 开发调试
  - 功能演示
  - 数据库为空时的快速体验

### 真实模式 (real)

- **数据读取**：所有市场数据只从数据库读取
- **数据写入**：执行日志、分析结果正常写入数据库
- **数据库为空时**：报错退出，提示用户同步数据或切换模式
- **适用场景**：
  - 正式分析
  - 投资决策
  - 历史研究

### 模拟数据

- **位置**：`data/test_data/` 目录下的CSV文件
- **内容**：程序生成的模拟股票信息、K线数据、指数数据
- **特点**：数据固定可复现，仅用于测试，不写入数据库

## QMT数据源配置

### 前置条件
1. 安装国金QMT交易端模拟软件
2. 以**极简模式**（独立交易模式）登录QMT
3. 安装xtquant库：`pip install xtquant`

### 配置说明

在 `config/credentials.json` 中配置QMT账号、密码和路径：

```json
{
    "qmt": {
        "account": "your_account",
        "password": "your_password",
        "path": "E:\\国金QMT交易端模拟\\userdata_mini"
    }
}
```

或通过环境变量配置：

```bash
# Linux/Mac
export QMT_ACCOUNT=your_account
export QMT_PASSWORD=your_password
export QMT_PATH="E:\\国金QMT交易端模拟\\userdata_mini"

# Windows
set QMT_ACCOUNT=your_account
set QMT_PASSWORD=your_password
set QMT_PATH=E:\国金QMT交易端模拟\userdata_mini
```

### 数据同步流程

系统会按以下顺序同步数据：
1. 获取全部股票/指数/ETF/基金列表
2. 同步合约基本信息（名称、行业、股本等）
3. 下载并同步日K线行情数据
4. 同步板块数据和成分股
5. 同步财务数据（资产负债表、利润表、现金流量表）

### 数据校验

系统提供数据完整性校验功能：
- 检查交易日历连续性
- 识别停牌股票和缺失数据
- 停牌数据自动补充（用前收盘价填充OHLC，成交量为0）

## 使用示例

### 通过环境变量选择数据源

```python
import os
os.environ['AQUANT_DATA_MODE'] = 'test'  # 或 'real'

from src.data import DataLoader

# 自动根据环境变量选择数据源
loader = DataLoader.create()
```

### 明确使用测试数据

```python
from src.data import DataLoader

loader = DataLoader.from_test_data()
print(loader.get_stock_list())
```

### 明确使用真实数据

```python
from src.data import DataLoader

loader = DataLoader.from_database('data/aquant.db')
print(loader.get_stock_list())
```

### 从QMT加载数据

```python
from src.data import DataLoader

loader = DataLoader.from_qmt(
    db_path='data/aquant.db',
    account='your_account',
    password='your_password',
    start_date='20230101'
)
```

### 数据同步

```python
from src.data.qmt_connector import QMTConnector
from src.data.data_sync import DataSynchronizer
from src.data.database import DatabaseManager

db = DatabaseManager('data/aquant.db')
connector = QMTConnector(account='your_account', password='your_password')
connector.connect()

synchronizer = DataSynchronizer(connector, db)
result = synchronizer.sync_all(start_date='20230101', end_date='')

print(result)
```

### 数据校验

```python
from src.data.data_validator import DataValidator
from src.data.database import DatabaseManager

db = DatabaseManager('data/aquant.db')
validator = DataValidator(db)

# 生成校验报告
report = validator.validate_and_report('20230101', '20231231')
print(report)

# 检查停牌股票
suspended = validator.find_suspended_stocks('20230101', '20231231')

# 检查数据完整性
integrity = validator.check_data_integrity('20230101', '20231231')
```

### 生成测试数据

```python
from src.data.test_data_generator import TestDataGenerator

generator = TestDataGenerator()
data = generator.generate_all_test_data(n_stocks=100, n_days=250)
print(data['stock_info'].head())
```

### 因子计算（含停牌过滤）

```python
from src.factors import FactorCalculator, WorldQuantFactors

calculator = FactorCalculator(loader)
calculator.load_data()

# 计算因子
wq = WorldQuantFactors(calculator)
factors = wq.calculate_all()

# 过滤停牌数据
close = calculator.close()
close_filtered = calculator.filter_suspended(close)
```

### 估值分析

```python
from src.valuation import ValuationAnalyzer
from src.data.database import DatabaseManager

db = DatabaseManager('data/aquant.db')
analyzer = ValuationAnalyzer(db)

# 单股票估值分析
result = analyzer.analyze('000001.SZ')
print(f"合理价值: {result['fair_value']['weighted']:.2f}")
print(f"投资建议: {result['fair_value']['recommendation']}")

# 保存估值结果
analyzer.save_results('000001.SZ', result)

# 筛选低估股票（上涨空间>20%）
stock_list = ['000001.SZ', '000002.SZ', '600000.SH']
undervalued = analyzer.screen_undervalued(stock_list, upside_threshold=0.20)
print(undervalued)

# 生成估值报告
report = analyzer.get_valuation_report('000001.SZ', result)
print(report)
```

### 因子分类与筛选

```python
from src.factors import FactorSelector, FactorCategory, print_factor_categories

# 查看所有因子分类
print_factor_categories()

# 创建筛选器并添加因子
selector = FactorSelector()
selector.add_factors(all_factors)

# 按分类获取因子
vwap_factors = selector.get_factors_by_category(FactorCategory.VWAP_DEVIATION)
print(f"VWAP偏离类因子: {vwap_factors}")

# 从指定分类中筛选最佳因子
best_momentum = selector.select_by_category(
    FactorCategory.MOMENTUM, 
    method='ic', 
    top_k=3
)
print(f"最佳动量因子: {best_momentum}")

# 获取分类统计
stats = selector.get_category_statistics()
print(stats[['category', 'factor_count', 'avg_ic', 'avg_ir']])
```

### 基本面因子计算

```python
from src.factors import FactorCalculator, FundamentalFactors

calculator = FactorCalculator(loader)
calculator.load_data()

# 计算基本面因子
fund = FundamentalFactors(calculator)
factors = fund.calculate_all()

# 仅计算估值因子
valuation_factors = fund.calculate_valuation_factors()

# 仅计算盈利因子
profit_factors = fund.calculate_profitability_factors()
```

### 多因子分层回测V2（推荐）

```bash
# 类别随机模式，每类2个因子，风险平价加权
python main.py --quintile-backtest --factor-mode category --factors-per-category 2 --weight-method risk_parity

# 指定因子模式
python main.py --quintile-backtest --factor-mode specified --factors WQ_001,GTJ_030

# 日历调仓，每月第1个交易日，次日开盘价调仓
python main.py --quintile-backtest --rebalance-mode calendar --calendar-freq monthly --calendar-n 1 --rebalance-price next_open

# 完整示例：指定时间区间、类别模式、IC加权、固定5天调仓
python main.py --quintile-backtest \
    --start-date 20220101 \
    --end-date 20241231 \
    --factor-mode category \
    --factors-per-category 3 \
    --weight-method ic_weighted \
    --rebalance-mode fixed_days \
    --hold-days 5 \
    --rebalance-price close \
    --n-rounds 10 \
    --output-dir reports/my_backtest
```

### 回测HTML报告生成

```python
from src.factors import Backtester

# 运行回测
backtester = Backtester(initial_capital=1000000)
backtester.load_data(price_data)
result = backtester.run_backtest(factor, n_stocks=20, rebalance_freq=5)

# 生成HTML报告
report_path = backtester.generate_report(
    output_path="reports/my_strategy.html",
    title="我的策略回测报告"
)
print(f"报告已生成: {report_path}")

# 或使用快捷函数
from src.factors import generate_backtest_report

report_path = generate_backtest_report(
    backtest_result=result,
    output_path="reports/report.html",
    title="回测分析报告"
)
```

## 待办事项

| ID | 功能 | 类别 | 优先级 | 状态 |
|----|------|------|--------|------|
| DATA-001 | 分钟级行情数据支持 | 数据层 | 中 | 待开发 |
| DATA-002 | 基本面数据接入 | 数据层 | 中 | 已完成(QMT) |
| DATA-003 | 宏观数据接入 | 数据层 | 低 | 待开发 |
| DATA-004 | 获取指数/ETF真实持仓数据 | 数据层 | 高 | 已完成(QMT) |
| DATA-005 | 股票历史数据校验与停牌补充 | 数据层 | 高 | 已完成 |
| DATA-006 | 测试数据与真实数据分离 | 数据层 | 高 | 已完成 |
| TRADE-001 | 实盘交易接口对接 | 实盘对接 | 低 | 待开发 |
| FEAT-001 | 深度学习相似度 | 功能增强 | 中 | 待开发 |
| FEAT-002 | 遗传编程挖因子 | 功能增强 | 中 | 待开发 |
| FEAT-003 | 估值分析模块 | 功能增强 | 高 | 已完成 |
| FEAT-004 | 因子分类体系 | 功能增强 | 高 | 已完成 |
| FEAT-005 | 基本面因子 | 功能增强 | 高 | 已完成 |
| FEAT-006 | 回测HTML报告 | 功能增强 | 中 | 已完成 |

## 技术栈

- **数据处理**: Pandas, NumPy, SciPy
- **数据库**: SQLite (WAL模式)
- **数据源**: 国金QMT (xtquant)
- **机器学习**: scikit-learn, LightGBM
- **可视化**: Streamlit, Plotly, ECharts (pyecharts)
- **因子计算**: 自研算法

## 版本历史

- **v0.6.0** (2025): 多因子回测引擎V2重构
  - 扩充因子池：8类因子（动量/均值回复/波动率/成交量/相关性/质量/趋势/形态），来自 alpha101/alpha191
  - 3种因子选择模式：`category`（每类随机）、`specified`（用户指定）、`random`（全随机）
  - 4种权重算法：`equal`（等权）、`risk_parity`（风险平价）、`ic_weighted`（IC加权）、`ir_weighted`（IR加权）
  - 时间段控制：`--start-date`/`--end-date` 替代原Batch机制，灵活指定回测区间
  - 调仓策略：`fixed_days`（固定持有N天）、`calendar`（日历驱动：每日/每周/每月第N个交易日）
  - 调仓价格：`close`（收盘价）、`next_open`（次日开盘价）
  - CLI参数重构：删除 `--batch-start`、`--batch-end`、`--rebalance-freq`，新增因子/权重/调仓相关参数

- **v0.5.0** (2025): 多因子回测引擎与CLI增强
  - 多因子分层回测V2引擎：风险平价加权、5组分层、7批次滚动回测
  - 多因子分批回测V1引擎：20轮单因子+5组多因子组合
  - CLI回测入口：`--quintile-backtest`、`--multi-factor-backtest`
  - 增强Summary报表：统计卡片、ECharts图表、单调性检验、最佳/最差轮次高亮
  - 因子分类体系：13个分类（技术指标类9个 + 基本面类4个）
  - 基本面因子：估值因子（8个）、盈利因子（5个）、成长因子（5个）、质量因子（4个）
  - 回测HTML报告：使用 ECharts 生成交互式报告

- **v0.4.1** (2025): 测试数据与真实数据分离
  - 测试数据不再写入数据库，改为CSV文件存储
  - 新增 `AQUANT_DATA_MODE` 环境变量配置
  - 支持运行时切换测试/真实数据源
  - 清晰的模式指示和警告提示
  - 新增 `--generate-test-data` 命令行参数
  - 文档更新：数据管理规范说明

- **v0.4.0** (2024): 估值分析模块
  - 6大行业差异化估值模型（金融PB-ROE、消费PE/PEG、周期PB、科技PEG/PS、房地产NAV、公用事业DCF）
  - 合理市值区间估算（基于历史分位数和行业比较）
  - 投资建议生成（强烈超配/超配/标配/低配/强烈低配）
  - 估值结果持久化（valuation_result、valuation_summary表）
  - 新闻情感分析接口（预留NLP扩展）

- **v0.3.0** (2024): 国金QMT集成
  - QMT接口连接器（支持股票、指数、基金、ETF）
  - 数据同步模块（全量/增量同步）
  - 数据校验模块（完整性检查、停牌补充）
  - 数据库表结构扩展（前收盘价、停牌标记、合约信息等）
  - 因子计算停牌过滤
  - VWAP精确计算（amount/volume）
  - 命令行参数支持（--source, --sync, --validate）

- **v0.2.0** (2024): 数据库集成与指数增强
  - SQLite数据库支持
  - 执行日志系统
  - 最佳记录自动更新
  - 指数增强分析模块（10个分析维度，30+指标）
  - Brinson归因分析
  - 因子暴露分析

- **v0.1.0** (2024): 初始版本
  - 市场阶段识别
  - 相似度分析
  - 因子计算与筛选
  - 回测框架
  - 风控模块
  - 可视化界面

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！
