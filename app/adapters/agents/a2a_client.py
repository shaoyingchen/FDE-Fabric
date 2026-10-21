"""A2A Client — 远程 Agent 交互（A2A 协议概念层）。

文档 §3/§7：Card 获取、Task 创建/查询/取消、Endpoint 健康检查。
此处实现一个可解析的 A2A 协议子集（JSON over HTTP），并保留协议版本扩展点。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ...ports.agent import A2AClientPort
from ...domain.models import AgentRegistryRecord

logger = logging.getLogger(__name__)

A2A_STATUS_TERMINAL = {"completed", "failed", "canceled"}


class A2AProtocolError(RuntimeError):
    pass


class A2AClient(A2AClientPort):
    """HTTP 版 A2A Client。

    A2A 子集端点（相对 endpoint）:
      GET  /.well-known/agent-card.json   Agent Card
      POST /a2a/tasks/send                创建任务 -> {"taskId", "status"}
      GET  /a2a/tasks/{task_id}           查询任务
      POST /a2a/tasks/{task_id}/cancel    取消任务
      GET  /.health/ready                 健康检查

    完整 A2A 规范（JSON-RPC tasks/*）在后续替换即可，端口契约不变。
    """

    def __init__(self, *, timeout: float = 10.0, base_url: str | None = None) -> None:
        self._timeout = timeout
        self._base = base_url  # 可选：统一代理前缀

    # --- Agent Card ---

    async def fetch_agent_card(self, card_url: str) -> dict[str, Any]:
        url = self._abs(card_url)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise A2AProtocolError("Agent Card 响应不是对象")
        return data

    # --- Task ---

    async def send_task(
        self,
        *,
        endpoint: str,
        message: dict[str, Any],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        endpoint = self._abs(endpoint)
        body: dict[str, Any] = {"message": message}
        if task_id:
            body["taskId"] = task_id
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{endpoint.rstrip('/')}/tasks/send", json=body)
            resp.raise_for_status()
        data = resp.json()
        if "taskId" not in data:
            raise A2AProtocolError("响应缺少 taskId")
        return {"task_id": data["taskId"], "status": data.get("status", "working"),
                "raw": data}

    async def get_task(self, *, endpoint: str, task_id: str) -> dict[str, Any]:
        endpoint = self._abs(endpoint)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{endpoint.rstrip('/')}/tasks/{task_id}")
            resp.raise_for_status()
        data = resp.json()
        return {"task_id": data.get("taskId", task_id),
                "status": data.get("status", "working"),
                "artifacts": data.get("artifacts", []),
                "raw": data}

    async def cancel_task(self, *, endpoint: str, task_id: str) -> dict[str, Any]:
        endpoint = self._abs(endpoint)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{endpoint.rstrip('/')}/tasks/{task_id}/cancel")
            resp.raise_for_status()
        return resp.json()

    async def health_check(self, *, endpoint: str) -> bool:
        endpoint = self._abs(endpoint)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{endpoint.rstrip('/')}/.health/ready")
            return resp.status_code == 200
        except Exception:
            return False

    # --- helpers ---

    def _abs(self, url: str) -> str:
        if self._base:
            return f"{self._base.rstrip('/')}/{url.lstrip('/')}"
        return url

    # --- 便捷：注册记录解析 ---

    async def resolve_agent_card(self, agent: AgentRegistryRecord) -> dict[str, Any]:
        """优先 Card URL，其次 endpoint。"""
        try:
            if agent.card_url:
                return await self.fetch_agent_card(agent.card_url)
            if agent.endpoint:
                return await self.fetch_agent_card(
                    f"{agent.endpoint.rstrip('/')}/.well-known/agent-card.json"
                )
        except Exception as exc:
            logger.warning("解析 Agent(%s) Card 失败: %s", agent.agent_id, exc)
        return {"name": agent.name, "description": agent.description,
                "skills": agent.skills}