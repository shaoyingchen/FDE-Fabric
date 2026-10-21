"""状态转换规则 — 统一校验入口（附录 §9.1 状态转换应经过统一校验入口）。"""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

from .models import RunStatus, TaskStatus

_T = TypeVar("_T", bound=StrEnum)


class TransitionError(ValueError):
    pass


_RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.CREATED: {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.RUNNING: {
        RunStatus.WAITING_APPROVAL,
        RunStatus.PAUSED,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.WAITING_APPROVAL: {RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.CANCELLED},
    RunStatus.PAUSED: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}

_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.SKIPPED},
    TaskStatus.READY: {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.SKIPPED},
    TaskStatus.RUNNING: {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.RETRY_WAIT,
        TaskStatus.BLOCKED,
    },
    TaskStatus.RETRY_WAIT: {TaskStatus.READY, TaskStatus.FAILED, TaskStatus.SUCCEEDED},
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.BLOCKED: {TaskStatus.READY, TaskStatus.SKIPPED},
    TaskStatus.SKIPPED: set(),
}


def assert_run_transition(current: RunStatus, target: RunStatus) -> None:
    _assert_transition(current, target, _RUN_TRANSITIONS, "run")


def assert_task_transition(current: TaskStatus, target: TaskStatus) -> None:
    _assert_transition(current, target, _TASK_TRANSITIONS, "task")


def _assert_transition(
    current: StrEnum, target: StrEnum, table: dict, kind: str
) -> None:
    allowed = table.get(current, set())
    if target not in allowed:
        raise TransitionError(
            f"非法{kind}状态转换: {current.value} -> {target.value}"
        )