"""本地工具注册表 — MCP Tool 治理的轻量实现。

文档 4.1 的示例工具：search_web / fetch_page / query_market_db / extract_evidence。
统一经过注册检查 → Schema 校验 → 幂等键执行 → 结果规范化 → 审计。
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine

from ...ports.tool import ToolCallContext, ToolSpec


class LocalToolRegistry:
    """工具注册 + 执行网关。"""

    def __init__(self, tools: list[ToolSpec] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Callable[..., Coroutine]] = {}
        for spec in (tools or []):
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec

    def register_handler(self, name: str, handler: Callable[..., Coroutine]) -> None:
        self._handlers[name] = handler

    async def list_tools(self) -> list[ToolSpec]:
        return list(self._specs.values())

    async def execute(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        context: ToolCallContext,
        idempotency_key: str,
    ) -> dict[str, Any]:
        spec = self._specs.get(name)
        if spec is None:
            return self._error(name, "UNKNOWN_TOOL", f"未注册的工具: {name}")
        handler = self._handlers.get(name)
        if handler is None:
            return self._error(name, "NO_HANDLER", f"工具 {name} 未绑定执行器")

        # Schema 校验（可选 input_schema JSON Schema 子集：required + type=object）
        schema_err = self._validate_schema(spec.input_schema, arguments)
        if schema_err:
            return self._error(name, "SCHEMA_ERROR", schema_err)

        try:
            raw = await handler(arguments=arguments, context=context, idempotency_key=idempotency_key)
            if isinstance(raw, dict) and raw.get("ok") is False:
                return raw
            return {"ok": True, "tool": name, "result": raw, "meta": {"mode": "local"}}
        except Exception as exc:  # pragma: no cover - 防御性异常边界
            return self._error(name, "EXEC_ERROR", f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _error(tool: str, code: str, message: str) -> dict[str, Any]:
        return {"ok": False, "tool": tool, "error": {"code": code, "message": message}}

    @staticmethod
    def _validate_schema(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
        for field in schema.get("required", []):
            if field not in args:
                return f"缺少必填参数: {field}"
        if schema.get("type") == "object" and not isinstance(args, dict):
            return "参数必须为 object"
        return None

    # --- 默认内置工具 ---

    @classmethod
    def with_defaults(cls) -> "LocalToolRegistry":
        registry = cls()
        registry.register(ToolSpec(name="search_web", description="搜索公开网页",
                                   input_schema={"type": "object", "required": ["query"]}))
        registry.register(ToolSpec(name="fetch_page", description="获取网页内容",
                                   input_schema={"type": "object", "required": ["url"]}))
        registry.register(ToolSpec(name="extract_evidence", description="从文档抽取事实与来源",
                                   input_schema={"type": "object", "required": ["content"]}))
        return registry

    @staticmethod
    def bind_default_handlers(registry: "LocalToolRegistry") -> None:
        async def search_web(*, arguments, context, idempotency_key):
            return {"query": arguments["query"], "results": ["示例结果1", "示例结果2"],
                    "took_ms": 12}

        async def fetch_page(*, arguments, context, idempotency_key):
            return {"url": arguments["url"], "content": "示例页面内容", "took_ms": 8}

        async def extract_evidence(*, arguments, context, idempotency_key):
            return {"facts": ["事实A(来源:1)", "事实B(来源:2)"], "count": 2, "took_ms": 5}

        registry.register_handler("search_web", search_web)
        registry.register_handler("fetch_page", fetch_page)
        registry.register_handler("extract_evidence", extract_evidence)