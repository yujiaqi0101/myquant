"""
申万行业数据连接器
==================

提供申万行业分类和成分股查询功能，基于东财掘金 API。

使用示例：
    from src.data.shenwan_connector import ShenwanConnector
    sw = ShenwanConnector()
    industries = sw.get_sw_industries(level=1)
    stocks = sw.get_industry_constituents('801010')
"""

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class ShenwanConnector:
    """
    申万行业数据连接器

    封装东财掘金的行业分类 API，提供：
    - 申万一级行业列表查询
    - 行业成分股查询
    - 行业资金净流入汇总计算
    """

    def __init__(self):
        from src.data.eastmoney_connector import EastmoneyConnector
        from config.config import get_credentials

        token = get_credentials('eastmoney').get('token', '')
        self._connector = EastmoneyConnector(token=token)
        self._industry_cache: Optional[pd.DataFrame] = None

    def get_sw_industries(self, level: int = 1) -> pd.DataFrame:
        """
        获取申万行业列表

        Parameters
        ----------
        level : int
            行业分级，1=一级行业，2=二级行业，3=三级行业

        Returns
        -------
        pd.DataFrame
            字段: industry_code, industry_name
        """
        if self._industry_cache is not None:
            return self._industry_cache

        try:
            df = self._connector.get_industry_category(
                source='sw2021',
                level=level,
            )

            if df is None or df.empty:
                logger.warning("获取申万行业列表为空")
                return pd.DataFrame(columns=['industry_code', 'industry_name'])

            # 标准化字段名
            result = pd.DataFrame()
            result['industry_code'] = df['industry_code']
            result['industry_name'] = df['industry_name']

            # 去重
            result = result.drop_duplicates(subset='industry_code').reset_index(drop=True)
            self._industry_cache = result

            logger.info(f"获取申万一级行业: {len(result)} 个")
            return result

        except Exception as e:
            logger.error(f"获取申万行业列表失败: {e}")
            return pd.DataFrame(columns=['industry_code', 'industry_name'])

    def get_industry_constituents(
        self,
        industry_code: str,
        date: str = None,
    ) -> List[str]:
        """
        获取某行业的成分股列表

        Parameters
        ----------
        industry_code : str
            申万行业代码
        date : str, optional
            查询日期，None 表示最新

        Returns
        -------
        List[str]
            股票代码列表（系统内部格式，如 '000001.SZ'）
        """
        from src.data.symbol_converter import SymbolConverter

        try:
            df = self._connector.get_industry_constituents(
                industry_code=industry_code,
                date=date,
            )

            if df is None or df.empty:
                return []

            # 过滤有效成分股（date_in <= date 且 date_out 为空或 > date）
            if date and 'date_in' in df.columns:
                df = df[df['date_in'] <= date]
                if 'date_out' in df.columns:
                    df = df[(df['date_out'].isna()) | (df['date_out'] > date)]

            codes = SymbolConverter.batch_to_internal(df['symbol'].tolist())
            return codes

        except Exception as e:
            logger.error(f"获取行业成分股失败 ({industry_code}): {e}")
            return []

    def get_industry_net_flow(
        self,
        date: str,
        level: int = 1,
    ) -> pd.Series:
        """
        计算各申万行业的主力资金净流入总额

        Parameters
        ----------
        date : str
            查询日期 'YYYY-MM-DD'
        level : int
            行业分级

        Returns
        -------
        pd.Series
            {industry_code: total_main_net_in}，已按净流入降序排列
        """
        from src.data.eastmoney_connector import EastmoneyConnector
        from config.config import get_credentials
        from src.data.symbol_converter import SymbolConverter

        token = get_credentials('eastmoney').get('token', '')
        connector = EastmoneyConnector(token=token)

        industries = self.get_sw_industries(level=level)
        if industries.empty:
            return pd.Series(dtype=float)

        industry_flows = {}
        total = len(industries)

        for idx, row in industries.iterrows():
            code = row['industry_code']
            name = row['industry_name']
            constituents = self.get_industry_constituents(code, date)

            if not constituents:
                industry_flows[code] = 0.0
                continue

            # 转换为掘金格式，获取资金流向
            mq_symbols = SymbolConverter.batch_to_eastmoney(constituents)

            try:
                flow_df = connector.get_money_flow(
                    symbols=mq_symbols,
                    trade_date=date,
                )

                if flow_df is not None and not flow_df.empty:
                    total_flow = flow_df['main_net_in'].sum()
                    industry_flows[code] = total_flow
                else:
                    industry_flows[code] = 0.0
            except Exception as e:
                logger.debug(f"获取 {name}({code}) 资金流向失败: {e}")
                industry_flows[code] = 0.0

            logger.debug(f"  行业资金: {name}({code}) = {industry_flows[code]:.2f} [{idx+1}/{total}]")

        # 排序
        result = pd.Series(industry_flows).sort_values(ascending=False)
        return result
