"""DAG 校验与就绪计算测试（文档附录 §5）。"""

import pytest

from app.domain.models import TaskPlan, TaskSpec
from app.planner.dag import DagError, get_ready_tasks, validate_dag


def _task(task_id, deps=None, status="pending"):
    return {"task_id": task_id, "status": status, "depends_on": deps or []}


def test_validate_linear_dag_ok():
    plan = TaskPlan(goal="g", tasks=[
        TaskSpec(id="t1", description="a"),
        TaskSpec(id="t2", description="b", depends_on=["t1"]),
    ])
    validate_dag(plan)  # 不抛异常


def test_validate_duplicate_id_raises():
    plan = TaskPlan(goal="g", tasks=[
        TaskSpec(id="t1", description="a"),
        TaskSpec(id="t1", description="b"),
    ])
    with pytest.raises(DagError, match="重复"):
        validate_dag(plan)


def test_validate_self_dependency_raises():
    plan = TaskPlan(goal="g", tasks=[
        TaskSpec(id="t1", description="a", depends_on=["t1"]),
    ])
    with pytest.raises(DagError, match="自依赖"):
        validate_dag(plan)


def test_validate_unknown_dependency_raises():
    plan = TaskPlan(goal="g", tasks=[
        TaskSpec(id="t1", description="a"),
        TaskSpec(id="t2", description="b", depends_on=["ghost"]),
    ])
    with pytest.raises(DagError, match="未知任务"):
        validate_dag(plan)


def test_validate_cycle_raises():
    plan = TaskPlan(goal="g", tasks=[
        TaskSpec(id="t1", description="a", depends_on=["t2"]),
        TaskSpec(id="t2", description="b", depends_on=["t1"]),
    ])
    with pytest.raises(DagError, match="环路"):
        validate_dag(plan)


def test_get_ready_tasks_all_deps_satisfied():
    tasks = [
        _task("t1"), _task("t2", deps=["t1"]), _task("t3", deps=["t1", "t2"]),
    ]
    tasks[0]["status"] = "succeeded"
    tasks[1]["status"] = "succeeded"
    ready = get_ready_tasks(tasks)
    assert [t["task_id"] for t in ready] == ["t3"]


def test_get_ready_tasks_blocked_when_dep_failed():
    tasks = [_task("t1"), _task("t2", deps=["t1"])]
    tasks[0]["status"] = "failed"
    ready = get_ready_tasks(tasks)
    assert ready == []
    # 依赖失败 → t2 被标记 blocked
    assert tasks[1]["status"] == "blocked"


def test_get_ready_tasks_returns_parallel_roots():
    tasks = [_task("t1"), _task("t2"), _task("t3", deps=["t1", "t2"])]
    ready = get_ready_tasks(tasks)
    assert {t["task_id"] for t in ready} == {"t1", "t2"}