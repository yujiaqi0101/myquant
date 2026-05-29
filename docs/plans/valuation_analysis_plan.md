# 估值分析模块实施计划

## 一、任务概述

为A股量化分析系统增加估值分析模块，根据标的所属行业选择不同估值模型，结合财报数据和新闻信息评估标的的合理市值区间。

### 目标
1. 实现6大行业分类的差异化估值模型
2. 建立财报数据解析和存储体系
3. 提供合理市值区间估算功能
4. 预留新闻情感分析接口

### 约束
- 复用现有QMT数据接口获取财务数据
- 与现有数据库表结构兼容
- 模块化设计，便于后续扩展

---

## 二、现状分析

### 2.1 现有系统结构
- 数据库：已支持stock_daily、index_daily、stock_info等表
- QMT集成：已通过data_sync.py同步财务数据
- 行业分类：stock_info表已有industry字段

### 2.2 已有财务数据表
- balance_sheet：资产负债表
- income_statement：利润表
- cash_flow_statement：现金流量表

---

## 三、实施步骤

### 阶段一：估值模型框架（基础）

#### 步骤1.1：创建估值模型基类
**文件**: `src/valuation/models/base.py`

**核心内容**:
- ValuationMethod枚举（PE、PB、PS、PEG、EV_EBITDA、DCF、NAV）
- ValuationInput数据类（统一输入格式）
- ValuationResult数据类（统一输出格式）
- ValuationModel抽象基类（定义calculate、get_fair_value_range接口）

#### 步骤1.2：实现金融行业估值模型
**文件**: `src/valuation/models/financial.py`

**核心内容**:
- 适用行业：银行、保险、券商、信托、多元金融
- 主要方法：PB-ROE模型
- 辅助方法：PE估值
- 合理PB区间基于历史分位数和ROE调整

#### 步骤1.3：实现消费行业估值模型
**文件**: `src/valuation/models/consumer.py`

**核心内容**:
- 适用行业：食品饮料、家用电器、医药生物、商贸零售、农林牧渔
- 主要方法：PE、PEG
- 辅助方法：PS
- PEG = PE / 盈利增长率

#### 步骤1.4：实现周期行业估值模型
**文件**: `src/valuation/models/cyclical.py`

**核心内容**:
- 适用行业：煤炭、钢铁、化工、有色金属、石油石化
- 主要方法：PB、EV/EBITDA
- 使用正常化盈利处理周期性

#### 步骤1.5：实现科技行业估值模型
**文件**: `src/valuation/models/technology.py`

**核心内容**:
- 适用行业：电子、计算机、通信、传媒、新能源
- 主要方法：PEG、PS
- 辅助方法：EV/Sales
- 关注成长性和研发投入

#### 步骤1.6：实现房地产估值模型
**文件**: `src/valuation/models/real_estate.py`

**核心内容**:
- 适用行业：房地产、建筑装饰
- 主要方法：NAV（净资产价值）
- NAV = 已开发项目现值 + 土地储备现值 - 净负债

#### 步骤1.7：实现公用事业估值模型
**文件**: `src/valuation/models/utility.py`

**核心内容**:
- 适用行业：电力、水务、燃气、交通运输
- 主要方法：PE、DCF
- 辅助方法：股息率模型
- DCF使用稳定现金流折现

### 阶段二：估值计算器

#### 步骤2.1：创建估值计算器
**文件**: `src/valuation/calculator/valuation_calculator.py`

**核心内容**:
- 行业到估值模型的映射表
- calculate方法：单股票估值
- calculate_batch方法：批量估值
- 自动获取财务数据和股价数据
- 构建ValuationInput对象

#### 步骤2.2：创建估值指标工具
**文件**: `src/valuation/calculator/metrics.py`

**核心内容**:
- calculate_pe、calculate_pb、calculate_ps等静态方法
- calculate_dcf方法（现金流折现）
- get_percentile_rank方法（历史分位数）

### 阶段三：合理市值估算

#### 步骤3.1：创建合理市值估算器
**文件**: `src/valuation/estimator/fair_value_estimator.py`

**核心内容**:
- 整合多种估值方法的结果
- 加权计算综合合理价值
- 计算估值区间（25%-75%分位数）
- 生成投资建议（强烈超配/超配/标配/低配/强烈低配）

### 阶段四：新闻情感分析（预留）

#### 步骤4.1：创建情感分析接口
**文件**: `src/valuation/sentiment/news_sentiment.py`

**核心内容**:
- NewsSentimentAnalyzer抽象基类
- SentimentResult数据类
- MockSentimentAnalyzer实现（开发测试用）
- 预留实际NLP模型接入点

### 阶段五：主入口和集成

#### 步骤5.1：创建估值分析主入口
**文件**: `src/valuation/analyzer.py`

**核心内容**:
- ValuationAnalyzer类整合所有功能
- analyze方法：完整估值分析流程
- screen_undervalued方法：筛选低估股票
- save_results方法：保存结果到数据库

#### 步骤5.2：创建模块初始化文件
**文件**: `src/valuation/__init__.py`

**核心内容**:
- 导出ValuationAnalyzer、各行业模型、估值结果类

#### 步骤5.3：扩展数据库表
**文件**: `src/data/database.py`

**新增表**:
- valuation_result：各估值方法的结果
- valuation_summary：综合估值结果

**新增方法**:
- insert_valuation_result
- get_valuation_result
- get_valuation_summary

#### 步骤5.4：更新主程序
**文件**: `main.py`

**新增内容**:
- 导入ValuationAnalyzer
- 在run_analysis中添加估值分析步骤
- 示例分析前10只股票的估值

#### 步骤5.5：更新配置
**文件**: `config/config.py`

**新增内容**:
- VALUATION_CONFIG配置项
- 各行业模型参数
- 估值权重配置
- 投资建议阈值

#### 步骤5.6：更新文档
**文件**: `README.md`

**新增内容**:
- 估值分析模块功能说明
- 使用示例
- 更新待办事项状态

---

## 四、文件变更清单

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| 新建 | src/valuation/__init__.py | 模块初始化 |
| 新建 | src/valuation/models/__init__.py | 模型子模块初始化 |
| 新建 | src/valuation/models/base.py | 估值模型基类 |
| 新建 | src/valuation/models/financial.py | 金融行业模型 |
| 新建 | src/valuation/models/consumer.py | 消费行业模型 |
| 新建 | src/valuation/models/cyclical.py | 周期行业模型 |
| 新建 | src/valuation/models/technology.py | 科技行业模型 |
| 新建 | src/valuation/models/real_estate.py | 房地产模型 |
| 新建 | src/valuation/models/utility.py | 公用事业模型 |
| 新建 | src/valuation/calculator/__init__.py | 计算器子模块初始化 |
| 新建 | src/valuation/calculator/valuation_calculator.py | 估值计算器 |
| 新建 | src/valuation/calculator/metrics.py | 估值指标工具 |
| 新建 | src/valuation/estimator/__init__.py | 估算器子模块初始化 |
| 新建 | src/valuation/estimator/fair_value_estimator.py | 合理市值估算器 |
| 新建 | src/valuation/sentiment/__init__.py | 情感分析子模块初始化 |
| 新建 | src/valuation/sentiment/news_sentiment.py | 情感分析接口 |
| 新建 | src/valuation/analyzer.py | 估值分析主入口 |
| 修改 | src/data/database.py | 新增估值结果表 |
| 修改 | main.py | 集成估值分析 |
| 修改 | config/config.py | 新增估值配置 |
| 修改 | README.md | 更新文档 |

---

## 五、行业估值模型对照表

| 行业分类 | 主要估值方法 | 辅助估值方法 | 关键指标 |
|----------|--------------|--------------|----------|
| 银行/保险/券商 | PB-ROE | PE | ROE、不良率 |
| 煤炭/钢铁/化工 | PB | EV/EBITDA | 产能利用率、PPI |
| 食品饮料/家电 | PE/PEG | PS | 毛利率、增长率 |
| 电子/计算机/通信 | PEG/PS | EV/Sales | 研发投入、用户增长 |
| 房地产 | NAV | PE | 土储质量、融资成本 |
| 电力/水务/燃气 | PE/DCF | 股息率 | 利用小时数、电价 |

---

## 六、验证步骤

### 6.1 单元测试
- 测试各行业模型的calculate方法
- 测试估值指标计算工具
- 测试合理市值估算器

### 6.2 集成测试
- 测试完整估值分析流程
- 测试批量估值功能
- 测试数据库读写

### 6.3 验收标准
- [ ] 能正确识别行业并选择对应模型
- [ ] 能计算各估值指标
- [ ] 能输出合理市值区间
- [ ] 能生成投资建议
- [ ] 结果能保存到数据库
- [ ] 主程序能正常运行估值分析

---

## 七、假设与决策

### 假设
1. 财务数据已通过QMT同步到数据库
2. 行业分类使用stock_info表中的industry字段
3. 新闻情感分析暂不实现，仅预留接口

### 决策
1. **估值方法选择**：每个行业选择1-2个主要方法，避免过度复杂
2. **合理区间确定**：基于历史分位数（25%-75%）确定估值区间
3. **权重配置**：默认等权重，用户可自定义
4. **数据更新**：估值结果随财报季更新
