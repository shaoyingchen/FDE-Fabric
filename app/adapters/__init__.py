"""adapters 层 — 具体实现（存储 / 模型 / 工具 / Agent）。"""

from .storage.base import get_repository

__all__ = ["get_repository"]