"""
V2.5 Live — Logger

实盘日志系统
3 类：
    orders.log   下单记录
    trades.log   成交记录
    errors.log   拒单 / 异常 / kill switch

V1 用 Python logging
V2 可换 loguru / sentry
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Any


class LiveLogger:
    """
    三路 logger：
        orders
        trades
        errors
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        self.orders = self._build(
            "live.orders", "orders.log"
        )
        self.trades = self._build(
            "live.trades", "trades.log"
        )
        self.errors = self._build(
            "live.errors", "errors.log"
        )

    def _build(
        self, name: str, fname: str
    ) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            path = os.path.join(
                self.log_dir, fname
            )
            fh = RotatingFileHandler(
                path,
                maxBytes=10 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            fmt = logging.Formatter(
                "%(asctime)s | %(message)s"
            )
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        return logger

    # ---- API ----
    def order(
        self,
        local_id: str,
        symbol: str,
        qty: int,
        ts: Any,
    ) -> None:
        self.orders.info(
            f"ORDER id={local_id} "
            f"sym={symbol} qty={qty} ts={ts}"
        )

    def trade(
        self,
        symbol: str,
        qty: int,
        price: float,
        ts: Any,
    ) -> None:
        self.trades.info(
            f"TRADE sym={symbol} "
            f"qty={qty} price={price:.4f} ts={ts}"
        )

    def reject(
        self,
        symbol: str,
        qty: int,
        reason: str,
    ) -> None:
        self.errors.warning(
            f"REJECT sym={symbol} "
            f"qty={qty} reason={reason}"
        )

    def error(self, msg: str) -> None:
        self.errors.error(msg)
