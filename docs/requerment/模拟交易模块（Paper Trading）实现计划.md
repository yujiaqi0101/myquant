# 模拟交易模块（Paper Trading）实现计划

# 

本计划旨在为 A 股量化分析系统实现一个完整的模拟交易模块。该模块加载数据库中激活的策略，在每日收盘数据下运行并生成交易决策，通过模拟撮合引擎计算成交、持仓和账户资金，并在 SQLite 数据库中记录完整流水与每日资产净值曲线。

## User Review Required

IMPORTANT

1. **数据库表扩展**：该模块将引入 5 张新表：`paper_accounts` \(资金账户\)、`paper_positions` \(持仓\)、`paper_orders` \(申请单\)、`paper_trades` \(成交流水\)、`paper_snapshots` \(每日净值\)，用于持久化模拟交易状态。

2. **撮合模型假定**：每日买卖订单支持“收盘价成交（close）”与“次日开盘价成交（next\_open）”两种撮合方式。在每日 15:00 收盘后运行程序时，次日开盘价交易会被标记为 Pending，并在下一次运行（即次日收盘后）使用当日的 open 价格撮合成交。

3. **费用和成本**：买入和卖出撮合将计算手续费（默认万三，最低5元）、印花税（卖出千一）与印花过户费，以贴近真实 A 股交易成本。

## Open Questions

NOTE

1. 每个策略在初始运行模拟交易时，默认虚拟资金账户的初始资金应设为多少？（我建议默认为 **1,000,000** 元人民币，可以在配置文件中自定义）

## Proposed Changes

---

### Component 1: 数据库层扩展 \(Database \& Data Access\)

#### \[MODIFY\] database\.py

- 在 `init_database` 中新增 5 张表（`paper_accounts`, `paper_positions`, `paper_orders`, `paper_trades`, `paper_snapshots`）的 SQL 创建语句和必要索引。

- 封装模拟交易的 CRUD 数据库接口：

    - 读取与保存账户状态 \(`get_paper_account`, `save_paper_account`\)

    - 读取与保存持仓列表 \(`get_paper_positions`, `save_paper_position`, `delete_paper_position`\)

    - 记录成交、订单与净值快照 \(`insert_paper_order`, `insert_paper_trade`, `insert_paper_snapshot`\)

    - 清理/重置模拟交易历史接口。

---

### Component 2: 模拟撮合与流程编排 \(Paper Trading Core\)

#### \[NEW\] engine\.py

- 实现 `PaperTradingEngine` 类：

    - 处理单笔买入与卖出的撮合，结合价格、手续费（佣金\+印花税等）计算资金扣减和持仓开仓价。

    - 支持次日开盘执行（next\_open）订单的延迟撮合与可用现金的临时冻结/解冻。

    - 支持每日收盘的账户权益计算，并输出每日资产快照。

#### \[NEW\] orchestrator\.py

- 实现 `PaperTradingOrchestrator` 类：

    - 获取数据库中所有活跃（`is_active=1`）的策略。

    - 为每个策略构造 `Context`，包括可用资金、持仓字典以及基于 `DataLoader` 加载的历史K线缓冲区。

    - 执行主流程：

        1. 撮合昨日生成的 Pending 延迟成交订单（基于今日 open）。

        2. 调用策略 `exit_checker` 判断持仓股的出场逻辑，生成并模拟成交出场订单。

        3. 调用策略 `on_bar` 获取今日开仓选股目标，生成并撮合入场订单（收盘成交，或冻结资金并加入 Pending 次日成交）。

        4. 执行每日收盘计算（总资产 = 现金 \+ 冻结现金 \+ 所有持仓按收盘价折算市值），记录快照至 `paper_snapshots`。

---

### Component 3: 命令行交互接口 \(CLI\)

#### \[NEW\] paper\_cli\.py

- 实现模拟交易的命令行控制子命令：

    - `--run`：执行每日模拟交易的计算流（支持指定 `--date YYYY-MM-DD` 补录历史数据）。

    - `--status`：用 Rich 表格漂亮地展示所有活跃策略账户的总资产、浮动盈亏、日收益率等。

    - `--positions`：查看特定策略的个股持仓明细（包括代码、股数、持仓成本、现价、浮盈等）。

    - `--reset`：清空模拟交易历史，用于重新开始。

#### \[MODIFY\] **init**\.py

- 导出 `paper_cli` 并挂载子命令至主 CLI 解析器。

#### \[MODIFY\] main\.py

- 绑定 `paper` 子命令到主入口，使其支持 `python main.py paper --help` 及其他相关选项。

---

### Component 4: 文档与展示 \(Docs \& Visuals\)

#### \[MODIFY\] README\.md

- 将新模块结构和 CLI 命令补充到 README\.md 说明中。

## Verification Plan

### Automated Tests

- 新增单元测试文件 `tests/test_paper_trading.py`：

    - 测试 `PaperTradingEngine` 手续费计算与持仓逻辑是否准确。

    - 测试 `PaperTradingOrchestrator` 能否正确驱动策略（例如加载小市值策略并生成开仓）。

    - 测试 Pending 订单在次日运行中被成功撮合。

    - **测试命令**：`python -X utf8 -m pytest tests/test_paper_trading.py`

### Manual Verification

1. 生成模拟历史数据并同步到本地数据库。

2. 运行模拟交易初始构建：`python main.py paper --status`（显示初始 1,000,000 元账户）。

3. 模拟执行几个交易日的数据更新： `python main.py paper --run --date 2024-01-02` `python main.py paper --run --date 2024-01-03`

4. 运行 `python main.py paper --status` 查看持仓与资产变动，确保资产扣减及手续费计算完全无误。

