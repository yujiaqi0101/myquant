"""
SubprocessVectorBT：把 vectorbt 隔离在子进程
sandbox / 受限环境下 vbt 崩进程不影响主进程

协议：
- 写 data 到临时 json
- subprocess 调 _vbt_worker.py
- 读 stdout json 取指标
"""

import json
import os
import subprocess
import sys
import tempfile

from typing import Dict

from ..core.base_engine import (
    BaseBacktestEngine,
)
from ..core.backtest_result import (
    BacktestResult,
)


class SubprocessVectorBT(BaseBacktestEngine):

    def __init__(
        self,
        python=None,
        timeout=120,
    ):

        self.python = (
            python or sys.executable
        )
        self.timeout = timeout
        self.worker = (
            os.path.join(
                os.path.dirname(
                    __file__
                ),
                "_vbt_worker.py",
            )
        )

    def run(
        self,
        strategy=None,
        data: Dict = None,
        params: Dict = None,
    ) -> BacktestResult:

        # BaseBacktestEngine 协议
        # strategy 必须带 fast/slow 属性
        # （这是当前 worker 协议）
        if strategy is None and hasattr(
            self, "_strategy"
        ):

            strategy = self._strategy

        if data is None and hasattr(
            self, "_data"
        ):

            data = self._data

        fast = getattr(strategy, "fast", 20)
        slow = getattr(strategy, "slow", 60)
        init_cash = getattr(
            self, "_init_cash", 100000
        )

        out = self._run_subprocess(
            data=data,
            fast=fast,
            slow=slow,
            init_cash=init_cash,
        )

        return self._build_result(
            out=out,
            source="vectorbt_subprocess",
        )

    def _run_subprocess(
        self,
        data: Dict,
        fast: int,
        slow: int,
        init_cash: float = 100000,
    ):

        # 序列化 data 到 json
        raw = {}
        for sym, df in data.items():

            raw[sym] = json.loads(
                df.reset_index().to_json(
                    orient="records",
                    date_format="iso",
                )
            )

        # 写临时文件
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        )
        json.dump(raw, tmp)
        tmp.close()
        data_path = tmp.name

        try:

            proc = subprocess.run(

                [
                    self.python,
                    self.worker,
                    "--mode", "single",
                    "--data-path", data_path,
                    "--fast", str(fast),
                    "--slow", str(slow),
                    "--init-cash",
                    str(init_cash),
                ],

                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            if proc.returncode != 0:

                return {
                    "ok": False,
                    "error": (
                        f"worker exit {proc.returncode}:"
                        f" {proc.stderr[-500:]}"
                    ),
                }

            out = json.loads(
                proc.stdout.strip()
            )

            return out

        except subprocess.TimeoutExpired:

            return {
                "ok": False,
                "error": "vbt worker timeout",
            }

        except Exception as e:

            return {
                "ok": False,
                "error": repr(e),
            }

        finally:

            try:
                os.unlink(data_path)
            except OSError:
                pass

    def _build_result(
        self,
        out: Dict,
        source: str,
    ):

        if not out.get("ok"):

            return BacktestResult(
                equity_curve=[],
                total_return=0.0,
                sharpe=0.0,
                max_drawdown=0.0,
                trade_count=0,
                win_rate=0.0,
                final_equity=0.0,
                source=source,
                raw=out,
                error=out.get(
                    "error",
                    "unknown error"
                ),
            )

        m = out.get("metrics", {})

        return BacktestResult(
            equity_curve=[],
            total_return=m.get(
                "total_return", 0.0
            ),
            sharpe=m.get("sharpe", 0.0),
            max_drawdown=0.0,
            trade_count=0,
            win_rate=0.0,
            final_equity=m.get(
                "final_equity", 0.0
            ),
            source=source,
            raw=out,
        )


def get_subprocess_vbt():

    # 检查 worker 脚本存在
    worker = os.path.join(
        os.path.dirname(__file__),
        "_vbt_worker.py",
    )
    if not os.path.exists(worker):
        return None
    return SubprocessVectorBT()
