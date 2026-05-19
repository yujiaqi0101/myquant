"""
市场阶段识别模块
===============

识别A股市场的不同阶段，包括：
- 牛熊判断
- 指数与个股关系
- 板块轮动
- 市场情绪
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
import pandas as pd
import numpy as np


class MarketStageDetector:
    """
    市场阶段识别器
    
    综合多维度判断市场所处的阶段。
    """
    
    # 市场趋势状态
    TREND_BULL = 'bull'              # 牛市
    TREND_BEAR = 'bear'              # 熊市
    TREND_NEUTRAL = 'neutral'        # 震荡
    TREND_BULL_PULLBACK = 'bull_pullback'  # 牛市回调
    TREND_BEAR_RALLY = 'bear_rally'  # 熊市反弹
    
    # 指数个股关系
    DIVERGENCE_INDEX_UP_STOCKS_UP = 'index_up_stocks_up'        # 指数涨个股涨
    DIVERGENCE_INDEX_UP_STOCKS_DOWN = 'index_up_stocks_down'    # 指数涨个股不涨
    DIVERGENCE_INDEX_DOWN_STOCKS_DOWN = 'index_down_stocks_down'  # 指数跌个股跌
    DIVERGENCE_INDEX_DOWN_STOCKS_UP = 'index_down_stocks_up'    # 指数跌个股不跌
    DIVERGENCE_NEUTRAL = 'neutral'  # 震荡
    
    def __init__(
        self,
        ma_long: int = 250,
        ma_short: int = 20,
        divergence_threshold: float = 0.3,
        sentiment_extreme_high: float = 0.8,
        sentiment_extreme_low: float = 0.2
    ):
        """
        初始化市场阶段识别器
        
        Parameters
        ----------
        ma_long : int
            长期均线周期（用于牛熊判断）
        ma_short : int
            短期均线周期
        divergence_threshold : float
            背离度阈值
        sentiment_extreme_high : float
            情绪过热阈值
        sentiment_extreme_low : float
            情绪过冷阈值
        """
        self.ma_long = ma_long
        self.ma_short = ma_short
        self.divergence_threshold = divergence_threshold
        self.sentiment_extreme_high = sentiment_extreme_high
        self.sentiment_extreme_low = sentiment_extreme_low
    
    def identify(
        self,
        index_data: pd.DataFrame,
        stock_data: pd.DataFrame,
        sector_data: Optional[pd.DataFrame] = None
    ) -> Dict:
        """
        综合识别市场阶段
        
        Parameters
        ----------
        index_data : pd.DataFrame
            指数数据，包含 close, volume 等字段
        stock_data : pd.DataFrame
            个股数据，包含 close, volume 等
        sector_data : pd.DataFrame, optional
            板块数据
        
        Returns
        -------
        Dict
            市场阶段识别结果
        """
        result = {
            'timestamp': datetime.now(),
            'trend': None,
            'divergence': None,
            'sector_rotation': None,
            'sentiment': None,
            'leading_sector': None,
            'leader_stock': None,
            'summary': None,
        }
        
        # 1. 牛熊判断
        result['trend'] = self._classify_trend(index_data)
        
        # 2. 指数个股关系
        result['divergence'] = self._calculate_divergence(index_data, stock_data)
        
        # 3. 板块轮动
        if sector_data is not None:
            result['sector_rotation'] = self._identify_sector_rotation(sector_data)
            result['leading_sector'] = self._get_leading_sector(sector_data)
        
        # 4. 市场情绪
        result['sentiment'] = self._calculate_sentiment(stock_data)
        
        # 5. 龙头股识别
        result['leader_stock'] = self._identify_leader_stock(stock_data)
        
        # 6. 生成总结
        result['summary'] = self._generate_summary(result)
        
        return result
    
    def _classify_trend(self, index_data: pd.DataFrame) -> Dict:
        """
        判断市场趋势（牛熊）
        
        Parameters
        ----------
        index_data : pd.DataFrame
            指数数据
        
        Returns
        -------
        Dict
            趋势判断结果
        """
        if isinstance(index_data.index, pd.MultiIndex):
            # 如果是MultiIndex，取第一个指数
            index_code = index_data.index.get_level_values('index_code')[0]
            close = index_data.xs(index_code, level='index_code')['close']
        else:
            close = index_data['close']
        
        # 计算均线
        ma_long = close.rolling(self.ma_long).mean()
        ma_short = close.rolling(self.ma_short).mean()
        
        # 当前值
        current_close = close.iloc[-1]
        current_ma_long = ma_long.iloc[-1]
        current_ma_short = ma_short.iloc[-1]
        
        # 前一日均线方向
        ma_short_direction = ma_short.iloc[-1] > ma_short.iloc[-2]
        
        # 判断趋势
        if current_close > current_ma_long:
            if ma_short_direction:
                trend = self.TREND_BULL
            else:
                trend = self.TREND_BULL_PULLBACK
        elif current_close < current_ma_long:
            if not ma_short_direction:
                trend = self.TREND_BEAR
            else:
                trend = self.TREND_BEAR_RALLY
        else:
            trend = self.TREND_NEUTRAL
        
        return {
            'trend': trend,
            'trend_name': self._get_trend_name(trend),
            'close': current_close,
            'ma_long': current_ma_long,
            'ma_short': current_ma_short,
            'ma_long_distance': (current_close / current_ma_long - 1),
            'ma_short_distance': (current_close / current_ma_short - 1),
        }
    
    def _get_trend_name(self, trend: str) -> str:
        """获取趋势中文名称"""
        trend_names = {
            self.TREND_BULL: '牛市',
            self.TREND_BEAR: '熊市',
            self.TREND_NEUTRAL: '震荡',
            self.TREND_BULL_PULLBACK: '牛市回调',
            self.TREND_BEAR_RALLY: '熊市反弹',
        }
        return trend_names.get(trend, '未知')
    
    def _calculate_divergence(
        self,
        index_data: pd.DataFrame,
        stock_data: pd.DataFrame
    ) -> Dict:
        """
        计算指数与个股的背离度
        
        Parameters
        ----------
        index_data : pd.DataFrame
            指数数据
        stock_data : pd.DataFrame
            个股数据
        
        Returns
        -------
        Dict
            背离度计算结果
        """
        # 获取指数收益
        if isinstance(index_data.index, pd.MultiIndex):
            index_code = index_data.index.get_level_values('index_code')[0]
            index_close = index_data.xs(index_code, level='index_code')['close']
        else:
            index_close = index_data['close']
        
        index_return = index_close.pct_change().iloc[-1]
        
        # 计算个股涨跌情况
        if isinstance(stock_data.index, pd.MultiIndex):
            # 按日期分组计算涨跌股票数
            last_date = stock_data.index.get_level_values('trade_date')[-1]
            prev_date = stock_data.index.get_level_values('trade_date')[-2]
            
            last_close = stock_data.xs(last_date, level='trade_date')['close']
            prev_close = stock_data.xs(prev_date, level='trade_date')['close']
            
            # 对齐股票代码
            common_stocks = last_close.index.intersection(prev_close.index)
            last_close = last_close[common_stocks]
            prev_close = prev_close[common_stocks]
            
            stock_returns = (last_close / prev_close - 1)
        else:
            stock_returns = stock_data['close'].pct_change().iloc[-1]
        
        # 计算涨跌比例
        up_stocks = (stock_returns > 0).sum()
        down_stocks = (stock_returns < 0).sum()
        total_stocks = len(stock_returns)
        
        if total_stocks > 0:
            up_ratio = up_stocks / total_stocks
            down_ratio = down_stocks / total_stocks
        else:
            up_ratio = 0.5
            down_ratio = 0.5
        
        # 判断背离类型
        if index_return > 0.01:  # 指数涨超过1%
            if up_ratio > 0.7:
                divergence_type = self.DIVERGENCE_INDEX_UP_STOCKS_UP
            elif up_ratio < 0.5:
                divergence_type = self.DIVERGENCE_INDEX_UP_STOCKS_DOWN
            else:
                divergence_type = self.DIVERGENCE_NEUTRAL
        elif index_return < -0.01:  # 指数跌超过1%
            if down_ratio > 0.7:
                divergence_type = self.DIVERGENCE_INDEX_DOWN_STOCKS_DOWN
            elif down_ratio < 0.5:
                divergence_type = self.DIVERGENCE_INDEX_DOWN_STOCKS_UP
            else:
                divergence_type = self.DIVERGENCE_NEUTRAL
        else:
            divergence_type = self.DIVERGENCE_NEUTRAL
        
        # 计算背离度
        divergence_value = index_return * (up_ratio - 0.5)
        
        return {
            'type': divergence_type,
            'type_name': self._get_divergence_name(divergence_type),
            'index_return': index_return,
            'up_ratio': up_ratio,
            'down_ratio': down_ratio,
            'divergence_value': divergence_value,
            'up_stocks': int(up_stocks),
            'down_stocks': int(down_stocks),
            'total_stocks': int(total_stocks),
        }
    
    def _get_divergence_name(self, divergence_type: str) -> str:
        """获取背离类型中文名称"""
        divergence_names = {
            self.DIVERGENCE_INDEX_UP_STOCKS_UP: '普涨行情',
            self.DIVERGENCE_INDEX_UP_STOCKS_DOWN: '权重拉指数',
            self.DIVERGENCE_INDEX_DOWN_STOCKS_DOWN: '普跌行情',
            self.DIVERGENCE_INDEX_DOWN_STOCKS_UP: '个股抗跌',
            self.DIVERGENCE_NEUTRAL: '震荡分化',
        }
        return divergence_names.get(divergence_type, '未知')
    
    def _identify_sector_rotation(self, sector_data: pd.DataFrame) -> Dict:
        """
        识别板块轮动
        
        Parameters
        ----------
        sector_data : pd.DataFrame
            板块数据
        
        Returns
        -------
        Dict
            板块轮动分析结果
        """
        # 计算各板块近期收益
        if 'sector_code' in sector_data.columns or 'sector_name' in sector_data.columns:
            sector_col = 'sector_name' if 'sector_name' in sector_data.columns else 'sector_code'
            
            # 按板块分组计算收益
            sector_returns = {}
            
            for sector, group in sector_data.groupby(sector_col):
                if 'close' in group.columns:
                    close = group['close']
                    if len(close) >= 20:
                        return_5d = close.pct_change(5).iloc[-1]
                        return_10d = close.pct_change(10).iloc[-1]
                        return_20d = close.pct_change(20).iloc[-1]
                        
                        sector_returns[sector] = {
                            'return_5d': return_5d,
                            'return_10d': return_10d,
                            'return_20d': return_20d,
                            'strength': 0.3 * return_5d + 0.25 * return_10d + 0.2 * return_20d,
                        }
            
            # 排序
            sorted_sectors = sorted(
                sector_returns.items(),
                key=lambda x: x[1]['strength'],
                reverse=True
            )
            
            return {
                'sector_ranking': sorted_sectors[:10],  # 前10强板块
                'sector_returns': sector_returns,
            }
        
        return {'sector_ranking': [], 'sector_returns': {}}
    
    def _get_leading_sector(self, sector_data: pd.DataFrame) -> Optional[str]:
        """获取领涨板块"""
        rotation = self._identify_sector_rotation(sector_data)
        
        if rotation['sector_ranking']:
            return rotation['sector_ranking'][0][0]
        
        return None
    
    def _calculate_sentiment(self, stock_data: pd.DataFrame) -> Dict:
        """
        计算市场情绪
        
        Parameters
        ----------
        stock_data : pd.DataFrame
            个股数据
        
        Returns
        -------
        Dict
            市场情绪指标
        """
        sentiment = {
            'score': 0.5,  # 默认中性
            'limit_up_count': 0,
            'limit_down_count': 0,
            'continuous_up_count': 0,
        }
        
        if isinstance(stock_data.index, pd.MultiIndex):
            # 获取最新一天数据
            last_date = stock_data.index.get_level_values('trade_date')[-1]
            last_data = stock_data.xs(last_date, level='trade_date')
            
            # 计算涨跌停（简化：涨跌幅超过9.5%视为涨停）
            if 'close' in last_data.columns:
                returns = last_data['close'].pct_change()
                
                # 涨停数
                sentiment['limit_up_count'] = int((returns > 0.095).sum())
                # 跌停数
                sentiment['limit_down_count'] = int((returns < -0.095).sum())
                
                # 计算情绪分数
                if sentiment['limit_up_count'] + sentiment['limit_down_count'] > 0:
                    sentiment['score'] = sentiment['limit_up_count'] / (
                        sentiment['limit_up_count'] + sentiment['limit_down_count']
                    )
        
        return sentiment
    
    def _identify_leader_stock(self, stock_data: pd.DataFrame) -> Optional[str]:
        """
        识别龙头股
        
        Parameters
        ----------
        stock_data : pd.DataFrame
            个股数据
        
        Returns
        -------
        Optional[str]
            龙头股代码
        """
        if not isinstance(stock_data.index, pd.MultiIndex):
            return None
        
        # 获取最近数据
        dates = stock_data.index.get_level_values('trade_date').unique()
        if len(dates) < 5:
            return None
        
        # 计算各股票的龙头分数
        leader_scores = {}
        
        for stock_code in stock_data.index.get_level_values('stock_code').unique():
            try:
                stock_series = stock_data.xs(stock_code, level='stock_code')
                
                if len(stock_series) < 5:
                    continue
                
                close = stock_series['close']
                volume = stock_series['volume']
                
                # 计算动量
                momentum = close.pct_change(5).iloc[-1]
                
                # 计算成交量放大
                vol_ma = volume.rolling(20).mean().iloc[-1]
                vol_ratio = volume.iloc[-1] / (vol_ma + 1e-10)
                
                # 计算连续上涨天数
                returns = close.pct_change()
                continuous_up = 0
                for r in returns.iloc[-10:][::-1]:
                    if r > 0:
                        continuous_up += 1
                    else:
                        break
                
                # 龙头分数
                score = (
                    0.4 * momentum +
                    0.3 * min(vol_ratio - 1, 1) +
                    0.3 * (continuous_up / 10)
                )
                
                leader_scores[stock_code] = score
                
            except Exception:
                continue
        
        # 返回分数最高的股票
        if leader_scores:
            return max(leader_scores.items(), key=lambda x: x[1])[0]
        
        return None
    
    def _generate_summary(self, result: Dict) -> str:
        """生成市场阶段总结"""
        trend = result.get('trend', {})
        divergence = result.get('divergence', {})
        sentiment = result.get('sentiment', {})
        
        trend_name = trend.get('trend_name', '未知')
        divergence_name = divergence.get('type_name', '未知')
        sentiment_score = sentiment.get('score', 0.5)
        
        if sentiment_score > self.sentiment_extreme_high:
            sentiment_desc = '过热'
        elif sentiment_score < self.sentiment_extreme_low:
            sentiment_desc = '过冷'
        else:
            sentiment_desc = '正常'
        
        summary = f"市场处于{trend_name}阶段，{divergence_name}，情绪{sentiment_desc}。"
        
        if result.get('leading_sector'):
            summary += f" 当前领涨板块：{result['leading_sector']}。"
        
        if result.get('leader_stock'):
            summary += f" 龙头股：{result['leader_stock']}。"
        
        return summary
    
    def get_market_stage_history(
        self,
        index_data: pd.DataFrame,
        stock_data: pd.DataFrame,
        window: int = 60
    ) -> pd.DataFrame:
        """
        获取市场阶段历史
        
        Parameters
        ----------
        index_data : pd.DataFrame
            指数数据
        stock_data : pd.DataFrame
            个股数据
        window : int
            回看窗口
        
        Returns
        -------
        pd.DataFrame
            市场阶段历史
        """
        history = []
        
        if isinstance(index_data.index, pd.MultiIndex):
            dates = index_data.index.get_level_values('trade_date').unique()[-window:]
        else:
            dates = index_data.index[-window:]
        
        for date in dates:
            try:
                # 获取到该日期为止的数据
                if isinstance(index_data.index, pd.MultiIndex):
                    idx_data = index_data.loc[pd.IndexSlice[:date, :], :]
                    stk_data = stock_data.loc[pd.IndexSlice[:date, :], :]
                else:
                    idx_data = index_data.loc[:date]
                    stk_data = stock_data.loc[:date]
                
                # 识别阶段
                stage = self.identify(idx_data, stk_data)
                
                history.append({
                    'date': date,
                    'trend': stage['trend']['trend'],
                    'divergence': stage['divergence']['type'],
                    'sentiment': stage['sentiment']['score'],
                })
            except Exception:
                continue
        
        return pd.DataFrame(history)
