"""
东财掘金数据适配器

继承 DailyDataAdapter，从东财掘金 API 获取数据并转换为系统内部格式。
"""

import logging
from typing import List, Set

import pandas as pd

from .adapter import DailyDataAdapter
from .eastmoney_connector import EastmoneyConnector
from .symbol_converter import SymbolConverter

logger = logging.getLogger(__name__)


class EastmoneyAdapter(DailyDataAdapter):
    """
    东财掘金数据适配器

    通过东财掘金 API 获取日频数据，转换为系统内部格式。
    """

    def __init__(self, token: str, adjust: int = 1, **connector_kwargs):
        """
        初始化适配器

        Parameters
        ----------
        token : str
            东财掘金 API token
        adjust : int
            复权方式：0=不复权, 1=前复权, 2=后复权
        **connector_kwargs
            连接器其他参数
        """
        super().__init__()
        self._connector = EastmoneyConnector(token=token, **connector_kwargs)
        self._adjust = adjust
        self._stock_info_df = None  # 缓存股票信息

    def load_price_data(
        self,
        start_date: str,
        end_date: str,
        stock_codes: List[str] = None,
    ):
        """
        从掘金 API 加载价格数据

        Parameters
        ----------
        start_date : str
            开始日期 'YYYY-MM-DD'
        end_date : str
            结束日期 'YYYY-MM-DD'
        stock_codes : List[str], optional
            股票代码列表（系统内部格式 600000.SH）
        """
        if stock_codes is None:
            # 获取全部 A 股
            stock_list = self._connector.get_stock_list()
            if stock_list.empty:
                raise ValueError("无法获取股票列表")
            stock_codes = SymbolConverter.batch_to_internal(stock_list['symbol'].tolist())

        logger.info(f"开始从掘金 API 加载价格数据: {len(stock_codes)} 只股票, {start_date} ~ {end_date}")

        # 按年份分批加载，避免 API 数据量限制
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])
        
        merged_df = None  # 增量合并，避免内存累积
        
        for year in range(start_year, end_year + 1):
            # 计算该年的时间范围
            year_start = f"{year}-01-01"
            year_end = f"{year}-12-31"
            
            # 调整首尾年份的日期范围
            if year == start_year:
                year_start = start_date
            if year == end_year:
                year_end = end_date
            
            logger.info(f"  加载 {year} 年数据: {year_start} ~ {year_end}")
            
            # 转换日期格式为掘金格式
            start_time = SymbolConverter.format_datetime(year_start, "09:00:00")
            end_time = SymbolConverter.format_datetime(year_end, "16:00:00")

            # 批量查询（每次最多500只，减少API调用次数）
            batch_size = 500
            total = len(stock_codes)
            year_df = None

            for batch_start in range(0, total, batch_size):
                batch_codes = stock_codes[batch_start:batch_start + batch_size]
                try:
                    # 批量转换为掘金格式
                    mq_symbols = SymbolConverter.batch_to_eastmoney(batch_codes)

                    # 批量查询历史行情
                    df = self._connector.get_history(
                        symbol=mq_symbols,  # 支持列表
                        frequency='1d',
                        start_time=start_time,
                        end_time=end_time,
                        adjust=self._adjust,
                    )

                    if df is not None and not df.empty:
                        # 转换为系统内部格式
                        df = self._transform_history_df_batch(df)
                        # 增量合并
                        if year_df is None:
                            year_df = df
                        else:
                            year_df = pd.concat([year_df, df], ignore_index=True)
                        # 释放临时 DataFrame
                        del df

                    # 进度输出
                    batch_end = min(batch_start + batch_size, total)
                    logger.info(f"    {year} 年进度: {batch_end}/{total}")

                except Exception as e:
                    logger.warning(f"批量加载失败 [{batch_start}:{batch_start+len(batch_codes)}]: {e}")
                    continue

            # 合并该年数据到总数据
            if year_df is not None and not year_df.empty:
                if merged_df is None:
                    merged_df = year_df
                else:
                    merged_df = pd.concat([merged_df, year_df], ignore_index=True)
                logger.info(f"  {year} 年数据加载完成: {len(year_df)} 条记录")

        if merged_df is None or merged_df.empty:
            raise ValueError("未能加载任何价格数据")

        self._price_df = merged_df
        self._price_df['trade_date'] = pd.to_datetime(self._price_df['trade_date'])
        self._price_df.set_index(['trade_date', 'stock_code'], inplace=True)
        del merged_df  # 释放内存

        logger.info(f"价格数据加载完成: {len(self._price_df)} 条记录")

    def load_stock_list(self):
        """从掘金 API 加载股票列表"""
        stock_list = self._connector.get_stock_list()

        if stock_list is None or stock_list.empty:
            raise ValueError("无法获取股票列表")

        # 转换为系统内部格式
        df = pd.DataFrame()
        df['stock_code'] = SymbolConverter.batch_to_internal(stock_list['symbol'].tolist())
        df['stock_name'] = stock_list['sec_name'].values
        df['list_date'] = pd.to_datetime(stock_list['listed_date']).dt.strftime('%Y-%m-%d')
        df['exchange'] = stock_list['exchange'].values

        # ST 标记
        df['is_st'] = stock_list.get('is_st', False).values

        self._stock_list_df = df
        self._stock_info_df = df  # 同时缓存用于过滤

        logger.info(f"股票列表加载完成: {len(df)} 只")

    def _transform_history_df(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        将掘金 history() 返回的 DataFrame 转换为系统内部格式（单只股票）

        掘金 bar 字段: symbol, frequency, open, close, high, low, amount, volume, bob, eob
        系统字段:    stock_code, trade_date, open, high, low, close, volume, amount, vwap
        """
        result = pd.DataFrame()
        result['trade_date'] = pd.to_datetime(df['eob']).apply(SymbolConverter.parse_datetime)
        result['stock_code'] = stock_code
        result['open'] = df['open']
        result['high'] = df['high']
        result['low'] = df['low']
        result['close'] = df['close']
        result['volume'] = df['volume']
        result['amount'] = df['amount']

        # 计算 VWAP
        result['vwap'] = (result['amount'] / result['volume']).round(4)

        return result

    def _transform_history_df_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        将掘金 history() 批量返回的 DataFrame 转换为系统内部格式（多只股票）

        批量查询返回的 df 包含 symbol 列，需要按 symbol 分别转换
        """
        result = pd.DataFrame()
        result['trade_date'] = pd.to_datetime(df['eob']).apply(SymbolConverter.parse_datetime)
        result['stock_code'] = df['symbol'].apply(SymbolConverter.to_internal)
        result['open'] = df['open']
        result['high'] = df['high']
        result['low'] = df['low']
        result['close'] = df['close']
        result['volume'] = df['volume']
        result['amount'] = df['amount']

        # 计算 VWAP
        result['vwap'] = (result['amount'] / result['volume']).round(4)

        return result

    def get_history_n(
        self,
        stock_code: str,
        count: int,
        end_date: str,
        frequency: str = '1d'
    ) -> pd.DataFrame:
        """
        策略运行时获取某只股票向前 N 条数据（如计算均线）

        Parameters
        ----------
        stock_code : str
            系统内部格式代码
        count : int
            条数
        end_date : str
            结束日期 'YYYY-MM-DD'
        frequency : str
            频率

        Returns
        -------
        pd.DataFrame
            历史数据
        """
        mq_symbol = SymbolConverter.to_eastmoney(stock_code)
        end_time = SymbolConverter.format_datetime(end_date, "16:00:00")

        df = self._connector.get_history_n(
            symbol=mq_symbol,
            frequency=frequency,
            count=count,
            end_time=end_time,
            adjust=self._adjust,
        )

        if df is not None and not df.empty:
            return self._transform_history_df(df, stock_code)
        return pd.DataFrame()

    # ---- StockInfoProvider 所需 ----

    def get_stock_info_filtered(self) -> pd.DataFrame:
        """获取股票基本信息（用于 ST/新股过滤）"""
        if self._stock_info_df is None:
            self.load_stock_list()
        return self._stock_info_df[['stock_code', 'stock_name', 'list_date']].copy()

    def get_trade_dates(self, start_date: str, end_date: str) -> List[str]:
        """获取交易日列表"""
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])
        dates = self._connector.get_trading_dates(start_year, end_year)
        # 过滤到指定范围
        return [d for d in dates if start_date <= d <= end_date]

    def get_st_codes(self) -> Set[str]:
        """获取 ST 股票代码集合"""
        if self._stock_info_df is None:
            self.load_stock_list()
        st_mask = self._stock_info_df['is_st'] == True
        return set(self._stock_info_df.loc[st_mask, 'stock_code'].tolist())
