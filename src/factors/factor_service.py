"""
策略级因子服务
==============

提供统一的因子获取和计算接口，支持策略内按日调用。

设计原则：
- 按日获取因子值（适合策略 on_bar 调用）
- 自动缓存，避免重复API调用
- 支持全市场排名和股票池筛选
- 统一处理缺失值和异常值
- 通过 FactorProvider 抽象层支持多数据源
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from config.config import get_data_source, DATABASE_CONFIG

logger = logging.getLogger(__name__)


class FactorService:
    """
    策略级因子服务

    使用示例：
    >>> service = FactorService()  # 自动读取配置的数据源
    >>> factors = service.get_factor('pb', '2024-01-02')
    >>> ranked = service.rank('pb', '2024-01-02', ascending=True)
    >>> combined = service.combined_rank(['pb', 'roe'], '2024-01-02')
    >>> top10 = service.top_n('pb', '2024-01-02', n=10)
    """

    def __init__(self, data_source: str = None, db_path: str = None):
        """
        初始化因子服务

        Parameters
        ----------
        data_source : str, optional
            数据源名称，'eastmoney' 或 'database'，None 则读取配置
        db_path : str, optional
            数据库路径，None 则使用默认配置
        """
        from .factor_provider import EastmoneyFactorProvider, DatabaseFactorProvider

        # 确定数据源
        if data_source is None:
            ds = get_data_source()
            data_source = ds.value if hasattr(ds, 'value') else ds

        # 创建对应的 Provider
        if data_source == 'eastmoney':
            self._provider = EastmoneyFactorProvider()
        else:
            db_path = db_path or DATABASE_CONFIG.get('path')
            self._provider = DatabaseFactorProvider(db_path)

        # 缓存：{date: {factor_name: {stock_code: value}}}
        self._cache: Dict[str, Dict[str, Dict[str, float]]] = {}

        logger.info(f"FactorService 初始化完成，数据源: {data_source}")

    def get_factor(
        self,
        factor_name: str,
        date: str,
        stock_pool: List[str] = None,
    ) -> Dict[str, float]:
        """
        获取某日某因子的值

        Parameters
        ----------
        factor_name : str
            因子名称，如 'pb', 'roe', 'pe_ttm'
        date : str
            查询日期 'YYYY-MM-DD'
        stock_pool : List[str], optional
            股票池代码列表，None 表示全市场

        Returns
        -------
        Dict[str, float]
            {stock_code: factor_value}

        Example
        -------
        >>> service = FactorService()
        >>> pb_values = service.get_factor('pb', '2024-01-02')
        >>> print(pb_values['000001.SZ'])  # 获取平安银行PB值
        """
        from .factor_registry import get_factor_info, FactorSource

        # 检查缓存
        cache_key = f"{factor_name}_{date}"
        if date in self._cache and factor_name in self._cache[date]:
            cached = self._cache[date][factor_name]
            if stock_pool:
                return {k: v for k, v in cached.items() if k in stock_pool}
            return cached

        # 获取因子元数据
        info = get_factor_info(factor_name)
        if not info:
            logger.error(f"未知因子: {factor_name}")
            return {}

        # 获取全市场股票列表
        all_symbols = self._provider.get_all_symbols()
        if not all_symbols:
            logger.error("无法获取全市场股票列表")
            return {}

        # 根据 source 类型路由到不同的 Provider 方法
        source = info['source']
        field = info['field']

        # 转换为掘金格式（Provider 需要）
        from src.data.symbol_converter import SymbolConverter
        mq_symbols = SymbolConverter.batch_to_eastmoney(all_symbols)

        if source == FactorSource.VALUATION:
            result = self._provider.get_valuation(mq_symbols, field, date)
        elif source == FactorSource.MKTVALUE:
            result = self._provider.get_mktvalue(mq_symbols, field, date)
        else:
            result = self._provider.get_financial(mq_symbols, field, date)

        # 缓存结果
        if date not in self._cache:
            self._cache[date] = {}
        self._cache[date][factor_name] = result

        # 如果指定了股票池，过滤结果
        if stock_pool:
            result = {k: v for k, v in result.items() if k in stock_pool}

        logger.debug(f"获取因子 {factor_name} ({date}): {len(result)} 只股票")
        return result

    def get_factors(
        self,
        factor_names: List[str],
        date: str,
        stock_pool: List[str] = None,
    ) -> Dict[str, Dict[str, float]]:
        """
        批量获取多个因子

        Parameters
        ----------
        factor_names : List[str]
            因子名称列表
        date : str
            查询日期
        stock_pool : List[str], optional
            股票池代码列表

        Returns
        -------
        Dict[str, Dict[str, float]]
            {factor_name: {stock_code: value}}

        Example
        -------
        >>> service = FactorService()
        >>> factors = service.get_factors(['pb', 'roe'], '2024-01-02')
        >>> print(factors['pb']['000001.SZ'])
        """
        result = {}
        for name in factor_names:
            result[name] = self.get_factor(name, date, stock_pool)
        return result

    def rank(
        self,
        factor_name: str,
        date: str,
        ascending: bool = None,
        stock_pool: List[str] = None,
    ) -> Dict[str, int]:
        """
        获取某因子的全市场排名

        Parameters
        ----------
        factor_name : str
            因子名称
        date : str
            查询日期
        ascending : bool, optional
            排名方向，True=升序(越小排名越高)，None 则使用因子默认方向
        stock_pool : List[str], optional
            股票池代码列表

        Returns
        -------
        Dict[str, int]
            {stock_code: rank}，rank 从 1 开始

        Example
        -------
        >>> service = FactorService()
        >>> ranks = service.rank('pb', '2024-01-02', ascending=True)
        >>> print(ranks['000001.SZ'])  # 获取平安银行PB排名
        """
        from .factor_registry import get_factor_info

        # 获取因子值
        values = self.get_factor(factor_name, date, stock_pool)
        if not values:
            return {}

        # 确定排名方向
        if ascending is None:
            info = get_factor_info(factor_name)
            ascending = info.get('default_ascending', True) if info else True

        # 转换为 Series 进行排名
        series = pd.Series(values)
        # 使用 min 方法处理相同值，na_option='keep' 保持 NaN
        ranks = series.rank(ascending=ascending, method='min', na_option='keep')

        # 转换为 int 排名（从1开始）
        result = {code: int(rank) for code, rank in ranks.items() if not np.isnan(rank)}

        logger.debug(f"排名 {factor_name} ({date}): {len(result)} 只股票")
        return result

    def combined_rank(
        self,
        factor_names: List[str],
        date: str,
        directions: List[bool] = None,
        stock_pool: List[str] = None,
    ) -> Dict[str, float]:
        """
        多因子综合排名（各因子排名相加）

        Parameters
        ----------
        factor_names : List[str]
            因子名称列表，如 ['pb', 'roe']
        date : str
            查询日期
        directions : List[bool], optional
            各因子的排名方向，True=升序(越小越好)，False=降序(越大越好)
            None 则使用各因子的默认方向
        stock_pool : List[str], optional
            股票池代码列表

        Returns
        -------
        Dict[str, float]
            {stock_code: combined_rank}，值越小排名越高

        Example
        -------
        >>> service = FactorService()
        >>> # PB升序(越小越好) + ROE降序(越大越好)
        >>> combined = service.combined_rank(
        ...     ['pb', 'roe'],
        ...     '2024-01-02',
        ...     directions=[True, False]
        ... )
        """
        from .factor_registry import get_factor_info

        if directions is None:
            directions = [None] * len(factor_names)

        if len(factor_names) != len(directions):
            raise ValueError("factor_names 和 directions 长度必须相同")

        # 获取各因子的排名
        all_ranks = {}
        for name, direction in zip(factor_names, directions):
            if direction is None:
                info = get_factor_info(name)
                direction = info.get('default_ascending', True) if info else True
            all_ranks[name] = self.rank(name, date, ascending=direction, stock_pool=stock_pool)

        # 合并排名（取交集，确保所有因子都有值的股票）
        common_stocks = set.intersection(*[set(ranks.keys()) for ranks in all_ranks.values()])

        # 计算综合排名（各因子排名相加）
        combined = {}
        for code in common_stocks:
            total_rank = sum(all_ranks[name].get(code, float('inf')) for name in factor_names)
            combined[code] = total_rank

        logger.info(f"综合排名 ({', '.join(factor_names)}) ({date}): {len(combined)} 只股票")
        return combined

    def top_n(
        self,
        factor_name: str,
        date: str,
        n: int = 10,
        ascending: bool = None,
        stock_pool: List[str] = None,
    ) -> List[str]:
        """
        获取某因子排名前N的股票代码

        Parameters
        ----------
        factor_name : str
            因子名称
        date : str
            查询日期
        n : int
            取前N名
        ascending : bool, optional
            排名方向
        stock_pool : List[str], optional
            股票池代码列表

        Returns
        -------
        List[str]
            排名前N的股票代码列表

        Example
        -------
        >>> service = FactorService()
        >>> top10 = service.top_n('pb', '2024-01-02', n=10, ascending=True)
        >>> print(top10)  # PB最低的10只股票
        """
        ranks = self.rank(factor_name, date, ascending, stock_pool)
        # 按排名排序，取前N
        sorted_stocks = sorted(ranks.items(), key=lambda x: x[1])
        return [code for code, _ in sorted_stocks[:n]]

    def top_pct(
        self,
        factor_name: str,
        date: str,
        pct: float = 10,
        ascending: bool = None,
        stock_pool: List[str] = None,
    ) -> List[str]:
        """
        获取某因子排名前N%的股票代码

        Parameters
        ----------
        factor_name : str
            因子名称
        date : str
            查询日期
        pct : float
            百分比，如 10 表示前10%
        ascending : bool, optional
            排名方向
        stock_pool : List[str], optional
            股票池代码列表

        Returns
        -------
        List[str]
            排名前N%的股票代码列表

        Example
        -------
        >>> service = FactorService()
        >>> top10pct = service.top_pct('pb', '2024-01-02', pct=10, ascending=True)
        >>> print(f"PB最低的10%股票共 {len(top10pct)} 只")
        """
        ranks = self.rank(factor_name, date, ascending, stock_pool)
        if not ranks:
            return []

        n = max(1, int(len(ranks) * pct / 100))
        sorted_stocks = sorted(ranks.items(), key=lambda x: x[1])
        return [code for code, _ in sorted_stocks[:n]]

    def clear_cache(self, date: str = None):
        """
        清除缓存

        Parameters
        ----------
        date : str, optional
            指定日期清除，None 则清除全部缓存
        """
        if date:
            if date in self._cache:
                del self._cache[date]
                logger.info(f"清除缓存: {date}")
        else:
            self._cache.clear()
            logger.info("清除全部缓存")

    def get_cache_info(self) -> Dict[str, int]:
        """
        获取缓存信息

        Returns
        -------
        Dict[str, int]
            {date: factor_count}
        """
        return {date: len(factors) for date, factors in self._cache.items()}

    # ---- 资金流向扩展方法 ----

    def get_money_flow(
        self,
        symbols: List[str],
        date: str,
    ) -> Dict[str, float]:
        """
        获取个股主力资金净流入

        Parameters
        ----------
        symbols : List[str]
            股票代码列表（系统内部格式）
        date : str
            查询日期 'YYYY-MM-DD'

        Returns
        -------
        Dict[str, float]
            {stock_code: main_net_in}
        """
        # 检查缓存
        cache_key = f"money_flow_{date}"
        if date in self._cache and cache_key in self._cache[date]:
            cached = self._cache[date][cache_key]
            symbol_set = set(symbols)
            return {k: v for k, v in cached.items() if k in symbol_set}

        from src.data.symbol_converter import SymbolConverter

        try:
            mq_symbols = SymbolConverter.batch_to_eastmoney(symbols)
            # 通过 provider 获取（EastmoneyFactorProvider 不支持，直接调用 connector）
            from src.data.eastmoney_connector import EastmoneyConnector
            from config.config import get_credentials

            token = get_credentials('eastmoney').get('token', '')
            connector = EastmoneyConnector(token=token)

            df = connector.get_money_flow(symbols=mq_symbols, trade_date=date)

            if df is None or df.empty:
                return {}

            result = {}
            for _, row in df.iterrows():
                code = SymbolConverter.to_internal(row['symbol'])
                result[code] = row.get('main_net_in', 0.0)

            # 缓存
            if date not in self._cache:
                self._cache[date] = {}
            self._cache[date][cache_key] = result

            return result

        except Exception as e:
            logger.error(f"获取资金流向失败: {e}")
            return {}

    def top_n_by_field(
        self,
        field: str,
        symbols: List[str],
        date: str,
        n: int = 5,
        ascending: bool = False,
    ) -> List[str]:
        """
        按某字段排序取 Top N 股票

        Parameters
        ----------
        field : str
            排序字段名（如 'main_net_in'）
        symbols : List[str]
            候选股票代码列表
        date : str
            查询日期
        n : int
            取前N名
        ascending : bool
            排序方向

        Returns
        -------
        List[str]
            排名前N的股票代码列表
        """
        if field == 'main_net_in':
            data = self.get_money_flow(symbols, date)
        else:
            data = self.get_factor(field, date, symbols)

        if not data:
            return []

        sorted_stocks = sorted(data.items(), key=lambda x: x[1], reverse=not ascending)
        return [code for code, _ in sorted_stocks[:n]]

    def top_n_growth(
        self,
        symbols: List[str],
        date: str,
        n: int = 5,
        days: int = 3,
    ) -> List[str]:
        """
        计算入选后N日涨幅，取 Top N

        Parameters
        ----------
        symbols : List[str]
            候选股票代码列表
        date : str
            入选日期（T日）
        n : int
            取前N名
        days : int
            涨幅计算天数

        Returns
        -------
        List[str]
            涨幅前N的股票代码列表
        """
        try:
            from src.data.eastmoney_connector import EastmoneyConnector
            from src.data.symbol_converter import SymbolConverter
            from config.config import get_credentials
            from datetime import datetime, timedelta

            token = get_credentials('eastmoney').get('token', '')
            connector = EastmoneyConnector(token=token)

            # 计算 T+days 的日期（跳过非交易日，简单处理）
            start_dt = datetime.strptime(date, '%Y-%m-%d')
            end_dt = start_dt + timedelta(days=days + 5)  # 多取几天确保有交易日

            mq_symbols = SymbolConverter.batch_to_eastmoney(symbols)

            # 获取历史行情
            history_df = connector.get_history(
                symbol=mq_symbols,
                frequency='1d',
                start_time=f"{date} 09:00:00",
                end_time=end_dt.strftime('%Y-%m-%d') + " 16:00:00",
                adjust=1,
            )

            if history_df is None or history_df.empty:
                return []

            # 转换格式
            history_df = history_df.rename(columns={'eob': 'date'})
            if 'date' not in history_df.columns and 'bob' in history_df.columns:
                history_df = history_df.rename(columns={'bob': 'date'})

            # 计算每只股票的涨幅
            growth_map = {}
            for code in symbols:
                stock_data = history_df[history_df['symbol'] == SymbolConverter.to_eastmoney(code)]
                if stock_data is None or len(stock_data) < 2:
                    continue

                stock_data = stock_data.sort_values('date')
                entry_price = stock_data.iloc[0]['close']

                # 找到第 days 个交易日
                if len(stock_data) > days:
                    exit_price = stock_data.iloc[days]['close']
                else:
                    exit_price = stock_data.iloc[-1]['close']

                if entry_price > 0:
                    growth = (exit_price - entry_price) / entry_price
                    growth_map[code] = growth

            if not growth_map:
                return []

            # 按涨幅降序排列
            sorted_stocks = sorted(growth_map.items(), key=lambda x: x[1], reverse=True)
            return [code for code, _ in sorted_stocks[:n]]

        except Exception as e:
            logger.error(f"计算涨幅失败: {e}")
            return []
