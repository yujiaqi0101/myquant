"""
临时数据同步脚本
用法: python tests/temp_sync.py
"""

import subprocess
import sys
import datetime


# 循环2010年1月到2015年12月，每个月
for year in range(2010, 2016):
    for month in range(1, 13):
        # 计算当月第一天和最后一天
        start_date = datetime.date(year, month, 1)
        if month == 12:
            end_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            end_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        # 2015年12月截止到31日
        if year == 2015 and month == 12:
            end_date = datetime.date(2015, 12, 31)

        # 格式化日期
        start_date_str = start_date.strftime("%Y%m%d")
        end_date_str = end_date.strftime("%Y%m%d")

        print(f"同步 {start_date_str} ~ {end_date_str} 的数据...")

        # 同步估值数据（步骤15），日期范围 20160101 ~ 20160110
        result = subprocess.run(
            [
                sys.executable, "main.py", "data", "sync",
                "--steps", "13,14,15,16",
                # "--steps", "15",
                "--start-date", start_date_str,
                "--end-date", end_date_str,
            ],
            cwd=r"D:\python_workspace\myquant",
        )

        # sys.exit(result.returncode)
