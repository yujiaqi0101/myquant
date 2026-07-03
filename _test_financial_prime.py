"""测试财务主要指标同步 - 取前20只股票，近3个月"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from datetime import datetime, timedelta
from src.data.database import DatabaseManager
from src.data.data_sync import DataSynchronizer

today = datetime.now()
start_date = (today - timedelta(days=92)).strftime('%Y%m%d')
end_date = today.strftime('%Y%m%d')
print(f"日期范围: {start_date} -> {end_date}")

db = DatabaseManager(os.path.join(os.path.dirname(__file__), 'data', 'aquant.db'))
sync = DataSynchronizer(db)

# 读取股票列表
import sqlite3
conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'aquant.db'))
c = conn.cursor()
c.execute("SELECT DISTINCT sec_id FROM t_stock_info WHERE sec_id IS NOT NULL LIMIT 20")
stock_list = [r[0] for r in c.fetchall() if r[0]]
conn.close()
print(f"测试股票数量: {len(stock_list)} 只")

# 同步财务数据
print("\n--- 同步财务主要指标 ---")
result = sync.sync_financial_data(stock_list, start_date, end_date)
print(f"结果: {result}")

# 验证数据库
if result.get('status') == 'success':
    print("\n✅ 同步成功!")
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'aquant.db'))
    c = conn.cursor()

    c.execute("PRAGMA table_info(financial_data)")
    print("\n表字段:")
    for col in c.fetchall():
        print(f"  {col[1]:25s} type={col[2]}")

    c.execute("SELECT COUNT(*) FROM financial_data")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT stock_code) FROM financial_data")
    n_stocks = c.fetchone()[0]
    print(f"\n总记录数: {total}, 覆盖股票数: {n_stocks}")

    c.execute("""SELECT stock_code, rpt_date, pub_date, eps_basic, eps_dil, roe, ttl_ast, ttl_liab,
                        ttl_inc_oper, net_prof_pcom, net_cf_oper, bps_sh, net_prof
                 FROM financial_data LIMIT 5""")
    cols = [d[0] for d in c.description]
    print(f"\n样本数据:")
    print(f"  {' | '.join(cols)}")
    for row in c.fetchall():
        print(f"  {' | '.join(str(v) for v in row)}")
    conn.close()
else:
    print(f"\n❌ 同步失败: {result}")
