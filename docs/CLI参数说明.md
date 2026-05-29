# 回测框架 CLI 完整参数说明

## 命令格式

```bash
python main.py <子命令> [参数...]
```

## 子命令总览

| 子命令 | 说明 |
|--------|------|
| `strategy` | 策略管理（列出、查看策略） |
| `backtest` | 运行回测 |
| `result` | 回测结果管理（查看、导出、删除） |
| `pool` | 股票池管理（创建、添加、删除） |

---

## 1. `strategy` - 策略管理

```bash
python main.py strategy [选项]
```

| 参数 | 缩写 | 说明 | 示例 |
|------|------|------|------|
| `--list` | `-l` | 列出所有可用策略 | `--list` |
| `--show <名称>` | `-s` | 查看策略详情（类注释+参数） | `--show breakout_pullback` |
| `--params` | | 显示策略参数详细说明（配合 `--show`） | `--show breakout_pullback --params` |

**示例：**

```bash
python main.py strategy --list
python main.py strategy --show breakout_pullback
python main.py strategy --show breakout_pullback --params
```

---

## 2. `backtest` - 运行回测

```bash
python main.py backtest --strategy <策略名> [选项...]
```

### 2.1 必选参数

| 参数 | 缩写 | 说明 | 示例 |
|------|------|------|------|
| `--strategy <名称>` | `-s` | 策略名称（必需） | `--strategy breakout_pullback` |

### 2.2 股票范围（二选一，也可都不选表示全市场）

| 参数 | 说明 | 示例 |
|------|------|------|
| `--pool <池名>` | 使用股票池 | `--pool test` |
| `--stocks <代码>` | 直接指定股票列表（逗号分隔） | `--stocks 000001.SZ,600000.SH` |

> `--pool` 和 `--stocks` 互斥，不能同时使用。

### 2.3 时间范围

| 参数 | 默认值 | 说明 | 示例 |
|------|--------|------|------|
| `--start-date` | `2024-01-01` | 回测开始日期 | `--start-date 2025-01-01` |
| `--end-date` | `2024-12-31` | 回测结束日期 | `--end-date 2025-07-14` |

### 2.4 交易参数

| 参数 | 类型 | 默认值 | 说明 | 示例 |
|------|------|--------|------|------|
| `--initial-capital` | float | `1000000` | 初始资金 | `--initial-capital 500000` |
| `--position-size` | float | `0.10` | 单次开仓资金比例 | `--position-size 0.20` |
| `--commission-rate` | float | `0.0003` | 佣金费率 | `--commission-rate 0.0001` |
| `--slippage` | float | `0.0001` | 滑点比例 | `--slippage 0.001` |
| `--execution-price` | enum | `close` | 订单执行价格：`close`=收盘价，`next_open`=次日开盘价 | `--execution-price next_open` |

### 2.5 出场规则

| 参数 | 类型 | 默认值 | 说明 | 示例 |
|------|------|--------|------|------|
| `--stop-loss` | float | `0.07` | 止损比例（0.07 = 7%） | `--stop-loss 0.05` |
| `--take-profit` | float | `0.20` | 止盈比例（0.20 = 20%） | `--take-profit 0.30` |
| `--trailing-stop` | int | `3` | 动态止盈均线窗口（跌破N日均线止盈，0=禁用） | `--trailing-stop 5` |
| `--max-holding-days` | int | `0` | 最大持仓天数（0=禁用超时平仓） | `--max-holding-days 30` |

### 2.6 风控参数

| 参数 | 类型 | 默认值 | 说明 | 示例 |
|------|------|--------|------|------|
| `--enable-risk-control` | flag | 关闭 | 启用组合级风控 | `--enable-risk-control` |
| `--portfolio-stop` | float | `0.10` | 组合止损比例（需先启用风控） | `--portfolio-stop 0.15` |

### 2.7 市场过滤（默认全部关闭）

| 参数 | 类型 | 默认值 | 说明 | 示例 |
|------|------|--------|------|------|
| `--exclude-st` | flag | 关闭 | 排除ST股 | `--exclude-st` |
| `--exclude-new-stock <N>` | int | `0` | 排除上市不满N个交易日的股票 | `--exclude-new-stock 60` |
| `--exclude-limit` | flag | 关闭 | 排除涨跌停股 | `--exclude-limit` |
| `--exclude-suspend` | flag | 关闭 | 排除停牌股 | `--exclude-suspend` |
| `--exclude-zero-vol` | flag | 关闭 | 排除零成交量股 | `--exclude-zero-vol` |

### 2.8 输出参数

| 参数 | 默认值 | 说明 | 示例 |
|------|--------|------|------|
| `--output-dir` | `reports` | 报告输出目录 | `--output-dir my_reports` |
| `--name` | 自动生成 | 自定义报告名称 | `--name my_test` |

> 报告目录默认命名格式：`backtest_{日志ID}_{开始日期}_{结束日期}`，每次回测不会覆盖。

**完整示例：**

```bash
# 基本回测
python main.py backtest --strategy breakout_pullback --pool test \
  --start-date 2025-01-01 --end-date 2025-07-14

# 全参数回测
python main.py backtest --strategy breakout_pullback --pool test \
  --start-date 2025-01-01 --end-date 2025-07-14 \
  --initial-capital 500000 --stop-loss 0.05 --take-profit 0.30 \
  --execution-price next_open \
  --exclude-st --exclude-new-stock 60 --exclude-limit \
  --exclude-suspend --exclude-zero-vol

# 使用股票列表回测
python main.py backtest --strategy breakout_pullback \
  --stocks 000001.SZ,600000.SH,000002.SZ \
  --start-date 2025-01-01 --end-date 2025-07-14
```

---

## 3. `result` - 回测结果管理

```bash
python main.py result [选项]
```

| 参数 | 缩写 | 说明 | 示例 |
|------|------|------|------|
| `--list` | `-l` | 列出所有回测结果 | `--list` |
| `--show <路径>` | | 查看回测结果摘要 | `--show reports/backtest_0071_2025-01-01_2025-07-14` |
| `--date <日期>` | | 查看指定日期详情（配合 `--show`） | `--date 2025-06-01` |
| `--detail <类型>` | | 详情类型：`cashflow`/`positions`/`trades`/`all`（配合 `--date`） | `--detail trades` |
| `--export <路径>` | | 导出交易记录为CSV | `--export reports/backtest_0071_...` |
| `--output` | `-o` | 导出文件路径（配合 `--export`） | `--output trades.csv` |
| `--html <路径>` | | 为已有结果生成HTML报告 | `--html reports/backtest_0071_...` |
| `--delete <路径>` | | 删除回测结果 | `--delete reports/backtest_0071_...` |

**示例：**

```bash
python main.py result --list
python main.py result --show reports/backtest_0071_2025-01-01_2025-07-14
python main.py result --show reports/backtest_0071_... --date 2025-06-01 --detail trades
python main.py result --html reports/backtest_0071_...
python main.py result --export reports/backtest_0071_... --output trades.csv
python main.py result --delete reports/backtest_0071_...
```

---

## 4. `pool` - 股票池管理

```bash
python main.py pool [选项]
```

| 参数 | 说明 | 示例 |
|------|------|------|
| `--list` | 列出所有股票池 | `--list` |
| `--create <名称>` | 创建股票池 | `--create tech_pool` |
| `--code <代码>` | 股票池代码（配合 `--create`） | `--code CSI300` |
| `--desc <描述>` | 股票池描述（配合 `--create`） | `--desc "科技股精选"` |
| `--show <名称>` | 查看股票池详情和成员列表 | `--show tech_pool` |
| `--delete <名称>` | 删除股票池 | `--delete tech_pool` |
| `--add <名称>` | 向股票池添加股票（配合 `--stocks` 或 `--import-csv`） | `--add tech_pool --stocks 000001.SZ,600000.SH` |
| `--remove <名称>` | 从股票池移除股票（配合 `--stocks`） | `--remove tech_pool --stocks 000001.SZ` |
| `--stocks <代码>` | 股票代码列表，逗号分隔 | `--stocks 000001.SZ,600000.SH` |
| `--import-csv <路径>` | 从CSV文件导入（配合 `--add`） | `--import-csv stocks.csv` |
| `--import-index <指数代码>` | 从指数成分股创建（配合 `--create`） | `--import-index 000300.SH` |

**示例：**

```bash
# 创建股票池
python main.py pool --create tech_pool --desc "科技股精选"
python main.py pool --create CSI300 --import-index 000300.SH

# 管理成员
python main.py pool --add tech_pool --stocks 000001.SZ,600000.SH
python main.py pool --add tech_pool --import-csv stocks.csv
python main.py pool --remove tech_pool --stocks 000001.SZ

# 查看/删除
python main.py pool --list
python main.py pool --show tech_pool
python main.py pool --delete tech_pool
```
