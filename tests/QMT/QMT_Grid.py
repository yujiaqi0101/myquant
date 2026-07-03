#coding:gbk

#在期货的1min线下运行
'''
回测模型示例（非实盘交易策略）

本策略首先计算了过去300个价格数据的均值和标准差
并根据均值加减标准差得到网格的区间分界线,
并分别配以0.3和0.5的仓位权重
然后根据价格所在的区间来配置仓位(+/-40为上下界,无实际意义):
(-40,-3],(-3,-2],(-2,2],(2,3],(3,40](具体价格等于均值+数字倍标准差)
[0.25, 0.15, 0.0, 0.15, 0.25](资金比例)
'''

import numpy as np
import pandas as pd
import time
import datetime
def init(ContextInfo):
	#设置图为标的
	ContextInfo.tradefuture = ContextInfo.stockcode+"."+ContextInfo.market
	ContextInfo.set_universe([ContextInfo.tradefuture])
	print(ContextInfo.get_universe())
	ContextInfo.timeseries = pd.DataFrame()
	ContextInfo.band = np.zeros(5)
	#print 'ContextInfo.band',ContextInfo.band
	
	# 设置网格的仓位
	ContextInfo.weight = [0.25, 0.15, 0.0, 0.15, 0.25]
	# 获取多仓仓位
	ContextInfo.position_long = 0
	# 获取孔仓仓位
	ContextInfo.position_short = 0
	
	#剩余资金
	ContextInfo.surpluscapital = ContextInfo.capital
	#保证金比率
	comdict = ContextInfo.get_commission()
	ContextInfo.marginratio = comdict['margin_ratio']
	#合约乘数
	ContextInfo.multiplier = ContextInfo.get_contract_multiplier(ContextInfo.tradefuture)
	#账号
	ContextInfo.accountid='testF'
	ContextInfo.now_timestamp = time.time()
def handlebar(ContextInfo):
	index = ContextInfo.barpos
	realtimetag  = ContextInfo.get_bar_timetag(index)
	lasttimetag = ContextInfo.get_bar_timetag(index - 1)
	print(timetag_to_datetime(realtimetag, '%Y-%m-%d %H:%M:%S'))
	if ContextInfo.period in ['1m','3m','5m','15m','30m'] and not ContextInfo.do_back_test:
		if (datetime.datetime.fromtimestamp(ContextInfo.now_timestamp) - datetime.datetime.fromtimestamp(realtimetag / 1000)).days > 7:
			return
	starttime = timetag_to_datetime(realtimetag-86400000 * 10, '%Y%m%d%H%M%S')
	endtime = timetag_to_datetime(realtimetag-86400000, '%Y%m%d%H%M%S')
	#print 'starttime,endtime',starttime,endtime
	Result=ContextInfo.get_market_data(['close'],stock_code=[ContextInfo.tradefuture],start_time=starttime,end_time=endtime,skip_paused=False,period=ContextInfo.period,dividend_type='front')
	close_sort = Result['close'].sort_index(axis = 0,ascending = True)
	#print close_sort,starttime,endtime
	#过去300个价格数据的均值和标准差
	Result_mean = close_sort.tail(300).mean()
	Result_std = close_sort.tail(300).std()
	ContextInfo.band = Result_mean + np.array([-40, -3, -2, 2, 3, 40]) * Result_std
	#print 'ContextInfo.band',ContextInfo.band
	if np.isnan(ContextInfo.band).any() or Result_std==0:
		return
	if index > 0:
		lasttimetag = ContextInfo.get_bar_timetag(index - 1)
		#前一根bar收盘价
		close_lastbar = ContextInfo.get_market_data (['close'],stock_code=[ContextInfo.tradefuture],period=ContextInfo.period,dividend_type='front')
		#当前开盘价
		open_currentbar = ContextInfo.get_market_data (['open'],stock_code=[ContextInfo.tradefuture],period=ContextInfo.period,dividend_type='front')
		#划分网格
		#print close_lastbar,ContextInfo.band
		grid = pd.cut([close_lastbar], ContextInfo.band, labels=[0, 1, 2, 3, 4])[0]
		#print 'grid ',grid
		if not ContextInfo.do_back_test:
			ContextInfo.paint('grid',float(grid),-1,0)
		# 若无仓位且价格突破则按照设置好的区间开仓
		if ContextInfo.position_long == 0 and ContextInfo.position_short == 0 and grid != 2:
			# 大于3为在中间网格的上方,做多
			if grid >= 3 and ContextInfo.surpluscapital > 0 :
				long_num = int(ContextInfo.weight[grid]*ContextInfo.surpluscapital/(ContextInfo.marginratio*close_lastbar*ContextInfo.multiplier))
				ContextInfo.position_long = long_num
				buy_open(ContextInfo.tradefuture,long_num,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
				ContextInfo.surpluscapital -= long_num * ContextInfo.marginratio * close_lastbar * ContextInfo.multiplier
				#print '开多' 
			elif grid <= 1 and ContextInfo.surpluscapital > 0 :
				short_num = int(ContextInfo.weight[grid]*ContextInfo.surpluscapital/(ContextInfo.marginratio*close_lastbar*ContextInfo.multiplier))
				ContextInfo.position_short = short_num
				sell_open(ContextInfo.tradefuture,short_num,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
				ContextInfo.surpluscapital -= short_num * ContextInfo.marginratio * close_lastbar * ContextInfo.multiplier
				#print '开空'
		# 持有多仓的处理
		elif ContextInfo.position_long > 0 :
			if grid >= 3 and ContextInfo.surpluscapital > 0 :
				targetlong_num = int(ContextInfo.weight[grid] * (ContextInfo.surpluscapital + ContextInfo.multiplier * close_lastbar * ContextInfo.position_long*ContextInfo.marginratio)/ (ContextInfo.marginratio*close_lastbar * ContextInfo.multiplier))
				if targetlong_num > ContextInfo.position_long : 
					trade_num = targetlong_num - ContextInfo.position_long 
					ContextInfo.position_long = targetlong_num
					buy_open(ContextInfo.tradefuture,trade_num,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
					ContextInfo.surpluscapital -= trade_num * close_lastbar * ContextInfo.marginratio * ContextInfo.multiplier
				elif targetlong_num < ContextInfo.position_long:
					trade_num = ContextInfo.position_long - targetlong_num
					ContextInfo.position_long = targetlong_num
					sell_close_tdayfirst(ContextInfo.tradefuture,trade_num,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
					ContextInfo.surpluscapital += trade_num * close_lastbar * ContextInfo.marginratio * ContextInfo.multiplier
				#print '调多仓到仓位'
				# 等于2为在中间网格,平仓
			elif grid == 2:
				sell_close_tdayfirst(ContextInfo.tradefuture,ContextInfo.position_long,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
				ContextInfo.surpluscapital += ContextInfo.position_long * close_lastbar * ContextInfo.marginratio * ContextInfo.multiplier
				ContextInfo.position_long = 0
				#print '平多'
			# 小于1为在中间网格的下方,做空
			elif grid <= 1:
				sell_close_tdayfirst(ContextInfo.tradefuture,ContextInfo.position_long,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
				ContextInfo.surpluscapital += ContextInfo.position_long * close_lastbar * ContextInfo.marginratio * ContextInfo.multiplier
				ContextInfo.position_long = 0
				#print '全平多仓'
				if ContextInfo.surpluscapital > 0 :
					short_num = int(ContextInfo.weight[grid]*ContextInfo.surpluscapital/(ContextInfo.multiplier * ContextInfo.marginratio * close_lastbar))
					ContextInfo.position_short = short_num
					sell_open(ContextInfo.tradefuture,short_num,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
					ContextInfo.surpluscapital -= short_num * close_lastbar * ContextInfo.marginratio * ContextInfo.multiplier
					#print '开空仓到仓位'
		
		# 持有空仓的处理
		elif ContextInfo.position_short> 0 :
			# 小于1为在中间网格的下方,做空
			if grid <= 1:
				targetlshort_num = int(ContextInfo.weight[grid]*(ContextInfo.surpluscapital + ContextInfo.multiplier*close_lastbar*ContextInfo.position_short*ContextInfo.marginratio)/(ContextInfo.multiplier * ContextInfo.marginratio * close_lastbar))
				if targetlshort_num > ContextInfo.position_short:
					trade_num = targetlshort_num - ContextInfo.position_short 
					ContextInfo.position_short = targetlshort_num
					sell_open(ContextInfo.tradefuture,trade_num,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
					ContextInfo.surpluscapital -= trade_num * close_lastbar * ContextInfo.marginratio * ContextInfo.multiplier
					#print '开空仓到仓位' ,targetlshort_num
				elif targetlshort_num < ContextInfo.position_short:
					trade_num = ContextInfo.position_short -  targetlshort_num 
					ContextInfo.position_short = targetlshort_num
					buy_close_tdayfirst(ContextInfo.tradefuture,trade_num,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
					ContextInfo.surpluscapital += trade_num * close_lastbar * ContextInfo.marginratio * ContextInfo.multiplier
					#print  '平空仓到仓位' ,targetlshort_num
			# 等于2为在中间网格,平仓
			elif grid == 2:
				buy_close_tdayfirst(ContextInfo.tradefuture,ContextInfo.position_short,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
				ContextInfo.surpluscapital += ContextInfo.position_short * close_lastbar * ContextInfo.marginratio * ContextInfo.multiplier
				ContextInfo.position_short = 0
				#print '全平空仓' 
			# 大于3为在中间网格的上方,做多
			elif grid >= 3:
				buy_close_tdayfirst(ContextInfo.tradefuture,ContextInfo.position_short,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
				ContextInfo.surpluscapital += ContextInfo.position_short * close_lastbar * ContextInfo.marginratio * ContextInfo.multiplier
				ContextInfo.position_short = 0
				#print  '全平空仓' 
				if ContextInfo.surpluscapital > 0 :
					trade_num = int(ContextInfo.weight[grid]*ContextInfo.surpluscapital / (ContextInfo.marginratio * close_lastbar * ContextInfo.multiplier))
					ContextInfo.position_long = trade_num
					buy_open(ContextInfo.tradefuture,trade_num,'fix',close_lastbar,ContextInfo,ContextInfo.accountid)
					ContextInfo.surpluscapital -= trade_num * close_lastbar * ContextInfo.marginratio * ContextInfo.multiplier
					#print ' 开多仓到仓位' 
	# 获取多仓仓位
	#print 'ContextInfo.position_long',ContextInfo.position_long
	# 获取空仓仓位
	#print 'ContextInfo.position_short',ContextInfo.position_short
	# 获取剩余资金
	#print 'ContextInfo.surpluscapital',ContextInfo.surpluscapital

