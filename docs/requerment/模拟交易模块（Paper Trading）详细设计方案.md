# 模拟交易模块（Paper Trading）详细设计方案

# 

本项目旨在开发一个模拟交易（Paper Trading）模块，用于在真实/模拟每日行情下，运行已注册的量化策略，记录账户、持仓、订单、成交记录与每日净值，供后续分析和可视化。

---

## 1\. 业务目标与需求分析

\- **\*\*多策略独立运行\*\***：支持多个注册活跃（\`is\_active=1\`）的策略版本独立拥有一个虚拟交易账户。

\- **\*\*每日定时任务驱动\*\***：在每日收盘后（如 15:30 以后），同步当日行情数据后一键运行，模拟策略在今日（或次日开盘）的交易决策。

\- **\*\*规则契合真实场景\*\***：

- 考虑交易成本：佣金（如万三，最低5元）、印花税（卖出千一或最新规定）、滑点等。

- 资金约束：买入时检查可用资金并进行冻结，不支持透支。

- 交易限制：支持过滤 ST 股票、新股（上市未满 N 天），支持基于当日涨跌停限制（如涨停无法买入，跌停无法卖出）。

\- **\*\*详尽的数据记录\*\***：每日生成账户快照，从而能够绘制与回测格式完全一致的净值曲线（NAV）。

\- **\*\*与回测系统共用接口\*\***：复用策略基类 \`BaseStrategy\` 的接口（\`on\_init\`, \`on\_bar\`, \`exit\_checker\`），开发好的策略无需修改任何代码即可直接接入模拟交易。

---

## 2\. 系统架构设计

模拟交易模块与现有系统的关系图如下：

```Plain Text
graph TD
    qmt[QMT/东财数据源] -->|每日同步| DB[(SQLite 数据库)]
    active_str[活跃策略加载] -->|策略初始化| pt_orch[模拟交易编排器]
    DB -->|获取今日K线/历史数据| pt_orch
    pt_orch -->|调用 exit_checker / on_bar| pt_eng[模拟交易引擎]
    pt_eng -->|模拟撮合成交| pt_eng
    pt_eng -->|更新账户/持仓/成交| DB
    streamlit_dashboard[Streamlit 仪表盘] -->|读取模拟数据| DB
```

模拟交易核心包结构（建议新建 `src/paper_trading/` 目录）：

```Plain Text
src/paper_trading/
  ├── __init__.py
  ├── engine.py          # PaperTradingEngine: 负责账户、持仓、订单的计算与模拟撮合
  ├── orchestrator.py    # PaperTradingOrchestrator: 负责编排流程（数据加载、执行策略、事务更新）
  └── config.py          # 模拟交易通用参数（如初始资金、费用率默认值等）
```

---

## 3\. 数据库表结构设计

在 SQLite 数据库中新增 5 张表，专门用于存储模拟交易的历史与状态：

### 3\.1 模拟账户表 \(`paper_accounts`\)

记录各策略账户的资金状态。

```SQL
CREATE TABLE IF NOT EXISTS paper_accounts (
    strategy_id VARCHAR(32) PRIMARY KEY,     -- 策略ID
    strategy_name VARCHAR(100) NOT NULL,     -- 策略名称
    version VARCHAR(20) NOT NULL,            -- 策略版本号
    initial_capital DOUBLE NOT NULL,         -- 初始资金
    cash DOUBLE NOT NULL,                    -- 可用资金
    frozen_cash DOUBLE NOT NULL DEFAULT 0.0, -- 冻结资金 (买单待执行)
    total_value DOUBLE NOT NULL,             -- 总资产 (可用资金 + 冻结资金 + 持仓市值)
    peak_value DOUBLE NOT NULL,              -- 资产最高值 (用于计算回撤)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3\.2 模拟持仓表 \(`paper_positions`\)

记录当前各策略的个股持仓。

```SQL
CREATE TABLE IF NOT EXISTS paper_positions (
    strategy_id VARCHAR(32) NOT NULL,
    stock_code VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,          -- direction: 'long' / 'short'
    quantity INTEGER NOT NULL,               -- 持仓股数
    entry_price DOUBLE NOT NULL,             -- 开仓均价
    entry_date TEXT NOT NULL,                -- 建仓日期 (YYYY-MM-DD)
    current_price DOUBLE NOT NULL,           -- 最新收盘价
    value DOUBLE NOT NULL,                   -- 当前市值
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (strategy_id, stock_code)
);
```

### 3\.3 模拟订单表 \(`paper_orders`\)

记录策略每日生成的买卖申请订单。

```SQL
CREATE TABLE IF NOT EXISTS paper_orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id VARCHAR(32) NOT NULL,
    stock_code VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,          -- direction: 'long' / 'short'
    quantity INTEGER NOT NULL,               -- 申请股数
    price_type VARCHAR(20) NOT NULL,         -- 'close' / 'next_open' 等
    reason TEXT,                             -- 触发原因 (如: 止损/异动止盈/因子选股)
    status VARCHAR(20) NOT NULL,             -- 'pending' / 'filled' / 'rejected'
    created_date TEXT NOT NULL,              -- 订单创建交易日 (YYYY-MM-DD)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_paper_orders_strategy ON paper_orders(strategy_id);
```

### 3\.4 模拟成交记录表 \(`paper_trades`\)

记录已经模拟成交的流水。

```SQL
CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    strategy_id VARCHAR(32) NOT NULL,
    stock_code VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    price DOUBLE NOT NULL,
    amount DOUBLE NOT NULL,                  -- 成交金额
    commission DOUBLE NOT NULL,              -- 手续费
    slippage DOUBLE NOT NULL,                -- 滑点成本
    trade_date TEXT NOT NULL,                -- 成交交易日 (YYYY-MM-DD)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_strategy ON paper_trades(strategy_id);
```

### 3\.5 模拟净值快照表 \(`paper_snapshots`\)

记录每日收盘后结算的账户净值，用于绘制收益率曲线。

```SQL
CREATE TABLE IF NOT EXISTS paper_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id VARCHAR(32) NOT NULL,
    trade_date TEXT NOT NULL,                -- 交易日 (YYYY-MM-DD)
    cash DOUBLE NOT NULL,
    position_value DOUBLE NOT NULL,          -- 持仓市值
    total_value DOUBLE NOT NULL,             -- 总资产
    daily_return DOUBLE NOT NULL,            -- 日收益率
    max_drawdown DOUBLE NOT NULL,            -- 当前累计最大回撤
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(strategy_id, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_paper_snapshots_strategy ON paper_snapshots(strategy_id);
```

---

## 4\. 模拟交易执行编排器设计

每日模拟交易的计算流包含以下步骤：

```Plain Text
[步骤1: 启动与初始化]
   └── 加载所有活跃策略配置
   └── 初始化数据库中缺失的 paper_accounts
[步骤2: 今日行情数据获取]
   └── 检查数据库是否有今日收盘数据 (stock_daily)
   └── 若为空则尝试同步今日最新数据
[步骤3: 次日开盘 pending 订单的撮合]
   └── 若存在昨日生成的 'next_open' 订单，使用今日 open 价格进行模拟成交
   └── 更新可用资金、扣除持仓
[步骤4: 策略出场检查 (Exit Check)]
   └── 循环当前持仓，使用今日 close 价格调用 strategy.exit_checker
   └── 若触发出场，根据 'close' 或 'next_open' 模式生成出场订单
   └── 'close' 订单当日收盘价直接成交；'next_open' 订单存入 pending
[步骤5: 策略入场计算 (on_bar)]
   └── 构造当前交易日的 Context (持仓、资金、行情缓冲区等)
   └── 调用 strategy.on_bar(context) 生成目标订单
   └── 过滤停牌/涨跌停/ST股，并检查资金是否足够：
       - 'close' 买单：当日收盘成交，扣减 cash，生成持仓
       - 'next_open' 买单：计算所需资金，将 cash 转移到 frozen_cash，存入 pending
[步骤6: 收盘结算并记录快照]
   └── 重新计算各账户的总市值 (cash + frozen_cash + 实时持仓市值)
   └── 更新 paper_accounts 表数据
   └── 向 paper_snapshots 插入今日净值记录
```

---

## 5\. 核心代码模块设计

### 5\.1 `PaperTradingEngine`

用于实现模拟账户逻辑的引擎，主要函数：

- `load_account(strategy_id)`: 从数据库读取当前账户与持仓。

- `execute_order(order, price, date)`:

    - 撮合个股成交。

    - 处理费用扣除（印花税和佣金）。

    - 更新持仓数量和开仓均价。

    - 写入 `paper_trades` 和 `paper_positions` 表。

- `freeze_capital(strategy_id, amount)`: 冻结买单资金。

- `unfreeze_capital(strategy_id, amount)`: 解冻并扣除实际买入资金。

- `settle_daily(date, day_close_prices)`:

    - 结合最新收盘价计算总持仓市值。

    - 计算日收益率和最大回撤。

    - 写入 `paper_snapshots`。

### 5\.2 `PaperTradingOrchestrator`

处理整个多策略每日调度的最高编排器：

- `run_daily_process(trade_date: str)`:

    - `auto_discover()` 发现所有策略。

    - 遍历数据库中 `is_active=1` 的活跃策略。

    - 读取当前策略的历史持仓和上下文信息（利用 `DataLoader` 的 `get_price_data` 生成 `Context`）。

    - 触发退出检查 \-\> 触发 on\_bar \-\> 订单撮合 \-\> 结算。

---

## 6\. 命令行界面 \(CLI\) 与功能集成

在 `src/cli/` 中新建 `paper_cli.py`，并将以下子命令挂载到 `main.py` 的主入口：

\- **\*\*每日运行指令\*\***：

`python main.py paper --run [--date YYYY-MM-DD]`

\(默认日期为今天，运行收盘计算并完成所有模拟撮合与快照记录\)

\- **\*\*查看状态指令\*\***：

`python main.py paper --status`

\(以精致的控制台表格形式，输出所有活跃策略账户的总资产、可用现金、持仓总市值、今日收益、最大回撤等\)

\- **\*\*查看特定策略持仓\*\***：

`python main.py paper --show <策略ID>`

\(列出当前账户的持仓列表：代码、持仓数、开仓价、当前价、浮动盈亏等\)

\- **\*\*手动调整现金\*\***：

`python main.py paper --adjust-cash <策略ID> --amount <金额>`

\(允许向虚拟账户充值或提取现金，便于维护和调整\)

---

## 7\. 可视化集成设计 \(Streamlit Dashboard\)

在 Streamlit 可视化大屏中加入模拟交易专属页面（如：`Paper Trading Terminal`）：

\- **\*\*概览面板\*\***：多策略净值曲线（NAV）同台对比，显示累计收益、夏普比率、胜率、最大回撤。

\- **\*\*持仓雷达\*\***：以图表形式展示当前持仓的行业分布、市值分布。

\- **\*\*实时看板\*\***：

- 账户概览表（Cash vs Positions）。

- 当前持仓列表（带有实时涨跌红绿提示）。

- 今日订单/成交日志滚动窗口。

