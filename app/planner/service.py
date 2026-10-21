"""Planner — 将目标转换为 DAG 计划，并做 DAG 校验与重规划占位。"""

from __future__ import annotations

from typing import Any

from ..domain.models import RunCreateRequest, TaskPlan, TaskSpec
from ..ports.model import ModelProvider
from .dag import validate_dag


class PlannerService:
    def __init__(self, model: ModelProvider) -> None:
        self._model = model

    async def build_plan(
        self, request: RunCreateRequest | dict | str
    ) -> TaskPlan:
        """调用 ModelProvider 生成任务 DAG（model_profile=planner）。

        兼容 RunCreateRequest / dict / goal 字符串三种调用形态。
        """
        if isinstance(request, str):
            goal = request
        elif isinstance(request, dict):
            goal = request.get("goal", "")
        else:
            goal = request.goal

        raw = await self._model.generate_structured(
            system_prompt="你是任务规划器，将目标拆解为可执行的 DAG。",
            input_data={"goal": goal},
            output_schema={"goal": "string", "tasks": "list"},
            model_profile="planner",
        )
        plan = TaskPlan(
            goal=raw.get("goal", goal),
            tasks=[TaskSpec(**t) for t in raw.get("tasks", [])],
            plan_version=1,
        )
        validate_dag(plan)
        return plan