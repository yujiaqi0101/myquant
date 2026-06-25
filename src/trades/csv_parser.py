"""
CSV 交易记录解析器
==================

支持自动识别主流券商 CSV 格式，将交易记录解析为统一 TradeRecord 列表。

支持的券商：华泰、中信、国金、东方财富、同花顺，以及通用格式。
"""

import csv
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import pandas as pd

from .models import (
    TradeRecord,
    BrokerFormat,
    FIELD_ALIASES,
    TRADE_TYPE_ALIASES,
    normalize_stock_code,
    normalize_trade_type,
)

logger = logging.getLogger(__name__)


class TradeCSVParser:
    """
    券商交易记录 CSV 解析器

    使用流程：
        parser = TradeCSVParser()
        records = parser.parse('trades.csv')          # 自动识别格式
        records = parser.parse('trades.csv', broker='huatai')  # 指定格式
    """

    def __init__(self):
        self._broker: Optional[BrokerFormat] = None
        self._field_map: Dict[str, str] = {}
        self._source_file: str = ''

    def detect_broker(self, columns: List[str]) -> BrokerFormat:
        """
        根据 CSV 列名自动识别券商格式

        匹配策略：计算每个券商的别名命中数，命中最多的即为该格式。
        若所有券商命中数均低于阈值，返回 GENERIC。

        Parameters
        ----------
        columns : List[str]
            CSV 表头列名列表

        Returns
        -------
        BrokerFormat
            识别出的券商格式
        """
        col_set = set(col.strip() for col in columns)
        best_broker = BrokerFormat.GENERIC
        best_score = 0

        for broker_key, aliases_dict in FIELD_ALIASES.items():
            score = 0
            for unified_field, alias_list in aliases_dict.items():
                for alias in alias_list:
                    if alias in col_set:
                        score += 1
                        break  # 每个统一字段只计一次
            if score > best_score:
                best_score = score
                best_broker = BrokerFormat(broker_key)

        # 至少匹配 4 个核心字段才认为是已知券商格式
        if best_score < 4:
            logger.info(f"CSV 列名匹配度不足 ({best_score} 匹配)，使用通用格式")
            return BrokerFormat.GENERIC

        logger.info(f"识别券商格式: {best_broker.display_name} (匹配 {best_score} 个字段)")
        return best_broker

    def _build_field_map(self, columns: List[str], broker: BrokerFormat) -> Dict[str, str]:
        """
        构建 CSV 列名到统一字段名的映射

        Parameters
        ----------
        columns : List[str]
            CSV 实际列名
        broker : BrokerFormat
            券商格式

        Returns
        -------
        Dict[str, str]
            {CSV列名: 统一字段名}
        """
        col_set = set(col.strip() for col in columns)
        field_map: Dict[str, str] = {}

        # 获取该券商的别名表，通用格式则合并所有券商的别名
        if broker == BrokerFormat.GENERIC:
            aliases_pool = {}
            for bk, aliases_dict in FIELD_ALIASES.items():
                for unified_field, alias_list in aliases_dict.items():
                    if unified_field not in aliases_pool:
                        aliases_pool[unified_field] = []
                    aliases_pool[unified_field].extend(alias_list)
        else:
            aliases_pool = FIELD_ALIASES.get(broker.value, {})

        for unified_field, alias_list in aliases_pool.items():
            for alias in alias_list:
                if alias in col_set:
                    field_map[alias] = unified_field
                    break

        return field_map

    def parse(
        self,
        file_path: str,
        broker: Optional[str] = None,
    ) -> Tuple[List[TradeRecord], BrokerFormat, List[str]]:
        """
        解析 CSV 文件

        Parameters
        ----------
        file_path : str
            CSV 文件路径
        broker : str, optional
            指定券商格式（huatai/citic/guojin/eastmoney/tonghuashun/generic），
            不指定则自动识别

        Returns
        -------
        Tuple[List[TradeRecord], BrokerFormat, List[str]]
            (交易记录列表, 识别的券商格式, 解析警告列表)

        Raises
        ------
        FileNotFoundError
            文件不存在
        ValueError
            CSV 格式错误或无法解析
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV 文件不存在: {file_path}")

        self._source_file = path.name

        # 尝试多种编码读取（券商导出文件可能使用 GBK/GB2312/UTF-8）
        df, encoding = self._read_csv_robust(str(path))
        logger.info(f"读取 CSV: {path.name}, 编码={encoding}, 行数={len(df)}")

        if df.empty:
            raise ValueError(f"CSV 文件为空或无法解析: {file_path}")

        # 识别券商格式
        if broker:
            try:
                broker_format = BrokerFormat(broker)
            except ValueError:
                raise ValueError(
                    f"不支持的券商格式: {broker}，"
                    f"可选: huatai/citic/guojin/eastmoney/tonghuashun/generic"
                )
        else:
            broker_format = self.detect_broker(list(df.columns))

        self._broker = broker_format
        self._field_map = self._build_field_map(list(df.columns), broker_format)

        # 检查必要字段
        required_fields = ['trade_date', 'stock_code', 'trade_type', 'price', 'quantity', 'amount']
        missing = [f for f in required_fields if f not in self._field_map.values()]
        if missing:
            raise ValueError(
                f"CSV 缺少必要字段映射: {missing}。"
                f"识别到的字段: {list(self._field_map.values())}。"
                f"请检查 CSV 表头是否包含: 交易日期、证券代码、买卖方向、成交价格、成交数量、成交金额"
            )

        # 逐行解析
        records: List[TradeRecord] = []
        warnings: List[str] = []

        for idx, row in df.iterrows():
            try:
                record = self._parse_row(row, idx, warnings)
                if record is not None:
                    records.append(record)
            except Exception as e:
                warnings.append(f"第 {idx + 2} 行解析失败: {e}")

        logger.info(f"解析完成: {len(records)} 条记录, {len(warnings)} 个警告")
        return records, broker_format, warnings

    def _read_csv_robust(self, file_path: str) -> Tuple[pd.DataFrame, str]:
        """
        尝试多种编码读取 CSV 文件

        券商导出的 CSV 通常使用 GBK 或 UTF-8-BOM 编码。
        """
        encodings = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'gb18030']
        for enc in encodings:
            try:
                df = pd.read_csv(file_path, encoding=enc, dtype=str, skipinitialspace=True)
                # 验证是否真的读到了中文内容（非乱码）
                if df.shape[1] > 0 and not df.empty:
                    sample = str(df.iloc[0, 0])
                    # 如果首列包含乱码字符，继续尝试其他编码
                    if '\ufffd' not in sample:
                        return df, enc
            except (UnicodeDecodeError, UnicodeError):
                continue
            except Exception as e:
                logger.warning(f"使用编码 {enc} 读取失败: {e}")
                continue
        # 最后一次尝试（gb18030 兼容性最广）
        df = pd.read_csv(file_path, encoding='gb18030', dtype=str, skipinitialspace=True,
                         on_bad_lines='warn')
        return df, 'gb18030'

    def _parse_row(self, row: pd.Series, idx: int, warnings: List[str]) -> Optional[TradeRecord]:
        """
        解析单行记录

        将 CSV 行数据根据字段映射转换为 TradeRecord。
        """
        # 提取字段值
        values: Dict[str, str] = {}
        for csv_col, unified_field in self._field_map.items():
            if csv_col in row.index:
                val = row[csv_col]
                if pd.notna(val):
                    values[unified_field] = str(val).strip()

        # 日期处理：支持多种格式
        trade_date = self._parse_date(values.get('trade_date', ''))
        if not trade_date:
            warnings.append(f"第 {idx + 2} 行: 日期无法解析 '{values.get('trade_date', '')}'，跳过")
            return None

        # 股票代码归一化
        stock_code = normalize_stock_code(values.get('stock_code', ''))
        if not stock_code or '.' not in stock_code:
            warnings.append(f"第 {idx + 2} 行: 股票代码无法归一化 '{values.get('stock_code', '')}'，跳过")
            return None

        # 交易类型归一化
        trade_type = normalize_trade_type(values.get('trade_type', ''))
        if not trade_type:
            warnings.append(f"第 {idx + 2} 行: 交易类型无法识别 '{values.get('trade_type', '')}'，跳过")
            return None

        # 数值字段解析
        price = self._parse_float(values.get('price', '0'))
        quantity = self._parse_float(values.get('quantity', '0'))
        amount = self._parse_float(values.get('amount', '0'))
        commission = self._parse_float(values.get('commission', '0'))
        stamp_tax = self._parse_float(values.get('stamp_tax', '0'))
        transfer_fee = self._parse_float(values.get('transfer_fee', '0'))
        other_fee = self._parse_float(values.get('other_fee', '0'))

        # 数量为负数的券商格式（卖出用负数表示），取绝对值
        if quantity < 0:
            quantity = abs(quantity)

        # 成交金额为空时自动计算
        if amount == 0 and price > 0 and quantity > 0:
            amount = price * quantity

        return TradeRecord(
            trade_date=trade_date,
            stock_code=stock_code,
            stock_name=values.get('stock_name', ''),
            trade_type=trade_type,
            price=price,
            quantity=quantity,
            amount=amount,
            commission=commission,
            stamp_tax=stamp_tax,
            transfer_fee=transfer_fee,
            other_fee=other_fee,
            trade_time=values.get('trade_time', ''),
            broker=self._broker.value if self._broker else '',
            account=values.get('account', ''),
        )

    def _parse_date(self, date_str: str) -> str:
        """
        解析日期字符串，统一输出 YYYY-MM-DD 格式

        支持格式：
        - 2024-01-15 / 2024-1-5
        - 2024/01/15
        - 20240115
        - 2024年01月15日
        """
        if not date_str:
            return ''
        date_str = str(date_str).strip()

        # 去除可能的时间部分
        date_str = date_str.split(' ')[0].split('T')[0]

        # YYYY-MM-DD
        if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', date_str):
            parts = date_str.split('-')
            return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"

        # YYYY/MM/DD
        if re.match(r'^\d{4}/\d{1,2}/\d{1,2}$', date_str):
            parts = date_str.split('/')
            return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"

        # YYYYMMDD
        if re.match(r'^\d{8}$', date_str):
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

        # YYYY年MM月DD日
        m = re.match(r'^(\d{4})年(\d{1,2})月(\d{1,2})日$', date_str)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        # 尝试 pandas 解析
        try:
            ts = pd.to_datetime(date_str)
            return ts.strftime('%Y-%m-%d')
        except Exception:
            return ''

    def _parse_float(self, val: str) -> float:
        """
        解析数值字符串，处理千分位逗号、空值等
        """
        if not val or val == '' or val == '--':
            return 0.0
        val = str(val).strip()
        # 去除千分位逗号
        val = val.replace(',', '').replace('，', '')
        # 去除货币符号和单位
        val = re.sub(r'[¥￥$元]', '', val)
        try:
            return float(val)
        except ValueError:
            return 0.0
