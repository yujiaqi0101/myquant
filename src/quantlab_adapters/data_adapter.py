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
) -> Dict[str, pd.DataFrame]:
    """
    直接从 myquant SQLite 数据库读数据，转 quantlab Dict[symbol, DataFrame]。

    比 to_quantlab_dict(MultiIndex) 更高效（避免先 group 再拆列）。

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

    return to_quantlab_dict(df)


__all__ = [
    "to_quantlab_dict",
    "from_quantlab_db",
    "DEFAULT_REQUIRED_COLS",
]
