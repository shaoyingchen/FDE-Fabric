"""恢复工人 — 周期性扫描：过期租约任务重置 + 恢复未完成 Run。

文档 §9.1：Worker 崩溃 → 租约过期后重新认领，从检查点恢复。
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("fde.recovery")


async def main() -> None:
    from app.api.app import _database_url
    from app.api.deps import build_container

    container = build_container(_database_url())
    interval = float(os.environ.get("FDE_RECOVERY_INTERVAL", "5.0"))
    logger.info("FDE recovery worker 启动，interval=%.1fs", interval)
    try:
        while True:
            try:
                stale = await container.runtime.recover_stale_tasks()
                recovered = await container.runtime.recover_active_runs()
                if stale or recovered:
                    logger.info("恢复: stale=%.0f, runs=%s", stale, recovered)
                await container.registry.probe_all()
            except Exception:
                logger.exception("恢复轮询异常")
            await asyncio.sleep(interval)
    finally:
        await container.repo.dispose()


if __name__ == "__main__":
    asyncio.run(main())