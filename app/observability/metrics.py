"""轻量指标计数 — 文档 §9.2 Trace & Observability 的指标实现。

计数器：runs / tasks / tool_calls / retries / a2a / budget。
直方图：耗时分布（duration_ms 秒点聚合），后续可对接 Prometheus。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._durations: defaultdict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def record_duration(self, name: str, seconds: float) -> None:
        with self._lock:
            self._durations[name].append(seconds)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            durations = {
                k: {
                    "count": len(v),
                    "p50_ms": (sorted(v)[len(v) // 2] * 1000) if v else None,
                    "p95_ms": (sorted(v)[int(len(v) * 0.95)] * 1000) if v else None,
                    "max_ms": max(v) * 1000 if v else None,
                }
                for k, v in self._durations.items()
            }
        return {
            "counters": counters,
            "durations": durations,
            "generated_at": time.time(),
        }


# 单例：模块内共享（进程级）。
single_metrics = Metrics()