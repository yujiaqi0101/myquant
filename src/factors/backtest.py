"""
回测模块
========

提供因子回测和策略评估功能。
"""

from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np


class Backtester:
    """
    回测器
    
    提供因子回测和策略评估功能。
    """
    
    def __init__(
        self,
        initial_capital: float = 1000000,
        commission_rate: float = 0.0003,
        slippage: float = 0.0001,
        position_limit: float = 0.1,
        execution_logger=None
    ):
        """
        初始化回测器
        
        Parameters
        ----------
        initial_capital : float
            初始资金
        commission_rate : float
            佣金费率
        slippage : float
            滑点
        position_limit : float
            单只股票最大仓位比例
        execution_logger : ExecutionLogger, optional
            执行日志记录器
        """
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.position_limit = position_limit
        self.execution_logger = execution_logger
        
        self._price_data = None
        self._trade_records = []
    
    def load_data(self, price_data: pd.DataFrame):
        """
        加载价格数据
        
        Parameters
        ----------
        price_data : pd.DataFrame
            价格数据
        """
        self._price_data = price_data

    @staticmethod
    def build_stock_filter(
        stock_info: pd.DataFrame,
        trade_date,
        min_list_days: int = 60
    ) -> set:
        """
        构建可选股票池（排除ST、新股）

        Parameters
        ----------
        stock_info : pd.DataFrame
            包含 stock_code, stock_name, list_date 列
        trade_date : datetime-like
            当前交易日期
        min_list_days : int
            最少上市天数

        Returns
        -------
        set
            可交易股票代码集合
        """
        trade_dt = pd.Timestamp(trade_date)
        valid_codes = set()

        for _, row in stock_info.iterrows():
            code = row['stock_code']
            name = str(row.get('stock_name', ''))

            # 排除ST
            if 'ST' in name.upper():
                continue

            # 排除新股
            list_date = row.get('list_date')
            if pd.notna(list_date) and list_date:
                try:
                    list_dt = pd.Timestamp(list_date)
                    if (trade_dt - list_dt).days < min_list_days:
                        continue
                except Exception:
                    pass

            valid_codes.add(code)

        return valid_codes

    @staticmethod
    def filter_daily(
        daily_data: pd.DataFrame,
        suspend: bool = True,
        limit_up: bool = True,
        limit_down: bool = True,
        zero_volume: bool = True,
    ) -> pd.DataFrame:
        """
        日频过滤：停牌、涨跌停、零成交量

        Parameters
        ----------
        daily_data : pd.DataFrame
            当日截面数据，需包含 close, pre_close, suspend_flag, volume 列
        suspend : bool
            是否过滤停牌
        limit_up : bool
            是否过滤涨停
        limit_down : bool
            是否过滤跌停
        zero_volume : bool
            是否过滤零成交量

        Returns
        -------
        pd.DataFrame
            过滤后的数据
        """
        mask = pd.Series(True, index=daily_data.index)

        if suspend and 'suspend_flag' in daily_data.columns:
            mask &= (daily_data['suspend_flag'] == 0)

        if (limit_up or limit_down) and 'pre_close' in daily_data.columns:
            pre_close = daily_data['pre_close']
            # pre_close 为空时不过滤
            valid_pre = pre_close.notna() & (pre_close > 0)
            if limit_up:
                mask &= ~((daily_data['close'] >= pre_close * 1.095) & valid_pre)
            if limit_down:
                mask &= ~((daily_data['close'] <= pre_close * 0.905) & valid_pre)

        if zero_volume and 'volume' in daily_data.columns:
            mask &= (daily_data['volume'] > 0)

        return daily_data[mask]
    
    def run_backtest(
        self,
        factor: pd.Series,
        n_stocks: int = 50,
        rebalance_freq: int = 5,
        long_short: bool = False,
        filter_func=None
    ) -> Dict:
        """
        运行回测
        
        Parameters
        ----------
        factor : pd.Series
            因子值序列
        n_stocks : int
            持仓股票数量
        rebalance_freq : int
            调仓频率（每N个交易日调仓一次）
        long_short : bool
            是否多空策略
        filter_func : callable, optional
            选股过滤回调 filter_func(daily_factor, date, daily_price) -> filtered_factor
        
        Returns
        -------
        Dict
            回测结果
        """
        if self._price_data is None:
            raise ValueError("请先使用 load_data() 加载价格数据")
        
        # 重置状态，避免多次调用累积
        self._trade_records = []
        self._portfolio_df = None
        self._last_performance = None
        
        # 获取交易日列表
        if isinstance(factor.index, pd.MultiIndex):
            trade_dates = factor.index.get_level_values('trade_date').unique().sort_values()
        else:
            trade_dates = factor.index.sort_values()
        
        # 初始化
        capital = self.initial_capital
        positions = {}  # 股票代码 -> 数量
        portfolio_values = []
        
        for i, date in enumerate(trade_dates):
            # 获取当日因子值
            try:
                if isinstance(factor.index, pd.MultiIndex):
                    daily_factor = factor.xs(date, level='trade_date')
                else:
                    daily_factor = factor.loc[date]
            except KeyError:
                continue
            
            # 获取当日价格
            try:
                if isinstance(self._price_data.index, pd.MultiIndex):
                    daily_price = self._price_data.xs(date, level='trade_date')
                else:
                    daily_price = self._price_data.loc[date]
            except KeyError:
                continue
            
            # 计算当前持仓市值
            position_value = 0
            for stock_code, quantity in positions.items():
                try:
                    if isinstance(daily_price.index, pd.MultiIndex):
                        price = daily_price.xs(stock_code, level='stock_code')['close']
                    else:
                        price = daily_price[daily_price['stock_code'] == stock_code]['close'].iloc[0]
                    position_value += price * quantity
                except Exception:
                    pass
            
            total_value = capital + position_value
            portfolio_values.append({
                'date': date,
                'value': total_value,
                'capital': capital,
                'position_value': position_value,
            })
            
            # 调仓日
            if i % rebalance_freq == 0:
                # 应用选股过滤回调
                if filter_func is not None:
                    try:
                        daily_price = self._price_data.xs(date, level='trade_date') \
                            if isinstance(self._price_data.index, pd.MultiIndex) else self._price_data.loc[date]
                        daily_factor = filter_func(daily_factor, date, daily_price)
                    except Exception as e:
                        logger.debug(f"选股过滤回调异常: {e}")

                # 选股
                sorted_factor = daily_factor.sort_values(ascending=False)
                
                if long_short:
                    # 多空策略
                    long_stocks = sorted_factor.head(n_stocks // 2).index.tolist()
                    short_stocks = sorted_factor.tail(n_stocks // 2).index.tolist()
                else:
                    # 多头策略
                    long_stocks = sorted_factor.head(n_stocks).index.tolist()
                    short_stocks = []
                
                # 清仓
                for stock_code in list(positions.keys()):
                    try:
                        if isinstance(daily_price.index, pd.MultiIndex):
                            price = daily_price.xs(stock_code, level='stock_code')['close']
                        else:
                            price = daily_price[daily_price['stock_code'] == stock_code]['close'].iloc[0]
                        
                        quantity = positions[stock_code]
                        trade_value = price * quantity
                        
                        # 计算交易成本
                        commission = abs(trade_value) * self.commission_rate
                        slippage_cost = abs(trade_value) * self.slippage
                        
                        capital += trade_value - commission - slippage_cost
                        
                        self._trade_records.append({
                            'date': date,
                            'stock_code': stock_code,
                            'action': 'sell',
                            'price': price,
                            'quantity': quantity,
                            'value': trade_value,
                        })
                        
                        del positions[stock_code]
                    except Exception:
                        pass
                
                # 开仓
                if long_stocks:
                    available_capital = capital * (1 - self.position_limit * 0.1)  # 保留部分现金
                    capital_per_stock = available_capital / len(long_stocks)
                    
                    for stock_code in long_stocks:
                        try:
                            if isinstance(daily_price.index, pd.MultiIndex):
                                price = daily_price.xs(stock_code, level='stock_code')['close']
                            else:
                                price = daily_price[daily_price['stock_code'] == stock_code]['close'].iloc[0]
                            
                            quantity = int(capital_per_stock / price / 100) * 100  # 整手
                            
                            if quantity > 0:
                                trade_value = price * quantity
                                commission = trade_value * self.commission_rate
                                slippage_cost = trade_value * self.slippage
                                
                                capital -= trade_value + commission + slippage_cost
                                positions[stock_code] = quantity
                                
                                self._trade_records.append({
                                    'date': date,
                                    'stock_code': stock_code,
                                    'action': 'buy',
                                    'price': price,
                                    'quantity': quantity,
                                    'value': trade_value,
                                })
                        except Exception:
                            pass
        
        # 计算绩效
        portfolio_df = pd.DataFrame(portfolio_values)
        performance = self._calculate_performance(portfolio_df)
        
        # 保存结果到实例变量，供 generate_report 使用
        self._portfolio_df = portfolio_df
        self._last_performance = performance

        # 记录到执行日志
        if self.execution_logger and performance:
            try:
                self.execution_logger.log_backtest_result(
                    factor_name='unknown',
                    performance=performance,
                    execution_context={
                        'n_positions': n_stocks,
                        'rebalance_freq': rebalance_freq,
                        'initial_capital': self.initial_capital,
                    }
                )
            except Exception:
                pass

        return {
            'portfolio_values': portfolio_df,
            'performance': performance,
            'trade_records': self._trade_records,
        }
    
    def _calculate_performance(self, portfolio_df: pd.DataFrame) -> Dict:
        """计算绩效指标"""
        if len(portfolio_df) == 0:
            return {}
        
        values = portfolio_df['value'].values
        returns = np.diff(values) / values[:-1]
        
        # 总收益
        total_return = values[-1] / values[0] - 1
        
        # 年化收益
        n_days = len(values)
        annual_return = (1 + total_return) ** (252 / n_days) - 1
        
        # 年化波动率
        annual_volatility = np.std(returns) * np.sqrt(252)
        
        # 夏普比率
        risk_free_rate = 0.03  # 假设无风险利率3%
        sharpe_ratio = (annual_return - risk_free_rate) / annual_volatility if annual_volatility > 0 else 0
        
        # 最大回撤
        max_drawdown = self._calculate_max_drawdown(values)
        
        # 卡玛比率
        calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0
        
        # 胜率
        win_rate = np.sum(returns > 0) / len(returns) if len(returns) > 0 else 0
        
        # 盈亏比
        positive_returns = returns[returns > 0]
        negative_returns = returns[returns < 0]
        profit_loss_ratio = (
            np.mean(positive_returns) / abs(np.mean(negative_returns))
            if len(negative_returns) > 0 and len(positive_returns) > 0
            else 0
        )
        
        return {
            'total_return': total_return,
            'annual_return': annual_return,
            'annual_volatility': annual_volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'calmar_ratio': calmar_ratio,
            'win_rate': win_rate,
            'profit_loss_ratio': profit_loss_ratio,
            'n_trades': len(self._trade_records),
        }
    
    def _calculate_max_drawdown(self, values: np.ndarray) -> float:
        """计算最大回撤"""
        peak = values[0]
        max_dd = 0
        
        for value in values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
        
        return -max_dd
    
    def get_trade_statistics(self) -> Dict:
        """获取交易统计"""
        if not self._trade_records:
            return {}
        
        trades_df = pd.DataFrame(self._trade_records)
        
        buy_trades = trades_df[trades_df['action'] == 'buy']
        sell_trades = trades_df[trades_df['action'] == 'sell']
        
        return {
            'total_trades': len(trades_df),
            'buy_trades': len(buy_trades),
            'sell_trades': len(sell_trades),
            'total_volume': trades_df['value'].sum(),
            'avg_trade_size': trades_df['value'].mean(),
        }
    
    def generate_report(
        self,
        output_path: str = "backtest_report.html",
        title: str = "回测报告"
    ) -> str:
        """
        生成回测 HTML 报告
        
        使用 ECharts 生成交互式图表，包含净值曲线、回撤曲线、
        绩效指标汇总表、交易记录明细等。
        
        Parameters
        ----------
        output_path : str
            输出文件路径，默认为当前目录下的 backtest_report.html
        title : str
            报告标题
        
        Returns
        -------
        str
            HTML 文件路径
        
        Examples
        --------
        >>> backtester = Backtester()
        >>> backtester.load_data(price_data)
        >>> result = backtester.run_backtest(factor)
        >>> report_path = backtester.generate_report("my_report.html", "我的策略回测")
        >>> print(f"报告已生成: {report_path}")
        """
        from .report_generator import BacktestReportGenerator
        
        # 构建回测结果
        result = {
            'portfolio_values': getattr(self, '_portfolio_df', pd.DataFrame()),
            'performance': getattr(self, '_last_performance', {}),
            'trade_records': self._trade_records,
        }
        
        generator = BacktestReportGenerator(result)
        return generator.generate_html(output_path, title)
