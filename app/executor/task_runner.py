"""TaskRunner — 按 execution_mode 路由到对应后端并归一化结果。

execution_mode:
  - local_react   : 本地 Agent（ReAct 循环 + Tool Gateway）
  - remote_a2a    : 远程 A2A Agent（A2A Task 跟踪 + 结果归一化 + 轮询）
  - deterministic : 确定性执行（无 LLM），用于测试/固定任务
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from pydantic import BaseModel

from ..domain.models import A2ATaskRecord, AgentRegistryRecord
from ..ports.agent import A2AClientPort, AgentInvoker
from ..ports.repository import RepositoryPort


class TaskExecutionResult(BaseModel):
    status: str  # succeeded / failed / needs_replan / timeout
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    retryable: bool = False  # 可重试错误（暂时性）；永久错误为 False
    cost: float = 0.0        # 本次执行成本（预算记账用）
    meta: dict[str, Any] = {}


# 永久错误码（不可重试）
_PERMANENT_ERRORS = {
    "PERMISSION_DENIED",
    "SCHEMA_ERROR",
    "NO_AGENT",
    "A2A_SEND_ERROR",
    "MODEL_ERROR",
    "DET_ERROR",
    "UNSUPPORTED_ACTION",
    "MAX_STEPS_EXCEEDED",
}


def classify_retryable(error: dict[str, Any] | None) -> bool:
    if not error:
        return False
    return error.get("code") not in _PERMANENT_ERRORS


class TaskRunner:
    def __init__(
        self,
        *,
        repo: RepositoryPort,
        local_invoker: AgentInvoker,
        a2a_client: A2AClientPort,
        a2a_poll_interval: float = 0.3,
        a2a_max_wait: float = 60.0,
        deterministic_handler=None,
    ) -> None:
        self._repo = repo
        self._local = local_invoker
        self._a2a = a2a_client
        self._poll = a2a_poll_interval
        self._max_wait = a2a_max_wait
        self._deterministic = deterministic_handler or self._default_deterministic

    async def execute(
        self,
        *,
        task: dict[str, Any],
        agent: AgentRegistryRecord | None,
        run_id: str,
    ) -> TaskExecutionResult:
        mode = task.get("execution_mode", "local_react")
        context = {"run_id": run_id, "task_id": task["task_id"]}

        if mode == "remote_a2a":
            if agent is None or not agent.endpoint:
                return TaskExecutionResult(status="failed", retryable=False,
                                           error={"code": "NO_AGENT", "message": "缺少远程 Agent 端点"})
            return await self._execute_a2a(task, agent, run_id)

        if mode == "deterministic":
            return await self._run_deterministic(task)

        # local_react 默认
        try:
            result = await asyncio.wait_for(
                self._local.invoke(
                    agent=agent, task=task, context=context,
                    deadline_seconds=task.get("timeout_seconds", 300),
                ),
                timeout=task.get("timeout_seconds", 300),
            )
        except asyncio.TimeoutError:
            return TaskExecutionResult(status="timeout", retryable=True,
                                       error={"code": "TASK_TIMEOUT",
                                              "message": "本地执行超时"})
        status = result.get("status", "failed")
        error = result.get("error")
        return TaskExecutionResult(status=status, result=result.get("result"),
                                   error=error, retryable=classify_retryable(error),
                                   cost=result.get("cost", 0.0),
                                   meta={"mode": "local_react"})

    # --- A2A ---

    async def _execute_a2a(
        self, task: dict[str, Any], agent: AgentRegistryRecord, run_id: str
    ) -> TaskExecutionResult:
        message = {
            "role": "user",
            "content": task.get("description", ""),
            "taskId": task.get("task_id"),
        }
        try:
            sent = await self._a2a.send_task(
                endpoint=agent.endpoint, message=message, task_id=task.get("task_id")
            )
        except Exception as exc:
            return TaskExecutionResult(status="failed", retryable=True,
                                       error={"code": "A2A_SEND_ERROR", "message": str(exc)})

        a2a_task_id = sent["task_id"]
        await self._repo.upsert_a2a_task(
            a2a_task_id=a2a_task_id, run_id=run_id, task_id=task["task_id"],
            agent_id=agent.agent_id, status=sent["status"], message=message,
            artifacts=[], error=None,
        )

        # 轮询到终态
        deadline = time.monotonic() + self._max_wait
        while time.monotonic() < deadline:
            current = await self._a2a.get_task(endpoint=agent.endpoint, task_id=a2a_task_id)
            status = current["status"]
            await self._repo.upsert_a2a_task(
                a2a_task_id=a2a_task_id, run_id=run_id, task_id=task["task_id"],
                agent_id=agent.agent_id, status=status, message=message,
                artifacts=current.get("artifacts", []), error=None,
            )
            if status in ("completed", "failed", "canceled"):
                break
            await asyncio.sleep(self._poll)

        last = await self._repo.get_a2a_task(run_id, task["task_id"]) or {}
        if last.get("status") in ("completed",):
            return TaskExecutionResult(status="succeeded",
                                       result={"a2a_task_id": a2a_task_id,
                                               "artifacts": last.get("artifacts", [])},
                                       meta={"mode": "remote_a2a"})
        if last.get("status") == "failed":
            return TaskExecutionResult(
                status="failed", retryable=False,
                error={"code": "A2A_FAILED",
                       "message": f"远程任务失败: {last.get('error')}"},
                meta={"mode": "remote_a2a", "a2a_task_id": a2a_task_id},
            )
        return TaskExecutionResult(
            status="timeout", retryable=True,
            error={"code": "A2A_TIMEOUT",
                   "message": f"远程任务未在时限内完成: {last.get('status')}"},
            meta={"mode": "remote_a2a", "a2a_task_id": a2a_task_id},
        )

    # --- deterministic ---

    async def _run_deterministic(self, task: dict[str, Any]):
        try:
            if asyncio.iscoroutinefunction(self._deterministic):
                out = await self._deterministic(task)
            else:
                out = self._deterministic(task)
            return TaskExecutionResult(status="succeeded", result=out,
                                       meta={"mode": "deterministic"})
        except Exception as exc:
            return TaskExecutionResult(status="failed", retryable=False,
                                       error={"code": "DET_ERROR",
                                              "message": str(exc)})

    @staticmethod
    async def _default_deterministic(task: dict[str, Any]) -> dict[str, Any]:
        return {"task_id": task.get("task_id"),
                "summary": f"确定性完成: {task.get('description', '')}"}