from gm.api import *
import pandas as pd
import json
from pathlib import Path
import sqlite3
import datetime


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




def get_stock_mktval():
    stocks = []
    try:
        conn = sqlite3.connect(r'D:\python_workspace\myquant\data\aquant.db')
        stocks = conn.execute('select exchange,sec_id from t_stock_info').fetchall()
        # print(stocks)
        conn.close()
    except sqlite3.Error as e:
        print(f"数据库操作失败: {e}")
        return None
    i=0
    for stock in stocks:
        symbol = stock[0] + '.' + stock[1]
        print(symbol)
        stock_mktval = get_stock_mktval(symbol=symbol,fields='tclose,turnrate,ttl_shr,circ_shr', start_date='2026-01-01', end_date='2026-05-27', df=True)
        print(stock_mktval)
        print('-----------------')
        i=i+1
        print(f'已处理{i}只股票')
        print(datetime.datetime.now())



def get_stock_mktval_pt():
    stocks = []
    try:
        conn = sqlite3.connect(r'D:\python_workspace\myquant\data\aquant.db')
        stocks = conn.execute('select exchange,sec_id from t_stock_info').fetchall()
        # print(stocks)
        conn.close()
    except sqlite3.Error as e:
        print(f"数据库操作失败: {e}")
        return None
    i=0
    df = pd.DataFrame()
    for trade_date in pd.date_range(start='2026-01-01', end='2026-06-01'):
        trade_date_str = trade_date.strftime('%Y-%m-%d')
        stock_mktval = stk_get_daily_mktvalue_pt(symbols=['SHSE.600335'],fields='tot_mv,tot_mv_csrc,a_mv', trade_date=trade_date_str, df=True)
        print(stock_mktval)
        print('-----------------')
        i=i+1
        print(f'已处理{i}只股票')
        print(datetime.datetime.now())
        df = pd.concat([df, stock_mktval], axis=0)
    print(df)

def get_daily_valuation_pt():
    stocks = []
    try:
        conn = sqlite3.connect(r'D:\python_workspace\myquant\data\aquant.db')
        stocks = conn.execute('select exchange,sec_id from t_stock_info').fetchall()
        # print(stocks)
        conn.close()
    except sqlite3.Error as e:
        print(f"数据库操作失败: {e}")
        return None
    i=0
    stock_list = []
    for stock in stocks:
        symbol = stock[0] + '.' + stock[1]
        stock_list.append(symbol)

    df = pd.DataFrame()
    for trade_date in pd.date_range(start='2026-01-01', end='2026-01-10'):
        trade_date_str = trade_date.strftime('%Y-%m-%d')
        # stock_mktval = stk_get_daily_valuation_pt(symbols=stock_list,fields='pb_lf', trade_date=trade_date_str, df=True)
        stock_mktval = stk_get_daily_valuation(symbol=stock_list[0],fields='pb_lf', start_date=trade_date_str, end_date=trade_date_str, df=True)
        print(stock_mktval)
        print('-----------------')
        i=i+1
        print(f'已处理{i}只股票')
        print(datetime.datetime.now())
        df = pd.concat([df, stock_mktval], axis=0)
        temp_df = df[df['pb_lf'].notnull()]
    print(temp_df)

def get_finance_prime_pt():
    stocks = []
    try:
        conn = sqlite3.connect(r'D:\python_workspace\myquant\data\aquant.db')
        stocks = conn.execute('select exchange,sec_id from t_stock_info').fetchall()
        # print(stocks)
        conn.close()
    except sqlite3.Error as e:
        print(f"数据库操作失败: {e}")
        return None
    i=0
    stock_list = []
    for stock in stocks:
        symbol = stock[0] + '.' + stock[1]
        stock_list.append(symbol)

    df = pd.DataFrame()
    for trade_date in pd.date_range(start='2026-01-01', end='2026-01-10'):
        trade_date_str = trade_date.strftime('%Y-%m-%d')
        # stock_mktval = stk_get_daily_valuation_pt(symbols=stock_list,fields='pb_lf', trade_date=trade_date_str, df=True)
        stock_mktval = stk_get_finance_prime_pt(symbols=stock_list, fields='net_prof', rpt_type=None, data_type=None, date=trade_date_str, df=True)
        stock_mktval = stock_mktval[stock_mktval['net_prof'].notnull()]
        print(stock_mktval)
        print('-----------------')
        i=i+1
        print(f'已处理{i}只股票')
        print(datetime.datetime.now())

def get_finance_deriv_pt2():
    stocks = []
    try:
        conn = sqlite3.connect(r'D:\python_workspace\myquant\data\aquant.db')
        stocks = conn.execute('select exchange,sec_id from t_stock_info').fetchall()
        # print(stocks)
        conn.close()
    except sqlite3.Error as e:
        print(f"数据库操作失败: {e}")
        return None
    i=0
    stock_list = []
    for stock in stocks:
        symbol = stock[0] + '.' + stock[1]
        stock_list.append(symbol)

    df = pd.DataFrame()
    for trade_date in pd.date_range(start='2026-01-01', end='2026-01-10'):
        trade_date_str = trade_date.strftime('%Y-%m-%d')
        # stock_mktval = stk_get_daily_valuation_pt(symbols=stock_list,fields='pb_lf', trade_date=trade_date_str, df=True)
        stock_mktval = stk_get_finance_deriv_pt(symbols=stock_list, fields='data_type_x,rpt_type_x', rpt_type=None, data_type=None, date=trade_date_str, df=True)
        stock_mktval = stock_mktval[stock_mktval['data_type_x'].notnull()]
        stock_mktval = stock_mktval[stock_mktval['rpt_type_x'].notnull()]
        print(stock_mktval)
        print('-----------------')
        i=i+1
        print(f'已处理{i}只股票')
        print(datetime.datetime.now())

get_finance_deriv_pt2()


def get_finance_deriv_pt():
    """
    测试 stk_get_finance_deriv_pt 接口字段拼接逻辑
    接口每次最多请求20个字段，需分批请求再合并（共142个字段，分8批）
    """
    stocks = []
    try:
        conn = sqlite3.connect(r'D:\python_workspace\myquant\data\aquant.db')
        stocks = conn.execute('select exchange,sec_id from t_stock_info').fetchall()
        conn.close()
    except sqlite3.Error as e:
        print(f"数据库操作失败: {e}")
        return None

    stock_list = []
    for stock in stocks:
        symbol = stock[0] + '.' + stock[1]
        stock_list.append(symbol)

    # 财务衍生指标完整字段（对齐 stk_get_finance_deriv，共142个）
    all_fields = [
        # 每股指标 (19)
        'eps_basic', 'eps_dil2', 'eps_dil', 'eps_basic_cut', 'eps_dil2_cut', 'eps_dil_cut',
        'bps', 'net_cf_oper_ps', 'ttl_inc_oper_ps', 'inc_oper_ps', 'ebit_ps',
        'cptl_rsv_ps', 'sur_rsv_ps', 'retain_prof_ps', 'retain_inc_ps',
        'net_cf_ps', 'fcff_ps', 'fcfe_ps', 'ebitda_ps',
        # ROE系列 + 现金流比率 + 同比增长 (20)
        'roe', 'roe_weight', 'roe_avg', 'roe_cut', 'roe_weight_cut', 'ocf_toi',
        'eps_dil_yoy', 'net_cf_oper_ps_yoy', 'ttl_inc_oper_yoy', 'inc_oper_yoy',
        'oper_prof_yoy', 'ttl_prof_yoy', 'net_prof_pcom_yoy', 'net_prof_pcom_cut_yoy',
        'net_cf_oper_yoy', 'roe_yoy', 'net_asset_yoy', 'ttl_liab_yoy',
        'ttl_asset_yoy', 'net_cash_flow_yoy',
        # 增长率(年初) + 债务股权比 + EBIT/EBITDA + 利润 (20)
        'bps_gr_begin_year', 'ttl_asset_gr_begin_year', 'ttl_eqy_pcom_gr_begin_year',
        'net_debt_eqy_ev', 'int_debt_eqy_ev', 'eps_bas_yoy',
        'ebit', 'ebitda', 'ebit_inverse', 'ebitda_inverse',
        'nr_prof_loss', 'net_prof_cut', 'gross_prof', 'oper_net_inc', 'val_chg_net_inc',
        'exp_rd', 'ttl_inv_cptl', 'work_cptl', 'net_work_cptl', 'tg_asset',
        # 留存收益 + 债务 + 现金流 + 杜邦 + 利润比率 + ROA/ROIC (20)
        'retain_inc', 'int_debt', 'net_debt', 'curr_liab_non_int', 'ncur_liab_non_int',
        'fcff', 'fcfe', 'cur_depr_amort', 'eqy_mult_dupont',
        'net_prof_pcom_np', 'net_prof_tp', 'ttl_prof_ebit',
        'roe_cut_avg', 'roe_add', 'roe_ann', 'roa', 'roa_ann', 'jroa', 'jroa_ann', 'roic',
        # 销售利润率 + 费用率 + EBITDA比率 (20)
        'sale_npm', 'sale_gpm', 'sale_cost_rate', 'sale_exp_rate',
        'net_prof_toi', 'oper_prof_toi', 'ebit_toi', 'ttl_cost_oper_toi',
        'exp_oper_toi', 'exp_admin_toi', 'exp_fin_toi', 'ast_impr_loss_toi', 'ebitda_toi',
        'oper_net_inc_tp', 'val_chg_net_inc_tp', 'net_exp_noper_tp', 'inc_tax_tp',
        'net_prof_cut_np', 'eqy_mult', 'curr_ast_ta',
        # 资产结构 + 负债结构 + 偿债能力 (20)
        'ncurr_ast_ta', 'tg_ast_ta', 'ttl_eqy_pcom_tic', 'int_debt_tic',
        'curr_liab_tl', 'ncurr_liab_tl', 'ast_liab_rate', 'quick_rate', 'curr_rate',
        'cons_quick_rate', 'liab_eqy_rate', 'ttl_eqy_pcom_tl', 'ttl_eqy_pcom_debt',
        'tg_ast_tl', 'tg_ast_int_debt', 'tg_ast_net_debt',
        'ebitda_tl', 'net_cf_oper_tl', 'net_cf_oper_int_debt', 'net_cf_oper_curr_liab',
        # 现金流/负债 + 利息保障 + 营业周期 + 周转率 (20)
        'net_cf_oper_net_liab', 'ebit_int_cover', 'long_liab_work_cptl', 'ebitda_int_debt',
        'oper_cycle', 'inv_turnover_days', 'acct_rcv_turnover_days',
        'inv_turnover_rate', 'acct_rcv_turnover_rate',
        'curr_ast_turnover_rate', 'fix_ast_turnover_rate', 'ttl_ast_turnover_rate',
        'cash_rcv_sale_oi', 'net_cf_oper_oi', 'net_cf_oper_oni', 'cptl_exp_da', 'cash_rate',
        'acct_pay_turnover_days', 'acct_pay_turnover_rate', 'net_oper_cycle',
        'ttl_cost_oper_yoy',
        # 同比增长率 (2)
        'net_prof_yoy', 'net_cf_oper_np',
    ]
    print(f"总字段数: {len(all_fields)}")

    trade_date_str = '2026-01-10'
    batch_size = 20
    merge_cols = ['symbol', 'pub_date', 'rpt_date']
    result_df = None

    for i in range(0, len(all_fields), batch_size):
        batch_fields = all_fields[i:i + batch_size]
        fields_str = ','.join(batch_fields)
        print(f"第 {i // batch_size + 1} 批: {len(batch_fields)} 个字段 -> {fields_str[:50]}...")

        df = stk_get_finance_deriv_pt(
            symbols=stock_list,
            fields=fields_str,
            date=trade_date_str,
            df=True,
        )
        print(f"  返回 {len(df)} 条记录, 列: {list(df.columns)}")

        if df is not None and not df.empty:
            if result_df is None:
                result_df = df
            else:
                new_cols = [c for c in df.columns if c not in merge_cols]
                result_df = result_df.merge(
                    df[merge_cols + new_cols],
                    on=merge_cols,
                    how='outer',
                )

    if result_df is not None:
        print(f"\n合并后总列数: {len(result_df.columns)}")
        print(f"合并后总记录数: {len(result_df)}")
        print(f"合并后列: {list(result_df.columns)}")
    return result_df



# df = get_symbol_infos(sec_type1=1060,sec_type2=106001 ,df=True)
# df.to_csv(r'F:\python_workspace\myquant\tests\106001.csv', index=False)
# df_history = get_history_symbol(symbol='SHSE.000685', start_date='2026-05-27', end_date='2026-05-27', df=True)
# df_history.to_csv(r'd:\python_workspace\myquant\tests\SHSE.000685_history.csv', index=False)

# ETF
# df = get_symbol_infos(sec_type1=1020,sec_type2=102001, symbols='SHSE.512130', df=True)
# df.to_csv(r'd:\python_workspace\myquant\tests\SHSE.512130.csv', index=False)

# df=history(symbol='SHSE.000016', frequency='1d', start_time='2026-01-01',  end_time='2026-07-30', fields='open, close, low, high, eob', adjust=ADJUST_PREV,adjust_end_time='2017-07-30', df= True)
# df.to_csv(r'd:\python_workspace\myquant\tests\SHSE.000016.csv', index=False)
# df = get_symbol_infos(sec_type1=1070,sec_type2=107001, df=True)
# df.to_csv(r'd:\python_workspace\myquant\tests\107001.csv', index=False)

# df = stk_get_finance_prime(symbol='SHSE.600000', fields='eps_basic,eps_dil,eps_basic_cut,eps_dil_cut,net_cf_oper_ps,bps_pcom_ps,ttl_ast,ttl_liab,share_cptl,ttl_inc_oper',rpt_type=None, data_type=None,start_date=None, end_date=None, df=True)
# df.to_csv(r'd:\python_workspace\myquant\tests\SHSE.600000finance.csv', index=False)

# df = stk_get_daily_valuation_pt(symbols=['SZSE.000001', 'SZSE.300002'],fields='pe_ttm,pe_lyr,pe_mrq', trade_date='2026-01-01' , df=True)
# # df.to_csv(r'd:\python_workspace\myquant\tests\SHSE.600000_daily_valuation.csv', index=False)
# print(df)

# df = stk_get_daily_valuation(symbol='SZSE.000001',fields='pe_ttm,pe_lyr,pe_mrq', start_date='2026-01-01', end_date='2026-05-27', df=True)
# df.to_csv(r'd:\python_workspace\myquant\tests\SHSE.600000_daily_valuation.csv', index=False)
# print(df)

# df = stk_get_daily_mktvalue(symbol='SZSE.000001',fields='tot_mv,tot_mv_csrc,a_mv', start_date='2026-01-01', end_date='2026-05-27', df=True)
# # df.to_csv(r'd:\python_workspace\myquant\tests\SHSE.600000_daily_valuation.csv', index=False)
# print(df)

# get_stock_mktval()


# get_stock_mktval_pt()



# get_daily_valuation_pt()

# get_finance_deriv_pt()






print('done')



