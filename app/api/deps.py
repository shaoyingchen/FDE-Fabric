"""依赖装配 — 组装 Repository / Model / Tool / Agent / Runtime 的单一入口。"""

from __future__ import annotations

from dataclasses import dataclass

from ..adapters.agents import A2AClient, LocalAgentInvoker, RegistryService
from ..adapters.models import DeterministicModelProvider
from ..adapters.storage.sqlite_repository import SqliteRepository
from ..adapters.tools import LocalToolRegistry
from ..executor import TaskRunner
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


def build_container(database_url: str) -> Container:
    """构造模块化单体全部依赖。

    database_url 示例: "sqlite+aiosqlite:///./fde.db"
    """
    repo = SqliteRepository(database_url)

    a2a = A2AClient()
    registry = RegistryService(repo=repo, a2a=a2a)

    model = DeterministicModelProvider()
    tools = LocalToolRegistry.with_defaults()
    LocalToolRegistry.bind_default_handlers(tools)

    local_invoker = LocalAgentInvoker(model=model, tool_gateway=tools)
    runner = TaskRunner(
        repo=repo, local_invoker=local_invoker, a2a_client=a2a,
    )
    planner = PlannerService(model=model)
    dispatcher = Dispatcher(max_concurrency=3)

    runtime = RuntimeService(
        repo=repo, planner=planner, dispatcher=dispatcher,
        runner=runner, registry=registry, model=model,
    )
    return Container(repo=repo, runtime=runtime, registry=registry, a2a=a2a, tools=tools)