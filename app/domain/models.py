"""领域模型与状态机 — 遵循设计文档第 4 节状态模型与附录 4.1 领域对象骨架。"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepType(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    A2A = "a2a"
    VALIDATE = "validate"
    ARTIFACT = "artifact"
    RECOVERY = "recovery"


class TaskSpec(BaseModel):
    """Planner 产出的调度单元（附录 4.1 TaskSpec）。"""

    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    execution_mode: str = "local_react"  # local_react / a2a / deterministic
    required_skill: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = 3
    timeout_seconds: int = 300
    required: bool = True


class TaskPlan(BaseModel):
    plan_version: int = 1
    goal: str
    tasks: list[TaskSpec]

    def task_ids(self) -> set[str]:
        return {t.id for t in self.tasks}


class RunRecord(BaseModel):
    run_id: str
    status: RunStatus = RunStatus.CREATED
    goal: str = ""
    plan_version: int = 0
    budget: float | None = None
    max_steps: int = 100
    deadline: str | None = None
    error: dict[str, Any] | None = None
    final_summary: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(BaseModel):
    """Task 三种来源统一：self.task_id / run_id 关联。"""

    run_id: str
    task_id: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    execution_mode: str = "local_react"
    required_skill: str | None = None
    attempt: int = 0
    max_attempts: int = 3
    depends_on: list[str] = Field(default_factory=list)
    required: bool = True
    input: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    result_ref: str | None = None  # artifact id or inline result
    result_summary: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    lease_owner: str | None = None
    lease_expires_at: float | None = None
    timeout_seconds: int = 300
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class StepRecord(BaseModel):
    step_id: str
    run_id: str
    task_id: str | None = None
    step_type: StepType = StepType.LLM
    name: str = ""
    status: StepStatus = StepStatus.PENDING
    input_ref: dict[str, Any] | None = None
    output_ref: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_at: float | None = None
    finished_at: float | None = None
    duration_ms: float | None = None
    created_at: float = Field(default_factory=time.time)


class AgentRegistryRecord(BaseModel):
    """附录 8.2 Registry 字段。"""

    agent_id: str
    name: str
    description: str = ""
    card_url: str = ""
    endpoint: str = ""
    skills: list[str] = Field(default_factory=list)
    status: str = "registered"  # registered / healthy / unhealthy / draining / offline
    version: str = ""
    last_heartbeat: float | None = None
    tenant_id: str = "default"


class RunCreateRequest(BaseModel):
    goal: str
    max_steps: int = 100
    budget: float | None = None
    deadline: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2ATaskRecord(BaseModel):
    """A2A Task 跟踪 — 远程委派的任务对象（概念层，非完整协议 schema）。"""

    a2a_task_id: str
    run_id: str
    task_id: str
    agent_id: str
    status: str = "submitted"  # submitted / working / completed / failed / input-required / canceled
    message: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)