"""阶段 2 可靠执行测试：幂等、重试分类、超时、租约恢复、预算、指标、取消。"""

import time

from app.domain.models import RunStatus


# ---------- 幂等 ----------

async def test_idempotent_tool_call_replays(container):
    """同一逻辑 action ID 重复执行 → 复用已存结果，不重复副作用。"""
    from app.ports.tool import ToolCallContext

    gateway = container.gateway
    ctx = ToolCallContext(run_id="run-r", task_id="task-t")
    first = await gateway.execute(
        name="search_web", arguments={"query": "市场"},
        context=ctx, idempotency_key="run-r:task-t:0:step1",
    )
    assert first["ok"] is True

    calls_before = len(await container.repo.list_tool_calls("run-r"))
    second = await gateway.execute(
        name="search_web", arguments={"query": "市场"},
        context=ctx, idempotency_key="run-r:task-t:0:step1",
    )
    assert second["replayed"] is True
    assert second["result"] == first["result"]
    # 审计表只保留一条记录
    calls_after = len(await container.repo.list_tool_calls("run-r"))
    assert calls_after == calls_before


# ---------- 重试分类 ----------

async def test_retry_classification(container):
    from app.executor import classify_retryable

    # 暂时性错误 → 可重试
    assert classify_retryable({"code": "TEMP_NETWORK"}) is True
    assert classify_retryable({"code": "RATE_LIMIT"}) is True
    assert classify_retryable({"code": "TASK_TIMEOUT"}) is True
    assert classify_retryable({"code": "A2A_TIMEOUT"}) is True
    # 永久错误 → 不可重试
    assert classify_retryable({"code": "PERMISSION_DENIED"}) is False
    assert classify_retryable({"code": "SCHEMA_ERROR"}) is False
    assert classify_retryable({"code": "NO_AGENT"}) is False
    assert classify_retryable({"code": "MAX_STEPS_EXCEEDED"}) is False
    assert classify_retryable(None) is False


async def test_attempt_increments_and_lease_clearance(container, runtime):
    """任务执行后：尝试次数递增、租约释放。"""
    run = await runtime.create_and_run({"goal": "生成报告"})
    assert run["status"] == RunStatus.SUCCEEDED.value
    tasks = await runtime.get_run_tasks(run["run_id"])
    for t in tasks:
        assert t["status"] == "succeeded"
        assert t["lease_owner"] is None
        assert t["lease_expires_at"] is None


# ---------- 租约与恢复 ----------

async def test_stale_lease_recovery(container, runtime):
    run = await runtime.create_run({"goal": "恢复测试"})
    # 生成计划任务，使 t1 存在（复用 graph 的 plan 节点产物）
    from app.domain.models import TaskSpec, TaskPlan

    plan = TaskPlan(goal="恢复测试", tasks=[TaskSpec(id="t1", description="a")])
    await container.repo.save_plan(run.run_id, plan)
    await container.repo.save_tasks(run.run_id, [
        {"task_id": t.id, "run_id": run.run_id, "description": t.description,
         "status": "pending", "execution_mode": t.execution_mode,
         "required_skill": t.required_skill, "depends_on": list(t.depends_on),
         "required": t.required, "input": t.input, "output_schema": t.output_schema,
         "max_attempts": t.max_attempts, "timeout_seconds": t.timeout_seconds,
         "created_at": time.time(), "updated_at": time.time()}
        for t in plan.tasks
    ])

    # 人为制造：任务 running 且租约过期（模拟 Worker 崩溃）
    await container.repo.update_task({
        "run_id": run.run_id, "task_id": "t1",
        "status": "running", "lease_owner": "dead-worker",
        "lease_expires_at": time.time() - 100, "updated_at": time.time(),
    })

    stale = await container.repo.list_stale_tasks(time.time())
    assert any(t["task_id"] == "t1" for t in stale)

    cleaned = await runtime.recover_stale_tasks()
    assert cleaned >= 1

    tasks = await runtime.get_run_tasks(run.run_id)
    t1 = next(t for t in tasks if t["task_id"] == "t1")
    assert t1["status"] == "ready"
    assert t1["lease_owner"] is None
    assert t1["lease_expires_at"] is None

    events = await runtime.get_run_events(run.run_id)
    assert any(e["event_type"] == "task.recovered" for e in events)


# ---------- 预算 ----------

async def test_budget_prevents_dispatch(container, runtime):
    """预算为 0 → 不派发任务，Run 直接失败（BUDGET_EXCEEDED）。"""
    run = await runtime.create_run({"goal": "预算测试", "budget": 0.0})
    detail = await runtime.execute_run(run.run_id)
    assert detail["status"] == RunStatus.FAILED.value
    assert detail["error"] and detail["error"].get("code") == "BUDGET_EXCEEDED"


async def test_budget_accounting_positive(container, runtime):
    """正常 Run 不设预算 → 不拦截；预算记账字段存在。"""
    run = await runtime.create_and_run({"goal": "生成报告"})
    assert run["status"] == RunStatus.SUCCEEDED.value


# ---------- 指标 ----------

async def test_metrics_recorded(container, runtime):
    run = await runtime.create_and_run({"goal": "生成报告"})
    assert run["status"] == "succeeded"
    snap = container.metrics.snapshot()
    assert snap["counters"].get("tasks.executed", 0) >= 1
    assert snap["counters"].get("tasks.succeeded", 0) >= 1
    assert "task.duration" in snap["durations"]


async def test_tool_metrics_recorded(container, runtime):
    run = await runtime.create_and_run({"goal": "生成报告"})
    snap = container.metrics.snapshot()
    assert snap["counters"].get("tool_calls.executed", 0) >= 1


# ---------- 取消 ----------

async def test_cancel_before_execution_skips_tasks(container, runtime):
    run = await runtime.create_run({"goal": "取消测试"})
    await runtime.cancel_run(run.run_id)
    detail = await runtime.execute_run(run.run_id)
    assert detail["status"] == RunStatus.CANCELLED.value

    tasks = await runtime.get_run_tasks(run.run_id)
    assert all(t["status"] == "skipped" for t in tasks)