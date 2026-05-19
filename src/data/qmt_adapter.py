"""
QMT数据适配器模块
================

将QMT返回的数据格式转换为系统内部格式（DataFrame），方便写入数据库。
"""

import logging
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class QMTDataAdapter:
    """
    QMT数据适配器

    将QMT接口返回的原始数据转换为系统内部统一格式，
    使上层业务逻辑无需关心底层QMT数据结构差异。
    """

    # QMT K线数据字段到系统标准字段的映射
    MARKET_DATA_FIELD_MAP = {
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'volume': 'volume',
        'amount': 'amount',
        'pvolume': 'pvolume',       # 持仓量（期货）
        'oi': 'oi',                 # Open Interest
        'high_limit': 'high_limit', # 涨停价
        'low_limit': 'low_limit',   # 跌停价
        'avg_price': 'avg_price',   # 均价
        'preClose': 'pre_close',    # 前收盘价（QMT字段名）
        'pre_close': 'pre_close',   # 前收盘价（兼容）
        'pre_settle': 'pre_settle', # 前结算价
        'suspendFlag': 'suspend_flag',  # 停牌标记（0正常, 1停牌, -1复牌）
    }

    # QMT instrument_detail 字段到 stock_info 标准字段的映射
    INSTRUMENT_FIELD_MAP = {
        'InstrumentName': 'stock_name',
        'ProductClassification': 'product_type',
        'ExchangeID': 'exchange',
        'InstrumentType': 'instrument_type',
        'OpenDate': 'list_date',
        'ExpireDate': 'expire_date',
        'PreClose': 'pre_close',
        'UpperLimit': 'upper_limit',
        'LowerLimit': 'lower_limit',
        'VolumeMultiple': 'volume_multiple',
        'PriceTick': 'price_tick',
        'LongMarginRatio': 'long_margin_ratio',
        'ShortMarginRatio': 'short_margin_ratio',
        'IsDelisting': 'is_delisting',
    }

    @staticmethod
    def transform_market_data(qmt_data: dict) -> pd.DataFrame:
        """
        将 get_market_data_ex 返回的 {code: DataFrame} 转换为统一的 DataFrame

        QMT的 get_market_data_ex 返回格式为:
            {stock_code: DataFrame}，其中 DataFrame 的索引为时间戳，
            列为各个行情字段。

        转换后格式:
            DataFrame，包含 stock_code, trade_date, open, high, low, close,
            volume, amount, vwap 等列。

        Parameters
        ----------
        qmt_data : dict
            get_market_data_ex 返回的数据字典 {stock_code: DataFrame}

        Returns
        -------
        pd.DataFrame
            统一格式的历史行情数据，包含 stock_code 和 trade_date 列
        """
        if not qmt_data:
            logger.warning("传入的qmt_data为空，返回空DataFrame")
            return pd.DataFrame()

        frames = []
        for stock_code, df in qmt_data.items():
            if df is None or df.empty:
                continue

            df = df.copy()
            # 将时间戳索引转为 trade_date 列
            df['trade_date'] = pd.to_datetime(df.index)
            df['stock_code'] = stock_code

            # 将QMT原始字段名映射为系统标准字段名
            for qmt_field, std_field in QMTDataAdapter.MARKET_DATA_FIELD_MAP.items():
                if qmt_field in df.columns and qmt_field != std_field:
                    if std_field not in df.columns:
                        df[std_field] = df[qmt_field]
                    else:
                        # 标准字段已存在（如pre_close），用QMT字段覆盖
                        df[std_field] = df[qmt_field]

            # 计算VWAP（如果数据中有amount和volume）
            if 'amount' in df.columns and 'volume' in df.columns:
                df['vwap'] = df.apply(
                    QMTDataAdapter.calculate_vwap, axis=1
                )

            frames.append(df)

        if not frames:
            logger.warning("qmt_data中没有有效数据，返回空DataFrame")
            return pd.DataFrame()

        result = pd.concat(frames, ignore_index=True)

        # 确保标准列存在
        standard_cols = ['stock_code', 'trade_date', 'open', 'high', 'low',
                         'close', 'volume', 'amount', 'vwap', 'suspend_flag']
        for col in standard_cols:
            if col not in result.columns:
                result[col] = None

        # 按股票代码和日期排序
        result = result.sort_values(['stock_code', 'trade_date']).reset_index(drop=True)

        logger.info(f"转换市场数据完成: {len(result)}条记录, {result['stock_code'].nunique()}只股票")
        return result

    @staticmethod
    def transform_instrument_detail(detail: dict, stock_code: str) -> dict:
        """
        将 get_instrument_detail 返回的详情转换为 stock_info 格式

        Parameters
        ----------
        detail : dict
            get_instrument_detail 返回的合约详情字典
        stock_code : str
            股票代码

        Returns
        -------
        dict
            标准化的股票信息字典，可直接写入 stock_info 表
        """
        if not detail:
            logger.warning(f"合约详情为空 [{stock_code}]，返回基本信息")
            return {'stock_code': stock_code}

        result = {'stock_code': stock_code}

        for qmt_key, std_key in QMTDataAdapter.INSTRUMENT_FIELD_MAP.items():
            if qmt_key in detail:
                result[std_key] = detail[qmt_key]

        # 处理日期字段：QMT返回的日期可能是毫秒时间戳
        for date_field in ['list_date', 'expire_date']:
            if date_field in result and result[date_field] is not None:
                val = result[date_field]
                if isinstance(val, (int, float)):
                    # 毫秒时间戳转日期字符串
                    try:
                        result[date_field] = pd.to_datetime(val, unit='ms').strftime('%Y-%m-%d')
                    except (ValueError, OSError):
                        result[date_field] = str(val)
                elif isinstance(val, str):
                    # 尝试标准化日期格式
                    try:
                        result[date_field] = pd.to_datetime(val).strftime('%Y-%m-%d')
                    except (ValueError, TypeError):
                        pass

        logger.debug(f"转换合约详情完成: {stock_code}")
        return result

    @staticmethod
    def transform_financial_data(qmt_data: dict, table_name: str) -> pd.DataFrame:
        """
        将财务数据转换为 DataFrame

        QMT的 get_financial_data 返回格式为:
            {stock_code: DataFrame}，其中 DataFrame 的索引为报告期，
            列为各个财务字段。

        Parameters
        ----------
        qmt_data : dict
            get_financial_data 返回的数据字典 {stock_code: DataFrame}
        table_name : str
            财务报表名称，如 'Balance', 'Income', 'CashFlow'

        Returns
        -------
        pd.DataFrame
            统一格式的财务数据
        """
        if not qmt_data:
            logger.warning(f"传入的财务数据为空 [{table_name}]，返回空DataFrame")
            return pd.DataFrame()

        frames = []
        for stock_code, df in qmt_data.items():
            if df is None or df.empty:
                continue

            df = df.copy()
            # 将索引转为列（QMT财务数据的索引通常是报告期）
            df = df.reset_index()
            # 尝试识别第一列是否为报告期
            if len(df.columns) > 0:
                first_col = df.columns[0]
                try:
                    pd.to_datetime(df[first_col].iloc[0])
                    df = df.rename(columns={first_col: 'report_date'})
                except (ValueError, TypeError, IndexError):
                    pass

            df['stock_code'] = stock_code
            df['table_name'] = table_name
            frames.append(df)

        if not frames:
            logger.warning(f"财务数据中没有有效数据 [{table_name}]，返回空DataFrame")
            return pd.DataFrame()

        result = pd.concat(frames, ignore_index=True)
        result = result.sort_values(['stock_code']).reset_index(drop=True)

        logger.info(
            f"转换财务数据完成 [{table_name}]: {len(result)}条记录, "
            f"{result['stock_code'].nunique()}只股票"
        )
        return result

    @staticmethod
    def calculate_vwap(row: dict) -> Optional[float]:
        """
        用 amount/volume 计算 VWAP（成交量加权平均价）

        Parameters
        ----------
        row : dict
            包含 amount 和 volume 字段的数据行

        Returns
        -------
        float or None
            VWAP值，volume为0或无效时返回None
        """
        volume = row.get('volume')
        amount = row.get('amount')

        # 检查数据有效性
        if volume is None or amount is None:
            return None

        try:
            volume = float(volume)
            amount = float(amount)
        except (TypeError, ValueError):
            return None

        if volume == 0:
            return None

        try:
            return round(amount / volume, 4)
        except (ZeroDivisionError, TypeError, ValueError):
            return None
