"""
回测报告生成器
=============

使用 ECharts (pyecharts) 生成交互式 HTML 回测报告。
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np

from pyecharts import options as opts
from pyecharts.charts import Line, Bar, Grid
from pyecharts.commons.utils import JsCode


class BacktestReportGenerator:
    """
    回测报告生成器
    
    使用 ECharts 生成交互式 HTML 回测报告。
    
    Parameters
    ----------
    backtest_result : Dict
        回测结果，包含：
        - portfolio_values: pd.DataFrame, 净值曲线数据
        - performance: Dict, 绩效指标
        - trade_records: List[Dict], 交易记录
    """
    
    def __init__(self, backtest_result: Dict):
        self.portfolio_df = backtest_result.get('portfolio_values', pd.DataFrame())
        self.performance = backtest_result.get('performance', {})
        self.trade_records = backtest_result.get('trade_records', [])
        
        # 计算回撤曲线
        self._calculate_drawdown()
    
    def _calculate_drawdown(self):
        """计算回撤曲线"""
        if self.portfolio_df.empty:
            self.drawdown_series = pd.Series()
            return
        
        values = self.portfolio_df['value'].values
        peak = np.maximum.accumulate(values)
        drawdown = (values - peak) / peak
        self.drawdown_series = pd.Series(drawdown, index=self.portfolio_df.index)
    
    def generate_html(self, output_path: str, title: str = "回测报告") -> str:
        """
        生成 HTML 报告
        
        Parameters
        ----------
        output_path : str
            输出文件路径
        title : str
            报告标题
        
        Returns
        -------
        str
            HTML 文件路径
        """
        # 创建各个图表组件
        nav_chart = self._create_nav_chart()
        drawdown_chart = self._create_drawdown_chart()
        
        # 生成 HTML 内容
        html_content = self._render_html(title, nav_chart, drawdown_chart)
        
        # 确保输出目录存在
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return str(output_path)
    
    def _create_nav_chart(self) -> Line:
        """创建净值曲线图"""
        if self.portfolio_df.empty:
            return Line()
        
        dates = self.portfolio_df['date'].astype(str).tolist()
        values = (self.portfolio_df['value'] / self.portfolio_df['value'].iloc[0] * 100).round(2).tolist()
        
        line = (
            Line(init_opts=opts.InitOpts(
                width="100%",
                height="400px",
                theme="light"
            ))
            .add_xaxis(dates)
            .add_yaxis(
                "组合净值",
                values,
                is_smooth=True,
                symbol="none",
                linestyle_opts=opts.LineStyleOpts(width=2, color="#5470c6"),
                areastyle_opts=opts.AreaStyleOpts(opacity=0.1, color="#5470c6"),
            )
            .set_global_opts(
                title_opts=opts.TitleOpts(
                    title="净值曲线",
                    subtitle="初始净值 = 100",
                    pos_left="center"
                ),
                tooltip_opts=opts.TooltipOpts(
                    trigger="axis",
                    axis_pointer_type="cross",
                    formatter=JsCode("""
                        function(params) {
                            var date = params[0].axisValue;
                            var value = params[0].value;
                            return '日期: ' + date + '<br/>净值: ' + value.toFixed(2);
                        }
                    """)
                ),
                legend_opts=opts.LegendOpts(pos_top="5%"),
                xaxis_opts=opts.AxisOpts(
                    type_="category",
                    axislabel_opts=opts.LabelOpts(rotate=45),
                    splitline_opts=opts.SplitLineOpts(is_show=False)
                ),
                yaxis_opts=opts.AxisOpts(
                    type_="value",
                    name="净值",
                    splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(type_="dashed"))
                ),
                datazoom_opts=[
                    opts.DataZoomOpts(
                        is_show=True,
                        type_="inside",
                        xaxis_index=[0],
                        range_start=0,
                        range_end=100
                    ),
                    opts.DataZoomOpts(
                        is_show=True,
                        type_="slider",
                        xaxis_index=[0],
                        range_start=0,
                        range_end=100
                    )
                ],
                toolbox_opts=opts.ToolboxOpts(
                    is_show=True,
                    feature={
                        "saveAsImage": {"title": "保存图片"},
                        "dataView": {"title": "数据视图", "readOnly": True},
                        "restore": {"title": "还原"},
                    }
                )
            )
        )
        
        return line
    
    def _create_drawdown_chart(self) -> Bar:
        """创建回撤曲线图"""
        if self.drawdown_series.empty:
            return Bar()
        
        dates = self.portfolio_df['date'].astype(str).tolist()
        drawdowns = (self.drawdown_series * 100).round(2).tolist()
        
        # 设置颜色：回撤为红色
        colors = ["#ee6666" if d < 0 else "#91cc75" for d in drawdowns]
        
        bar = (
            Bar(init_opts=opts.InitOpts(
                width="100%",
                height="250px",
                theme="light"
            ))
            .add_xaxis(dates)
            .add_yaxis(
                "回撤(%)",
                drawdowns,
                itemstyle_opts=opts.ItemStyleOpts(color=JsCode("""
                    function(params) {
                        return params.value < 0 ? '#ee6666' : '#91cc75';
                    }
                """))
            )
            .set_global_opts(
                title_opts=opts.TitleOpts(
                    title="回撤曲线",
                    pos_left="center"
                ),
                tooltip_opts=opts.TooltipOpts(
                    trigger="axis",
                    formatter=JsCode("""
                        function(params) {
                            var date = params[0].axisValue;
                            var value = params[0].value;
                            return '日期: ' + date + '<br/>回撤: ' + value.toFixed(2) + '%';
                        }
                    """)
                ),
                xaxis_opts=opts.AxisOpts(
                    type_="category",
                    axislabel_opts=opts.LabelOpts(rotate=45),
                    splitline_opts=opts.SplitLineOpts(is_show=False)
                ),
                yaxis_opts=opts.AxisOpts(
                    type_="value",
                    name="回撤(%)",
                    splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(type_="dashed"))
                ),
                datazoom_opts=[
                    opts.DataZoomOpts(
                        is_show=True,
                        type_="inside",
                        xaxis_index=[0]
                    )
                ]
            )
        )
        
        return bar
    
    def _format_performance_table(self) -> str:
        """生成绩效指标表格 HTML"""
        if not self.performance:
            return "<p>无绩效数据</p>"
        
        # 指标定义
        metrics = [
            ("总收益率", "total_return", "{:.2%}", "回测期间的总收益"),
            ("年化收益率", "annual_return", "{:.2%}", "年化后的收益率"),
            ("年化波动率", "annual_volatility", "{:.2%}", "收益率的年化标准差"),
            ("夏普比率", "sharpe_ratio", "{:.2f}", "风险调整后收益 (无风险利率3%)"),
            ("最大回撤", "max_drawdown", "{:.2%}", "历史最大回撤幅度"),
            ("卡玛比率", "calmar_ratio", "{:.2f}", "年化收益/最大回撤"),
            ("胜率", "win_rate", "{:.2%}", "盈利交易日占比"),
            ("盈亏比", "profit_loss_ratio", "{:.2f}", "平均盈利/平均亏损"),
            ("交易次数", "n_trades", "{:.0f}", "总交易次数"),
        ]
        
        rows = []
        for name, key, fmt, desc in metrics:
            value = self.performance.get(key, 0)
            formatted_value = fmt.format(value)
            
            # 颜色编码
            if key in ['total_return', 'annual_return']:
                color = "color: green;" if value > 0 else "color: red;"
            elif key == 'max_drawdown':
                color = "color: red;"
            elif key == 'sharpe_ratio':
                color = "color: green;" if value > 1 else "color: orange;" if value > 0 else "color: red;"
            else:
                color = ""
            
            rows.append(f"""
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">{name}</td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold; {color}">{formatted_value}</td>
                    <td style="padding: 8px; border-bottom: 1px solid #eee; color: #666;">{desc}</td>
                </tr>
            """)
        
        return f"""
        <table style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr style="background-color: #f5f5f5;">
                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #ddd;">指标名称</th>
                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #ddd;">数值</th>
                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #ddd;">说明</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        """
    
    def _format_trade_table(self, max_rows: int = 100) -> str:
        """生成交易记录表格 HTML"""
        if not self.trade_records:
            return "<p>无交易记录</p>"
        
        # 限制显示行数
        records = self.trade_records[:max_rows]
        
        rows = []
        for record in records:
            date = str(record.get('date', ''))[:10]
            stock_code = record.get('stock_code', '')
            action = record.get('action', '')
            price = record.get('price', 0)
            quantity = record.get('quantity', 0)
            value = record.get('value', 0)
            
            # 买卖颜色
            action_color = "color: green;" if action == 'buy' else "color: red;"
            action_text = "买入" if action == 'buy' else "卖出"
            
            rows.append(f"""
                <tr>
                    <td style="padding: 6px; border-bottom: 1px solid #eee;">{date}</td>
                    <td style="padding: 6px; border-bottom: 1px solid #eee;">{stock_code}</td>
                    <td style="padding: 6px; border-bottom: 1px solid #eee; {action_color} font-weight: bold;">{action_text}</td>
                    <td style="padding: 6px; border-bottom: 1px solid #eee; text-align: right;">{price:.2f}</td>
                    <td style="padding: 6px; border-bottom: 1px solid #eee; text-align: right;">{quantity:,}</td>
                    <td style="padding: 6px; border-bottom: 1px solid #eee; text-align: right;">{value:,.0f}</td>
                </tr>
            """)
        
        more_info = f"<p style='color: #666; margin-top: 10px;'>显示前 {len(records)} 条记录，共 {len(self.trade_records)} 条</p>" if len(self.trade_records) > max_rows else ""
        
        return f"""
        <div style="max-height: 400px; overflow-y: auto;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="background-color: #f5f5f5; position: sticky; top: 0;">
                        <th style="padding: 8px; text-align: left; border-bottom: 2px solid #ddd;">日期</th>
                        <th style="padding: 8px; text-align: left; border-bottom: 2px solid #ddd;">股票代码</th>
                        <th style="padding: 8px; text-align: left; border-bottom: 2px solid #ddd;">方向</th>
                        <th style="padding: 8px; text-align: right; border-bottom: 2px solid #ddd;">价格</th>
                        <th style="padding: 8px; text-align: right; border-bottom: 2px solid #ddd;">数量</th>
                        <th style="padding: 8px; text-align: right; border-bottom: 2px solid #ddd;">金额</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        </div>
        {more_info}
        """
    
    def _format_trade_statistics(self) -> str:
        """生成交易统计 HTML"""
        if not self.trade_records:
            return ""
        
        trades_df = pd.DataFrame(self.trade_records)
        buy_count = len(trades_df[trades_df['action'] == 'buy'])
        sell_count = len(trades_df[trades_df['action'] == 'sell'])
        total_volume = trades_df['value'].sum()
        avg_size = trades_df['value'].mean()
        
        return f"""
        <div style="display: flex; gap: 20px; margin-bottom: 20px;">
            <div style="flex: 1; background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center;">
                <div style="font-size: 24px; font-weight: bold; color: #333;">{len(self.trade_records)}</div>
                <div style="color: #666; font-size: 14px;">总交易次数</div>
            </div>
            <div style="flex: 1; background: #e8f5e9; padding: 15px; border-radius: 8px; text-align: center;">
                <div style="font-size: 24px; font-weight: bold; color: #2e7d32;">{buy_count}</div>
                <div style="color: #666; font-size: 14px;">买入次数</div>
            </div>
            <div style="flex: 1; background: #ffebee; padding: 15px; border-radius: 8px; text-align: center;">
                <div style="font-size: 24px; font-weight: bold; color: #c62828;">{sell_count}</div>
                <div style="color: #666; font-size: 14px;">卖出次数</div>
            </div>
            <div style="flex: 1; background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center;">
                <div style="font-size: 24px; font-weight: bold; color: #333;">{total_volume:,.0f}</div>
                <div style="color: #666; font-size: 14px;">总成交额</div>
            </div>
        </div>
        """
    
    def _format_summary_cards(self) -> str:
        """生成核心指标卡片 HTML"""
        if not self.performance:
            return ""
        
        total_return = self.performance.get('total_return', 0)
        annual_return = self.performance.get('annual_return', 0)
        sharpe = self.performance.get('sharpe_ratio', 0)
        max_dd = self.performance.get('max_drawdown', 0)
        
        def format_value(value, is_percent=True, decimals=2):
            if is_percent:
                return f"{value*100:.{decimals}f}%"
            return f"{value:.{decimals}f}"
        
        def get_color(value, is_return=True):
            if is_return:
                return "#2e7d32" if value > 0 else "#c62828"
            return "#c62828" if value < -0.1 else "#ff9800" if value < -0.05 else "#2e7d32"
        
        return f"""
        <div style="display: flex; gap: 20px; margin-bottom: 30px;">
            <div style="flex: 1; background: linear-gradient(135deg, {get_color(total_return)}15, {get_color(total_return)}05); 
                        padding: 20px; border-radius: 12px; border-left: 4px solid {get_color(total_return)};">
                <div style="color: #666; font-size: 14px; margin-bottom: 5px;">总收益率</div>
                <div style="font-size: 28px; font-weight: bold; color: {get_color(total_return)};">{format_value(total_return)}</div>
            </div>
            <div style="flex: 1; background: linear-gradient(135deg, {get_color(annual_return)}15, {get_color(annual_return)}05); 
                        padding: 20px; border-radius: 12px; border-left: 4px solid {get_color(annual_return)};">
                <div style="color: #666; font-size: 14px; margin-bottom: 5px;">年化收益率</div>
                <div style="font-size: 28px; font-weight: bold; color: {get_color(annual_return)};">{format_value(annual_return)}</div>
            </div>
            <div style="flex: 1; background: linear-gradient(135deg, #1976d215, #1976d205); 
                        padding: 20px; border-radius: 12px; border-left: 4px solid #1976d2;">
                <div style="color: #666; font-size: 14px; margin-bottom: 5px;">夏普比率</div>
                <div style="font-size: 28px; font-weight: bold; color: #1976d2;">{format_value(sharpe, is_percent=False)}</div>
            </div>
            <div style="flex: 1; background: linear-gradient(135deg, {get_color(max_dd, is_return=False)}15, {get_color(max_dd, is_return=False)}05); 
                        padding: 20px; border-radius: 12px; border-left: 4px solid {get_color(max_dd, is_return=False)};">
                <div style="color: #666; font-size: 14px; margin-bottom: 5px;">最大回撤</div>
                <div style="font-size: 28px; font-weight: bold; color: {get_color(max_dd, is_return=False)};">{format_value(max_dd)}</div>
            </div>
        </div>
        """
    
    def _render_html(self, title: str, nav_chart: Line, drawdown_chart: Bar) -> str:
        """渲染完整 HTML 页面"""
        generate_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 获取图表 HTML
        nav_chart_html = nav_chart.render_embed() if nav_chart else ""
        drawdown_chart_html = drawdown_chart.render_embed() if drawdown_chart else ""
        
        # 获取 ECharts 依赖
        echarts_js = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"
        
        return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="{echarts_js}"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #fafafa;
            color: #333;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background: linear-gradient(135deg, #1976d2, #1565c0);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
        }}
        .header .meta {{
            font-size: 14px;
            opacity: 0.9;
        }}
        .section {{
            background: white;
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }}
        .section-title {{
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #1976d2;
        }}
        .chart-container {{
            margin: 20px 0;
        }}
        .footer {{
            text-align: center;
            color: #999;
            font-size: 12px;
            margin-top: 30px;
            padding: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 {title}</h1>
            <div class="meta">
                生成时间: {generate_time} | A股量化分析系统
            </div>
        </div>
        
        <!-- 核心指标卡片 -->
        <div class="section">
            {self._format_summary_cards()}
        </div>
        
        <!-- 净值曲线 -->
        <div class="section">
            <div class="section-title">📈 净值曲线</div>
            <div class="chart-container" id="nav-chart">
                {nav_chart_html}
            </div>
        </div>
        
        <!-- 回撤曲线 -->
        <div class="section">
            <div class="section-title">📉 回撤曲线</div>
            <div class="chart-container" id="drawdown-chart">
                {drawdown_chart_html}
            </div>
        </div>
        
        <!-- 绩效指标 -->
        <div class="section">
            <div class="section-title">📋 绩效指标汇总</div>
            {self._format_performance_table()}
        </div>
        
        <!-- 交易统计 -->
        <div class="section">
            <div class="section-title">📊 交易统计</div>
            {self._format_trade_statistics()}
        </div>
        
        <!-- 交易记录 -->
        <div class="section">
            <div class="section-title">📝 交易记录明细</div>
            {self._format_trade_table()}
        </div>
        
        <div class="footer">
            <p>本报告由 A股量化分析系统 自动生成 | 数据仅供参考，不构成投资建议</p>
        </div>
    </div>
</body>
</html>
        """


def generate_backtest_report(
    backtest_result: Dict,
    output_path: str = "backtest_report.html",
    title: str = "回测报告"
) -> str:
    """
    快捷函数：生成回测报告
    
    Parameters
    ----------
    backtest_result : Dict
        回测结果
    output_path : str
        输出文件路径
    title : str
        报告标题
    
    Returns
    -------
    str
        HTML 文件路径
    """
    generator = BacktestReportGenerator(backtest_result)
    return generator.generate_html(output_path, title)
