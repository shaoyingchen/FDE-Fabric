"""scheduler 包 — DAG 就绪计算、选择与并发控制。"""

from .dispatcher import Dispatcher

__all__ = ["Dispatcher"]