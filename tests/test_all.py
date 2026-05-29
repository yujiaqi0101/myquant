"""
测试模块
========

测试A股量化分析系统的各个模块。
"""

import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data import DataLoader, DailyDataAdapter, MockDataAdapter
from src.factors import FactorCalculator, WorldQuantFactors, GuotaiFactors
from src.factors.selector import FactorSelector
from src.factors.backtest import Backtester
from src.analysis import MarketStageDetector, SimilarityAnalyzer
from src.risk import RiskManager, OverfittingDetector


class TestDataModule:
    """测试数据模块"""
    
    def test_data_loader_creation(self):
        """测试数据加载器创建"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        assert loader is not None
        assert loader.adapter is not None
    
    def test_price_data_loading(self):
        """测试价格数据加载"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        price_data = loader.get_price_data()
        
        assert price_data is not None
        assert len(price_data) > 0
    
    def test_index_data_loading(self):
        """测试指数数据加载"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        index_data = loader.get_index_data()
        
        assert index_data is not None
        assert len(index_data) > 0
    
    def test_stock_list(self):
        """测试股票列表获取"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        stock_list = loader.get_stock_list()
        
        assert stock_list is not None
        assert len(stock_list) == 10
    
    def test_industry_mapping(self):
        """测试行业映射"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        industry_map = loader.get_industry_mapping()
        
        assert industry_map is not None
        assert len(industry_map) == 10


class TestFactorModule:
    """测试因子模块"""
    
    def test_factor_calculator(self):
        """测试因子计算器"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        calculator = FactorCalculator(loader)
        calculator.load_data()
        
        close = calculator.close()
        assert close is not None
        assert len(close) > 0
    
    def test_worldquant_factors(self):
        """测试WorldQuant因子计算"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        calculator = FactorCalculator(loader)
        calculator.load_data()
        
        wq = WorldQuantFactors(calculator)
        
        # 测试单个因子
        alpha_001 = wq.alpha_001()
        assert alpha_001 is not None
    
    def test_guotai_factors(self):
        """测试国泰君安因子计算"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        calculator = FactorCalculator(loader)
        calculator.load_data()
        
        gtj = GuotaiFactors(calculator)
        
        # 测试单个因子
        alpha_001 = gtj.alpha_001()
        assert alpha_001 is not None
    
    def test_factor_selector(self):
        """测试因子筛选"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        calculator = FactorCalculator(loader)
        calculator.load_data()
        
        # 计算因子
        wq = WorldQuantFactors(calculator)
        factors = wq.calculate_all()
        
        # 评估因子
        returns = calculator.returns(5).shift(-5)
        
        selector = FactorSelector()
        selector.add_factors(factors)
        metrics = selector.evaluate_all_factors(returns)
        
        assert metrics is not None
        assert len(metrics) > 0


class TestAnalysisModule:
    """测试分析模块"""
    
    def test_market_stage_detector(self):
        """测试市场阶段识别"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=100)
        
        detector = MarketStageDetector()
        
        index_data = loader.get_index_data()
        stock_data = loader.get_price_data()
        
        result = detector.identify(index_data, stock_data)
        
        assert result is not None
        assert 'trend' in result
        assert 'divergence' in result
        assert 'sentiment' in result
    
    def test_similarity_analyzer(self):
        """测试相似度分析"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        
        analyzer = SimilarityAnalyzer(method='cosine')
        stock_data = loader.get_price_data()
        analyzer.load_data(stock_data)
        
        # 获取股票列表
        if isinstance(stock_data.index, pd.MultiIndex):
            stock_codes = stock_data.index.get_level_values('stock_code').unique().tolist()
        else:
            stock_codes = stock_data['stock_code'].unique().tolist()
        
        # 测试相似股票查找
        similar = analyzer.find_similar_stocks(stock_codes[0], window=20, top_k=3)
        
        assert similar is not None
    
    def test_dtw_similarity(self):
        """测试DTW相似度"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        
        analyzer = SimilarityAnalyzer(method='dtw')
        stock_data = loader.get_price_data()
        analyzer.load_data(stock_data)
        
        if isinstance(stock_data.index, pd.MultiIndex):
            stock_codes = stock_data.index.get_level_values('stock_code').unique().tolist()
        else:
            stock_codes = stock_data['stock_code'].unique().tolist()
        
        similar = analyzer.find_similar_stocks(stock_codes[0], window=20, top_k=3)
        
        assert similar is not None


class TestRiskModule:
    """测试风控模块"""
    
    def test_industry_diversification(self):
        """测试行业分散度检查"""
        loader = DataLoader.create_mock(n_stocks=20, n_days=50)
        
        risk_manager = RiskManager()
        industry_map = loader.get_industry_mapping()
        
        # 模拟持仓
        positions = {stock: 0.1 for stock in list(industry_map.keys())[:10]}
        
        result = risk_manager.check_industry_diversification(positions, industry_map)
        
        assert result is not None
        assert 'passed' in result
        assert 'industry_weights' in result
    
    def test_market_cap_exposure(self):
        """测试市值暴露检查"""
        loader = DataLoader.create_mock(n_stocks=20, n_days=50)
        
        risk_manager = RiskManager()
        market_cap_data = loader.get_market_cap_data()
        
        # 模拟持仓
        positions = {stock: 0.1 for stock in list(market_cap_data.keys())[:10]}
        
        result = risk_manager.check_market_cap_exposure(positions, market_cap_data)
        
        assert result is not None
        assert 'passed' in result
    
    def test_drawdown_check(self):
        """测试回撤检查"""
        risk_manager = RiskManager()
        
        # 模拟净值序列
        values = np.array([100, 105, 103, 108, 102, 110, 108, 115])
        
        result = risk_manager.check_drawdown(values)
        
        assert result is not None
        assert 'max_drawdown' in result
    
    def test_overfitting_detector(self):
        """测试过拟合检测"""
        detector = OverfittingDetector()
        
        # 测试夏普衰减
        result = detector.detect_sharpe_decay(2.0, 1.5)
        
        assert result is not None
        assert 'decay' in result
        assert 'is_overfitted' in result


class TestBacktestModule:
    """测试回测模块"""
    
    def test_backtester(self):
        """测试回测器"""
        loader = DataLoader.create_mock(n_stocks=10, n_days=50)
        
        calculator = FactorCalculator(loader)
        calculator.load_data()
        
        wq = WorldQuantFactors(calculator)
        factors = wq.calculate_all()
        
        if factors:
            factor_name = list(factors.keys())[0]
            factor = factors[factor_name]
            
            backtester = Backtester()
            backtester.load_data(loader.get_price_data())
            
            result = backtester.run_backtest(
                factor=factor,
                n_stocks=5,
                rebalance_freq=5
            )
            
            assert result is not None
            assert 'performance' in result


def run_tests():
    """运行所有测试"""
    print("开始运行测试...")
    print("-" * 50)
    
    # 数据模块测试
    print("\n[数据模块测试]")
    test_data = TestDataModule()
    test_data.test_data_loader_creation()
    print("  ✓ 数据加载器创建测试通过")
    test_data.test_price_data_loading()
    print("  ✓ 价格数据加载测试通过")
    test_data.test_index_data_loading()
    print("  ✓ 指数数据加载测试通过")
    test_data.test_stock_list()
    print("  ✓ 股票列表获取测试通过")
    test_data.test_industry_mapping()
    print("  ✓ 行业映射测试通过")
    
    # 分析模块测试
    print("\n[分析模块测试]")
    test_analysis = TestAnalysisModule()
    test_analysis.test_market_stage_detector()
    print("  ✓ 市场阶段识别测试通过")
    test_analysis.test_similarity_analyzer()
    print("  ✓ 相似度分析测试通过")
    test_analysis.test_dtw_similarity()
    print("  ✓ DTW相似度测试通过")
    
    # 因子模块测试
    print("\n[因子模块测试]")
    test_factor = TestFactorModule()
    test_factor.test_factor_calculator()
    print("  ✓ 因子计算器测试通过")
    test_factor.test_worldquant_factors()
    print("  ✓ WorldQuant因子测试通过")
    test_factor.test_guotai_factors()
    print("  ✓ 国泰君安因子测试通过")
    test_factor.test_factor_selector()
    print("  ✓ 因子筛选测试通过")
    
    # 风控模块测试
    print("\n[风控模块测试]")
    test_risk = TestRiskModule()
    test_risk.test_industry_diversification()
    print("  ✓ 行业分散度检查测试通过")
    test_risk.test_market_cap_exposure()
    print("  ✓ 市值暴露检查测试通过")
    test_risk.test_drawdown_check()
    print("  ✓ 回撤检查测试通过")
    test_risk.test_overfitting_detector()
    print("  ✓ 过拟合检测测试通过")
    
    # 回测模块测试
    print("\n[回测模块测试]")
    test_backtest = TestBacktestModule()
    test_backtest.test_backtester()
    print("  ✓ 回测器测试通过")
    
    print("\n" + "-" * 50)
    print("所有测试通过！✓")


if __name__ == "__main__":
    run_tests()
