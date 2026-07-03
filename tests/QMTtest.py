from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant import xtdata
print("demo test")
path = r"E:\国金QMT交易端模拟\userdata_mini"
session_id = 123456
xt_trader = XtQuantTrader(path, session_id)
print(xt_trader)

field_list=[
                'time',
                'open',
                'high',
                'low',
                'close',
                'volume',
                'amount',
                'preClose',
                'suspendFlag'
            ]

stock_list=['000001.SH']
period = '1d'
start_time = '20240201'
end_time = '20240207'
count = -1
dividend_type = 'none'

xtdata.download_history_data('000001.SH', period=period)

data = xtdata.get_market_data_ex(field_list=field_list,
                stock_list=stock_list, period=period, start_time=start_time, end_time=end_time,
                dividend_type=dividend_type,fill_data=True
            )

print(data)


