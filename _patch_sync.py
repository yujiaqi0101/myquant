"""临时脚本：给 data_sync.py 添加 sync_steps 方法"""
import pathlib

p = pathlib.Path(r'd:\python_workspace\myquant\src\data\data_sync.py')
content = p.read_text(encoding='utf-8')

old = '        return results\n\n    # ============ 各步骤同步方法 ============'

new = '''        return results

    # ============ 按步骤同步 ============

    # 步骤定义表：(名称, 目标表, 是否需要stock_list, 是否需要日期范围)
    SYNC_STEPS = {
        1:  ('交易日历', 't_trading_date', False, False),
        2:  ('股票基本信息', 't_stock_info', False, False),
        3:  ('申万行业分类', 't_stock_info.industry', False, False),
        4:  ('申万行业分类明细', 't_stock_in_sw', False, False),
        5:  ('股票日频数据', 't_stock_daily', True, True),
        6:  ('ETF基本信息', 't_etf_info', False, False),
        7:  ('ETF日频数据', 't_etf_daily', True, True),
        8:  ('指数基本信息', 't_index_info', False, False),
        9:  ('指数成分股', 't_stock_in_index', False, False),
        10: ('指数日频数据', 't_index_daily', True, True),
        11: ('板块基本信息', 't_sector_info', False, False),
        12: ('板块成分股', 't_stock_list_in_sector', False, False),
        13: ('财务数据', 't_finance_prime', True, True),
        14: ('每日市值指标', 't_stock_mktvalue', True, True),
        15: ('估值数据', 't_valuation_data', True, True),
        16: ('除权除息', 't_dividend_date', True, True),
    }

    def sync_steps(self, steps: list, start_date='20230101', end_date='', progress_callback=None) -> dict:
        """
        按指定步骤同步数据

        Parameters
        ----------
        steps : list
            要执行的步骤编号列表，如 [14, 15] 或 [1, 2, 3]
        start_date : str
            开始日期，格式 YYYYMMDD
        end_date : str
            结束日期，格式 YYYYMMDD，为空则使用当前日期
        progress_callback : callable, optional
            进度回调函数

        Returns
        -------
        dict
            同步结果汇总
        """
        if not end_date:
            end_date = datetime.now().strftime('%Y%m%d')

        start_time = datetime.now()
        results = {
            'start_date': start_date,
            'end_date': end_date,
            'steps': {},
            'errors': [],
        }

        # 预加载依赖数据：stock_list / etf_list / index_list
        stock_list = []
        etf_list = []
        index_list = []

        needs_stock_list = any(self.SYNC_STEPS.get(s, (None,))[2] for s in steps if s in self.SYNC_STEPS)
        needs_etf_list = 7 in steps
        needs_index_list = 10 in steps

        if needs_stock_list or needs_etf_list or needs_index_list:
            logger.info("从数据库加载前置数据...")
            if needs_stock_list:
                stock_list = self._get_stock_list_from_db()
                if not stock_list:
                    logger.warning("数据库中无股票列表，请先执行步骤2（股票基本信息）")
            if needs_etf_list:
                etf_list = self._get_etf_list_from_db()
            if needs_index_list:
                index_list = self._get_index_list_from_db()

        total_steps = len(steps)
        for idx, step_num in enumerate(steps, 1):
            if step_num not in self.SYNC_STEPS:
                logger.warning(f"无效步骤号: {step_num}，跳过")
                continue

            step_name, table_name, _, _ = self.SYNC_STEPS[step_num]
            self._report_progress(progress_callback, step_name, idx, total_steps,
                                  f'正在同步 {step_name}...')

            try:
                r = self._execute_step(step_num, stock_list, etf_list, index_list,
                                       start_date, end_date, progress_callback)
                results['steps'][step_name] = r
                self._report_progress(progress_callback, step_name, idx, total_steps,
                                      f'{step_name}同步完成，共 {r.get("count", r.get("records", 0))} 条')
            except Exception as e:
                logger.error(f"步骤{step_num}({step_name})同步失败: {e}", exc_info=True)
                results['steps'][step_name] = {'count': 0, 'status': 'failed', 'error': str(e)}
                results['errors'].append(f'步骤{step_num}: {e}')
                self._report_progress(progress_callback, step_name, idx, total_steps,
                                      f'{step_name}同步失败: {e}')

        end_time = datetime.now()
        logger.info(f"指定步骤同步完成，耗时 {(end_time - start_time).total_seconds():.1f}s")
        return results

    def _execute_step(self, step_num: int, stock_list: list, etf_list: list,
                      index_list: list, start_date: str, end_date: str,
                      progress_callback=None) -> dict:
        """执行单个同步步骤"""
        if step_num == 1:
            return self.sync_trading_dates(start_date, end_date)
        elif step_num == 2:
            r = self.sync_stock_info()
            if r.get('codes'):
                stock_list.clear()
                stock_list.extend(r['codes'])
            return r
        elif step_num == 3:
            return self.update_shenwan_industry()
        elif step_num == 4:
            return self.sync_shenwan_industry_detail()
        elif step_num == 5:
            return self.sync_stock_daily(stock_list, start_date, end_date, progress_callback)
        elif step_num == 6:
            r = self.sync_etf_info()
            if r.get('codes'):
                etf_list.clear()
                etf_list.extend(r['codes'])
            return r
        elif step_num == 7:
            return self.sync_etf_daily(etf_list, start_date, end_date, progress_callback)
        elif step_num == 8:
            r = self.sync_index_info()
            if r.get('codes'):
                index_list.clear()
                index_list.extend(r['codes'])
            return r
        elif step_num == 9:
            return self.sync_index_constituents()
        elif step_num == 10:
            return self.sync_index_daily(index_list, start_date, end_date, progress_callback)
        elif step_num == 11:
            return self.sync_sector_info()
        elif step_num == 12:
            return self.sync_sector_constituents()
        elif step_num == 13:
            return self.sync_financial_data(stock_list, start_date, end_date, progress_callback)
        elif step_num == 14:
            return self.sync_stock_mktvalue(stock_list, end_date)
        elif step_num == 15:
            return self.sync_valuation_data(stock_list, end_date)
        elif step_num == 16:
            return self.sync_dividend_data(stock_list, start_date, end_date)
        else:
            return {'count': 0, 'status': 'unknown_step'}

    def _get_stock_list_from_db(self) -> list:
        """从数据库获取股票代码列表"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT stock_code FROM t_stock_info')
                return [row['stock_code'] for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"从数据库获取股票列表失败: {e}")
            return []

    def _get_etf_list_from_db(self) -> list:
        """从数据库获取ETF代码列表"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT etf_code FROM t_etf_info')
                return [row['etf_code'] for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"从数据库获取ETF列表失败: {e}")
            return []

    def _get_index_list_from_db(self) -> list:
        """从数据库获取指数代码列表"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT index_code FROM t_index_info')
                return [row['index_code'] for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"从数据库获取指数列表失败: {e}")
            return []

    # ============ 各步骤同步方法 ============'''

assert old in content, 'old string not found'
content = content.replace(old, new, 1)
with open(str(p), 'w', encoding='utf-8') as f:
    f.write(content)
print('OK - data_sync.py updated')
