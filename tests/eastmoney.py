from gm.api import *
import pandas as pd
import json
from pathlib import Path

# 从配置文件读取token
config_path = Path(__file__).parent.parent / 'config' / 'config.json'
if config_path.exists():
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
        token = config.get('credentials', {}).get('eastmoney', {}).get('token', '')
else:
    token = ''

if not token:
    raise ValueError("请先配置东财掘金Token，运行: python main.py config --token <your_token>")
print(token)
set_token(token)
# df = get_symbol_infos(sec_type1=1060,sec_type2=106001 ,df=True)
# df.to_csv(r'F:\python_workspace\myquant\tests\106001.csv', index=False)
# df_history = get_history_symbol(symbol='SHSE.000685', start_date='2026-05-27', end_date='2026-05-27', df=True)
# df_history.to_csv(r'd:\python_workspace\myquant\tests\SHSE.000685_history.csv', index=False)

# ETF
# df = get_symbol_infos(sec_type1=1020,sec_type2=102001, symbols='SHSE.512130', df=True)
# df.to_csv(r'd:\python_workspace\myquant\tests\SHSE.512130.csv', index=False)

df=history(symbol='SHSE.000016', frequency='1d', start_time='2026-01-01',  end_time='2026-07-30', fields='open, close, low, high, eob', adjust=ADJUST_PREV,adjust_end_time='2017-07-30', df= True)
df.to_csv(r'd:\python_workspace\myquant\tests\SHSE.000016.csv', index=False)


print('done')
