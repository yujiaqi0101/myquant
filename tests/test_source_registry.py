"""
SourceRegistry 单元测试
=======================

验证：
- 单例模式正常工作
- get_source() 按名称返回正确实例 / 未知返回 None
- get_source_for_data_type() 按 config 路由
- reset() 清空缓存
- 'database' 类型返回 None（不需要实例）
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# 项目根加入 path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data.source_registry import SourceRegistry


class TestSourceRegistrySingleton(unittest.TestCase):
    """单例模式：多次实例化返回同一对象。"""

    def test_singleton(self):
        a = SourceRegistry()
        b = SourceRegistry()
        self.assertIs(a, b)

    def test_reset_clears_instances(self):
        a = SourceRegistry()
        a._instances = {"fake": MagicMock()}
        a.reset()
        self.assertEqual(a._instances, {})


class TestGetSource(unittest.TestCase):
    """get_source() 各分支覆盖。"""

    def setUp(self):
        # 每个用例独立
        SourceRegistry().reset()

    def tearDown(self):
        SourceRegistry().reset()

    def test_database_returns_none(self):
        """'database' 是无实例的特殊数据源。"""
        self.assertIsNone(SourceRegistry().get_source('database'))

    def test_empty_string_returns_none(self):
        self.assertIsNone(SourceRegistry().get_source(''))

    def test_unknown_source_returns_none(self):
        """未知数据源名返回 None。"""
        self.assertIsNone(SourceRegistry().get_source('not_a_real_source'))

    @patch('src.data.tdx_source.TdxSource')
    def test_tdx_lazy_load(self, mock_tdx_cls):
        """tdx 走懒加载。"""
        mock_instance = MagicMock()
        mock_tdx_cls.return_value = mock_instance

        src = SourceRegistry().get_source('tdx')
        self.assertIs(src, mock_instance)
        # 二次调用应命中缓存
        src2 = SourceRegistry().get_source('tdx')
        self.assertIs(src2, mock_instance)
        self.assertEqual(mock_tdx_cls.call_count, 1)

    @patch('src.data.qmt_connector.QMTConnector')
    def test_qmt_lazy_load(self, mock_qmt_cls):
        mock_instance = MagicMock()
        mock_qmt_cls.return_value = mock_instance

        src = SourceRegistry().get_source('qmt')
        self.assertIs(src, mock_instance)

    @patch('config.config.get_credentials')
    @patch('src.data.eastmoney_connector.EastmoneyConnector')
    def test_eastmoney_lazy_load_with_token(self, mock_em_cls, mock_get_creds):
        mock_get_creds.return_value = {'token': 'fake_token'}
        mock_instance = MagicMock()
        mock_em_cls.return_value = mock_instance

        src = SourceRegistry().get_source('eastmoney')
        self.assertIs(src, mock_instance)
        mock_em_cls.assert_called_once_with(token='fake_token')
        mock_instance.connect.assert_called_once()

    @patch('config.config.get_credentials')
    @patch('src.data.eastmoney_connector.EastmoneyConnector')
    def test_eastmoney_no_token_returns_none(self, mock_em_cls, mock_get_creds):
        """未配置 token 时返回 None。"""
        mock_get_creds.return_value = {'token': ''}
        self.assertIsNone(SourceRegistry().get_source('eastmoney'))
        mock_em_cls.assert_not_called()

    @patch('src.data.tdx_source.TdxSource', side_effect=Exception('boom'))
    def test_create_failure_returns_none(self, _mock_cls):
        self.assertIsNone(SourceRegistry().get_source('tdx'))


class TestGetSourceForDataType(unittest.TestCase):
    """get_source_for_data_type() 按 config 路由。"""

    def setUp(self):
        SourceRegistry().reset()

    def tearDown(self):
        SourceRegistry().reset()

    @patch('src.data.source_registry._get_data_source_for_type')
    @patch('src.data.tdx_source.TdxSource')
    def test_routing_sector_constituents_to_tdx(self, mock_tdx_cls, mock_get_source):
        """'sector_constituents' 在 config 默认路由到 tdx。"""
        mock_get_source.return_value = 'tdx'
        mock_tdx_cls.return_value = MagicMock()

        src = SourceRegistry().get_source_for_data_type('sector_constituents')
        self.assertIsNotNone(src)
        mock_get_source.assert_called_once_with('sector_constituents')

    @patch('src.data.source_registry._get_data_source_for_type')
    def test_routing_database_returns_none(self, mock_get_source):
        """未知数据类型默认 'database' → 返回 None。"""
        mock_get_source.return_value = 'database'
        self.assertIsNone(
            SourceRegistry().get_source_for_data_type('non_existent_type')
        )


if __name__ == '__main__':
    unittest.main()
