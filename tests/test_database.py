"""
数据库模块测试
==============

测试数据库CRUD、数据生成器、执行日志等功能。
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

import pandas as pd
import numpy as np

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data.database import DatabaseManager
from src.data.test_data_generator import TestDataGenerator
from src.data.db_adapter import DatabaseAdapter
from src.data.loader import DataLoader
from src.factors.execution_logger import ExecutionLogger


def run_all_tests():
    """运行所有数据库测试"""
    print("=" * 60)
    print("数据库模块测试")
    print("=" * 60)

    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, 'test_aquant.db')

    try:
        # ========== 1. 数据库初始化 ==========
        print("\n[1] 数据库初始化测试...")
        db = DatabaseManager(db_path)
        assert os.path.exists(db_path), "数据库文件应存在"
        summary = db.get_data_summary()
        assert 'stock_daily' in summary
        assert 'execution_log' in summary
        print("  ✓ 数据库初始化成功")

        # ========== 2. 测试数据生成 ==========
        print("\n[2] 测试数据生成...")
        generator = TestDataGenerator(db)
        data = generator.generate_all_test_data(n_stocks=20, n_days=50)

        assert len(data['stock_info']) == 20
        assert len(data['stock_daily']) == 20 * 50
        assert len(data['index_daily']) > 0
        print(f"  ✓ 股票信息: {len(data['stock_info'])} 条")
        print(f"  ✓ 股票日频: {len(data['stock_daily'])} 条")
        print(f"  ✓ 指数日频: {len(data['index_daily'])} 条")

        # ========== 3. 数据查询 ==========
        print("\n[3] 数据查询测试...")

        # 查询股票日频数据
        stock_daily = db.get_stock_daily(
            stock_codes=[data['stock_info']['stock_code'].iloc[0]],
            start_date='2023-01-01',
            end_date='2023-12-31'
        )
        assert not stock_daily.empty, "应能查询到数据"
        assert isinstance(stock_daily.index, pd.MultiIndex)
        print(f"  ✓ 查询到 {len(stock_daily)} 条股票数据")

        # 查询指数数据
        index_daily = db.get_index_daily()
        assert not index_daily.empty
        print(f"  ✓ 查询到 {len(index_daily)} 条指数数据")

        # 查询股票信息
        stock_info = db.get_stock_info()
        assert len(stock_info) == 20
        print(f"  ✓ 查询到 {len(stock_info)} 条股票信息")

        # ========== 4. 执行日志 ==========
        print("\n[4] 执行日志测试...")

        # 记录因子评估
        log_id_1 = db.log_execution(
            execution_type='factor_evaluation',
            factor_name='WQ_001',
            factor_category='worldquant',
            start_date='2023-01-01',
            end_date='2023-12-31',
            n_stocks=20,
            n_days=50,
            ic_mean=0.05,
            ic_std=0.02,
            ir=2.5,
            status='success'
        )
        assert log_id_1 > 0
        print(f"  ✓ 因子评估日志记录成功, id={log_id_1}")

        # 记录回测结果
        log_id_2 = db.log_execution(
            execution_type='backtest',
            factor_name='WQ_001',
            factor_category='worldquant',
            start_date='2023-01-01',
            end_date='2023-12-31',
            n_stocks=20,
            n_days=50,
            n_positions=10,
            rebalance_freq=5,
            initial_capital=1000000,
            sharpe=1.5,
            max_drawdown=-0.08,
            total_return=0.2,
            annual_return=0.25,
            annual_volatility=0.15,
            win_rate=0.55,
            status='success'
        )
        assert log_id_2 > 0
        print(f"  ✓ 回测结果日志记录成功, id={log_id_2}")

        # 查询执行日志
        logs = db.get_execution_logs(execution_type='factor_evaluation')
        assert len(logs) == 1
        assert logs.iloc[0]['factor_name'] == 'WQ_001'
        assert logs.iloc[0]['ic_mean'] == 0.05
        assert logs.iloc[0]['start_date'] == '2023-01-01'
        assert logs.iloc[0]['n_stocks'] == 20
        print("  ✓ 执行日志查询成功")

        # 查询回测日志
        bt_logs = db.get_execution_logs(execution_type='backtest')
        assert len(bt_logs) == 1
        assert bt_logs.iloc[0]['sharpe'] == 1.5
        assert bt_logs.iloc[0]['n_positions'] == 10
        assert bt_logs.iloc[0]['rebalance_freq'] == 5
        assert bt_logs.iloc[0]['initial_capital'] == 1000000
        print("  ✓ 回测日志查询成功（含执行条件）")

        # ========== 5. 最佳记录 ==========
        print("\n[5] 最佳记录测试...")

        # 更新最佳IC
        updated_1 = db.update_best_record('factor', 'WQ_001_IC', 0.05, log_id_1)
        assert updated_1
        print("  ✓ 新增最佳IC记录")

        # 更新为更好的值
        updated_2 = db.update_best_record('factor', 'WQ_001_IC', 0.08, log_id_1)
        assert updated_2
        print("  ✓ 更新最佳IC记录（0.05 -> 0.08）")

        # 不应更新（值更小）
        updated_3 = db.update_best_record('factor', 'WQ_001_IC', 0.03, log_id_1)
        assert not updated_3
        print("  ✓ 未更新（值更小）")

        # 更新最大回撤（越小越好）
        updated_4 = db.update_best_record('backtest', 'MaxDrawdown', -0.08, log_id_2)
        assert updated_4
        updated_5 = db.update_best_record('backtest', 'MaxDrawdown', -0.05, log_id_2)
        assert updated_5  # -0.05 > -0.08，应该更新
        print("  ✓ 最大回撤记录更新（越小越好）")

        # 查询最佳记录
        best = db.get_best_records()
        assert not best.empty
        print(f"  ✓ 查询到 {len(best)} 条最佳记录")

        # ========== 6. DataLoader.from_database ==========
        print("\n[6] DataLoader.from_database 测试...")
        loader = DataLoader.from_database(db_path)
        price_data = loader.get_price_data()
        assert not price_data.empty
        print(f"  ✓ 从数据库加载 {len(price_data)} 条价格数据")

        stock_list = loader.get_stock_list()
        assert len(stock_list) == 20
        print(f"  ✓ 从数据库加载 {len(stock_list)} 只股票信息")

        industry_map = loader.get_industry_mapping()
        assert len(industry_map) == 20
        print(f"  ✓ 行业映射: {len(industry_map)} 条")

        # ========== 7. ExecutionLogger ==========
        print("\n[7] ExecutionLogger 测试...")
        exec_logger = ExecutionLogger(db)

        # 记录因子评估
        eval_id = exec_logger.log_factor_evaluation(
            'GTJ_001',
            {'IC_mean': 0.06, 'IC_std': 0.03, 'IC_IR': 2.0},
            execution_context={
                'factor_category': 'guotai',
                'start_date': '2023-01-01',
                'end_date': '2023-12-31',
                'n_stocks': 20,
                'n_days': 50,
            }
        )
        assert eval_id > 0
        print(f"  ✓ 因子评估日志记录成功, id={eval_id}")

        # 记录回测结果
        bt_id = exec_logger.log_backtest_result(
            'GTJ_001',
            {'sharpe_ratio': 2.0, 'max_drawdown': -0.1, 'total_return': 0.3},
            execution_context={
                'factor_category': 'guotai',
                'n_positions': 15,
                'rebalance_freq': 5,
                'initial_capital': 1000000,
            }
        )
        assert bt_id > 0
        print(f"  ✓ 回测日志记录成功, id={bt_id}")

        # 查询最佳记录
        best = exec_logger.get_best_records()
        assert not best.empty
        print(f"  ✓ 最佳记录: {len(best)} 条")

        # 查询执行历史
        history = exec_logger.get_execution_history(limit=10)
        assert len(history) >= 2
        print(f"  ✓ 执行历史: {len(history)} 条")

        # ========== 8. 数据概览 ==========
        print("\n[8] 数据概览测试...")
        summary = db.get_data_summary()
        assert summary['stock_daily']['count'] == 20 * 50
        assert summary['stock_info']['count'] == 20
        assert summary['execution_log']['count'] >= 3
        assert summary['best_records']['count'] >= 2
        print(f"  ✓ 股票数据: {summary['stock_daily']['count']} 条")
        print(f"  ✓ 执行日志: {summary['execution_log']['count']} 条")
        print(f"  ✓ 最佳记录: {summary['best_records']['count']} 条")

        print("\n" + "=" * 60)
        print("所有测试通过！✓")
        print("=" * 60)

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)
        print(f"\n已清理临时目录: {temp_dir}")


if __name__ == "__main__":
    run_all_tests()
