# A股量化分析系统 SQLite数据库实现计划

## 一、需求概述

1. **创建SQLite数据库**：包含5个表
   - `stock_daily`: 股票日频数据
   - `index_daily`: 指数日频数据
   - `stock_info`: 股票信息
   - `execution_log`: 执行日志（增强版）
   - `best_records`: 最佳表现记录

2. **添加测试数据**：生成模拟的股票、指数数据

3. **调整系统**：DataLoader改为从数据库读取

4. **执行日志**：记录详细的执行条件和各指标最佳表现

---

## 二、当前状态分析

- `config/config.py` 已定义 `DATABASE_CONFIG = {"type": "sqlite", "path": "data/aquant.db"}`
- `src/data/` 包含 adapter.py（数据适配器）和 loader.py（数据加载器）
- `src/factors/` 包含 selector.py（因子筛选）和 backtest.py（回测器）

---

## 三、文件变更计划

### 新建文件

| 文件路径 | 说明 |
|---------|------|
| `src/data/database.py` | 数据库核心模块：连接管理、表创建、CRUD操作 |
| `src/data/test_data_generator.py` | 测试数据生成器：生成股票、指数、股票信息 |
| `src/data/db_adapter.py` | 数据库适配器：实现与DailyDataAdapter相同接口 |
| `src/factors/execution_logger.py` | 执行日志记录器：自动记录评估和回测结果 |
| `tests/test_database.py` | 数据库模块单元测试 |

### 修改文件

| 文件路径 | 修改内容 |
|---------|---------|
| `src/data/__init__.py` | 导出新增的数据库相关类 |
| `src/data/loader.py` | 添加 `from_database()` 类方法 |
| `src/factors/selector.py` | 添加 `execution_logger` 参数 |
| `src/factors/backtest.py` | 添加 `execution_logger` 参数 |
| `main.py` | 添加数据库初始化和日志查询功能 |

---

## 四、数据库表结构

### 4.1 股票日频数据表 (stock_daily)

```sql
CREATE TABLE stock_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date DATE NOT NULL,
    stock_code VARCHAR(20) NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, amount REAL, vwap REAL,
    UNIQUE(trade_date, stock_code)
);
```

### 4.2 指数日频数据表 (index_daily)

```sql
CREATE TABLE index_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date DATE NOT NULL,
    index_code VARCHAR(20) NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    UNIQUE(trade_date, index_code)
);
```

### 4.3 股票信息表 (stock_info)

```sql
CREATE TABLE stock_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code VARCHAR(20) UNIQUE NOT NULL,
    stock_name VARCHAR(100), industry VARCHAR(100),
    market_cap REAL, list_date DATE
);
```

### 4.4 执行日志表 (execution_log) - 增强版

```sql
CREATE TABLE execution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 执行基本信息
    execution_type VARCHAR(50) NOT NULL,  -- 'backtest', 'factor_evaluation'
    status VARCHAR(20) DEFAULT 'success',  -- 'success', 'failed'
    
    -- 执行条件
    start_date DATE,           -- 数据开始日期
    end_date DATE,             -- 数据结束日期
    n_stocks INTEGER,          -- 股票数量
    n_days INTEGER,            -- 交易日数量
    
    -- 因子/策略信息
    factor_name VARCHAR(100),
    factor_category VARCHAR(50),  -- 'worldquant', 'guotai', 'custom'
    
    -- 回测参数
    n_positions INTEGER,       -- 持仓数量
    rebalance_freq INTEGER,    -- 调仓频率
    initial_capital REAL,     -- 初始资金
    
    -- 绩效指标
    ic_mean REAL,              -- IC均值
    ic_std REAL,               -- IC标准差
    ir REAL,                   -- IR值
    sharpe REAL,               -- 夏普比率
    max_drawdown REAL,         -- 最大回撤
    total_return REAL,         -- 总收益
    annual_return REAL,        -- 年化收益
    annual_volatility REAL,    -- 年化波动率
    win_rate REAL,             -- 胜率
    
    -- 详细信息
    details TEXT               -- JSON格式的额外信息
);
```

### 4.5 最佳记录表 (best_records)

```sql
CREATE TABLE best_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category VARCHAR(50) NOT NULL,    -- 'factor', 'backtest'
    metric_name VARCHAR(100) NOT NULL,  -- 'IC', 'IR', 'Sharpe', 'MaxDrawdown', 'TotalReturn'
    best_value REAL,
    record_date DATE,
    execution_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (execution_id) REFERENCES execution_log(id)
);
```

---

## 五、实施步骤

### 步骤1：创建数据库核心模块
- 新建 `src/data/database.py`
- 实现 `DatabaseManager` 类
- 包含表创建、索引、CRUD操作
- 包含执行日志记录、最佳记录更新功能

### 步骤2：创建测试数据生成器
- 新建 `src/data/test_data_generator.py`
- 实现 `TestDataGenerator` 类
- 生成股票信息、股票日频数据、指数日频数据
- 支持保存到数据库

### 步骤3：创建数据库适配器
- 新建 `src/data/db_adapter.py`
- 实现 `DatabaseAdapter` 类
- 继承 `DailyDataAdapter`
- 实现相同的数据访问接口

### 步骤4：创建执行日志记录器
- 新建 `src/factors/execution_logger.py`
- 实现 `ExecutionLogger` 类
- 封装日志记录和最佳记录更新
- 提供查询接口

### 步骤5：修改DataLoader
- 修改 `src/data/loader.py`
- 添加 `from_database()` 类方法
- 支持从数据库加载所有数据

### 步骤6：集成执行日志
- 修改 `src/factors/backtest.py`
- 修改 `src/factors/selector.py`
- 添加 `execution_logger` 参数
- 每次评估/回测自动记录

### 步骤7：更新主入口
- 修改 `main.py`
- 添加数据库初始化逻辑
- 添加最佳记录查询显示

### 步骤8：创建测试文件
- 新建 `tests/test_database.py`
- 测试数据库CRUD操作
- 测试数据生成器
- 测试执行日志

### 步骤9：运行验证
- 运行单元测试
- 验证数据一致性
- 验证日志记录功能

---

## 六、验证步骤

1. **数据库创建验证**：
   - 启动后数据库文件存在
   - 所有表创建成功
   - 索引正确创建

2. **数据插入验证**：
   - 股票信息正确插入
   - 股票日频数据正确插入
   - 指数数据正确插入

3. **数据查询验证**：
   - DataLoader.from_database() 正常工作
   - 查询结果与直接SQL查询一致

4. **执行日志验证**：
   - 因子评估结果自动记录（包含执行条件）
   - 回测结果自动记录（包含回测参数）
   - best_records 正确更新

5. **最佳记录查询验证**：
   - 可以查询各指标最佳表现
   - 可以查询执行历史
   - 可以按条件筛选日志

---

## 七、假设与决策

1. **数据粒度**：每次执行记录一条汇总记录
2. **执行日志记录内容**：
   - 执行基本信息（时间、类型、状态）
   - 执行条件（日期范围、股票数量）
   - 因子/策略信息
   - 回测参数
   - 绩效指标
   - 详细信息（JSON格式）
3. **最佳记录更新逻辑**：
   - IC、IR、夏普、总收益：越大越好
   - 最大回撤：越小越好（取绝对值比较）
4. **数据来源**：仅从数据库读取
5. **兼容性**：保持现有接口不变，通过参数切换

---

## 八、预期产出

1. `/workspace/aquant/src/data/database.py` - 数据库核心模块
2. `/workspace/aquant/src/data/test_data_generator.py` - 测试数据生成器
3. `/workspace/aquant/src/data/db_adapter.py` - 数据库适配器
4. `/workspace/aquant/src/factors/execution_logger.py` - 执行日志记录器
5. `/workspace/aquant/tests/test_database.py` - 数据库测试
6. 更新后的 loader.py, backtest.py, selector.py, main.py
7. 更新的 README.md
