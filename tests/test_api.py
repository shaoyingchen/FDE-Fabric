"""API 契约测试 — /api/runs 与 /api/registry。"""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app


@pytest.fixture
async def client(container):
    app = create_app(container=container)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


async def test_create_run_and_query(client):
    resp = await client.post("/api/runs", json={"goal": "生成报告"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "created"
    run_id = body["run_id"]

    # 等待后台执行完成（轮询）
    for _ in range(20):
        r = await client.get(f"/api/runs/{run_id}")
        if r.json()["status"] in ("succeeded", "failed", "cancelled"):
            break
        await asyncio.sleep(0.1)
    assert r.json()["status"] == "succeeded"

    tasks = await client.get(f"/api/runs/{run_id}/tasks")
    assert tasks.status_code == 200
    assert len(tasks.json()) == 5

    events = await client.get(f"/api/runs/{run_id}/events")
    types = [e["event_type"] for e in events.json()]
    assert "run.succeeded" in types


async def test_list_runs_filter(client):
    await client.post("/api/runs", json={"goal": "生成报告"})
    r = await client.get("/api/runs")
    assert r.status_code == 200
    assert len(r.json()) >= 1


async def test_404_on_unknown_run(client):
    r = await client.get("/api/runs/nope")
    assert r.status_code == 404


async def test_registry_crud(client):
    reg = await client.post(
        "/api/registry/agents",
        json={"agent_id": "a1", "name": "Agent One", "endpoint": "", "skills": ["search"]},
    )
    assert reg.status_code == 201

    listed = await client.get("/api/registry/agents")
    assert any(a["agent_id"] == "a1" for a in listed.json())

    by_skill = await client.get("/api/registry/agents", params={"skill": "search"})
    assert any(a["agent_id"] == "a1" for a in by_skill.json())

    got = await client.get("/api/registry/agents/a1")
    assert got.json()["name"] == "Agent One"

    deleted = await client.delete("/api/registry/agents/a1")
    assert deleted.status_code == 200
    gone = await client.get("/api/registry/agents/a1")
    assert gone.status_code == 404


async def test_console_index_served(container):
    from pathlib import Path

    static_dir = Path(container.runtime.__class__.__module__.split(".")[0]).resolve().parent / "console"
    if not static_dir.exists():
        pytest.skip("console 未挂载")
    app = create_app(container=container)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/")
        assert r.status_code == 200
        assert "FDE Fabric" in r.text