# CLAUDE.md

本文件为 Claude Code（claude.ai/code）在此仓库中工作时提供指引。

## 项目概述

A股量化分析系统 — 集因子计算、回测、风控、可视化于一体的A股量化研究平台。

## 常用命令

```bash
# 运行完整分析流程（自动数据模式：优先数据库，数据库为空时回退模拟数据）
python main.py

# CLI 子命令
python main.py config           # 配置管理
python main.py data             # 数据同步/校验/生成
python main.py factor           # 因子查询/注册表
python main.py strategy --list  # 列出所有可用策略
python main.py strategy --show <名称>  # 查看策略详情
python main.py backtest         # 执行回测
python main.py result           # 查看结果
python main.py pool             # 股票池管理

# 数据模式切换
python main.py --source test    # 测试模式（优先数据库，可回退模拟数据）
python main.py --source real    # 真实模式（仅数据库，为空则报错）
python main.py --sync           # 从QMT同步数据到本地数据库
python main.py --validate       # 校验数据库数据完整性
python main.py --generate-test-data  # 生成模拟测试数据CSV

# 运行测试
pytest tests/
python test_engine.py           # 引擎独立测试
python test_debug.py            # 调试测试脚本

# 代码检查
flake8 src/
black --check src/
```

## 数据模式系统

通过环境变量 `AQUANT_DATA_MODE` 或 `--source` 参数控制三种模式：
- **test**（默认）：优先从SQLite数据库读取，数据库为空时回退到模拟CSV数据。模拟数据绝不写入数据库；执行日志、分析结果等运行产出正常写入。
- **real**：仅从数据库读取，数据库为空则报错退出。
- **auto**：行为与test模式相同。

## 架构

```
main.py                          # CLI入口，编排分析流程
config/
  config.py                      # 数据模式、数据库配置、凭证加载
  config.json                    # 统一配置文件：数据源 + QMT/东财掘金凭证（gitignore）
src/
  data/                          # 数据层
    database.py                  # SQLite数据库管理（WAL模式）— 行情数据、执行日志、结果
    adapter.py / loader.py       # DataAdapter/DataLoader — 统一数据访问抽象
    qmt_adapter.py / qmt_connector.py  # QMT（xtquant）集成
    eastmoney_adapter.py / eastmoney_connector.py  # 东财掘金集成
    db_adapter.py / csv_adapter.py  # 数据库和CSV测试数据适配器
    test_data_generator.py       # 模拟数据生成
  engine/                        # 统一回测框架（所有策略在此运行）
    types.py                     # Order、TradeRecord、Position、DailySnapshot、BacktestResult、Context
    base_strategy.py             # BaseStrategy抽象基类（on_init → on_bar → on_stop）、StrategyRegistry策略注册表
    backtest_engine.py           # BacktestEngine — 逐日事件循环、订单执行、风控集成
    exit_checker.py              # ExitChecker — 止损/止盈/ATR动态止盈/超时平仓
  strategies/                    # 策略实现（ID目录 + 版本化文件）
    __init__.py                 # 自动发现 + 数据库注册
    3a7b2c01/                  # 小市值策略
      small_cap_v1.py          # v1 六步选股+异动止盈
      策略路径.md               # 策略说明与版本历史
    5d8e3f02/                  # 小盘股质量策略
    7f9a4b03/                  # PB+ROE月度轮动
    2c6d5e04/                  # 申万行业资金流向
    9b1f7a05/                  # 突破回调
    4e8c3d06/                  # 北向资金择时
    # 策略加载由 auto_discover() 扫描子目录，
    # 数据库 strategy_versions 表 is_active=1 的版本被加载
  factors/                       # 因子计算（WorldQuant 101、国泰君安191、基本面因子）
    factor_service.py            # FactorService — 策略级因子服务，带缓存
    factor_registry.py           # 因子注册表
    factor_provider.py           # Provider抽象层（东财 / 数据库数据源）
    multi_factor_quintile_backtest_v2.py  # 多因子分层回测引擎V2
  analysis/                      # 市场阶段识别、股票相似度分析
  risk/                          # 组合层面风控（非个股止损）
  valuation/                     # 分行业估值模型（科技、消费、金融、地产等）
  enhancement/                   # 指数增强分析（相对基准的超额表现）
  report/                        # HTML回测报告生成
  visualization/                 # Streamlit可视化仪表盘
  cli/                           # CLI子命令处理
  utils/logger.py                # 日志工具 — 控制台（带颜色）+ 按天轮转文件（保留30天）
scripts/
  import_shenwan_data.py         # 申万行业数据导入脚本
```

## 核心设计模式

### 策略开发
策略继承 `BaseStrategy` 并使用 `@register_strategy` 装饰器实现自动发现。需要实现 `on_init(context)` 进行预计算，以及 `on_bar(context)` 处理每日交易逻辑（返回 `List[Order]`）。出场逻辑使用 `ExitChecker`（止损/止盈/ATR动态止盈/超时平仓）——在策略中组合使用，引擎通过 `strategy.exit_checker()` 调用。

### 数据流
`FactorService` 是策略统一的因子获取层——支持东财API和本地数据库两种后端，带自动缓存。策略在 `on_bar` 中通过 `service.get_factor(因子名, 日期)` 获取因子值。

### 凭证管理
凭证和数据源配置存储在 `config/config.json`（已gitignore）。命令行参数 `--data-source` 可临时覆盖配置文件。凭证环境变量（`QMT_ACCOUNT`、`QMT_PASSWORD`、`EASTMONEY_TOKEN`）优先级高于配置文件。格式参考 `config/config.example.json`。

### 执行价格选择
回测引擎支持 `close`（当日收盘价）和 `next_open`（次日开盘价）两种执行方式，可避免未来函数。通过 `--rebalance-price` 或策略参数配置。

### 数据库
SQLite，启用WAL模式和 foreign keys。核心表：stock_daily、index_daily、stock_info、industry_mapping、execution_logs、best_records、index_constituent、portfolio_weights、strategy_backtests、strategy_trades、strategy_snapshots、strategy_versions（策略版本管理）。

### 策略版本管理

每个策略位于独立ID目录下：`src/strategies/<策略ID>/<策略名>_<版本>.py`

**数据库 `strategy_versions` 表**：
| 字段 | 说明 |
|------|------|
| `strategy_id` | 策略目录ID（固定，同策略的所有版本共享） |
| `strategy_name` | 策略名称 |
| `version` | 版本号 (v1/v2/...) |
| `file_path` | 策略文件相对路径 |
| `is_active` | 1=运行时加载此版本 |

**运行时加载逻辑**：`StrategyRegistry.auto_discover()` 扫描所有ID子目录，仅加载 `is_active=1` 的版本。

**创建新版本**（策略逻辑调整时）：
```python
from src.data.database import DatabaseManager
from config.config import DATABASE_CONFIG
db = DatabaseManager(DATABASE_CONFIG['path'])

# 1. 复制 & 修改策略文件
# cp small_cap_v1.py small_cap_v2.py

# 2. 注册新版本（自动激活，旧版本设为未激活）
db.create_new_strategy_version(
    'small_cap', 'v2',
    'src/strategies/3a7b2c01/small_cap_v2.py',
    '变更说明'
)

# 3. 切换版本
db.set_active_version('small_cap', 'v1')  # 回退
db.set_active_version('small_cap', 'v2')  # 启用新版本

# 4. 更新 策略路径.md 版本历史
```

**每个策略目录必须包含**：`__init__.py`、`<策略名>_<版本>.py`、`策略路径.md`

## 可视化

```bash
streamlit run src/visualization/dashboard.py
```

## 规则
1.总是使用中文回复所有问题；
2.使用plan模型生成的计划，写成MD文件存放到/docs/plans目录下；
3.每个策略都放在自己的目录下【目录名以ID形式命名】，策略命名为【文件名为策略名_版本号.py】，每个策略目录都有【策略路径.md】，当根据逻辑进行策略调整时，新建一个版本出来修改【文件名为策略名_版本号.py】，数据库中有策略表记录策略名和版本号，程序运行时根据版本号加载对应的策略；
4.修改完的内容记得更新对应的文档；