"""ModelProvider 协议 — 文档附录 §7。

接口第一版实现为确定性/模拟 Provider（可离线验证），后续可切换 OpenAI
等真实模型厂商而不影响上层 Scheduler / Executor。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class ModelDecision(BaseModel):
    """一次 Agent Loop 迭代的决策。"""

    type: str  # finish / tool_call / ask_input / error
    result: dict[str, Any] | None = None
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    reason: str | None = None
    needs_replan: bool = False


@runtime_checkable
class ModelProvider(Protocol):
    name: str = "model_provider"

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        input_data: dict[str, Any],
        output_schema: dict[str, Any],
        model_profile: str,
    ) -> dict[str, Any]:
        """结构化输出，用于 Planner 生成 DAG 计划、Evaluator 判定等。"""
        ...

    async def next_action(
        self,
        *,
        task: dict[str, Any],
        observations: list[dict[str, Any]],
        allowed_tools: list[str],
    ) -> ModelDecision:
        """ReAct 循环的下一步决策。"""
        ...