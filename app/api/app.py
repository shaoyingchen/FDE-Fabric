"""FastAPI 应用 — 运行 API、Registry API、事件/步骤查询与静态控制台。"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..adapters.agents import RegistryService
from ..domain.models import AgentRegistryRecord, RunCreateRequest
from ..runtime import RuntimeService
from .deps import Container, build_container

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "console"


def _database_url() -> str:
    env = os.environ.get("FDE_DATABASE_URL")
    if env:
        return env
    return f"sqlite+aiosqlite:///{Path(__file__).resolve().parent.parent.parent / 'fde.db'}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    container: Container = app.state.container
    await container.repo.init_schema()
    # 启动时恢复未完成的 Run（可恢复性）
    recovered = await container.runtime.recover_active_runs()
    if recovered:
        print(f"[FDE] 恢复 {len(recovered)} 个未完成 Run: {recovered}")
    yield
    await container.repo.dispose()


def create_app(*, container: Container | None = None) -> FastAPI:
    if container is None:
        container = build_container(_database_url())

    app = FastAPI(title="FDE Fabric", version="0.1.0", lifespan=lifespan)
    app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/api/runs", status_code=201)
    async def create_run(request: RunCreateRequest):
        runtime: RuntimeService = container.runtime
        run = await runtime.create_run(request)
        # 后台执行，避免请求内同步跑完（文档 §12）
        asyncio.create_task(runtime.execute_run(run.run_id))
        return {"run_id": run.run_id, "status": run.status.value}

    @app.get("/api/runs")
    async def list_runs(status: str | None = None, limit: int = 50):
        runtime: RuntimeService = container.runtime
        return await runtime.list_runs(status=status, limit=limit)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        runtime: RuntimeService = container.runtime
        run = await runtime.get_run(run_id)
        if run is None:
            raise HTTPException(404, "Run 不存在")
        return run

    @app.get("/api/runs/{run_id}/tasks")
    async def get_run_tasks(run_id: str):
        runtime: RuntimeService = container.runtime
        if await runtime.get_run(run_id) is None:
            raise HTTPException(404, "Run 不存在")
        return await runtime.get_run_tasks(run_id)

    @app.get("/api/runs/{run_id}/events")
    async def get_run_events(run_id: str):
        runtime: RuntimeService = container.runtime
        return await runtime.get_run_events(run_id)

    @app.get("/api/runs/{run_id}/steps")
    async def get_run_steps(run_id: str, task_id: str | None = None):
        runtime: RuntimeService = container.runtime
        return await runtime.get_run_steps(run_id, task_id=task_id)

    @app.get("/api/runs/{run_id}/artifacts")
    async def get_run_artifacts(run_id: str):
        runtime: RuntimeService = container.runtime
        return await runtime.get_run_artifacts(run_id)

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        runtime: RuntimeService = container.runtime
        return await runtime.cancel_run(run_id)

    @app.post("/api/runs/{run_id}/resume")
    async def resume_run(run_id: str):
        runtime: RuntimeService = container.runtime
        return await runtime.resume_run(run_id)

    @app.get("/api/runs/{run_id}/tool-calls")
    async def get_run_tool_calls(run_id: str):
        return await container.repo.list_tool_calls(run_id)

    @app.get("/api/metrics")
    async def get_metrics():
        return container.metrics.snapshot()

    @app.get("/api/dashboard/stats")
    async def dashboard_stats():
        runtime: RuntimeService = container.runtime
        return await runtime.dashboard_stats()

    @app.post("/api/recovery/scan")
    async def recovery_scan():
        runtime: RuntimeService = container.runtime
        stale = await runtime.recover_stale_tasks()
        runs = await runtime.recover_active_runs()
        return {"stale_recovered": stale, "runs_recovered": runs}

    # --- Agent Registry ---

    @app.post("/api/registry/agents", status_code=201)
    async def register_agent(record: AgentRegistryRecord):
        registry: RegistryService = container.registry
        existing = await registry.get_by_id(record.agent_id)
        if existing is not None:
            raise HTTPException(409, f"Agent 已存在: {record.agent_id}")
        await registry.register(record)
        return await registry.get_by_id(record.agent_id)

    @app.get("/api/registry/agents")
    async def list_agents(skill: str | None = None, status: str | None = None):
        registry: RegistryService = container.registry
        return [a.model_dump() for a in await registry.list_agents(skill=skill, status=status)]

    @app.post("/api/registry/probe-all")
    async def probe_all_agents():
        registry: RegistryService = container.registry
        await registry.probe_all()
        return [a.model_dump() for a in await registry.list_agents()]

    @app.get("/api/registry/agents/{agent_id}")
    async def get_agent(agent_id: str):
        registry: RegistryService = container.registry
        agent = await registry.get_by_id(agent_id)
        if agent is None:
            raise HTTPException(404, "Agent 未注册")
        return agent.model_dump()

    @app.get("/api/registry/agents/{agent_id}/card")
    async def get_agent_card(agent_id: str):
        registry: RegistryService = container.registry
        agent = await registry.get_by_id(agent_id)
        if agent is None:
            raise HTTPException(404, "Agent 未注册")
        return await container.a2a.resolve_agent_card(agent)

    @app.delete("/api/registry/agents/{agent_id}")
    async def deregister_agent(agent_id: str):
        registry: RegistryService = container.registry
        await registry.deregister(agent_id)
        return {"ok": True}

    @app.post("/api/registry/agents/{agent_id}/healthcheck")
    async def healthcheck_agent(agent_id: str):
        registry: RegistryService = container.registry
        agent = await registry.get_by_id(agent_id)
        if agent is None:
            raise HTTPException(404, "Agent 未注册")
        if not agent.endpoint:
            return {"agent_id": agent_id, "healthy": False, "reason": "无 endpoint"}
        healthy = await container.a2a.health_check(endpoint=agent.endpoint)
        await registry.update_health(agent_id, healthy=healthy, heartbeat=time.time())
        return {"agent_id": agent_id, "healthy": healthy}

    # --- 静态控制台 ---
    if _STATIC_DIR.exists():
        app.mount("/console", StaticFiles(directory=str(_STATIC_DIR), html=True), name="console")

        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(str(_STATIC_DIR / "index.html"))

    return app