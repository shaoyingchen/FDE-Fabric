"""确定性 ModelProvider — 用于离线验证整条链路（不依赖外部 LLM API）。

它按文档第 5 节市场研究示例，将「分析目标」结构化为固定 DAG 计划：
T1 市场规模研究 → T2 竞品分析 → T3 技术趋势 → T4 证据核验(依赖 T1/T2/T3) → T5 生成报告(依赖 T4)

真实生产可替换为 OpenAI / ADK 等 ModelProvider 实现，Scheduler/Executor 无需改动。
"""

from __future__ import annotations

import re
from typing import Any

from ...ports.model import ModelDecision

_GOAL_RULES = [
    ("report", "[研究|调研|报告|分析|竞品|报告]"),
    ("research", "[搜|查|研究|调研|采集|收集|证据]"),
    ("extract", "[提取|清洗|解析|归一|抽取]"),
    ("qa", "[问答|答疑|回答|咨询|建议|方案|问题]"),
]


class DeterministicModelProvider:
    name = "deterministic-v1"

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        input_data: dict[str, Any],
        output_schema: dict[str, Any],
        model_profile: str,
    ) -> dict[str, Any]:
        """生成结构化计划（文档 §3.3 示例的 DAG）。"""
        goal = str(input_data.get("goal", "")).strip()
        if model_profile == "planner":
            return await self._plan(goal)
        if model_profile == "evaluator":
            return await self._evaluate(input_data)
        raise ValueError(f"未知 model_profile: {model_profile}")

    async def next_action(
        self,
        *,
        task: dict[str, Any],
        observations: list[dict[str, Any]],
        allowed_tools: list[str],
    ) -> ModelDecision:
        """ReAct 循环：无工具需求直接完成；否则按顺序消费工具。"""
        task_type = task.get("execution_mode") or task.get("type") or "report"
        tool_steps = {
            "research": ["search_web", "fetch_page"],
            "report": ["search_web", "fetch_page", "extract_evidence"],
            "extract": ["extract_evidence"],
            "qa": ["search_web"],
        }.get(task_type, [])

        used = [o.get("tool") for o in observations if o.get("tool")]
        next_tool = next((t for t in tool_steps if t in allowed_tools and t not in used), None)

        if next_tool:
            task_text = task.get("description", "")
            args = {"query": task_text}
            if next_tool == "fetch_page":
                args = {"url": task_text}
            elif next_tool == "extract_evidence":
                args = {"content": task_text}
            return ModelDecision(type="tool_call", tool=next_tool, arguments=args)
        # 完成，返回结构化结果
        result = {
            "task_id": task.get("task_id"),
            "summary": f"完成: {task.get('description', '')}",
            "evidence_count": sum(1 for _ in observations),
        }
        return ModelDecision(type="finish", result=result)

    # --- helpers ---

    async def _plan(self, goal: str) -> dict[str, Any]:
        kind = "report"
        for key, pattern in _GOAL_RULES:
            if re.search(pattern, goal):
                kind = key
                break
        return _DEFAULT_PLANS[kind]

    async def _evaluate(self, input_data: dict[str, Any]) -> dict[str, Any]:
        task = input_data.get("task", {})
        output = input_data.get("output", {})
        accepted = bool(output) and "summary" in output
        return {
            "accepted": accepted,
            "verdict": "accepted" if accepted else "rejected",
            "reason": "输出包含总结字段" if accepted else "输出缺少有效结果",
        }


_DEFAULT_PLANS: dict[str, dict[str, Any]] = {
    "report": {
        "goal": "生成市场研究报告",
        "tasks": [
            {"id": "t1", "description": "市场规模研究", "depends_on": [], "execution_mode": "research"},
            {"id": "t2", "description": "竞品分析", "depends_on": [], "execution_mode": "research"},
            {"id": "t3", "description": "技术趋势研究", "depends_on": [], "execution_mode": "research"},
            {"id": "t4", "description": "证据核验", "depends_on": ["t1", "t2", "t3"], "execution_mode": "extract"},
            {"id": "t5", "description": "生成最终报告", "depends_on": ["t4"], "execution_mode": "report"},
        ],
    },
    "research": {
        "goal": "研究任务",
        "tasks": [
            {"id": "t1", "description": "资料收集", "depends_on": [], "execution_mode": "research"},
            {"id": "t2", "description": "证据整理", "depends_on": ["t1"], "execution_mode": "extract"},
        ],
    },
    "extract": {
        "goal": "数据处理",
        "tasks": [
            {"id": "t1", "description": "数据提取与清洗", "depends_on": [], "execution_mode": "extract"},
        ],
    },
    "qa": {
        "goal": "问答任务",
        "tasks": [
            {"id": "t1", "description": "检索资料", "depends_on": [], "execution_mode": "qa"},
            {"id": "t2", "description": "整理答案", "depends_on": ["t1"], "execution_mode": "report"},
        ],
    },
}