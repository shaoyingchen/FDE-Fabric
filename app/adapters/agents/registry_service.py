"""Agent Registry 服务 — 文档 §8 的 Registry 实现（PostgreSQL 为事实来源时的服务层）。

职责：注册/注销/查询/健康状态更新/按技能解析。注册通过统一入口，避免主 Agent 直查数据库。
"""

from __future__ import annotations

import time
from typing import Any

from ...domain.models import AgentRegistryRecord
from ...ports.agent import A2AClientPort, AgentRegistryPort


class RegistryService(AgentRegistryPort):
    """基于 Repository + A2A Client 健康检查的 Registry 服务。"""

    def __init__(self, repo, a2a: A2AClientPort) -> None:
        self._repo = repo
        self._a2a = a2a

    async def register(self, record: AgentRegistryRecord) -> AgentRegistryRecord:
        record.last_heartbeat = time.time()
        record.status = "registered"
        # 注册后立即做一次健康探测（尽力而为，失败不阻断注册）
        if record.endpoint:
            healthy = await self._a2a.health_check(endpoint=record.endpoint)
            record.status = "healthy" if healthy else "unhealthy"
        return await self._repo.register(record)

    async def deregister(self, agent_id: str) -> None:
        await self._repo.deregister(agent_id)

    async def get_by_id(self, agent_id: str) -> AgentRegistryRecord | None:
        data = await self._repo.get_agent(agent_id)
        return self._to_record(data) if data else None

    async def list_agents(
        self, *, skill: str | None = None, status: str | None = None
    ) -> list[AgentRegistryRecord]:
        data = await self._repo.list_agents(skill=skill, status=status)
        return [self._to_record(d) for d in data]

    async def resolve(
        self, *, required_skill: str | None = None
    ) -> AgentRegistryRecord | None:
        agents = await self._repo.list_agents(skill=required_skill)
        # 优先 healthy
        for status in ("healthy", "registered"):
            for d in agents:
                rec = self._to_record(d)
                if rec.status == status:
                    return rec
        return None

    async def update_health(
        self, agent_id: str, *, healthy: bool, heartbeat: float
    ) -> None:
        rec = await self.get_by_id(agent_id)
        if rec is None:
            return
        rec.status = "healthy" if healthy else "unhealthy"
        rec.last_heartbeat = heartbeat
        await self._repo.update_agent(rec)

    async def probe_all(self) -> None:
        """主动健康检查（后台扫描用）。"""
        for d in await self._repo.list_agents():
            rec = self._to_record(d)
            if rec.endpoint:
                await self.update_health(
                    rec.agent_id,
                    healthy=await self._a2a.health_check(endpoint=rec.endpoint),
                    heartbeat=time.time(),
                )

    @staticmethod
    def _to_record(data: dict[str, Any]) -> AgentRegistryRecord:
        return AgentRegistryRecord(**data)