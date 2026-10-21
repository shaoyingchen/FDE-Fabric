"""agents 适配器包 — 本地 Agent / A2A 远程 Agent / Agent Registry 服务。"""

from .a2a_client import A2AClient
from .local_agent_invoker import LocalAgentInvoker
from .registry_service import RegistryService

__all__ = ["A2AClient", "LocalAgentInvoker", "RegistryService"]