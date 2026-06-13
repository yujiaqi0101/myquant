"""
EventBus
pub/sub 模型
订阅者按 type 监听
发布者发出事件 → 路由到对应订阅者
"""

from collections import defaultdict
from typing import Callable, List, Dict, Any


class EventBus:

    def __init__(self):

        # type -> List[handler]
        self._handlers: Dict[
            str,
            List[Callable],
        ] = defaultdict(list)

        # 历史事件（可选 / 用于 replay / audit）
        self._history: List[Any] = []

    def subscribe(
        self,
        event_type: str,
        handler: Callable,
    ):

        self._handlers[event_type].append(
            handler
        )

    def unsubscribe(
        self,
        event_type: str,
        handler: Callable,
    ):

        if handler in self._handlers.get(
            event_type, []
        ):

            self._handlers[
                event_type
            ].remove(handler)

    def publish(
        self,
        event,
    ):

        self._history.append(event)

        handlers = self._handlers.get(
            event.type, []
        )

        for h in handlers:

            h(event)

    def clear(self):

        self._handlers.clear()
        self._history.clear()

    def history(
        self,
        event_type: str = None,
    ):

        if event_type is None:

            return list(self._history)

        return [
            e for e in self._history
            if e.type == event_type
        ]


# 全局单例
# V1 简单起见用全局
# V2 改成 per-Engine 实例
event_bus = EventBus()
