"""本地 Agent 执行器 — 局部 ReAct 循环，通过 Tool Gateway 调用 MCP/本地工具。

文档附录 §8 ReActExecutor 的 AgentInvoker 承载实现。
幂等键使用持久化逻辑 action ID：{run_id}:{task_id}:{attempt}:{step}，
同一个逻辑动作重试时复用同一 ID（附录 §8：不是每次重启后重新生成）。
"""

from __future__ import annotations

import time
from typing import Any

from ...ports.model import ModelProvider
from ...ports.tool import ToolExecutor, ToolCallContext


class LocalAgentInvoker:
    """将「本地任务执行」统一为 AgentInvoker 协议输出。"""

    def __init__(
        self,
        *,
        model: ModelProvider,
        tool_gateway: ToolExecutor,
        max_steps: int = 12,
    ) -> None:
        self._model = model
        self._tools = tool_gateway
        self._max_steps = max_steps

    async def invoke(
        self,
        *,
        agent,
        task: dict[str, Any],
        context: dict[str, Any],
        deadline_seconds: int,
    ) -> dict[str, Any]:
        run_id = context.get("run_id")
        task_id = context.get("task_id")
        attempt = task.get("attempt", 0)
        allowed = [s.name for s in await self._tools.list_tools()]
        observations: list[dict[str, Any]] = []

        started = time.monotonic()
        steps = 0
        while steps < self._max_steps:
            if time.monotonic() - started > deadline_seconds:
                return {"status": "timeout",
                        "error": {"code": "TASK_TIMEOUT", "message": "超过截止时间"}}
            decision = await self._model.next_action(
                task=task, observations=observations, allowed_tools=allowed
            )
            if decision.type == "finish":
                return {"status": "succeeded", "result": decision.result}
            if decision.type == "error":
                return {"status": "failed", "error": {"code": "MODEL_ERROR",
                                                      "message": decision.reason}}
            if decision.type != "tool_call":
                return {"status": "failed", "error": {"code": "UNSUPPORTED_ACTION",
                                                      "message": decision.type}}
            if decision.tool not in allowed:
                return {"status": "failed", "error": {"code": "PERMISSION_DENIED",
                                                      "message": f"工具越权: {decision.tool}"}}

            steps += 1
            # 持久化逻辑 action ID：重试同一逻辑动作复用同一 ID（幂等恢复）
            idempotency_key = f"{run_id}:{task_id}:{attempt}:step{steps}"
            obs = await self._tools.execute(
                name=decision.tool,
                arguments=decision.arguments or {},
                context=ToolCallContext(run_id=run_id, task_id=task_id),
                idempotency_key=idempotency_key,
            )
            obs["tool"] = decision.tool
            observations.append(obs)

        return {"status": "failed",
                "error": {"code": "MAX_STEPS_EXCEEDED", "message": "超过最大步骤数"}}