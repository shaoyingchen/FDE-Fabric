"""状态转换测试（文档附录 §4 状态模型）。"""

import pytest

from app.domain.models import RunStatus, TaskStatus
from app.domain.transitions import (
    TransitionError,
    assert_run_transition,
    assert_task_transition,
)


def test_run_transition_valid():
    assert_run_transition(RunStatus.CREATED, RunStatus.RUNNING)
    assert_run_transition(RunStatus.RUNNING, RunStatus.SUCCEEDED)
    assert_run_transition(RunStatus.RUNNING, RunStatus.FAILED)
    assert_run_transition(RunStatus.RUNNING, RunStatus.CANCELLED)
    assert_run_transition(RunStatus.WAITING_APPROVAL, RunStatus.RUNNING)


def test_run_transition_terminal_is_fixed():
    with pytest.raises(TransitionError):
        assert_run_transition(RunStatus.SUCCEEDED, RunStatus.RUNNING)
    with pytest.raises(TransitionError):
        assert_run_transition(RunStatus.FAILED, RunStatus.CANCELLED)


def test_task_transition_valid():
    assert_task_transition(TaskStatus.PENDING, TaskStatus.READY)
    assert_task_transition(TaskStatus.READY, TaskStatus.RUNNING)
    assert_task_transition(TaskStatus.RUNNING, TaskStatus.RETRY_WAIT)
    assert_task_transition(TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
    assert_task_transition(TaskStatus.RUNNING, TaskStatus.FAILED)
    assert_task_transition(TaskStatus.BLOCKED, TaskStatus.SKIPPED)


def test_task_transition_invalid():
    with pytest.raises(TransitionError):
        assert_task_transition(TaskStatus.SUCCEEDED, TaskStatus.RUNNING)
    with pytest.raises(TransitionError):
        assert_task_transition(TaskStatus.PENDING, TaskStatus.SUCCEEDED)