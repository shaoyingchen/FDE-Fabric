# FDE Fabric

**Full-chain Delivery Engine** — 面向多 Agent 的全链路运行时与管控平台。

FDE Fabric 覆盖：Agent Runtime（规划/调度/执行/恢复）、A2A 协作、MCP 工具治理、任务调度、执行追踪、异常恢复与全生命周期管理。

## 快速开始

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m uvicorn app.api.app:create_app --factory --reload --port 8000
```

打开 <http://localhost:8000/> 使用精简控制台，或访问 <http://localhost:8000/docs> 查看 API。

## 数据持久化

默认 SQLite（`fde.db`，`sqlite+aiosqlite://`）。通过环境变量切换真实库：

```powershell
$env:FDE_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/fde"
```

## 运行测试

```powershell
.\.venv\Scripts\python -m pytest -q
```

## 阶段说明

- 阶段 1+3：同步执行 MVP（Run/Task/Step 模型、Planner、DAG 调度、局部 ReAct、SQLite 持久化）+ 远程 Agent 协作（A2A Client、Agent Card 发现、Agent Registry、A2A Task 跟踪）。
- 架构依据：`Agent_Card_A2A_Task_MCP_Tool_Agent_Runtime_架构整理_补充长程Runtime设计.md`。