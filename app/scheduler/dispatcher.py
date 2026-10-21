"""Dispatcher — 就绪任务选择与并发调度（内存版，足以支撑阶段 1+3 验收）。

多 Worker 生产环境应改为数据库行锁/条件更新的租约认领。
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from ..planner.dag import get_ready_tasks


class Dispatcher:
    def __init__(self, *, max_concurrency: int = 3) -> None:
        self._max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def dispatch(
        self,
        tasks: list[dict],
        *,
        run_fn: Callable[[dict], Awaitable[dict]],
    ) -> list[dict]:
        """并行执行所有就绪任务，返回执行后的任务状态列表。

        run_fn 接收单任务 dict，返回更新后的任务 dict（含新 status）。
        """
        ready = get_ready_tasks([dict(t) for t in tasks])
        if not ready:
            return [dict(t) for t in tasks]

        async def _run(task: dict) -> dict:
            async with self._semaphore:
                return await run_fn(task)

        results = await asyncio.gather(*[_run(t) for t in ready])
        by_id = {r["task_id"]: r for r in results}
        merged = []
        for t in tasks:
            merged.append(by_id.get(t["task_id"], t))
        return merged