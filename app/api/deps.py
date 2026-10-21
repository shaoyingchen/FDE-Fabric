"""依赖装配 — 组装 Repository / Model / Tool / Agent / Runtime 的单一入口。"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass

from ..adapters.agents import A2AClient, LocalAgentInvoker, RegistryService
from ..adapters.models import DeterministicModelProvider
from ..adapters.storage.sqlite_repository import SqliteRepository
from ..adapters.tools import LocalToolRegistry, ToolGateway
from ..executor import TaskRunner
from ..observability import Metrics, single_metrics
from ..planner import PlannerService
from ..runtime import RuntimeService
from ..scheduler import Dispatcher


@dataclass
class Container:
    repo: SqliteRepository
    runtime: RuntimeService
    registry: RegistryService
    a2a: A2AClient
    tools: LocalToolRegistry
    gateway: ToolGateway
    metrics: Metrics


def build_container(
    database_url: str,
    *,
    worker_id: str | None = None,
    retry_backoff_base: float | None = None,
    retry_max_wait: float | None = None,
    metrics: Metrics | None = None,
) -> Container:
    """构造模块化单体全部依赖。

    database_url 示例: "sqlite+aiosqlite:///./fde.db"
    """
    repo = SqliteRepository(database_url)

    a2a = A2AClient()
    registry = RegistryService(repo=repo, a2a=a2a)

    model = DeterministicModelProvider()
    tools = LocalToolRegistry.with_defaults()
    LocalToolRegistry.bind_default_handlers(tools)
    _metrics = metrics or single_metrics
    gateway = ToolGateway(registry=tools, repo=repo, metrics=_metrics)

    if worker_id is None:
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
    if retry_backoff_base is None:
        retry_backoff_base = float(os.environ.get("FDE_RETRY_BACKOFF", "0.3"))
    if retry_max_wait is None:
        retry_max_wait = float(os.environ.get("FDE_RETRY_MAX_WAIT", "30"))

    local_invoker = LocalAgentInvoker(model=model, tool_gateway=gateway)
    runner = TaskRunner(
        repo=repo, local_invoker=local_invoker, a2a_client=a2a,
    )
    planner = PlannerService(model=model)
    dispatcher = Dispatcher(max_concurrency=3)

    runtime = RuntimeService(
        repo=repo, planner=planner, dispatcher=dispatcher,
        runner=runner, registry=registry, model=model,
        worker_id=worker_id,
        retry_backoff_base=retry_backoff_base,
        retry_max_wait=retry_max_wait,
        metrics=_metrics,
    )
    return Container(
        repo=repo, runtime=runtime, registry=registry, a2a=a2a,
        tools=tools, gateway=gateway, metrics=_metrics,
    )