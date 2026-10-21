"""AgentInvoker / A2A / Registry 协议 — 文档附录 §7 + §8。

AgentInvoker 将「本地 Agent 执行」与「远程 A2A Agent」统一为一个执行后端，
A2AClientPort 封装 A2A 协议交互，AgentRegistryPort 封装 Registry 目录访问。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..domain.models import AgentRegistryRecord


@runtime_checkable
class AgentInvoker(Protocol):
    async def invoke(
        self,
        *,
        agent: AgentRegistryRecord,
        task: dict[str, Any],
        context: dict[str, Any],
        deadline_seconds: int,
    ) -> dict[str, Any]:
        """执行一个 Agent 任务。

        返回规范化结果 {status, result|error, meta}；
        status ∈ succeeded / failed / needs_replan / timeout。
        """
        ...


@runtime_checkable
class A2AClientPort(Protocol):
    async def fetch_agent_card(self, card_url: str) -> dict[str, Any]:
        """获取 Agent Card（well-known 或显式 URL）。"""
        ...

    async def send_task(
        self, *, endpoint: str, message: dict[str, Any],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """创建/发送 A2A Task，返回 {task_id, status}。"""
        ...

    async def get_task(self, *, endpoint: str, task_id: str) -> dict[str, Any]:
        """查询 A2A Task 状态与产物。"""
        ...

    async def cancel_task(self, *, endpoint: str, task_id: str) -> dict[str, Any]:
        """取消 A2A Task。"""
        ...

    async def health_check(self, *, endpoint: str) -> bool:
        """Endpoint 健康检查。"""
        ...


@runtime_checkable
class AgentRegistryPort(Protocol):
    async def register(self, record: AgentRegistryRecord) -> AgentRegistryRecord:
        ...

    async def deregister(self, agent_id: str) -> None:
        ...

    async def get_by_id(self, agent_id: str) -> AgentRegistryRecord | None:
        ...

    async def list_agents(
        self, *, skill: str | None = None, status: str | None = None
    ) -> list[AgentRegistryRecord]:
        ...

    async def resolve(
        self, *, required_skill: str | None = None
    ) -> AgentRegistryRecord | None:
        """按技能解析可用 Agent。优先 healthy。"""
        ...

    async def update_health(
        self, agent_id: str, *, healthy: bool, heartbeat: float
    ) -> None:
        ...