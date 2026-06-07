# 国金QMT数据集成实施计划

## 一、任务概述

将国金QMT量化交易接口集成到现有A股量化分析系统中，实现真实数据的获取、存储和使用，替换原有的模拟数据。

### 目标
1. 通过国金QMT接口获取真实股票、指数、基金、ETF数据
2. 扩展数据库表结构以存储QMT返回的所有字段
3. 调整现有代码逻辑以适应真实数据
4. 实现数据完整性校验和停牌数据补充逻辑

### 约束
- 仅开发代码，由用户在本地Windows环境测试验证
- 优先实现日K线数据，基础行情+财务数据
- 首次获取一年历史数据
- 使用用户测试账号：68073686 / 285154

---

## 二、现状分析

### 2.1 国金QMT API关键点

| API | 用途 | 数据类型 |
|-----|------|----------|
| `download_history_data` | 下载单股历史数据 | K线、Tick |
| `download_history_data2` | 批量下载历史数据 | K线 |
| `download_sector_data` | ~~下载板块数据~~ (已废弃) | 改用client.down_all_sector_data |
| `client.down_all_sector_data` | 下载板块数据（推荐） | 板块信息 |
| `download_financial_data` | 下载财务数据 | 财务报表 |
| `get_instrument_detail` | 获取合约详细信息 | 基本信息 |
| `get_market_data_ex` | 获取历史行情 | K线数据 |
| `get_stock_list_in_sector` | 获取板块成分股 | 成分股列表 |
| `get_sector_list` | 获取板块列表 | 板块分类 |
| `get_financial_data` | 获取财务数据 | 财务报表 |

**重要提醒**：
1. QMT需要先调用`download_*`方法下载数据到本地，才能通过`get_*`方法获取数据
2. `xtdata.download_sector_data()`在241014及以上版本存在卡死bug，官方已废弃，必须改用`client.down_all_sector_data()`

### 2.2 现有数据库表结构

| 表名 | 当前字段 | 需扩展字段 |
|------|----------|------------|
| stock_daily | trade_date, stock_code, OHLC, volume, amount, vwap | preClose, suspendFlag, upStop, downStop |
| index_daily | trade_date, index_code, OHLC, volume | preClose |
| stock_info | stock_code, stock_name, industry, market_cap, list_date | exchange, product_type, float_volume, total_volume, instrument_status |
| index_constituent | trade_date, index_code, stock_code, weight, market_cap, pe, pb | 无需扩展 |

### 2.3 需新增的数据库表

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| qmt_instrument | 合约基本信息 | InstrumentID, InstrumentName, ExchangeID, ProductType, OpenDate, PreClose等 |
| qmt_sector | 板块信息 | sector_name, sector_type |
| qmt_sector_constituent | 板块成分股 | trade_date, sector_name, stock_code |
| qmt_financial_balance | 资产负债表 | stock_code, report_date, 各资产负债科目 |
| qmt_financial_income | 利润表 | stock_code, report_date, 各利润科目 |
| qmt_financial_cashflow | 现金流量表 | stock_code, report_date, 各现金流科目 |
| data_sync_log | 数据同步日志 | sync_type, start_time, end_time, record_count, status |

---

## 三、实施步骤

### 阶段一：QMT接口封装模块（新建）

#### 步骤1.1：创建QMT连接器
**文件**: `/workspace/aquant/src/data/qmt_connector.py`

**功能**:
- QMT连接管理（支持MiniQMT模式）
- 数据下载方法封装
- 数据获取方法封装
- 错误处理和重试机制

**关键方法**:
```python
class QMTConnector:
    def __init__(self, account=None, password=None)
    def connect(self) -> bool
    def disconnect(self)
    def get_client(self)  # 获取client对象，用于down_all_sector_data
    def download_stock_list(self) -> List[str]
    def download_history_data(self, stock_list, period, start_time, end_time)
    def download_sector_data(self)  # 使用client.down_all_sector_data()，避免卡死bug
    def get_instrument_detail(self, stock_code) -> Dict
    def get_market_data(self, stock_list, period, start_time, end_time) -> Dict
    def get_sector_list(self) -> List[str]
    def get_stock_list_in_sector(self, sector_name) -> List[str]
    def download_financial_data(self, stock_list, table_list, start_time, end_time)
    def get_financial_data(self, stock_list, table_list, start_time, end_time) -> Dict
```

#### 步骤1.2：创建QMT数据适配器
**文件**: `/workspace/aquant/src/data/qmt_adapter.py`

**功能**:
- 继承`DatabaseAdapter`
- 将QMT数据格式转换为系统内部格式
- 实现数据写入数据库的逻辑

---

### 阶段二：数据库表结构扩展

#### 步骤2.1：扩展现有表
**文件**: `/workspace/aquant/src/data/database.py`

**修改内容**:

1. **stock_daily表** 新增字段:
   - `pre_close` REAL - 前收盘价
   - `suspend_flag` INTEGER - 停牌标记(1停牌,0正常)
   - `up_stop_price` REAL - 涨停价
   - `down_stop_price` REAL - 跌停价

2. **index_daily表** 新增字段:
   - `pre_close` REAL - 前收盘价

3. **stock_info表** 新增字段:
   - `exchange` VARCHAR(20) - 交易所(SH/SZ/BJ)
   - `product_type` INTEGER - 产品类型
   - `float_volume` REAL - 流通股本
   - `total_volume` REAL - 总股本
   - `instrument_status` INTEGER - 停牌状态
   - `up_stop_price` REAL - 涨停价
   - `down_stop_price` REAL - 跌停价

#### 步骤2.2：创建新表
**文件**: `/workspace/aquant/src/data/database.py`

新增以下表:

1. **qmt_instrument表** - 存储所有合约基本信息
2. **qmt_sector表** - 存储板块分类
3. **qmt_sector_constituent表** - 存储板块成分股
4. **qmt_financial_balance表** - 资产负债表
5. **qmt_financial_income表** - 利润表
6. **qmt_financial_cashflow表** - 现金流量表
7. **data_sync_log表** - 数据同步日志

---

### 阶段三：数据同步模块

#### 步骤3.1：创建数据同步器
**文件**: `/workspace/aquant/src/data/data_sync.py`

**功能**:
- 全量数据同步（首次运行）
- 增量数据同步（日常更新）
- 数据完整性校验
- 停牌数据补充逻辑

**关键方法**:
```python
class DataSynchronizer:
    def __init__(self, qmt_connector, db_manager)

    def sync_all(self, start_date, end_date)
        """全量同步：股票列表 -> 基本信息 -> 行情数据 -> 财务数据"""

    def sync_instruments(self)
        """同步所有合约基本信息（股票、指数、基金、ETF）"""

    def sync_stock_list(self)
        """同步股票列表"""

    def sync_daily_data(self, stock_list, start_date, end_date)
        """同步日K线数据"""

    def sync_financial_data(self, stock_list, start_date, end_date)
        """同步财务数据"""

    def sync_sector_data(self)
        """同步板块数据"""

    def check_data_integrity(self, start_date, end_date) -> Dict
        """检查数据完整性"""

    def fill_missing_data(self, stock_code, missing_dates)
        """补充缺失数据（停牌期间用前收盘价填充）"""
```

#### 步骤3.2：数据完整性校验逻辑
**文件**: `/workspace/aquant/src/data/data_validator.py`

**功能**:
- 检查交易日历完整性
- 检查股票数据连续性
- 识别停牌股票
- 自动补充停牌数据

**停牌数据处理规则**:
1. 从QMT获取`suspendFlag`字段识别停牌
2. 停牌期间用前收盘价填充OHLC
3. 成交量、成交额设为0
4. 标记`suspend_flag=1`

---

### 阶段四：现有代码调整

#### 步骤4.1：修改数据加载器
**文件**: `/workspace/aquant/src/data/loader.py`

**修改内容**:
- 新增`from_qmt()`方法
- 调整`get_price_data()`以处理真实数据格式
- 添加数据验证逻辑

#### 步骤4.2：修改测试数据生成器
**文件**: `/workspace/aquant/src/data/test_data_generator.py`

**修改内容**:
- 添加`generate_from_qmt()`方法
- 保留原有模拟数据生成功能（用于测试）

#### 步骤4.3：修改因子计算器
**文件**: `/workspace/aquant/src/factors/calculator.py`

**修改内容**:
- 添加停牌股票过滤逻辑
- 处理缺失数据情况
- 调整VWAP计算逻辑（详见下方说明）

**VWAP计算逻辑调整**:

现状：`calculator.py` 第234-239行，`vwap()`方法优先使用数据库`vwap`字段，否则用`(high+low+close)/3`近似。

问题：QMT日K线不提供VWAP字段，但提供了`amount`（成交额）和`volume`（成交量），可以精确计算真实VWAP。

调整方案：
1. **数据同步时计算VWAP**：在`data_sync.py`的`sync_daily_data()`中，写入数据库前用`amount/volume`计算VWAP，填入`vwap`字段
2. **停牌日VWAP处理**：停牌日`volume=0`，VWAP用前收盘价填充（与OHLC填充逻辑一致）
3. **保留降级逻辑**：`calculator.py`中仍保留`(H+L+C)/3`作为兜底，防止数据异常时因子计算崩溃

影响范围：WorldQuant Alpha#5、Alpha#11 和 国泰君安 GTJ_005 三个因子使用VWAP，切换到真实VWAP后因子值会变化，属正常现象

#### 步骤4.4：修改指数增强分析器
**文件**: `/workspace/aquant/src/enhancement/analyzer.py`

**修改内容**:
- 使用真实成分股数据
- 处理成分股变更情况
- 添加数据有效性检查

#### 步骤4.5：修改主程序
**文件**: `/workspace/aquant/main.py`

**修改内容**:
- 添加QMT数据源选项
- 添加数据同步流程
- 调整分析流程以适应真实数据

---

### 阶段五：配置和文档

#### 步骤5.1：更新配置文件
**文件**: `/workspace/aquant/config/config.py`

**新增配置**:
```python
QMT_CONFIG = {
    'enabled': True,
    'account': '',  # 从环境变量或配置文件读取
    'password': '',
    'default_start_date': '2023-01-01',
    'data_types': ['stock', 'index', 'etf', 'fund'],
    'sync_on_startup': False,
}
```

#### 步骤5.2：更新依赖文件
**文件**: `/workspace/aquant/requirements.txt`

**新增依赖**:
```
xtquant>=1.0.0
```

#### 步骤5.3：更新README文档
**文件**: `/workspace/aquant/README.md`

**新增内容**:
- QMT数据源配置说明
- 数据同步使用方法
- 待办事项更新

---

## 四、文件变更清单

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| 新建 | src/data/qmt_connector.py | QMT接口连接器 |
| 新建 | src/data/qmt_adapter.py | QMT数据适配器 |
| 新建 | src/data/data_sync.py | 数据同步模块 |
| 新建 | src/data/data_validator.py | 数据校验模块 |
| 修改 | src/data/database.py | 扩展表结构、新增表 |
| 修改 | src/data/loader.py | 添加QMT数据源支持 |
| 修改 | src/data/test_data_generator.py | 添加QMT数据生成 |
| 修改 | src/factors/calculator.py | 处理真实数据 |
| 修改 | src/enhancement/analyzer.py | 适应真实数据 |
| 修改 | main.py | 集成QMT数据流程 |
| 修改 | config/config.py | 添加QMT配置 |
| 修改 | requirements.txt | 添加xtquant依赖 |
| 修改 | README.md | 更新文档 |

---

## 五、待办事项更新

| ID | 功能 | 类别 | 优先级 | 状态 |
|----|------|------|--------|------|
| DATA-001 | 分钟级行情数据支持 | 数据层 | 中 | 待开发 |
| DATA-002 | 基本面数据接入 | 数据层 | 中 | 已完成(QMT) |
| DATA-003 | 宏观数据接入 | 数据层 | 低 | 待开发 |
| DATA-004 | 获取指数/ETF真实持仓数据 | 数据层 | 高 | 已完成(QMT) |
| DATA-005 | 股票历史数据校验与停牌补充 | 数据层 | 高 | 待开发 |
| TRADE-001 | 实盘交易接口对接 | 实盘对接 | 低 | 待开发 |
| FEAT-001 | 深度学习相似度 | 功能增强 | 中 | 待开发 |
| FEAT-002 | 遗传编程挖因子 | 功能增强 | 中 | 待开发 |

---

## 六、验证步骤

### 6.1 单元测试
1. 测试QMT连接器连接/断开
2. 测试数据下载功能
3. 测试数据格式转换
4. 测试数据库写入

### 6.2 集成测试
1. 运行完整数据同步流程
2. 验证数据完整性
3. 运行因子计算
4. 运行回测分析
5. 运行指数增强分析

### 6.3 验收标准
- [ ] 能够成功连接QMT并下载数据
- [ ] 数据库中存储了完整的股票、指数、ETF信息
- [ ] 行情数据连续完整，停牌数据正确填充
- [ ] 因子计算结果正确
- [ ] 回测分析正常运行
- [ ] 指数增强分析正常运行
- [ ] 文档已更新

---

## 七、假设与决策

### 假设
1. 用户已在Windows环境安装国金QMT交易端模拟软件
2. 用户能够以极简模式登录QMT
3. 当前开发环境无法直接调用QMT，代码由用户在本地测试

### 决策
1. **数据优先级**：先实现日K线数据，后续再扩展分钟级
2. **历史数据范围**：首次获取一年数据（2023-01-01至今）
3. **停牌数据处理**：用前收盘价填充，成交量为0
4. **代码兼容性**：保留模拟数据功能，支持两种数据源切换
