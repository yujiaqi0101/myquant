"""
Streamlit可视化仪表盘
====================

提供交互式的量化分析可视化界面。
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Optional
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.data import DataLoader
from src.factors import FactorCalculator, WorldQuantFactors, GuotaiFactors
from src.factors.selector import FactorSelector
from src.factors.backtest import Backtester
from src.analysis import MarketStageDetector, SimilarityAnalyzer
from src.risk import RiskManager


def create_dashboard():
    """创建Streamlit仪表盘"""
    
    st.set_page_config(
        page_title="A股量化分析系统",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # 侧边栏
    st.sidebar.title("📊 A股量化分析系统")
    st.sidebar.markdown("---")
    
    # 功能选择
    page = st.sidebar.selectbox(
        "选择功能",
        ["🏠 首页", "📈 市场阶段识别", "🔍 相似度分析", "📊 因子分析", "💰 回测分析", "🛡️ 风控检查", "📋 待办事项"]
    )
    
    # 初始化session state
    if 'data_loader' not in st.session_state:
        st.session_state.data_loader = None
    if 'price_data' not in st.session_state:
        st.session_state.price_data = None
    
    # 根据选择显示不同页面
    if page == "🏠 首页":
        show_home_page()
    elif page == "📈 市场阶段识别":
        show_market_stage_page()
    elif page == "🔍 相似度分析":
        show_similarity_page()
    elif page == "📊 因子分析":
        show_factor_page()
    elif page == "💰 回测分析":
        show_backtest_page()
    elif page == "🛡️ 风控检查":
        show_risk_page()
    elif page == "📋 待办事项":
        show_todo_page()


def show_home_page():
    """显示首页"""
    st.title("🏠 系统首页")
    
    st.markdown("""
    ## 欢迎使用A股量化分析系统
    
    本系统是一个专注于分析的A股量化研究平台，包含以下核心功能：
    
    ### 📈 市场阶段识别
    - 牛熊判断
    - 指数与个股关系分析
    - 板块轮动识别
    - 市场情绪指标
    
    ### 🔍 相似度分析
    - 股票走势相似度计算
    - 历史相似时间段查找
    - 相似度矩阵可视化
    
    ### 📊 因子分析
    - WorldQuant 101因子
    - 国泰君安191因子
    - 因子筛选与组合优化
    
    ### 💰 回测分析
    - 因子回测
    - 策略评估
    - 绩效分析
    
    ### 🛡️ 风控检查
    - 行业分散度控制
    - 市值暴露控制
    - 过拟合检测
    """)
    
    # 数据加载区域
    st.markdown("---")
    st.subheader("📁 数据加载")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**选项1：使用模拟数据**")
        n_stocks = st.number_input("股票数量", min_value=10, max_value=500, value=100)
        n_days = st.number_input("交易日数量", min_value=50, max_value=1000, value=250)
        
        if st.button("生成模拟数据"):
            with st.spinner("正在生成模拟数据..."):
                data_loader = DataLoader.create_mock(n_stocks=n_stocks, n_days=n_days)
                st.session_state.data_loader = data_loader
                st.session_state.price_data = data_loader.get_price_data()
                st.success(f"已生成 {n_stocks} 只股票，{n_days} 个交易日的模拟数据")
    
    with col2:
        st.markdown("**选项2：上传CSV文件**")
        uploaded_file = st.file_uploader("上传价格数据CSV", type=['csv'])
        
        if uploaded_file is not None:
            try:
                df = pd.read_csv(uploaded_file)
                data_loader = DataLoader.from_dataframe(df)
                st.session_state.data_loader = data_loader
                st.session_state.price_data = data_loader.get_price_data()
                st.success(f"已加载数据：{len(df)} 行")
            except Exception as e:
                st.error(f"加载数据失败：{e}")
    
    # 显示数据概览
    if st.session_state.price_data is not None:
        st.markdown("---")
        st.subheader("📊 数据概览")
        
        price_data = st.session_state.price_data
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if isinstance(price_data.index, pd.MultiIndex):
                n_stocks = len(price_data.index.get_level_values('stock_code').unique())
                n_days = len(price_data.index.get_level_values('trade_date').unique())
            else:
                n_stocks = len(price_data['stock_code'].unique()) if 'stock_code' in price_data.columns else 1
                n_days = len(price_data)
            
            st.metric("股票数量", n_stocks)
        
        with col2:
            st.metric("交易日数", n_days)
        
        with col3:
            st.metric("数据行数", len(price_data))
        
        with col4:
            st.metric("数据列数", len(price_data.columns))
        
        # 显示数据样例
        st.markdown("**数据样例：**")
        st.dataframe(price_data.head(10))


def show_market_stage_page():
    """显示市场阶段识别页面"""
    st.title("📈 市场阶段识别")
    
    if st.session_state.data_loader is None:
        st.warning("请先在首页加载数据")
        return
    
    # 获取数据
    data_loader = st.session_state.data_loader
    
    # 初始化识别器
    detector = MarketStageDetector()
    
    # 获取指数和个股数据
    try:
        index_data = data_loader.get_index_data()
        stock_data = data_loader.get_price_data()
    except Exception as e:
        st.error(f"获取数据失败：{e}")
        return
    
    # 识别市场阶段
    with st.spinner("正在识别市场阶段..."):
        result = detector.identify(index_data, stock_data)
    
    # 显示结果
    st.subheader("📊 市场阶段概览")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        trend = result.get('trend', {})
        st.metric(
            "市场趋势",
            trend.get('trend_name', '未知'),
            delta=f"{trend.get('ma_long_distance', 0):.2%}" if trend else None
        )
    
    with col2:
        divergence = result.get('divergence', {})
        st.metric(
            "指数个股关系",
            divergence.get('type_name', '未知'),
            delta=f"涨跌比: {divergence.get('up_ratio', 0):.1%}" if divergence else None
        )
    
    with col3:
        sentiment = result.get('sentiment', {})
        score = sentiment.get('score', 0.5)
        st.metric(
            "市场情绪",
            f"{score:.2f}",
            delta="过热" if score > 0.8 else ("过冷" if score < 0.2 else "正常")
        )
    
    with col4:
        leading_sector = result.get('leading_sector', '未知')
        st.metric("领涨板块", leading_sector)
    
    # 显示总结
    st.markdown("---")
    st.subheader("📝 市场总结")
    st.info(result.get('summary', '暂无总结'))
    
    # 显示趋势详情
    st.markdown("---")
    st.subheader("📈 趋势详情")
    
    trend = result.get('trend', {})
    if trend:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"""
            - **趋势状态**: {trend.get('trend_name', '未知')}
            - **当前价格**: {trend.get('close', 0):.2f}
            - **长期均线**: {trend.get('ma_long', 0):.2f}
            - **短期均线**: {trend.get('ma_short', 0):.2f}
            """)
        
        with col2:
            st.markdown(f"""
            - **长期均线偏离**: {trend.get('ma_long_distance', 0):.2%}
            - **短期均线偏离**: {trend.get('ma_short_distance', 0):.2%}
            """)
    
    # 显示背离详情
    st.markdown("---")
    st.subheader("📊 指数个股背离分析")
    
    divergence = result.get('divergence', {})
    if divergence:
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("指数收益", f"{divergence.get('index_return', 0):.2%}")
        
        with col2:
            st.metric("上涨股票占比", f"{divergence.get('up_ratio', 0):.1%}")
        
        with col3:
            st.metric("下跌股票占比", f"{divergence.get('down_ratio', 0):.1%}")


def show_similarity_page():
    """显示相似度分析页面"""
    st.title("🔍 相似度分析")
    
    if st.session_state.data_loader is None:
        st.warning("请先在首页加载数据")
        return
    
    price_data = st.session_state.price_data
    
    # 参数设置
    col1, col2, col3 = st.columns(3)
    
    with col1:
        window = st.selectbox("分析窗口", [20, 60, 120], index=0)
    
    with col2:
        method = st.selectbox("相似度方法", ["hybrid", "dtw", "cosine", "feature"], index=0)
    
    with col3:
        top_k = st.number_input("返回数量", min_value=5, max_value=50, value=10)
    
    # 初始化分析器
    analyzer = SimilarityAnalyzer(method=method, windows=[window])
    analyzer.load_data(price_data)
    
    # 获取股票列表
    if isinstance(price_data.index, pd.MultiIndex):
        stock_codes = price_data.index.get_level_values('stock_code').unique().tolist()
    else:
        stock_codes = price_data['stock_code'].unique().tolist() if 'stock_code' in price_data.columns else []
    
    # 选择目标股票
    target_stock = st.selectbox("选择目标股票", stock_codes[:100] if len(stock_codes) > 100 else stock_codes)
    
    if st.button("查找相似股票"):
        with st.spinner("正在计算相似度..."):
            similar_stocks = analyzer.find_similar_stocks(
                target_stock=target_stock,
                window=window,
                top_k=top_k
            )
        
        if similar_stocks:
            st.subheader("📊 相似股票列表")
            
            df = pd.DataFrame(similar_stocks)
            df['similarity'] = df['similarity'].apply(lambda x: f"{x:.4f}")
            st.dataframe(df, use_container_width=True)
            
            # 绘制走势对比图
            st.subheader("📈 走势对比")
            
            target_series = analyzer._get_price_series(target_stock, window)
            
            fig = go.Figure()
            
            # 目标股票
            fig.add_trace(go.Scatter(
                y=target_series,
                mode='lines',
                name=f'目标: {target_stock}',
                line=dict(color='blue', width=2)
            ))
            
            # 相似股票（前5个）
            colors = ['red', 'green', 'orange', 'purple', 'brown']
            for i, stock in enumerate(similar_stocks[:5]):
                series = analyzer._get_price_series(stock['stock_code'], window)
                if series is not None:
                    fig.add_trace(go.Scatter(
                        y=series,
                        mode='lines',
                        name=f"{stock['stock_code']} ({stock['similarity']:.2%})",
                        line=dict(color=colors[i % len(colors)], width=1, dash='dash')
                    ))
            
            fig.update_layout(
                title='走势对比图',
                xaxis_title='交易日',
                yaxis_title='价格',
                height=500
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("未找到相似股票")


def show_factor_page():
    """显示因子分析页面"""
    st.title("📊 因子分析")
    
    if st.session_state.data_loader is None:
        st.warning("请先在首页加载数据")
        return
    
    data_loader = st.session_state.data_loader
    
    # 因子计算
    st.subheader("🔧 因子计算")
    
    col1, col2 = st.columns(2)
    
    with col1:
        calc_wq = st.checkbox("计算WorldQuant因子", value=True)
    
    with col2:
        calc_gtj = st.checkbox("计算国泰君安因子", value=True)
    
    if st.button("计算因子"):
        with st.spinner("正在计算因子..."):
            # 初始化计算器
            calculator = FactorCalculator(data_loader)
            calculator.load_data()
            
            factors = {}
            
            if calc_wq:
                wq = WorldQuantFactors(calculator)
                wq_factors = wq.calculate_all()
                factors.update(wq_factors)
            
            if calc_gtj:
                gtj = GuotaiFactors(calculator)
                gtj_factors = gtj.calculate_all()
                factors.update(gtj_factors)
            
            st.session_state.factors = factors
            st.success(f"已计算 {len(factors)} 个因子")
    
    # 因子评估
    if 'factors' in st.session_state and st.session_state.factors:
        st.markdown("---")
        st.subheader("📈 因子评估")
        
        if st.button("评估因子"):
            with st.spinner("正在评估因子..."):
                # 计算未来收益
                calculator = FactorCalculator(data_loader)
                calculator.load_data()
                returns = calculator.returns(5).shift(-5)
                
                # 评估因子
                selector = FactorSelector()
                selector.add_factors(st.session_state.factors)
                metrics = selector.evaluate_all_factors(returns)
                
                st.session_state.factor_metrics = metrics
                st.session_state.factor_selector = selector
        
        # 显示评估结果
        if 'factor_metrics' in st.session_state:
            st.subheader("📊 因子评估结果")
            
            report = st.session_state.factor_selector.get_factor_report()
            st.dataframe(report.style.format({
                'IC_mean': '{:.4f}',
                'IC_std': '{:.4f}',
                'IC_IR': '{:.4f}',
                'IC_positive_ratio': '{:.2%}',
                'layer_spread': '{:.2%}',
                'turnover': '{:.4f}',
            }), use_container_width=True)


def show_backtest_page():
    """显示回测分析页面"""
    st.title("💰 回测分析")
    
    if 'factors' not in st.session_state or not st.session_state.factors:
        st.warning("请先在因子分析页面计算因子")
        return
    
    # 参数设置
    col1, col2, col3 = st.columns(3)
    
    with col1:
        factor_name = st.selectbox("选择因子", list(st.session_state.factors.keys()))
    
    with col2:
        n_stocks = st.number_input("持仓股票数", min_value=10, max_value=200, value=50)
    
    with col3:
        rebalance_freq = st.number_input("调仓频率（日）", min_value=1, max_value=20, value=5)
    
    if st.button("运行回测"):
        with st.spinner("正在运行回测..."):
            factor = st.session_state.factors[factor_name]
            
            # 初始化回测器
            backtester = Backtester()
            backtester.load_data(st.session_state.price_data)
            
            # 运行回测
            result = backtester.run_backtest(
                factor=factor,
                n_stocks=n_stocks,
                rebalance_freq=rebalance_freq
            )
        
        # 显示结果
        st.subheader("📊 回测结果")
        
        performance = result['performance']
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("总收益", f"{performance.get('total_return', 0):.2%}")
        
        with col2:
            st.metric("年化收益", f"{performance.get('annual_return', 0):.2%}")
        
        with col3:
            st.metric("夏普比率", f"{performance.get('sharpe_ratio', 0):.2f}")
        
        with col4:
            st.metric("最大回撤", f"{performance.get('max_drawdown', 0):.2%}")
        
        # 绘制净值曲线
        st.subheader("📈 净值曲线")
        
        portfolio_df = result['portfolio_values']
        
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=portfolio_df['date'],
            y=portfolio_df['value'],
            mode='lines',
            name='组合净值',
            line=dict(color='blue', width=2)
        ))
        
        fig.update_layout(
            title='组合净值曲线',
            xaxis_title='日期',
            yaxis_title='净值',
            height=400
        )
        
        st.plotly_chart(fig, use_container_width=True)


def show_risk_page():
    """显示风控检查页面"""
    st.title("🛡️ 风控检查")
    
    st.markdown("""
    ### 风控模块功能
    
    本模块提供以下风控功能：
    
    1. **行业分散度控制**：检查持仓是否过度集中于单一行业
    2. **市值暴露控制**：检查持仓的市值分布是否合理
    3. **过拟合检测**：检测策略是否存在过拟合问题
    
    请在回测后使用本功能进行风控检查。
    """)
    
    # 示例：行业分散度检查
    st.subheader("📊 行业分散度检查示例")
    
    if st.session_state.data_loader is not None:
        data_loader = st.session_state.data_loader
        industry_map = data_loader.get_industry_mapping()
        
        if industry_map:
            st.write(f"已加载 {len(industry_map)} 只股票的行业信息")
            
            # 显示行业分布
            industries = list(industry_map.values())
            industry_counts = pd.Series(industries).value_counts()
            
            fig = go.Figure(data=[go.Bar(
                x=industry_counts.index,
                y=industry_counts.values
            )])
            
            fig.update_layout(
                title='股票行业分布',
                xaxis_title='行业',
                yaxis_title='股票数量',
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("模拟数据中已包含行业信息")


def show_todo_page():
    """显示待办事项页面"""
    st.title("📋 待办事项")
    
    st.markdown("""
    ### 系统待办事项
    
    以下功能计划在未来版本中实现：
    """)
    
    todos = [
        {"id": "DATA-001", "title": "分钟级行情数据支持", "category": "数据层", "priority": "中", "status": "待开发"},
        {"id": "DATA-002", "title": "基本面数据接入", "category": "数据层", "priority": "中", "status": "待开发"},
        {"id": "DATA-003", "title": "宏观数据接入", "category": "数据层", "priority": "低", "status": "待开发"},
        {"id": "DATA-004", "title": "另类数据接入", "category": "数据层", "priority": "低", "status": "待开发"},
        {"id": "TRADE-001", "title": "实盘交易接口对接", "category": "实盘对接", "priority": "低", "status": "待开发"},
        {"id": "FEAT-001", "title": "形态识别算法", "category": "功能增强", "priority": "中", "status": "待开发"},
        {"id": "FEAT-002", "title": "深度学习相似度", "category": "功能增强", "priority": "中", "status": "待开发"},
        {"id": "FEAT-003", "title": "遗传编程挖因子", "category": "功能增强", "priority": "中", "status": "待开发"},
    ]
    
    df = pd.DataFrame(todos)
    st.dataframe(df, use_container_width=True)


def run_dashboard():
    """运行仪表盘"""
    create_dashboard()


if __name__ == "__main__":
    run_dashboard()
