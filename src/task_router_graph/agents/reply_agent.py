from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .agent_utils import extract_text, merge_invoke_config, parse_json_object, replace_last


_REPLY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "minLength": 1},
    },
    "required": ["reply"],
    "additionalProperties": False,
}


class ReplyAgent:
    def __init__(self, *, llm: Any, system_prompt: str) -> None:
        self.llm = llm
        self.system_prompt = system_prompt

    def run(
        self,
        *,
        user_input: str,
        final_task: dict[str, Any],
        environment_view: dict[str, Any],
        invoke_config: dict[str, Any] | None = None,
    ) -> str:
        rendered_system_prompt = self._render_system_prompt(
            user_input=user_input,
            final_task=final_task,
            environment_view=environment_view,
        )
        llm = self.llm.bind(
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "reply_output",
                    "strict": True,
                    "schema": _REPLY_OUTPUT_SCHEMA,
                },
            }
        )

        response = llm.invoke(
            [
                SystemMessage(content=rendered_system_prompt),
                HumanMessage(content="请只输出一个合法 JSON 对象，不要输出解释或 Markdown。"),
            ],
            config=merge_invoke_config(
                invoke_config,
                run_name="task-router.reply.llm",
                tags=["task-router", "reply"],
            ),
        )

        text = extract_text(response.content if hasattr(response, "content") else str(response))
        payload = parse_json_object(text)

        reply = str(payload.get("reply", "")).strip()
        if not reply:
            raise ValueError("reply is empty")
        return reply

    def _render_system_prompt(
        self,
        *,
        user_input: str,
        final_task: dict[str, Any],
        environment_view: dict[str, Any],
    ) -> str:
        rendered = self.system_prompt
        rendered = replace_last(rendered, "{{USER_INPUT}}", user_input)
        rendered = replace_last(rendered, "{{FINAL_TASK_JSON}}", json.dumps(final_task, ensure_ascii=False, indent=2))
        rendered = replace_last(rendered, "{{ENVIRONMENT_JSON}}", json.dumps(environment_view, ensure_ascii=False, indent=2))
        return rendered

def run_reply_task(
    *,
    llm: Any,
    system_prompt: str,
    user_input: str,
    final_task: dict[str, Any],
    environment_view: dict[str, Any],
    invoke_config: dict[str, Any] | None = None,
) -> str:
    return ReplyAgent(llm=llm, system_prompt=system_prompt).run(
        user_input=user_input,
        final_task=final_task,
        environment_view=environment_view,
        invoke_config=invoke_config,
    )
