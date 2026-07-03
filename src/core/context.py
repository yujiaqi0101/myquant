"""
src/core/context.py
====================

策略上下文抽象基类模块。

Context 是策略与引擎交互的唯一接口，封装 7 大职责：
    1. 数据访问：subscribe / history / history_multi / get_subscribed_symbols
    2. 订单操作：submit_order / cancel_order
    3. 持仓查询：get_position / get_positions
    4. 账户查询：get_account
    5. 定时器：add_timer / is_timer_due
    6. 时间查询：get_clock
    7. 日志配置：log / get_config
    8. 数据库访问：get_db（供策略加载股票池等只读用途）

设计要点（设计文档 3.3 节）：
    1. Context 是抽象基类，由各引擎提供具体实现：
       - BacktestContext（回测，从 HistoricalDataFeed 读历史）
       - PaperContext（模拟盘，实时行情 + 模拟撮合 + DB 持久化）
       - LiveContext（实盘，调用券商 API）
    2. 策略通过 Context 不感知运行模式，同一份代码可切换回测/实盘
    3. 主动式下单：context.submit_order() 立即返回 order_id，
       实际成交通过 OrderEvent/TradeEvent 异步回报

阶段1 仅定义抽象接口，具体实现在阶段 2/5 完成。
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

# 数据库连接类型：使用 Any 避免直接依赖 src.data.database（解耦，便于 core 独立测试）
# 实际运行时由引擎注入 DatabaseManager 实例
DbConnection = Any


class Context(ABC):
    """策略上下文抽象基类。

    所有方法均为抽象方法，由具体引擎子类实现。
    策略代码只依赖本抽象接口，不直接访问引擎内部组件。

    实现约定：
        - 历史数据方法 history/history_multi 不返回未来数据（避免未来函数）
        - submit_order 返回 order_id 后，订单实际状态由 OrderEvent 异步推送
        - get_position/get_account 返回 dict（而非内部对象），避免暴露引擎实现细节
    """

    # -------------------------------------------------------------------
    # 1. 数据访问
    # -------------------------------------------------------------------

    @abstractmethod
    def subscribe(self, symbols: Union[str, List[str]]) -> None:
        """订阅标的行情。

        在 on_init 中调用。订阅后引擎才会推送该标的的 BarEvent/TickEvent。

        Args:
            symbols: 单个标的代码或列表，如 "600000.SH" 或 ["600000.SH", "000001.SZ"]
        """
        raise NotImplementedError

    @abstractmethod
    def history(
        self,
        symbol: str,
        fields: Union[str, List[str]] = "close",
        count: int = 100,
    ) -> Any:
        """查询单个标的的历史 K 线。

        切片规则：返回当前时间点之前的历史数据，绝不包含未来数据。
        例如 on_bar 处理 2024-06-01 的 BarEvent 时，history 返回的数据
        不含 2024-06-01 当天的 OHLC（除非引擎明确允许，如收盘后调用）。

        Args:
            symbol: 标的代码
            fields: 字段名或字段列表，如 "close" 或 ["open", "close", "volume"]
            count: 返回的 K 线根数（从当前时间往前数）

        Returns:
            单字段时返回 List[float]；多字段时返回结构化对象（具体由实现决定，
            常见为 dict[str, List[float]] 或 pandas.DataFrame）
        """
        raise NotImplementedError

    @abstractmethod
    def history_multi(
        self,
        symbols: List[str],
        fields: Union[str, List[str]] = "close",
        count: int = 100,
    ) -> Any:
        """批量查询多个标的的历史 K 线。

        等价于对每个 symbol 调用 history，但实现可批量查询提升性能。

        Args:
            symbols: 标的代码列表
            fields: 字段名或字段列表
            count: 返回的 K 线根数

        Returns:
            结构化对象（具体由实现决定，常见为 dict[symbol, ...]）
        """
        raise NotImplementedError

    @abstractmethod
    def get_subscribed_symbols(self) -> List[str]:
        """获取已订阅的标的列表。"""
        raise NotImplementedError

    # -------------------------------------------------------------------
    # 2. 订单操作
    # -------------------------------------------------------------------

    @abstractmethod
    def submit_order(
        self,
        symbol: str,
        direction: str,
        volume: Optional[float] = None,
        target_weight: Optional[float] = None,
        price_type: str = "market",
        price: Optional[float] = None,
        order_id: Optional[str] = None,
    ) -> str:
        """提交订单。

        主动式下单接口（vnpy 风格）。订单经风控管线检查后送入 Execution，
        实际成交通过 OrderEvent/TradeEvent 异步回报。

        支持两种下单方式：
            1. 按数量：direction="buy"/"sell" + volume
            2. 按目标权重：direction="target" + target_weight + price_type="target_percent"

        Args:
            symbol: 标的代码
            direction: 买卖方向（"buy"/"sell"/"target"）
            volume: 委托数量（按数量下单时使用）
            target_weight: 目标持仓权重 0-1（direction="target" 时使用）
            price_type: 价格类型（"market"/"limit"/"next_open"/"target_percent"）
            price: 限价单价格（price_type="limit" 时使用）
            order_id: 订单ID（可选，未指定则引擎自动生成）

        Returns:
            订单ID（用于后续 cancel_order / 查询状态）

        Raises:
            ValueError: 参数不合法（如 volume 和 target_weight 同时为空）
            RuntimeError: 风控拒绝订单时可能抛出（具体实现决定是否异步回报）
        """
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤销订单。

        Args:
            order_id: 订单ID

        Returns:
            是否撤销成功（已成交/已终结的订单无法撤销，返回 False）
        """
        raise NotImplementedError

    # -------------------------------------------------------------------
    # 3. 持仓查询
    # -------------------------------------------------------------------

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """查询单个标的的持仓。

        Args:
            symbol: 标的代码

        Returns:
            持仓字典（含 quantity/available/avg_price/market_price/pnl 等），
            无持仓时返回 None。字段对应 src.core.types.Position.to_dict() 输出
        """
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        """查询全部持仓。

        Returns:
            symbol → 持仓字典 的映射，无持仓时返回空 dict
        """
        raise NotImplementedError

    # -------------------------------------------------------------------
    # 4. 账户查询
    # -------------------------------------------------------------------

    @abstractmethod
    def get_account(self) -> Dict[str, Any]:
        """查询账户资金。

        Returns:
            账户字典，含以下字段：
                cash          可用现金
                frozen        冻结资金（Pending 订单占用）
                market_value  持仓市值
                total         总资产 = cash + frozen + market_value
                pnl           累计盈亏 = total - initial_cash
                pnl_pct       累计盈亏百分比 = pnl / initial_cash
                daily_pnl     当日盈亏
                daily_pnl_pct 当日盈亏百分比
        """
        raise NotImplementedError

    # -------------------------------------------------------------------
    # 5. 定时器
    # -------------------------------------------------------------------

    @abstractmethod
    def add_timer(self, name: str, rule: str) -> None:
        """注册定时器。

        在 on_init 中调用。引擎按 rule 触发时机推送 TimerEvent(name)。
        策略在 on_event 中通过 event.name 判断是否到期。

        常用 rule（具体语法由引擎实现决定）：
            - "month_start"    每月第一个交易日
            - "month_end"      每月最后一个交易日
            - "week_start"     每周第一个交易日
            - "daily_open"     每日开盘
            - "daily_close"    每日收盘

        Args:
            name: 定时器名称（唯一标识，与 TimerEvent.name 对应）
            rule: 触发规则
        """
        raise NotImplementedError

    @abstractmethod
    def is_timer_due(self, name: str) -> bool:
        """判断定时器是否在当前事件中触发。

        在 on_event 中调用，用于确认当前事件是否为指定定时器的触发事件。

        Args:
            name: 定时器名称

        Returns:
            是否触发（当前事件为该定时器的 TimerEvent 时返回 True）
        """
        raise NotImplementedError

    # -------------------------------------------------------------------
    # 6. 时间查询
    # -------------------------------------------------------------------

    @abstractmethod
    def get_clock(self) -> datetime:
        """获取当前回测/实盘时间。

        回测模式返回 BarEvent.timestamp（模拟时间）；
        模拟盘/实盘返回墙钟时间。

        Returns:
            当前时间
        """
        raise NotImplementedError

    # -------------------------------------------------------------------
    # 7. 日志与配置
    # -------------------------------------------------------------------

    @abstractmethod
    def log(self, level: str, msg: str, **kwargs: Any) -> None:
        """写日志。

        Args:
            level: 日志级别（"debug"/"info"/"warning"/"error"/"critical"）
            msg: 日志消息
            **kwargs: 附加字段（如 symbol/order_id，便于结构化检索）
        """
        raise NotImplementedError

    @abstractmethod
    def get_config(self, key: str, default: Any = None) -> Any:
        """读取引擎配置。

        用于策略获取运行时配置（如基准代码、手续费率、初始资金等）。
        配置来源由引擎决定（CLI 参数 / 配置文件 / 环境变量）。

        Args:
            key: 配置键
            default: 默认值（键不存在时返回）

        Returns:
            配置值
        """
        raise NotImplementedError

    # -------------------------------------------------------------------
    # 8. 数据库访问（只读，供策略加载股票池等）
    # -------------------------------------------------------------------

    @abstractmethod
    def get_db(self) -> Optional[DbConnection]:
        """获取数据库连接（只读用途）。

        供策略加载股票池、行业分类等静态数据使用。
        回测/模拟盘/实盘均注入 DatabaseManager 实例；
        若引擎未配置数据库（如纯单元测试），返回 None。

        注意：策略不应通过此接口写入数据，写操作由引擎持久化层统一处理。

        Returns:
            数据库连接对象（DatabaseManager），未配置时返回 None
        """
        raise NotImplementedError
