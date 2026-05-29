# 回测结果HTML报告生成功能计划

## Summary

为回测系统增加HTML报告生成功能，使用 ECharts (pyecharts) 生成交互式图表，包含净值曲线、回撤图、绩效指标汇总表、交易记录明细等内容。

## Current State Analysis

### 现有回测系统结构

**回测器** (`src/factors/backtest.py`):
- `Backtester` 类提供回测功能
- `run_backtest()` 返回结果包含：
  - `portfolio_values`: 净值曲线数据 (date, value, capital, position_value)
  - `performance`: 绩效指标 (total_return, annual_return, sharpe_ratio, max_drawdown 等 9 个)
  - `trade_records`: 交易记录列表

**现有可视化** (`src/visualization/dashboard.py`):
- 使用 Streamlit + Plotly
- 已有净值曲线展示
- 缺少独立的HTML报告生成功能

**依赖库**:
- 当前使用 Plotly 做图表
- 需要新增 pyecharts 支持 ECharts

---

## Proposed Changes

### 1. 新增依赖

在 `requirements.txt` 中添加：
```
pyecharts>=2.0.0
jinja2>=3.0.0
```

### 2. 新建 `src/factors/report_generator.py`

创建 `BacktestReportGenerator` 类，核心功能：

```python
class BacktestReportGenerator:
    """回测报告生成器"""
    
    def __init__(self, backtest_result: Dict):
        """
        Parameters
        ----------
        backtest_result : Dict
            回测结果，包含 portfolio_values, performance, trade_records
        """
        
    def generate_html(self, output_path: str, title: str = "回测报告") -> str:
        """
        生成HTML报告
        
        Returns
        -------
        str
            HTML文件路径
        """
        
    def _create_nav_chart(self) -> Chart:
        """创建净值曲线图 (ECharts)"""
        
    def _create_drawdown_chart(self) -> Chart:
        """创建回撤曲线图"""
        
    def _create_performance_table(self) -> str:
        """创建绩效指标表格 (HTML)"""
        
    def _create_trade_table(self) -> str:
        """创建交易记录表格 (HTML)"""
        
    def _render_template(self, charts: Dict, tables: Dict) -> str:
        """渲染HTML模板"""
```

### 3. HTML报告内容结构

```
┌─────────────────────────────────────────────────────────────┐
│                     回测报告标题                              │
│                  生成时间 | 回测参数摘要                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │   总收益: +15.2%     │  │   年化收益: 8.5%     │          │
│  └─────────────────────┘  └─────────────────────┘          │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │   夏普比率: 1.25     │  │   最大回撤: -8.3%    │          │
│  └─────────────────────┘  └─────────────────────┘          │
├─────────────────────────────────────────────────────────────┤
│                     净值曲线 (ECharts交互图)                  │
│  [可缩放、悬停查看数据、切换显示净值/基准]                      │
├─────────────────────────────────────────────────────────────┤
│                     回撤曲线 (ECharts交互图)                  │
│  [显示每个回撤期、最大回撤标注]                               │
├─────────────────────────────────────────────────────────────┤
│                     绩效指标汇总表                            │
│  | 指标名称 | 数值 | 说明 |                                  │
│  | 总收益   | 15.2%| ...  |                                  │
│  | ...      | ...  | ...  |                                  │
├─────────────────────────────────────────────────────────────┤
│                     交易记录明细                              │
│  [可排序、筛选的表格]                                         │
│  | 日期 | 股票代码 | 方向 | 价格 | 数量 | 金额 |              │
├─────────────────────────────────────────────────────────────┤
│                     交易统计                                  │
│  | 总交易次数 | 买入次数 | 卖出次数 | 总成交额 |              │
└─────────────────────────────────────────────────────────────┘
```

### 4. 图表实现细节

#### 净值曲线图 (ECharts)
- 主图：组合净值曲线
- 可选：添加基准对比线
- 交互：缩放、区域选择、悬停显示数据
- 工具栏：下载图片、数据视图

#### 回撤曲线图 (ECharts)
- 计算每日回撤率
- 标注最大回撤位置
- 颜色区分回撤深度

#### 绩效指标表
- 核心指标：总收益、年化收益、夏普比率、最大回撤、卡玛比率、胜率、盈亏比、交易次数
- 格式化显示：百分比、保留小数位
- 颜色编码：正收益绿色、负收益红色

#### 交易记录表
- 支持分页、排序
- 买入/卖出颜色区分
- 导出CSV功能

### 5. 修改 `src/factors/backtest.py`

在 `Backtester` 类中添加报告生成方法：

```python
def generate_report(self, output_path: str = "backtest_report.html", 
                    title: str = "回测报告") -> str:
    """
    生成回测HTML报告
    
    Parameters
    ----------
    output_path : str
        输出文件路径
    title : str
        报告标题
        
    Returns
    -------
    str
        HTML文件路径
    """
    from .report_generator import BacktestReportGenerator
    
    result = {
        'portfolio_values': self._portfolio_df,
        'performance': self._last_performance,
        'trade_records': self._trade_records
    }
    
    generator = BacktestReportGenerator(result)
    return generator.generate_html(output_path, title)
```

### 6. 修改 `src/factors/__init__.py`

添加新模块导出：
```python
from .report_generator import BacktestReportGenerator
```

---

## Assumptions & Decisions

1. **图表库选择**：使用 pyecharts (ECharts 的 Python 封装)，生成独立 HTML 文件，无需服务器即可查看
2. **报告格式**：单文件 HTML，所有资源内嵌，方便分享和存档
3. **样式设计**：简洁专业的金融报告风格，深色/浅色主题可选
4. **扩展性**：预留接口支持自定义图表和指标

---

## Verification Steps

1. **单元测试**：
   - 测试报告生成器初始化
   - 测试各图表组件生成
   - 测试HTML文件生成

2. **集成测试**：
   - 运行完整回测流程
   - 生成HTML报告
   - 在浏览器中验证报告显示正确

3. **功能验证**：
   - 净值曲线可交互（缩放、悬停）
   - 回撤曲线正确计算
   - 绩效指标格式正确
   - 交易记录表格可排序

---

## Files to Modify/Create

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| MODIFY | `requirements.txt` | 添加 pyecharts, jinja2 |
| CREATE | `src/factors/report_generator.py` | 报告生成器核心类 |
| CREATE | `src/factors/templates/report.html` | HTML模板文件 |
| MODIFY | `src/factors/backtest.py` | 添加 generate_report 方法 |
| MODIFY | `src/factors/__init__.py` | 添加新模块导出 |
