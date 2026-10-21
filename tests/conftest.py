"""conftest — 共享 fixtures：临时 SQLite、Container、Runtime、Registry。"""

from __future__ import annotations

import asyncio
import pytest

from app.api.deps import build_container


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def container(tmp_path, anyio_backend):
    db_path = tmp_path / "fde_test.db"
    c = build_container(f"sqlite+aiosqlite:///{db_path}")
    await c.repo.init_schema()
    yield c
    await c.repo.dispose()


@pytest.fixture
async def runtime(container):
    return container.runtime


@pytest.fixture
async def registry(container):
    return container.registry