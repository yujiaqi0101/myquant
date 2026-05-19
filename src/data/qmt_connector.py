"""
QMT接口连接器模块
================

封装国金QMT的xtquant接口，提供统一的连接管理、数据下载和数据获取方法。
"""

import logging
import random
import time
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

# 尝试导入xtquant，若未安装则设置占位符
try:
    from xtquant import xttrader
    from xtquant.xtdata import (
        download_history_data,
        download_financial_data2,
        get_instrument_detail,
        get_market_data_ex,
        get_stock_list_in_sector,
        get_sector_list,
        get_trading_dates,
        get_index_weight,
        get_financial_data,
        download_financial_data2,
        download_index_weight,
    )
    _XTQUANT_AVAILABLE = True
    logger.info("xtquant 导入成功")
except ImportError:
    _XTQUANT_AVAILABLE = False
    logger.warning(
        "xtquant 未安装或导入失败，QMTConnector 将以离线模式运行。"
        "请安装 xtquant 后方可使用完整功能。"
    )


class QMTConnector:
    """
    QMT接口连接器

    封装国金QMT的xtquant接口，提供统一的连接管理、数据下载和数据获取方法。
    当 xtquant 未安装时，所有方法会抛出 ImportError。
    """

    def __init__(self, account: Optional[str] = None, password: Optional[str] = None,
                 qmt_path: Optional[str] = None):
        """
        初始化QMT连接器

        Parameters
        ----------
        account : str, optional
            QMT交易账号
        password : str, optional
            QMT交易密码
        qmt_path : str, optional
            QMT安装目录下userdata_mini路径，如未指定则从配置文件读取
        """
        # 优先使用传入参数，否则从配置读取
        from config.config import get_credentials
        creds = get_credentials('qmt')
        self.account = account or creds.get('account', '')
        self.password = password or creds.get('password', '')
        self.qmt_path = qmt_path or creds.get('path', '')
        self._client = None
        self._connected = False

    def connect(self, max_retries: int = 3, data_only: bool = True) -> bool:
        """
        连接QMT交易系统

        Parameters
        ----------
        max_retries : int
            最大重试次数
        data_only : bool
            是否仅使用数据接口（不使用交易接口XtQuantTrader）

        Returns
        -------
        bool
            连接是否成功
        """
        if not _XTQUANT_AVAILABLE:
            logger.error("xtquant 未安装，无法连接QMT")
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        # 数据模式：只使用xtdata，不使用XtQuantTrader
        if data_only:
            try:
                # xtdata会自动连接，无需手动调用connect
                # 通过获取股票列表来测试连接
                test_stocks = get_stock_list_in_sector('沪深A股')
                if test_stocks and len(test_stocks) > 0:
                    self._connected = True
                    logger.info(f"QMT数据接口连接成功，获取到 {len(test_stocks)} 只股票")
                    return True
                else:
                    logger.error("QMT数据接口连接失败：无法获取股票列表")
                    return False
            except Exception as e:
                logger.error(f"QMT数据接口连接异常: {e}")
                return False

        # 交易模式：使用XtQuantTrader（需要QMT软件配合）
        for attempt in range(max_retries):
            try:
                # 使用随机session ID避免冲突
                session_id = random.randint(100000, 999999)
                self._client = xttrader.XtQuantTrader(
                    path=self.qmt_path, session=session_id
                )
                if self.account:
                    self._client.start()
                    result = self._client.connect()
                    if result == 0:
                        self._connected = True
                        logger.info(f"QMT连接成功，账号: {self.account}, session: {session_id}")
                        return True
                    else:
                        self._connected = False
                        logger.warning(f"QMT连接失败，返回码: {result}，尝试 {attempt + 1}/{max_retries}")
                        if attempt < max_retries - 1:
                            time.sleep(2)
                else:
                    # 无账号时仅标记为已初始化（可用于数据查询）
                    self._connected = True
                    logger.info("QMT已初始化（无交易账号，仅数据模式）")
                    return True
            except Exception as e:
                self._connected = False
                logger.error(f"QMT连接异常: {e}，尝试 {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    time.sleep(2)

        logger.error(f"QMT连接失败，已重试 {max_retries} 次")
        return False

    def disconnect(self):
        """断开QMT连接"""
        if self._client is not None:
            try:
                if self.account:
                    self._client.stop()
                logger.info("QMT已断开连接")
            except Exception as e:
                logger.error(f"断开QMT连接时异常: {e}")
            finally:
                self._client = None
                self._connected = False

    def get_client(self):
        """
        获取底层client对象

        Returns
        -------
        XtQuantTrader 或 None
            底层xtquant客户端对象
        """
        return self._client

    def is_connected(self) -> bool:
        """
        检查是否已连接

        Returns
        -------
        bool
            是否已连接
        """
        return self._connected

    # ============ 数据下载方法 ============

    def download_history_data(
        self,
        stock_list: List[str],
        period: str = '1d',
        start_time: str = '',
        end_time: str = '',
    ):
        """
        下载历史K线数据

        Parameters
        ----------
        stock_list : list of str
            股票代码列表，如 ['000001.SZ', '600000.SH']
        period : str
            K线周期，如 '1d', '5m', '15m', '1h'
        start_time : str
            开始时间，格式 'YYYYMMDD' 或 'YYYYMMDDHHmmss'
        end_time : str
            结束时间，格式 'YYYYMMDD' 或 'YYYYMMDDHHmmss'
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            # download_history_data 只接受单只股票，需要逐个下载
            for i, stock_code in enumerate(stock_list):
                if i % 100 == 0:
                    logger.info(f"下载历史数据进度: {i}/{len(stock_list)}")
                download_history_data(stock_code, period, start_time, end_time)
            logger.info(f"历史数据下载完成，共 {len(stock_list)} 只股票")
        except Exception as e:
            logger.error(f"下载历史数据失败: {e}")
            raise

    def download_sector_data(self):
        """
        下载板块数据

        使用 client.down_all_sector_data() 下载全部板块数据。
        如果 client 不可用，则回退到 xtdata 层级。
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            logger.info("开始下载板块数据")
            if self._client is not None and hasattr(self._client, 'down_all_sector_data'):
                self._client.down_all_sector_data()
                logger.info("板块数据下载完成（通过client）")
            else:
                # 回退方案：通过 xtdata 下载
                from xtquant.xtdata import download_sector_data as _download_sector
                _download_sector()
                logger.info("板块数据下载完成（通过xtdata回退）")
        except Exception as e:
            logger.error(f"下载板块数据失败: {e}")
            raise

    def download_financial_data(
        self,
        stock_list: List[str],
        table_list: List[str],
        start_time: str = '',
        end_time: str = '',
    ):
        """
        下载财务数据

        Parameters
        ----------
        stock_list : list of str
            股票代码列表
        table_list : list of str
            财务报表名称列表，如 ['Balance', 'Income', 'CashFlow']
        start_time : str
            开始时间，格式 'YYYYMMDD'
        end_time : str
            结束时间，格式 'YYYYMMDD'
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            logger.info(
                f"开始下载财务数据: {len(stock_list)}只股票, "
                f"报表={table_list}, 起始={start_time}, 结束={end_time}"
            )
            download_financial_data2(stock_list, table_list, start_time, end_time)
            logger.info("财务数据下载完成")
        except Exception as e:
            logger.error(f"下载财务数据失败: {e}")
            raise

    # ============ 数据获取方法 ============

    def get_instrument_detail(self, stock_code: str) -> dict:
        """
        获取股票/合约详细信息

        Parameters
        ----------
        stock_code : str
            股票代码，如 '000001.SZ'

        Returns
        -------
        dict
            合约详情字典
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            detail = get_instrument_detail(stock_code)
            logger.debug(f"获取合约详情: {stock_code}")
            return detail if detail is not None else {}
        except Exception as e:
            logger.error(f"获取合约详情失败 [{stock_code}]: {e}")
            raise

    def get_market_data_ex(
        self,
        stock_list: List[str],
        period: str = '1d',
        start_time: str = '',
        end_time: str = '',
        count: int = -1,
        dividend_type: str = 'front',
        field_list: List[str] = None,
    ) -> dict:
        """
        获取市场K线数据（扩展版）

        Parameters
        ----------
        stock_list : list of str
            股票代码列表
        period : str
            K线周期
        start_time : str
            开始时间
        end_time : str
            结束时间
        count : int
            获取数量，-1表示全部
        dividend_type : str
            复权类型: 'front'前复权, 'back'后复权, 'none'不复权
        field_list : list of str, optional
            字段列表，如 ['time', 'open', 'high', 'low', 'close', 'volume', 'amount']

        Returns
        -------
        dict
            {stock_code: DataFrame} 格式的数据字典
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            logger.debug(
                f"获取市场数据: {len(stock_list)}只股票, "
                f"周期={period}, 复权={dividend_type}"
            )
            # 默认字段列表
            if field_list is None:
                field_list = ['time', 'open', 'high', 'low', 'close', 'volume', 'amount', 'preClose', 'suspendFlag']
            data = get_market_data_ex(
                field_list=field_list,
                stock_list=stock_list,
                period=period,
                start_time=start_time,
                end_time=end_time,
                count=count,
                dividend_type=dividend_type,
            )
            return data if data is not None else {}
        except Exception as e:
            logger.error(f"获取市场数据失败: {e}")
            raise

    def get_stock_list_in_sector(self, sector_name: str) -> list:
        """
        获取板块内的股票列表

        Parameters
        ----------
        sector_name : str
            板块名称，如 '沪深300', '中证500'

        Returns
        -------
        list
            股票代码列表
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            stock_list = get_stock_list_in_sector(sector_name)
            logger.debug(f"获取板块 [{sector_name}] 股票列表: {len(stock_list)}只")
            return stock_list if stock_list is not None else []
        except Exception as e:
            logger.error(f"获取板块股票列表失败 [{sector_name}]: {e}")
            raise

    def get_index_list(self) -> list:
        """
        获取所有指数代码列表

        通过 '沪深指数', '沪市指数', '深市指数' 等板块获取指数列表

        Returns
        -------
        list
            指数代码列表
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            index_codes = set()
            index_sectors = ['沪深指数', '沪市指数', '深市指数']

            for sector in index_sectors:
                try:
                    codes = get_stock_list_in_sector(sector)
                    if codes:
                        index_codes.update(codes)
                except Exception:
                    pass

            result = list(index_codes)
            logger.info(f"获取指数列表: {len(result)} 个")
            return result
        except Exception as e:
            logger.error(f"获取指数列表失败: {e}")
            raise

    def get_sector_list(self) -> list:
        """
        获取所有板块列表

        Returns
        -------
        list
            板块名称列表
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            sectors = get_sector_list()
            logger.debug(f"获取板块列表: {len(sectors)}个板块")
            return sectors if sectors is not None else []
        except Exception as e:
            logger.error(f"获取板块列表失败: {e}")
            raise

    def download_index_weight(self, index_codes: list):
        """
        下载指数成分股权重数据

        必须先下载才能通过 get_index_weight 获取

        Parameters
        ----------
        index_codes : list of str
            指数代码列表
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            logger.info(f"开始下载指数权重数据: {len(index_codes)} 个指数")
            download_index_weight()
            logger.info("指数权重数据下载完成")
        except Exception as e:
            logger.error(f"下载指数权重数据失败: {e}")
            raise

    def get_index_weight(self, index_code: str) -> dict:
        """
        获取指数成分股权重

        Parameters
        ----------
        index_code : str
            指数代码，如 '000300.SH'

        Returns
        -------
        dict
            成分股权重信息
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            weight = get_index_weight(index_code)
            logger.debug(f"获取指数权重: {index_code}")
            return weight if weight is not None else {}
        except Exception as e:
            logger.error(f"获取指数权重失败 [{index_code}]: {e}")
            raise

    def download_financial_data(self, stock_list, table_list, start_time='', end_time=''):
        """
        下载财务数据到本地

        财务数据必须先下载才能通过 get_financial_data 获取

        Parameters
        ----------
        stock_list : list of str
            股票代码列表
        table_list : list of str
            财务报表名称列表，如 ['Balance', 'Income', 'CashFlow']
        start_time : str
            开始时间
        end_time : str
            结束时间
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            logger.info(
                f"开始下载财务数据: {len(stock_list)}只股票, "
                f"报表={table_list}, 起始={start_time}, 结束={end_time}"
            )
            download_financial_data2(stock_list, table_list, start_time, end_time)
            logger.info("财务数据下载完成")
        except Exception as e:
            logger.error(f"下载财务数据失败: {e}")
            raise

    def get_financial_data(
        self,
        stock_list: List[str],
        table_list: List[str],
        start_time: str = '',
        end_time: str = '',
    ) -> dict:
        """
        获取财务数据

        Parameters
        ----------
        stock_list : list of str
            股票代码列表
        table_list : list of str
            财务报表名称列表
        start_time : str
            开始时间
        end_time : str
            结束时间

        Returns
        -------
        dict
            财务数据字典
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            logger.debug(
                f"获取财务数据: {len(stock_list)}只股票, 报表={table_list}"
            )
            data = get_financial_data(stock_list, table_list, start_time, end_time)
            return data if data is not None else {}
        except Exception as e:
            logger.error(f"获取财务数据失败: {e}")
            raise

    def get_trading_dates(
        self,
        market: str = 'SH',
        start_time: str = '',
        end_time: str = '',
    ) -> list:
        """
        获取交易日历

        Parameters
        ----------
        market : str
            市场代码，'SH' 上海, 'SZ' 深圳
        start_time : str
            开始时间，格式 'YYYYMMDD'
        end_time : str
            结束时间，格式 'YYYYMMDD'

        Returns
        -------
        list
            交易日列表
        """
        if not _XTQUANT_AVAILABLE:
            raise ImportError("xtquant 未安装，请先安装 xtquant 库")

        try:
            dates = get_trading_dates(market, start_time, end_time)
            logger.debug(
                f"获取交易日历: 市场={market}, {len(dates) if dates else 0}个交易日"
            )
            return dates if dates is not None else []
        except Exception as e:
            logger.error(f"获取交易日历失败: {e}")
            raise
