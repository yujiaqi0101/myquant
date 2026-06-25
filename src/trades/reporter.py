"""
交易记录报表生成器
==================

复用现有 HTMLReporter 报表引擎，将导入的交易记录转换为报表引擎所需的 JSON 结构，
然后调用 HTMLReporter 生成可视化 HTML 报表。
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional

import pandas as pd

from .models import TradeRecord
from .repository import TradeRepository

logger = logging.getLogger(__name__)


class TradeReporter:
    """
    交易记录报表生成器

    将交易记录转换为 HTMLReporter 所需的 JSON 结构并生成报表。

    HTMLReporter 读取三个 JSON 文件：
    - performance.json: 汇总指标
    - trades.json: 交易记录列表
    - snapshots.json: 每日快照

    本类负责将交易记录转换为这些 JSON 文件，然后调用 HTMLReporter.generate()。
    """

    def __init__(self, db_manager):
        """
        Parameters
        ----------
        db_manager : DatabaseManager
            数据库管理器实例
        """
        self.db = db_manager
        self.repo = TradeRepository(db_manager)

    def generate_report(
        self,
        output_dir: str,
        broker: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """
        生成 HTML 报表

        Parameters
        ----------
        output_dir : str
            报表输出目录
        broker : str, optional
            按券商筛选
        start_date : str, optional
            起始日期 YYYY-MM-DD
        end_date : str, optional
            结束日期 YYYY-MM-DD

        Returns
        -------
        str
            生成的 HTML 文件路径
        """
        # 查询交易记录
        df = self.repo.get_records(broker=broker, start_date=start_date, end_date=end_date)

        if df.empty:
            raise ValueError("没有可用的交易记录，请先导入数据")

        # 创建输出目录
        result_dir = Path(output_dir)
        result_dir.mkdir(parents=True, exist_ok=True)

        # 生成 JSON 文件
        self._write_performance_json(result_dir, df)
        self._write_trades_json(result_dir, df)
        self._write_snapshots_json(result_dir, df)

        # 复用现有 HTMLReporter 引擎生成报表
        from src.report.html_reporter import HTMLReporter
        reporter = HTMLReporter(str(result_dir))

        # 覆盖 _build_header 以显示交易记录报表标题
        html = self._build_custom_html(result_dir, df)

        output_path = result_dir / 'trade_report.html'
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        logger.info(f"报表已生成: {output_path}")
        return str(output_path)

    def _write_performance_json(self, result_dir: Path, df: pd.DataFrame):
        """生成 performance.json - 汇总指标"""
        total_trades = len(df)
        buy_df = df[df['trade_type'] == 'buy']
        sell_df = df[df['trade_type'] == 'sell']

        total_buy_amount = float(buy_df['amount'].sum()) if not buy_df.empty else 0
        total_sell_amount = float(sell_df['amount'].sum()) if not sell_df.empty else 0
        total_fee = float(df['total_fee'].sum()) if 'total_fee' in df.columns else 0
        net_amount = float(df['net_amount'].sum()) if 'net_amount' in df.columns else 0

        # 按股票统计
        stock_stats = df.groupby('stock_code').agg(
            buy_amount=('amount', lambda x: x[df.loc[x.index, 'trade_type'] == 'buy'].sum()),
            sell_amount=('amount', lambda x: x[df.loc[x.index, 'trade_type'] == 'sell'].sum()),
            trade_count=('amount', 'count'),
            total_fee=('total_fee', 'sum'),
        ).reset_index()

        performance = {
            'strategy_name': '历史交易记录分析',
            'start_date': str(df['trade_date'].min()),
            'end_date': str(df['trade_date'].max()),
            'total_return': net_amount / total_buy_amount if total_buy_amount > 0 else 0,
            'annual_return': 0,  # 历史记录无法计算年化
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'win_rate': 0,
            'total_trades': total_trades,
            'initial_capital': total_buy_amount,
            'final_value': total_buy_amount + net_amount,
            'annual_volatility': 0,
            # 交易记录特有指标
            'total_buy_amount': total_buy_amount,
            'total_sell_amount': total_sell_amount,
            'total_fee': total_fee,
            'net_amount': net_amount,
            'buy_count': len(buy_df),
            'sell_count': len(sell_df),
            'stock_count': df['stock_code'].nunique(),
            'broker': ', '.join(df['broker'].dropna().unique()) if 'broker' in df.columns else '',
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

        with open(result_dir / 'performance.json', 'w', encoding='utf-8') as f:
            json.dump(performance, f, ensure_ascii=False, indent=2)

    def _write_trades_json(self, result_dir: Path, df: pd.DataFrame):
        """生成 trades.json - 交易记录列表"""
        trades = []
        for _, row in df.iterrows():
            trades.append({
                'date': str(row['trade_date']),
                'time': str(row.get('trade_time', '')),
                'stock_code': str(row['stock_code']),
                'stock_name': str(row.get('stock_name', '')),
                'action': 'open' if row['trade_type'] == 'buy' else 'close',
                'trade_type': str(row['trade_type']),
                'price': float(row['price']),
                'quantity': float(row['quantity']),
                'amount': float(row['amount']),
                'commission': float(row.get('commission', 0)),
                'total_fee': float(row.get('total_fee', 0)),
                'net_amount': float(row.get('net_amount', 0)),
                'pnl': float(row.get('net_amount', 0)) if row['trade_type'] == 'sell' else 0,
                'reason': str(row.get('broker', '')),
            })

        with open(result_dir / 'trades.json', 'w', encoding='utf-8') as f:
            json.dump(trades, f, ensure_ascii=False, indent=2)

    def _write_snapshots_json(self, result_dir: Path, df: pd.DataFrame):
        """生成 snapshots.json - 每日资金快照"""
        # 按日期聚合
        df['trade_date'] = df['trade_date'].astype(str)
        daily = df.groupby('trade_date').agg(
            buy_amount=('amount', lambda x: x[df.loc[x.index, 'trade_type'] == 'buy'].sum()),
            sell_amount=('amount', lambda x: x[df.loc[x.index, 'trade_type'] == 'sell'].sum()),
            daily_fee=('total_fee', 'sum'),
            net_amount=('net_amount', 'sum'),
            trade_count=('amount', 'count'),
        ).reset_index().sort_values('trade_date')

        # 累计现金流
        daily['cumulative_net'] = daily['net_amount'].cumsum()
        daily['cumulative_buy'] = daily['buy_amount'].cumsum()
        daily['cumulative_sell'] = daily['sell_amount'].cumsum()

        snapshots = []
        for _, row in daily.iterrows():
            snapshots.append({
                'date': str(row['trade_date']),
                'cash_flow': float(row['net_amount']),
                'cumulative_net': float(row['cumulative_net']),
                'buy_amount': float(row['buy_amount']),
                'sell_amount': float(row['sell_amount']),
                'daily_fee': float(row['daily_fee']),
                'trade_count': int(row['trade_count']),
                'equity': float(row['cumulative_net']),
            })

        with open(result_dir / 'snapshots.json', 'w', encoding='utf-8') as f:
            json.dump(snapshots, f, ensure_ascii=False, indent=2)

    def _build_custom_html(self, result_dir: Path, df: pd.DataFrame) -> str:
        """
        构建自定义 HTML 报表

        复用 HTMLReporter 的 CSS 样式体系，但针对交易记录特点定制内容：
        - 汇总指标卡片（总交易数、买卖金额、费用、净额）
        - 现金流走势图
        - 交易记录明细表
        - 按股票汇总统计
        """
        # 加载 JSON 数据
        with open(result_dir / 'performance.json', 'r', encoding='utf-8') as f:
            perf = json.load(f)
        with open(result_dir / 'trades.json', 'r', encoding='utf-8') as f:
            trades = json.load(f)
        with open(result_dir / 'snapshots.json', 'r', encoding='utf-8') as f:
            snapshots = json.load(f)

        return self._render_html(perf, trades, snapshots, df)

    def _render_html(self, perf: dict, trades: list, snapshots: list, df: pd.DataFrame) -> str:
        """渲染完整 HTML"""
        # 按股票汇总
        stock_summary = df.groupby(['stock_code', 'stock_name']).agg(
            buy_amount=('amount', lambda x: x[df.loc[x.index, 'trade_type'] == 'buy'].sum()),
            sell_amount=('amount', lambda x: x[df.loc[x.index, 'trade_type'] == 'sell'].sum()),
            buy_qty=('quantity', lambda x: x[df.loc[x.index, 'trade_type'] == 'buy'].sum()),
            sell_qty=('quantity', lambda x: x[df.loc[x.index, 'trade_type'] == 'sell'].sum()),
            total_fee=('total_fee', 'sum'),
            trade_count=('amount', 'count'),
        ).reset_index()

        net_amount = perf['net_amount']
        net_class = 'positive' if net_amount > 0 else 'negative' if net_amount < 0 else ''

        # 构建 HTML
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>历史交易记录报表 - {perf.get('broker', '')}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        {self._get_css()}
    </style>
</head>
<body>
    <div class="container">
        {self._render_header(perf)}
        {self._render_summary(perf, net_class)}
        {self._render_cashflow_chart(snapshots)}
        {self._render_trades_table(trades)}
        {self._render_stock_summary(stock_summary)}
    </div>
    <script>
        {self._render_javascript(snapshots)}
    </script>
</body>
</html>"""

    def _get_css(self) -> str:
        """复用 HTMLReporter 的 CSS 样式体系"""
        return """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f7fa; color: #333; line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; padding: 30px; border-radius: 12px;
            margin-bottom: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .header h1 { font-size: 28px; margin-bottom: 10px; }
        .header .subtitle { opacity: 0.9; font-size: 14px; }
        .card {
            background: white; border-radius: 12px; padding: 24px;
            margin-bottom: 24px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        .card-title {
            font-size: 18px; font-weight: 600; margin-bottom: 20px;
            color: #1a1a2e; border-left: 4px solid #667eea; padding-left: 12px;
        }
        .metrics-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px;
        }
        .metric-item { background: #f8f9fa; padding: 16px; border-radius: 8px; text-align: center; }
        .metric-label { font-size: 12px; color: #666; margin-bottom: 4px; }
        .metric-value { font-size: 24px; font-weight: 600; color: #1a1a2e; }
        .metric-value.positive { color: #f5222d; }
        .metric-value.negative { color: #52c41a; }
        .chart-container { position: relative; height: 400px; margin: 20px 0; }
        .trades-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .trades-table th, .trades-table td {
            padding: 12px; text-align: left; border-bottom: 1px solid #e8e8e8;
        }
        .trades-table th {
            background: #f8f9fa; font-weight: 600; color: #666; position: sticky; top: 0;
        }
        .trades-table tr:hover { background: #f8f9fa; }
        .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
        .tag-buy { background: #fff1f0; color: #f5222d; border: 1px solid #ffa39e; }
        .tag-sell { background: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }
        .table-container { max-height: 500px; overflow-y: auto; border-radius: 8px; border: 1px solid #e8e8e8; }
        .info-row { display: flex; gap: 24px; margin-bottom: 12px; flex-wrap: wrap; }
        .info-item { display: flex; align-items: center; gap: 8px; }
        .info-label { color: #666; font-size: 13px; }
        .info-value { font-weight: 500; color: #1a1a2e; }
        .pnl-positive { color: #f5222d; }
        .pnl-negative { color: #52c41a; }
        """

    def _render_header(self, perf: dict) -> str:
        """渲染头部"""
        broker = perf.get('broker', '未知')
        date_range = perf.get('date_range', '')
        return f"""
        <div class="header">
            <h1>📊 历史交易记录报表</h1>
            <div class="subtitle">
                券商: {broker} |
                交易区间: {perf.get('start_date', '-')} ~ {perf.get('end_date', '-')} |
                生成时间: {perf.get('generated_at', '')}
            </div>
        </div>"""

    def _render_summary(self, perf: dict, net_class: str) -> str:
        """渲染汇总卡片"""
        return f"""
        <div class="card">
            <div class="card-title">交易汇总</div>
            <div class="metrics-grid">
                <div class="metric-item">
                    <div class="metric-label">总交易笔数</div>
                    <div class="metric-value">{perf['total_trades']}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">买入笔数</div>
                    <div class="metric-value">{perf['buy_count']}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">卖出笔数</div>
                    <div class="metric-value">{perf['sell_count']}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">交易股票数</div>
                    <div class="metric-value">{perf['stock_count']}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">买入总额</div>
                    <div class="metric-value">¥{perf['total_buy_amount']:,.2f}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">卖出总额</div>
                    <div class="metric-value">¥{perf['total_sell_amount']:,.2f}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">总手续费</div>
                    <div class="metric-value">¥{perf['total_fee']:,.2f}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">净现金流</div>
                    <div class="metric-value {net_class}">¥{perf['net_amount']:,.2f}</div>
                </div>
            </div>
        </div>"""

    def _render_cashflow_chart(self, snapshots: list) -> str:
        """渲染现金流图表"""
        if not snapshots:
            return ""
        return """
        <div class="card">
            <div class="card-title">现金流走势</div>
            <div class="chart-container">
                <canvas id="cashflowChart"></canvas>
            </div>
        </div>"""

    def _render_trades_table(self, trades: list) -> str:
        """渲染交易记录表"""
        if not trades:
            return ""

        rows = []
        for t in trades:
            action_class = "tag-buy" if t.get('action') == 'open' else "tag-sell"
            action_text = "买入" if t.get('action') == 'open' else "卖出"
            pnl = t.get('pnl', 0)
            pnl_class = "pnl-positive" if pnl > 0 else "pnl-negative" if pnl < 0 else ""
            pnl_text = f"¥{pnl:+,.2f}" if pnl != 0 else "-"

            rows.append(f"""
                <tr>
                    <td>{t.get('date', '-')}</td>
                    <td>{t.get('time', '')}</td>
                    <td>{t.get('stock_code', '-')}</td>
                    <td>{t.get('stock_name', '-')}</td>
                    <td><span class="tag {action_class}">{action_text}</span></td>
                    <td>{t.get('price', 0):.3f}</td>
                    <td>{t.get('quantity', 0):,.0f}</td>
                    <td>¥{t.get('amount', 0):,.2f}</td>
                    <td>¥{t.get('total_fee', 0):,.2f}</td>
                    <td class="{pnl_class}">{pnl_text}</td>
                </tr>""")

        return f"""
        <div class="card">
            <div class="card-title">交易明细 ({len(trades)} 笔)</div>
            <div class="table-container">
                <table class="trades-table">
                    <thead>
                        <tr>
                            <th>日期</th><th>时间</th><th>代码</th><th>名称</th>
                            <th>操作</th><th>价格</th><th>数量</th>
                            <th>金额</th><th>费用</th><th>净额</th>
                        </tr>
                    </thead>
                    <tbody>{''.join(rows)}</tbody>
                </table>
            </div>
        </div>"""

    def _render_stock_summary(self, stock_df: pd.DataFrame) -> str:
        """渲染按股票汇总表"""
        if stock_df.empty:
            return ""

        rows = []
        for _, row in stock_df.iterrows():
            net = float(row['sell_amount']) - float(row['buy_amount'])
            net_class = "pnl-positive" if net > 0 else "pnl-negative" if net < 0 else ""
            name = row.get('stock_name', '')
            code = row['stock_code']
            display = f"{code} {name}" if name else code

            rows.append(f"""
                <tr>
                    <td>{display}</td>
                    <td>{int(row['trade_count'])}</td>
                    <td>¥{float(row['buy_amount']):,.2f}</td>
                    <td>{float(row['buy_qty']):,.0f}</td>
                    <td>¥{float(row['sell_amount']):,.2f}</td>
                    <td>{float(row['sell_qty']):,.0f}</td>
                    <td>¥{float(row['total_fee']):,.2f}</td>
                    <td class="{net_class}">¥{net:+,.2f}</td>
                </tr>""")

        return f"""
        <div class="card">
            <div class="card-title">按股票汇总 ({len(stock_df)} 只)</div>
            <div class="table-container">
                <table class="trades-table">
                    <thead>
                        <tr>
                            <th>证券</th><th>交易笔数</th>
                            <th>买入金额</th><th>买入数量</th>
                            <th>卖出金额</th><th>卖出数量</th>
                            <th>总费用</th><th>净额</th>
                        </tr>
                    </thead>
                    <tbody>{''.join(rows)}</tbody>
                </table>
            </div>
        </div>"""

    def _render_javascript(self, snapshots: list) -> str:
        """渲染 JavaScript（现金流图表）"""
        if not snapshots:
            return ""

        dates = [s['date'] for s in snapshots]
        cum_net = [s['cumulative_net'] for s in snapshots]
        daily_flow = [s['cash_flow'] for s in snapshots]

        return f"""
        const ctx = document.getElementById('cashflowChart').getContext('2d');
        new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(dates)},
                datasets: [
                    {{
                        label: '每日现金流',
                        data: {json.dumps(daily_flow)},
                        backgroundColor: daily_flow.map(v => v >= 0 ? 'rgba(245,34,45,0.5)' : 'rgba(82,196,26,0.5)'),
                        borderColor: daily_flow.map(v => v >= 0 ? '#f5222d' : '#52c41a'),
                        borderWidth: 1,
                        yAxisID: 'y'
                    }},
                    {{
                        label: '累计现金流',
                        type: 'line',
                        data: {json.dumps(cum_net)},
                        borderColor: '#1890ff',
                        backgroundColor: 'rgba(24,144,255,0.1)',
                        fill: true,
                        tension: 0.1,
                        yAxisID: 'y1'
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{ ticks: {{ maxTicksLimit: 20 }} }},
                    y: {{
                        type: 'linear',
                        position: 'left',
                        title: {{ display: true, text: '每日现金流 (¥)' }}
                    }},
                    y1: {{
                        type: 'linear',
                        position: 'right',
                        title: {{ display: true, text: '累计现金流 (¥)' }},
                        grid: {{ drawOnChartArea: false }}
                    }}
                }},
                plugins: {{
                    tooltip: {{
                        callbacks: {{
                            label: function(ctx) {{
                                return ctx.dataset.label + ': ¥' + ctx.parsed.y.toLocaleString('zh-CN', {{
                                    minimumFractionDigits: 2, maximumFractionDigits: 2
                                }});
                            }}
                        }}
                    }}
                }}
            }}
        }});
        """
