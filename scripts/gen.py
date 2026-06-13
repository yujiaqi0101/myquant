# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')

pool_path = r'D:\python_workspace\myquant\docs\stock_pool_code.txt'
main_path = r'D:\python_workspace\AI生成的量化策略\东财策略\5743b356-624b-11f1-ac80-30c59923a9df\main.py'

with open(pool_path, 'r', encoding='utf-8') as f:
    pool_code = f.read()

with open(main_path, 'r', encoding='utf-8') as f:
    orig_lines = f.readlines()

header = '''# coding=utf-8
"""索罗斯趋势投机策略 - 试探+正反馈+三级共振权重（限定股票池版本）

限定股票池版本：所有选股、排序、交易均限定在附件448只股票池内。
股票池来源：docs/股票与ETF清单.xlsx
"""
from __future__ import print_function, absolute_import
from gm.api import *
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

TOP_N, REB_FREQ, MIN_DAYS, LOOKBACK = 20, 5, 60, 80

# ========== 448只限定股票池（掘金symbol格式） ==========
# 由 docs/股票与ETF清单.xlsx 导出
STOCK_POOL_448 = None
'''

def_init = '''
def init(context):
    context.top_n = TOP_N; context.reb_freq = REB_FREQ
    context.min_days = MIN_DAYS; context.lookback = LOOKBACK
    context.last_reb = None; context.day_cnt = 0; context.exposure = 1.0
    _load_stock_pool(context)
    schedule(schedule_func=algo, date_rule='1d', time_rule='14:50:00')
'''

def_algo = '''
def algo(context):
    today = context.now.strftime('%Y-%m-%d')
    context.day_cnt += 1
    _soros_check(context, today)
    if context.last_reb is None or context.day_cnt - context.last_reb >= context.reb_freq:
        context.last_reb = context.day_cnt
        _rebalance(context, today)
'''

def_rebalance = '''
def _rebalance(context, today):
    pool = _stock_pool(today, context)
    if pool is None or len(pool) == 0: return
    syms = pool['symbol'].tolist()
    hist = _batch_history(syms, today, context.lookback)
    if hist is None or len(hist) == 0: return
    state = _market_state(today)
    context.exposure = {'bull':1.0,'neutral':0.7,'bear':0.4}[state]
    scores = _score_stocks(hist, syms)
    targets = _rank_select(scores, hist, context.top_n)
    _do_trade(context, targets, today)
'''

new_funcs = '''
def _load_stock_pool(context):
    """加裁448只限定股票池"""
    global STOCK_POOL_448
    if STOCK_POOL_448 is not None:
        context.stock_pool = STOCK_POOL_448
        return
    STOCK_POOL_448 = [
''' + pool_code.rstrip().rstrip(',') + '''
    ]
    context.stock_pool = STOCK_POOL_448

def _stock_pool(today, context):
    """从448只限定股票池中，通过掘金API验证状态并筛选。

    验证项目：
    1. 是否在交易日期内可交易（skip_st=True, skip_suspended=True）
    2. 上市天数 >= min_days
    返回: DataFrame，列包含 symbol / listed_date / days 等
    """
    min_days = context.min_days
    pool = context.stock_pool
    if not pool:
        return None
    all_syms = ",".join(pool)
    try:
        df = get_symbols(sec_type1=1010, sec_type2=101001, exchanges="SHSE,SZSE",
                         skip_st=True, skip_suspended=True, trade_date=today,
                         symbols=all_syms, df=True)
    except Exception:
        df = get_symbols(sec_type1=1010, sec_type2=101001, exchanges="SHSE,SZSE",
                         skip_st=True, skip_suspended=True, trade_date=today, df=True)
        if df is not None and len(df) > 0:
            df = df[df["symbol"].isin(pool)]
    if df is None or len(df) == 0:
        return None
    df["ldate"] = pd.to_datetime(df["listed_date"]).dt.tz_localize(None)
    df["days"] = (pd.to_datetime(today) - df["ldate"]).dt.days
    df = df[df["days"] >= min_days]
    return df if len(df) > 0 else None
'''

# Find where tail funcs start (after _stock_pool)
tail_start = None
for i, ln in enumerate(orig_lines):
    if 'def _batch_history(' in ln:
        tail_start = i
        break

tail = ''.join(orig_lines[tail_start:])

result = header + def_init + def_algo + def_rebalance + new_funcs + tail

with open(main_path, 'w', encoding='utf-8') as f:
    f.write(result)

print(f'OK - {len(result.splitlines())} lines written')
