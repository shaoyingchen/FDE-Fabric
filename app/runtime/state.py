"""Global Graph State — 文档附录 §6.1 RuntimeState。"""

from __future__ import annotations

import operator
from typing import Annotated, Any
from typing_extensions import TypedDict


class RuntimeState(TypedDict, total=False):
    run_id: str
    goal: str
    plan_version: int
    plan: dict[str, Any]
    ready_task_ids: list[str]
    completed_task_ids: list[str]
    failed_task_ids: list[str]
    replan_required: bool
    replan_reason: str | None
    final_result_ref: str | None
    error: dict[str, Any] | None
    route: str  # evaluate 决策: continue / replan / finalize / fail
    events: Annotated[list[dict[str, Any]], operator.add]