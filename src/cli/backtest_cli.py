"""
回测 CLI 模块

提供策略管理、回测执行、结果管理等功能。
"""

import argparse
import json
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd
from datetime import timedelta

# 导入引擎
from src.engine import BaseStrategy, StrategyRegistry, BacktestEngine
from src.engine.types import BacktestResult, TradeRecord, Direction
from src.risk import RiskController


def setup_strategy_parser(parser: argparse.ArgumentParser):
    """设置策略管理命令参数"""
    
    # 列出策略
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='列出所有可用策略'
    )
    
    # 查看策略详情
    parser.add_argument(
        '--show', '-s',
        metavar='STRATEGY_NAME',
        help='查看策略详情（显示策略类注释和参数说明）'
    )
    
    # 显示参数模式
    parser.add_argument(
        '--params',
        action='store_true',
        help='显示策略参数详细说明（与 --show 配合使用）'
    )


def run_strategy_command(args: argparse.Namespace):
    """执行策略管理命令"""
    
    # 1. 自动发现 v2 策略（SignalStrategy，最新版本）
    from src.quantlab_adapters import discover_v2_strategies, SignalStrategyRegistry
    discover_v2_strategies('src.strategies')
    
    # 2. 自动发现 v1 策略（BaseStrategy，旧版本兼容）
    StrategyRegistry.auto_discover('src.strategies')
    
    # 3. 列出所有策略（合并两个注册表，v2优先）
    if args.list:
        # 合并策略列表：v2策略（最新版本）优先覆盖v1
        all_strategies = {}
        # 先加v1
        for s in StrategyRegistry.list_strategies():
            all_strategies[s['name']] = s
        # 再加v2（v2会覆盖v1同名策略，因为是最新版本）
        for s in SignalStrategyRegistry.list_strategies():
            all_strategies[s['name']] = s
        
        strategies = sorted(all_strategies.values(), key=lambda x: x['name'])
        print("\n可用策略列表：")
        print("=" * 60)
        for s in strategies:
            print(f"  {s['name']:<20} {s['description'][:40]}")
        print("=" * 60)
        print(f"共 {len(strategies)} 个策略")
        print("\n使用 'python main.py strategy --list' 列出所有策略")
        print("使用 'python main.py strategy --show <策略名>' 查看详情")
        return
    
    # 4. 查看策略详情
    if args.show:
        # 优先查找v2策略
        strategy_class = SignalStrategyRegistry.get(args.show)
        is_v2 = True
        if strategy_class is None:
            # 再找v1策略
            strategy_class = StrategyRegistry.get(args.show)
            is_v2 = False
        
        if strategy_class is None:
            print(f"错误：未知策略 '{args.show}'")
            v1_available = [s['name'] for s in StrategyRegistry.list_strategies()]
            v2_available = [s['name'] for s in SignalStrategyRegistry.list_strategies()]
            all_available = list(set(v1_available + v2_available))
            print(f"可用策略: {', '.join(sorted(all_available))}")
            return
        
        # 获取策略文档字符串（类注释）
        docstring = strategy_class.__doc__ or "（无描述）"
        
        print(f"\n策略: {strategy_class.name or strategy_class.__name__}")
        print("=" * 60)
        print(f"版本类型: {'quantlab (最新版本)' if is_v2 else 'myquant (旧版本)'}")
        print("\n【策略说明】")
        print(docstring)
        
        # 显示参数
        if hasattr(strategy_class, 'get_param_schema'):
            # v1策略
            schema = strategy_class.get_param_schema()
            print("\n【参数说明】")
            print("-" * 40)
            if args.params:
                for param_name, param_info in schema.items():
                    print(f"  {param_name}:")
                    print(f"    类型: {param_info['type']}")
                    print(f"    默认值: {param_info['default']}")
                    print(f"    说明: {param_info['description']}")
                    if 'min' in param_info:
                        print(f"    范围: [{param_info['min']}, {param_info['max']}]")
            else:
                print("-" * 40)
                for name, value in strategy_class.default_params.items():
                    print(f"  {name}: {value}")
                print("\n使用 '--params' 查看详细参数说明")
        elif hasattr(strategy_class, 'default_params'):
            # v2策略有default_params
            print("\n【默认参数】")
            print("-" * 40)
            for name, value in strategy_class.default_params.items():
                print(f"  {name}: {value}")
        else:
            print("\n【无默认参数】")
        
        print("=" * 60)
        return
    
    # 无参数时显示提示信息
    print("\n策略管理命令")
    print("=" * 60)
    print("\n可用选项：")
    print("  --list, -l          列出所有可用策略")
    print("  --show <策略名>     查看策略详情（显示策略类注释和参数说明）")
    print("  --params            显示策略参数详细说明（与 --show 配合使用）")
    print("\n示例：")
    print("  python main.py strategy --list")
    print("  python main.py strategy --show BreakoutPullbackStrategy")
    print("  python main.py strategy --show BreakoutPullbackStrategy --params")
    print("=" * 60)


def setup_backtest_parser(parser: argparse.ArgumentParser):
    """设置回测命令参数"""
    
    # 策略选择（必需）
    parser.add_argument(
        '--strategy', '-s',
        required=True,
        help='策略名称（通过 strategy --list 查看可用策略）'
    )

    # 股票池（与 --stocks 互斥）
    parser.add_argument(
        '--pool',
        metavar='POOL_NAME',
        help='使用股票池（通过 pool --list 查看可用股票池）'
    )

    # 股票列表（与 --pool 互斥）
    parser.add_argument(
        '--stocks',
        metavar='CODES',
        help='股票代码列表，逗号分隔（如 000001.SZ,600000.SH）'
    )
    
    # 时间范围
    parser.add_argument(
        '--start-date',
        default='2024-01-01',
        help='回测开始日期'
    )
    
    parser.add_argument(
        '--end-date',
        default='2024-12-31',
        help='回测结束日期'
    )
    
    # 通用参数（所有策略都支持）
    parser.add_argument(
        '--initial-capital',
        type=float,
        default=1_000_000,
        help='初始资金'
    )
    
    parser.add_argument(
        '--stop-loss',
        type=float,
        default=None,
        help='止损比例（如0.07表示7%，不指定则使用策略默认值）'
    )
    
    parser.add_argument(
        '--take-profit',
        type=float,
        default=None,
        help='止盈比例（如0.20表示20%，0表示禁用，不指定则使用策略默认值）'
    )
    
    parser.add_argument(
        '--trailing-stop',
        type=float,
        default=None,
        help='ATR动态止盈倍数（如3表示价格从最高点回落超过3×ATR时卖出，0=禁用，不指定则使用策略默认值）'
    )
    
    parser.add_argument(
        '--max-holding-days',
        type=int,
        default=None,
        help='最大持仓天数（0表示禁用，不指定则使用策略默认值）'
    )
    
    parser.add_argument(
        '--execution-price',
        choices=['close', 'next_open'],
        default='close',
        help='订单执行价格：close=收盘价(默认), next_open=次日开盘价'
    )
    
    parser.add_argument(
        '--position-size',
        type=float,
        default=0.10,
        help='单次开仓资金比例'
    )
    
    parser.add_argument(
        '--max-positions',
        type=int,
        default=30,
        help='最大持仓数量（0表示不限制）'
    )
    
    parser.add_argument(
        '--commission-rate',
        type=float,
        default=0.0003,
        help='佣金费率'
    )
    
    parser.add_argument(
        '--slippage',
        type=float,
        default=0.0001,
        help='滑点比例'
    )
    
    # 风控参数
    parser.add_argument(
        '--enable-risk-control',
        action='store_true',
        help='启用风控'
    )
    
    parser.add_argument(
        '--portfolio-stop',
        type=float,
        default=0.10,
        help='组合止损比例'
    )
    
    # 市场过滤参数
    parser.add_argument(
        '--exclude-st',
        action='store_true',
        default=False,
        help='排除ST股（需要 stock_info 表有数据）'
    )
    
    parser.add_argument(
        '--exclude-new-stock',
        type=int,
        default=0,
        metavar='DAYS',
        help='排除上市不满N个交易日的股票（如 --exclude-new-stock 60，默认0不排除）'
    )
    
    parser.add_argument(
        '--exclude-limit',
        action='store_true',
        default=False,
        help='排除涨跌停股'
    )
    
    parser.add_argument(
        '--exclude-suspend',
        action='store_true',
        default=False,
        help='排除停牌股'
    )
    
    parser.add_argument(
        '--exclude-zero-vol',
        action='store_true',
        default=False,
        help='排除零成交量股'
    )
    
    # 输出参数
    parser.add_argument(
        '--output-dir',
        default='reports',
        help='报告输出目录'
    )
    
    parser.add_argument(
        '--name',
        default='',
        help='报告名称（默认自动生成）'
    )

    # 数据源统一从本地数据库读取

    # ===== Phase 4 新增：quantlab 引擎选择 =====
    parser.add_argument(
        '--engine',
        type=str,
        default='auto',
        choices=['auto', 'bar', 'event', 'vbt', 'tick', 'myquant'],
        help='回测引擎：auto（按策略名 _v2 自动选择）/ bar（quantlab BarEngine）/ '
             'event（quantlab EventEngine）/ vbt（quantlab VectorBTAdapter）/ '
             'tick（quantlab TickEngine）/ myquant（myquant BacktestEngine，已废弃）'
    )
    parser.add_argument(
        '--no-risk-check',
        action='store_true',
        help='禁用 A 股 RiskCheck（涨跌停/ST/T+1/新股/停牌）'
    )
    parser.add_argument(
        '--no-execution-cost',
        action='store_true',
        help='禁用佣金和滑点（仅用于研究对比）'
    )


def load_price_data(
    start_date: str,
    end_date: str,
    stock_codes: List[str] = None,
    db_path: str = None,
) -> pd.DataFrame:
    """
    从本地数据库加载价格数据

    Parameters
    ----------
    start_date : str
        开始日期
    end_date : str
        结束日期
    stock_codes : List[str], optional
        股票代码列表
    db_path : str, optional
        数据库路径

    Returns
    -------
    pd.DataFrame
        价格数据
    """
    from config.config import DATABASE_CONFIG
    from src.data.database import DatabaseManager

    if db_path is None:
        db_path = DATABASE_CONFIG.get("path", str(Path(__file__).parent.parent.parent / 'data' / 'aquant.db'))

    db = DatabaseManager(db_path)
    return db.get_stock_daily(stock_codes=stock_codes, start_date=start_date, end_date=end_date)


def _resolve_engine_choice(strategy_name: str, requested: str) -> str:
    """
    根据策略和用户选择，决定实际使用的引擎。
    
    版本规则：
    - 版本号 v1/v2/v3... 只表示策略改造次数，与使用哪个引擎无关
    - 默认auto模式：如果SignalStrategyRegistry中存在该策略（即有最新版本的v2+策略），
      则使用quantlab引擎；否则使用myquant引擎运行v1策略
    - 用户显式指定引擎时尊重用户选择
    返回 'myquant' | 'bar' | 'event' | 'vbt' | 'tick'
    """
    from src.quantlab_adapters import SignalStrategyRegistry
    
    if requested == "auto":
        # 优先查找SignalStrategy（最新版本），如果存在则走quantlab
        if SignalStrategyRegistry.get(strategy_name) is not None:
            return "vbt"  # quantlab VectorBTAdapter（默认，用户之前用的是vbt）
        # 否则走myquant（兼容v1策略）
        return "myquant"
    return requested


def _is_quantlab_strategy(strategy_name: str) -> bool:
    """判断策略是否是quantlab SignalStrategy（即是否有最新版本）。"""
    from src.quantlab_adapters import SignalStrategyRegistry
    return SignalStrategyRegistry.get(strategy_name) is not None


def run_backtest_command(args: argparse.Namespace):
    """执行回测命令"""

    strategy_name = args.strategy

    # 0. 按需加载目标策略（只加载用户指定的那个，不加载全部）
    from src.quantlab_adapters import discover_v2_strategies, SignalStrategyRegistry
    discover_v2_strategies("src.strategies", strategy_name=strategy_name)

    # 1. 也检查v1注册表（只判断是否存在，不全量discover；v1的auto_discover在_run_myquant_backtest中按需调用）
    # 先尝试从v2注册表获取
    is_v2 = SignalStrategyRegistry.get(strategy_name) is not None

    # 2. 决定引擎
    engine_choice = _resolve_engine_choice(strategy_name, args.engine)

    # 3. 分发
    if engine_choice == "myquant" and not is_v2:
        # 走 myquant 自研引擎（兼容 v1 策略）
        StrategyRegistry.auto_discover("src.strategies")
        if StrategyRegistry.get(strategy_name) is None:
            print(f"错误：未知策略 '{strategy_name}'")
            # 需要列出所有可用策略时才全量discover
            discover_v2_strategies("src.strategies")
            StrategyRegistry.auto_discover("src.strategies")
            v1_available = [s['name'] for s in StrategyRegistry.list_strategies()]
            v2_available = [s['name'] for s in SignalStrategyRegistry.list_strategies()]
            all_available = list(set(v1_available + v2_available))
            print(f"可用策略: {', '.join(sorted(all_available))}")
            return
        return _run_myquant_backtest(args)
    else:
        # 走 quantlab 引擎
        if not is_v2:
            # 用户显式选 quantlab，但策略只有v1版本 → 提示并自动 fallback
            print(
                f"[警告] 策略 '{strategy_name}' 只有v1 (BaseStrategy) 版本，"
                f"无法在 quantlab 引擎上运行。已自动切回 myquant BacktestEngine。"
            )
            StrategyRegistry.auto_discover("src.strategies")
            return _run_myquant_backtest(args)
        return _run_quantlab_backtest(args, engine_choice)


def _run_myquant_backtest(args: argparse.Namespace):
    """原有 myquant BacktestEngine 路径（v1 策略 / 兼容保留）。"""
    # 1. 自动发现策略
    StrategyRegistry.auto_discover('src.strategies')

    # 2. 获取策略类
    strategy_class = StrategyRegistry.get(args.strategy)
    if strategy_class is None:
        print(f"错误：未知策略 '{args.strategy}'")
        available = [s['name'] for s in StrategyRegistry.list_strategies()]
        print(f"可用策略: {', '.join(available)}")
        return
    
    # 3. 获取策略参数模式，确定需要的预热期
    param_schema = strategy_class.get_param_schema()
    
    # 计算预热期长度（根据策略需要的最大回看窗口）
    warmup_days = 0
    if 'consolidation_window' in param_schema:
        warmup_days = max(warmup_days, param_schema['consolidation_window'].get('default', 20))
    warmup_days = max(warmup_days, 20)  # 最小20天
    
    # 4. 构建策略参数
    # 根据持仓上限自动调整单只仓位（最大总仓位98%，留2%缓冲）
    max_positions = args.max_positions
    position_size = args.position_size
    if max_positions > 0:
        # 自动计算：总仓位98% / 持仓上限
        auto_position_size = 0.98 / max_positions
        # 如果用户未指定position_size或自动值更小，使用自动值
        if args.position_size == 0.10:  # 默认值
            position_size = auto_position_size
            print(f"  自动调整单只仓位: {position_size:.4f} (98% / {max_positions}只)")
        else:
            # 用户指定了position_size，检查是否合理
            total_usage = position_size * max_positions
            if total_usage > 0.98:
                print(f"  警告: 单只仓位{position_size:.2%} × 持仓上限{max_positions} = {total_usage:.2%} > 98%")
                print(f"  已自动调整为 {auto_position_size:.4f}")
                position_size = auto_position_size
    
    # 5. 创建策略实例
    # 只传递用户显式指定的参数，未指定的使用策略 default_params
    strategy_params = {
        'position_size': position_size,
        'max_positions': max_positions,
        'commission_rate': args.commission_rate,
        'slippage': args.slippage,
        'db_path': _get_db_path(),  # 保持兼容
    }
    # 用户显式指定的出场参数才覆盖策略默认值
    if args.stop_loss is not None:
        strategy_params['stop_loss'] = args.stop_loss
    if args.take_profit is not None:
        strategy_params['take_profit'] = args.take_profit
    if args.trailing_stop is not None:
        strategy_params['trailing_stop'] = args.trailing_stop
    if args.max_holding_days is not None:
        strategy_params['max_holding_days'] = args.max_holding_days

    strategy = strategy_class(**strategy_params)

    # 6. 创建引擎（先不注入 stock_info_provider，后面再设置）
    risk_controller = None
    if args.enable_risk_control:
        risk_controller = RiskController(
            portfolio_stop=args.portfolio_stop,
        )

    # 构建市场过滤配置
    market_filter = {}
    if args.exclude_st:
        market_filter['exclude_st'] = True
    if args.exclude_new_stock > 0:
        market_filter['exclude_new_stock'] = args.exclude_new_stock
    if args.exclude_limit:
        market_filter['exclude_limit'] = True
    if args.exclude_suspend:
        market_filter['exclude_suspend'] = True
    if args.exclude_zero_vol:
        market_filter['exclude_zero_vol'] = True

    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=args.initial_capital,
        risk_controller=risk_controller,
        execution_price=args.execution_price,
        market_filter=market_filter,
    )

    # 7. 确定股票范围
    stock_codes = None
    pool_name = None

    if args.pool and args.stocks:
        print("错误：--pool 和 --stocks 不能同时使用")
        return

    if args.pool:
        # 从本地数据库获取股票池
        from src.data.database import DatabaseManager
        db = DatabaseManager(_get_db_path())
        stock_codes = db.get_stock_pool_members(args.pool)

        if not stock_codes:
            print(f"错误：股票池 '{args.pool}' 不存在或为空")
            return
        pool_name = args.pool

    if args.stocks:
        stock_codes = [s.strip() for s in args.stocks.split(',')]

    # 8. 加载数据（含预热期）
    start_dt = pd.Timestamp(args.start_date)
    warmup_start = (start_dt - timedelta(days=int(warmup_days * 1.5 + 10))).strftime('%Y-%m-%d')
    
    print(f"数据加载：")
    print(f"  预热期: {warmup_start} ~ {args.start_date} (约{warmup_days}个交易日)")
    print(f"  回测期: {args.start_date} ~ {args.end_date}")
    if pool_name:
        print(f"  股票池: {pool_name} ({len(stock_codes)} 只)")
    elif stock_codes:
        print(f"  股票列表: {len(stock_codes)} 只")
    
    # 加载完整数据（预热期+回测期，从本地数据库）
    full_data = load_price_data(warmup_start, args.end_date, stock_codes=stock_codes)
    
    # 分离预热期和回测期数据
    warmup_data = full_data[full_data.index.get_level_values('trade_date') < args.start_date]
    price_data = full_data[full_data.index.get_level_values('trade_date') >= args.start_date]
    
    print(f"  加载完成: {len(full_data)} 条记录")

    # 8. 设置 stock_info_provider（从本地数据库）
    from src.data.stock_info_provider import DatabaseStockInfoProvider
    engine._stock_info_provider = DatabaseStockInfoProvider(_get_db_path())

    # 9. 运行回测
    print(f"\n开始回测...")
    result = engine.run(price_data, warmup_data)
    
    # 9. 先记录执行日志，获取 log_id
    from src.data.database import DatabaseManager
    db = DatabaseManager(_get_db_path())
    
    perf = result.performance
    log_id = db.log_execution(
        execution_type='backtest',
        factor_name=strategy_class.name or args.strategy,
        start_date=args.start_date,
        end_date=args.end_date,
        n_stocks=len(stock_codes) if stock_codes else 0,
        total_return=result.total_return,
        annual_return=perf.get('annual_return', 0),
        sharpe_ratio=perf.get('sharpe_ratio', 0),
        max_drawdown=perf.get('max_drawdown', 0),
        win_rate=perf.get('win_rate', 0),
        calmar_ratio=perf.get('calmar_ratio', 0),
        volatility=perf.get('annual_volatility', 0),
        params_json=json.dumps(strategy_params)
    )
    
    # 10. 保存结果（使用 log_id 命名目录）
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if args.name:
        report_name = args.name
    else:
        report_name = f"backtest_{log_id:04d}_{args.start_date}_{args.end_date}"
    result_dir = output_dir / report_name
    result_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存绩效
    with open(result_dir / 'performance.json', 'w', encoding='utf-8') as f:
        json.dump({
            'log_id': log_id,
            'strategy_name': result.strategy_name,
            'start_date': result.start_date,
            'end_date': result.end_date,
            'initial_capital': result.initial_capital,
            'final_value': result.final_value,
            'total_return': result.total_return,
            **result.performance,
        }, f, indent=2, ensure_ascii=False)
    
    # 保存交易记录
    trades_data = [
        {
            'date': t.date.strftime('%Y-%m-%d'),
            'stock_code': t.stock_code,
            'direction': t.direction.name,
            'action': t.action,
            'price': t.price,
            'quantity': t.quantity,
            'commission': t.commission,
            'slippage': t.slippage,
            'pnl': t.pnl,
            'reason': t.reason,
        }
        for t in result.trades
    ]
    with open(result_dir / 'trades.json', 'w', encoding='utf-8') as f:
        json.dump(trades_data, f, indent=2, ensure_ascii=False)
    
    # 保存每日快照
    snapshots_data = [
        {
            'date': s.date.strftime('%Y-%m-%d'),
            'cash': s.cash,
            'frozen_cash': s.frozen_cash,
            'position_value': s.position_value,
            'total_value': s.total_value,
            'n_positions': s.n_positions,
            'daily_pnl': s.daily_pnl,
            'daily_return': s.daily_return,
            'drawdown': s.drawdown,
            'max_drawdown': s.max_drawdown,
        }
        for s in result.daily_snapshots
    ]
    with open(result_dir / 'snapshots.json', 'w', encoding='utf-8') as f:
        json.dump(snapshots_data, f, indent=2, ensure_ascii=False)
    
    # 保存K线数据（只保存有交易的股票）
    traded_stocks = set(t.stock_code for t in result.trades)
    if traded_stocks and price_data is not None:
        kline_data = {}
        for stock_code in traded_stocks:
            try:
                if isinstance(price_data.index, pd.MultiIndex):
                    stock_kline = price_data.xs(stock_code, level='stock_code')
                else:
                    stock_kline = price_data[price_data['stock_code'] == stock_code]
                
                # 转换为字典列表
                kline_data[stock_code] = [
                    {
                        'date': idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx),
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row.get('volume', 0)),
                    }
                    for idx, row in stock_kline.iterrows()
                ]
            except Exception:
                continue
        
        with open(result_dir / 'klines.json', 'w', encoding='utf-8') as f:
            json.dump(kline_data, f, ensure_ascii=False)
    
    # 生成 HTML 报告
    from src.report import generate_html_report
    try:
        html_path = generate_html_report(result_dir)
        print(f"\n  HTML报告: {html_path}")
    except Exception as e:
        print(f"\n  HTML报告生成失败: {e}")
    
    print(f"\n回测完成！")
    print(f"  日志ID: {log_id}")
    print(f"  报告目录: {result_dir}")
    print(f"\n绩效摘要：")
    print(f"  总收益率: {result.total_return:.2%}")
    print(f"  年化收益: {result.performance.get('annual_return', 0):.2%}")
    print(f"  夏普比率: {result.performance.get('sharpe_ratio', 0):.2f}")
    print(f"  最大回撤: {result.performance.get('max_drawdown', 0):.2%}")
    print(f"  交易次数: {len(result.trades)}")


# ============ quantlab 引擎路径（Phase 4 新增） ============


def _build_quantlab_engine(engine_choice: str, strategy, initial_capital: float):
    """
    构造 quantlab 引擎实例。

    engine_choice: 'bar' | 'event' | 'vbt' | 'tick'
    """
    from src.quantlab.execution import (
        PercentageCommission,
        PercentageSlippage,
    )
    from src.quantlab.portfolio_construction.top_n import TopN

    from src.quantlab_extras import (
        build_ashare_risk_manager,
        build_ashare_execution,
    )

    # 1) 选 portfolio_constructor：默认 TopN(30) 来自策略 default_params
    top_n = int(strategy.params.get("top_n", 30) if hasattr(strategy, "params") else 30)
    # 退路：v2 策略常见的 top_n_* 命名
    if top_n == 30:
        for key in ("n_positions", "top_pct", "max_positions"):
            if key in getattr(strategy, "params", {}):
                v = strategy.params.get(key)
                if isinstance(v, int) and v > 0 and v < 1000:
                    top_n = v
                    break
    constructor = TopN(n=top_n)

    # 2) 选 execution
    execution = build_ashare_execution(
        commission_rate=0.00025,
        slippage_rate=0.0001,
        lot_size=100,
    )

    if engine_choice == "bar":
        from src.quantlab.engine import BarEngine
        # BarEngine 接受独立的 commission/slippage 模型
        return BarEngine(
            strategy=strategy,
            portfolio_constructor=constructor,
            execution_model=execution,
            commission_model=PercentageCommission(rate=0.00025),
            slippage_model=PercentageSlippage(rate=0.0001),
            initial_cash=initial_capital,
        )

    if engine_choice == "event":
        from src.quantlab.event_engine import EventEngine
        return EventEngine(
            strategy=strategy,
            portfolio_constructor=constructor,
            execution_model=execution,
            commission_model=PercentageCommission(rate=0.00025),
            slippage_model=PercentageSlippage(rate=0.0001),
            initial_cash=initial_capital,
        )

    if engine_choice == "vbt":
        from src.quantlab.adapters.vectorbt_adapter import VectorBTAdapter
        return VectorBTAdapter(
            constructor=constructor,
            fees=0.00025,
            slippage=0.0001,
            init_cash=initial_capital,
        )

    if engine_choice == "tick":
        from src.quantlab.engine.tick_engine import TickEngine
        return TickEngine(
            strategy=strategy,
            initial_cash=initial_capital,
        )

    raise ValueError(f"未知引擎: {engine_choice}")


def _run_quantlab_backtest(args: argparse.Namespace, engine_choice: str):
    """
    quantlab 引擎回测路径（Phase 4 新增）。

    流程：
        1) 加载 v2 策略（SignalStrategy）
        2) from_quantlab_db 读数据 → Dict[symbol, DataFrame]
        3) 构造 quantlab 引擎
        4) engine.run() → BacktestResult (quantlab)
        5) to_myquant_result 转换 → myquant BacktestResult
        6) 写库 + HTML 报告（同 v1 路径）
    """
    from src.quantlab_adapters import (
        from_quantlab_db,
        from_etf_db,
        from_index_db,
        from_mixed_db,
        to_myquant_result,
        SignalStrategyRegistry,
    )
    from src.quantlab_extras import build_ashare_risk_manager
    from src.data.database import DatabaseManager

    # 统一创建一个 DatabaseManager 实例复用
    db = DatabaseManager(_get_db_path())

    # 1) 取策略类
    strategy_class = SignalStrategyRegistry.get(args.strategy)
    if strategy_class is None:
        print(f"错误：未知 v2 策略 '{args.strategy}'")
        print(
            "可用 v2 策略:",
            ", ".join(s["name"] for s in SignalStrategyRegistry.list_strategies()),
        )
        return

    # 2) 构造策略实例
    strategy = strategy_class()
    # 读取策略声明的资产类型（默认 stock，向后兼容现有策略）
    asset_class = getattr(strategy, "asset_class", "stock")

    # 3) 解析股票范围
    stock_codes: Optional[list] = None
    pool_name: Optional[str] = None

    if args.pool and args.stocks:
        print("错误：--pool 和 --stocks 不能同时使用")
        return

    if args.pool:
        stock_codes = db.get_stock_pool_members(args.pool)
        if not stock_codes:
            print(f"错误：股票池 '{args.pool}' 不存在或为空")
            return
        pool_name = args.pool

    if args.stocks:
        stock_codes = [s.strip() for s in args.stocks.split(",")]

    # 4) 回测前数据完整性检查（仅对 stock 资产类型执行 stock_daily 检查）
    if asset_class == "stock":
        from src.data.inspector import DataInspector
        inspector = DataInspector(db)
        inspect_report = inspector.inspect(
            start_date=args.start_date,
            end_date=args.end_date,
            data_types=['stock_daily'],
        )
        for dtype, detail in inspect_report.items():
            if detail.get('status') == 'warning':
                missing_codes = list(detail.get('details', {}).keys())
                if len(missing_codes) > 0:
                    print(f"[数据检查] {dtype}: {len(missing_codes)} 只股票数据缺失超过10%")
                    if len(missing_codes) <= 10:
                        print(f"  缺失股票: {', '.join(missing_codes)}")
                    else:
                        print(f"  缺失股票(前10): {', '.join(missing_codes[:10])}...")
                    print(f"  建议: 运行 python main.py data sync 补同步")

    # 5) 加载数据（含预热期，与 v1 对齐）—— 按策略 asset_class 路由
    from datetime import timedelta
    import time

    warmup_days = 60
    start_dt = pd.Timestamp(args.start_date)
    warmup_start = (start_dt - timedelta(days=int(warmup_days * 1.5 + 10))).strftime("%Y-%m-%d")

    print(f"[quantlab/{engine_choice}] 数据加载（asset_class={asset_class}）：")
    print(f"  预热期: {warmup_start} ~ {args.start_date}")
    print(f"  回测期: {args.start_date} ~ {args.end_date}")
    if pool_name:
        print(f"  股票池: {pool_name} ({len(stock_codes)} 只)")
    elif stock_codes:
        print(f"  标的列表: {len(stock_codes)} 只")

    t0 = time.time()
    if asset_class == "etf":
        # ETF 数据加载：从 t_etf_daily + t_etf_info 读取
        data = from_etf_db(
            db_path=_get_db_path(),
            start_date=warmup_start,
            end_date=args.end_date,
            etf_codes=stock_codes,
            db=db,
        )
    elif asset_class == "index":
        # 指数数据加载：从 t_index_daily + t_index_info 读取
        data = from_index_db(
            db_path=_get_db_path(),
            start_date=warmup_start,
            end_date=args.end_date,
            index_codes=stock_codes,
            db=db,
        )
    elif asset_class == "mixed":
        # 多资产混合加载（为两层策略搭路，需要策略提供更具体的 codes）
        # 当前简化处理：mixed 模式下 --stocks 同时传给 etf/stock/index
        # 未来两层策略可自行扩展解析逻辑
        data = from_mixed_db(
            db_path=_get_db_path(),
            start_date=warmup_start,
            end_date=args.end_date,
            etf_codes=stock_codes,
            stock_codes=stock_codes,
            index_codes=stock_codes,
            db=db,
        )
    else:
        # 默认 stock：个股数据加载（保持向后兼容）
        data = from_quantlab_db(
            db_path=_get_db_path(),
            start_date=warmup_start,
            end_date=args.end_date,
            stock_codes=stock_codes,
            db=db,
        )
    print(f"  加载完成: {len(data)} 个 symbol, 耗时 {time.time() - t0:.1f}s")

    if not data:
        print("错误：未加载到任何数据，请检查日期范围与股票池")
        return

    # 对齐所有 symbol 到统一交易日历（不同股票上市时间/停牌不同，长度可能不一致）
    all_indices = [df.index for df in data.values()]
    common_index = all_indices[0]
    for idx in all_indices[1:]:
        common_index = common_index.union(idx)
    common_index = common_index.sort_values()
    data = {
        sym: df.reindex(common_index) for sym, df in data.items()
    }

    # 5) 构造引擎
    engine = _build_quantlab_engine(
        engine_choice=engine_choice,
        strategy=strategy,
        initial_capital=args.initial_capital,
    )

    # 6) 跑回测
    print(f"\n开始回测 [引擎={engine_choice}, 策略={args.strategy}]...")
    t0 = time.time()
    ql_result = engine.run(strategy=strategy, data=data, params=strategy.params)
    elapsed = time.time() - t0
    print(f"  回测耗时: {elapsed:.1f}s")
    if hasattr(ql_result, "error") and ql_result.error:
        print(f"[错误] {ql_result.error}")
        return

    # 7) 转换结果
    result = to_myquant_result(
        ql_result,
        strategy_name=strategy_class.name or args.strategy,
        initial_capital=args.initial_capital,
    )

    # 8) 写库 + 报告（与 v1 路径一致的输出格式）
    perf = result.performance
    log_id = db.log_execution(
        execution_type=f"backtest_quantlab_{engine_choice}",
        factor_name=strategy_class.name or args.strategy,
        start_date=args.start_date,
        end_date=args.end_date,
        n_stocks=len(stock_codes) if stock_codes else 0,
        total_return=result.total_return,
        annual_return=perf.get("annual_return", 0),
        sharpe_ratio=perf.get("sharpe_ratio", 0),
        max_drawdown=perf.get("max_drawdown", 0),
        win_rate=perf.get("win_rate", 0),
        calmar_ratio=0,
        volatility=perf.get("annual_volatility", 0),
        params_json=json.dumps({"engine": engine_choice, **strategy.params}),
    )

    # 9) 保存报告目录
    output_dir = Path(args.output_dir) / "quantlab"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.name:
        report_name = args.name
    else:
        report_name = f"quantlab_{engine_choice}_{log_id:04d}_{args.start_date}_{args.end_date}"
    result_dir = output_dir / report_name
    result_dir.mkdir(parents=True, exist_ok=True)

    with open(result_dir / "performance.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "log_id": log_id,
                "engine": engine_choice,
                "strategy_name": result.strategy_name,
                "start_date": result.start_date,
                "end_date": result.end_date,
                "initial_capital": result.initial_capital,
                "final_value": result.final_value,
                "total_return": result.total_return,
                **result.performance,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    trades_data = [
        {
            "date": t.date.strftime("%Y-%m-%d"),
            "stock_code": t.stock_code,
            "direction": t.direction.name,
            "action": t.action,
            "price": t.price,
            "quantity": t.quantity,
            "pnl": t.pnl,
            "reason": t.reason,
        }
        for t in result.trades
    ]
    with open(result_dir / "trades.json", "w", encoding="utf-8") as f:
        json.dump(trades_data, f, indent=2, ensure_ascii=False)

    snapshots_data = []
    for s in result.daily_snapshots:
        # 处理NaT日期（无效快照）
        date_val = s.date
        if pd.isna(date_val):
            continue
        date_str = date_val.strftime("%Y-%m-%d") if hasattr(date_val, 'strftime') else str(date_val)
        snapshots_data.append({
            "date": date_str,
            "cash": s.cash,
            "position_value": s.position_value,
            "total_value": s.total_value,
            "n_positions": s.n_positions,
            "daily_pnl": s.daily_pnl,
            "daily_return": s.daily_return,
            "drawdown": s.drawdown,
            "max_drawdown": s.max_drawdown,
        })
    with open(result_dir / "snapshots.json", "w", encoding="utf-8") as f:
        json.dump(snapshots_data, f, indent=2, ensure_ascii=False)

    # HTML 报告（v1 路径的同款）
    from src.report import generate_html_report
    try:
        html_path = generate_html_report(result_dir)
        print(f"  HTML报告: {html_path}")
    except Exception as e:
        print(f"  HTML报告生成失败: {e}")

    print(f"\n[quantlab] 回测完成！")
    print(f"  引擎: {engine_choice}")
    print(f"  日志ID: {log_id}")
    print(f"  报告目录: {result_dir}")
    print(f"\n绩效摘要：")
    print(f"  总收益率: {result.total_return:.2%}")
    print(f"  年化收益: {result.performance.get('annual_return', 0):.2%}")
    print(f"  夏普比率: {result.performance.get('sharpe_ratio', 0):.2f}")
    print(f"  最大回撤: {result.performance.get('max_drawdown', 0):.2%}")
    print(f"  交易次数: {len(result.trades)}")


def setup_result_parser(parser: argparse.ArgumentParser):
    """设置回测结果管理命令参数"""
    
    # 列出结果
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='列出已有回测结果'
    )
    
    # 查看结果
    parser.add_argument(
        '--show',
        metavar='RESULT_PATH',
        help='查看回测结果摘要'
    )
    
    # 查看指定日期详情
    parser.add_argument(
        '--date',
        help='查看指定日期的详情（与 --show 配合使用）'
    )
    
    # 详情类型
    parser.add_argument(
        '--detail',
        choices=['cashflow', 'positions', 'trades', 'all'],
        default='all',
        help='详情类型（与 --date 配合使用）'
    )
    
    # 导出
    parser.add_argument(
        '--export',
        metavar='RESULT_PATH',
        help='导出回测结果'
    )
    
    parser.add_argument(
        '--output', '-o',
        help='导出文件路径'
    )
    
    # 删除
    parser.add_argument(
        '--delete',
        metavar='RESULT_PATH',
        help='删除回测结果'
    )
    
    # 生成 HTML 报告
    parser.add_argument(
        '--html',
        metavar='RESULT_PATH',
        help='生成 HTML 报告'
    )


def load_backtest_result(result_path: Path) -> Optional[BacktestResult]:
    """加载回测结果"""
    
    perf_file = result_path / 'performance.json'
    trades_file = result_path / 'trades.json'
    
    if not perf_file.exists():
        return None
    
    with open(perf_file, 'r', encoding='utf-8') as f:
        perf = json.load(f)
    
    trades = []
    if trades_file.exists():
        with open(trades_file, 'r', encoding='utf-8') as f:
            trades_data = json.load(f)
            for t in trades_data:
                trades.append(TradeRecord(
                    date=pd.Timestamp(t['date']),
                    stock_code=t['stock_code'],
                    direction=Direction[t['direction']],
                    action=t['action'],
                    price=t['price'],
                    quantity=t['quantity'],
                    commission=t.get('commission', 0),
                    slippage=t.get('slippage', 0),
                    pnl=t.get('pnl', 0),
                    reason=t.get('reason', ''),
                ))
    
    return BacktestResult(
        strategy_name=perf.get('strategy_name', 'unknown'),
        start_date=perf.get('start_date', ''),
        end_date=perf.get('end_date', ''),
        initial_capital=perf.get('initial_capital', 0),
        final_value=perf.get('final_value', 0),
        total_return=perf.get('total_return', 0),
        daily_snapshots=[],  # 简化加载
        trades=trades,
        performance=perf,
    )


def run_result_command(args: argparse.Namespace):
    """执行回测结果管理命令"""
    
    reports_dir = Path('reports')
    
    # 1. 列出已有回测结果
    if args.list:
        if not reports_dir.exists():
            print("暂无回测结果")
            return
        
        results = []
        for result_dir in reports_dir.rglob('*'):
            if result_dir.is_dir():
                # 查找绩效文件
                perf_file = result_dir / 'performance.json'
                if perf_file.exists():
                    with open(perf_file, 'r', encoding='utf-8') as f:
                        perf = json.load(f)
                    results.append({
                        'path': str(result_dir),
                        'strategy': perf.get('strategy_name', 'unknown'),
                        'start_date': perf.get('start_date', ''),
                        'end_date': perf.get('end_date', ''),
                        'total_return': perf.get('total_return', 0),
                        'sharpe': perf.get('sharpe_ratio', 0),
                        'max_dd': perf.get('max_drawdown', 0),
                    })
        
        if not results:
            print("暂无回测结果")
            return
        
        print("\n已有回测结果：")
        print("=" * 100)
        print(f"{'策略':<20} {'回测区间':<22} {'总收益':>10} {'夏普':>8} {'最大回撤':>10}")
        print("-" * 100)
        for r in sorted(results, key=lambda x: x['start_date'], reverse=True):
            print(f"{r['strategy']:<20} {r['start_date']} ~ {r['end_date']:<10} "
                  f"{r['total_return']:>9.2%} {r['sharpe']:>8.2f} {r['max_dd']:>9.2%}")
        print("=" * 100)
        print(f"共 {len(results)} 条记录")
        print("\n使用 'python main.py result --show <路径>' 查看详情")
        return
    
    # 2. 查看回测结果详情
    if args.show:
        result_path = Path(args.show)
        if not result_path.exists():
            # 尝试在 reports 目录下查找
            result_path = reports_dir / args.show
            if not result_path.exists():
                print(f"错误：找不到回测结果 '{args.show}'")
                return
        
        # 加载结果
        result = load_backtest_result(result_path)
        if result is None:
            print(f"错误：无法加载回测结果 '{args.show}'")
            return
        
        # 查看指定日期详情
        if args.date:
            print(f"\n【{args.date} 账户详情】")
            print("=" * 60)
            
            # 现金流
            if args.detail in ['cashflow', 'all']:
                cashflow = result.get_daily_cashflow(args.date)
                print("\n现金流：")
                print(f"  可用现金: {cashflow.get('cash', 0):,.2f}")
                print(f"  冻结资金: {cashflow.get('frozen_cash', 0):,.2f}")
                print(f"  当日流入: {cashflow.get('inflow', 0):,.2f}")
                print(f"  当日流出: {cashflow.get('outflow', 0):,.2f}")
            
            # 持仓
            if args.detail in ['positions', 'all']:
                positions = result.get_daily_positions(args.date)
                print(f"\n持仓（{len(positions)} 只）：")
                for pos in positions[:10]:  # 最多显示10只
                    print(f"  {pos.stock_code}: {pos.quantity}股 @ {pos.entry_price:.2f}")
                if len(positions) > 10:
                    print(f"  ... 还有 {len(positions) - 10} 只")
            
            # 交易
            if args.detail in ['trades', 'all']:
                trades = [t for t in result.trades if t.date.strftime('%Y-%m-%d') == args.date]
                print(f"\n当日交易（{len(trades)} 笔）：")
                for t in trades:
                    action = "买入" if t.action == "open" else "卖出"
                    print(f"  {action} {t.stock_code}: {t.quantity}股 @ {t.price:.2f} ({t.reason})")
            
            print("=" * 60)
            return
        
        # 显示摘要
        print(f"\n【回测结果摘要】")
        print("=" * 60)
        print(f"策略: {result.strategy_name}")
        print(f"回测区间: {result.start_date} ~ {result.end_date}")
        print(f"初始资金: {result.initial_capital:,.2f}")
        print(f"最终资产: {result.final_value:,.2f}")
        print(f"总收益率: {result.total_return:.2%}")
        print(f"交易次数: {len(result.trades)}")
        
        if result.performance:
            print(f"\n【绩效指标】")
            print("-" * 40)
            for key, value in result.performance.items():
                if isinstance(value, float):
                    if 'ratio' in key.lower() or 'return' in key.lower() or 'rate' in key.lower():
                        print(f"  {key}: {value:.2%}")
                    else:
                        print(f"  {key}: {value:.2f}")
                else:
                    print(f"  {key}: {value}")
        
        print("=" * 60)
        print(f"\n结果路径: {result_path}")
        print("使用 '--date YYYY-MM-DD --detail cashflow/positions/trades' 查看逐日详情")
        return
    
    # 3. 导出结果
    if args.export:
        result_path = Path(args.export)
        if not result_path.exists():
            result_path = reports_dir / args.export
        
        result = load_backtest_result(result_path)
        if result is None:
            print(f"错误：无法加载回测结果 '{args.export}'")
            return
        
        output_path = args.output or 'trades_export.csv'
        
        # 导出交易记录
        trades_df = pd.DataFrame([
            {
                'date': t.date,
                'stock_code': t.stock_code,
                'action': t.action,
                'price': t.price,
                'quantity': t.quantity,
                'pnl': t.pnl,
                'reason': t.reason,
            }
            for t in result.trades
        ])
        trades_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"交易记录已导出: {output_path}")
        return
    
    # 4. 生成 HTML 报告
    if args.html:
        result_path = Path(args.html)
        if not result_path.exists():
            result_path = reports_dir / args.html
        
        if not result_path.exists():
            print(f"错误：找不到回测结果 '{args.html}'")
            return
        
        from src.report import generate_html_report
        try:
            html_path = generate_html_report(str(result_path))
            print(f"HTML 报告已生成: {html_path}")
        except Exception as e:
            print(f"生成失败: {e}")
        return
    
    # 5. 删除结果
    if args.delete:
        result_path = Path(args.delete)
        if not result_path.exists():
            result_path = reports_dir / args.delete
        
        if not result_path.exists():
            print(f"错误：找不到回测结果 '{args.delete}'")
            return
        
        shutil.rmtree(result_path)
        print(f"已删除: {result_path}")
        return
    
    # 无参数时显示提示信息
    print("\n回测结果管理命令")
    print("=" * 60)
    print("\n可用选项：")
    print("  --list, -l          列出已有回测结果")
    print("  --show <路径>       查看回测结果摘要")
    print("  --date <日期>       查看指定日期的详情（与 --show 配合使用）")
    print("  --detail <类型>     详情类型: cashflow/positions/trades/all")
    print("  --export <路径>     导出回测结果")
    print("  --html <路径>       生成 HTML 报告")
    print("  --delete <路径>     删除回测结果")
    print("\n示例：")
    print("  python main.py result --list")
    print("  python main.py result --show reports/backtest_2024-01-01_2024-12-31")
    print("  python main.py result --show <路径> --date 2024-06-01 --detail trades")
    print("  python main.py result --html reports/backtest_2024-01-01_2024-12-31")
    print("=" * 60)


# ============ 股票池管理命令 ============

def setup_pool_parser(parser: argparse.ArgumentParser):
    """设置股票池管理命令参数"""

    # 列出股票池
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='列出所有股票池'
    )

    # 创建股票池
    parser.add_argument(
        '--create',
        metavar='POOL_NAME',
        help='创建股票池'
    )

    # 股票池代码
    parser.add_argument(
        '--code',
        metavar='CODE',
        help='股票池代码（如 CSI300，与 --create 配合使用）'
    )

    # 描述
    parser.add_argument(
        '--desc',
        metavar='DESCRIPTION',
        help='股票池描述（与 --create 配合使用）'
    )

    # 查看股票池详情
    parser.add_argument(
        '--show',
        metavar='POOL_NAME',
        help='查看股票池详情（含成员列表）'
    )

    # 删除股票池
    parser.add_argument(
        '--delete',
        metavar='POOL_NAME',
        help='删除股票池'
    )

    # 添加成员
    parser.add_argument(
        '--add',
        metavar='POOL_NAME',
        help='向股票池添加股票（配合 --stocks 使用）'
    )

    # 移除成员
    parser.add_argument(
        '--remove',
        metavar='POOL_NAME',
        help='从股票池移除股票（配合 --stocks 使用）'
    )

    # 股票代码列表（逗号分隔）
    parser.add_argument(
        '--stocks',
        metavar='CODES',
        help='股票代码列表，逗号分隔（如 000001.SZ,600000.SH）'
    )

    # 从CSV导入
    parser.add_argument(
        '--import-csv',
        metavar='CSV_PATH',
        help='从CSV文件导入股票到股票池（配合 --add 使用）'
    )

    # 从指数导入
    parser.add_argument(
        '--import-index',
        metavar='INDEX_CODE',
        help='从指数成分股导入为股票池（配合 --create 使用）'
    )


def _get_db_path() -> str:
    """获取数据库路径"""
    return str(Path(__file__).parent.parent.parent / 'data' / 'aquant.db')


def run_pool_command(args: argparse.Namespace):
    """执行股票池管理命令"""

    from src.data.database import DatabaseManager

    db = DatabaseManager(_get_db_path())

    # 1. 列出所有股票池
    if args.list:
        pools = db.list_stock_pools()
        if not pools:
            print("\n暂无股票池")
            return

        print("\n股票池列表：")
        print("=" * 80)
        print(f"{'名称':<20} {'代码':<15} {'成员数':>8}  {'描述':<25} {'创建时间'}")
        print("-" * 80)
        for p in pools:
            desc = (p['description'] or '')[:24]
            print(f"{p['pool_name']:<20} {(p['pool_code'] or ''):<15} {p['member_count']:>8}  {desc:<25} {p['created_at']}")
        print("=" * 80)
        print(f"共 {len(pools)} 个股票池")
        print("\n使用 'python main.py pool --show <名称>' 查看详情")
        return

    # 2. 创建股票池
    if args.create:
        pool_name = args.create

        # 如果指定了从指数导入
        if args.import_index:
            count = db.import_index_as_pool(args.import_index, pool_name, args.desc)
            if count == -1:
                print(f"错误：指数 {args.import_index} 无成分股数据")
            else:
                print(f"已从指数 {args.import_index} 创建股票池 '{pool_name}'，导入 {count} 只股票")
            return

        pool_id = db.create_stock_pool(pool_name, args.code, args.desc)
        if pool_id == -1:
            print(f"错误：股票池 '{pool_name}' 已存在")
        else:
            print(f"已创建股票池: {pool_name}")
            if args.code:
                print(f"  代码: {args.code}")
            if args.desc:
                print(f"  描述: {args.desc}")
            print(f"\n使用 'python main.py pool --add {pool_name} --stocks <代码列表>' 添加股票")
        return

    # 3. 查看股票池详情
    if args.show:
        pool_name = args.show
        info = db.get_stock_pool_info(pool_name)
        if not info:
            print(f"错误：股票池 '{pool_name}' 不存在")
            return

        members = db.get_stock_pool_members(pool_name)
        print(f"\n股票池: {pool_name}")
        print("=" * 60)
        if info.get('pool_code'):
            print(f"  代码: {info['pool_code']}")
        if info.get('description'):
            print(f"  描述: {info['description']}")
        print(f"  创建时间: {info['created_at']}")
        print(f"  当前成员数: {len(members)}")

        if members:
            print(f"\n成员列表（共 {len(members)} 只）：")
            # 每行显示8个
            for i in range(0, len(members), 8):
                print("  " + ", ".join(members[i:i + 8]))
        else:
            print("\n  （空股票池）")

        print("=" * 60)
        return

    # 4. 删除股票池
    if args.delete:
        pool_name = args.delete
        if db.delete_stock_pool(pool_name):
            print(f"已删除股票池: {pool_name}")
        else:
            print(f"错误：股票池 '{pool_name}' 不存在")
        return

    # 5. 添加成员
    if args.add:
        pool_name = args.add

        # 从CSV导入
        if args.import_csv:
            csv_path = args.import_csv
            if not Path(csv_path).exists():
                print(f"错误：文件不存在 '{csv_path}'")
                return
            count = db.import_csv_as_pool(csv_path, pool_name)
            if count == -1:
                print("导入失败")
            else:
                print(f"已从CSV导入 {count} 只股票到股票池 '{pool_name}'")
            return

        # 从命令行添加
        if not args.stocks:
            print("错误：请通过 --stocks 指定股票代码列表")
            return

        stock_codes = [s.strip() for s in args.stocks.split(',')]
        count = db.add_to_stock_pool(pool_name, stock_codes)
        if count == 0:
            # 可能是已存在，检查股票池是否存在
            info = db.get_stock_pool_info(pool_name)
            if info is None:
                print(f"错误：股票池 '{pool_name}' 不存在，请先创建")
            else:
                print(f"所有股票已存在于 '{pool_name}' 中，无需重复添加")
        else:
            print(f"已向 '{pool_name}' 添加 {count} 只股票（跳过已存在的）")
        return

    # 6. 移除成员
    if args.remove:
        pool_name = args.remove
        if not args.stocks:
            print("错误：请通过 --stocks 指定要移除的股票代码列表")
            return

        stock_codes = [s.strip() for s in args.stocks.split(',')]
        count = db.remove_from_stock_pool(pool_name, stock_codes)
        print(f"已从 '{pool_name}' 移除 {count} 只股票")
        return

    # 无参数时显示提示信息
    print("\n股票池管理命令")
    print("=" * 60)
    print("\n可用选项：")
    print("  --list, -l                  列出所有股票池")
    print("  --create <名称>             创建股票池")
    print("  --code <代码>               股票池代码（与 --create 配合）")
    print("  --desc <描述>               股票池描述（与 --create 配合）")
    print("  --show <名称>               查看股票池详情和成员列表")
    print("  --delete <名称>             删除股票池")
    print("  --add <名称> --stocks <代码>   添加股票到池")
    print("  --remove <名称> --stocks <代码> 从池移除股票")
    print("  --import-csv <路径>         从CSV导入（与 --add 配合）")
    print("  --import-index <指数代码>   从指数成分股创建（与 --create 配合）")
    print("\n示例：")
    print("  python main.py pool --list")
    print("  python main.py pool --create tech_pool --desc '科技股精选'")
    print("  python main.py pool --add tech_pool --stocks 000001.SZ,600000.SH")
    print("  python main.py pool --show tech_pool")
    print("  python main.py pool --create CSI300 --import-index 000300.SH")
    print("=" * 60)
