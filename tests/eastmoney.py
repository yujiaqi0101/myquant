from gm.api import *
import pandas as pd

set_token('3e42df3dda1021b373eff76258b1e123eeb76f16')
# df = get_symbol_infos(sec_type1=1060,sec_type2=106001 ,df=True)
# df.to_csv(r'F:\python_workspace\myquant\tests\106001.csv', index=False)
df_history = get_history_symbol(symbol='SHSE.000685', start_date='2026-05-27', end_date='2026-05-27', df=True)
df_history.to_csv(r'd:\python_workspace\myquant\tests\SHSE.000685_history.csv', index=False)

print('done')
