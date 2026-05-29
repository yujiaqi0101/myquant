"""
@deprecated 简化版多因子分层回测 - 已被 multi_factor_quintile_backtest_v2.py 替代
请使用: python -m src.factors.multi_factor_quintile_backtest_v2
"""
import os
import sys
import random
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, r'e:\python_space\myquant')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 批次配置
BATCHES = [
    ('2017-01-01', '2019-12-31', '2020-01-01', '2020-12-31'),
    ('2018-01-01', '2020-12-31', '2021-01-01', '2021-12-31'),
    ('2019-01-01', '2021-12-31', '2022-01-01', '2022-12-31'),
    ('2020-01-01', '2022-12-31', '2023-01-01', '2023-12-31'),
    ('2021-01-01', '2023-12-31', '2024-01-01', '2024-12-31'),
    ('2022-01-01', '2024-12-31', '2025-01-01', '2025-12-31'),
    ('2023-01-01', '2025-12-31', '2026-01-01', '2026-05-19'),
]

FACTOR_IDS = [3, 5, 6, 7, 8, 9, 10, 12, 14, 20]


def run_backtest():
    """运行简化版回测"""
    from src.data.database import DatabaseManager
    from src.factors.backtest import Backtester
    
    db = DatabaseManager(r'e:\python_space\myquant\data\aquant.db')
    output_dir = Path(r'e:\python_space\myquant\reports\backtest\quintile')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    random.seed(42)
    
    all_results = []
    
    for round_id in range(1, 21):
        logger.info(f"\n{'='*60}")
        logger.info(f"第 {round_id}/20 轮")
        logger.info(f"{'='*60}")
        
        # 随机选2-4个因子
        n_factors = random.randint(2, 4)
        selected_factors = random.sample(FACTOR_IDS, n_factors)
        logger.info(f"选中因子: {selected_factors}")
        
        round_result = {
            'round_id': round_id,
            'factors': selected_factors,
            'batches': []
        }
        
        for batch_idx, (train_start, train_end, test_start, test_end) in enumerate(BATCHES, 1):
            logger.info(f"  批次 {batch_idx}/7: {train_start}~{train_end}")
            
            try:
                # 加载数据
                df = db.get_stock_daily(start_date=train_start, end_date=train_end)
                if df.empty:
                    continue
                
                if not isinstance(df.index, pd.MultiIndex):
                    df = df.set_index(['trade_date', 'stock_code'])
                
                # 简化：用收益率作为因子（避免复杂计算）
                close = df['close']
                returns = close.groupby(level='stock_code').pct_change(5)  # 5日收益率
                
                # 清理数据
                returns = returns.replace([np.inf, -np.inf], np.nan).fillna(0)
                
                # 5组分层回测
                bt = Backtester(initial_capital=1000000)
                bt.load_data(df)
                
                # 只回测Q1(top 20%)和Q5(bottom 20%)
                trade_dates = returns.index.get_level_values('trade_date').unique()
                
                q1_returns = []
                q5_returns = []
                
                for date in trade_dates[::5]:  # 每5天调仓
                    day_data = returns.xs(date, level='trade_date')
                    sorted_stocks = day_data.sort_values(ascending=False)
                    n = len(sorted_stocks)
                    
                    if n >= 10:
                        top_stocks = sorted_stocks.iloc[:max(n//5, 5)].index.tolist()
                        bottom_stocks = sorted_stocks.iloc[-max(n//5, 5):].index.tolist()
                        
                        # Q1回测
                        q1_factor = returns[returns.index.get_level_values('stock_code').isin(top_stocks)]
                        if not q1_factor.empty:
                            result = bt.run_backtest(q1_factor, n_stocks=20, rebalance_freq=5, long_short=False)
                            q1_returns.append(result['performance'].get('annual_return', 0))
                        
                        # Q5回测
                        q5_factor = returns[returns.index.get_level_values('stock_code').isin(bottom_stocks)]
                        if not q5_factor.empty:
                            result = bt.run_backtest(q5_factor, n_stocks=20, rebalance_freq=5, long_short=False)
                            q5_returns.append(result['performance'].get('annual_return', 0))
                
                batch_result = {
                    'batch': batch_idx,
                    'q1_return': np.mean(q1_returns) if q1_returns else 0,
                    'q5_return': np.mean(q5_returns) if q5_returns else 0,
                }
                round_result['batches'].append(batch_result)
                
                logger.info(f"    Q1平均收益: {batch_result['q1_return']:.2%}, Q5平均收益: {batch_result['q5_return']:.2%}")
                
            except Exception as e:
                logger.error(f"    批次失败: {e}")
                continue
        
        all_results.append(round_result)
        
        # 生成单轮报告
        generate_round_report(round_result, output_dir)
    
    # 生成综合报告
    generate_summary_report(all_results, output_dir)
    
    logger.info(f"\n完成！报告目录: {output_dir}")


def generate_round_report(result, output_dir):
    """生成单轮HTML报告"""
    round_id = result['round_id']
    factors = result['factors']
    batches = result['batches']
    
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>第{round_id}轮报告</title>
<style>
body{{font-family:Arial;margin:20px;background:#f5f5f5}}
.container{{max-width:1000px;margin:0 auto;background:white;padding:20px}}
h1{{color:#333;border-bottom:2px solid #4CAF50}}
table{{width:100%;border-collapse:collapse;margin:20px 0}}
th,td{{border:1px solid #ddd;padding:10px;text-align:center}}
th{{background:#4CAF50;color:white}}
.positive{{color:green}}.negative{{color:red}}
</style></head>
<body>
<div class="container">
<h1>第{round_id}轮多因子分层回测</h1>
<p>因子: {', '.join([f'alpha_{f:03d}' for f in factors])}</p>
<table>
<tr><th>批次</th><th>Q1(Top 20%)</th><th>Q5(Bottom 20%)</th><th>多空收益</th></tr>
"""
    
    for b in batches:
        long_short = b['q1_return'] - b['q5_return']
        html += f"""
<tr>
<td>批次{b['batch']}</td>
<td class="{'positive' if b['q1_return'] > 0 else 'negative'}">{b['q1_return']:.2%}</td>
<td class="{'positive' if b['q5_return'] > 0 else 'negative'}">{b['q5_return']:.2%}</td>
<td class="{'positive' if long_short > 0 else 'negative'}">{long_short:.2%}</td>
</tr>
"""
    
    html += "</table></div></body></html>"
    
    with open(output_dir / f"round_{round_id:03d}.html", 'w', encoding='utf-8') as f:
        f.write(html)


def generate_summary_report(all_results, output_dir):
    """生成综合报告"""
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>综合报告</title>
<style>
body{{font-family:Arial;margin:20px;background:#f5f5f5}}
.container{{max-width:1000px;margin:0 auto;background:white;padding:20px}}
h1{{color:#333;border-bottom:2px solid #4CAF50}}
table{{width:100%;border-collapse:collapse}}
th,td{{border:1px solid #ddd;padding:10px;text-align:center}}
th{{background:#4CAF50;color:white}}
</style></head>
<body>
<div class="container">
<h1>多因子分层回测综合报告</h1>
<p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<table>
<tr><th>轮次</th><th>因子</th><th>批次</th></tr>
"""
    
    for r in all_results:
        html += f"""
<tr><td>第{r['round_id']}轮</td>
<td>{', '.join([f'alpha_{f:03d}' for f in r['factors']])}</td>
<td>{len(r['batches'])}</td></tr>
"""
    
    html += "</table></div></body></html>"
    
    with open(output_dir / "summary.html", 'w', encoding='utf-8') as f:
        f.write(html)


if __name__ == '__main__':
    run_backtest()
