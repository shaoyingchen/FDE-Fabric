"""Runtime Graph 服务节点与全局图构建（文档附录 §6.2）。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import START, END, StateGraph

from ..adapters.agents import RegistryService
from ..domain.models import TaskSpec
from ..executor import TaskRunner, classify_retryable
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
    worker_id: str = "worker-default"
    retry_backoff_base: float = 1.0
    retry_backoff_factor: float = 2.0
    retry_max_wait: float = 60.0
    lease_grace: float = 5.0
    metrics: Any = None
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
        "required_skill": spec.required_skill,
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
    """并发执行所有就绪任务，写库并统计事件。

    阶段 2 增强：
      - 认领租约（lease_owner / lease_expires_at）
      - 可重试错误 → 指数退避重试（RETRY_WAIT → READY）
      - 每次执行计入预算成本；超预算停止派发
      - 取消检查：Run 已取消 → 跳过剩余任务
      - 指标上报
    """
    run_id = state["run_id"]
    run = await services.repo.get_run(run_id)
    if run is None:
        return {"route": "fail", "error": {"code": "RUN_NOT_FOUND"}}
    budget = run.get("budget")
    spent = float((run.get("metadata") or {}).get("budget_spent", 0.0))

    tasks = await services.repo.list_tasks(run_id)

    # 取消检查：若 Run 已取消，剩余待办任务标记 skipped
    if run["status"] == "cancelled":
        updated = []
        for t in tasks:
            if t["status"] in ("pending", "ready"):
                await services.repo.update_task({
                    "run_id": run_id, "task_id": t["task_id"],
                    "status": "skipped", "updated_at": _now(),
                })
            updated.append({**t, "status": "skipped" if t["status"] in ("pending", "ready") else t["status"]})
        return {"route": "finalize"}

    # 预算检查：超预算则不派发新任务，直接判死 Run
    if budget is not None and spent >= float(budget):
        error = {"code": "BUDGET_EXCEEDED",
                 "message": f"预算 ${budget} 已耗尽（已用 ${spent:g}）"}
        await services.repo.update_run({
            "run_id": run_id, "status": "failed", "error": error, "updated_at": _now(),
        })
        await services.repo.append_event(
            run_id=run_id, event_type="run.failed", task_id=None, payload=error,
        )
        return {"route": "fail", "error": error}

    async def run_one(task: dict) -> dict:
        done = False
        attempt = task.get("attempt", 0)
        error = None
        result_summary = None
        end_status = "failed"
        cost = 0.0
        while not done:
            attempt += 1
            # 认领：租约到期时间 = 任务超时 + 宽限
            lease_until = _now() + task.get("timeout_seconds", 300) + services.lease_grace
            await services.repo.update_task({
                "run_id": run_id, "task_id": task["task_id"],
                "status": "running", "attempt": attempt,
                "lease_owner": services.worker_id, "lease_expires_at": lease_until,
                "updated_at": _now(),
            })
            await services.repo.append_event(
                run_id=run_id, event_type="task.started", task_id=task["task_id"],
                payload={"mode": task.get("execution_mode"), "attempt": attempt},
            )
            agent = await services.registry.resolve(required_skill=task.get("required_skill"))
            started_at = _now()
            result = await services.runner.execute(
                task=task, agent=agent, run_id=run_id
            )
            cost += result.cost
            if result.status == "succeeded":
                done = True
                end_status = "succeeded"
                result_summary = result.result
            elif result.retryable and attempt < task.get("max_attempts", 3):
                # 指数退避（有上限），然后回到 READY 重新调度
                wait = min(
                    services.retry_backoff_base * (services.retry_backoff_factor ** (attempt - 1)),
                    services.retry_max_wait,
                )
                error = result.error
                await services.repo.append_event(
                    run_id=run_id, event_type="task.retry_wait", task_id=task["task_id"],
                    payload={"attempt": attempt, "error": error, "wait_s": wait},
                )
                await asyncio.sleep(wait)
                await services.repo.update_task({
                    "run_id": run_id, "task_id": task["task_id"],
                    "status": "retry_wait", "attempt": attempt, "error": error,
                    "updated_at": _now(),
                })
                # 等退避结束置回 ready（单 Worker 内存内直接继续循环）
                await services.repo.update_task({
                    "run_id": run_id, "task_id": task["task_id"],
                    "status": "ready", "updated_at": _now(),
                })
            else:
                done = True
                end_status = "failed" if result.status != "cancelled" else "cancelled"
                error = result.error or {"code": "TASK_FAILED"}
                result_summary = None

        patch = {
            "run_id": run_id, "task_id": task["task_id"],
            "status": end_status, "updated_at": _now(),
            "error": error, "lease_owner": None, "lease_expires_at": None,
        }
        if end_status == "succeeded":
            patch["result_ref"] = f"artifact:{task['task_id']}"
            if result_summary is not None:
                patch["result_summary"] = result_summary
        await services.repo.update_task(patch)
        if services.metrics is not None:
            services.metrics.inc("tasks.executed")
            services.metrics.inc(f"tasks.{end_status}")
            services.metrics.record_duration("task.duration", _now() - started_at)
        await services.repo.append_event(
            run_id=run_id, event_type=f"task.{end_status}", task_id=task["task_id"],
            payload={"error": error, "attempt": attempt, "cost": cost},
        )
        return {**task, **patch, "_cost": cost}

    updated = await services.dispatcher.dispatch(tasks, run_fn=run_one)

    # 预算记账：汇总本轮成本
    if budget is not None:
        new_spent = spent
        for t in updated:
            new_spent += t.get("_cost", 0.0)
        meta = dict(run.get("metadata") or {})
        meta["budget_spent"] = new_spent
        await services.repo.update_run({
            "run_id": run_id, "metadata": meta, "updated_at": _now(),
        })

    succeeded = [t["task_id"] for t in updated if t["status"] == "succeeded"]
    failed = [t["task_id"] for t in updated if t["status"] in ("failed", "blocked", "skipped", "cancelled")]
    return {"completed_task_ids": succeeded, "failed_task_ids": failed, "route": "continue"}


async def node_evaluate(state: RuntimeState, services: RuntimeServices) -> dict:
    """评估进度（文档附录 §6.2 evaluate）：

    1. 还有依赖满足但未执行的任务 → continue；
    2. Run 已被 dispatch 判死（预算/取消）→ 尊重持久化终态，不再覆盖；
    3. 全部完成 → finalize。

    显式返回 route 决策，避免依赖状态残留字段。
    """
    run_id = state["run_id"]
    run = await services.repo.get_run(run_id)
    if run is None:
        return {"route": "fail", "error": {"code": "RUN_NOT_FOUND"}}
    # 尊重 dispatch 已写库的终态（预算耗尽等在 dispatch 层判定）
    if run["status"] == "failed":
        return {"route": "fail", "error": run.get("error") or {"code": "RUN_FAILED"}}
    if run["status"] == "cancelled":
        return {"route": "finalize"}

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
        "skipped": [t["task_id"] for t in tasks if t["status"] == "skipped"],
    }
    # 已取消的 Run 保持 cancelled（不能被标记为成功）
    if run["status"] == "cancelled":
        await services.repo.append_event(run_id=run_id, event_type="run.cancelled",
                                         task_id=None, payload=summary)
        return {"final_result_ref": str(summary)}
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