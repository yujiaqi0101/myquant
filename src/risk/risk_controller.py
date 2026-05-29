"""
风控控制器
=========

在回测过程中实时监控和执行组合层面风控规则。

支持的风控类型：
1. 组合止损 - 组合整体回撤阈值
2. 仓位限制 - 单股/行业最大仓位
3. 波动率控制 - 基于波动率动态调整仓位

注：个股止损止盈已移至策略层，由策略通过 exit_checker 方法实现。
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class RiskAction(Enum):
    """风控触发后的操作"""
    NONE = "none"           # 不操作（仅记录）
    CLOSE = "close"         # 清仓
    REDUCE = "reduce"       # 减仓至限制
    HALT = "halt"           # 暂停交易


class RiskRuleType(Enum):
    """风控规则类型"""
    STOP_LOSS = "stop_loss"         # 个股止损
    TAKE_PROFIT = "take_profit"     # 个股止盈
    PORTFOLIO_STOP = "portfolio_stop"  # 组合止损
    POSITION_LIMIT = "position_limit"  # 仓位限制
    VOLATILITY_CONTROL = "volatility_control"  # 波动率控制


@dataclass
class RiskRule:
    """风控规则配置"""
    rule_type: RiskRuleType
    threshold: float                # 阈值（如止损比例0.07表示-7%）
    action: RiskAction              # 触发后的操作
    params: Dict[str, Any] = field(default_factory=dict)  # 额外参数
    enabled: bool = True            # 是否启用


@dataclass
class RiskEvent:
    """风控事件记录"""
    date: str
    rule_type: RiskRuleType
    stock_code: Optional[str]       # 个股相关则为股票代码
    trigger_value: float            # 触发时的值
    threshold: float                # 阈值
    action: RiskAction              # 执行的操作
    position_before: float          # 操作前仓位
    position_after: float           # 操作后仓位
    reason: str                     # 触发原因


class RiskController:
    """
    风控控制器 - 组合层面风控
    
    在回测过程中实时监控组合风险指标，触发风控规则时执行相应操作。
    
    注：个股止损止盈已移至策略层，由策略通过 exit_checker 方法实现。
    """
    
    def __init__(
        self,
        portfolio_stop: float = 0.10,      # 组合止损比例（-10%）
        max_position_per_stock: float = 0.10,  # 单股最大仓位（10%）
        max_position_per_industry: float = 0.30,  # 行业最大仓位（30%）
        volatility_lookback: int = 20,     # 波动率计算回看天数
        volatility_target: Optional[float] = None,  # 目标波动率
        risk_action: str = "close",        # 默认操作：close/reduce/halt
        enable_portfolio_stop: bool = True,
        enable_position_limit: bool = True,
    ):
        """
        初始化风控控制器
        
        Parameters
        ----------
        portfolio_stop : float
            组合止损比例，默认0.10（-10%）
        max_position_per_stock : float
            单只股票最大仓位，默认0.10（10%）
        max_position_per_industry : float
            单个行业最大仓位，默认0.30（30%）
        volatility_lookback : int
            波动率计算回看天数，默认20天
        volatility_target : float, optional
            目标年化波动率，默认None（不启用）
        risk_action : str
            风控触发后的默认操作：'close'/'reduce'/'halt'
        """
        self.rules = {}
        
        # 组合止损
        if enable_portfolio_stop and portfolio_stop > 0:
            self.rules[RiskRuleType.PORTFOLIO_STOP] = RiskRule(
                rule_type=RiskRuleType.PORTFOLIO_STOP,
                threshold=-portfolio_stop,
                action=RiskAction(risk_action),
                enabled=True
            )
        
        # 仓位限制
        if enable_position_limit:
            self.rules[RiskRuleType.POSITION_LIMIT] = RiskRule(
                rule_type=RiskRuleType.POSITION_LIMIT,
                threshold=max_position_per_stock,
                action=RiskAction.REDUCE,
                params={
                    'max_per_stock': max_position_per_stock,
                    'max_per_industry': max_position_per_industry,
                },
                enabled=True
            )
        
        # 波动率控制
        if volatility_target is not None and volatility_target > 0:
            self.rules[RiskRuleType.VOLATILITY_CONTROL] = RiskRule(
                rule_type=RiskRuleType.VOLATILITY_CONTROL,
                threshold=volatility_target,
                action=RiskAction.REDUCE,
                params={'lookback': volatility_lookback},
                enabled=True
            )
        
        # 状态跟踪
        self.events: List[RiskEvent] = []
        self.portfolio_peak_value = 0.0   # 组合峰值
        self.entry_prices: Dict[str, float] = {}  # 股票买入成本
        self.halted_stocks: set = set()   # 被暂停交易的股票
        
    def record_entry(self, date: str, stock_code: str, price: float, 
                     position: float = 0.0):
        """
        记录股票买入
        
        Parameters
        ----------
        date : str
            买入日期
        stock_code : str
            股票代码
        price : float
            买入价格
        position : float
            买入仓位
        """
        if stock_code not in self.entry_prices:
            self.entry_prices[stock_code] = {'price': price, 'date': date}
        else:
            # 加权平均成本
            old_price = self.entry_prices[stock_code]['price']
            self.entry_prices[stock_code]['price'] = (old_price + price) / 2
            
        # 从暂停列表中移除（新买入）
        self.halted_stocks.discard(stock_code)
        
    def record_exit(self, stock_code: str):
        """
        记录股票卖出/清仓
        
        Parameters
        ----------
        stock_code : str
            股票代码
        """
        if stock_code in self.entry_prices:
            del self.entry_prices[stock_code]
        self.halted_stocks.discard(stock_code)
        
    def check_stock_risk(
        self,
        date: str,
        stock_code: str,
        current_price: float,
        current_position: float,
        industry: Optional[str] = None
    ) -> Tuple[RiskAction, float, str]:
        """
        [已废弃] 个股风控检查已移至策略层

        请使用策略的 exit_checker 方法替代。
        保留此方法用于向后兼容，直接返回 NONE。
        
        Parameters
        ----------
        date : str
            当前日期
        stock_code : str
            股票代码
        current_price : float
            当前价格
        current_position : float
            当前仓位
        industry : str, optional
            所属行业
            
        Returns
        -------
        Tuple[RiskAction, float, str]
            (操作类型, 目标仓位, 原因)
        """
        return RiskAction.NONE, current_position, ""
    
    def check_portfolio_risk(
        self,
        date: str,
        portfolio_value: float,
        total_position: float
    ) -> Tuple[RiskAction, float, str]:
        """
        检查组合层面风险
        
        Parameters
        ----------
        date : str
            当前日期
        portfolio_value : float
            当前组合净值
        total_position : float
            当前总仓位
            
        Returns
        -------
        Tuple[RiskAction, float, str]
            (操作类型, 目标仓位比例, 原因)
        """
        # 更新峰值
        if portfolio_value > self.portfolio_peak_value:
            self.portfolio_peak_value = portfolio_value
        
        # 计算回撤
        drawdown = (self.portfolio_peak_value - portfolio_value) / self.portfolio_peak_value if self.portfolio_peak_value > 0 else 0
        
        # 检查组合止损
        if RiskRuleType.PORTFOLIO_STOP in self.rules:
            rule = self.rules[RiskRuleType.PORTFOLIO_STOP]
            if rule.enabled and -drawdown <= rule.threshold:  # threshold是负数
                event = RiskEvent(
                    date=date,
                    rule_type=RiskRuleType.PORTFOLIO_STOP,
                    stock_code=None,
                    trigger_value=-drawdown,
                    threshold=rule.threshold,
                    action=rule.action,
                    position_before=total_position,
                    position_after=0.0 if rule.action == RiskAction.CLOSE else total_position * 0.5,
                    reason=f"组合止损触发：回撤 {-drawdown:.2%} <= 阈值 {rule.threshold:.2%}"
                )
                self.events.append(event)
                
                logger.warning(f"[{date}] 组合止损触发: 回撤 {-drawdown:.2%}")
                
                if rule.action == RiskAction.CLOSE:
                    return RiskAction.CLOSE, 0.0, event.reason
                elif rule.action == RiskAction.REDUCE:
                    return RiskAction.REDUCE, total_position * 0.5, event.reason
                else:
                    return RiskAction.HALT, total_position, event.reason
        
        return RiskAction.NONE, total_position, ""
    
    def check_position_limits(
        self,
        date: str,
        positions: Dict[str, float],
        industry_mapping: Optional[Dict[str, str]] = None
    ) -> Dict[str, Tuple[RiskAction, float, str]]:
        """
        检查仓位限制
        
        Parameters
        ----------
        date : str
            当前日期
        positions : Dict[str, float]
            当前各股票仓位
        industry_mapping : Dict[str, str], optional
            股票-行业映射
            
        Returns
        -------
        Dict[str, Tuple[RiskAction, float, str]]
            各股票的风控结果
        """
        results = {}
        
        if RiskRuleType.POSITION_LIMIT not in self.rules:
            return results
        
        rule = self.rules[RiskRuleType.POSITION_LIMIT]
        if not rule.enabled:
            return results
        
        max_per_stock = rule.params.get('max_per_stock', 0.10)
        max_per_industry = rule.params.get('max_per_industry', 0.30)
        
        # 检查个股仓位
        for stock_code, position in positions.items():
            if position > max_per_stock:
                event = RiskEvent(
                    date=date,
                    rule_type=RiskRuleType.POSITION_LIMIT,
                    stock_code=stock_code,
                    trigger_value=position,
                    threshold=max_per_stock,
                    action=RiskAction.REDUCE,
                    position_before=position,
                    position_after=max_per_stock,
                    reason=f"个股仓位超限：{position:.2%} > 限制 {max_per_stock:.2%}"
                )
                self.events.append(event)
                results[stock_code] = (RiskAction.REDUCE, max_per_stock, event.reason)
        
        # 检查行业仓位
        if industry_mapping:
            industry_positions = {}
            for stock_code, position in positions.items():
                industry = industry_mapping.get(stock_code, 'Unknown')
                industry_positions[industry] = industry_positions.get(industry, 0) + position
            
            for industry, position in industry_positions.items():
                if position > max_per_industry:
                    logger.warning(f"[{date}] 行业 {industry} 仓位超限: {position:.2%} > {max_per_industry:.2%}")
        
        return results
    
    def get_risk_report(self) -> Dict:
        """
        获取风控报告
        
        Returns
        -------
        Dict
            风控统计报告
        """
        if not self.events:
            return {
                'total_events': 0,
                'events_by_type': {},
                'events_by_action': {},
            }
        
        events_by_type = {}
        events_by_action = {}
        
        for event in self.events:
            type_name = event.rule_type.value
            action_name = event.action.value
            
            events_by_type[type_name] = events_by_type.get(type_name, 0) + 1
            events_by_action[action_name] = events_by_action.get(action_name, 0) + 1
        
        return {
            'total_events': len(self.events),
            'events_by_type': events_by_type,
            'events_by_action': events_by_action,
            'halted_stocks': list(self.halted_stocks),
            'recent_events': [
                {
                    'date': e.date,
                    'type': e.rule_type.value,
                    'stock': e.stock_code,
                    'trigger': e.trigger_value,
                    'action': e.action.value,
                    'reason': e.reason,
                }
                for e in self.events[-10:]  # 最近10条
            ],
        }
    
    def reset(self):
        """重置风控状态（用于新一轮回测）"""
        self.events = []
        self.portfolio_peak_value = 0.0
        self.entry_prices = {}
        self.halted_stocks = set()
