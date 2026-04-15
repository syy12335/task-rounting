from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .agent_utils import extract_text, merge_invoke_config, parse_json_object, replace_last


_FAILURE_DIAGNOSIS_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "failure_diagnosis": {"type": "string", "minLength": 1},
    },
    "required": ["failure_diagnosis"],
    "additionalProperties": False,
}


class FailureDiagnosisAgent:
    def __init__(self, *, llm: Any, system_prompt: str) -> None:
        self.llm = llm
        self.system_prompt = system_prompt

    def run(
        self,
        *,
        task: dict[str, Any],
        track: list[dict[str, Any]],
        invoke_config: dict[str, Any] | None = None,
    ) -> str:
        rendered_system_prompt = self._render_system_prompt(task=task, track=track)
        llm = self.llm.bind(
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "failure_diagnosis_output",
                    "strict": True,
                    "schema": _FAILURE_DIAGNOSIS_OUTPUT_SCHEMA,
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
                run_name="task-router.failure-analysis.llm",
                tags=["task-router", "failure-analysis"],
            ),
        )

        text = extract_text(response.content if hasattr(response, "content") else str(response))
        payload = parse_json_object(text)

        analysis = str(payload.get("failure_diagnosis", "")).strip()
        if not analysis:
            raise ValueError("failure_diagnosis is empty")
        return analysis

    def _render_system_prompt(self, *, task: dict[str, Any], track: list[dict[str, Any]]) -> str:
        rendered = self.system_prompt
        rendered = replace_last(rendered, "{{TASK_JSON}}", json.dumps(task, ensure_ascii=False, indent=2))
        rendered = replace_last(rendered, "{{TRACK_JSON}}", json.dumps(track, ensure_ascii=False, indent=2))
        return rendered

def run_failure_diagnosis_task(
    *,
    llm: Any,
    system_prompt: str,
    task: dict[str, Any],
    track: list[dict[str, Any]],
    invoke_config: dict[str, Any] | None = None,
) -> str:
    return FailureDiagnosisAgent(llm=llm, system_prompt=system_prompt).run(
        task=task,
        track=track,
        invoke_config=invoke_config,
    )
