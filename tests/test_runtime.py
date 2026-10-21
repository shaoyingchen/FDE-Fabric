"""Runtime 端到端测试（阶段 1 验收：多步骤任务完整执行、状态、事件、产物）。"""

from app.domain.models import RunStatus


async def test_end_to_end_report_run(runtime):
    run = await runtime.create_and_run({"goal": "生成企业级 AI Agent 市场研究报告"})
    assert run["status"] == RunStatus.SUCCEEDED.value

    tasks = await runtime.get_run_tasks(run["run_id"])
    task_ids = {t["task_id"] for t in tasks}
    assert task_ids == {"t1", "t2", "t3", "t4", "t5"}
    assert all(t["status"] == "succeeded" for t in tasks)

    # DAG 依赖顺序：t4 依赖 t1/t2/t3
    by_id = {t["task_id"]: t for t in tasks}
    assert set(by_id["t4"]["depends_on"]) == {"t1", "t2", "t3"}


async def test_run_progress_and_events(runtime):
    run = await runtime.create_and_run({"goal": "生成报告"})
    detail = await runtime.get_run(run["run_id"])
    assert detail["progress"].endswith("5/5")

    events = await runtime.get_run_events(run["run_id"])
    types = [e["event_type"] for e in events]
    assert "run.created" in types
    assert "run.succeeded" in types
    assert all("task." + t in types for t in ("started", "succeeded"))


async def test_run_artifacts_from_succeeded_tasks(runtime):
    run = await runtime.create_and_run({"goal": "生成报告"})
    artifacts = await runtime.get_run_artifacts(run["run_id"])
    assert len(artifacts) >= 1
    assert all(a["status"] == "succeeded" for a in artifacts)


async def test_cancel_run_before_execution(runtime):
    run = await runtime.create_run({"goal": "将被取消的任务"})
    await runtime.cancel_run(run.run_id)
    got = await runtime.get_run(run.run_id)
    assert got["status"] == "cancelled"


async def test_resume_and_recovery(container, runtime):
    run = await runtime.create_run({"goal": "研究竞争对手"})
    # 模拟进程重启：另一容器从持久化状态恢复
    active = await container.repo.list_active_runs()
    assert run.run_id in [r["run_id"] for r in active]

    recovered = await runtime.recover_active_runs()
    assert run.run_id in recovered
    got = await runtime.get_run(run.run_id)
    assert got["status"] == "succeeded"