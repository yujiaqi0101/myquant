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
    
    # 1. 自动发现策略
    StrategyRegistry.auto_discover('src.strategies')
    
    # 2. 列出所有策略
    if args.list:
        strategies = StrategyRegistry.list_strategies()
        print("\n可用策略列表：")
        print("=" * 60)
        for s in strategies:
            print(f"  {s['name']:<20} {s['description'][:40]}")
        print("=" * 60)
        print(f"共 {len(strategies)} 个策略")
        print("\n使用 'python main.py strategy --show <策略名>' 查看详情")
        return
    
    # 3. 查看策略详情
    if args.show:
        strategy_class = StrategyRegistry.get(args.show)
        if strategy_class is None:
            print(f"错误：未知策略 '{args.show}'")
            available = [s['name'] for s in StrategyRegistry.list_strategies()]
            print(f"可用策略: {', '.join(available)}")
            return
        
        # 获取策略文档字符串（类注释）
        docstring = strategy_class.__doc__ or "（无描述）"
        
        print(f"\n策略: {strategy_class.name or strategy_class.__name__}")
        print("=" * 60)
        print("\n【策略说明】")
        print(docstring)
        
        # 显示参数模式
        if args.params:
            print("\n【参数说明】")
            print("-" * 40)
            schema = strategy_class.get_param_schema()
            for param_name, param_info in schema.items():
                print(f"  {param_name}:")
                print(f"    类型: {param_info['type']}")
                print(f"    默认值: {param_info['default']}")
                print(f"    说明: {param_info['description']}")
                if 'min' in param_info:
                    print(f"    范围: [{param_info['min']}, {param_info['max']}]")
        else:
            print(f"\n【默认参数】")
            print("-" * 40)
            for name, value in strategy_class.default_params.items():
                print(f"  {name}: {value}")
            print("\n使用 '--params' 查看详细参数说明")
        
        print("=" * 60)
        return
    
    # 无参数时显示帮助
    parser.print_help()


def setup_backtest_parser(parser: argparse.ArgumentParser):
    """设置回测命令参数"""
    
    # 策略选择（必需）
    parser.add_argument(
        '--strategy', '-s',
        required=True,
        help='策略名称（通过 strategy --list 查看可用策略）'
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
        default=0.07,
        help='止损比例（如0.07表示7%）'
    )
    
    parser.add_argument(
        '--take-profit',
        type=float,
        default=0.20,
        help='止盈比例（如0.20表示20%）'
    )
    
    parser.add_argument(
        '--trailing-stop',
        type=int,
        default=3,
        help='动态止盈均线窗口（如3表示跌破3日均线止盈）'
    )
    
    parser.add_argument(
        '--max-holding-days',
        type=int,
        default=20,
        help='最大持仓天数'
    )
    
    parser.add_argument(
        '--position-size',
        type=float,
        default=0.10,
        help='单次开仓资金比例'
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


def load_price_data(start_date: str, end_date: str, db_path: str = None) -> pd.DataFrame:
    """加载价格数据"""
    from src.data import DataLoader
    
    if db_path is None:
        db_path = str(Path(__file__).parent.parent.parent / 'data' / 'aquant.db')
    
    data_loader = DataLoader.from_database(db_path)
    
    # 加载数据
    price_data = data_loader.get_price_data(start_date, end_date)
    
    return price_data


def run_backtest_command(args: argparse.Namespace):
    """执行回测命令"""
    
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
    if 'trailing_stop' in param_schema:
        warmup_days = max(warmup_days, param_schema['trailing_stop'].get('default', 3))
    warmup_days = max(warmup_days, 20)  # 最小20天
    
    # 4. 构建策略参数
    strategy_params = {
        'stop_loss': args.stop_loss,
        'take_profit': args.take_profit,
        'trailing_stop': args.trailing_stop,
        'max_holding_days': args.max_holding_days,
        'position_size': args.position_size,
        'commission_rate': args.commission_rate,
        'slippage': args.slippage,
    }
    
    # 5. 创建策略实例
    strategy = strategy_class(**strategy_params)
    
    # 6. 创建引擎
    risk_controller = None
    if args.enable_risk_control:
        risk_controller = RiskController(
            stop_loss=args.stop_loss,
            take_profit=args.take_profit,
            portfolio_stop=args.portfolio_stop,
        )
    
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=args.initial_capital,
        enable_engine_exit=True,
        risk_controller=risk_controller,
    )
    
    # 7. 加载数据（含预热期）
    start_dt = pd.Timestamp(args.start_date)
    warmup_start = (start_dt - timedelta(days=int(warmup_days * 1.5 + 10))).strftime('%Y-%m-%d')
    
    print(f"数据加载：")
    print(f"  预热期: {warmup_start} ~ {args.start_date} (约{warmup_days}个交易日)")
    print(f"  回测期: {args.start_date} ~ {args.end_date}")
    
    # 加载完整数据（预热期+回测期）
    full_data = load_price_data(warmup_start, args.end_date)
    
    # 分离预热期和回测期数据
    warmup_data = full_data[full_data.index.get_level_values('trade_date') < args.start_date]
    price_data = full_data[full_data.index.get_level_values('trade_date') >= args.start_date]
    
    print(f"  加载完成: {len(full_data)} 条记录")
    
    # 8. 运行回测
    print(f"\n开始回测...")
    result = engine.run(price_data, warmup_data)
    
    # 9. 保存结果
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    report_name = args.name or f"backtest_{args.start_date}_{args.end_date}"
    result_dir = output_dir / report_name
    result_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存绩效
    with open(result_dir / 'performance.json', 'w', encoding='utf-8') as f:
        json.dump({
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
    
    print(f"\n回测完成！")
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
    
    # 4. 删除结果
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
    
    # 无参数时显示帮助
    parser.print_help()
