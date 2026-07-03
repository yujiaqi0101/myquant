"""调试：检查5年回测的信号分布"""
import sys
sys.path.insert(0, '.')

from config.config import DATABASE_CONFIG
from src.quantlab_adapters.data_adapter import from_etf_db
import importlib

# 加载5年数据
data = from_etf_db(
    db_path=DATABASE_CONFIG['path'],
    start_date="2021-03-01",
    end_date="2026-06-28",
    etf_codes=["510050.SH", "510300.SH", "510500.SH"],
)
print(f"加载 {len(data)} 只 ETF")
for sym, df in data.items():
    print(f"  {sym}: {len(df)} 行, 日期范围 {df.index[0].date()} ~ {df.index[-1].date()}")

# 加载策略
mod = importlib.import_module("src.strategies.8b3c1d07.style_rotation_etf_v1")
strategy = mod.StyleRotationEtfV1(momentum_period=20, rebalance_at="month_start", top_n=1)

# 构造 ctx
class Ctx:
    pass
ctx = Ctx()
ctx.data = data

# 生成信号
signal = strategy.signal(ctx)
print(f"\n信号形状: {signal.shape}")

# 查看调仓日的信号
rebalance_dates = strategy._get_rebalance_dates(signal.index)
print(f"调仓日数量: {len(rebalance_dates)}")

# 统计调仓日的正收益信号
positive_count = 0
negative_count = 0
zero_count = 0
for d in rebalance_dates:
    row = signal.loc[d]
    non_nan = row.dropna()
    if len(non_nan) == 0:
        continue
    pos = (non_nan > 0).sum()
    neg = (non_nan < 0).sum()
    zer = (non_nan == 0).sum()
    if pos > 0:
        positive_count += 1
    elif neg > 0 and pos == 0:
        negative_count += 1
    else:
        zero_count += 1

print(f"\n调仓日信号统计:")
print(f"  有正收益信号的调仓日: {positive_count}")
print(f"  全负收益的调仓日: {negative_count}")
print(f"  全零的调仓日: {zero_count}")

# 打印前10个有正收益的调仓日
print(f"\n前10个有正收益的调仓日:")
count = 0
for d in rebalance_dates:
    row = signal.loc[d]
    non_nan = row.dropna()
    if len(non_nan) == 0:
        continue
    pos = non_nan[non_nan > 0]
    if len(pos) > 0:
        print(f"  {d.date()}: 正收益 {dict(pos)}")
        count += 1
        if count >= 10:
            break
