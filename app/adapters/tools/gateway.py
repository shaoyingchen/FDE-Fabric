"""Tool Gateway — 统一工具调用出口（文档附录 §7 + §9.1 幂等）。

链路：注册检查 → Schema 校验（注册表负责） → 幂等键去重 → 实际执行
→ 结果审计（agent_tool_calls 表，含持久化逻辑 action ID）。
"""

from __future__ import annotations

import time
from typing import Any

from ...ports.repository import RepositoryPort
from ...ports.tool import ToolCallContext, ToolExecutor, ToolSpec
from .local_tool_registry import LocalToolRegistry


class ToolGateway:
    """幂等工具网关：复用已成功执行的结果，避免重复副作用。"""

    def __init__(self, registry: LocalToolRegistry, repo: RepositoryPort,
                 metrics=None) -> None:
        self._registry = registry
        self._repo = repo
        self._metrics = metrics

    async def list_tools(self) -> list[ToolSpec]:
        return await self._registry.list_tools()

    async def execute(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        context: ToolCallContext,
        idempotency_key: str,
    ) -> dict[str, Any]:
        started = time.monotonic()
        # 幂等：同逻辑 action ID 已成功 → 直接复用结果
        if await self._repo.tool_call_has_run(idempotency_key):
            cached = await self._repo.get_tool_call_result(idempotency_key)
            if cached and cached.get("status") == "succeeded":
                self._record(name, acked=True)
                return {
                    "ok": True, "tool": name, "result": cached.get("result"),
                    "replayed": True, "meta": {"idempotency_key": idempotency_key},
                }

        result = await self._registry.execute(
            name=name, arguments=arguments, context=context,
            idempotency_key=idempotency_key,
        )
        self._record(name, seconds=time.monotonic() - started)

        # 审计记录（幂等键即持久化的逻辑 action ID）；result 存内层结果便于重放
        await self._repo.record_tool_call(
            idempotency_key=idempotency_key, run_id=context.run_id, task_id=context.task_id,
            tool_name=name, status="succeeded" if result.get("ok") else "failed",
            result=result.get("result") if result.get("ok") else None,
            error=None if result.get("ok") else result.get("error"),
        )
        return result

    def _record(self, name: str, *, acked: bool = False, seconds: float = 0.0) -> None:
        if self._metrics is None:
            return
        self._metrics.inc("tool_calls.acked" if acked else "tool_calls.executed")
        if seconds:
            self._metrics.record_duration("tool.duration", seconds)