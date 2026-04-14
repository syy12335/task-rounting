from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .common import extract_text, parse_json_object


class NormalAgent:
    def __init__(self, *, llm: Any, system_prompt: str) -> None:
        self.llm = llm
        self.system_prompt = system_prompt

    def run(
        self,
        *,
        task_content: str,
        tasks: dict[str, Any],
        normal_skills_index: str,
        invoke_config: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        rendered_system_prompt = self._render_system_prompt(
            task_content=task_content,
            tasks=tasks,
            normal_skills_index=normal_skills_index,
        )
        llm = self.llm.bind(response_format={"type": "json_object"})

        response = llm.invoke(
            [
                SystemMessage(content=rendered_system_prompt),
                HumanMessage(content="请只输出一个合法 JSON 对象，不要输出解释或 Markdown。"),
            ],
            config=_merge_invoke_config(
                invoke_config,
                run_name="task-router.normal.llm",
                tags=["task-router", "normal"],
            ),
        )
        text = extract_text(response.content if hasattr(response, "content") else str(response))
        payload = parse_json_object(text)

        task_status = str(payload.get("task_status", "")).strip()
        task_result = str(payload.get("task_result", "")).strip()

        return {
            "task_status": task_status,
            "task_result": task_result,
        }

    def _render_system_prompt(
        self,
        *,
        task_content: str,
        tasks: dict[str, Any],
        normal_skills_index: str,
    ) -> str:
        rendered = self.system_prompt
        rendered = _replace_last(rendered, "{{TASK_CONTENT}}", task_content)
        rendered = _replace_last(rendered, "{{TASKS_JSON}}", json.dumps(tasks, ensure_ascii=False, indent=2))
        rendered = _replace_last(rendered, "{{NORMAL_SKILLS_INDEX}}", normal_skills_index)
        return rendered


def _replace_last(text: str, old: str, new: str) -> str:
    head, sep, tail = text.rpartition(old)
    if not sep:
        raise ValueError(f"placeholder not found: {old}")
    return head + new + tail


def _merge_invoke_config(
    base_config: dict[str, Any] | None,
    *,
    run_name: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = dict(base_config or {})

    if run_name:
        config["run_name"] = run_name

    if tags:
        existing_tags = config.get("tags", [])
        if not isinstance(existing_tags, list):
            existing_tags = []
        merged_tags: list[str] = []
        for item in list(existing_tags) + tags:
            value = str(item).strip()
            if value and value not in merged_tags:
                merged_tags.append(value)
        config["tags"] = merged_tags

    if metadata:
        existing_metadata = config.get("metadata", {})
        if not isinstance(existing_metadata, dict):
            existing_metadata = {}
        config["metadata"] = {**existing_metadata, **metadata}

    return config


def run_normal_task(
    *,
    llm: Any,
    system_prompt: str,
    task_content: str,
    tasks: dict[str, Any],
    normal_skills_index: str,
    invoke_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    return NormalAgent(llm=llm, system_prompt=system_prompt).run(
        task_content=task_content,
        tasks=tasks,
        normal_skills_index=normal_skills_index,
        invoke_config=invoke_config,
    )
