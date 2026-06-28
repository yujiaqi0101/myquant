"""
DataAdapter — myquant 数据库格式与 quantlab Dict 格式互转。

quantlab 引擎（BarEngine / EventEngine / VectorBTAdapter）要求数据格式：
    data: Dict[symbol, DataFrame]
    每个 DataFrame:
        - index   : pd.DatetimeIndex（单调递增）
        - columns : 必须含 open / close（其他列任意）
        - 兼容性：pre_close / suspend_flag / list_date 等列透传

myquant 现有数据是 MultiIndex(trade_date, stock_code)，来自 stock_daily 表。
本模块提供两种入口：
    - to_quantlab_dict(multiindex_df)  : MultiIndex → Dict
    - from_quantlab_db(db_path, ...)   : 直接从 SQLite 读，绕过 MultiIndex
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _convert_eastmoney_code(code: str) -> str:
    """
    东财掘金代码格式 → myquant标准格式
    SHSE.600000 → 600000.SH
    SZSE.000001 → 000001.SZ
    BJSE.430047 → 430047.BJ
    """
    if '.' in code:
        parts = code.split('.')
        if len(parts) == 2:
            exch, num = parts[0], parts[1]
            if exch == 'SHSE':
                return f'{num}.SH'
            elif exch == 'SZSE':
                return f'{num}.SZ'
            elif exch == 'BJSE':
                return f'{num}.BJ'
    return code


# quantlab / quantlab_extras 实际访问的列名清单
#  - open / close  : BarEngine 撮合使用
#  - pre_close     : LimitUpCheck / LimitDownCheck
#  - suspend_flag  : SuspendCheck
#  - list_date     : NewStockCheck（来自 stock_info）
#  - stock_name    : STFilterCheck（来自 stock_info）
#  - market_cap / amount : v2 策略选股条件
DEFAULT_REQUIRED_COLS = ["open", "close", "pre_close"]


def to_quantlab_dict(
    multiindex_df: pd.DataFrame,
    code_col: str = "stock_code",
    date_col: str = "trade_date",
    keep_cols: Optional[List[str]] = None,
) -> Dict[str, pd.DataFrame]:
    """
    myquant MultiIndex DataFrame → quantlab Dict[symbol, DataFrame]。

    Parameters
    ----------
    multiindex_df : pd.DataFrame
        来自 myquant stock_daily 查询的 DataFrame
        索引必须是 (date, symbol) MultiIndex，或至少含 date_col / code_col 两列
    code_col : str
        股票代码列名（默认 stock_code）
    date_col : str
        日期列名（默认 trade_date）
    keep_cols : list[str] | None
        额外透传的列（如 market_cap / amount / industry / market_cap）
        None = 透传所有列

    Returns
    -------
    Dict[str, pd.DataFrame]
        {symbol: DataFrame}，每只股票一个独立 DataFrame

    Raises
    ------
    ValueError
        输入 DataFrame 缺少必要列
    """
    if multiindex_df is None or multiindex_df.empty:
        return {}

    df = multiindex_df.copy()

    # ---- 1) 把 MultiIndex 拆回列 ----
    if isinstance(df.index, pd.MultiIndex):
        if df.index.nlevels != 2:
            raise ValueError(
                f"MultiIndex 必须是 2 级 (date, symbol)，"
                f"实际 {df.index.nlevels} 级"
            )
        df = df.reset_index()
    elif isinstance(df.index, pd.DatetimeIndex):
        # 已经是单 symbol 的 DataFrame → 直接包一层
        sym = df.attrs.get("symbol", "UNKNOWN")
        df = df.reset_index()
        df[code_col] = sym
    else:
        # RangeIndex / 其他
        if date_col not in df.columns or code_col not in df.columns:
            raise ValueError(
                f"DataFrame 缺 {date_col} / {code_col} 列"
            )

    # ---- 2) 列重命名 / 校验 ----
    if date_col not in df.columns:
        raise ValueError(f"DataFrame 缺 {date_col} 列")
    if code_col not in df.columns:
        raise ValueError(f"DataFrame 缺 {code_col} 列")

    df[date_col] = pd.to_datetime(df[date_col])

    # ---- 3) 决定保留哪些列 ----
    base_cols = [date_col, code_col]
    if keep_cols is None:
        # 透传除 base_cols 外的所有列
        pass_cols = [c for c in df.columns if c not in base_cols]
    else:
        pass_cols = list(keep_cols)

    # 必需列必须存在（缺失用 NaN 占位，BarEngine 跳过即可）
    for col in DEFAULT_REQUIRED_COLS:
        if col not in pass_cols and col in df.columns:
            pass_cols.append(col)

    slim = df[base_cols + pass_cols].copy()

    # ---- 4) 按 symbol 分组 → Dict ----
    out: Dict[str, pd.DataFrame] = {}
    for sym, sub in slim.groupby(code_col, sort=False):
        sub = sub.drop(columns=[code_col]).set_index(date_col)
        sub = sub.sort_index()

        # 校验：DatetimeIndex 单调递增
        if not isinstance(sub.index, pd.DatetimeIndex):
            sub.index = pd.to_datetime(sub.index)
        if not sub.index.is_monotonic_increasing:
            sub = sub.sort_index()

        # 标注 symbol（方便调试）
        sub.attrs["symbol"] = sym
        out[str(sym)] = sub

    logger.info(
        "to_quantlab_dict: %d 行 → %d 个 symbol",
        len(multiindex_df),
        len(out),
    )
    return out


def from_quantlab_db(
    db_path: str,
    start_date: str,
    end_date: str,
    stock_codes: Optional[List[str]] = None,
    fields: Optional[List[str]] = None,
    enrich_stock_info: bool = True,
    db=None,
) -> Dict[str, pd.DataFrame]:
    """
    直接从 myquant SQLite 数据库读数据，转 quantlab Dict[symbol, DataFrame]。

    比 to_quantlab_dict(MultiIndex) 更高效（避免先 group 再拆列）。
    合并的表：
    - t_stock_daily：行情数据（open/high/low/close/volume/pre_close等）
    - t_stock_info：基本信息（list_date/stock_name）
    - t_valuation_data：估值数据（pb）
    - t_finance_prime：主要财务指标（roe/revenue_growth）
    - t_stock_mktvalue：每日市值（market_cap = a_mv，流通市值）
    - t_stock_in_sw：申万行业分类（industry_l1/industry_l2/industry_l3）
    - t_finance_deriv：财务衍生指标（eps/bps等）

    Parameters
    ----------
    db_path : str
        SQLite 数据库路径
    start_date / end_date : str
        'YYYY-MM-DD' 格式
    stock_codes : list[str] | None
        指定股票代码；None = 全市场
    fields : list[str] | None
        显式指定要读的列；None = 读所有
    enrich_stock_info : bool
        是否从 stock_info 表合并 list_date / stock_name（RiskCheck 需要）
        默认 True

    Returns
    -------
    Dict[str, pd.DataFrame]
    """
    from src.data.database import DatabaseManager

    if db is None:
        db = DatabaseManager(db_path)
    df = db.get_stock_daily(
        stock_codes=stock_codes,
        start_date=start_date,
        end_date=end_date,
        fields=fields,
    )

    if df.empty:
        return {}

    # ---- 合并 stock_info（list_date / stock_name） ----
    if enrich_stock_info:
        try:
            info_df = db.get_stock_info_filtered()
        except Exception:
            info_df = pd.DataFrame()

        if not info_df.empty:
            df = df.reset_index()
            df = df.merge(
                info_df[["stock_code", "list_date", "stock_name"]],
                on="stock_code",
                how="left",
            )
            # 转回 MultiIndex
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.set_index(["trade_date", "stock_code"])

    # ---- 合并申万行业分类（industry_l1/l2/l3，静态数据） ----
    if enrich_stock_info:
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            sw_df = pd.read_sql_query(
                "SELECT stock_code, industry_l1, industry_l2, industry_l3 "
                "FROM t_stock_in_sw",
                conn,
            )
            conn.close()
            if not sw_df.empty:
                df = df.reset_index()
                df = df.merge(sw_df, on="stock_code", how="left")
                df = df.set_index(["trade_date", "stock_code"])
        except Exception:
            pass

    # ---- 合并估值数据（pb）按 trade_date + stock_code join + ffill ----
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        val_df = pd.read_sql_query(
            "SELECT trade_date, stock_code, pb_mrq "
            "FROM t_valuation_data "
            "WHERE trade_date >= ? AND trade_date <= ?",
            conn,
            params=[start_date, end_date],
        )
        conn.close()
        if not val_df.empty:
            val_df.rename(columns={
                "pb_mrq": "pb",
            }, inplace=True)
            val_df["trade_date"] = pd.to_datetime(val_df["trade_date"])
            df = df.reset_index()
            df = df.merge(val_df, on=["trade_date", "stock_code"], how="left")
            # 按 stock_code 分组 ffill + bfill（估值数据可能只有部分日期有值）
            df = df.sort_values(["stock_code", "trade_date"])
            df[["pb"]] = df.groupby("stock_code")[["pb"]].ffill()
            df[["pb"]] = df.groupby("stock_code")[["pb"]].bfill()
            df = df.set_index(["trade_date", "stock_code"])
    except Exception:
        pass

    # ---- 合并每日市值（market_cap = a_mv，流通市值）按 trade_date + stock_code join ----
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        mkt_df = pd.read_sql_query(
            "SELECT trade_date, stock_code, a_mv "
            "FROM t_stock_mktvalue "
            "WHERE trade_date >= ? AND trade_date <= ?",
            conn,
            params=[start_date, end_date],
        )
        conn.close()
        if not mkt_df.empty:
            mkt_df.rename(columns={"a_mv": "market_cap"}, inplace=True)
            # 东财代码格式转换：SHSE.600000 → 600000.SH
            mkt_df['stock_code'] = mkt_df['stock_code'].apply(_convert_eastmoney_code)
            mkt_df["trade_date"] = pd.to_datetime(mkt_df["trade_date"])
            df = df.reset_index()
            df = df.merge(mkt_df, on=["trade_date", "stock_code"], how="left")
            # 按 stock_code 分组 ffill + bfill（市值数据可能部分日期缺失）
            df = df.sort_values(["stock_code", "trade_date"])
            df[["market_cap"]] = df.groupby("stock_code")[["market_cap"]].ffill()
            df[["market_cap"]] = df.groupby("stock_code")[["market_cap"]].bfill()
            df = df.set_index(["trade_date", "stock_code"])
    except Exception:
        pass

    # ---- 合并财务数据（roe / revenue_growth）取最近报告期 ----
    # t_finance_prime 的 stock_code 格式是 SHSE.600000，需转换为 600000.SH
    try:
        fin_df = db.get_financial_data(stock_codes=stock_codes)
        if fin_df is not None and not fin_df.empty:
            fin_df = fin_df.copy()
            fin_df['stock_code'] = fin_df['stock_code'].apply(_convert_eastmoney_code)
            # 取每只股票最近一期的 roe 和 inc_oper_yoy
            fin_latest = fin_df.sort_values("rpt_date").groupby("stock_code").last().reset_index()
            fin_latest = fin_latest[["stock_code", "roe", "inc_oper_yoy"]].copy()
            fin_latest.rename(columns={"inc_oper_yoy": "revenue_growth"}, inplace=True)
            df = df.reset_index()
            df = df.merge(fin_latest, on="stock_code", how="left")
            df = df.set_index(["trade_date", "stock_code"])
    except Exception:
        pass

    # ---- 合并财务衍生指标（eps / bps / 各类同比增长）取最近报告期 ----
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        # t_finance_deriv 股票代码格式同样是 SHSE.600000 格式
        deriv_df = pd.read_sql_query(
            "SELECT stock_code, rpt_date, "
            "eps_basic, eps_dil, bps, roe_weight, "
            "net_cf_oper_ps, ocf_toi, "
            "eps_dil_yoy, inc_oper_yoy, net_prof_pcom_yoy "
            "FROM t_finance_deriv "
            "WHERE rpt_date <= ?",
            conn,
            params=[end_date],
        )
        conn.close()
        if not deriv_df.empty:
            deriv_df = deriv_df.copy()
            deriv_df['stock_code'] = deriv_df['stock_code'].apply(_convert_eastmoney_code)
            # 取每只股票最近一期数据
            deriv_latest = deriv_df.sort_values("rpt_date").groupby("stock_code").last().reset_index()
            deriv_latest = deriv_latest.drop(columns=["rpt_date"])
            df = df.reset_index()
            df = df.merge(deriv_latest, on="stock_code", how="left")
            df = df.set_index(["trade_date", "stock_code"])
    except Exception:
        pass

    return to_quantlab_dict(df)


# ============ ETF 数据加载 ============

def from_etf_db(
    db_path: str,
    start_date: str,
    end_date: str,
    etf_codes: Optional[List[str]] = None,
    fields: Optional[List[str]] = None,
    enrich_etf_info: bool = True,
    db=None,
) -> Dict[str, pd.DataFrame]:
    """
    从 myquant SQLite 数据库读取 ETF 日频行情，转 quantlab Dict[symbol, DataFrame]。

    合并的表：
    - t_etf_daily：ETF 日频行情（open/high/low/close/volume/amount/pre_close/vwap）
    - t_etf_info：ETF 基础信息（etf_name/listed_date/delisted_date/benchmark_index/fund_type/management_fee）

    Parameters
    ----------
    db_path : str
        SQLite 数据库路径
    start_date / end_date : str
        'YYYY-MM-DD' 格式
    etf_codes : list[str] | None
        指定 ETF 代码（如 ["510050.SH","510300.SH"]）；None = 全市场 ETF
    fields : list[str] | None
        显式指定要读的列；None = 读所有
    enrich_etf_info : bool
        是否从 t_etf_info 合并基础信息（风控需要 etf_name/listed_date），默认 True
    db : DatabaseManager | None
        可选的已存在 DatabaseManager 实例（避免重复创建连接）

    Returns
    -------
    Dict[str, pd.DataFrame]
        {etf_code: DataFrame}，每只 ETF 一个独立 DataFrame
    """
    import sqlite3

    # 直接 SQL 查询 t_etf_daily（支持批量 etf_codes 或全市场）
    conn = sqlite3.connect(db_path)
    try:
        # 动态构建列名，避免 SELECT *
        if fields:
            select_cols = ['trade_date', 'etf_code']
            for f in fields:
                if f not in select_cols:
                    select_cols.append(f)
            sql = f"SELECT {','.join(select_cols)} FROM t_etf_daily WHERE 1=1"
        else:
            sql = "SELECT * FROM t_etf_daily WHERE 1=1"

        params: list = []
        sql += " AND trade_date >= ? AND trade_date <= ?"
        params.extend([start_date, end_date])

        if etf_codes:
            placeholders = ','.join(['?' for _ in etf_codes])
            sql += f" AND etf_code IN ({placeholders})"
            params.extend(etf_codes)

        sql += " ORDER BY trade_date"
        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()

    if df.empty:
        return {}

    # ---- 合并 t_etf_info（etf_name/listed_date/benchmark_index 等，风控需要） ----
    if enrich_etf_info:
        try:
            conn = sqlite3.connect(db_path)
            info_df = pd.read_sql_query(
                "SELECT etf_code, etf_name, listed_date, delisted_date, "
                "benchmark_index, fund_type, management_fee FROM t_etf_info",
                conn,
            )
            conn.close()
            if not info_df.empty:
                # t_etf_info 中 etf_code 可能是 SHSE.510050 格式，转换为 510050.SH
                info_df['etf_code'] = info_df['etf_code'].apply(_convert_eastmoney_code)
                df = df.merge(info_df, on='etf_code', how='left')
        except Exception as e:
            logger.warning("from_etf_db: 合并 t_etf_info 失败: %s", e)

    return to_quantlab_dict(df, code_col="etf_code")


# ============ 指数数据加载 ============

def from_index_db(
    db_path: str,
    start_date: str,
    end_date: str,
    index_codes: Optional[List[str]] = None,
    fields: Optional[List[str]] = None,
    enrich_index_info: bool = True,
    db=None,
) -> Dict[str, pd.DataFrame]:
    """
    从 myquant SQLite 数据库读取指数日频行情，转 quantlab Dict[symbol, DataFrame]。

    合并的表：
    - t_index_daily：指数日频行情（open/high/low/close/volume/amount/pre_close）
    - t_index_info：指数基础信息（index_name/listed_date/delisted_date/base_date/base_point/publish_date）

    Parameters
    ----------
    db_path : str
        SQLite 数据库路径
    start_date / end_date : str
        'YYYY-MM-DD' 格式
    index_codes : list[str] | None
        指定指数代码（如 ["000300.SH"]）；None = 全市场指数
    fields : list[str] | None
        显式指定要读的列；None = 读所有
    enrich_index_info : bool
        是否从 t_index_info 合并基础信息，默认 True
    db : DatabaseManager | None
        可选的已存在 DatabaseManager 实例

    Returns
    -------
    Dict[str, pd.DataFrame]
        {index_code: DataFrame}，每个指数一个独立 DataFrame
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        if fields:
            select_cols = ['trade_date', 'index_code']
            for f in fields:
                if f not in select_cols:
                    select_cols.append(f)
            sql = f"SELECT {','.join(select_cols)} FROM t_index_daily WHERE 1=1"
        else:
            sql = "SELECT * FROM t_index_daily WHERE 1=1"

        params: list = []
        sql += " AND trade_date >= ? AND trade_date <= ?"
        params.extend([start_date, end_date])

        if index_codes:
            placeholders = ','.join(['?' for _ in index_codes])
            sql += f" AND index_code IN ({placeholders})"
            params.extend(index_codes)

        sql += " ORDER BY trade_date"
        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()

    if df.empty:
        return {}

    # ---- 合并 t_index_info（index_name/listed_date 等） ----
    if enrich_index_info:
        try:
            conn = sqlite3.connect(db_path)
            info_df = pd.read_sql_query(
                "SELECT index_code, index_name, listed_date, delisted_date, "
                "base_date, base_point, publish_date FROM t_index_info",
                conn,
            )
            conn.close()
            if not info_df.empty:
                info_df['index_code'] = info_df['index_code'].apply(_convert_eastmoney_code)
                df = df.merge(info_df, on='index_code', how='left')
        except Exception as e:
            logger.warning("from_index_db: 合并 t_index_info 失败: %s", e)

    return to_quantlab_dict(df, code_col="index_code")


# ============ 成分股查询工具 ============

def get_index_constituents(
    index_code: str,
    db_path: str,
    trade_date: Optional[str] = None,
) -> List[str]:
    """
    查询指定指数的成分股代码列表（从 t_stock_in_index 表）。

    Parameters
    ----------
    index_code : str
        指数代码（如 "000300.SH"）
    db_path : str
        数据库路径
    trade_date : str | None
        指定交易日（'YYYY-MM-DD'）；None = 最新日期的成分股

    Returns
    -------
    list[str]
        成分股代码列表（如 ["600000.SH", "000001.SZ", ...]）
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        if trade_date is None:
            # 取最新日期的成分股
            df = pd.read_sql_query(
                "SELECT stock_code FROM t_stock_in_index "
                "WHERE index_code = ? "
                "AND trade_date = ("
                "    SELECT MAX(trade_date) FROM t_stock_in_index WHERE index_code = ?"
                ") ORDER BY weight DESC",
                conn,
                params=[index_code, index_code],
            )
        else:
            df = pd.read_sql_query(
                "SELECT stock_code FROM t_stock_in_index "
                "WHERE index_code = ? AND trade_date = ? ORDER BY weight DESC",
                conn,
                params=[index_code, trade_date],
            )
    finally:
        conn.close()

    return df['stock_code'].tolist() if not df.empty else []


def get_etf_constituents(
    etf_code: str,
    db_path: str,
    trade_date: Optional[str] = None,
) -> List[str]:
    """
    查询指定 ETF 的实际成分股代码列表（从 t_stock_in_etf 表）。

    【实事求是原则】ETF 成分股 ≠ 指数成分股，绝不回退到 t_stock_in_index。
    t_stock_in_etf 表为空或无数据时返回空列表，并打印警告。

    Parameters
    ----------
    etf_code : str
        ETF 代码（如 "510050.SH"）
    db_path : str
        数据库路径
    trade_date : str | None
        指定交易日（'YYYY-MM-DD'）；None = 最新日期的成分股

    Returns
    -------
    list[str]
        成分股代码列表；表为空或无数据时返回 []
    """
    import sqlite3

    try:
        conn = sqlite3.connect(db_path)
        try:
            # 先检查表是否存在
            table_check = pd.read_sql_query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='t_stock_in_etf'",
                conn,
            )
            if table_check.empty:
                logger.warning(
                    "ETF %s 成分股数据未同步：t_stock_in_etf 表不存在，请先运行 data auto-sync",
                    etf_code,
                )
                return []

            if trade_date is None:
                df = pd.read_sql_query(
                    "SELECT stock_code FROM t_stock_in_etf "
                    "WHERE etf_code = ? "
                    "AND trade_date = ("
                    "    SELECT MAX(trade_date) FROM t_stock_in_etf WHERE etf_code = ?"
                    ") ORDER BY weight DESC",
                    conn,
                    params=[etf_code, etf_code],
                )
            else:
                df = pd.read_sql_query(
                    "SELECT stock_code FROM t_stock_in_etf "
                    "WHERE etf_code = ? AND trade_date = ? ORDER BY weight DESC",
                    conn,
                    params=[etf_code, trade_date],
                )
        finally:
            conn.close()
    except Exception as e:
        logger.warning("get_etf_constituents: 查询失败: %s", e)
        return []

    if df.empty:
        logger.warning(
            "ETF %s 成分股数据未同步，请先运行 data auto-sync（绝不回退到 t_stock_in_index）",
            etf_code,
        )
        return []

    return df['stock_code'].tolist()


# ============ 多资产混合数据加载 ============

def from_mixed_db(
    db_path: str,
    start_date: str,
    end_date: str,
    etf_codes: Optional[List[str]] = None,
    stock_codes: Optional[List[str]] = None,
    index_codes: Optional[List[str]] = None,
    fields: Optional[List[str]] = None,
    db=None,
) -> Dict[str, pd.DataFrame]:
    """
    多资产混合加载（为两层选股策略搭路）。

    合并加载 ETF + 个股 + 指数数据，并查询 t_stock_in_index / t_stock_in_etf 成分股关联。

    Parameters
    ----------
    db_path : str
        数据库路径
    start_date / end_date : str
        'YYYY-MM-DD' 格式
    etf_codes / stock_codes / index_codes : list[str] | None
        各类资产代码列表；None = 不加载该类资产
    fields : list[str] | None
        显式指定要读的列（仅对个股生效，ETF/指数读全部）
    db : DatabaseManager | None
        可选的已存在 DatabaseManager 实例

    Returns
    -------
    Dict[str, pd.DataFrame]
        合并后的 {symbol: DataFrame}，symbol 为各资产代码
        成分股关联信息通过 DataFrame.attrs 传递：
        - 'index_constituents': dict[index_code, list[stock_code]]
        - 'etf_constituents': dict[etf_code, list[stock_code]]
    """
    data: Dict[str, pd.DataFrame] = {}

    # ---- 1) 加载 ETF 数据 ----
    if etf_codes:
        etf_data = from_etf_db(
            db_path=db_path,
            start_date=start_date,
            end_date=end_date,
            etf_codes=etf_codes,
            fields=fields,
            db=db,
        )
        data.update(etf_data)

    # ---- 2) 加载个股数据 ----
    if stock_codes:
        stock_data = from_quantlab_db(
            db_path=db_path,
            start_date=start_date,
            end_date=end_date,
            stock_codes=stock_codes,
            fields=fields,
            db=db,
        )
        data.update(stock_data)

    # ---- 3) 加载指数数据 ----
    if index_codes:
        index_data = from_index_db(
            db_path=db_path,
            start_date=start_date,
            end_date=end_date,
            index_codes=index_codes,
            fields=fields,
            db=db,
        )
        data.update(index_data)

    # ---- 4) 查询成分股关联（附在第一个 symbol 的 attrs 上，方便策略层读取） ----
    index_constituents: Dict[str, List[str]] = {}
    etf_constituents: Dict[str, List[str]] = {}

    if index_codes:
        for idx_code in index_codes:
            index_constituents[idx_code] = get_index_constituents(idx_code, db_path)

    if etf_codes:
        for etf_code in etf_codes:
            etf_constituents[etf_code] = get_etf_constituents(etf_code, db_path)

    # 通过第一个 DataFrame 的 attrs 传递成分股信息（避免改变返回类型）
    if data:
        first_sym = next(iter(data))
        data[first_sym].attrs['index_constituents'] = index_constituents
        data[first_sym].attrs['etf_constituents'] = etf_constituents

    return data


__all__ = [
    "to_quantlab_dict",
    "from_quantlab_db",
    "from_etf_db",
    "from_index_db",
    "from_mixed_db",
    "get_index_constituents",
    "get_etf_constituents",
    "DEFAULT_REQUIRED_COLS",
]
