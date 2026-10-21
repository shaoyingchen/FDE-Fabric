"""executor 包 — 统一任务执行入口（local_react / a2a / deterministic）。"""

from .task_runner import TaskExecutionResult, TaskRunner, classify_retryable

__all__ = ["TaskRunner", "TaskExecutionResult", "classify_retryable"]