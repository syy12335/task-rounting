from __future__ import annotations

import json
from typing import Any


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part.strip() for part in parts if part.strip()).strip()
    return str(content).strip()


def parse_json_object(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Model output JSON is not an object")
    return payload


def build_rounds_context(rounds: list[Any], limit: int = 5) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for round_item in rounds[-limit:]:
        controller_trace: list[dict[str, Any]] = []
        for action in round_item.controller_trace:
            controller_trace.append(
                {
                    "action_kind": action.action_kind,
                    "reason": action.reason,
                    "tool": action.tool,
                    "args": action.args,
                    "task_type": action.task_type,
                    "task_content": action.task_content,
                    "observation": action.observation,
                }
            )

        context.append(
            {
                "round": round_item.round,
                "user_input": round_item.user_input,
                "controller_trace": controller_trace,
                "task": {
                    "type": round_item.task.type,
                    "content": round_item.task.content,
                    "status": round_item.task.status,
                    "result": round_item.task.result,
                },
                "reply": round_item.reply,
            }
        )
    return context
