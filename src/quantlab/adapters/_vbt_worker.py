"""
vbt 子进程 worker
通过 json 传参数
崩溃不会影响主进程
"""

import sys
import os
import json
import argparse


def main():

    # 必须在 import vbt 之前
    # 设置环境变量避免 numba JIT 等
    os.environ.setdefault(
        "NUMBA_DISABLE_JIT", "1"
    )
    os.environ.setdefault(
        "MPLBACKEND", "Agg"
    )

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", required=True
    )
    parser.add_argument(
        "--data-path", required=True
    )
    parser.add_argument(
        "--fast", type=int, required=True
    )
    parser.add_argument(
        "--slow", type=int, required=True
    )
    parser.add_argument(
        "--init-cash", type=float, default=100000
    )

    args = parser.parse_args()

    try:

        import numpy as np
        import pandas as pd
        import vectorbt as vbt

        # 读 data（json: {symbol: {date: ohlc...}}）
        with open(args.data_path, "r") as f:
            raw = json.load(f)

        data = {}
        for sym, rows in raw.items():

            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(
                df["date"]
            )
            df = df.set_index("date")
            data[sym] = df

        symbols = list(data.keys())

        # 用 fast / slow 计算均线交叉信号
        closes = pd.DataFrame({
            sym: df["close"]
            for sym, df in data.items()
        })

        ma_fast = closes.rolling(
            args.fast
        ).mean()
        ma_slow = closes.rolling(
            args.slow
        ).mean()
        entries = (
            (ma_fast > ma_slow)
            & (ma_fast.shift(1) <= ma_slow.shift(1))
        )
        exits = (
            (ma_fast < ma_slow)
            & (ma_fast.shift(1) >= ma_slow.shift(1))
        )

        # 按 symbol 单独跑 Portfolio
        portfolios = {}
        for sym in symbols:

            close = data[sym]["close"]
            pf = vbt.Portfolio.from_signals(
                close=close,
                entries=entries[sym],
                exits=exits[sym],
                init_cash=args.init_cash,
            )
            portfolios[sym] = pf

        # 汇总：等权合并 equity
        equity = sum(
            pf.value()
            for pf in portfolios.values()
        ) / len(portfolios)

        # 计算简单指标
        rets = equity.pct_change().dropna()
        total_return = (
            equity.iloc[-1] / equity.iloc[0] - 1
        )
        sharpe = (
            rets.mean() / rets.std()
            * np.sqrt(252)
        ) if len(rets) > 1 and rets.std() > 0 else 0.0

        out = {
            "ok": True,
            "metrics": {
                "total_return": float(total_return),
                "sharpe": float(sharpe),
                "final_equity": float(equity.iloc[-1]),
            },
            "n_symbols": len(symbols),
        }

    except Exception as e:

        out = {
            "ok": False,
            "error": repr(e),
        }

    print(json.dumps(out))
    sys.exit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()
