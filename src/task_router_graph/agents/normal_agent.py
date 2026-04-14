from __future__ import annotations

import json
from typing import Any, Callable

from jsonschema import ValidationError, validate
from langchain_core.messages import HumanMessage, SystemMessage

from .common import extract_text, parse_json_object


_NORMAL_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "action_kind": {"const": "observe"},
                "tool": {
                    "type": "string",
                    "enum": ["beijing_time", "web_search"],
                },
                "args": {"type": "object"},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": ["action_kind", "tool", "args", "reason"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action_kind": {"const": "finish"},
                "task_status": {"type": "string", "enum": ["done", "failed"]},
                "task_result": {"type": "string", "minLength": 1},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": ["action_kind", "task_status", "task_result", "reason"],
            "additionalProperties": False,
        },
    ],
}

_NORMAL_OUTPUT_CONSTRAINTS: dict[str, Any] = {
    "output_format": "json_object",
    "action_kind_enum": ["observe", "finish"],
    "observe_required": ["action_kind", "tool", "args", "reason"],
    "finish_required": ["action_kind", "task_status", "task_result", "reason"],
    "forbid_additional_properties": True,
}

DEFAULT_MAX_STEPS = 4
DEFAULT_MAX_WEB_SEARCH_CALLS = 2
DEFAULT_MAX_BEIJING_TIME_CALLS = 2


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
        observe_tools: dict[str, Callable[..., Any]],
        max_steps: int = DEFAULT_MAX_STEPS,
        max_web_search_calls: int = DEFAULT_MAX_WEB_SEARCH_CALLS,
        max_beijing_time_calls: int = DEFAULT_MAX_BEIJING_TIME_CALLS,
        invoke_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rendered_system_prompt = self._render_system_prompt(
            task_content=task_content,
            tasks=tasks,
            normal_skills_index=normal_skills_index,
        )
        llm = self.llm.bind(
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "normal_action",
                    "strict": True,
                    "schema": _NORMAL_ACTION_SCHEMA,
                },
            }
        )

        observations: list[dict[str, Any]] = []
        web_search_calls = 0
        beijing_time_calls = 0

        for step in range(1, max(1, int(max_steps)) + 1):
            step_invoke_config = _merge_invoke_config(
                invoke_config,
                run_name="task-router.normal.llm_step",
                tags=["task-router", "normal", f"normal-step:{step}"],
                metadata={"normal_step": step},
            )

            response = llm.invoke(
                [
                    SystemMessage(content=rendered_system_prompt),
                    HumanMessage(
                        content=json.dumps(
                            {
                                "step": step,
                                "observations": observations,
                                "output_constraints": _NORMAL_OUTPUT_CONSTRAINTS,
                                "tool_limits": {
                                    "web_search_remaining": max(0, max_web_search_calls - web_search_calls),
                                    "beijing_time_remaining": max(0, max_beijing_time_calls - beijing_time_calls),
                                },
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    ),
                ],
                config=step_invoke_config,
            )

            text = extract_text(response.content if hasattr(response, "content") else str(response))
            action = parse_json_object(text)

            try:
                _validate_normal_action(action)
            except ValidationError as exc:
                raise ValueError(f"Invalid normal action schema: {exc.message}") from exc

            action_kind = str(action.get("action_kind", "")).strip().lower()
            if action_kind == "finish":
                return {
                    "task_status": str(action.get("task_status", "")).strip(),
                    "task_result": str(action.get("task_result", "")).strip(),
                    "normal_trace": observations,
                }

            tool_name = str(action.get("tool", "")).strip()
            tool_args = action.get("args", {})
            reason = str(action.get("reason", "")).strip()

            if tool_name == "web_search" and web_search_calls >= max_web_search_calls:
                observation_result: Any = (
                    "ERROR: web_search quota exceeded in current normal task. "
                    "Only use web_search when external or time-sensitive facts are truly required."
                )
            elif tool_name == "beijing_time" and beijing_time_calls >= max_beijing_time_calls:
                observation_result = "ERROR: beijing_time quota exceeded in current normal task."
            else:
                tool = observe_tools.get(tool_name)
                if tool is None:
                    observation_result = f"ERROR: normal observe tool is not registered: {tool_name}"
                else:
                    try:
                        observation_result = tool(**tool_args)
                        if tool_name == "web_search":
                            web_search_calls += 1
                        elif tool_name == "beijing_time":
                            beijing_time_calls += 1
                    except Exception as exc:
                        observation_result = f"ERROR: normal observe tool execution failed: tool={tool_name}, error={exc}"

            observation_text = (
                observation_result.strip()
                if isinstance(observation_result, str)
                else json.dumps(observation_result, ensure_ascii=False, indent=2)
            )

            observations.append(
                {
                    "tool": tool_name,
                    "args": tool_args if isinstance(tool_args, dict) else {},
                    "reason": reason,
                    "observation": observation_text,
                }
            )

        return {
            "task_status": "failed",
            "task_result": "normal agent exceeded max_steps without finish action",
            "normal_trace": observations,
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


def _validate_normal_action(action: dict[str, Any]) -> None:
    validate(instance=action, schema=_NORMAL_ACTION_SCHEMA)


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
    observe_tools: dict[str, Callable[..., Any]],
    max_steps: int = DEFAULT_MAX_STEPS,
    invoke_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return NormalAgent(llm=llm, system_prompt=system_prompt).run(
        task_content=task_content,
        tasks=tasks,
        normal_skills_index=normal_skills_index,
        observe_tools=observe_tools,
        max_steps=max_steps,
        invoke_config=invoke_config,
    )
