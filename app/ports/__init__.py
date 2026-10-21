"""ports 层 — 面向接口（Python Protocol），契约先行定义。

对应文档附录 §7：可替换的模型、工具和 Agent 接口。
"""

from .model import ModelProvider, ModelDecision
from .tool import ToolExecutor, ToolSpec
from .agent import AgentInvoker, A2AClientPort, AgentRegistryPort
from .repository import RepositoryPort

__all__ = [
    "ModelProvider",
    "ModelDecision",
    "ToolExecutor",
    "ToolSpec",
    "AgentInvoker",
    "A2AClientPort",
    "AgentRegistryPort",
    "RepositoryPort",
]