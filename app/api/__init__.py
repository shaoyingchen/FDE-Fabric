"""api 包 — FastAPI 层：创建/查询/取消任务、Registry、静态控制台。"""

from .app import create_app

__all__ = ["create_app"]