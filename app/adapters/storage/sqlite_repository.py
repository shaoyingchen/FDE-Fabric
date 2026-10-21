"""SQLite 存储适配层 — Repository 接口的 SQLAlchemy 2.0 实现。

当前用 SQLite 跑通；表结构对齐文档附录 §10（agent_runs / agent_plans /
agent_tasks / agent_steps / agent_events / agent_artifacts / agent_tool_calls /
agent_registry / a2a_tasks）。换 PostgreSQL 仅需更换 engine URL。
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from sqlalchemy import (
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ...ports.repository import RepositoryPort


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "agent_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    goal: Mapped[str] = mapped_column(Text, default="")
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


class PlanRow(Base):
    __tablename__ = "agent_plans"
    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    plan_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("run_id", "version"),)


class TaskRow(Base):
    __tablename__ = "agent_tasks"
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), index=True)
    execution_mode: Mapped[str] = mapped_column(String(32), default="local_react")
    required_skill: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    depends_on: Mapped[list | None] = mapped_column(JSON, default=list)
    required: Mapped[bool] = mapped_column(Integer, default=1)
    input_json: Mapped[dict | None] = mapped_column("input", JSON, nullable=True)
    output_schema_json: Mapped[dict | None] = mapped_column("output_schema", JSON, nullable=True)
    result_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "task_id"),
        Index("ix_agent_tasks_status_lease", "status", "lease_expires_at"),
    )


class StepRow(Base):
    __tablename__ = "agent_steps"
    step_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_type: Mapped[str] = mapped_column(String(32), default="llm")
    name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    input_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)


class EventRow(Base):
    __tablename__ = "agent_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)


class ToolCallRow(Base):
    __tablename__ = "agent_tool_calls"
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)


class RegistryRow(Base):
    __tablename__ = "agent_registry"
    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    card_url: Mapped[str] = mapped_column(Text, default="")
    endpoint: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list | None] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="registered")
    version: Mapped[str] = mapped_column(String(32), default="")
    last_heartbeat: Mapped[float | None] = mapped_column(Float, nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default")


class A2ATaskRow(Base):
    __tablename__ = "a2a_tasks"
    row_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    a2a_task_id: Mapped[str] = mapped_column(String(128))
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str] = mapped_column(String(64))
    agent_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    message: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    artifacts: Mapped[list | None] = mapped_column(JSON, default=list)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("run_id", "task_id"),)


class SqliteRepository(RepositoryPort):
    """SQLAlchemy Async 仓储实现（SQLite 跑通，PG 可换）。"""

    def __init__(self, engine_url: str):  # e.g. "sqlite+aiosqlite:///./fde.db"
        self._engine = create_async_engine(engine_url, echo=False)
        self._session = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init_schema(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self._engine.dispose()

    # --- helpers ---

    def _session_ctx(self) -> AsyncIterator[AsyncSession]:
        return self._session()

    # --- Run ---

    async def create_run(self, run) -> RunRow:  # type: ignore[override]
        row = RunRow(
            run_id=run.run_id, status=run.status.value, goal=run.goal,
            plan_version=run.plan_version, budget=run.budget, deadline=run.deadline,
            error=run.error, final_summary=run.final_summary,
            created_at=run.created_at, updated_at=run.updated_at,
            metadata_json=run.metadata,
        )
        async with self._session() as s:
            s.add(row)
            await s.commit()
        return run

    async def get_run(self, run_id: str) -> dict | None:  # type: ignore[override]
        async with self._session() as s:
            row = (await s.execute(select(RunRow).where(RunRow.run_id == run_id))).scalar_one_or_none()
            return self._run_to_dict(row) if row else None

    async def update_run(self, run) -> dict:  # type: ignore[override]
        if isinstance(run, dict):
            return await self._update_run_dict(run)
        async with self._session() as s:
            row = (await s.execute(select(RunRow).where(RunRow.run_id == run.run_id))).scalar_one()
            row.status = run.status.value
            row.plan_version = run.plan_version
            row.budget = run.budget
            row.deadline = run.deadline
            row.error = run.error
            row.final_summary = run.final_summary
            row.updated_at = run.updated_at
            row.metadata_json = run.metadata
            await s.commit()
        return self._run_to_dict(row)

    async def _update_run_dict(self, run: dict) -> dict:
        async with self._session() as s:
            row = (await s.execute(select(RunRow).where(RunRow.run_id == run["run_id"]))).scalar_one()
            for k, v in run.items():
                if k == "metadata":
                    setattr(row, "metadata_json", v)
                elif k in ("run_id",):
                    continue
                elif hasattr(row, k):
                    setattr(row, k, v)
            await s.commit()
        return self._run_to_dict(row)

    async def list_runs(self, *, status: str | None = None, limit: int = 50) -> list:  # type: ignore[override]
        async with self._session() as s:
            stmt = select(RunRow).order_by(RunRow.created_at.desc()).limit(limit)
            if status:
                stmt = stmt.where(RunRow.status == status)
            rows = (await s.execute(stmt)).scalars().all()
            return [self._run_to_dict(row) for row in rows]

    async def list_active_runs(self) -> list:  # type: ignore[override]
        active = ("running", "waiting_approval", "paused", "created")
        async with self._session() as s:
            rows = (
                await s.execute(
                    select(RunRow).where(RunRow.status.in_(active)).order_by(RunRow.created_at)
                )
            ).scalars().all()
            return [self._run_to_dict(row) for row in rows]

    @staticmethod
    def _run_to_dict(row: RunRow) -> dict:
        return {
            "run_id": row.run_id, "status": row.status, "goal": row.goal,
            "plan_version": row.plan_version, "budget": row.budget,
            "deadline": row.deadline, "error": row.error,
            "final_summary": row.final_summary, "created_at": row.created_at,
            "updated_at": row.updated_at, "metadata": row.metadata_json or {},
        }

    # --- Plan ---

    async def save_plan(self, run_id: str, plan) -> dict:  # type: ignore[override]
        from time import time as _t

        latest = await self.get_latest_plan(run_id)
        version = plan.plan_version if latest is None else latest["version"] + 1
        row = PlanRow(
            run_id=run_id, version=version, plan_json=plan.model_dump(),
            created_at=_t(),
        )
        async with self._session() as s:
            s.add(row)
            await s.commit()
        return {"run_id": run_id, "version": version, "plan": plan.model_dump()}

    async def get_latest_plan(self, run_id: str) -> dict | None:  # type: ignore[override]
        async with self._session() as s:
            row = (
                await s.execute(
                    select(PlanRow).where(PlanRow.run_id == run_id)
                    .order_by(PlanRow.version.desc()).limit(1)
                )
            ).scalar_one_or_none()
            if not row:
                return None
            return {"run_id": row.run_id, "version": row.version, "plan": row.plan_json}

    # --- Task ---

    async def save_tasks(self, run_id: str, tasks: list) -> None:  # type: ignore[override]
        async with self._session() as s:
            for t in tasks:
                s.add(self._task_to_row(run_id, t))
            await s.commit()

    async def get_task(self, run_id: str, task_id: str) -> dict | None:  # type: ignore[override]
        async with self._session() as s:
            row = (
                await s.execute(
                    select(TaskRow).where(TaskRow.run_id == run_id, TaskRow.task_id == task_id)
                )
            ).scalar_one_or_none()
            return self._task_to_dict(row) if row else None

    async def list_tasks(self, run_id: str) -> list:  # type: ignore[override]
        async with self._session() as s:
            rows = (
                await s.execute(select(TaskRow).where(TaskRow.run_id == run_id))
            ).scalars().all()
            return [self._task_to_dict(row) for row in rows]

    async def update_task(self, task) -> dict:  # type: ignore[override]
        if isinstance(task, dict):
            return await self._update_task_dict(task)
        async with self._session() as s:
            row = (
                await s.execute(
                    select(TaskRow).where(TaskRow.run_id == task.run_id, TaskRow.task_id == task.task_id)
                )
            ).scalar_one()
            row.status = task.status.value
            row.execution_mode = task.execution_mode
            row.required_skill = task.required_skill
            row.attempt = task.attempt
            row.max_attempts = task.max_attempts
            row.depends_on = task.depends_on
            row.required = int(task.required)
            row.input_json = task.input
            row.output_schema_json = task.output_schema
            row.result_ref = task.result_ref
            row.result_summary = task.result_summary
            row.error = task.error
            row.lease_owner = task.lease_owner
            row.lease_expires_at = task.lease_expires_at
            row.timeout_seconds = task.timeout_seconds
            row.updated_at = task.updated_at
            await s.commit()
        return self._task_to_dict(row)

    async def _update_task_dict(self, task: dict) -> dict:
        async with self._session() as s:
            row = (
                await s.execute(
                    select(TaskRow).where(
                        TaskRow.run_id == task["run_id"], TaskRow.task_id == task["task_id"]
                    )
                )
            ).scalar_one()
            for k, v in task.items():
                if k in ("run_id", "task_id"):
                    continue
                mapping = {"input": "input_json", "output_schema": "output_schema_json"}
                col = mapping.get(k, k)
                if hasattr(row, col):
                    setattr(row, col, v)
            await s.commit()
        return self._task_to_dict(row)

    async def task_successors(self, run_id: str, task_id: str) -> list:  # type: ignore[override]
        async with self._session() as s:
            rows = (
                await s.execute(
                    select(TaskRow).where(TaskRow.run_id == run_id)
                )
            ).scalars().all()
            result = [self._task_to_dict(r) for r in rows if task_id in (r.depends_on or [])]
            return result

    @staticmethod
    def _task_to_row(run_id: str, t) -> TaskRow:
        if isinstance(t, dict):
            return TaskRow(
                task_id=t["task_id"],
                run_id=t.get("run_id") or run_id,
                description=t.get("description", ""),
                status=t.get("status", "pending"),
                execution_mode=t.get("execution_mode", "local_react"),
                required_skill=t.get("required_skill"),
                attempt=t.get("attempt", 0),
                max_attempts=t.get("max_attempts", 3),
                depends_on=list(t.get("depends_on", [])),
                required=int(bool(t.get("required", True))),
                input_json=t.get("input", {}) or {},
                output_schema_json=t.get("output_schema", {}) or {},
                timeout_seconds=t.get("timeout_seconds", 300),
                created_at=t.get("created_at", t.get("_now", 0)),
                updated_at=t.get("updated_at", t.get("_now", 0)),
            )
        return TaskRow(
            task_id=t.id,
            run_id=run_id, description=t.description, status=t.status.value
            if hasattr(t.status, "value") else t.status,
            execution_mode=t.execution_mode, required_skill=t.required_skill,
            attempt=t.attempt,
            max_attempts=t.max_attempts, depends_on=list(t.depends_on),
            required=int(t.required), input_json=t.input, output_schema_json=t.output_schema,
            timeout_seconds=t.timeout_seconds, created_at=t.created_at, updated_at=t.updated_at,
        )

    @staticmethod
    def _task_to_dict(row: TaskRow) -> dict:
        return {
            "run_id": row.run_id, "task_id": row.task_id, "description": row.description,
            "status": row.status, "execution_mode": row.execution_mode,
            "required_skill": row.required_skill, "attempt": row.attempt,
            "max_attempts": row.max_attempts, "depends_on": row.depends_on or [],
            "required": bool(row.required), "input": row.input_json or {},
            "output_schema": row.output_schema_json or {}, "result_ref": row.result_ref,
            "result_summary": row.result_summary, "error": row.error,
            "lease_owner": row.lease_owner, "lease_expires_at": row.lease_expires_at,
            "timeout_seconds": row.timeout_seconds, "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    # --- Step ---

    async def append_step(self, step) -> dict:  # type: ignore[override]
        row = StepRow(
            step_id=step.step_id, run_id=step.run_id, task_id=step.task_id,
            step_type=step.step_type.value if hasattr(step.step_type, "value") else str(step.step_type),
            name=step.name, status=step.status.value, input_ref=step.input_ref,
            output_ref=step.output_ref, error=step.error, started_at=step.started_at,
            finished_at=step.finished_at, duration_ms=step.duration_ms,
            created_at=step.created_at,
        )
        async with self._session() as s:
            s.add(row)
            await s.commit()
        return {"step_id": row.step_id, "status": row.status}

    async def list_steps(self, run_id: str, *, task_id: str | None = None) -> list:  # type: ignore[override]
        async with self._session() as s:
            stmt = select(StepRow).where(StepRow.run_id == run_id)
            if task_id:
                stmt = stmt.where(StepRow.task_id == task_id)
            rows = (await s.execute(stmt.order_by(StepRow.created_at))).scalars().all()
            return [
                {
                    "step_id": r.step_id, "task_id": r.task_id, "step_type": r.step_type,
                    "name": r.name, "status": r.status, "input_ref": r.input_ref,
                    "output_ref": r.output_ref, "error": r.error, "started_at": r.started_at,
                    "finished_at": r.finished_at, "duration_ms": r.duration_ms,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    # --- Events ---

    async def append_event(self, *, run_id: str, event_type: str, task_id: str | None,
                           payload: dict[str, Any] | None) -> None:  # type: ignore[override]
        from time import time as _t

        row = EventRow(run_id=run_id, event_type=event_type, task_id=task_id,
                       payload=payload, created_at=_t())
        async with self._session() as s:
            s.add(row)
            await s.commit()

    async def list_events(self, run_id: str) -> list:  # type: ignore[override]
        async with self._session() as s:
            rows = (
                await s.execute(
                    select(EventRow).where(EventRow.run_id == run_id).order_by(EventRow.seq)
                )
            ).scalars().all()
            return [
                {"seq": r.seq, "event_type": r.event_type, "task_id": r.task_id,
                 "payload": r.payload, "created_at": r.created_at}
                for r in rows
            ]

    # --- Agent Registry ---

    async def register(self, record: AgentRegistryRecord) -> AgentRegistryRecord:  # type: ignore[override]
        async with self._session() as s:
            row = RegistryRow(
                agent_id=record.agent_id, name=record.name, description=record.description,
                card_url=record.card_url, endpoint=record.endpoint, skills=record.skills,
                status=record.status, version=record.version,
                last_heartbeat=record.last_heartbeat, tenant_id=record.tenant_id,
            )
            s.add(row)
            await s.commit()
        return record

    async def deregister(self, agent_id: str) -> None:  # type: ignore[override]
        async with self._session() as s:
            row = (await s.execute(select(RegistryRow).where(RegistryRow.agent_id == agent_id))).scalar_one_or_none()
            if row:
                await s.delete(row)
                await s.commit()

    async def get_agent(self, agent_id: str) -> dict | None:  # type: ignore[override]
        async with self._session() as s:
            row = (await s.execute(select(RegistryRow).where(RegistryRow.agent_id == agent_id))).scalar_one_or_none()
            return self._reg_to_dict(row) if row else None

    async def list_agents(self, *, skill: str | None = None, status: str | None = None) -> list:  # type: ignore[override]
        async with self._session() as s:
            stmt = select(RegistryRow)
            if status:
                stmt = stmt.where(RegistryRow.status == status)
            rows = (await s.execute(stmt)).scalars().all()
            result = [self._reg_to_dict(r) for r in rows]
            if skill:
                result = [r for r in result if skill in r["skills"]]
            return result

    async def update_agent(self, record: AgentRegistryRecord) -> AgentRegistryRecord:  # type: ignore[override]
        async with self._session() as s:
            row = (await s.execute(select(RegistryRow).where(RegistryRow.agent_id == record.agent_id))).scalar_one()
            row.name = record.name
            row.description = record.description
            row.card_url = record.card_url
            row.endpoint = record.endpoint
            row.skills = record.skills
            row.status = record.status
            row.version = record.version
            row.last_heartbeat = record.last_heartbeat
            row.tenant_id = record.tenant_id
            await s.commit()
        return record

    @staticmethod
    def _reg_to_dict(row: RegistryRow) -> dict:
        return {
            "agent_id": row.agent_id, "name": row.name, "description": row.description,
            "card_url": row.card_url, "endpoint": row.endpoint, "skills": row.skills or [],
            "status": row.status, "version": row.version, "last_heartbeat": row.last_heartbeat,
            "tenant_id": row.tenant_id,
        }

    # --- Tool call idempotency ---

    async def tool_call_has_run(self, idempotency_key: str) -> bool:  # type: ignore[override]
        async with self._session() as s:
            row = (await s.execute(select(ToolCallRow).where(ToolCallRow.idempotency_key == idempotency_key))).scalar_one_or_none()
            return row is not None

    async def record_tool_call(self, *, idempotency_key: str, task_id: str | None,
                               tool_name: str, status: str, result: dict | None,
                               error: dict | None) -> None:  # type: ignore[override]
        from time import time as _t

        row = ToolCallRow(idempotency_key=idempotency_key, task_id=task_id,
                          tool_name=tool_name, status=status, result=result,
                          error=error, created_at=_t())
        async with self._session() as s:
            s.merge(row)
            await s.commit()

    # --- A2A tracking ---

    async def upsert_a2a_task(self, *, a2a_task_id: str, run_id: str, task_id: str,
                              agent_id: str, status: str, message: dict,
                              artifacts: list | None, error: dict | None) -> None:  # type: ignore[override]
        from time import time as _t

        now = _t()
        async with self._session() as s:
            row = (
                await s.execute(
                    select(A2ATaskRow).where(A2ATaskRow.run_id == run_id, A2ATaskRow.task_id == task_id)
                )
            ).scalar_one_or_none()
            if row is None:
                row = A2ATaskRow(a2a_task_id=a2a_task_id, run_id=run_id, task_id=task_id,
                                 agent_id=agent_id, status=status, message=message,
                                 artifacts=artifacts or [], error=error,
                                 created_at=now, updated_at=now)
                s.add(row)
            else:
                row.a2a_task_id = a2a_task_id
                row.status = status
                row.message = message
                row.artifacts = artifacts or []
                row.error = error
                row.updated_at = now
            await s.commit()

    async def get_a2a_task(self, run_id: str, task_id: str) -> dict | None:  # type: ignore[override]
        async with self._session() as s:
            row = (
                await s.execute(
                    select(A2ATaskRow).where(A2ATaskRow.run_id == run_id, A2ATaskRow.task_id == task_id)
                )
            ).scalar_one_or_none()
            if not row:
                return None
            return {
                "a2a_task_id": row.a2a_task_id, "run_id": row.run_id, "task_id": row.task_id,
                "agent_id": row.agent_id, "status": row.status, "message": row.message,
                "artifacts": row.artifacts or [], "error": row.error,
                "created_at": row.created_at, "updated_at": row.updated_at,
            }