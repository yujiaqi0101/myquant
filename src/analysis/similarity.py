"""
股票走势相似度分析模块
====================

提供多种相似度计算方法：
- DTW（动态时间规整）
- 余弦相似度
- 特征向量相似度
- 深度学习相似度（预留）
"""

from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime
import pandas as pd
import numpy as np
from scipy.spatial.distance import euclidean


class SimilarityAnalyzer:
    """
    股票走势相似度分析器
    
    支持多种相似度计算方法和分析功能。
    """
    
    def __init__(
        self,
        freq: str = 'daily',
        method: str = 'hybrid',
        windows: List[int] = None
    ):
        """
        初始化相似度分析器
        
        Parameters
        ----------
        freq : str
            数据频率，当前仅支持 'daily'
        method : str
            相似度计算方法：
            - 'dtw': 动态时间规整
            - 'cosine': 余弦相似度
            - 'feature': 特征向量相似度
            - 'hybrid': 混合方法（推荐）
        windows : List[int]
            分析窗口列表，默认 [20, 60, 120]
        """
        self._validate_freq(freq)
        self.freq = freq
        self.method = method
        self.windows = windows or [20, 60, 120]
        
        # 数据存储
        self._price_data = None
        self._normalized_cache = {}
    
    def _validate_freq(self, freq: str):
        """验证频率"""
        supported = ['daily']
        planned = ['5min', '15min', '30min', '60min']
        
        if freq not in supported:
            if freq in planned:
                raise NotImplementedError(f"频率 '{freq}' 计划支持中")
            else:
                raise ValueError(f"不支持的频率: '{freq}'")
    
    def load_data(self, price_data: pd.DataFrame):
        """
        加载价格数据
        
        Parameters
        ----------
        price_data : pd.DataFrame
            价格数据，索引为 (trade_date, stock_code)
        """
        self._price_data = price_data
        self._normalized_cache = {}
    
    def _get_price_series(
        self,
        stock_code: str,
        window: int,
        end_date: Optional[datetime] = None
    ) -> Optional[np.ndarray]:
        """
        获取指定股票的价格序列
        
        Parameters
        ----------
        stock_code : str
            股票代码
        window : int
            窗口大小
        end_date : datetime, optional
            结束日期
        
        Returns
        -------
        np.ndarray
            价格序列
        """
        if self._price_data is None:
            raise ValueError("请先使用 load_data() 加载数据")
        
        try:
            if isinstance(self._price_data.index, pd.MultiIndex):
                stock_data = self._price_data.xs(stock_code, level='stock_code')
            else:
                stock_data = self._price_data[self._price_data['stock_code'] == stock_code]
            
            if end_date:
                stock_data = stock_data.loc[:end_date]
            
            # 获取最近window天的收盘价
            close = stock_data['close'].iloc[-window:]
            
            if len(close) < window:
                return None
            
            return close.values
        except Exception:
            return None
    
    def _normalize(self, series: np.ndarray, method: str = 'zscore') -> np.ndarray:
        """
        标准化序列
        
        Parameters
        ----------
        series : np.ndarray
            原始序列
        method : str
            标准化方法：'zscore' 或 'minmax'
        
        Returns
        -------
        np.ndarray
            标准化后的序列
        """
        if method == 'zscore':
            mean = np.mean(series)
            std = np.std(series)
            if std < 1e-10:
                return np.zeros_like(series)
            return (series - mean) / std
        elif method == 'minmax':
            min_val = np.min(series)
            max_val = np.max(series)
            if max_val - min_val < 1e-10:
                return np.zeros_like(series)
            return (series - min_val) / (max_val - min_val)
        else:
            return series
    
    def calculate_dtw_similarity(
        self,
        series1: np.ndarray,
        series2: np.ndarray
    ) -> float:
        """
        计算DTW相似度
        
        使用快速DTW算法计算两个序列的相似度。
        
        Parameters
        ----------
        series1 : np.ndarray
            序列1
        series2 : np.ndarray
            序列2
        
        Returns
        -------
        float
            相似度值 (0-1)
        """
        # 标准化
        s1 = self._normalize(series1)
        s2 = self._normalize(series2)
        
        # 简化的DTW实现
        n, m = len(s1), len(s2)
        
        # 初始化距离矩阵
        dtw_matrix = np.full((n + 1, m + 1), np.inf)
        dtw_matrix[0, 0] = 0
        
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cost = (s1[i-1] - s2[j-1]) ** 2
                dtw_matrix[i, j] = cost + min(
                    dtw_matrix[i-1, j],    # 插入
                    dtw_matrix[i, j-1],    # 删除
                    dtw_matrix[i-1, j-1]   # 匹配
                )
        
        distance = np.sqrt(dtw_matrix[n, m])
        
        # 转换为相似度
        similarity = 1 / (1 + distance)
        
        return similarity
    
    def calculate_cosine_similarity(
        self,
        series1: np.ndarray,
        series2: np.ndarray
    ) -> float:
        """
        计算余弦相似度
        
        Parameters
        ----------
        series1 : np.ndarray
            序列1
        series2 : np.ndarray
            序列2
        
        Returns
        -------
        float
            相似度值 (-1 到 1)
        """
        # 标准化
        s1 = self._normalize(series1)
        s2 = self._normalize(series2)
        
        # 确保长度一致
        min_len = min(len(s1), len(s2))
        s1 = s1[:min_len]
        s2 = s2[:min_len]
        
        # 计算余弦相似度
        dot_product = np.dot(s1, s2)
        norm1 = np.linalg.norm(s1)
        norm2 = np.linalg.norm(s2)
        
        if norm1 < 1e-10 or norm2 < 1e-10:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def calculate_feature_similarity(
        self,
        series1: np.ndarray,
        series2: np.ndarray
    ) -> float:
        """
        计算特征向量相似度
        
        提取序列特征，计算特征向量的相似度。
        
        Parameters
        ----------
        series1 : np.ndarray
            序列1
        series2 : np.ndarray
            序列2
        
        Returns
        -------
        float
            相似度值 (0-1)
        """
        def extract_features(series: np.ndarray) -> np.ndarray:
            """提取特征向量"""
            features = []
            
            # 收益率特征
            returns = np.diff(series) / series[:-1]
            features.append(np.mean(returns))
            features.append(np.std(returns))
            features.append(np.max(returns))
            features.append(np.min(returns))
            
            # 趋势特征
            x = np.arange(len(series))
            slope, _ = np.polyfit(x, series, 1)
            features.append(slope / np.mean(series))
            
            # 波动特征
            features.append(np.std(series) / np.mean(series))
            
            # 形态特征
            max_val = np.max(series)
            min_val = np.min(series)
            features.append((max_val - min_val) / np.mean(series))
            
            # 位置特征
            features.append((series[-1] - min_val) / (max_val - min_val + 1e-10))
            
            return np.array(features)
        
        feat1 = extract_features(series1)
        feat2 = extract_features(series2)
        
        # 计算欧氏距离并转换为相似度
        distance = np.linalg.norm(feat1 - feat2)
        similarity = 1 / (1 + distance)
        
        return similarity
    
    def calculate_similarity(
        self,
        series1: np.ndarray,
        series2: np.ndarray,
        method: Optional[str] = None
    ) -> float:
        """
        计算相似度
        
        Parameters
        ----------
        series1 : np.ndarray
            序列1
        series2 : np.ndarray
            序列2
        method : str, optional
            计算方法，不指定则使用初始化时的方法
        
        Returns
        -------
        float
            相似度值
        """
        method = method or self.method
        
        if method == 'dtw':
            return self.calculate_dtw_similarity(series1, series2)
        elif method == 'cosine':
            return self.calculate_cosine_similarity(series1, series2)
        elif method == 'feature':
            return self.calculate_feature_similarity(series1, series2)
        elif method == 'hybrid':
            dtw_sim = self.calculate_dtw_similarity(series1, series2)
            cosine_sim = self.calculate_cosine_similarity(series1, series2)
            feature_sim = self.calculate_feature_similarity(series1, series2)
            return 0.4 * dtw_sim + 0.3 * cosine_sim + 0.3 * feature_sim
        else:
            raise ValueError(f"不支持的相似度计算方法: '{method}'")
    
    def find_similar_stocks(
        self,
        target_stock: str,
        candidate_stocks: Optional[List[str]] = None,
        window: int = 20,
        top_k: int = 10,
        threshold: float = 0.0
    ) -> List[Dict]:
        """
        找出与目标股票走势相似的股票
        
        Parameters
        ----------
        target_stock : str
            目标股票代码
        candidate_stocks : List[str], optional
            候选股票列表，不指定则使用所有股票
        window : int
            分析窗口
        top_k : int
            返回前K个最相似的股票
        threshold : float
            相似度阈值
        
        Returns
        -------
        List[Dict]
            相似股票列表，包含股票代码和相似度
        """
        # 获取目标序列
        target_series = self._get_price_series(target_stock, window)
        if target_series is None:
            return []
        
        # 获取候选股票列表
        if candidate_stocks is None:
            if isinstance(self._price_data.index, pd.MultiIndex):
                candidate_stocks = self._price_data.index.get_level_values('stock_code').unique().tolist()
            else:
                candidate_stocks = self._price_data['stock_code'].unique().tolist()
        
        # 排除目标股票
        candidate_stocks = [s for s in candidate_stocks if s != target_stock]
        
        # 计算相似度
        similarities = []
        
        for stock_code in candidate_stocks:
            series = self._get_price_series(stock_code, window)
            if series is None:
                continue
            
            sim = self.calculate_similarity(target_series, series)
            
            if sim >= threshold:
                similarities.append({
                    'stock_code': stock_code,
                    'similarity': sim,
                    'window': window,
                })
        
        # 排序并返回Top K
        similarities.sort(key=lambda x: x['similarity'], reverse=True)
        
        return similarities[:top_k]
    
    def find_similar_periods(
        self,
        stock_code: str,
        window: int = 20,
        threshold: float = 0.8,
        min_gap: int = 60
    ) -> List[Dict]:
        """
        在历史数据中查找与当前走势相似的时间段
        
        Parameters
        ----------
        stock_code : str
            股票代码
        window : int
            分析窗口
        threshold : float
            相似度阈值
        min_gap : int
            最小间隔（避免重叠）
        
        Returns
        -------
        List[Dict]
            相似时间段列表
        """
        # 获取完整价格序列
        full_series = self._get_price_series(stock_code, len(self._price_data))
        if full_series is None or len(full_series) < window + min_gap:
            return []
        
        # 当前走势
        current_series = full_series[-window:]
        
        # 遍历历史
        similar_periods = []
        
        for i in range(0, len(full_series) - window - min_gap, min_gap // 2):
            historical_series = full_series[i:i+window]
            
            sim = self.calculate_similarity(current_series, historical_series)
            
            if sim >= threshold:
                # 计算后续收益
                if i + window + 20 < len(full_series):
                    subsequent_series = full_series[i+window:i+window+20]
                    subsequent_return = (subsequent_series[-1] - subsequent_series[0]) / subsequent_series[0]
                else:
                    subsequent_return = None
                
                similar_periods.append({
                    'start_idx': i,
                    'end_idx': i + window,
                    'similarity': sim,
                    'subsequent_return_20d': subsequent_return,
                })
        
        # 按相似度排序
        similar_periods.sort(key=lambda x: x['similarity'], reverse=True)
        
        return similar_periods
    
    def calculate_similarity_matrix(
        self,
        stock_codes: List[str],
        window: int = 20
    ) -> pd.DataFrame:
        """
        计算股票之间的相似度矩阵
        
        Parameters
        ----------
        stock_codes : List[str]
            股票代码列表
        window : int
            分析窗口
        
        Returns
        -------
        pd.DataFrame
            相似度矩阵
        """
        n = len(stock_codes)
        matrix = np.zeros((n, n))
        
        # 获取所有序列
        series_dict = {}
        for i, stock_code in enumerate(stock_codes):
            series = self._get_price_series(stock_code, window)
            if series is not None:
                series_dict[stock_code] = series
        
        # 计算相似度矩阵
        for i, code1 in enumerate(stock_codes):
            if code1 not in series_dict:
                continue
            
            for j, code2 in enumerate(stock_codes):
                if i == j:
                    matrix[i, j] = 1.0
                elif j > i and code2 in series_dict:
                    sim = self.calculate_similarity(series_dict[code1], series_dict[code2])
                    matrix[i, j] = sim
                    matrix[j, i] = sim
        
        return pd.DataFrame(matrix, index=stock_codes, columns=stock_codes)
    
    def cluster_similar_stocks(
        self,
        stock_codes: List[str],
        window: int = 20,
        n_clusters: int = 5
    ) -> Dict[int, List[str]]:
        """
        对股票进行聚类
        
        Parameters
        ----------
        stock_codes : List[str]
            股票代码列表
        window : int
            分析窗口
        n_clusters : int
            聚类数量
        
        Returns
        -------
        Dict[int, List[str]]
            聚类结果，键为聚类编号，值为股票代码列表
        """
        from sklearn.cluster import KMeans
        
        # 计算相似度矩阵
        sim_matrix = self.calculate_similarity_matrix(stock_codes, window)
        
        # 转换为距离矩阵
        dist_matrix = 1 - sim_matrix.values
        
        # K-Means聚类
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(dist_matrix)
        
        # 整理结果
        clusters = {}
        for i, label in enumerate(labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(stock_codes[i])
        
        return clusters
