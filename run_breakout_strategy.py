"""
震荡突破回踩策略 - 回测执行脚本
================================

使用方式：
  python run_breakout_strategy.py

数据来源：
  1. 优先从数据库 (data/aquant.db) 读取
  2. 数据库为空时从 data/test_data/ CSV 读取
  3. CSV 也不存在则报错退出（不再自动生成测试数据）

回测区间：默认最近3年
"""

import sys
sys.path.insert(0, 'e:/python_space/myquant')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from pathlib import Path

from src.data.loader import DataLoader
from src.strategies.breakout_pullback_strategy import BreakoutPullbackStrategy


# ============================================================
# 配置
# ============================================================

# 回测区间（默认最近3年）
END_DATE = datetime.now().strftime('%Y-%m-%d')
START_DATE = (datetime.now() - timedelta(days=3 * 365)).strftime('%Y-%m-%d')

# 策略参数
STRATEGY_PARAMS = {
    'consolidation_window': 20,       # 震荡区间识别窗口（天）
    'breakout_threshold': 0.01,       # 突破确认阈值（1%）
    'pullback_threshold': 0.01,       # 回踩确认阈值（1%）
    'atr_window': 14,                  # ATR计算窗口
    'ma_window': 3,                    # 动态止盈均线窗口（3天）
    'max_holding_days': 20,            # 最大持仓天数
    'position_size': 0.1,              # 单次开仓资金比例（10%）
    'commission_rate': 0.0003,         # 佣金费率（万三）
    'slippage': 0.0001,                # 滑点（万分之一）
}

INITIAL_CAPITAL = 1_000_000  # 初始资金100万

# 输出目录
OUTPUT_DIR = Path('e:/python_space/myquant/reports')


# ============================================================
# 数据加载
# ============================================================

def load_price_data():
    """
    加载价格数据
    优先数据库 → 其次CSV → 都没有则报错
    """
    # 尝试从数据库加载
    try:
        from src.data.database import DatabaseManager
        db_path = Path('e:/python_space/myquant/data/aquant.db')
        if db_path.exists():
            db = DatabaseManager(str(db_path))
            summary = db.get_data_summary()
            count = summary['stock_daily']['count']
            if count > 0:
                print(f"[数据] 从数据库加载: {count} 条记录")
                print(f"        日期范围: {summary['stock_daily']['start_date']} ~ {summary['stock_daily']['end_date']}")
                loader = DataLoader.from_database(str(db_path))
                return loader
    except Exception as e:
        print(f"[数据] 数据库加载失败: {e}")

    # 尝试从CSV加载
    try:
        csv_dir = Path('e:/python_space/myquant/data/test_data')
        if csv_dir.exists():
            loader = DataLoader.from_test_data()
            return loader
    except Exception as e:
        print(f"[数据] CSV加载失败: {e}")

    print("[错误] 没有可用的数据！请先通过QMT同步数据到数据库，或放入CSV测试数据。")
    print("       数据库路径: data/aquant.db")
    print("       CSV路径:   data/test_data/stock_daily.csv")
    sys.exit(1)


# ============================================================
# 报告生成
# ============================================================

def print_report(results: dict, params: dict):
    """打印回测报告"""
    if not results:
        print("\n[结果] 回测无结果（可能数据不足或无交易信号）")
        return

    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)

    print("\n【策略参数】")
    for k, v in params.items():
        print(f"  {k}: {v}")

    print("\n【绩效指标】")
    print(f"  初始资金:     {results['initial_capital']:>15,.0f}")
    print(f"  最终资金:     {results['final_value']:>15,.0f}")
    print(f"  总收益率:     {results['total_return']:>14.2%}")
    print(f"  年化收益率:   {results['annual_return']:>14.2%}")
    print(f"  年化波动率:   {results['annual_volatility']:>14.2%}")
    print(f"  夏普比率:     {results['sharpe_ratio']:>14.2f}")
    print(f"  最大回撤:     {results['max_drawdown']:>14.2%}")
    print(f"  卡玛比率:     {results['calmar_ratio']:>14.2f}")
    print(f"  日胜率:       {results['win_rate']:>14.2%}")
    print(f"  盈亏比:       {results['profit_loss_ratio']:>14.2f}")

    print("\n【交易统计】")
    print(f"  开仓次数:     {results['n_trades']}")
    print(f"  平仓次数:     {results['n_close']}")
    print(f"  交易胜率:     {results['trade_win_rate']:.2%}")
    print(f"  平均盈亏:     {results['avg_pnl']:>14,.2f}")
    print(f"  总盈亏:       {results['total_pnl']:>14,.2f}")

    # 年度收益
    print("\n【年度收益】")
    values_df = results['values_df']
    values_df['year'] = values_df.index.year
    for year in sorted(values_df['year'].unique()):
        yd = values_df[values_df['year'] == year]
        if len(yd) > 1:
            yr = yd['total_value'].iloc[-1] / yd['total_value'].iloc[0] - 1
            print(f"  {year}年: {yr:>10.2%}  ({len(yd)}个交易日)")


def save_report(results: dict, params: dict):
    """保存报告文件"""
    if not results:
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. 净值曲线 CSV
    values_file = OUTPUT_DIR / f"breakout_values_{ts}.csv"
    results['values_df'].to_csv(values_file, encoding='utf-8-sig')

    # 2. 交易记录 CSV
    trades_df = results['trades_df']
    trades_file = None
    if not trades_df.empty:
        trades_file = OUTPUT_DIR / f"breakout_trades_{ts}.csv"
        trades_df.to_csv(trades_file, index=False, encoding='utf-8-sig')

    # 3. 绩效 JSON
    report = {
        'strategy': '震荡突破回踩策略',
        'period': {
            'start': str(results['values_df'].index[0].date()),
            'end': str(results['values_df'].index[-1].date()),
            'days': len(results['values_df']),
        },
        'params': params,
        'performance': {k: v for k, v in results.items() if k not in ('values_df', 'trades_df')},
    }
    report_file = OUTPUT_DIR / f"breakout_report_{ts}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    # 4. HTML 可视化报告
    html_file = OUTPUT_DIR / f"breakout_report_{ts}.html"
    _generate_html(results, params, ts, html_file)

    print(f"\n[输出] 净值曲线: {values_file}")
    if trades_file:
        print(f"[输出] 交易记录: {trades_file}")
    print(f"[输出] 绩效报告: {report_file}")
    print(f"[输出] 可视化:   {html_file}")


def _generate_html(results: dict, params: dict, ts: str, filepath: Path):
    """生成 HTML 可视化报告"""
    vdf = results['values_df']
    dates = vdf.index.strftime('%Y-%m-%d').tolist()
    values = [round(x, 2) for x in vdf['total_value'].tolist()]
    dd = ((vdf['total_value'] - vdf['total_value'].cummax()) / vdf['total_value'].cummax() * 100).tolist()

    html = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>震荡突破回踩策略回测报告</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;margin:0;padding:20px;background:#f5f5f5}}
.box{{max-width:1400px;margin:0 auto;background:#fff;padding:30px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
h1{{color:#333;text-align:center;margin-bottom:10px}}
.sub{{text-align:center;color:#999;margin-bottom:30px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin-bottom:30px}}
.card{{padding:20px;border-radius:8px;color:#fff;text-align:center}}
.card.a{{background:linear-gradient(135deg,#667eea,#764ba2)}}
.card.b{{background:linear-gradient(135deg,#4facfe,#00f2fe)}}
.card.c{{background:linear-gradient(135deg,#f093fb,#f5576c)}}
.card .l{{font-size:12px;opacity:.9}}
.card .v{{font-size:24px;font-weight:bold;margin-top:5px}}
.chart{{width:100%;height:400px;margin-bottom:20px}}
table{{width:100%;border-collapse:collapse;margin-top:10px}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #eee}}
th{{background:#f8f9fa;font-weight:600}}
.green{{color:#52c41a}} .red{{color:#f5222d}}
</style></head><body><div class="box">
<h1>震荡突破回踩策略回测报告</h1>
<p class="sub">{vdf.index[0].date()} ~ {vdf.index[-1].date()} | {len(vdf)} 个交易日</p>
<div class="cards">
  <div class="card {'c' if results['total_return']<0 else 'a'}"><div class="l">总收益率</div><div class="v">{results['total_return']:.2%}</div></div>
  <div class="card {'c' if results['annual_return']<0 else 'a'}"><div class="l">年化收益率</div><div class="v">{results['annual_return']:.2%}</div></div>
  <div class="card b"><div class="l">夏普比率</div><div class="v">{results['sharpe_ratio']:.2f}</div></div>
  <div class="card c"><div class="l">最大回撤</div><div class="v">{results['max_drawdown']:.2%}</div></div>
</div>
<div id="eq" class="chart"></div>
<div id="dd" class="chart"></div>
<h3>详细指标</h3>
<table>
<tr><th>指标</th><th>数值</th><th>指标</th><th>数值</th></tr>
<tr><td>初始资金</td><td>{results['initial_capital']:,.0f}</td><td>最终资金</td><td>{results['final_value']:,.0f}</td></tr>
<tr><td>年化波动率</td><td>{results['annual_volatility']:.2%}</td><td>卡玛比率</td><td>{results['calmar_ratio']:.2f}</td></tr>
<tr><td>日胜率</td><td>{results['win_rate']:.2%}</td><td>盈亏比</td><td>{results['profit_loss_ratio']:.2f}</td></tr>
<tr><td>开仓次数</td><td>{results['n_trades']}</td><td>交易胜率</td><td>{results['trade_win_rate']:.2%}</td></tr>
<tr><td>平均盈亏</td><td class="{'green' if results['avg_pnl']>0 else 'red'}">{results['avg_pnl']:,.2f}</td><td>总盈亏</td><td class="{'green' if results['total_pnl']>0 else 'red'}">{results['total_pnl']:,.2f}</td></tr>
</table>
<h3 style="margin-top:20px">策略参数</h3>
<table>
<tr><th>参数</th><th>值</th><th>参数</th><th>值</th></tr>
<tr><td>震荡区间窗口</td><td>{params['consolidation_window']}天</td><td>突破阈值</td><td>{params['breakout_threshold']:.2%}</td></tr>
<tr><td>回踩阈值</td><td>{params['pullback_threshold']:.2%}</td><td>ATR窗口</td><td>{params['atr_window']}天</td></tr>
<tr><td>止盈均线窗口</td><td>{params['ma_window']}天</td><td>最大持仓天数</td><td>{params['max_holding_days']}天</td></tr>
<tr><td>单次仓位</td><td>{params['position_size']:.0%}</td><td>佣金+滑点</td><td>{(params['commission_rate']+params['slippage'])*10000:.1f}‱</td></tr>
</table>
</div>
<script>
var dates={dates},vals={values},dds={dd};
var eq=echarts.init(document.getElementById('eq'));
eq.setOption({{title:{{text:'净值曲线',left:'center'}},tooltip:{{trigger:'axis'}},
  xAxis:{{type:'category',data:dates,boundaryGap:false}},
  yAxis:{{axisLabel:{{formatter:function(v){{return(v/10000).toFixed(0)+'万'}}}}}},
  series:[{{type:'line',data:vals,smooth:true,lineStyle:{{color:'#667eea',width:2}},
    areaStyle:{{color:new echarts.graphic.LinearGradient(0,0,0,1,[{{offset:0,color:'rgba(102,126,234,.3)'}},{{offset:1,color:'rgba(102,126,234,.05)'}}])}}}}]}}
);
var dd2=echarts.init(document.getElementById('dd'));
dd2.setOption({{title:{{text:'回撤曲线',left:'center'}},tooltip:{{trigger:'axis'}},
  xAxis:{{type:'category',data:dates,boundaryGap:false}},
  yAxis:{{axisLabel:{{formatter:'{{value}}%'}}}},
  series:[{{type:'line',data:dds,smooth:true,lineStyle:{{color:'#f5576c',width:2}},
    areaStyle:{{color:new echarts.graphic.LinearGradient(0,0,0,1,[{{offset:0,color:'rgba(245,87,108,.3)'}},{{offset:1,color:'rgba(245,87,108,.05)'}}])}}}}]}}
);
window.onresize=function(){{eq.resize();dd2.resize()}};
</script></body></html>'''

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html)


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 60)
    print("震荡突破回踩策略 - 回测系统")
    print("=" * 60)
    print(f"回测区间: {START_DATE} ~ {END_DATE}")
    print(f"初始资金: {INITIAL_CAPITAL:,.0f}")
    print()

    # 1. 加载数据
    loader = load_price_data()

    # 2. 获取价格数据
    price_data = loader.get_price_data(start_date=START_DATE, end_date=END_DATE)
    if price_data.empty:
        print("[错误] 指定日期范围内没有数据！请检查数据是否覆盖该区间。")
        sys.exit(1)

    print(f"[数据] 记录数: {len(price_data)}")
    print(f"[数据] 股票数: {price_data.index.get_level_values('stock_code').nunique()}")
    print(f"[数据] 日期范围: {price_data.index.get_level_values('trade_date').min().date()} ~ {price_data.index.get_level_values('trade_date').max().date()}")

    # 3. 运行回测
    print()
    strategy = BreakoutPullbackStrategy(**STRATEGY_PARAMS)
    results = strategy.run_backtest(price_data, initial_capital=INITIAL_CAPITAL)

    # 4. 输出报告
    print_report(results, STRATEGY_PARAMS)
    save_report(results, STRATEGY_PARAMS)

    print("\n" + "=" * 60)
    print("完成")
    print("=" * 60)

    return results


if __name__ == '__main__':
    main()
