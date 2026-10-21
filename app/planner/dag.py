"""DAG 校验与就绪任务计算（文档附录 §5 算法，线程安全纯函数）。"""

from __future__ import annotations

from collections.abc import Iterable
from graphlib import CycleError, TopologicalSorter

from ..domain.models import TaskPlan


class DagError(ValueError):
    pass


def validate_dag(plan: TaskPlan) -> None:
    """校验 DAG：重复 ID、自依赖、未知依赖、环路。"""
    tasks = plan.tasks
    task_ids = {t.id for t in tasks}
    if len(task_ids) != len(tasks):
        raise DagError("存在重复任务 ID")

    dependencies: dict[str, set[str]] = {}
    for task in tasks:
        deps = set(task.depends_on)
        if task.id in deps:
            raise DagError(f"任务 {task.id} 存在自依赖")
        unknown = deps - task_ids
        if unknown:
            raise DagError(f"任务 {task.id} 依赖未知任务: {sorted(unknown)}")
        dependencies[task.id] = deps

    try:
        sorted_ids = list(TopologicalSorter(dependencies).static_order())
    except CycleError as exc:
        raise DagError(f"检测到环路依赖: {exc}") from exc
    if len(sorted_ids) != len(task_ids):
        raise DagError("检测到环路依赖")
    plan  # noqa


def get_ready_tasks(tasks: list[dict]) -> list[dict]:
    """返回依赖已满足、可立即执行的待运行任务。

    入参为 task dict（含 status/depends_on）。返回原任务副本列表；有上游失败/阻塞时
    将受影响任务置为 blocked（原地修改）。
    """
    by_id = {t["task_id"]: t for t in tasks}
    ready: list[dict] = []
    for task in tasks:
        if task["status"] not in ("pending", "ready"):
            continue
        deps = [by_id[d] for d in task.get("depends_on", []) if d in by_id]
        if any(d["status"] == "failed" for d in deps):
            task["status"] = "blocked"
            continue
        if all(d["status"] == "succeeded" for d in deps):
            ready.append(task)
    return ready


def ready_tasks_after(task_id: str, tasks: list[dict]) -> list[dict]:
    """获取依赖该 task 的直接后继（幂等重跑局部用）。"""
    return [t for t in tasks if task_id in t.get("depends_on", [])]