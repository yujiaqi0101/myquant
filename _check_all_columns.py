"""全面检查所有表的列完整性"""
import sqlite3
import sys
sys.path.insert(0, r'd:\python_workspace\myquant\src')

# 从 database.py 读入期望的 CREATE TABLE 定义中所有列名
# 先从代码中读，再对比数据库
conn = sqlite3.connect(r'd:\python_workspace\myquant\data\aquant.db')
c = conn.cursor()

tables_to_check = ['t_stock_daily', 't_etf_daily', 't_index_daily', 't_stock_info', 't_etf_info', 't_index_info', 'financial_data', 't_valuation_data']

for table in tables_to_check:
    c.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in c.fetchall()}
    if not cols:
        print(f"⚠️  {table} 不存在")
        continue
    
    # 尝试获取原始 CREATE TABLE 定义（期望的 schema）
    try:
        c.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
        sql = c.fetchone()
        if sql:
            print(f"\n=== {table} (当前列: {len(cols)}) ===")
            print(f"当前列: {sorted(cols)}")
    except Exception:
        pass

conn.close()
print("\n\n完成，接下来对比代码中的期望列定义")