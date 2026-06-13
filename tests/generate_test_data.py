"""
generate_test_data.py - 生成 quantlab 端到端测试需要的股票数据
"""
import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "src")

from src.data.test_data_generator import TestDataGenerator

# 1) 生成股票基本信息（含 list_date / stock_name）
gen = TestDataGenerator(output_dir="data/test_data")
n_stocks = 30
stock_info = gen.generate_stock_info(n_stocks=n_stocks)
print(f"[1/3] Generated {len(stock_info)} stock_info rows")

# 2) 生成日线数据
start = datetime(2023, 1, 1)
end = datetime(2024, 12, 31)
dates = pd.bdate_range(start, end)
print(f"[2/3] Date range: {dates[0].date()} ~ {dates[-1].date()} ({len(dates)} bars)")

# 构造每只股票的日线
records = []
np.random.seed(42)
for _, row in stock_info.iterrows():
    sym = row["stock_code"]
    n = len(dates)
    close = 10.0 + np.cumsum(np.random.randn(n) * 0.02)
    # 控制市场市值在 30~150 亿（适配 small_cap_v2 范围）
    base_mc = np.random.uniform(30, 150) * 1e8
    for i, d in enumerate(dates):
        records.append({
            "trade_date": d.strftime("%Y-%m-%d"),
            "stock_code": sym,
            "open": float(close[i] + np.random.randn() * 0.05),
            "high": float(close[i] + abs(np.random.randn() * 0.1)),
            "low": float(close[i] - abs(np.random.randn() * 0.1)),
            "close": float(close[i]),
            "volume": int(np.random.randint(1_000_000, 10_000_000)),
            "pre_close": float(close[i - 1] if i > 0 else close[i]),
            "amount": float(np.random.randint(50_000_000, 500_000_000)),
            "market_cap": float(base_mc),
        })
stock_daily = pd.DataFrame(records)
print(f"[3/3] Generated {len(stock_daily)} stock_daily rows")

# 3) 写入 CSV
output_dir = Path("data/test_data")
output_dir.mkdir(parents=True, exist_ok=True)
stock_info.to_csv(output_dir / "stock_info.csv", index=False)
stock_daily.to_csv(output_dir / "stock_daily.csv", index=False)
print(f"Wrote to {output_dir}/")
print(f"  - stock_info.csv  ({len(stock_info)} rows)")
print(f"  - stock_daily.csv ({len(stock_daily)} rows)")
