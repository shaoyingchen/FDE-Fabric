"""ToolExecutor 协议 — 统一经过 Tool Gateway：注册检查 → Schema 校验 → 权限 → 预算/超时 → 幂等执行 → 结果规范化 → 审计。"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    execute_mode: str = "local"  # local / mcp
    mcp_server: str | None = None


class ToolCallContext(BaseModel):
    run_id: str | None = None
    task_id: str | None = None
    tenant_id: str = "default"


@runtime_checkable
class ToolExecutor(Protocol):
    async def list_tools(self) -> list[ToolSpec]:
        """返回全部可调用工具描述（含 MCP 工具治理中的注册项）。"""
        ...

    async def execute(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        context: ToolCallContext,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """执行工具。返回规范化结果 {ok, result|error, meta}。"""
        ...