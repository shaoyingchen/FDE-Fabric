"""存储适配层工厂 — 按配置返回统一 Repository 接口实现（当前 SQLite）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from ...ports.repository import RepositoryPort
from .sqlite_repository import SqliteRepository


@asynccontextmanager
async def get_repository(database_url: str) -> AsyncIterator[RepositoryPort]:
    repo = SqliteRepository(database_url)
    await repo.init_schema()
    try:
        yield repo  # type: ignore[misc]
    finally:
        await repo.dispose()