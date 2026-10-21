"""storage 包 — SQLite（当前）→ PostgreSQL（后续只需换 engine URL）。"""

from .base import get_repository

__all__ = ["get_repository"]