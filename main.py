"""
A股量化分析系统
==============

主入口文件

数据读取约定（hard constraints）：
- 所有市场数据严格从数据库读取
- 数据库为空时直接报错退出
- AQUANT_DATA_MODE 模式已删除，不再支持模拟数据回退
"""

import sys
import argparse
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.data import DataLoader
from src.data.database import DatabaseManager
from src.data.test_data_generator import TestDataGenerator
from src.factors import FactorCalculator, WorldQuantFactors, GuotaiFactors
from src.factors.selector import FactorSelector
from src.factors.backtest import Backtester
from src.factors.execution_logger import ExecutionLogger
from src.analysis import MarketStageDetector, SimilarityAnalyzer
from src.risk import RiskManager
from src.enhancement import IndexEnhancementAnalyzer, IndexConstituentGenerator
from src.valuation import ValuationAnalyzer
from src.utils.logger import setup_logger, get_log_files
from src.factors.multi_factor_quintile_backtest_v2 import MultiFactorQuintileBacktestEngineV2
from src.factors.multi_factor_backtest import MultiFactorBacktester

# 导入配置
from config.config import (
    DataMode, 
    get_data_mode, 
    is_test_mode, 
    DATABASE_CONFIG,
    TEST_DATA_DIR
)

import pandas as pd


def generate_test_data():
    """生成测试数据CSV文件"""
    print("\n[测试数据生成]")
    generator = TestDataGenerator()
    data = generator.generate_all_test_data(n_stocks=100, n_days=250)
    print(f"   ✓ 测试数据已保存到: {TEST_DATA_DIR}")
    print(f"   ✓ 股票信息: {len(data['stock_info'])} 条")
    print(f"   ✓ 股票日频: {len(data['stock_daily'])} 条")
    print(f"   ✓ 指数日频: {len(data['index_daily'])} 条")
    return data


def run_analysis(db=None, data_loader=None, used_mock_data=False):
    """
    运行分析流程

    Parameters
    ----------
    db : DatabaseManager, optional
        数据库管理器
    data_loader : DataLoader, optional
        数据加载器
    used_mock_data : bool
        是否使用了模拟数据（用于提示用户）
    """
    # 打印数据源信息
    print("\n" + "-" * 50)
    if used_mock_data:
        print("⚠  警告: 当前使用了模拟数据（数据库为空，已自动回退）")
        print("         分析结果仅供参考，不代表真实市场情况")
        print("         如需使用真实数据，请先通过QMT同步数据到数据库")
    else:
        print("✓  当前使用数据库中的真实数据")
    print("-" * 50)
    
    # 如果没有提供 data_loader，从数据库加载
    if data_loader is None:
        db_path = str(project_root / DATABASE_CONFIG["path"])
        data_loader = DataLoader.from_database(db_path)
        if db is None:
            db = DatabaseManager(db_path)

    print("\n[数据加载] 从数据源加载数据...")
    print(f"   ✓ 数据加载完成")

    # 创建执行日志记录器
    # 测试模式下也正常写入执行日志（执行结果不是测试数据）
    exec_logger = None
    if db is not None:
        exec_logger = ExecutionLogger(db)

    # 3. 市场阶段识别
    print("\n[市场阶段识别]")
    detector = MarketStageDetector()
    index_data = data_loader.get_index_data()
    stock_data = data_loader.get_price_data()

    if index_data.empty or stock_data.empty:
        print("   ⚠ 数据不足，跳过市场阶段识别")
    else:
        market_stage = detector.identify(index_data, stock_data)
        print(f"   ✓ 市场趋势: {market_stage['trend']['trend_name']}")
        print(f"   ✓ 指数个股关系: {market_stage['divergence']['type_name']}")
        print(f"   ✓ 市场情绪: {market_stage['sentiment']['score']:.2f}")
        print(f"   ✓ 总结: {market_stage['summary']}")

    # 4. 相似度分析
    print("\n[相似度分析]")
    if stock_data.empty:
        print("   ⚠ 数据不足，跳过相似度分析")
    else:
        analyzer = SimilarityAnalyzer(method='hybrid')
        analyzer.load_data(stock_data)

        if isinstance(stock_data.index, pd.MultiIndex):
            target_stock = stock_data.index.get_level_values('stock_code')[0]
        else:
            target_stock = stock_data['stock_code'].iloc[0]

        similar_stocks = analyzer.find_similar_stocks(target_stock, window=20, top_k=5)
        print(f"   ✓ 目标股票: {target_stock}")
        print(f"   ✓ 找到 {len(similar_stocks)} 只相似股票")
        for i, stock in enumerate(similar_stocks[:3], 1):
            print(f"      {i}. {stock['stock_code']}: 相似度 {stock['similarity']:.2%}")

    # 5. 因子计算
    print("\n[因子计算]")
    if stock_data.empty:
        print("   ⚠ 数据不足，跳过因子计算")
    else:
        calculator = FactorCalculator(data_loader)
        calculator.load_data()

        wq = WorldQuantFactors(calculator)
        wq_factors = wq.calculate_all()
        print(f"   ✓ 已计算 {len(wq_factors)} 个WorldQuant因子")

        gtj = GuotaiFactors(calculator)
        gtj_factors = gtj.calculate_all()
        print(f"   ✓ 已计算 {len(gtj_factors)} 个国泰君安因子")

        # 6. 因子筛选（带执行日志）
        print("\n[因子筛选]")
        all_factors = {**wq_factors, **gtj_factors}

        if exec_logger is not None:
            selector = FactorSelector(execution_logger=exec_logger)
        else:
            selector = FactorSelector()

        selector.add_factors(all_factors)

        returns = calculator.returns(5).shift(-5)
        metrics = selector.evaluate_all_factors(returns)

        selected = selector.select_factors(method='ic', top_k=5)
        print(f"   ✓ 已评估 {len(metrics)} 个因子")
        if exec_logger is not None:
            print(f"   ✓ 筛选出 {len(selected)} 个有效因子（结果已记录到数据库）")
        else:
            print(f"   ✓ 筛选出 {len(selected)} 个有效因子")
        for i, name in enumerate(selected[:3], 1):
            m = metrics[name]
            print(f"      {i}. {name}: IC={m['IC_mean']:.4f}, IR={m['IC_IR']:.4f}")

        # 7. 回测（带执行日志）
        print("\n[因子回测]")
        if selected:
            best_factor = all_factors[selected[0]]

            if exec_logger is not None:
                backtester = Backtester(execution_logger=exec_logger)
            else:
                backtester = Backtester()

            backtester.load_data(stock_data)

            result = backtester.run_backtest(
                factor=best_factor,
                n_stocks=20,
                rebalance_freq=5
            )

            perf = result['performance']
            print(f"   ✓ 总收益: {perf['total_return']:.2%}")
            print(f"   ✓ 年化收益: {perf['annual_return']:.2%}")
            print(f"   ✓ 夏普比率: {perf['sharpe_ratio']:.2f}")
            print(f"   ✓ 最大回撤: {perf['max_drawdown']:.2%}")
            if exec_logger is not None:
                print(f"   ✓ 回测结果已记录到数据库")
        else:
            print("   ⚠ 无有效因子，跳过回测")

        # 8. 风控检查
        print("\n[风控检查]")
        risk_manager = RiskManager()

        industry_map = data_loader.get_industry_mapping()
        positions = {stock: 1.0 / max(len(selected), 1) for stock in selected[:10]}

        risk_check = risk_manager.check_industry_diversification(positions, industry_map)
        print(f"   ✓ 行业分散度检查: {'通过' if risk_check['passed'] else '未通过'}")
        print(f"   ✓ 覆盖行业数: {risk_check['n_industries']}")

    # 9. 指数增强分析
    # 注意：generate_constituent_data 会往数据库写入成分股数据
    # 这些成分股数据属于"模拟的市场数据"，不是执行结果
    # 所以在 used_mock_data=True 时跳过，避免污染数据库
    if db is not None and not used_mock_data:
        print("\n[指数增强分析]")
        try:
            generator = IndexConstituentGenerator(db)

            # 检查是否已有成分股数据
            summary = db.get_data_summary()
            if summary['index_constituent']['count'] == 0:
                print("   生成指数成分股模拟数据...")
                generator.generate_constituent_data(
                    index_code='000300.SH',
                    n_stocks=50,
                    start_date='2023-01-01',
                    end_date='2023-12-29'
                )

            # 生成模拟组合权重
            portfolio_weights = generator.generate_portfolio_weights(
                index_code='000300.SH',
                n_holdings=20,
                start_date='2023-01-01',
                end_date='2023-12-29'
            )

            # 执行分析
            analyzer = IndexEnhancementAnalyzer(
                db_manager=db,
                benchmark_code='000300.SH',
                execution_logger=exec_logger
            )

            enhancement_result = analyzer.analyze(
                portfolio_weights=portfolio_weights,
                start_date='2023-01-01',
                end_date='2023-12-31',
                portfolio_id='test_enhancement'
            )
            print("   ✓ 指数增强分析完成")
        except Exception as e:
            import traceback
            print(f"   ✗ 指数增强分析失败: {e}")
            traceback.print_exc()
    elif used_mock_data:
        print("\n[指数增强分析]")
        print("   ⚠ 使用模拟数据时跳过（避免向数据库写入模拟成分股数据）")

    # 10. 显示历史最佳记录
    if db is not None:
        print("\n[历史最佳记录]")
        best_records = db.get_best_records()
        if not best_records.empty:
            print("   最佳指标记录:")
            for _, row in best_records.iterrows():
                print(f"      {row['category']}.{row['metric_name']}: {row['best_value']:.4f}")
        else:
            print("   暂无最佳记录")

        # 11. 显示最近执行日志
        print("\n[最近执行日志]")
        logs = db.get_execution_logs(limit=5)
        if not logs.empty:
            for _, row in logs.iterrows():
                factor = row.get('factor_name', 'N/A')
                ic = f"{row['ic_mean']:.4f}" if pd.notna(row.get('ic_mean')) else 'N/A'
                sharpe = f"{row['sharpe']:.4f}" if pd.notna(row.get('sharpe')) else 'N/A'
                print(f"      [{row['execution_type']}] {factor}: IC={ic}, Sharpe={sharpe}")
        else:
            print("   暂无执行日志")

    # 12. 估值分析
    print("\n[估值分析]")
    try:
        if db is not None and not used_mock_data:
            valuation_analyzer = ValuationAnalyzer(db)
        else:
            print("   (使用模拟数据，仅展示价格信息)")
            valuation_analyzer = None

        # 获取股票列表（取前10只作为示例）
        stock_list = data_loader.get_stock_list()
        if not stock_list.empty:
            sample_stocks = stock_list['stock_code'].head(10).tolist()

            for stock_code in sample_stocks:
                try:
                    if valuation_analyzer is not None:
                        result = valuation_analyzer.analyze(stock_code)
                        summary = result.get('summary', {})
                        if summary.get('has_fair_value'):
                            print(f"   {stock_code}: 合理价值={summary['weighted_fair_value']:.2f}, "
                                  f"偏离={summary['deviation_pct']:+.1%}, 建议={summary['recommendation']}")
                        else:
                            print(f"   {stock_code}: 无法计算合理价值")
                    else:
                        # 简单的价格显示
                        price_data = data_loader.get_price_data(stock_code)
                        if not price_data.empty:
                            latest = price_data.iloc[-1]
                            print(f"   {stock_code}: 最新价={latest['close']:.2f}")
                except Exception as e:
                    print(f"   {stock_code}: 分析失败 - {e}")

            if valuation_analyzer is not None:
                print("   ✓ 估值分析完成，结果已保存")
            else:
                print("   ✓ 估值数据展示完成（模拟数据模式）")
    except Exception as e:
        print(f"   ✗ 估值分析失败: {e}")


def run_data_sync(db_path: str, account: str = None, password: str = None,
                  start_date: str = '20230101', end_date: str = ''):
    """运行数据同步"""
    try:
        from src.data.qmt_connector import QMTConnector
        from src.data.data_sync import DataSynchronizer
        from src.data.data_validator import DataValidator
    except ImportError as e:
        print(f"QMT模块不可用: {e}")
        return

    # end_date 为空时默认为当天
    if not end_date:
        end_date = pd.Timestamp.now().strftime('%Y%m%d')

    db = DatabaseManager(db_path)

    # 连接QMT
    print("正在连接QMT...")
    connector = QMTConnector(account=account, password=password)
    if not connector.is_connected():
        connector.connect()

    if not connector.is_connected():
        print("QMT连接失败")
        return

    print("QMT连接成功")

    # 同步数据
    print(f"\n开始同步数据 ({start_date} ~ {end_date})...")
    synchronizer = DataSynchronizer(connector, db)

    def progress_cb(stage, current, total, message):
        if total > 0:
            pct = current / total * 100
            print(f"  [{stage}] {pct:.1f}% ({current}/{total}) {message}")
        else:
            print(f"  [{stage}] {message}")

    result = synchronizer.sync_all(
        start_date=start_date,
        end_date=end_date,
        progress_callback=progress_cb
    )

    print(f"\n同步完成:")
    for key, val in result.items():
        print(f"  {key}: {val}")

    # 数据校验
    print(f"\n数据校验...")
    validator = DataValidator(db)
    report = validator.validate_and_report(start_date, end_date)
    print(report)


def run_data_validate(db_path: str, start_date: str = '20230101', end_date: str = ''):
    """运行数据校验"""
    from src.data.data_validator import DataValidator

    db = DatabaseManager(db_path)
    validator = DataValidator(db)

    if not end_date:
        end_date = pd.Timestamp.now().strftime('%Y%m%d')

    report = validator.validate_and_report(start_date, end_date)
    print(report)


def run_list_factors(db_path: str, category: str = None, source: str = None, keyword: str = None, detail: bool = False):
    """
    列出系统因子

    Parameters
    ----------
    db_path : str
        数据库路径
    category : str, optional
        按分类筛选
    source : str, optional
        按来源筛选 (worldquant/guotai/fundamental)
    keyword : str, optional
        关键词搜索
    detail : bool
        是否显示详细信息
    """
    from src.factors.categories import ALL_FACTOR_META, CATEGORY_NAMES, get_factor_full_info

    db = DatabaseManager(db_path)

    # 首先同步因子元数据到数据库
    db.sync_factor_registry(ALL_FACTOR_META)

    # 从数据库查询因子
    df = db.get_factor_registry(category=category, source=source, keyword=keyword)

    if df.empty:
        print("未找到匹配的因子")
        return

    print("\n" + "=" * 100)
    print("系统因子列表")
    print("=" * 100)

    # 显示统计信息
    summary = db.get_factor_registry_summary()
    print(f"\n总计: {summary['total']} 个因子")
    print("按来源分布:")
    for src, cnt in summary['by_source'].items():
        src_name = {'worldquant': 'WorldQuant 101', 'guotai': '国泰君安 191', 'fundamental': '基本面因子'}.get(src, src)
        print(f"  - {src_name}: {cnt} 个")
    print()

    # 显示因子列表
    if detail:
        # 详细模式
        for _, row in df.iterrows():
            print("-" * 100)
            print(f"因子ID: {row['factor_id']}")
            print(f"名称: {row['name']}")
            print(f"分类: {CATEGORY_NAMES.get(row['category'], row['category'])}")
            print(f"来源: {row['source']}")
            print(f"调用方法: {row['call_method']}")
            print(f"关键词: {row['keywords']}")
            print(f"描述: {row['description']}")
            print(f"输入参数: {row['input_params']}")
            print(f"输出参数: {row['output_params']}")
            print()
    else:
        # 简洁模式
        print(f"{'因子ID':<12} {'名称':<20} {'分类':<12} {'来源':<12} {'描述'}")
        print("-" * 100)
        for _, row in df.iterrows():
            category_name = CATEGORY_NAMES.get(row['category'], row['category'])
            desc = row['description'][:40] + '...' if len(row['description']) > 40 else row['description']
            print(f"{row['factor_id']:<12} {row['name']:<20} {category_name:<12} {row['source']:<12} {desc}")

    print("=" * 100)
    print(f"\n提示: 使用 --factor-detail <因子ID> 查看单个因子的详细信息")
    print("提示: 使用 --factor-category <分类> 按分类筛选")
    print("提示: 使用 --factor-source <来源> 按来源筛选 (worldquant/guotai/fundamental)")


def run_factor_detail(db_path: str, factor_id: str):
    """
    显示单个因子的详细信息

    Parameters
    ----------
    db_path : str
        数据库路径
    factor_id : str
        因子ID
    """
    from src.factors.categories import CATEGORY_NAMES

    db = DatabaseManager(db_path)

    # 从数据库查询因子详情
    info = db.get_factor_detail(factor_id)

    if not info:
        print(f"因子 {factor_id} 不存在")
        return

    print("\n" + "=" * 100)
    print(f"因子详情: {factor_id}")
    print("=" * 100)
    print(f"名称: {info['name']}")
    print(f"分类: {CATEGORY_NAMES.get(info['category'], info['category'])}")
    print(f"来源: {info['source']}")
    print(f"调用方法: {info['call_method']}")
    print(f"关键词: {info['keywords']}")
    print()
    print("描述:")
    print(f"  {info['description']}")
    print()
    print("输入参数:")
    print(f"  {info['input_params']}")
    print()
    print("输出参数:")
    print(f"  {info['output_params']}")
    print("=" * 100)


def run_quintile_backtest(args, db_path: str):
    """运行多因子分层回测V2"""
    # 日期格式转换: 支持 YYYYMMDD 和 YYYY-MM-DD 两种格式
    start_date = None
    end_date = None
    if args.start_date:
        s = args.start_date.replace('-', '')
        if len(s) == 8:
            start_date = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if args.end_date:
        e = args.end_date.replace('-', '')
        if len(e) == 8:
            end_date = f"{e[:4]}-{e[4:6]}-{e[6:]}"

    # 因子列表解析: 'WQ_001,GTJ_030' -> ['wq_001', 'gtj_030']
    specified_factors = None
    if args.factors:
        specified_factors = [f.strip().lower() for f in args.factors.split(',')]

    output_dir = args.output_dir or str(project_root / 'reports' / 'backtest' / 'quintile')
    engine = MultiFactorQuintileBacktestEngineV2(
        db_path=db_path,
        output_dir=output_dir,
        n_rounds=args.n_rounds,
        n_stocks=args.bt_n_stocks,
        seed=args.seed,
        # 时间段
        start_date=start_date,
        end_date=end_date,
        # 因子选择
        factor_mode=args.factor_mode,
        factor_per_category=args.factors_per_category,
        specified_factors=specified_factors,
        n_random_factors=args.n_factors,
        # 权重方法
        weight_method=args.weight_method,
        # 调仓策略
        rebalance_mode=args.rebalance_mode,
        rebalance_price=args.rebalance_price,
        hold_days=args.hold_days,
        calendar_freq=args.calendar_freq,
        calendar_n=args.calendar_n,
        # 风控配置
        enable_risk_control=args.enable_risk,
        stop_loss=args.stop_loss,
        take_profit=args.take_profit,
        portfolio_stop=args.portfolio_stop,
        max_position_per_stock=args.max_position,
        risk_action=args.risk_action,
    )
    engine.run_all_rounds()


def run_multi_factor_backtest(args, db_path: str):
    """运行多因子分批回测V1"""
    from pathlib import Path as P
    report_dir = str(P(db_path).parent.parent / 'reports' / 'backtest')

    # 日期格式转换: 支持 YYYYMMDD 和 YYYY-MM-DD 两种格式
    start_date = None
    end_date = None
    if args.start_date:
        s = args.start_date.replace('-', '')
        if len(s) == 8:
            start_date = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if args.end_date:
        e = args.end_date.replace('-', '')
        if len(e) == 8:
            end_date = f"{e[:4]}-{e[4:6]}-{e[6:]}"

    engine = MultiFactorBacktester(
        db_path=db_path,
        report_dir=report_dir,
        seed=args.seed,
        max_stocks=args.max_stocks,
        # 时间段
        start_date=start_date,
        end_date=end_date,
        # 调仓策略
        rebalance_mode=args.rebalance_mode,
        rebalance_price=args.rebalance_price,
        hold_days=args.hold_days,
        calendar_freq=args.calendar_freq,
        calendar_n=args.calendar_n,
    )
    engine.run_all()
    report_path = engine.generate_summary_report()
    if report_path:
        print(f"   综合报告已生成: {report_path}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='A股量化分析系统')
    
    # 创建子命令
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # 添加新的子命令
    from src.cli import (
        setup_strategy_parser, run_strategy_command,
        setup_backtest_parser, run_backtest_command,
        setup_result_parser, run_result_command,
        setup_pool_parser, run_pool_command,
    )
    from src.cli.config_cli import setup_config_parser, run_config_command
    from src.cli.data_cli import setup_data_parser, run_data_command
    from src.cli.factor_cli import setup_factor_parser, run_factor_command
    from src.cli.quantlab_cli import setup_quantlab_parser, run_quantlab_subcommand
    
    # config 子命令（配置管理）
    config_parser = subparsers.add_parser('config', help='配置管理（交互式/命令式）')
    setup_config_parser(config_parser)
    
    # data 子命令（数据管理）
    data_parser = subparsers.add_parser('data', help='数据管理（同步/校验/生成）')
    setup_data_parser(data_parser)
    
    # factor 子命令（因子管理）
    factor_parser = subparsers.add_parser('factor', help='因子管理（查询/注册/测试）')
    setup_factor_parser(factor_parser)
    
    # strategy 子命令
    strategy_parser = subparsers.add_parser('strategy', help='策略管理')
    setup_strategy_parser(strategy_parser)
    
    # backtest 子命令
    backtest_parser = subparsers.add_parser('backtest', help='运行回测')
    setup_backtest_parser(backtest_parser)
    
    # result 子命令
    result_parser = subparsers.add_parser('result', help='回测结果管理')
    setup_result_parser(result_parser)
    
    # pool 子命令
    pool_parser = subparsers.add_parser('pool', help='股票池管理')
    setup_pool_parser(pool_parser)

    # quantlab 子命令（Phase 6 新增：6 个子动作）
    setup_quantlab_parser(subparsers)
    
    # 原有参数（向后兼容）
    parser.add_argument('--sync', action='store_true', help='仅同步数据（不运行分析）')
    parser.add_argument('--validate', action='store_true', help='仅校验数据完整性')
    parser.add_argument('--generate-test-data', action='store_true', help='仅生成测试数据CSV文件')
    parser.add_argument('--start-date', default='20230101', help='数据起始日期 (YYYYMMDD)')
    parser.add_argument('--end-date', default='', help='数据结束日期 (YYYYMMDD)')
    parser.add_argument('--account', default='', help='QMT交易账号（默认从config/config.json读取）')
    parser.add_argument('--password', default='', help='QMT交易密码（默认从config/config.json读取）')
    parser.add_argument('--n-stocks', type=int, default=100, help='测试数据股票数量')
    parser.add_argument('--n-days', type=int, default=250, help='测试数据天数')
    parser.add_argument('--log-level', default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='日志级别 (默认INFO)')
    parser.add_argument('--no-log-file', action='store_true',
                        help='禁用日志文件输出（仅控制台）')

    # 因子注册表相关参数
    parser.add_argument('--list-factors', action='store_true', help='列出所有系统因子')
    parser.add_argument('--factor-category', default=None, help='按分类筛选因子')
    parser.add_argument('--factor-source', default=None, choices=['worldquant', 'guotai', 'fundamental'],
                        help='按来源筛选因子 (worldquant/guotai/fundamental)')
    parser.add_argument('--factor-keyword', default=None, help='按关键词搜索因子')
    parser.add_argument('--factor-detail', default=None, help='查看指定因子的详细信息')
    parser.add_argument('--factor-detail-mode', action='store_true', help='以详细模式显示因子列表')

    # 多因子回测参数
    parser.add_argument('--quintile-backtest', action='store_true',
                        help='运行多因子分层回测V2（推荐）')
    parser.add_argument('--multi-factor-backtest', action='store_true',
                        help='运行多因子分批回测V1')
    parser.add_argument('--n-rounds', type=int, default=20,
                        help='回测轮数 (默认20)')
    parser.add_argument('--bt-n-stocks', type=int, default=50,
                        help='回测分组股票数 (默认50)')
    parser.add_argument('--seed', type=int, default=None,
                        help='随机种子 (默认None)')
    parser.add_argument('--output-dir', default=None,
                        help='报告输出目录 (默认reports/backtest/quintile)')
    parser.add_argument('--max-stocks', type=int, default=500,
                        help='V1回测股票池上限 (默认500)')

    # V2 引擎参数 - 因子选择
    parser.add_argument('--factor-mode', default='category',
                        choices=['category', 'specified', 'random'],
                        help='因子选择模式 (默认category)')
    parser.add_argument('--factors-per-category', type=int, default=1,
                        help='每类因子选择数量 (默认1)')
    parser.add_argument('--factors', default=None,
                        help='指定因子，如 WQ_001,GTJ_030')
    parser.add_argument('--n-factors', type=int, default=4,
                        help='随机模式下的因子数量 (默认4)')

    # V2 引擎参数 - 权重方法
    parser.add_argument('--weight-method', default='risk_parity',
                        choices=['equal', 'risk_parity', 'ic_weighted', 'ir_weighted'],
                        help='因子权重方法 (默认risk_parity)')

    # V2 引擎参数 - 调仓策略
    parser.add_argument('--rebalance-mode', default='fixed_days',
                        choices=['fixed_days', 'calendar'],
                        help='调仓模式 (默认fixed_days)')
    parser.add_argument('--rebalance-price', default='close',
                        choices=['close', 'next_open'],
                        help='调仓价格类型 (默认close)')
    parser.add_argument('--hold-days', type=int, default=5,
                        help='固定持仓天数 (默认5)')
    parser.add_argument('--calendar-freq', default=None,
                        choices=['monthly', 'weekly', 'quarterly', 'yearly'],
                        help='日历调仓频率')
    parser.add_argument('--calendar-n', type=int, default=1,
                        help='日历调仓间隔 (默认1)')

    # V2 引擎参数 - 风控配置
    parser.add_argument('--enable-risk', action='store_true',
                        help='启用风控 (默认关闭)')
    parser.add_argument('--stop-loss', type=float, default=0.07,
                        help='个股止损比例 (默认0.07 = -7%%)')
    parser.add_argument('--take-profit', type=float, default=0.20,
                        help='个股止盈比例 (默认0.20 = +20%%)')
    parser.add_argument('--portfolio-stop', type=float, default=0.10,
                        help='组合止损比例 (默认0.10 = -10%%)')
    parser.add_argument('--max-position', type=float, default=0.10,
                        help='单股最大仓位 (默认0.10 = 10%%)')
    parser.add_argument('--risk-action', default='close',
                        choices=['close', 'reduce', 'halt'],
                        help='风控触发后的操作 (默认close)')

    args = parser.parse_args()

    # 无参数时显示帮助信息
    if args.command is None and not any([
        args.sync, args.validate, args.generate_test_data,
        args.list_factors, args.quintile_backtest, args.multi_factor_backtest,
    ]):
        parser.print_help()
        return

    # 处理子命令
    if args.command == 'config':
        run_config_command(args)
        return
    elif args.command == 'data':
        run_data_command(args)
        return
    elif args.command == 'factor':
        run_factor_command(args)
        return
    elif args.command == 'strategy':
        run_strategy_command(args)
        return
    elif args.command == 'backtest':
        run_backtest_command(args)
        return
    elif args.command == 'result':
        run_result_command(args)
        return
    elif args.command == 'pool':
        run_pool_command(args)
        return
    elif args.command == 'quantlab':
        run_quantlab_subcommand(args)
        return

    # 初始化日志（AQUANT_DATA_MODE 已删除，不再打印数据模式）
    import logging
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logger = setup_logger(
        level=log_level,
        console=True,
        log_file=None if args.no_log_file else 'aquant.log'
    )
    logger.info("=" * 60)
    logger.info("A股量化分析系统 v0.5.0 (数据分离版)")
    logger.info("=" * 60)
    logger.info(f"日志级别: {args.log_level}")
    if not args.no_log_file:
        from src.utils.logger import LOG_DIR
        logger.info(f"日志文件: {LOG_DIR}/aquant_*.log")
    logger.info("=" * 60)

    # 数据库路径
    db_path = str(project_root / DATABASE_CONFIG["path"])

    # 启动信息：显示数据库路径 + 最新交易日（飞书"## CLI 启动信息"要求）
    print(f"\n[系统启动信息]")
    print(f"  数据库: {db_path}")
    try:
        db_check = DatabaseManager(db_path)
        latest_date = db_check.get_data_summary().get('stock_daily', {}).get('end_date') or 'N/A'
        print(f"  最新交易日: {latest_date}")
    except Exception:
        print(f"  最新交易日: N/A (数据库未初始化)")
    print()

    # 启动检查：补全 strategy_best_perf（飞书"Task 11.6 启动检查"约定）
    try:
        from src.quantlab_adapters import ensure_best_perf_fresh
        stats = ensure_best_perf_fresh(db_path)
        if stats.get("missing_fixed") or stats.get("stale_rebuilt"):
            print(
                f"  [best_perf 启动检查] "
                f"missing_fixed={stats['missing_fixed']} "
                f"stale_rebuilt={stats['stale_rebuilt']}"
            )
    except Exception as e:
        # 数据库为空等情况下 ensure_best_perf_fresh 可能抛错，不影响启动
        logger.debug(f"ensure_best_perf_fresh 跳过: {e}")

    # 0. 因子注册表查询（优先处理，不需要数据模式）
    if args.list_factors:
        print("\n[因子注册表查询]")
        run_list_factors(
            db_path=db_path,
            category=args.factor_category,
            source=args.factor_source,
            keyword=args.factor_keyword,
            detail=args.factor_detail_mode
        )
        return

    if args.factor_detail:
        print(f"\n[因子详情查询: {args.factor_detail}]")
        run_factor_detail(db_path=db_path, factor_id=args.factor_detail)
        return

    # 多因子回测（优先于数据模式相关操作）
    if args.quintile_backtest:
        print("\n[多因子分层回测V2]")
        run_quintile_backtest(args, db_path)
        return

    if args.multi_factor_backtest:
        print("\n[多因子分批回测V1]")
        run_multi_factor_backtest(args, db_path)
        return

    # 1. 生成测试数据
    if args.generate_test_data:
        generate_test_data()
        return

    if args.sync:
        print("\n[数据同步模式]")
        # 命令行参数优先，为空时从配置文件读取
        from config.config import get_credentials
        creds = get_credentials('qmt')
        sync_account = args.account or creds.get('account', '')
        sync_password = args.password or creds.get('password', '')
        run_data_sync(
            db_path=db_path,
            account=sync_account or None,
            password=sync_password or None,
            start_date=args.start_date,
            end_date=args.end_date
        )
        return

    if args.validate:
        print("\n[数据校验模式]")
        run_data_validate(
            db_path=db_path,
            start_date=args.start_date,
            end_date=args.end_date
        )
        return

    # 加载并运行分析（AQUANT_DATA_MODE 已删除，仅数据库模式）
    print("\n[运行分析] 模式: 真实数据 (仅数据库)")
    db = DatabaseManager(db_path)
    summary = db.get_data_summary()
    if summary['stock_daily']['count'] == 0:
        print("\n   ✗ 数据库为空，无法运行分析!")
        print("   请先通过以下方式之一准备数据：")
        print("   1. 同步 QMT 数据: python main.py data sync")
        print("   2. 生成测试数据: python main.py data generate-test")
        return

    print(f"   ✓ 数据库数据: {summary['stock_daily']['count']} 条记录")
    run_analysis(db=db, data_loader=None, used_mock_data=False)

    print("\n" + "=" * 60)
    print("分析完成！")
    print("=" * 60)

    print(f"\n数据目录:")
    print(f"  数据库: {db_path}")

    print(f"\n提示: 运行 'streamlit run src/visualization/dashboard.py' 启动可视化界面")
    print("提示: 运行 'python main.py data generate-test' 生成模拟数据CSV")


if __name__ == "__main__":
    main()
