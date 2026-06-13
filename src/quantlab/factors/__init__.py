# factors 包
# 因子库
# 每个因子内部自带 cache 逻辑
# 策略只需调用：
#   fast_ma = ma(ctx, 20)
#   slow_ma = ma(ctx, 60)
# 不需要关心 cache key / 重复计算
