"""Runtime Graph 服务节点与全局图构建（文档附录 §6.2）。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from langgraph.graph import START, END, StateGraph

from ..adapters.agents import RegistryService
from ..domain.models import TaskSpec
from ..executor import TaskRunner
from ..planner import PlannerService
from ..planner.dag import get_ready_tasks
from ..ports.model import ModelProvider
from ..ports.repository import RepositoryPort
from ..scheduler import Dispatcher
from .state import RuntimeState


@dataclass
class RuntimeServices:
    repo: RepositoryPort
    planner: PlannerService
    dispatcher: Dispatcher
    runner: TaskRunner
    registry: RegistryService
    model: ModelProvider
    max_rounds: int = 20


def _now() -> float:
    return time.time()


async def node_initialize(state: RuntimeState, services: RuntimeServices) -> dict:
    run_id = state["run_id"]
    run = await services.repo.get_run(run_id)
    goal = run["goal"] if run else state.get("goal", "")
    plan = await services.repo.get_latest_plan(run_id)
    return {
        "goal": goal,
        "plan": plan["plan"] if plan else None,
        "plan_version": plan["version"] if plan else 0,
        "replan_required": False,
    }


async def node_plan(state: RuntimeState, services: RuntimeServices) -> dict:
    run_id = state["run_id"]
    plan = state.get("plan")
    if plan is None:
        run = await services.repo.get_run(run_id)
        req = {"goal": run["goal"], "max_steps": 100}
        new_plan = await services.planner.build_plan(req)
        saved = await services.repo.save_plan(run_id, new_plan)
        # 保存任务初始记录
        records = []
        for t in new_plan.tasks:
            records.append(_spec_to_record(run_id, t))
        await services.repo.save_tasks(run_id, records)
        plan = new_plan.model_dump()
    return {"plan": plan}


def _spec_to_record(run_id: str, spec: TaskSpec) -> dict:
    return {
        "run_id": run_id,
        "task_id": spec.id,
        "description": spec.description,
        "status": "pending",
        "execution_mode": spec.execution_mode,
        "depends_on": list(spec.depends_on),
        "required": spec.required,
        "input": spec.input,
        "output_schema": spec.output_schema,
        "max_attempts": spec.max_attempts,
        "timeout_seconds": spec.timeout_seconds,
        "created_at": _now(),
        "updated_at": _now(),
    }


async def node_dispatch(state: RuntimeState, services: RuntimeServices) -> dict:
    """并发执行所有就绪任务，写库并统计事件。"""
    run_id = state["run_id"]
    tasks = await services.repo.list_tasks(run_id)

    async def run_one(task: dict) -> dict:
        await services.repo.update_task({
            "run_id": run_id, "task_id": task["task_id"],
            "status": "running", "updated_at": _now(),
        })
        await services.repo.append_event(
            run_id=run_id, event_type="task.started", task_id=task["task_id"],
            payload={"mode": task.get("execution_mode")},
        )
        # 按任务的 required_skill 解析 Agent（文档附录 §5 伪代码）
        agent = await services.registry.resolve(required_skill=task.get("required_skill"))
        result = await services.runner.execute(
            task=task, agent=agent, run_id=run_id
        )
        patch = {
            "run_id": run_id, "task_id": task["task_id"],
            "status": result.status, "updated_at": _now(),
            "result_ref": None,
            "error": result.error,
        }
        if result.result is not None:
            patch["result_summary"] = result.result
        await services.repo.update_task(patch)
        await services.repo.append_event(
            run_id=run_id, event_type=f"task.{result.status}", task_id=task["task_id"],
            payload={"error": result.error},
        )
        return {**task, **patch}

    updated = await services.dispatcher.dispatch(tasks, run_fn=run_one)
    succeeded = [t["task_id"] for t in updated if t["status"] == "succeeded"]
    failed = [t["task_id"] for t in updated if t["status"] in ("failed", "timeout", "blocked")]
    return {"completed_task_ids": succeeded, "failed_task_ids": failed}


async def node_evaluate(state: RuntimeState, services: RuntimeServices) -> dict:
    """评估进度（文档附录 §6.2 evaluate）：

    1. 还有依赖满足但未执行的任务 → continue；
    2. 有任务失败 → fail（必要时重规划，MVP 直判失败）；
    3. 全部完成 → finalize。

    显式返回 route 决策，避免依赖状态残留字段。
    """
    run_id = state["run_id"]
    tasks = await services.repo.list_tasks(run_id)
    ready = get_ready_tasks([dict(t) for t in tasks])
    if ready:
        return {"route": "continue", "ready_task_ids": [t["task_id"] for t in ready]}

    failed = [t for t in tasks if t["status"] in ("failed", "blocked")]
    if failed:
        return {
            "route": "fail",
            "error": {
                "code": "TASK_FAILED",
                "message": f"{len(failed)} 个任务失败",
                "failed_tasks": [t["task_id"] for t in failed],
            },
        }
    return {"route": "finalize", "ready_task_ids": []}


async def node_finalize(state: RuntimeState, services: RuntimeServices) -> dict:
    run_id = state["run_id"]
    run = await services.repo.get_run(run_id)
    if run is None:
        return {}
    tasks = await services.repo.list_tasks(run_id)
    summary = {
        "succeeded": [t["task_id"] for t in tasks if t["status"] == "succeeded"],
        "failed": [t["task_id"] for t in tasks if t["status"] in ("failed", "blocked")],
    }
    await services.repo.update_run({
        "run_id": run_id, "status": "succeeded",
        "final_summary": str(summary), "updated_at": _now(),
    })
    await services.repo.append_event(run_id=run_id, event_type="run.succeeded",
                                     task_id=None, payload=summary)
    return {"final_result_ref": str(summary)}


async def node_fail(state: RuntimeState, services: RuntimeServices) -> dict:
    run_id = state["run_id"]
    error = state.get("error") or {"code": "RUN_FAILED"}
    await services.repo.update_run({
        "run_id": run_id, "status": "failed", "error": error, "updated_at": _now(),
    })
    await services.repo.append_event(run_id=run_id, event_type="run.failed",
                                     task_id=None, payload=error)
    return {}


def _route_after_evaluation(state: RuntimeState) -> str:
    return state.get("route", "finalize")


def build_runtime_graph(services: RuntimeServices, checkpointer=None):
    graph = StateGraph(RuntimeState)

    async def _initialize(s): return await node_initialize(s, services)
    async def _plan(s): return await node_plan(s, services)
    async def _dispatch(s): return await node_dispatch(s, services)
    async def _evaluate(s): return await node_evaluate(s, services)
    async def _replan(s): return {"replan_required": False}
    async def _finalize(s): return await node_finalize(s, services)
    async def _fail(s): return await node_fail(s, services)

    graph.add_node("initialize", _initialize)
    graph.add_node("plan", _plan)
    graph.add_node("dispatch", _dispatch)
    graph.add_node("evaluate", _evaluate)
    graph.add_node("replan", _replan)
    graph.add_node("finalize", _finalize)
    graph.add_node("fail", _fail)

    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "plan")
    graph.add_edge("plan", "dispatch")
    graph.add_edge("dispatch", "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        _route_after_evaluation,
        {
            "continue": "dispatch",
            "replan": "plan",
            "finalize": "finalize",
            "fail": "fail",
        },
    )
    graph.add_edge("replan", "plan")
    graph.add_edge("finalize", END)
    graph.add_edge("fail", END)
    kwargs = {"checkpointer": checkpointer} if checkpointer is not None else {}
    return graph.compile(**kwargs)