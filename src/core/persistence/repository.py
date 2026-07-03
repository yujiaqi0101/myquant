"""
src/core/persistence/repository.py
==================================

账户持久化仓库（模拟盘/实盘状态持久化）。

本模块管理 account_* 系列 5 张表的 CRUD，替代旧的 paper_* 表。
表结构通过 ensure_tables() 幂等创建（CREATE TABLE IF NOT EXISTS），
不依赖迁移逻辑，符合"直接修改数据库结构"原则。

5 张表职责（设计文档第 6.3 节）：
    - account_info: 账户信息（资金、策略绑定）
    - account_positions: 持仓快照（跨日持久化）
    - account_orders: 订单记录
    - account_fills: 成交记录
    - account_snapshots: 每日净值快照

使用方式：
    - 回测模式：不持久化（Portfolio 纯内存）
    - 模拟盘/实盘：每日收盘后调用 save_account_state() 持久化全部状态
    - 重启恢复：调用 load_account_state() 从数据库重建 Portfolio

用法示例：
    from src.core.persistence import PersistenceRepository
    repo = PersistenceRepository(db_manager)
    repo.ensure_tables()                          # 幂等建表
    repo.save_account_state("acc_001", portfolio) # 持久化全部状态
    repo.load_account_state("acc_001", portfolio) # 恢复全部状态
"""

from typing import Any, Dict, List, Optional

from src.core.types import Direction, Order, OrderStatus, Position, PositionDirection
from src.core.portfolio import AccountInfo


# ---------------------------------------------------------------------------
# 表结构定义（DDL）
# ---------------------------------------------------------------------------

# 账户信息表：每个 account_id 一行，记录资金状态
_DDL_ACCOUNT_INFO = """
CREATE TABLE IF NOT EXISTS account_info (
    account_id      VARCHAR(64) PRIMARY KEY,
    strategy_name   VARCHAR(100) NOT NULL,
    initial_capital DOUBLE NOT NULL,
    cash            DOUBLE NOT NULL,
    frozen          DOUBLE NOT NULL DEFAULT 0.0,
    total_value     DOUBLE NOT NULL,
    peak_value      DOUBLE NOT NULL,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

# 持仓快照表：每个 (account_id, symbol) 一行，跨日持久化
_DDL_ACCOUNT_POSITIONS = """
CREATE TABLE IF NOT EXISTS account_positions (
    account_id   VARCHAR(64) NOT NULL,
    symbol       VARCHAR(20) NOT NULL,
    direction    VARCHAR(10) NOT NULL,
    quantity     DOUBLE NOT NULL,
    available    DOUBLE NOT NULL,
    avg_price    DOUBLE NOT NULL,
    market_price DOUBLE NOT NULL,
    market_value DOUBLE NOT NULL,
    cost         DOUBLE NOT NULL,
    pnl          DOUBLE NOT NULL,
    today_bought DOUBLE NOT NULL DEFAULT 0.0,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, symbol)
)
"""

# 订单记录表：每个 order_id 一行
_DDL_ACCOUNT_ORDERS = """
CREATE TABLE IF NOT EXISTS account_orders (
    order_id      VARCHAR(64) PRIMARY KEY,
    account_id    VARCHAR(64) NOT NULL,
    symbol        VARCHAR(20) NOT NULL,
    direction     VARCHAR(10) NOT NULL,
    volume        DOUBLE NOT NULL,
    target_weight REAL,
    price_type    VARCHAR(20) NOT NULL,
    price         REAL,
    status        VARCHAR(20) NOT NULL,
    filled_volume DOUBLE NOT NULL DEFAULT 0.0,
    filled_price  DOUBLE NOT NULL DEFAULT 0.0,
    created_time  TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

# 成交记录表：每个 fill_id 一行
_DDL_ACCOUNT_FILLS = """
CREATE TABLE IF NOT EXISTS account_fills (
    fill_id      VARCHAR(64) PRIMARY KEY,
    account_id   VARCHAR(64) NOT NULL,
    order_id     VARCHAR(64),
    symbol       VARCHAR(20) NOT NULL,
    direction    VARCHAR(10) NOT NULL,
    volume       DOUBLE NOT NULL,
    price        DOUBLE NOT NULL,
    commission   DOUBLE NOT NULL DEFAULT 0.0,
    stamp_tax    DOUBLE NOT NULL DEFAULT 0.0,
    transfer_fee DOUBLE NOT NULL DEFAULT 0.0,
    fill_time    TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

# 每日净值快照表：每个 (account_id, trade_date) 一行
_DDL_ACCOUNT_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS account_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    VARCHAR(64) NOT NULL,
    trade_date    TEXT NOT NULL,
    cash          DOUBLE NOT NULL,
    market_value  DOUBLE NOT NULL,
    total_value   DOUBLE NOT NULL,
    daily_pnl     DOUBLE NOT NULL,
    daily_pnl_pct DOUBLE NOT NULL,
    pnl           DOUBLE NOT NULL,
    pnl_pct       DOUBLE NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, trade_date)
)
"""

_INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_account_orders_account ON account_orders(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_account_fills_account ON account_fills(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_account_snapshots_account ON account_snapshots(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_account_snapshots_date ON account_snapshots(trade_date)",
]


# ---------------------------------------------------------------------------
# PersistenceRepository：持久化仓库
# ---------------------------------------------------------------------------


class PersistenceRepository:
    """账户持久化仓库。

    管理 account_* 5 张表的 CRUD，支持模拟盘/实盘状态持久化与恢复。

    Parameters
    ----------
    db : DatabaseManager
        数据库管理器（需提供 get_connection() 上下文管理器）
    """

    def __init__(self, db: Any):
        self.db = db
        self._tables_ready: bool = False

    # ------------------------------------------------------------------
    # 建表
    # ------------------------------------------------------------------

    def ensure_tables(self) -> None:
        """幂等创建 account_* 5 张表及索引。

        使用 CREATE TABLE IF NOT EXISTS，重复调用安全。
        在首次持久化前调用一次即可。
        """
        if self._tables_ready:
            return
        with self.db.get_connection() as conn:
            for ddl in (
                _DDL_ACCOUNT_INFO,
                _DDL_ACCOUNT_POSITIONS,
                _DDL_ACCOUNT_ORDERS,
                _DDL_ACCOUNT_FILLS,
                _DDL_ACCOUNT_SNAPSHOTS,
            ):
                conn.execute(ddl)
            for idx_ddl in _INDEX_DDL:
                conn.execute(idx_ddl)
        self._tables_ready = True

    # ------------------------------------------------------------------
    # 账户信息
    # ------------------------------------------------------------------

    def save_account_info(
        self,
        account_id: str,
        strategy_name: str,
        info: AccountInfo,
    ) -> None:
        """保存（upsert）账户资金状态。

        Args:
            account_id: 账户ID
            strategy_name: 策略名称
            info: 账户快照
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO account_info
                    (account_id, strategy_name, initial_capital,
                     cash, frozen, total_value, peak_value)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    strategy_name=excluded.strategy_name,
                    initial_capital=excluded.initial_capital,
                    cash=excluded.cash,
                    frozen=excluded.frozen,
                    total_value=excluded.total_value,
                    peak_value=excluded.peak_value,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    account_id,
                    strategy_name,
                    info.initial_capital,
                    info.cash,
                    info.frozen,
                    info.total,
                    info.peak_value,
                ),
            )

    def load_account_info(self, account_id: str) -> Optional[Dict[str, Any]]:
        """加载账户资金状态，不存在返回 None。"""
        self.ensure_tables()
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM account_info WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # 持仓
    # ------------------------------------------------------------------

    def save_positions(
        self,
        account_id: str,
        positions: Dict[str, Position],
    ) -> None:
        """保存全部持仓（先清空旧持仓再写入）。

        Args:
            account_id: 账户ID
            positions: {symbol: Position} 字典
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            # 清空旧持仓
            conn.execute(
                "DELETE FROM account_positions WHERE account_id = ?",
                (account_id,),
            )
            # 写入新持仓
            for symbol, pos in positions.items():
                if pos.quantity <= 1e-9:
                    continue  # 跳过零持仓
                conn.execute(
                    """
                    INSERT INTO account_positions
                        (account_id, symbol, direction, quantity, available,
                         avg_price, market_price, market_value, cost, pnl, today_bought)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_id,
                        symbol,
                        pos.direction.value,
                        pos.quantity,
                        pos.available,
                        pos.avg_price,
                        pos.market_price,
                        pos.market_value,
                        pos.cost,
                        pos.pnl,
                        pos.today_bought,
                    ),
                )

    def load_positions(self, account_id: str) -> Dict[str, Position]:
        """加载全部持仓，返回 {symbol: Position}。"""
        self.ensure_tables()
        positions: Dict[str, Position] = {}
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM account_positions WHERE account_id = ?",
                (account_id,),
            ).fetchall()
            for row in rows:
                r = dict(row)
                positions[r["symbol"]] = Position(
                    symbol=r["symbol"],
                    direction=PositionDirection(r["direction"]),
                    quantity=r["quantity"],
                    available=r["available"],
                    avg_price=r["avg_price"],
                    market_price=r["market_price"],
                    market_value=r["market_value"],
                    cost=r["cost"],
                    pnl=r["pnl"],
                    today_bought=r.get("today_bought", 0.0),
                )
                # 派生字段重算
                positions[r["symbol"]].pnl_pct = (
                    r["pnl"] / r["cost"] if r["cost"] > 0 else 0.0
                )
        return positions

    # ------------------------------------------------------------------
    # 订单
    # ------------------------------------------------------------------

    def save_order(self, account_id: str, order: Order) -> None:
        """保存单条订单（upsert）。"""
        self.ensure_tables()
        created_time = (
            order.created_time.isoformat() if order.created_time else None
        )
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO account_orders
                    (order_id, account_id, symbol, direction, volume,
                     target_weight, price_type, price, status,
                     filled_volume, filled_price, created_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    status=excluded.status,
                    filled_volume=excluded.filled_volume,
                    filled_price=excluded.filled_price
                """,
                (
                    order.order_id,
                    account_id,
                    order.symbol,
                    order.direction.value,
                    order.volume,
                    order.target_weight,
                    order.price_type,
                    order.price,
                    order.status.value,
                    order.filled_volume,
                    order.filled_price,
                    created_time,
                ),
            )

    def load_orders(self, account_id: str) -> List[Dict[str, Any]]:
        """加载全部订单（按创建时间升序）。"""
        self.ensure_tables()
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM account_orders WHERE account_id = ? ORDER BY created_time",
                (account_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 成交
    # ------------------------------------------------------------------

    def save_fill(self, account_id: str, fill: Any) -> None:
        """保存单条成交记录（upsert）。

        Args:
            account_id: 账户ID
            fill: Fill 对象（src.core.types.Fill）
        """
        self.ensure_tables()
        fill_time = fill.fill_time.isoformat() if fill.fill_time else None
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO account_fills
                    (fill_id, account_id, order_id, symbol, direction,
                     volume, price, commission, stamp_tax, transfer_fee, fill_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fill_id) DO UPDATE SET
                    commission=excluded.commission,
                    stamp_tax=excluded.stamp_tax,
                    transfer_fee=excluded.transfer_fee
                """,
                (
                    fill.fill_id,
                    account_id,
                    fill.order_id,
                    fill.symbol,
                    fill.direction.value,
                    fill.volume,
                    fill.price,
                    fill.commission,
                    fill.stamp_tax,
                    fill.transfer_fee,
                    fill_time,
                ),
            )

    def load_fills(self, account_id: str) -> List[Dict[str, Any]]:
        """加载全部成交记录（按成交时间升序）。"""
        self.ensure_tables()
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM account_fills WHERE account_id = ? ORDER BY fill_time",
                (account_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 每日快照
    # ------------------------------------------------------------------

    def save_snapshot(
        self,
        account_id: str,
        trade_date: str,
        snapshot: Dict[str, Any],
    ) -> None:
        """保存每日净值快照（upsert）。

        Args:
            account_id: 账户ID
            trade_date: 交易日（YYYY-MM-DD 字符串）
            snapshot: Portfolio.snapshot() 返回的字典
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO account_snapshots
                    (account_id, trade_date, cash, market_value, total_value,
                     daily_pnl, daily_pnl_pct, pnl, pnl_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, trade_date) DO UPDATE SET
                    cash=excluded.cash,
                    market_value=excluded.market_value,
                    total_value=excluded.total_value,
                    daily_pnl=excluded.daily_pnl,
                    daily_pnl_pct=excluded.daily_pnl_pct,
                    pnl=excluded.pnl,
                    pnl_pct=excluded.pnl_pct
                """,
                (
                    account_id,
                    trade_date,
                    snapshot.get("cash", 0.0),
                    snapshot.get("market_value", 0.0),
                    snapshot.get("total", 0.0),
                    snapshot.get("daily_pnl", 0.0),
                    snapshot.get("daily_pnl_pct", 0.0),
                    snapshot.get("pnl", 0.0),
                    snapshot.get("pnl_pct", 0.0),
                ),
            )

    def load_snapshots(self, account_id: str) -> List[Dict[str, Any]]:
        """加载全部每日快照（按日期升序）。"""
        self.ensure_tables()
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM account_snapshots WHERE account_id = ? ORDER BY trade_date",
                (account_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 批量状态保存/恢复
    # ------------------------------------------------------------------

    def save_account_state(
        self,
        account_id: str,
        strategy_name: str,
        portfolio: Any,
        trade_date: Optional[str] = None,
    ) -> None:
        """批量保存账户全状态（账户信息 + 持仓 + 当日快照）。

        模拟盘/实盘每日收盘后调用。订单和成交在产生时即时保存（调用 save_order/save_fill）。

        Args:
            account_id: 账户ID
            strategy_name: 策略名称
            portfolio: Portfolio 实例
            trade_date: 当日交易日（YYYY-MM-DD），None 时不保存快照
        """
        self.ensure_tables()
        # 保存账户信息
        acct = portfolio.get_account()
        self.save_account_info(account_id, strategy_name, acct)
        # 保存持仓
        self.save_positions(account_id, portfolio.get_active_positions())
        # 保存快照
        if trade_date is not None:
            snapshot = {
                "cash": acct.cash,
                "market_value": acct.market_value,
                "total": acct.total,
                "daily_pnl": acct.daily_pnl,
                "daily_pnl_pct": acct.daily_pnl_pct,
                "pnl": acct.pnl,
                "pnl_pct": acct.pnl_pct,
            }
            self.save_snapshot(account_id, trade_date, snapshot)

    def load_account_state(
        self,
        account_id: str,
        portfolio: Any,
    ) -> bool:
        """从数据库恢复账户全状态到 Portfolio。

        重启模拟盘/实盘时调用，恢复资金/持仓/历史快照。
        订单和成交记录通过 load_orders/load_fills 单独查询（不回填到 Portfolio 内存）。

        Args:
            account_id: 账户ID
            portfolio: 待恢复的 Portfolio 实例

        Returns:
            True 恢复成功，False 账户不存在
        """
        info = self.load_account_info(account_id)
        if info is None:
            return False

        # 恢复资金
        portfolio.initial_capital = info["initial_capital"]
        portfolio.cash = info["cash"]
        portfolio.frozen = info["frozen"]
        portfolio.peak_value = info["peak_value"]
        portfolio._last_total = info["total_value"]

        # 恢复持仓
        portfolio.positions = self.load_positions(account_id)

        # 恢复净值曲线（从历史快照）
        snapshots = self.load_snapshots(account_id)
        portfolio.equity_curve = []
        portfolio.trade_dates = []
        from datetime import datetime as _dt
        for snap in snapshots:
            try:
                ts = _dt.strptime(snap["trade_date"], "%Y-%m-%d")
            except (ValueError, TypeError):
                ts = snap["trade_date"]
            portfolio.equity_curve.append((ts, snap["total_value"]))
            portfolio.trade_dates.append(ts)

        return True

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    def delete_account(self, account_id: str) -> None:
        """删除账户的全部数据（账户/持仓/订单/成交/快照）。"""
        self.ensure_tables()
        with self.db.get_connection() as conn:
            for table in (
                "account_info",
                "account_positions",
                "account_orders",
                "account_fills",
                "account_snapshots",
            ):
                conn.execute(
                    f"DELETE FROM {table} WHERE account_id = ?",
                    (account_id,),
                )
