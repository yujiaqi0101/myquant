"""
HTML 报告生成器
==============

将回测结果生成为可视化的 HTML 报告。
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import base64
import sqlite3


class HTMLReporter:
    """HTML 报告生成器"""

    def __init__(self, result_dir: str):
        """
        初始化报告生成器

        Parameters
        ----------
        result_dir : str
            回测结果目录路径（包含 performance.json, trades.json, snapshots.json）
        """
        self.result_dir = Path(result_dir)
        self.performance = self._load_json('performance.json')
        self.trades = self._load_json('trades.json')
        self.snapshots = self._load_json('snapshots.json')
        self.klines = self._load_json('klines.json')
        self.stock_names = self._load_stock_names()

    def _load_json(self, filename: str) -> Any:
        """加载 JSON 文件"""
        filepath = self.result_dir / filename
        if not filepath.exists():
            return {} if 'performance' in filename else []
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _load_stock_names(self) -> Dict[str, str]:
        """从数据库加载股票名称"""
        stock_names = {}
        try:
            # 查找数据库路径
            db_path = self.result_dir.parent.parent / 'data' / 'aquant.db'
            if not db_path.exists():
                # 尝试默认路径
                db_path = Path('e:/python_space/myquant/data/aquant.db')
            
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT stock_code, stock_name FROM stock_info")
                for row in cursor.fetchall():
                    stock_names[row[0]] = row[1]
                conn.close()
        except Exception:
            pass
        return stock_names

    def generate(self, output_path: Optional[str] = None) -> str:
        """
        生成 HTML 报告

        Parameters
        ----------
        output_path : str, optional
            输出文件路径，默认保存到结果目录下的 report.html

        Returns
        -------
        str
            生成的 HTML 文件路径
        """
        if output_path is None:
            output_path = self.result_dir / 'report.html'
        else:
            output_path = Path(output_path)

        html = self._build_html()

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        return str(output_path)

    def _build_html(self) -> str:
        """构建完整的 HTML 文档"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>回测报告 - {self.performance.get('strategy_name', 'Unknown')}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        {self._get_css()}
    </style>
</head>
<body>
    <div class="container">
        {self._build_header()}
        {self._build_summary()}
        {self._build_charts()}
        {self._build_trades_table()}
        {self._build_stock_detail()}
        {self._build_daily_snapshots()}
    </div>
    <script>
        {self._get_javascript()}
    </script>
</body>
</html>"""

    def _get_css(self) -> str:
        """获取 CSS 样式"""
        return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 24px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }
        
        .header .subtitle {
            opacity: 0.9;
            font-size: 14px;
        }
        
        .card {
            background: white;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        
        .card-title {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 20px;
            color: #1a1a2e;
            border-left: 4px solid #667eea;
            padding-left: 12px;
        }
        
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }
        
        .metric-item {
            background: #f8f9fa;
            padding: 16px;
            border-radius: 8px;
            text-align: center;
        }
        
        .metric-label {
            font-size: 12px;
            color: #666;
            margin-bottom: 4px;
        }
        
        .metric-value {
            font-size: 24px;
            font-weight: 600;
            color: #1a1a2e;
        }
        
        .metric-value.positive {
            color: #f5222d;  /* 中国股市：红涨 */
        }
        
        .metric-value.negative {
            color: #52c41a;  /* 中国股市：绿跌 */
        }
        
        .chart-container {
            position: relative;
            height: 400px;
            margin: 20px 0;
        }
        
        .trades-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        
        .trades-table th,
        .trades-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e8e8e8;
        }
        
        .trades-table th {
            background: #f8f9fa;
            font-weight: 600;
            color: #666;
            position: sticky;
            top: 0;
        }
        
        .trades-table tr:hover {
            background: #f8f9fa;
        }
        
        .trades-table .action-open {
            color: #f5222d;  /* 中国股市：买入用红色 */
            font-weight: 500;
        }
        
        .trades-table .action-close {
            color: #52c41a;  /* 中国股市：卖出用绿色 */
            font-weight: 500;
        }
        
        .trades-table .pnl-positive {
            color: #f5222d;  /* 中国股市：红涨 */
        }
        
        .trades-table .pnl-negative {
            color: #52c41a;  /* 中国股市：绿跌 */
        }
        
        .tag {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 500;
        }
        
        .tag-buy {
            background: #fff1f0;
            color: #f5222d;  /* 中国股市：买入用红色 */
            border: 1px solid #ffa39e;
        }
        
        .tag-sell {
            background: #f6ffed;
            color: #52c41a;  /* 中国股市：卖出用绿色 */
            border: 1px solid #b7eb8f;
        }
        
        .info-row {
            display: flex;
            gap: 24px;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }
        
        .info-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .info-label {
            color: #666;
            font-size: 13px;
        }
        
        .info-value {
            font-weight: 500;
            color: #1a1a2e;
        }
        
        .table-container {
            max-height: 500px;
            overflow-y: auto;
            border-radius: 8px;
            border: 1px solid #e8e8e8;
        }
        
        /* 个股明细样式 */
        .stock-detail-container {
            display: flex;
            gap: 24px;
            min-height: 600px;
        }
        
        .stock-list-panel {
            width: 280px;
            flex-shrink: 0;
            border: 1px solid #e8e8e8;
            border-radius: 8px;
            overflow: hidden;
        }
        
        .stock-list-header {
            background: #f8f9fa;
            padding: 12px 16px;
            font-weight: 600;
            border-bottom: 1px solid #e8e8e8;
        }
        
        .stock-list {
            max-height: 550px;
            overflow-y: auto;
        }
        
        .stock-item {
            padding: 12px 16px;
            border-bottom: 1px solid #f0f0f0;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .stock-item:hover {
            background: #f5f7fa;
        }
        
        .stock-item.active {
            background: #e6f7ff;
            border-left: 3px solid #1890ff;
        }
        
        .stock-item-code {
            font-weight: 600;
            color: #1a1a2e;
        }
        
        .stock-item-stats {
            font-size: 12px;
            color: #666;
            margin-top: 4px;
        }
        
        .stock-item-pnl {
            font-weight: 500;
        }
        
        .stock-item-pnl.positive {
            color: #f5222d;  /* 中国股市：红涨 */
        }
        
        .stock-item-pnl.negative {
            color: #52c41a;  /* 中国股市：绿跌 */
        }
        
        .stock-detail-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        
        .kline-container {
            background: #fafafa;
            border-radius: 8px;
            padding: 16px;
            height: 400px;
        }
        
        .kline-chart {
            width: 100%;
            height: 100%;
        }
        
        .stock-trades-panel {
            flex: 1;
            border: 1px solid #e8e8e8;
            border-radius: 8px;
            overflow: hidden;
        }
        
        .stock-trades-header {
            background: #f8f9fa;
            padding: 12px 16px;
            font-weight: 600;
            border-bottom: 1px solid #e8e8e8;
        }
        
        .stock-trades-table {
            max-height: 180px;
            overflow-y: auto;
        }
        
        .no-data {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: #999;
            font-size: 14px;
        }
        
        @media (max-width: 768px) {
            .stock-detail-container {
                flex-direction: column;
            }
            
            .stock-list-panel {
                width: 100%;
            }
            
            .metrics-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            
            .trades-table {
                font-size: 11px;
            }
            
            .trades-table th,
            .trades-table td {
                padding: 8px;
            }
        }
        """

    def _build_header(self) -> str:
        """构建头部区域"""
        strategy_name = self.performance.get('strategy_name', 'Unknown')
        start_date = self.performance.get('start_date', '-')
        end_date = self.performance.get('end_date', '-')

        return f"""
        <div class="header">
            <h1>📊 回测报告</h1>
            <div class="subtitle">
                策略: {strategy_name} | 
                回测区间: {start_date} ~ {end_date} |
                生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
        </div>
        """

    def _build_summary(self) -> str:
        """构建绩效摘要卡片"""
        perf = self.performance
        total_return = perf.get('total_return', 0)
        annual_return = perf.get('annual_return', 0)
        sharpe = perf.get('sharpe_ratio', 0)
        max_dd = perf.get('max_drawdown', 0)
        win_rate = perf.get('win_rate', 0)
        total_trades = perf.get('total_trades', 0)

        return f"""
        <div class="card">
            <div class="card-title">绩效摘要</div>
            <div class="metrics-grid">
                <div class="metric-item">
                    <div class="metric-label">总收益率</div>
                    <div class="metric-value {'positive' if total_return > 0 else 'negative'}">{total_return:+.2%}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">年化收益</div>
                    <div class="metric-value {'positive' if annual_return > 0 else 'negative'}">{annual_return:+.2%}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">夏普比率</div>
                    <div class="metric-value">{sharpe:.2f}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">最大回撤</div>
                    <div class="metric-value negative">{max_dd:.2%}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">胜率</div>
                    <div class="metric-value">{win_rate:.1%}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">交易次数</div>
                    <div class="metric-value">{total_trades}</div>
                </div>
            </div>
            
            <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid #e8e8e8;">
                <div class="info-row">
                    <div class="info-item">
                        <span class="info-label">初始资金:</span>
                        <span class="info-value">¥{perf.get('initial_capital', 0):,.2f}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">最终资产:</span>
                        <span class="info-value">¥{perf.get('final_value', 0):,.2f}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">年化波动率:</span>
                        <span class="info-value">{perf.get('annual_volatility', 0):.2%}</span>
                    </div>
                </div>
            </div>
        </div>
        """

    def _build_charts(self) -> str:
        """构建图表区域"""
        return """
        <div class="card">
            <div class="card-title">净值曲线</div>
            <div class="chart-container">
                <canvas id="equityChart"></canvas>
            </div>
        </div>
        """

    def _build_trades_table(self) -> str:
        """构建交易记录表格"""
        if not self.trades:
            return ""

        rows = []
        for trade in self.trades:
            action_class = "action-open" if trade.get('action') == 'open' else "action-close"
            action_text = "买入开仓" if trade.get('action') == 'open' else "卖出平仓"
            tag_class = "tag-buy" if trade.get('action') == 'open' else "tag-sell"

            pnl = trade.get('pnl', 0)
            pnl_class = ""
            pnl_text = "-"
            if pnl != 0:
                pnl_class = "pnl-positive" if pnl > 0 else "pnl-negative"
                pnl_text = f"{pnl:+.2f}"

            rows.append(f"""
                <tr>
                    <td>{trade.get('date', '-')}</td>
                    <td>{trade.get('stock_code', '-')}</td>
                    <td><span class="tag {tag_class}">{action_text}</span></td>
                    <td>{trade.get('price', 0):.3f}</td>
                    <td>{trade.get('quantity', 0):,}</td>
                    <td class="{pnl_class}">{pnl_text}</td>
                    <td>{trade.get('reason', '-')}</td>
                </tr>
            """)

        return f"""
        <div class="card">
            <div class="card-title">交易记录 ({len(self.trades)} 笔)</div>
            <div class="table-container">
                <table class="trades-table">
                    <thead>
                        <tr>
                            <th>日期</th>
                            <th>股票代码</th>
                            <th>操作</th>
                            <th>价格</th>
                            <th>数量</th>
                            <th>盈亏</th>
                            <th>原因</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(rows)}
                    </tbody>
                </table>
            </div>
        </div>
        """

    def _build_stock_detail(self) -> str:
        """构建个股明细区域"""
        if not self.trades or not self.klines:
            return ""
        
        # 统计每只股票的交易信息
        stock_stats = {}
        for trade in self.trades:
            code = trade.get('stock_code', '')
            if not code:
                continue
            if code not in stock_stats:
                stock_stats[code] = {
                    'trades': 0,
                    'total_pnl': 0,
                    'wins': 0,
                }
            stock_stats[code]['trades'] += 1
            pnl = trade.get('pnl', 0)
            stock_stats[code]['total_pnl'] += pnl
            if pnl > 0:
                stock_stats[code]['wins'] += 1
        
        # 生成股票列表
        stock_items = []
        for code, stats in sorted(stock_stats.items(), key=lambda x: -x[1]['total_pnl']):
            pnl_class = "positive" if stats['total_pnl'] > 0 else "negative" if stats['total_pnl'] < 0 else ""
            win_rate = stats['wins'] / max(1, stats['trades'] // 2) * 100  # 买卖成对
            stock_name = self.stock_names.get(code, '')
            display_name = f"{code} {stock_name}" if stock_name else code
            
            stock_items.append(f"""
                <div class="stock-item" onclick="selectStock('{code}')" data-stock="{code}">
                    <div class="stock-item-code">{display_name}</div>
                    <div class="stock-item-stats">
                        交易 {stats['trades']}笔 | 胜率 {win_rate:.0f}%
                        <span class="stock-item-pnl {pnl_class}">盈亏 {stats['total_pnl']:+.0f}</span>
                    </div>
                </div>
            """)
        
        return f"""
        <div class="card">
            <div class="card-title">个股明细</div>
            <div class="stock-detail-container">
                <div class="stock-list-panel">
                    <div class="stock-list-header">股票列表 ({len(stock_stats)} 只)</div>
                    <div class="stock-list">
                        {''.join(stock_items)}
                    </div>
                </div>
                <div class="stock-detail-panel">
                    <div class="kline-container">
                        <div id="klineChart" class="kline-chart">
                            <div class="no-data">请从左侧选择股票查看K线图</div>
                        </div>
                    </div>
                    <div class="stock-trades-panel">
                        <div class="stock-trades-header">交易明细</div>
                        <div id="stockTradesTable" class="stock-trades-table">
                            <div class="no-data">选择股票后显示交易明细</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """

    def _build_daily_snapshots(self) -> str:
        """构建每日快照表格"""
        if not self.snapshots:
            return ""

        rows = []
        for snap in self.snapshots:
            total_value = snap.get('total_value', 0)
            daily_return = snap.get('daily_return', 0)
            return_class = "pnl-positive" if daily_return > 0 else "pnl-negative" if daily_return < 0 else ""

            rows.append(f"""
                <tr>
                    <td>{snap.get('date', '-')}</td>
                    <td>¥{snap.get('cash', 0):,.2f}</td>
                    <td>¥{snap.get('position_value', 0):,.2f}</td>
                    <td>¥{total_value:,.2f}</td>
                    <td class="{return_class}">{daily_return:+.2%}</td>
                    <td>{snap.get('n_positions', 0)}</td>
                </tr>
            """)

        return f"""
        <div class="card">
            <div class="card-title">每日账户快照 ({len(self.snapshots)} 天)</div>
            <div class="table-container">
                <table class="trades-table">
                    <thead>
                        <tr>
                            <th>日期</th>
                            <th>现金</th>
                            <th>持仓市值</th>
                            <th>总资产</th>
                            <th>日收益率</th>
                            <th>持仓数</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(rows)}
                    </tbody>
                </table>
            </div>
        </div>
        """

    def _get_javascript(self) -> str:
        """获取 JavaScript 代码"""
        # 准备净值曲线数据
        equity_data = []
        if self.snapshots:
            for snap in self.snapshots:
                equity_data.append({
                    'date': snap.get('date', ''),
                    'value': snap.get('total_value', 0)
                })

        equity_json = json.dumps(equity_data, ensure_ascii=False)
        
        # K线数据和交易数据
        klines_json = json.dumps(self.klines, ensure_ascii=False)
        trades_json = json.dumps(self.trades, ensure_ascii=False)

        return f"""
        // 净值曲线数据
        const equityData = {equity_json};
        
        // K线数据
        const klinesData = {klines_json};
        
        // 交易记录
        const tradesData = {trades_json};
        
        // 当前选中的股票
        let selectedStock = null;
        let klineChart = null;
        
        // 绘制净值曲线
        const ctx = document.getElementById('equityChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: equityData.map(d => d.date),
                datasets: [{{
                    label: '总资产',
                    data: equityData.map(d => d.value),
                    borderColor: '#667eea',
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 6
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    intersect: false,
                    mode: 'index'
                }},
                plugins: {{
                    legend: {{
                        display: false
                    }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                return '总资产: ¥' + context.parsed.y.toLocaleString('zh-CN', {{
                                    minimumFractionDigits: 2,
                                    maximumFractionDigits: 2
                                }});
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        grid: {{
                            display: false
                        }},
                        ticks: {{
                            maxTicksLimit: 10
                        }}
                    }},
                    y: {{
                        beginAtZero: false,
                        ticks: {{
                            callback: function(value) {{
                                return '¥' + (value / 10000).toFixed(1) + '万';
                            }}
                        }}
                    }}
                }}
            }}
        }});
        
        // 选择股票
        function selectStock(stockCode) {{
            // 更新选中状态
            document.querySelectorAll('.stock-item').forEach(el => {{
                el.classList.remove('active');
            }});
            document.querySelector(`.stock-item[data-stock="${{stockCode}}"]`).classList.add('active');
            
            selectedStock = stockCode;
            
            // 绘制K线图
            drawKlineChart(stockCode);
            
            // 显示交易明细
            showStockTrades(stockCode);
        }}
        
        // 绘制K线图（简化版：使用收盘价折线图+买卖点标记）
        function drawKlineChart(stockCode) {{
            const kline = klinesData[stockCode];
            if (!kline || kline.length === 0) {{
                document.getElementById('klineChart').innerHTML = '<div class="no-data">无K线数据</div>';
                return;
            }}
            
            // 获取该股票的交易点
            const stockTrades = tradesData.filter(t => t.stock_code === stockCode);
            const buyPoints = {{}};
            const sellPoints = {{}};
            stockTrades.forEach(t => {{
                if (t.action === 'open') {{
                    buyPoints[t.date] = t.price;
                }} else {{
                    sellPoints[t.date] = t.price;
                }}
            }});
            
            // 销毁旧图表
            if (klineChart) {{
                klineChart.destroy();
            }}
            
            // 创建新图表
            const container = document.getElementById('klineChart');
            container.innerHTML = '<canvas id="klineCanvas"></canvas>';
            const ctx = document.getElementById('klineCanvas').getContext('2d');
            
            // 准备数据
            const labels = kline.map(d => d.date);
            const closes = kline.map(d => d.close);
            
            // 买卖点数据
            const buyMarkers = kline.map(d => buyPoints[d.date] || null);
            const sellMarkers = kline.map(d => sellPoints[d.date] || null);
            
            klineChart = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: labels,
                    datasets: [
                        {{
                            label: '收盘价',
                            data: closes,
                            borderColor: '#667eea',
                            backgroundColor: 'rgba(102, 126, 234, 0.05)',
                            borderWidth: 1.5,
                            fill: true,
                            tension: 0.1,
                            pointRadius: 0,
                        }},
                        {{
                            label: '买入',
                            data: buyMarkers,
                            borderColor: '#f5222d',  /* 中国股市：买入用红色 */
                            backgroundColor: '#f5222d',
                            pointStyle: 'triangle',
                            pointRadius: 8,
                            pointHoverRadius: 10,
                            showLine: false,
                        }},
                        {{
                            label: '卖出',
                            data: sellMarkers,
                            borderColor: '#52c41a',  /* 中国股市：卖出用绿色 */
                            backgroundColor: '#52c41a',
                            pointStyle: 'triangle',
                            pointRadius: 8,
                            pointHoverRadius: 10,
                            rotation: 180,
                            showLine: false,
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{
                        intersect: false,
                        mode: 'index'
                    }},
                    plugins: {{
                        legend: {{
                            display: true,
                            position: 'top'
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    if (context.dataset.label === '收盘价') {{
                                        return '收盘: ¥' + context.parsed.y.toFixed(2);
                                    }} else if (context.dataset.label === '买入') {{
                                        return '买入: ¥' + context.parsed.y.toFixed(2);
                                    }} else if (context.dataset.label === '卖出') {{
                                        return '卖出: ¥' + context.parsed.y.toFixed(2);
                                    }}
                                    return null;
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            grid: {{ display: false }},
                            ticks: {{ maxTicksLimit: 15 }}
                        }},
                        y: {{
                            beginAtZero: false,
                            ticks: {{
                                callback: function(value) {{
                                    return '¥' + value.toFixed(2);
                                }}
                            }}
                        }}
                    }}
                }}
            }});
        }}
        
        // 显示股票交易明细
        function showStockTrades(stockCode) {{
            const stockTrades = tradesData.filter(t => t.stock_code === stockCode);
            
            if (stockTrades.length === 0) {{
                document.getElementById('stockTradesTable').innerHTML = '<div class="no-data">无交易记录</div>';
                return;
            }}
            
            let html = `<table class="trades-table">
                <thead>
                    <tr>
                        <th>日期</th>
                        <th>操作</th>
                        <th>价格</th>
                        <th>数量</th>
                        <th>盈亏</th>
                        <th>原因</th>
                    </tr>
                </thead>
                <tbody>`;
            
            stockTrades.forEach(t => {{
                const actionText = t.action === 'open' ? '买入' : '卖出';
                const actionClass = t.action === 'open' ? 'tag-buy' : 'tag-sell';
                const pnlClass = t.pnl > 0 ? 'pnl-positive' : t.pnl < 0 ? 'pnl-negative' : '';
                const pnlText = t.pnl ? t.pnl.toFixed(2) : '-';
                
                html += `<tr>
                    <td>${{t.date}}</td>
                    <td><span class="tag ${{actionClass}}">${{actionText}}</span></td>
                    <td>${{t.price.toFixed(3)}}</td>
                    <td>${{t.quantity.toLocaleString()}}</td>
                    <td class="${{pnlClass}}">${{pnlText}}</td>
                    <td>${{t.reason || '-'}}</td>
                </tr>`;
            }});
            
            html += '</tbody></table>';
            document.getElementById('stockTradesTable').innerHTML = html;
        }}
        """


def generate_html_report(result_dir: str, output_path: Optional[str] = None) -> str:
    """
    生成 HTML 报告的便捷函数

    Parameters
    ----------
    result_dir : str
        回测结果目录
    output_path : str, optional
        输出文件路径

    Returns
    -------
    str
        生成的 HTML 文件路径
    """
    reporter = HTMLReporter(result_dir)
    return reporter.generate(output_path)


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        result_dir = sys.argv[1]
        output = generate_html_report(result_dir)
        print(f"报告已生成: {output}")
    else:
        print("用法: python html_reporter.py <结果目录>")
