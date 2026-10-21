"""RuntimeService — 面向 API 与 Worker 的编排入口。

职责：创建 Run、执行（LangGraph 图）、查询状态、取消、恢复、事件溯源。
状态持久化在 Repository（SQLite 现在 / PG 未来），LangGraph 负责执行流程。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from ..adapters.agents import RegistryService
from ..domain.models import RunCreateRequest, RunRecord, RunStatus
from ..executor import TaskRunner
from ..planner import PlannerService
from ..ports.model import ModelProvider
from ..ports.repository import RepositoryPort
from ..scheduler import Dispatcher
from .graph import RuntimeServices, build_runtime_graph


class RuntimeService:
    def __init__(
        self,
        *,
        repo: RepositoryPort,
        planner: PlannerService,
        dispatcher: Dispatcher,
        runner: TaskRunner,
        registry: RegistryService,
        model: ModelProvider,
        checkpointer=None,
    ) -> None:
        self._repo = repo
        self._services = RuntimeServices(
            repo=repo, planner=planner, dispatcher=dispatcher,
            runner=runner, registry=registry, model=model,
        )
        self._checkpointer = checkpointer or InMemorySaver()
        self._graph = build_runtime_graph(self._services, self._checkpointer)

    # --- Run 生命周期 ---

    async def create_run(self, request: RunCreateRequest | dict) -> RunRecord:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        if isinstance(request, dict):
            goal = request.get("goal", "")
            max_steps = request.get("max_steps", 100)
            budget = request.get("budget")
            deadline = request.get("deadline")
            metadata = request.get("metadata", {})
        else:
            goal = request.goal
            max_steps = request.max_steps
            budget = request.budget
            deadline = request.deadline
            metadata = request.metadata
        record = RunRecord(
            run_id=run_id,
            goal=goal,
            max_steps=max_steps,
            budget=budget,
            deadline=deadline,
            metadata=metadata,
            status=RunStatus.CREATED,
        )
        await self._repo.create_run(record)
        await self._repo.append_event(
            run_id=run_id, event_type="run.created", task_id=None, payload={"goal": goal}
        )
        return record

    async def execute_run(self, run_id: str) -> dict[str, Any]:
        """执行一次 Run（可恢复：从当前持久化状态继续）。"""
        run = await self._repo.get_run(run_id)
        if run is None:
            raise KeyError(f"Run 不存在: {run_id}")
        if run["status"] in ("succeeded", "failed", "cancelled"):
            return run

        await self._repo.update_run({"run_id": run_id, "status": "running"})
        state = {
            "run_id": run_id,
            "goal": run.get("goal", ""),
            "events": [],
        }
        result = await self._graph.ainvoke(
            state, config={"configurable": {"thread_id": run_id}}
        )
        return await self._repo.get_run(run_id) or result

    async def create_and_run(self, request: RunCreateRequest | dict) -> dict[str, Any]:
        run = await self.create_run(request)
        await self.execute_run(run.run_id)
        return await self._repo.get_run(run.run_id) or run.model_dump()

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = await self._repo.get_run(run_id)
        if run is None:
            return None
        tasks = await self._repo.list_tasks(run_id)
        completed = sum(1 for t in tasks if t["status"] == "succeeded")
        run["progress"] = f"{completed}/{len(tasks)}" if tasks else "0/0"
        run["tasks"] = tasks
        return run

    async def get_run_tasks(self, run_id: str) -> list[dict[str, Any]]:
        return await self._repo.list_tasks(run_id)

    async def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        return await self._repo.list_events(run_id)

    async def get_run_steps(self, run_id: str, *, task_id: str | None = None) -> list[dict[str, Any]]:
        return await self._repo.list_steps(run_id, task_id=task_id)

    async def get_run_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        """从已完成任务的 result_summary 中聚合产物（第 1 阶段对象存储为下一阶段）。"""
        tasks = await self._repo.list_tasks(run_id)
        return [
            {"task_id": t["task_id"], "description": t["description"],
             "status": t["status"], "result": t["result_summary"]}
            for t in tasks if t["status"] == "succeeded" and t["result_summary"]
        ]

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = await self._repo.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["status"] in ("succeeded", "failed", "cancelled"):
            return run
        await self._repo.update_run({"run_id": run_id, "status": "cancelled"})
        await self._repo.append_event(
            run_id=run_id, event_type="run.cancelled", task_id=None, payload={}
        )
        return await self._repo.get_run(run_id) or run

    async def resume_run(self, run_id: str) -> dict[str, Any]:
        """恢复 paused / 满足恢复条件的 Run。"""
        run = await self._repo.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["status"] == "cancelled":
            return run
        # 持久化状态已是最新；从当前状态继续执行
        return await self.execute_run(run_id)

    # --- 恢复扫描（进程重启后找回未完成 Run） ---

    async def recover_active_runs(self) -> list[str]:
        active = await self._repo.list_active_runs()
        recovered = []
        for run in active:
            try:
                await self.execute_run(run["run_id"])
                recovered.append(run["run_id"])
            except Exception:
                # 单个 Run 恢复失败不影响其余
                continue
        return recovered

    # --- 查询 ---

    async def list_runs(self, *, status: str | None = None, limit: int = 50) -> list[dict]:
        return await self._repo.list_runs(status=status, limit=limit)

    async def repo(self) -> RepositoryPort:
        return self._repo