from __future__ import annotations

import json
from typing import Any, Callable

from jsonschema import ValidationError

from .agent_utils import extract_text, merge_invoke_config, parse_json_object, replace_last
from .memory import AgentMemory, ContextCompressionOptions
from ..schema import CONTROLLER_ACTION_SCHEMA, CONTROLLER_OUTPUT_CONSTRAINTS, validate_controller_action_payload


class ControllerRouteError(ValueError):
    def __init__(self, message: str, *, observations: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.observations = observations or []


class ControllerAgent:
    def __init__(
        self,
        *,
        llm: Any,
        system_prompt: str,
        max_steps: int = 3,
        context_options: ContextCompressionOptions | None = None,
    ) -> None:
        self.llm = llm
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.context_options = context_options or ContextCompressionOptions()

    def run(
        self,
        *,
        user_input: str,
        tasks: dict[str, Any],
        skills_index: str,
        observe_tools: dict[str, Callable[..., Any]],
        invoke_config: dict[str, Any] | None = None,
        recent_rounds_payload: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        rendered_system_prompt = self._render_system_prompt(
            user_input=user_input,
            tasks=tasks,
            skills_index=skills_index,
        )
        llm = self.llm.bind(
            response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "controller_action",
                        "strict": True,
                        "schema": CONTROLLER_ACTION_SCHEMA,
                    },
                }
        )

        memory = AgentMemory(
            llm=self.llm,
            system_prompt=rendered_system_prompt,
            options=self.context_options,
        )
        observations: list[dict[str, Any]] = []

        for step in range(1, self.max_steps + 1):
            step_invoke_config = merge_invoke_config(
                invoke_config,
                run_name="task-router.controller.llm_step",
                tags=["task-router", "controller", f"controller-step:{step}"],
                metadata={"controller_step": step},
            )
            memory.maybe_compress_context(
                step=step,
                recent_rounds_payload=recent_rounds_payload,
                invoke_config=step_invoke_config,
            )
            memory.append_user(
                json.dumps(
                    {
                        "step": step,
                        "observations": observations,
                        "output_constraints": CONTROLLER_OUTPUT_CONSTRAINTS,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            response = llm.invoke(memory.to_langchain_messages(), config=step_invoke_config)

            text = extract_text(response.content if hasattr(response, "content") else str(response))
            memory.append_assistant(text)
            action = parse_json_object(text)

            action_kind = _normalize_action_kind(action)
            if action_kind in {"observe", "generate_task"}:
                action["action_kind"] = action_kind

            try:
                _validate_controller_action(action)
            except ValidationError as exc:
                raise ControllerRouteError(
                    f"Invalid controller action schema: {exc.message}",
                    observations=observations,
                ) from exc

            if action["action_kind"] == "generate_task":
                action["controller_trace"] = observations
                return action

            tool_name = str(action.get("tool", "")).strip()
            tool_args = action.get("args", {})
            reason = str(action.get("reason", "")).strip()

            tool = observe_tools.get(tool_name)
            if tool is None:
                raise ControllerRouteError(
                    f"Observe tool is not registered: {tool_name}",
                    observations=observations,
                )

            try:
                observation_result = tool(**tool_args)
            except Exception as exc:
                raise ControllerRouteError(
                    f"Observe tool execution failed: tool={tool_name}, error={exc}",
                    observations=observations,
                ) from exc

            observation_text = (
                observation_result.strip()
                if isinstance(observation_result, str)
                else json.dumps(observation_result, ensure_ascii=False, indent=2)
            )
            observation_text = memory.trim_tool_observation(
                raw_result=observation_text,
                task_text=user_input,
                user_text=json.dumps(tasks, ensure_ascii=False),
                assistant_text=text,
            )

            observations.append(
                {
                    "tool": tool_name,
                    "args": tool_args,
                    "reason": reason,
                    "observation": observation_text,
                }
            )
            memory.append_tool(observation_text)

        raise ControllerRouteError(
            "ControllerAgent exceeded max_steps without returning generate_task",
            observations=observations,
        )

    def _render_system_prompt(
        self,
        *,
        user_input: str,
        tasks: dict[str, Any],
        skills_index: str,
    ) -> str:
        rendered = self.system_prompt
        rendered = replace_last(rendered, "{{USER_INPUT}}", user_input)
        rendered = replace_last(rendered, "{{ENVIRONMENT_JSON}}", json.dumps(tasks, ensure_ascii=False, indent=2))
        rendered = replace_last(rendered, "{{SKILLS_INDEX}}", skills_index)
        return rendered


def _validate_controller_action(action: dict[str, Any]) -> None:
    validate_controller_action_payload(action)


def _normalize_action_kind(action: dict[str, Any]) -> str:
    raw = str(action.get("action_kind", action.get("action", ""))).strip().lower()
    if raw in {"generate_task", "generate-task", "generate"}:
        return "generate_task"
    if raw in {"observe", "observation"}:
        return "observe"

    has_tool = bool(str(action.get("tool", "")).strip())
    has_task_type = bool(str(action.get("task_type", "")).strip())
    has_task_content = bool(str(action.get("task_content", "")).strip())
    has_task = has_task_type or has_task_content

    if has_tool and not has_task:
        return "observe"
    if has_task and not has_tool:
        return "generate_task"

    return raw


def route_task(
    *,
    llm: Any,
    system_prompt: str,
    user_input: str,
    tasks: dict[str, Any],
    skills_index: str,
    observe_tools: dict[str, Callable[..., Any]],
    max_steps: int = 3,
    invoke_config: dict[str, Any] | None = None,
    context_options: ContextCompressionOptions | None = None,
    recent_rounds_payload: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return ControllerAgent(
        llm=llm,
        system_prompt=system_prompt,
        max_steps=max_steps,
        context_options=context_options,
    ).run(
        user_input=user_input,
        tasks=tasks,
        skills_index=str(skills_index).strip(),
        observe_tools=observe_tools,
        invoke_config=invoke_config,
        recent_rounds_payload=recent_rounds_payload,
    )
