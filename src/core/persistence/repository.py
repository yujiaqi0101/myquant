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

# 账户信息表：每个 account_id 一行，记录主账户资金状态
# strategy_name 可空（主账户不绑定单一策略，多策略模式下由 account_strategies 管理子账户）
# allocated_capital: 已分配给子账户的资金总额
_DDL_ACCOUNT_INFO = """
CREATE TABLE IF NOT EXISTS account_info (
    account_id        VARCHAR(64) PRIMARY KEY,
    strategy_name     VARCHAR(100),
    initial_capital   DOUBLE NOT NULL,
    cash              DOUBLE NOT NULL,
    allocated_capital DOUBLE NOT NULL DEFAULT 0.0,
    frozen            DOUBLE NOT NULL DEFAULT 0.0,
    total_value       DOUBLE NOT NULL,
    peak_value        DOUBLE NOT NULL,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

# 子账户策略关联表：每个 (account_id, strategy_name) 一行
# 记录主账户下各子账户的资金分配和运行状态
_DDL_ACCOUNT_STRATEGIES = """
CREATE TABLE IF NOT EXISTS account_strategies (
    account_id        VARCHAR(64) NOT NULL,
    strategy_name     VARCHAR(100) NOT NULL,
    allocated_capital DOUBLE NOT NULL,
    cash              DOUBLE NOT NULL,
    total_value       DOUBLE NOT NULL,
    enabled           INTEGER NOT NULL DEFAULT 1,
    last_trade_date   TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, strategy_name)
)
"""

# 持仓快照表：每个 (account_id, strategy_name, symbol) 一行，跨日持久化
_DDL_ACCOUNT_POSITIONS = """
CREATE TABLE IF NOT EXISTS account_positions (
    account_id    VARCHAR(64) NOT NULL,
    strategy_name VARCHAR(100) NOT NULL DEFAULT '',
    symbol        VARCHAR(20) NOT NULL,
    direction     VARCHAR(10) NOT NULL,
    quantity      DOUBLE NOT NULL,
    available     DOUBLE NOT NULL,
    avg_price     DOUBLE NOT NULL,
    market_price  DOUBLE NOT NULL,
    market_value  DOUBLE NOT NULL,
    cost          DOUBLE NOT NULL,
    pnl           DOUBLE NOT NULL,
    today_bought  DOUBLE NOT NULL DEFAULT 0.0,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, strategy_name, symbol)
)
"""

# 订单记录表：每个 order_id 一行
_DDL_ACCOUNT_ORDERS = """
CREATE TABLE IF NOT EXISTS account_orders (
    order_id      VARCHAR(64) PRIMARY KEY,
    account_id    VARCHAR(64) NOT NULL,
    strategy_name VARCHAR(100) NOT NULL DEFAULT '',
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
    strategy_name VARCHAR(100) NOT NULL DEFAULT '',
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

# 每日净值快照表：每个 (account_id, strategy_name, trade_date) 一行
_DDL_ACCOUNT_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS account_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    VARCHAR(64) NOT NULL,
    strategy_name VARCHAR(100) NOT NULL DEFAULT '',
    trade_date    TEXT NOT NULL,
    cash          DOUBLE NOT NULL,
    market_value  DOUBLE NOT NULL,
    total_value   DOUBLE NOT NULL,
    daily_pnl     DOUBLE NOT NULL,
    daily_pnl_pct DOUBLE NOT NULL,
    pnl           DOUBLE NOT NULL,
    pnl_pct       DOUBLE NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, strategy_name, trade_date)
)
"""

_INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_account_orders_account ON account_orders(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_account_fills_account ON account_fills(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_account_snapshots_account ON account_snapshots(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_account_snapshots_date ON account_snapshots(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_account_positions_strategy ON account_positions(account_id, strategy_name)",
    "CREATE INDEX IF NOT EXISTS idx_account_orders_strategy ON account_orders(account_id, strategy_name)",
    "CREATE INDEX IF NOT EXISTS idx_account_fills_strategy ON account_fills(account_id, strategy_name)",
    "CREATE INDEX IF NOT EXISTS idx_account_snapshots_strategy ON account_snapshots(account_id, strategy_name)",
]

# 已有表新增列的升级语句（用于表已存在但缺少新列的场景）
# 格式: (表名, 列名, 列定义)
_ALTER_COLUMNS = [
    ("account_info", "allocated_capital", "DOUBLE NOT NULL DEFAULT 0.0"),
    ("account_positions", "strategy_name", "VARCHAR(100) NOT NULL DEFAULT ''"),
    ("account_orders", "strategy_name", "VARCHAR(100) NOT NULL DEFAULT ''"),
    ("account_fills", "strategy_name", "VARCHAR(100) NOT NULL DEFAULT ''"),
    ("account_snapshots", "strategy_name", "VARCHAR(100) NOT NULL DEFAULT ''"),
    ("account_strategies", "last_trade_date", "TEXT"),
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
        """幂等创建 account_* 6 张表及索引，并升级已有表的新列。

        流程：
            1. CREATE TABLE IF NOT EXISTS 创建全部6张表（含 account_strategies）
            2. 对已有表用 PRAGMA table_info 检查列是否存在，缺失则 ALTER TABLE ADD COLUMN
            3. 创建全部索引

        使用 CREATE TABLE IF NOT EXISTS，重复调用安全。
        """
        if self._tables_ready:
            return
        with self.db.get_connection() as conn:
            # 1. 创建全部6张表
            for ddl in (
                _DDL_ACCOUNT_INFO,
                _DDL_ACCOUNT_STRATEGIES,
                _DDL_ACCOUNT_POSITIONS,
                _DDL_ACCOUNT_ORDERS,
                _DDL_ACCOUNT_FILLS,
                _DDL_ACCOUNT_SNAPSHOTS,
            ):
                conn.execute(ddl)

            # 2. 已有表列升级：检查列是否存在，缺失则 ADD COLUMN
            # SQLite 不支持 IF NOT EXISTS 语法添加列，需先查询 PRAGMA table_info
            for table_name, column_name, column_def in _ALTER_COLUMNS:
                cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
                existing = {row[1] for row in cols}  # row[1] 是列名
                if column_name not in existing:
                    conn.execute(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
                    )

            # 3. 创建索引
            for idx_ddl in _INDEX_DDL:
                conn.execute(idx_ddl)
        self._tables_ready = True

    # ------------------------------------------------------------------
    # 主账户管理（不绑定具体策略）
    # ------------------------------------------------------------------

    def init_main_account(
        self,
        account_id: str,
        initial_capital: float,
    ) -> bool:
        """创建主账户（不绑定策略）。

        主账户独立存在，资金通过 deposit/withdraw 充值提取，
        再通过 add_strategy 分配给子账户。

        Args:
            account_id: 账户ID（用户自定义，唯一）
            initial_capital: 初始资金

        Returns:
            True 创建成功，False 账户已存在
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            existing = conn.execute(
                "SELECT 1 FROM account_info WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if existing:
                return False
            conn.execute(
                """
                INSERT INTO account_info
                    (account_id, strategy_name, initial_capital,
                     cash, allocated_capital, frozen, total_value, peak_value)
                VALUES (?, NULL, ?, ?, 0.0, 0.0, ?, ?)
                """,
                (
                    account_id,
                    initial_capital,
                    initial_capital,
                    initial_capital,
                    initial_capital,
                ),
            )
        return True

    def deposit_main_account(self, account_id: str, amount: float) -> bool:
        """主账户充值（增加现金和总资金）。

        Args:
            account_id: 账户ID
            amount: 充值金额（正数）

        Returns:
            True 成功，False 账户不存在或金额非法
        """
        if amount <= 0:
            return False
        self.ensure_tables()
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT cash, total_value, peak_value FROM account_info WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return False
            new_cash = row["cash"] + amount
            new_total = row["total_value"] + amount
            new_peak = max(row["peak_value"], new_total)
            conn.execute(
                """
                UPDATE account_info
                SET cash = ?, total_value = ?, peak_value = ?, updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ?
                """,
                (new_cash, new_total, new_peak, account_id),
            )
        return True

    def withdraw_main_account(self, account_id: str, amount: float) -> bool:
        """主账户提取（减少现金和总资金）。

        只能提取未分配给子账户的可用现金（cash - allocated_capital）。

        Args:
            account_id: 账户ID
            amount: 提取金额（正数）

        Returns:
            True 成功，False 账户不存在/金额非法/可用现金不足
        """
        if amount <= 0:
            return False
        self.ensure_tables()
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT cash, total_value, allocated_capital FROM account_info WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return False
            # 可用现金 = 总现金 - 已分配给子账户的资金
            available = row["cash"] - row["allocated_capital"]
            if amount > available:
                return False
            new_cash = row["cash"] - amount
            new_total = row["total_value"] - amount
            conn.execute(
                """
                UPDATE account_info
                SET cash = ?, total_value = ?, updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ?
                """,
                (new_cash, new_total, account_id),
            )
        return True

    def get_main_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        """查询主账户信息（含已分配/可用资金）。"""
        self.ensure_tables()
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM account_info WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return None
            data = dict(row)
            # 派生字段：可用资金 = 现金 - 已分配
            data["available_capital"] = data["cash"] - data["allocated_capital"]
            return data

    def list_main_accounts(self) -> List[Dict[str, Any]]:
        """列出全部主账户。"""
        self.ensure_tables()
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM account_info ORDER BY account_id"
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                data["available_capital"] = data["cash"] - data["allocated_capital"]
                result.append(data)
            return result

    # ------------------------------------------------------------------
    # 子账户策略管理（account_strategies CRUD）
    # ------------------------------------------------------------------

    def add_strategy(
        self,
        account_id: str,
        strategy_name: str,
        allocated_capital: float,
    ) -> bool:
        """为主账户添加子账户（绑定策略并分配资金）。

        资金从主账户现金转入子账户：
            1. 检查主账户可用现金 >= allocated_capital
            2. 在 account_strategies 插入子账户记录
            3. 主账户 cash 不变，allocated_capital += allocated_capital
            （子账户资金独立记账，主账户现金是"总现金"，allocated_capital 是"已冻结分配"）

        Args:
            account_id: 主账户ID
            strategy_name: 策略名称
            allocated_capital: 分配给该子账户的资金

        Returns:
            True 成功，False 主账户不存在/可用资金不足/子账户已存在
        """
        if allocated_capital <= 0:
            return False
        self.ensure_tables()
        with self.db.get_connection() as conn:
            # 检查主账户
            row = conn.execute(
                "SELECT cash, allocated_capital FROM account_info WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if row is None:
                return False
            available = row["cash"] - row["allocated_capital"]
            if allocated_capital > available:
                return False
            # 检查子账户是否已存在
            existing = conn.execute(
                "SELECT 1 FROM account_strategies WHERE account_id = ? AND strategy_name = ?",
                (account_id, strategy_name),
            ).fetchone()
            if existing:
                return False
            # 插入子账户
            conn.execute(
                """
                INSERT INTO account_strategies
                    (account_id, strategy_name, allocated_capital,
                     cash, total_value, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    account_id,
                    strategy_name,
                    allocated_capital,
                    allocated_capital,
                    allocated_capital,
                ),
            )
            # 更新主账户已分配资金
            new_allocated = row["allocated_capital"] + allocated_capital
            conn.execute(
                """
                UPDATE account_info
                SET allocated_capital = ?, updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ?
                """,
                (new_allocated, account_id),
            )
        return True

    def remove_strategy(
        self,
        account_id: str,
        strategy_name: str,
    ) -> Optional[float]:
        """彻底删除子账户（含持仓/订单/成交/快照）。

        资金回收：子账户剩余资金（cash）返还主账户，从 allocated_capital 扣除。

        Args:
            account_id: 主账户ID
            strategy_name: 策略名称

        Returns:
            返回回收的资金金额，None 子账户不存在
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            # 查询子账户剩余资金
            row = conn.execute(
                "SELECT cash, allocated_capital FROM account_strategies WHERE account_id = ? AND strategy_name = ?",
                (account_id, strategy_name),
            ).fetchone()
            if row is None:
                return None
            recovered = row["cash"]
            original_allocated = row["allocated_capital"]
            # 删除子账户全部数据
            conn.execute(
                "DELETE FROM account_positions WHERE account_id = ? AND strategy_name = ?",
                (account_id, strategy_name),
            )
            conn.execute(
                "DELETE FROM account_orders WHERE account_id = ? AND strategy_name = ?",
                (account_id, strategy_name),
            )
            conn.execute(
                "DELETE FROM account_fills WHERE account_id = ? AND strategy_name = ?",
                (account_id, strategy_name),
            )
            conn.execute(
                "DELETE FROM account_snapshots WHERE account_id = ? AND strategy_name = ?",
                (account_id, strategy_name),
            )
            conn.execute(
                "DELETE FROM account_strategies WHERE account_id = ? AND strategy_name = ?",
                (account_id, strategy_name),
            )
            # 主账户 allocated_capital 减少，现金不变（资金已在子账户 cash 中，回收等于主账户总现金恢复）
            # 实际上：主账户 cash 一直是"总现金"，allocated_capital 是"已分配"，
            # 删除子账户后 allocated_capital -= original_allocated，cash 不需要变（资金回流自动反映在 total_value 上）
            # 但为了精确，主账户 total_value 需要重新计算（= cash + sum(子账户total_value) - allocated_capital + allocated_capital）
            # 简化处理：allocated_capital 减少，total_value 同步减少（因为该子账户资金已消失）
            conn.execute(
                """
                UPDATE account_info
                SET allocated_capital = allocated_capital - ?,
                    total_value = total_value - ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ?
                """,
                (original_allocated, recovered, account_id),
            )
        return recovered

    def disable_strategy(
        self,
        account_id: str,
        strategy_name: str,
    ) -> bool:
        """停用子账户（停止运行策略，但保留历史数据和资金记录）。

        停用后该子账户不再参与运行，但历史持仓/快照可查询，资金仍冻结。

        Args:
            account_id: 主账户ID
            strategy_name: 策略名称

        Returns:
            True 成功，False 子账户不存在
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE account_strategies
                SET enabled = 0, updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ? AND strategy_name = ?
                """,
                (account_id, strategy_name),
            )
            return cur.rowcount > 0

    def enable_strategy(
        self,
        account_id: str,
        strategy_name: str,
    ) -> bool:
        """启用已停用的子账户。

        Args:
            account_id: 主账户ID
            strategy_name: 策略名称

        Returns:
            True 成功，False 子账户不存在
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE account_strategies
                SET enabled = 1, updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ? AND strategy_name = ?
                """,
                (account_id, strategy_name),
            )
            return cur.rowcount > 0

    def list_strategies(
        self,
        account_id: str,
        enabled_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """列出主账户下的全部子账户。

        Args:
            account_id: 主账户ID
            enabled_only: True 仅返回启用的子账户

        Returns:
            子账户列表，每项含 strategy_name/allocated_capital/cash/total_value/enabled
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            if enabled_only:
                rows = conn.execute(
                    """
                    SELECT * FROM account_strategies
                    WHERE account_id = ? AND enabled = 1
                    ORDER BY created_at
                    """,
                    (account_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM account_strategies
                    WHERE account_id = ?
                    ORDER BY created_at
                    """,
                    (account_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_strategy(
        self,
        account_id: str,
        strategy_name: str,
    ) -> Optional[Dict[str, Any]]:
        """查询单个子账户信息。"""
        self.ensure_tables()
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM account_strategies
                WHERE account_id = ? AND strategy_name = ?
                """,
                (account_id, strategy_name),
            ).fetchone()
            return dict(row) if row else None

    def update_strategy_state(
        self,
        account_id: str,
        strategy_name: str,
        cash: float,
        total_value: float,
        trade_date: Optional[str] = None,
    ) -> None:
        """更新子账户资金状态（模拟盘每日运行后调用）。

        Args:
            account_id: 主账户ID
            strategy_name: 策略名称
            cash: 子账户当前现金
            total_value: 子账户当前总资产
            trade_date: 当日交易日（YYYY-MM-DD），写入 last_trade_date 便于补记录
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            if trade_date is not None:
                conn.execute(
                    """
                    UPDATE account_strategies
                    SET cash = ?, total_value = ?, last_trade_date = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE account_id = ? AND strategy_name = ?
                    """,
                    (cash, total_value, trade_date, account_id, strategy_name),
                )
            else:
                conn.execute(
                    """
                    UPDATE account_strategies
                    SET cash = ?, total_value = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE account_id = ? AND strategy_name = ?
                    """,
                    (cash, total_value, account_id, strategy_name),
                )

    # ------------------------------------------------------------------
    # 账户信息（旧接口，保留兼容；多策略模式下主账户用 init_main_account/deposit/withdraw）
    # ------------------------------------------------------------------

    def save_account_info(
        self,
        account_id: str,
        strategy_name: str,
        info: AccountInfo,
    ) -> None:
        """保存（upsert）账户资金状态。

        兼容旧接口，多策略模式下主账户的资金通过 init_main_account/deposit/withdraw 管理。

        Args:
            account_id: 账户ID
            strategy_name: 策略名称（可空）
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
    # 持仓（按 strategy_name 隔离）
    # ------------------------------------------------------------------

    def save_positions(
        self,
        account_id: str,
        positions: Dict[str, Position],
        strategy_name: str = "",
    ) -> None:
        """保存全部持仓（先清空该子账户旧持仓再写入）。

        Args:
            account_id: 账户ID
            positions: {symbol: Position} 字典
            strategy_name: 策略名称（子账户标识，默认空字符串兼容旧调用）
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            # 清空该子账户的旧持仓（仅删除当前 strategy_name 的，不影响其他子账户）
            conn.execute(
                "DELETE FROM account_positions WHERE account_id = ? AND strategy_name = ?",
                (account_id, strategy_name),
            )
            # 写入新持仓
            for symbol, pos in positions.items():
                if pos.quantity <= 1e-9:
                    continue  # 跳过零持仓
                conn.execute(
                    """
                    INSERT INTO account_positions
                        (account_id, strategy_name, symbol, direction, quantity, available,
                         avg_price, market_price, market_value, cost, pnl, today_bought)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_id,
                        strategy_name,
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

    def load_positions(
        self,
        account_id: str,
        strategy_name: Optional[str] = None,
    ) -> Dict[str, Position]:
        """加载持仓，返回 {symbol: Position}。

        Args:
            account_id: 账户ID
            strategy_name: 策略名称。
                None - 加载该账户全部持仓（跨策略合并）
                ""或具体值 - 仅加载指定子账户的持仓
        """
        self.ensure_tables()
        positions: Dict[str, Position] = {}
        with self.db.get_connection() as conn:
            if strategy_name is None:
                rows = conn.execute(
                    "SELECT * FROM account_positions WHERE account_id = ?",
                    (account_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM account_positions WHERE account_id = ? AND strategy_name = ?",
                    (account_id, strategy_name),
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
    # 订单（按 strategy_name 隔离）
    # ------------------------------------------------------------------

    def save_order(
        self,
        account_id: str,
        order: Order,
        strategy_name: str = "",
    ) -> None:
        """保存单条订单（upsert）。

        Args:
            account_id: 账户ID
            order: 订单对象
            strategy_name: 策略名称（子账户标识）
        """
        self.ensure_tables()
        created_time = (
            order.created_time.isoformat() if order.created_time else None
        )
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO account_orders
                    (order_id, account_id, strategy_name, symbol, direction, volume,
                     target_weight, price_type, price, status,
                     filled_volume, filled_price, created_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    status=excluded.status,
                    filled_volume=excluded.filled_volume,
                    filled_price=excluded.filled_price
                """,
                (
                    order.order_id,
                    account_id,
                    strategy_name,
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

    def load_orders(
        self,
        account_id: str,
        strategy_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """加载订单（按创建时间升序）。

        Args:
            account_id: 账户ID
            strategy_name: None 加载全部，""或具体值仅加载指定子账户
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            if strategy_name is None:
                rows = conn.execute(
                    "SELECT * FROM account_orders WHERE account_id = ? ORDER BY created_time",
                    (account_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM account_orders WHERE account_id = ? AND strategy_name = ? ORDER BY created_time",
                    (account_id, strategy_name),
                ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 成交（按 strategy_name 隔离）
    # ------------------------------------------------------------------

    def save_fill(
        self,
        account_id: str,
        fill: Any,
        strategy_name: str = "",
    ) -> None:
        """保存单条成交记录（upsert）。

        Args:
            account_id: 账户ID
            fill: Fill 对象（src.core.types.Fill）
            strategy_name: 策略名称（子账户标识）
        """
        self.ensure_tables()
        fill_time = fill.fill_time.isoformat() if fill.fill_time else None
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO account_fills
                    (fill_id, account_id, strategy_name, order_id, symbol, direction,
                     volume, price, commission, stamp_tax, transfer_fee, fill_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fill_id) DO UPDATE SET
                    commission=excluded.commission,
                    stamp_tax=excluded.stamp_tax,
                    transfer_fee=excluded.transfer_fee
                """,
                (
                    fill.fill_id,
                    account_id,
                    strategy_name,
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

    def load_fills(
        self,
        account_id: str,
        strategy_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """加载成交记录（按成交时间升序）。

        Args:
            account_id: 账户ID
            strategy_name: None 加载全部，""或具体值仅加载指定子账户
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            if strategy_name is None:
                rows = conn.execute(
                    "SELECT * FROM account_fills WHERE account_id = ? ORDER BY fill_time",
                    (account_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM account_fills WHERE account_id = ? AND strategy_name = ? ORDER BY fill_time",
                    (account_id, strategy_name),
                ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 每日快照（按 strategy_name 隔离）
    # ------------------------------------------------------------------

    def save_snapshot(
        self,
        account_id: str,
        trade_date: str,
        snapshot: Dict[str, Any],
        strategy_name: str = "",
    ) -> None:
        """保存每日净值快照（upsert）。

        Args:
            account_id: 账户ID
            trade_date: 交易日（YYYY-MM-DD 字符串）
            snapshot: Portfolio.snapshot() 返回的字典
            strategy_name: 策略名称（子账户标识）
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO account_snapshots
                    (account_id, strategy_name, trade_date, cash, market_value, total_value,
                     daily_pnl, daily_pnl_pct, pnl, pnl_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, strategy_name, trade_date) DO UPDATE SET
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
                    strategy_name,
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

    def load_snapshots(
        self,
        account_id: str,
        strategy_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """加载每日快照（按日期升序）。

        Args:
            account_id: 账户ID
            strategy_name: None 加载全部，""或具体值仅加载指定子账户
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            if strategy_name is None:
                rows = conn.execute(
                    "SELECT * FROM account_snapshots WHERE account_id = ? ORDER BY trade_date",
                    (account_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM account_snapshots WHERE account_id = ? AND strategy_name = ? ORDER BY trade_date",
                    (account_id, strategy_name),
                ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 批量状态保存/恢复（按 strategy_name 隔离子账户）
    # ------------------------------------------------------------------

    def save_account_state(
        self,
        account_id: str,
        strategy_name: str,
        portfolio: Any,
        trade_date: Optional[str] = None,
    ) -> None:
        """批量保存子账户全状态（持仓 + 当日快照 + 更新子账户资金）。

        多策略模式下，子账户（account_strategies）的资金状态通过 update_strategy_state 更新，
        主账户（account_info）的资金由各子账户汇总计算（不在此处保存）。

        Args:
            account_id: 主账户ID
            strategy_name: 子账户策略名称
            portfolio: 该子账户的 Portfolio 实例
            trade_date: 当日交易日（YYYY-MM-DD），None 时不保存快照
        """
        self.ensure_tables()
        acct = portfolio.get_account()
        # 保存持仓（带 strategy_name）
        self.save_positions(account_id, portfolio.get_active_positions(), strategy_name)
        # 保存快照（带 strategy_name）
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
            self.save_snapshot(account_id, trade_date, snapshot, strategy_name)
        # 更新子账户资金状态
        self.update_strategy_state(account_id, strategy_name, acct.cash, acct.total, trade_date)

    def load_account_state(
        self,
        account_id: str,
        strategy_name: str,
        portfolio: Any,
    ) -> bool:
        """从数据库恢复指定子账户状态到 Portfolio。

        重启模拟盘时调用，恢复该子账户的资金/持仓/历史快照。

        Args:
            account_id: 主账户ID
            strategy_name: 子账户策略名称
            portfolio: 待恢复的 Portfolio 实例

        Returns:
            True 恢复成功，False 子账户不存在
        """
        # 从 account_strategies 读取子账户资金
        strat = self.get_strategy(account_id, strategy_name)
        if strat is None:
            return False

        # 恢复资金（用子账户的 allocated_capital 作为 initial_capital）
        portfolio.initial_capital = strat["allocated_capital"]
        portfolio.cash = strat["cash"]
        portfolio.frozen = 0.0
        portfolio.peak_value = strat["total_value"]
        portfolio._last_total = strat["total_value"]

        # 恢复持仓（仅该子账户的）
        portfolio.positions = self.load_positions(account_id, strategy_name)

        # 恢复净值曲线（从该子账户历史快照）
        snapshots = self.load_snapshots(account_id, strategy_name)
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
        """删除主账户的全部数据（含所有子账户）。

        危险操作：会级联删除该账户下的所有策略子账户、持仓、订单、成交、快照。
        通常应使用 remove_strategy 逐个删除子账户，仅在销户时调用本方法。
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            for table in (
                "account_info",
                "account_strategies",
                "account_positions",
                "account_orders",
                "account_fills",
                "account_snapshots",
            ):
                conn.execute(
                    f"DELETE FROM {table} WHERE account_id = ?",
                    (account_id,),
                )

    def reset_strategy(
        self,
        account_id: str,
        strategy_name: str,
        new_capital: Optional[float] = None,
    ) -> bool:
        """重置子账户（清空持仓/订单/成交/快照，资金回到初始或指定金额）。

        用于子账户策略重新开始模拟。

        Args:
            account_id: 主账户ID
            strategy_name: 子账户策略名称
            new_capital: 重置后的资金，None 用原 allocated_capital

        Returns:
            True 成功，False 子账户不存在
        """
        self.ensure_tables()
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT allocated_capital FROM account_strategies WHERE account_id = ? AND strategy_name = ?",
                (account_id, strategy_name),
            ).fetchone()
            if row is None:
                return False
            capital = new_capital if new_capital is not None else row["allocated_capital"]
            # 清空该子账户全部业务数据
            for table in ("account_positions", "account_orders", "account_fills", "account_snapshots"):
                conn.execute(
                    f"DELETE FROM {table} WHERE account_id = ? AND strategy_name = ?",
                    (account_id, strategy_name),
                )
            # 重置子账户资金
            conn.execute(
                """
                UPDATE account_strategies
                SET cash = ?, total_value = ?, updated_at = CURRENT_TIMESTAMP
                WHERE account_id = ? AND strategy_name = ?
                """,
                (capital, capital, account_id, strategy_name),
            )
        return True

    def adjust_strategy_capital(
        self,
        account_id: str,
        strategy_name: str,
        delta: float,
    ) -> bool:
        """调整子账户资金（追加或减少分配资金）。

        delta > 0：从主账户可用现金追加分配给子账户
        delta < 0：从子账户回收资金到主账户

        Args:
            account_id: 主账户ID
            strategy_name: 子账户策略名称
            delta: 资金变动量（正追加，负回收）

        Returns:
            True 成功，False 子账户不存在/主账户可用资金不足/子账户现金不足
        """
        if abs(delta) < 1e-9:
            return True
        self.ensure_tables()
        with self.db.get_connection() as conn:
            # 检查子账户
            strat = conn.execute(
                "SELECT cash, allocated_capital, total_value FROM account_strategies WHERE account_id = ? AND strategy_name = ?",
                (account_id, strategy_name),
            ).fetchone()
            if strat is None:
                return False
            # 检查主账户
            main = conn.execute(
                "SELECT cash, allocated_capital FROM account_info WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if main is None:
                return False

            if delta > 0:
                # 追加：检查主账户可用现金
                available = main["cash"] - main["allocated_capital"]
                if delta > available:
                    return False
                # 主账户 allocated_capital 增加
                conn.execute(
                    "UPDATE account_info SET allocated_capital = allocated_capital + ?, updated_at = CURRENT_TIMESTAMP WHERE account_id = ?",
                    (delta, account_id),
                )
                # 子账户资金增加
                new_cash = strat["cash"] + delta
                new_allocated = strat["allocated_capital"] + delta
                new_total = strat["total_value"] + delta
                conn.execute(
                    "UPDATE account_strategies SET cash = ?, allocated_capital = ?, total_value = ?, updated_at = CURRENT_TIMESTAMP WHERE account_id = ? AND strategy_name = ?",
                    (new_cash, new_allocated, new_total, account_id, strategy_name),
                )
            else:
                abs_delta = -delta
                # 回收：检查子账户现金
                if abs_delta > strat["cash"]:
                    return False
                # 主账户 allocated_capital 减少
                conn.execute(
                    "UPDATE account_info SET allocated_capital = allocated_capital - ?, updated_at = CURRENT_TIMESTAMP WHERE account_id = ?",
                    (abs_delta, account_id),
                )
                # 子账户资金减少
                new_cash = strat["cash"] - abs_delta
                new_allocated = max(0.0, strat["allocated_capital"] - abs_delta)
                new_total = strat["total_value"] - abs_delta
                conn.execute(
                    "UPDATE account_strategies SET cash = ?, allocated_capital = ?, total_value = ?, updated_at = CURRENT_TIMESTAMP WHERE account_id = ? AND strategy_name = ?",
                    (new_cash, new_allocated, new_total, account_id, strategy_name),
                )
        return True
