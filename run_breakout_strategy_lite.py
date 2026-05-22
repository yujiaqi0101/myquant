"""
震荡突破回踩策略 - 回测执行脚本 (轻量版)
============================================

限制股票数量以避免内存问题
"""

import sys
sys.path.insert(0, 'e:/python_space/myquant')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3

from src.strategies.breakout_pullback_strategy import BreakoutPullbackStrategy


# ============================================================
# 配置
# ============================================================

# 回测区间
START_DATE = '2022-01-01'
END_DATE = '2024-12-31'

# 策略参数
STRATEGY_PARAMS = {
    'consolidation_window': 20,
    'breakout_threshold': 0.015,
    'pullback_threshold': 0.01,
    'atr_window': 14,
    'ma_window': 3,
    'max_holding_days': 20,
    'position_size': 0.1,
    'commission_rate': 0.0003,
    'slippage': 0.0001,
}

INITIAL_CAPITAL = 1_000_000
MAX_STOCKS = 200  # 限制股票数量

OUTPUT_DIR = Path('e:/python_space/myquant/reports')


def load_price_data_lite():
    """轻量版数据加载 - 限制股票数量"""
    db_path = 'e:/python_space/myquant/data/aquant.db'
    conn = sqlite3.connect(db_path)
    
    print(f'[数据] 加载 {START_DATE} ~ {END_DATE} 的数据')
    
    # 先获取有完整数据的股票列表
    stock_query = f'''
    SELECT stock_code, COUNT(*) as cnt 
    FROM stock_daily 
    WHERE trade_date BETWEEN ? AND ?
    GROUP BY stock_code
    HAVING cnt > 100
    ORDER BY cnt DESC
    LIMIT {MAX_STOCKS}
    '''
    
    stocks_df = pd.read_sql(stock_query, conn, params=(START_DATE, END_DATE))
    stock_codes = stocks_df['stock_code'].tolist()
    
    print(f'[数据] 选取 {len(stock_codes)} 只股票')
    
    # 分批加载数据避免内存问题
    batch_size = 50
    all_data = []
    
    for i in range(0, len(stock_codes), batch_size):
        batch = stock_codes[i:i+batch_size]
        placeholders = ','.join(['?' for _ in batch])
        
        query = f'''
        SELECT trade_date, stock_code, open, high, low, close, volume
        FROM stock_daily 
        WHERE stock_code IN ({placeholders})
        AND trade_date BETWEEN ? AND ?
        ORDER BY trade_date, stock_code
        '''
        
        batch_df = pd.read_sql(query, conn, params=batch + [START_DATE, END_DATE])
        all_data.append(batch_df)
        print(f'  批次 {i//batch_size + 1}/{(len(stock_codes)-1)//batch_size + 1}: {len(batch_df)} 条')
    
    conn.close()
    
    # 合并数据
    df = pd.concat(all_data, ignore_index=True)
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.set_index(['trade_date', 'stock_code'])
    
    print(f'[数据] 总计: {len(df)} 条记录, {df.index.get_level_values(1).nunique()} 只股票')
    
    return df


def print_report(results: dict, params: dict):
    """打印回测报告"""
    if not results:
        print("\n[结果] 回测无结果")
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


def main():
    print("=" * 60)
    print("震荡突破回踩策略 - 回测系统 (轻量版)")
    print("=" * 60)
    print(f"回测区间: {START_DATE} ~ {END_DATE}")
    print(f"初始资金: {INITIAL_CAPITAL:,.0f}")
    print(f"最大股票数: {MAX_STOCKS}")
    print()

    # 1. 加载数据
    price_data = load_price_data_lite()
    
    if price_data.empty:
        print("[错误] 没有加载到数据！")
        sys.exit(1)

    # 2. 运行回测
    print()
    strategy = BreakoutPullbackStrategy(**STRATEGY_PARAMS)
    results = strategy.run_backtest(price_data, initial_capital=INITIAL_CAPITAL)

    # 3. 输出报告
    print_report(results, STRATEGY_PARAMS)
    save_report(results, STRATEGY_PARAMS)

    print("\n" + "=" * 60)
    print("完成")
    print("=" * 60)

    return results


if __name__ == '__main__':
    main()
