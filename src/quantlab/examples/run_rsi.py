"""
RSI 策略 SOP 跑法（薄壳）
=====================

调用通用 [run_pipeline.py] 对 RSIStrategy 跑 6 stage。
所有 SOP 行为（基线 / 双引擎 / 网格 / WF / 入库 / 反例）
都在 run_pipeline.run_sop() 里实现。

运行：
    python examples/run_rsi.py
"""
import os
import sys

# 让脚本无论从项目根还是 examples/ 子目录直接跑都能找到 quantlab 包
# 也让 examples/ 内的 run_pipeline 能被相对导入
_PKG_PARENT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run_pipeline import run_sop
from quantlab.signals import (
    RSIStrategy,
    RSI_PARAM_SPACE,
)

if __name__ == "__main__":
    run_sop(
        strategy_cls=RSIStrategy,
        param_space=RSI_PARAM_SPACE,
        base_params={
            "period": 14,
            "oversold": 30.0,
            "overbought": 70.0,
            "use_trend_filter": False,
            "trend_period": 200,
        },
        tag="mean_reversion",
        note=(
            "RSI(14)/30/70，TopN=2，"
            "commission=3bps，slippage=2bps"
        ),
    )
