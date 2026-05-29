"""
执行日志记录器
=============

自动记录因子评估和回测结果到数据库，并更新最佳记录。
"""

import json
import logging
from typing import Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class ExecutionLogger:
    """
    执行日志记录器

    封装数据库操作，自动记录因子评估和回测结果，并更新最佳记录。
    """

    def __init__(self, db_manager):
        """
        Parameters
        ----------
        db_manager : DatabaseManager
            数据库管理器实例
        """
        self.db = db_manager

    def log_factor_evaluation(
        self,
        factor_name: str,
        metrics: Dict,
        execution_context: Optional[Dict] = None
    ) -> int:
        """
        记录因子评估结果

        Parameters
        ----------
        factor_name : str
            因子名称
        metrics : Dict
            评估指标，如 IC_mean, IC_std, IC_IR 等
        execution_context : Dict, optional
            执行上下文（日期范围、股票数等）

        Returns
        -------
        int
            执行日志ID
        """
        context = execution_context or {}

        log_id = self.db.log_execution(
            execution_type='factor_evaluation',
            factor_name=factor_name,
            factor_category=context.get('factor_category'),
            start_date=context.get('start_date'),
            end_date=context.get('end_date'),
            n_stocks=context.get('n_stocks'),
            n_days=context.get('n_days'),
            ic_mean=metrics.get('IC_mean'),
            ic_std=metrics.get('IC_std'),
            ir=metrics.get('IC_IR'),
            status='success',
            details={
                'ic_positive_ratio': metrics.get('IC_positive_ratio'),
                'layer_spread': metrics.get('layer_spread'),
                'turnover': metrics.get('turnover'),
            }
        )

        # 更新最佳记录
        self._update_best_records('factor', factor_name, metrics, log_id)

        return log_id

    def log_backtest_result(
        self,
        factor_name: str,
        performance: Dict,
        execution_context: Optional[Dict] = None
    ) -> int:
        """
        记录回测结果

        Parameters
        ----------
        factor_name : str
            因子名称
        performance : Dict
            绩效指标
        execution_context : Dict, optional
            执行上下文

        Returns
        -------
        int
            执行日志ID
        """
        context = execution_context or {}

        log_id = self.db.log_execution(
            execution_type='backtest',
            factor_name=factor_name,
            factor_category=context.get('factor_category'),
            start_date=context.get('start_date'),
            end_date=context.get('end_date'),
            n_stocks=context.get('n_stocks'),
            n_days=context.get('n_days'),
            n_positions=context.get('n_positions'),
            rebalance_freq=context.get('rebalance_freq'),
            initial_capital=context.get('initial_capital'),
            sharpe=performance.get('sharpe_ratio'),
            max_drawdown=performance.get('max_drawdown'),
            total_return=performance.get('total_return'),
            annual_return=performance.get('annual_return'),
            annual_volatility=performance.get('annual_volatility'),
            win_rate=performance.get('win_rate'),
            status='success',
            details={
                'calmar_ratio': performance.get('calmar_ratio'),
                'profit_loss_ratio': performance.get('profit_loss_ratio'),
                'n_trades': performance.get('n_trades'),
            }
        )

        # 更新最佳记录
        self._update_best_records('backtest', factor_name, performance, log_id)

        return log_id

    def log_error(
        self,
        execution_type: str,
        factor_name: Optional[str] = None,
        error_message: Optional[str] = None,
        execution_context: Optional[Dict] = None
    ) -> int:
        """记录执行错误"""
        context = execution_context or {}

        return self.db.log_execution(
            execution_type=execution_type,
            factor_name=factor_name,
            factor_category=context.get('factor_category'),
            start_date=context.get('start_date'),
            end_date=context.get('end_date'),
            status='failed',
            details={'error': error_message}
        )

    def _update_best_records(self, category: str, factor_name: str, metrics: Dict, log_id: int):
        """更新最佳记录"""
        # IC均值
        ic = metrics.get('IC_mean') or metrics.get('ic_mean')
        if ic is not None and not (isinstance(ic, float) and (ic != ic)):
            self.db.update_best_record(category, f'{factor_name}_IC', ic, log_id)

        # IR
        ir = metrics.get('IC_IR') or metrics.get('ir')
        if ir is not None and not (isinstance(ir, float) and (ir != ir)):
            self.db.update_best_record(category, f'{factor_name}_IR', ir, log_id)

        # 夏普比率
        sharpe = metrics.get('sharpe_ratio') or metrics.get('sharpe')
        if sharpe is not None and not (isinstance(sharpe, float) and (sharpe != sharpe)):
            self.db.update_best_record(category, 'Sharpe', sharpe, log_id)

        # 最大回撤
        max_dd = metrics.get('max_drawdown')
        if max_dd is not None and not (isinstance(max_dd, float) and (max_dd != max_dd)):
            self.db.update_best_record(category, 'MaxDrawdown', max_dd, log_id)

        # 总收益
        total_ret = metrics.get('total_return')
        if total_ret is not None and not (isinstance(total_ret, float) and (total_ret != total_ret)):
            self.db.update_best_record(category, 'TotalReturn', total_ret, log_id)

    def get_best_records(self, category: Optional[str] = None) -> pd.DataFrame:
        """查询最佳记录"""
        return self.db.get_best_records(category)

    def get_execution_history(
        self,
        execution_type: Optional[str] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """查询执行历史"""
        return self.db.get_execution_logs(execution_type=execution_type, limit=limit)
