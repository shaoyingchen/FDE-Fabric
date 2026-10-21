"""A2A 远程协作测试（阶段 3 验收）：

- A2A Client：send / get / cancel / health check / card 获取
- Agent Registry：注册、按技能解析、健康探活
- 端到端：远程 A2A 任务通过统一 TaskRunner 契约被调度并跟踪
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid

import pytest
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.adapters.agents import A2AClient, RegistryService
from app.domain.models import AgentRegistryRecord


class SendBody(BaseModel):
    message: dict
    taskId: str | None = None


class FakeA2AServer:
    """最小 A2A 端点实现，供测试作为真实远程 Agent 后端。"""

    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self.port = 0
        self._thread: threading.Thread | None = None

    def build_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/.well-known/agent-card.json")
        async def card():
            return {
                "name": "fake-research", "description": "测试远程 Agent",
                "skills": ["research"], "version": "1.0.0",
            }

        @app.get("/.health/ready")
        async def health():
            return {"status": "ready"}

        @app.post("/tasks/send")
        async def send(body: SendBody):
            tid = body.taskId or f"a2a-{uuid.uuid4().hex[:8]}"
            self.tasks[tid] = {"taskId": tid, "status": "working", "artifacts": []}
            # 模拟异步完成
            async def _complete():
                await asyncio.sleep(0.05)
                self.tasks[tid]["status"] = "completed"
                self.tasks[tid]["artifacts"] = [{**body.message, "mode": "complete"}]
            asyncio.create_task(_complete())
            return {"taskId": tid, "status": "working"}

        @app.get("/tasks/{task_id}")
        async def get(task_id: str):
            return self.tasks.get(task_id, {"taskId": task_id, "status": "unknown"})

        @app.post("/tasks/{task_id}/cancel")
        async def cancel(task_id: str):
            if task_id in self.tasks:
                self.tasks[task_id]["status"] = "canceled"
            return {"taskId": task_id, "status": "canceled"}

        return app

    def start(self) -> str:
        app = self.build_app()
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
        server = uvicorn.Server(config)
        self._server = server
        self._thread = threading.Thread(target=server.run, daemon=True)
        self._thread.start()
        # 等待端口分配
        for _ in range(50):
            if server.started and server.servers:
                try:
                    self.port = server.servers[0].sockets[0].getsockname()[1]
                    break
                except Exception:
                    pass
            time.sleep(0.05)
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if getattr(self, "_server", None):
            self._server.should_exit = True
            self._thread.join(timeout=3)


@pytest.fixture
def fake_server():
    srv = FakeA2AServer()
    endpoint = srv.start()
    yield endpoint
    srv.stop()


async def test_a2a_client_card_and_health(container, fake_server):
    client = A2AClient()
    card = await client.fetch_agent_card(f"{fake_server}/.well-known/agent-card.json")
    assert card["name"] == "fake-research"
    assert card["skills"] == ["research"]
    assert await client.health_check(endpoint=fake_server) is True


async def test_a2a_client_send_get_poll(container, fake_server):
    client = A2AClient()
    sent = await client.send_task(endpoint=fake_server, message={"role": "user", "content": "hi"})
    assert sent["status"] in ("working", "completed")
    tid = sent["task_id"]
    # 轮询至终态
    deadline = time.time() + 3
    while time.time() < deadline:
        cur = await client.get_task(endpoint=fake_server, task_id=tid)
        if cur["status"] in ("completed", "failed", "canceled"):
            break
        await asyncio.sleep(0.05)
    assert cur["status"] == "completed"
    assert cur["artifacts"]


async def test_registry_register_resolve_health(container, fake_server):
    client = A2AClient()
    svc = RegistryService(repo=container.repo, a2a=client)

    rec = AgentRegistryRecord(
        agent_id="research-1", name="Research", endpoint=fake_server,
        skills=["research"],
    )

    registered = await svc.register(rec)
    # 注册即健康探测 → healthy
    assert registered.status in ("healthy", "registered")

    resolved = await svc.resolve(required_skill="research")
    assert resolved is not None
    assert resolved.agent_id == "research-1"

    await svc.update_health("research-1", healthy=True, heartbeat=time.time())
    got = await svc.get_by_id("research-1")
    assert got is not None and got.status == "healthy"

    await svc.deregister("research-1")
    assert await svc.get_by_id("research-1") is None


async def test_remote_a2a_task_via_task_runner(container, runtime, fake_server):
    """端到端：远程 A2A 任务按统一契约被调度。"""
    client = A2AClient()
    registry_svc = RegistryService(repo=container.repo, a2a=client)
    await registry_svc.register(AgentRegistryRecord(
        agent_id="research-1", name="Research", endpoint=fake_server,
        skills=["research"],
    ))

    # 手动构造一个 remote_a2a 任务
    from app.executor import TaskRunner
    from app.adapters.agents import LocalAgentInvoker

    local = container.runtime._services.runner
    agent = await registry_svc.resolve(required_skill="research")
    result = await local.execute(
        task={"task_id": "remote-1", "execution_mode": "remote_a2a",
              "description": "远程调研", "required_skill": "research",
              "timeout_seconds": 5},
        agent=agent, run_id="run-demo",
    )
    assert result.status == "succeeded"
    assert result.meta["mode"] == "remote_a2a"

    # A2A Task 已持久化跟踪
    tracked = await container.repo.get_a2a_task("run-demo", "remote-1")
    assert tracked is not None
    assert tracked["status"] == "completed"