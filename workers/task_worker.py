"""任务工人 — 轮询数据库队列执行 Run（文档 §12 第一版使用数据库任务表轮询）。"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("fde.worker")


async def poll_once(app, container) -> None:
    await container.repo.init_schema()
    active = await container.repo.list_active_runs()
    for run in active:
        logger.info("Worker 处理 Run: %s (status=%s)", run["run_id"], run["status"])
        try:
            await container.runtime.execute_run(run["run_id"])
        except Exception as exc:
            logger.exception("执行 Run %s 失败: %s", run["run_id"], exc)


async def main() -> None:
    from app.api.app import _database_url
    from app.api.deps import build_container

    container = build_container(_database_url())
    interval = float(os.environ.get("FDE_WORKER_INTERVAL", "2.0"))
    logger.info("FDE task worker 启动，poll interval=%.1fs", interval)
    try:
        while True:
            try:
                await poll_once(None, container)
            except Exception:
                logger.exception("轮询异常")
            await asyncio.sleep(interval)
    finally:
        await container.repo.dispose()


if __name__ == "__main__":
    asyncio.run(main())