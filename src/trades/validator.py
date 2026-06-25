"""
交易记录数据验证模块
====================

对导入的交易记录进行完整性和有效性检查：
1. 格式验证：日期、代码、交易类型格式是否正确
2. 数据范围验证：价格、数量、金额是否在合理范围
3. 业务规则验证：金额一致性、手续费合理性、日期合法性
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict

from .models import TradeRecord

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """验证错误"""

    row_index: int          # 行号（0-based）
    field: str              # 字段名
    error_type: str          # 错误类型 format/range/business
    message: str             # 错误描述
    value: str = ''         # 错误值


@dataclass
class ValidationResult:
    """验证结果"""

    valid_count: int = 0            # 有效记录数
    invalid_count: int = 0          # 无效记录数
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """是否全部通过验证（无错误，可能有警告）"""
        return self.invalid_count == 0

    @property
    def total_count(self) -> int:
        return self.valid_count + self.invalid_count

    def add_error(self, row_index: int, field: str, error_type: str, message: str, value: str = ''):
        self.errors.append(ValidationError(row_index, field, error_type, message, value))
        self.invalid_count += 1

    def add_warning(self, message: str):
        self.warnings.append(message)

    def summary(self) -> str:
        """生成验证摘要文本"""
        lines = []
        lines.append("=" * 60)
        lines.append("交易记录验证报告")
        lines.append("=" * 60)
        lines.append(f"总记录数: {self.total_count}")
        lines.append(f"有效记录: {self.valid_count}")
        lines.append(f"无效记录: {self.invalid_count}")
        lines.append(f"警告数量: {len(self.warnings)}")

        if self.errors:
            lines.append("")
            lines.append("-" * 40)
            lines.append(f"错误详情 ({len(self.errors)} 条):")
            # 按错误类型分组
            by_type: Dict[str, List[ValidationError]] = {}
            for err in self.errors:
                by_type.setdefault(err.error_type, []).append(err)

            type_names = {
                'format': '格式错误',
                'range': '范围错误',
                'business': '业务规则错误',
            }
            for etype, errs in by_type.items():
                lines.append(f"\n  [{type_names.get(etype, etype)}] ({len(errs)} 条)")
                for err in errs[:10]:  # 每类最多显示10条
                    lines.append(f"    第{err.row_index + 1}行 [{err.field}]: {err.message}")
                if len(errs) > 10:
                    lines.append(f"    ... 还有 {len(errs) - 10} 条")

        if self.warnings:
            lines.append("")
            lines.append("-" * 40)
            lines.append(f"警告 ({len(self.warnings)} 条):")
            for w in self.warnings[:10]:
                lines.append(f"  - {w}")
            if len(self.warnings) > 10:
                lines.append(f"  ... 还有 {len(self.warnings) - 10} 条")

        lines.append("=" * 60)
        return "\n".join(lines)


class TradeValidator:
    """
    交易记录验证器

    执行三类验证：
    1. 格式验证 - 字段格式是否正确
    2. 范围验证 - 数值是否在合理范围
    3. 业务规则验证 - 数据一致性和合理性
    """

    # A股价格涨跌停限制（普通股票 ±10%，ST ±5%）
    MAX_PRICE = 100000       # 单股价格上限
    MIN_PRICE = 0.01         # 单股价格下限
    MAX_QUANTITY = 100_000_000  # 单笔数量上限（1亿股）
    MAX_AMOUNT = 100_000_000_000  # 单笔金额上限（千亿）
    AMOUNT_TOLERANCE = 0.02  # 金额一致性容差 2%（考虑手续费/滑点）

    def validate(self, records: List[TradeRecord]) -> ValidationResult:
        """
        验证交易记录列表

        Parameters
        ----------
        records : List[TradeRecord]
            待验证的交易记录

        Returns
        -------
        ValidationResult
            验证结果
        """
        result = ValidationResult()

        for idx, record in enumerate(records):
            has_error = False

            # 1. 格式验证
            fmt_errors = self._validate_format(idx, record)
            for err in fmt_errors:
                result.errors.append(err)
                has_error = True

            # 2. 范围验证
            range_errors = self._validate_range(idx, record)
            for err in range_errors:
                result.errors.append(err)
                has_error = True

            # 3. 业务规则验证
            biz_errors, biz_warnings = self._validate_business_rules(idx, record)
            for err in biz_errors:
                result.errors.append(err)
                has_error = True
            result.warnings.extend(biz_warnings)

            if has_error:
                result.invalid_count += 1
            else:
                result.valid_count += 1

        logger.info(f"验证完成: {result.valid_count} 条有效, {result.invalid_count} 条无效")
        return result

    def _validate_format(self, idx: int, record: TradeRecord) -> List[ValidationError]:
        """格式验证：检查字段格式是否正确"""
        errors: List[ValidationError] = []

        # 交易日期格式
        if not record.trade_date:
            errors.append(ValidationError(idx, 'trade_date', 'format', '交易日期为空'))
        else:
            try:
                datetime.strptime(record.trade_date, '%Y-%m-%d')
            except ValueError:
                errors.append(ValidationError(
                    idx, 'trade_date', 'format',
                    f'交易日期格式错误: {record.trade_date}（应为 YYYY-MM-DD）',
                    record.trade_date
                ))

        # 股票代码格式
        if not record.stock_code:
            errors.append(ValidationError(idx, 'stock_code', 'format', '股票代码为空'))
        elif '.' not in record.stock_code:
            errors.append(ValidationError(
                idx, 'stock_code', 'format',
                f'股票代码格式错误: {record.stock_code}（应包含交易所后缀如 .SZ/.SH）',
                record.stock_code
            ))

        # 交易类型
        if record.trade_type not in ('buy', 'sell'):
            errors.append(ValidationError(
                idx, 'trade_type', 'format',
                f'交易类型无效: {record.trade_type}（应为 buy 或 sell）',
                record.trade_type
            ))

        # 证券名称
        if not record.stock_name:
            errors.append(ValidationError(idx, 'stock_name', 'format', '证券名称为空'))

        return errors

    def _validate_range(self, idx: int, record: TradeRecord) -> List[ValidationError]:
        """范围验证：检查数值是否在合理范围"""
        errors: List[ValidationError] = []

        # 价格范围
        if record.price <= 0:
            errors.append(ValidationError(
                idx, 'price', 'range',
                f'成交价格必须大于0: {record.price}',
                str(record.price)
            ))
        elif record.price > self.MAX_PRICE:
            errors.append(ValidationError(
                idx, 'price', 'range',
                f'成交价格异常过高: {record.price}（上限 {self.MAX_PRICE}）',
                str(record.price)
            ))

        # 数量范围
        if record.quantity <= 0:
            errors.append(ValidationError(
                idx, 'quantity', 'range',
                f'成交数量必须大于0: {record.quantity}',
                str(record.quantity)
            ))
        elif record.quantity > self.MAX_QUANTITY:
            errors.append(ValidationError(
                idx, 'quantity', 'range',
                f'成交数量异常过大: {record.quantity}（上限 {self.MAX_QUANTITY}）',
                str(record.quantity)
            ))

        # 金额范围
        if record.amount < 0:
            errors.append(ValidationError(
                idx, 'amount', 'range',
                f'成交金额不能为负: {record.amount}',
                str(record.amount)
            ))
        elif record.amount > self.MAX_AMOUNT:
            errors.append(ValidationError(
                idx, 'amount', 'range',
                f'成交金额异常过大: {record.amount}（上限 {self.MAX_AMOUNT}）',
                str(record.amount)
            ))

        # 手续费非负
        for fee_name in ['commission', 'stamp_tax', 'transfer_fee', 'other_fee']:
            fee_val = getattr(record, fee_name, 0)
            if fee_val < 0:
                errors.append(ValidationError(
                    idx, fee_name, 'range',
                    f'{fee_name} 不能为负: {fee_val}',
                    str(fee_val)
                ))

        return errors

    def _validate_business_rules(
        self, idx: int, record: TradeRecord
    ) -> tuple[List[ValidationError], List[str]]:
        """业务规则验证"""
        errors: List[ValidationError] = []
        warnings: List[str] = []

        # 金额一致性校验：amount ≈ price × quantity
        if record.price > 0 and record.quantity > 0:
            expected_amount = record.price * record.quantity
            if record.amount > 0:
                diff = abs(record.amount - expected_amount)
                tolerance = expected_amount * self.AMOUNT_TOLERANCE
                if diff > tolerance:
                    errors.append(ValidationError(
                        idx, 'amount', 'business',
                        f'成交金额不一致: amount={record.amount}, '
                        f'price×quantity={expected_amount:.2f} (差异 {diff:.2f})',
                        str(record.amount)
                    ))

        # 日期合法性：不晚于今天
        if record.trade_date:
            try:
                trade_dt = datetime.strptime(record.trade_date, '%Y-%m-%d').date()
                today = date.today()
                if trade_dt > today:
                    errors.append(ValidationError(
                        idx, 'trade_date', 'business',
                        f'交易日期不能晚于今天: {record.trade_date}',
                        record.trade_date
                    ))
            except ValueError:
                pass  # 格式错误已在格式验证中捕获

        # 手续费合理性：通常不超过成交金额的 1%
        if record.amount > 0 and record.commission > 0:
            commission_rate = record.commission / record.amount
            if commission_rate > 0.01:
                warnings.append(
                    f"第{idx + 1}行: 手续费率偏高 {commission_rate:.4%} "
                    f"(佣金={record.commission}, 金额={record.amount})"
                )

        # 印花税：仅卖出收取，费率约 0.05%
        if record.stamp_tax > 0 and record.trade_type == 'buy':
            warnings.append(
                f"第{idx + 1}行: 买入记录有印花税 {record.stamp_tax}（通常仅卖出收取）"
            )

        return errors, warnings
