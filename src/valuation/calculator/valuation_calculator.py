"""
估值计算器主类
整合各行业估值模型
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class FinancialData:
    """财务数据结构"""
    # 利润表数据
    revenue: Optional[float] = None  # 营业收入
    net_profit: Optional[float] = None  # 净利润
    operating_profit: Optional[float] = None  # 营业利润
    ebitda: Optional[float] = None  # 息税折旧摊销前利润

    # 资产负债表数据
    total_assets: Optional[float] = None  # 总资产
    total_liabilities: Optional[float] = None  # 总负债
    shareholders_equity: Optional[float] = None  # 股东权益
    total_debt: Optional[float] = None  # 总债务
    cash_and_equivalents: Optional[float] = None  # 现金及等价物

    # 现金流量表数据
    operating_cash_flow: Optional[float] = None  # 经营活动现金流
    free_cash_flow: Optional[float] = None  # 自由现金流
    capex: Optional[float] = None  # 资本支出

    # 衍生指标
    eps: Optional[float] = None  # 每股收益
    book_value_per_share: Optional[float] = None  # 每股净资产
    revenue_per_share: Optional[float] = None  # 每股营业收入


@dataclass
class PriceData:
    """股价数据结构"""
    current_price: Optional[float] = None  # 当前股价
    total_shares: Optional[float] = None  # 总股本
    market_cap: Optional[float] = None  # 市值


@dataclass
class ValuationInput:
    """估值输入数据结构"""
    stock_code: str
    industry: str
    financial_data: FinancialData
    price_data: PriceData
    report_date: Optional[str] = None
    historical_pe: List[float] = field(default_factory=list)
    historical_pb: List[float] = field(default_factory=list)
    historical_ps: List[float] = field(default_factory=list)


@dataclass
class ValuationResult:
    """估值结果数据结构"""
    method_name: str  # 估值方法名称
    fair_value: Optional[float]  # 合理价值（股价）
    fair_value_low: Optional[float] = None  # 合理价值区间下限
    fair_value_high: Optional[float] = None  # 合理价值区间上限
    current_price: Optional[float] = None  # 当前股价
    deviation_pct: Optional[float] = None  # 偏离百分比
    pe_ratio: Optional[float] = None  # 对应PE
    pb_ratio: Optional[float] = None  # 对应PB
    ps_ratio: Optional[float] = None  # 对应PS
    confidence: str = "medium"  # 置信度：high/medium/low
    notes: str = ""  # 备注说明


class BaseValuationModel:
    """估值模型基类"""

    def calculate(self, input_data: ValuationInput) -> List[ValuationResult]:
        """
        执行估值计算

        Args:
            input_data: 估值输入数据

        Returns:
            估值结果列表
        """
        raise NotImplementedError("子类必须实现此方法")

    def get_model_name(self) -> str:
        """获取模型名称"""
        return self.__class__.__name__


class GeneralValuationModel(BaseValuationModel):
    """通用估值模型（适用于大多数行业）"""

    def calculate(self, input_data: ValuationInput) -> List[ValuationResult]:
        """使用PE、PB、DCF等方法进行估值"""
        from .metrics import ValuationMetrics

        results = []
        fd = input_data.financial_data
        pd = input_data.price_data

        # PE估值法
        if fd.eps and fd.eps > 0 and pd.current_price:
            # 使用历史PE中位数作为目标PE
            target_pe = self._get_median(input_data.historical_pe) if input_data.historical_pe else 15.0
            if target_pe:
                fair_value = ValuationMetrics.calculate_fair_value_from_pe(fd.eps, target_pe)
                if fair_value:
                    current_pe = ValuationMetrics.calculate_pe(pd.current_price, fd.eps)
                    deviation = (pd.current_price - fair_value) / fair_value * 100 if fair_value else None
                    results.append(ValuationResult(
                        method_name="PE估值法",
                        fair_value=round(fair_value, 2),
                        fair_value_low=round(fd.eps * target_pe * 0.8, 2),
                        fair_value_high=round(fd.eps * target_pe * 1.2, 2),
                        current_price=pd.current_price,
                        deviation_pct=round(deviation, 2) if deviation else None,
                        pe_ratio=round(current_pe, 2) if current_pe else None,
                        confidence="medium"
                    ))

        # PB估值法
        if fd.book_value_per_share and fd.book_value_per_share > 0 and pd.current_price:
            target_pb = self._get_median(input_data.historical_pb) if input_data.historical_pb else 1.5
            if target_pb:
                fair_value = ValuationMetrics.calculate_fair_value_from_pb(fd.book_value_per_share, target_pb)
                if fair_value:
                    current_pb = ValuationMetrics.calculate_pb(pd.current_price, fd.book_value_per_share)
                    deviation = (pd.current_price - fair_value) / fair_value * 100 if fair_value else None
                    results.append(ValuationResult(
                        method_name="PB估值法",
                        fair_value=round(fair_value, 2),
                        fair_value_low=round(fd.book_value_per_share * target_pb * 0.8, 2),
                        fair_value_high=round(fd.book_value_per_share * target_pb * 1.2, 2),
                        current_price=pd.current_price,
                        deviation_pct=round(deviation, 2) if deviation else None,
                        pb_ratio=round(current_pb, 2) if current_pb else None,
                        confidence="medium"
                    ))

        # PS估值法
        if fd.revenue_per_share and fd.revenue_per_share > 0 and pd.current_price:
            target_ps = self._get_median(input_data.historical_ps) if input_data.historical_ps else 2.0
            if target_ps:
                fair_value = ValuationMetrics.calculate_fair_value_from_ps(fd.revenue_per_share, target_ps)
                if fair_value:
                    current_ps = ValuationMetrics.calculate_ps(pd.current_price, fd.revenue_per_share)
                    deviation = (pd.current_price - fair_value) / fair_value * 100 if fair_value else None
                    results.append(ValuationResult(
                        method_name="PS估值法",
                        fair_value=round(fair_value, 2),
                        fair_value_low=round(fd.revenue_per_share * target_ps * 0.7, 2),
                        fair_value_high=round(fd.revenue_per_share * target_ps * 1.3, 2),
                        current_price=pd.current_price,
                        deviation_pct=round(deviation, 2) if deviation else None,
                        ps_ratio=round(current_ps, 2) if current_ps else None,
                        confidence="low"
                    ))

        # DCF估值法
        if fd.free_cash_flow and fd.free_cash_flow > 0 and pd.total_shares and pd.total_shares > 0:
            fcf_per_share = fd.free_cash_flow / pd.total_shares
            # 使用默认参数进行DCF计算
            dcf_value = ValuationMetrics.calculate_dcf(
                free_cash_flow=fcf_per_share,
                growth_rate=0.05,  # 假设5%增长率
                discount_rate=0.10,  # 10%折现率
                terminal_growth=0.02,  # 2%永续增长
                years=5
            )
            if dcf_value:
                deviation = (pd.current_price - dcf_value) / dcf_value * 100 if pd.current_price else None
                results.append(ValuationResult(
                    method_name="DCF估值法",
                    fair_value=round(dcf_value, 2),
                    fair_value_low=round(dcf_value * 0.7, 2),
                    fair_value_high=round(dcf_value * 1.3, 2),
                    current_price=pd.current_price,
                    deviation_pct=round(deviation, 2) if deviation else None,
                    confidence="medium",
                    notes="基于5%增长率、10%折现率假设"
                ))

        return results

    def _get_median(self, values: List[float]) -> Optional[float]:
        """获取中位数"""
        if not values:
            return None
        sorted_values = sorted([v for v in values if v is not None and v > 0])
        if not sorted_values:
            return None
        n = len(sorted_values)
        if n % 2 == 1:
            return sorted_values[n // 2]
        else:
            return (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2


class BankValuationModel(BaseValuationModel):
    """银行业估值模型"""

    def calculate(self, input_data: ValuationInput) -> List[ValuationResult]:
        """银行业主要使用PB估值法"""
        from .metrics import ValuationMetrics

        results = []
        fd = input_data.financial_data
        pd = input_data.price_data

        # PB估值法（银行业首选）
        if fd.book_value_per_share and fd.book_value_per_share > 0 and pd.current_price:
            target_pb = self._get_median(input_data.historical_pb) if input_data.historical_pb else 1.0
            if target_pb:
                fair_value = ValuationMetrics.calculate_fair_value_from_pb(fd.book_value_per_share, target_pb)
                if fair_value:
                    current_pb = ValuationMetrics.calculate_pb(pd.current_price, fd.book_value_per_share)
                    deviation = (pd.current_price - fair_value) / fair_value * 100 if fair_value else None
                    results.append(ValuationResult(
                        method_name="PB估值法（银行业）",
                        fair_value=round(fair_value, 2),
                        fair_value_low=round(fd.book_value_per_share * target_pb * 0.85, 2),
                        fair_value_high=round(fd.book_value_per_share * target_pb * 1.15, 2),
                        current_price=pd.current_price,
                        deviation_pct=round(deviation, 2) if deviation else None,
                        pb_ratio=round(current_pb, 2) if current_pb else None,
                        confidence="high",
                        notes="银行业首选估值方法"
                    ))

        # PE估值法（辅助）
        if fd.eps and fd.eps > 0 and pd.current_price:
            target_pe = 8.0  # 银行业通常PE较低
            fair_value = ValuationMetrics.calculate_fair_value_from_pe(fd.eps, target_pe)
            if fair_value:
                current_pe = ValuationMetrics.calculate_pe(pd.current_price, fd.eps)
                deviation = (pd.current_price - fair_value) / fair_value * 100 if fair_value else None
                results.append(ValuationResult(
                    method_name="PE估值法（辅助）",
                    fair_value=round(fair_value, 2),
                    current_price=pd.current_price,
                    deviation_pct=round(deviation, 2) if deviation else None,
                    pe_ratio=round(current_pe, 2) if current_pe else None,
                    confidence="low",
                    notes="仅供参考"
                ))

        return results

    def _get_median(self, values: List[float]) -> Optional[float]:
        """获取中位数"""
        if not values:
            return None
        sorted_values = sorted([v for v in values if v is not None and v > 0])
        if not sorted_values:
            return None
        n = len(sorted_values)
        if n % 2 == 1:
            return sorted_values[n // 2]
        else:
            return (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2


class TechValuationModel(BaseValuationModel):
    """科技行业估值模型"""

    def calculate(self, input_data: ValuationInput) -> List[ValuationResult]:
        """科技行业主要使用PE、PEG、PS估值法"""
        from .metrics import ValuationMetrics

        results = []
        fd = input_data.financial_data
        pd = input_data.price_data

        # PE估值法
        if fd.eps and fd.eps > 0 and pd.current_price:
            target_pe = self._get_median(input_data.historical_pe) if input_data.historical_pe else 25.0
            if target_pe:
                fair_value = ValuationMetrics.calculate_fair_value_from_pe(fd.eps, target_pe)
                if fair_value:
                    current_pe = ValuationMetrics.calculate_pe(pd.current_price, fd.eps)
                    deviation = (pd.current_price - fair_value) / fair_value * 100 if fair_value else None
                    results.append(ValuationResult(
                        method_name="PE估值法",
                        fair_value=round(fair_value, 2),
                        fair_value_low=round(fd.eps * target_pe * 0.75, 2),
                        fair_value_high=round(fd.eps * target_pe * 1.25, 2),
                        current_price=pd.current_price,
                        deviation_pct=round(deviation, 2) if deviation else None,
                        pe_ratio=round(current_pe, 2) if current_pe else None,
                        confidence="medium"
                    ))

        # PEG估值法
        if fd.eps and fd.eps > 0 and pd.current_price:
            # 假设增长率20%（科技行业）
            growth_rate = 20.0
            current_pe = ValuationMetrics.calculate_pe(pd.current_price, fd.eps)
            if current_pe:
                peg = ValuationMetrics.calculate_peg(current_pe, growth_rate)
                # PEG=1时为合理估值
                target_pe_from_peg = growth_rate
                fair_value = fd.eps * target_pe_from_peg
                deviation = (pd.current_price - fair_value) / fair_value * 100 if fair_value else None
                results.append(ValuationResult(
                    method_name="PEG估值法",
                    fair_value=round(fair_value, 2),
                    current_price=pd.current_price,
                    deviation_pct=round(deviation, 2) if deviation else None,
                    pe_ratio=round(current_pe, 2),
                    confidence="medium",
                    notes=f"假设增长率{growth_rate}%，当前PEG={round(peg, 2) if peg else 'N/A'}"
                ))

        # PS估值法（适用于高成长科技公司）
        if fd.revenue_per_share and fd.revenue_per_share > 0 and pd.current_price:
            target_ps = self._get_median(input_data.historical_ps) if input_data.historical_ps else 5.0
            if target_ps:
                fair_value = ValuationMetrics.calculate_fair_value_from_ps(fd.revenue_per_share, target_ps)
                if fair_value:
                    current_ps = ValuationMetrics.calculate_ps(pd.current_price, fd.revenue_per_share)
                    deviation = (pd.current_price - fair_value) / fair_value * 100 if fair_value else None
                    results.append(ValuationResult(
                        method_name="PS估值法",
                        fair_value=round(fair_value, 2),
                        fair_value_low=round(fd.revenue_per_share * target_ps * 0.6, 2),
                        fair_value_high=round(fd.revenue_per_share * target_ps * 1.4, 2),
                        current_price=pd.current_price,
                        deviation_pct=round(deviation, 2) if deviation else None,
                        ps_ratio=round(current_ps, 2) if current_ps else None,
                        confidence="medium"
                    ))

        return results

    def _get_median(self, values: List[float]) -> Optional[float]:
        """获取中位数"""
        if not values:
            return None
        sorted_values = sorted([v for v in values if v is not None and v > 0])
        if not sorted_values:
            return None
        n = len(sorted_values)
        if n % 2 == 1:
            return sorted_values[n // 2]
        else:
            return (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2


class REITsValuationModel(BaseValuationModel):
    """REITs/房地产估值模型"""

    def calculate(self, input_data: ValuationInput) -> List[ValuationResult]:
        """REITs主要使用P/FFO、NAV估值法"""
        from .metrics import ValuationMetrics

        results = []
        fd = input_data.financial_data
        pd = input_data.price_data

        # NAV估值法（净资产价值）
        if fd.shareholders_equity and pd.total_shares and pd.current_price:
            nav_per_share = fd.shareholders_equity / pd.total_shares
            # NAV通常有溢价或折价
            target_premium = 0.0  # 假设平价
            fair_value = nav_per_share * (1 + target_premium)
            deviation = (pd.current_price - fair_value) / fair_value * 100 if fair_value else None

            results.append(ValuationResult(
                method_name="NAV估值法",
                fair_value=round(fair_value, 2),
                fair_value_low=round(nav_per_share * 0.9, 2),
                fair_value_high=round(nav_per_share * 1.1, 2),
                current_price=pd.current_price,
                deviation_pct=round(deviation, 2) if deviation else None,
                confidence="high",
                notes="基于净资产价值"
            ))

        # PB估值法
        if fd.book_value_per_share and fd.book_value_per_share > 0 and pd.current_price:
            target_pb = 1.0  # REITs通常PB接近1
            fair_value = ValuationMetrics.calculate_fair_value_from_pb(fd.book_value_per_share, target_pb)
            if fair_value:
                current_pb = ValuationMetrics.calculate_pb(pd.current_price, fd.book_value_per_share)
                deviation = (pd.current_price - fair_value) / fair_value * 100 if fair_value else None
                results.append(ValuationResult(
                    method_name="PB估值法",
                    fair_value=round(fair_value, 2),
                    current_price=pd.current_price,
                    deviation_pct=round(deviation, 2) if deviation else None,
                    pb_ratio=round(current_pb, 2) if current_pb else None,
                    confidence="medium"
                ))

        return results


class ValuationCalculator:
    """
    估值计算器主类
    整合各行业估值模型，提供统一的估值计算接口
    """

    # 行业到估值模型的映射字典
    INDUSTRY_MODEL_MAP = {
        # 银行业
        "银行": BankValuationModel,
        "商业银行": BankValuationModel,
        "投资银行": BankValuationModel,

        # 科技行业
        "科技": TechValuationModel,
        "软件": TechValuationModel,
        "互联网": TechValuationModel,
        "半导体": TechValuationModel,
        "电子": TechValuationModel,
        "通信": TechValuationModel,

        # REITs/房地产
        "REITs": REITsValuationModel,
        "房地产": REITsValuationModel,
        "商业地产": REITsValuationModel,

        # 其他行业使用通用模型
        "default": GeneralValuationModel,
    }

    def __init__(self, db_manager: Any = None):
        """
        初始化估值计算器

        Args:
            db_manager: 数据库管理器实例，用于获取财务数据
        """
        self.db_manager = db_manager
        self._model_cache: Dict[str, BaseValuationModel] = {}
        logger.info("ValuationCalculator initialized")

    def _get_model(self, industry: str) -> BaseValuationModel:
        """
        获取行业对应的估值模型（带缓存）

        Args:
            industry: 行业名称

        Returns:
            估值模型实例
        """
        # 检查缓存
        if industry in self._model_cache:
            return self._model_cache[industry]

        # 获取模型类
        model_class = self.INDUSTRY_MODEL_MAP.get(industry, GeneralValuationModel)

        # 创建实例并缓存
        model = model_class()
        self._model_cache[industry] = model

        return model

    def calculate(
        self,
        stock_code: str,
        industry: Optional[str] = None,
        report_date: Optional[str] = None
    ) -> Dict[str, List[ValuationResult]]:
        """
        单股票估值计算

        Args:
            stock_code: 股票代码
            industry: 行业分类（如未提供则自动获取）
            report_date: 报告日期（如未提供则使用最新）

        Returns:
            Dict[模型名, List[ValuationResult]]
        """
        logger.info(f"开始估值计算: {stock_code}, 行业: {industry}, 报告期: {report_date}")

        # 1. 自动获取行业分类（如果未提供）
        if industry is None:
            industry = self._get_industry(stock_code)
            logger.info(f"自动获取行业分类: {industry}")

        # 2. 获取财务数据
        financial_data = self._get_financial_data(stock_code, report_date)
        if financial_data is None:
            logger.error(f"无法获取财务数据: {stock_code}")
            return {}

        # 3. 获取股价数据
        price_data = self._get_price_data(stock_code)
        if price_data is None:
            logger.error(f"无法获取股价数据: {stock_code}")
            return {}

        # 4. 获取历史估值数据
        historical_pe, historical_pb, historical_ps = self._get_historical_valuation(stock_code)

        # 5. 构建ValuationInput对象
        valuation_input = self._build_valuation_input(
            stock_code=stock_code,
            industry=industry,
            financial_data=financial_data,
            price_data=price_data,
            report_date=report_date,
            historical_pe=historical_pe,
            historical_pb=historical_pb,
            historical_ps=historical_ps
        )

        # 6. 获取对应行业模型并计算
        model = self._get_model(industry)
        results = model.calculate(valuation_input)

        logger.info(f"估值计算完成: {stock_code}, 共{len(results)}个结果")

        return {model.get_model_name(): results}

    def calculate_batch(
        self,
        stock_codes: List[str],
        industry_map: Optional[Dict[str, str]] = None
    ) -> Dict[str, Dict[str, List[ValuationResult]]]:
        """
        批量估值计算

        Args:
            stock_codes: 股票代码列表
            industry_map: 行业映射字典 {stock_code: industry}

        Returns:
            Dict[stock_code, Dict[模型名, List[ValuationResult]]]
        """
        results = {}
        industry_map = industry_map or {}

        logger.info(f"开始批量估值计算，共{len(stock_codes)}只股票")

        for stock_code in stock_codes:
            try:
                industry = industry_map.get(stock_code)
                stock_results = self.calculate(stock_code, industry=industry)
                results[stock_code] = stock_results
            except Exception as e:
                logger.error(f"估值计算失败 {stock_code}: {str(e)}")
                results[stock_code] = {}

        logger.info(f"批量估值计算完成")
        return results

    def _get_industry(self, stock_code: str) -> str:
        """
        从数据库获取股票的行业分类

        Args:
            stock_code: 股票代码

        Returns:
            行业名称
        """
        # 如果有数据库管理器，从数据库查询
        if self.db_manager:
            try:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT industry FROM stock_info WHERE code = ?",
                        (stock_code,)
                    )
                    row = cursor.fetchone()
                    if row:
                        return row['industry'] or "default"
            except Exception as e:
                logger.warning(f"从数据库获取行业分类失败: {e}")

        # 默认返回通用行业
        return "default"

    def _get_financial_data(
        self,
        stock_code: str,
        report_date: Optional[str] = None
    ) -> Optional[FinancialData]:
        """
        从数据库获取三张表数据

        Args:
            stock_code: 股票代码
            report_date: 报告日期

        Returns:
            FinancialData对象
        """
        if self.db_manager is None:
            # 模拟数据，用于测试
            logger.warning(f"无数据库连接，返回模拟数据: {stock_code}")
            return self._get_mock_financial_data(stock_code)

        try:
            # 构建查询条件
            date_condition = ""
            params = [stock_code]
            if report_date:
                date_condition = "AND report_date = ?"
                params.append(report_date)
            else:
                date_condition = "ORDER BY report_date DESC LIMIT 1"

            # 查询利润表
            income_sql = f"""
                SELECT revenue, net_profit, operating_profit
                FROM income_statement
                WHERE stock_code = ? {date_condition}
            """
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(income_sql, tuple(params))
                income_result = cursor.fetchall()

            # 查询资产负债表
            balance_sql = f"""
                SELECT total_assets, total_liabilities, shareholders_equity,
                       total_debt, cash_and_equivalents
                FROM balance_sheet
                WHERE stock_code = ? {date_condition}
            """
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(balance_sql, tuple(params))
                balance_result = cursor.fetchall()

            # 查询现金流量表
            cashflow_sql = f"""
                SELECT operating_cash_flow, free_cash_flow, capex
                FROM cashflow_statement
                WHERE stock_code = ? {date_condition}
            """
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(cashflow_sql, tuple(params))
                cashflow_result = cursor.fetchall()

            # 查询股本数据
            shares_sql = """
                SELECT total_shares FROM stock_info WHERE code = ?
            """
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(shares_sql, (stock_code,))
                shares_result = cursor.fetchall()

            # 构建FinancialData对象
            fd = FinancialData()

            if income_result and len(income_result) > 0:
                fd.revenue = income_result[0][0]
                fd.net_profit = income_result[0][1]
                fd.operating_profit = income_result[0][2]

            if balance_result and len(balance_result) > 0:
                fd.total_assets = balance_result[0][0]
                fd.total_liabilities = balance_result[0][1]
                fd.shareholders_equity = balance_result[0][2]
                fd.total_debt = balance_result[0][3]
                fd.cash_and_equivalents = balance_result[0][4]

            if cashflow_result and len(cashflow_result) > 0:
                fd.operating_cash_flow = cashflow_result[0][0]
                fd.free_cash_flow = cashflow_result[0][1]
                fd.capex = cashflow_result[0][2]

            # 计算每股指标
            total_shares = shares_result[0][0] if shares_result and len(shares_result) > 0 else None
            if total_shares and total_shares > 0:
                fd.eps = fd.net_profit / total_shares if fd.net_profit else None
                fd.book_value_per_share = fd.shareholders_equity / total_shares if fd.shareholders_equity else None
                fd.revenue_per_share = fd.revenue / total_shares if fd.revenue else None

            return fd

        except Exception as e:
            logger.error(f"获取财务数据失败: {e}")
            return None

    def _get_mock_financial_data(self, stock_code: str) -> FinancialData:
        """获取模拟财务数据（用于测试）"""
        # 根据股票代码生成不同的模拟数据
        code_num = sum(ord(c) for c in stock_code) % 100

        return FinancialData(
            revenue=1000000000 + code_num * 10000000,
            net_profit=100000000 + code_num * 1000000,
            operating_profit=120000000 + code_num * 1200000,
            ebitda=150000000 + code_num * 1500000,
            total_assets=2000000000 + code_num * 20000000,
            total_liabilities=800000000 + code_num * 8000000,
            shareholders_equity=1200000000 + code_num * 12000000,
            total_debt=500000000 + code_num * 5000000,
            cash_and_equivalents=300000000 + code_num * 3000000,
            operating_cash_flow=120000000 + code_num * 1200000,
            free_cash_flow=80000000 + code_num * 800000,
            capex=40000000 + code_num * 400000,
            eps=2.0 + code_num * 0.01,
            book_value_per_share=15.0 + code_num * 0.1,
            revenue_per_share=20.0 + code_num * 0.15
        )

    def _get_price_data(self, stock_code: str) -> Optional[PriceData]:
        """
        获取最新股价和股本

        Args:
            stock_code: 股票代码

        Returns:
            PriceData对象
        """
        if self.db_manager is None:
            # 模拟数据，用于测试
            logger.warning(f"无数据库连接，返回模拟价格数据: {stock_code}")
            return self._get_mock_price_data(stock_code)

        try:
            # 查询最新股价
            price_sql = """
                SELECT close_price, total_shares
                FROM stock_daily
                WHERE stock_code = ?
                ORDER BY trade_date DESC
                LIMIT 1
            """
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(price_sql, (stock_code,))
                result = cursor.fetchall()

            if result and len(result) > 0:
                current_price = result[0][0]
                total_shares = result[0][1]
                market_cap = current_price * total_shares if current_price and total_shares else None

                return PriceData(
                    current_price=current_price,
                    total_shares=total_shares,
                    market_cap=market_cap
                )

            return None

        except Exception as e:
            logger.error(f"获取股价数据失败: {e}")
            return None

    def _get_mock_price_data(self, stock_code: str) -> PriceData:
        """获取模拟价格数据（用于测试）"""
        code_num = sum(ord(c) for c in stock_code) % 100

        current_price = 30.0 + code_num * 0.5
        total_shares = 50000000 + code_num * 100000
        market_cap = current_price * total_shares

        return PriceData(
            current_price=current_price,
            total_shares=total_shares,
            market_cap=market_cap
        )

    def _get_historical_valuation(self, stock_code: str) -> tuple:
        """
        获取历史估值数据

        Args:
            stock_code: 股票代码

        Returns:
            (historical_pe, historical_pb, historical_ps)
        """
        if self.db_manager is None:
            # 返回模拟历史数据
            return (
                [10, 12, 15, 18, 20, 22, 25, 20, 18, 15],  # PE历史
                [1.0, 1.2, 1.5, 1.8, 2.0, 1.8, 1.5, 1.3, 1.2, 1.0],  # PB历史
                [1.5, 2.0, 2.5, 3.0, 3.5, 3.0, 2.5, 2.0, 1.8, 1.5]   # PS历史
            )

        try:
            sql = """
                SELECT pe_ratio, pb_ratio, ps_ratio
                FROM stock_valuation_history
                WHERE stock_code = ?
                ORDER BY report_date DESC
                LIMIT 20
            """
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (stock_code,))
                result = cursor.fetchall()

            if result:
                pe_list = [r[0] for r in result if r[0] is not None]
                pb_list = [r[1] for r in result if r[1] is not None]
                ps_list = [r[2] for r in result if r[2] is not None]
                return (pe_list, pb_list, ps_list)

            return ([], [], [])

        except Exception as e:
            logger.error(f"获取历史估值数据失败: {e}")
            return ([], [], [])

    def _build_valuation_input(
        self,
        stock_code: str,
        industry: str,
        financial_data: FinancialData,
        price_data: PriceData,
        report_date: Optional[str] = None,
        historical_pe: List[float] = None,
        historical_pb: List[float] = None,
        historical_ps: List[float] = None
    ) -> ValuationInput:
        """
        构建估值输入对象

        Args:
            stock_code: 股票代码
            industry: 行业分类
            financial_data: 财务数据
            price_data: 股价数据
            report_date: 报告日期
            historical_pe: 历史PE数据
            historical_pb: 历史PB数据
            historical_ps: 历史PS数据

        Returns:
            ValuationInput对象
        """
        return ValuationInput(
            stock_code=stock_code,
            industry=industry,
            financial_data=financial_data,
            price_data=price_data,
            report_date=report_date,
            historical_pe=historical_pe or [],
            historical_pb=historical_pb or [],
            historical_ps=historical_ps or []
        )
