from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jsonschema import ValidationError, validate

from ..protocol_constants import ARG_INPUT, ARG_NAME, TOOL_SKILL_TOOL


_OBSERVE_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action_kind": {"const": "observe"},
        "tool": {"const": "read"},
        "args": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["action_kind", "tool", "args", "reason"],
    "additionalProperties": False,
}

_OBSERVE_LS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action_kind": {"const": "observe"},
        "tool": {"const": "ls"},
        "args": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["action_kind", "tool", "args", "reason"],
    "additionalProperties": False,
}

_OBSERVE_BUILD_VIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action_kind": {"const": "observe"},
        "tool": {"const": "build_context_view"},
        "args": {
            "type": "object",
            "properties": {
                "task_limit": {"type": ["integer", "null"], "minimum": 1},
                "include_user_input": {"type": ["boolean", "integer", "string"]},
                "include_task": {"type": ["boolean", "integer", "string"]},
                "include_reply": {"type": ["boolean", "integer", "string"]},
                "include_trace": {"type": ["boolean", "integer", "string"]},
                "compress": {"type": ["boolean", "integer", "string"]},
                "compress_target_tokens": {"type": ["integer", "null"], "minimum": 80},
            },
            "additionalProperties": False,
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["action_kind", "tool", "args", "reason"],
    "additionalProperties": False,
}

_OBSERVE_PREVIOUS_FAILED_TRACK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action_kind": {"const": "observe"},
        "tool": {"const": "previous_failed_track"},
        "args": {
            "type": "object",
            "maxProperties": 0,
            "additionalProperties": False,
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["action_kind", "tool", "args", "reason"],
    "additionalProperties": False,
}

_OBSERVE_BEIJING_TIME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action_kind": {"const": "observe"},
        "tool": {"const": "beijing_time"},
        "args": {
            "type": "object",
            "maxProperties": 0,
            "additionalProperties": False,
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["action_kind", "tool", "args", "reason"],
    "additionalProperties": False,
}

_OBSERVE_SKILL_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action_kind": {"const": "observe"},
        "tool": {"const": TOOL_SKILL_TOOL},
        "args": {
            "type": "object",
            "properties": {
                ARG_NAME: {"type": "string", "minLength": 1},
                ARG_INPUT: {"type": "object"},
            },
            "required": [ARG_NAME, ARG_INPUT],
            "additionalProperties": False,
        },
        "reason": {"type": "string", "minLength": 1},
    },
    "required": ["action_kind", "tool", "args", "reason"],
    "additionalProperties": False,
}

CONTROLLER_ALLOWED_ACTION_KINDS = ("observe", "generate_task")
CONTROLLER_ALLOWED_OBSERVE_TOOLS = (
    "read",
    "ls",
    "build_context_view",
    "previous_failed_track",
    "beijing_time",
    TOOL_SKILL_TOOL,
)
CONTROLLER_ALLOWED_TASK_TYPES = ("executor", "functest", "accutest", "perftest")

CONTROLLER_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "oneOf": [
        _OBSERVE_READ_SCHEMA,
        _OBSERVE_LS_SCHEMA,
        _OBSERVE_BUILD_VIEW_SCHEMA,
        _OBSERVE_PREVIOUS_FAILED_TRACK_SCHEMA,
        _OBSERVE_BEIJING_TIME_SCHEMA,
        _OBSERVE_SKILL_TOOL_SCHEMA,
        {
            "type": "object",
            "properties": {
                "action_kind": {"const": "generate_task"},
                "task_type": {
                    "type": "string",
                    "enum": list(CONTROLLER_ALLOWED_TASK_TYPES),
                },
                "task_content": {"type": "string", "minLength": 1},
                "reason": {"type": "string", "minLength": 1},
            },
            "required": ["action_kind", "task_type", "task_content", "reason"],
            "additionalProperties": False,
        },
    ],
}

CONTROLLER_OUTPUT_CONSTRAINTS: dict[str, Any] = {
    "output_format": "json_object",
    "action_kind_enum": list(CONTROLLER_ALLOWED_ACTION_KINDS),
    "observe_required": ["action_kind", "tool", "args", "reason"],
    "observe_tool_enum": list(CONTROLLER_ALLOWED_OBSERVE_TOOLS),
    "generate_task_required": ["action_kind", "task_type", "task_content", "reason"],
    "forbid_additional_properties": True,
    "observe_tool_args_required": {
        "read": ["path"],
        "ls": ["path"],
        "build_context_view": [],
        "previous_failed_track": [],
        "beijing_time": [],
        TOOL_SKILL_TOOL: [ARG_NAME, ARG_INPUT],
    },
}


def validate_controller_action_payload(action: dict[str, Any]) -> None:
    validate(instance=action, schema=CONTROLLER_ACTION_SCHEMA)


def validate_controller_action_dict(action: dict[str, Any]) -> tuple[bool, list[str]]:
    try:
        validate_controller_action_payload(action)
    except ValidationError as exc:
        return False, [exc.message]
    return True, []


@dataclass
class ControllerAction:
    # 控制器单个步骤动作：要么是 observe，要么是 generate_task。
    action_kind: str
    reason: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    task_type: str | None = None
    task_content: str | None = None
    observation: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ControllerAction":
        # 从模型输出或持久化字典恢复动作对象。
        return cls(
            action_kind=str(payload.get("action_kind", "")).strip(),
            reason=str(payload.get("reason", "")).strip(),
            tool=(str(payload.get("tool", "")).strip() or None),
            args=payload.get("args", {}) if isinstance(payload.get("args"), dict) else {},
            task_type=(str(payload.get("task_type", "")).strip() or None),
            task_content=(str(payload.get("task_content", "")).strip() or None),
            observation=(str(payload.get("observation", "")).strip() or None),
        )

    def to_dict(self) -> dict[str, Any]:
        # 统一动作对象的序列化格式。
        return {
            "action_kind": self.action_kind,
            "reason": self.reason,
            "tool": self.tool,
            "args": self.args,
            "task_type": self.task_type,
            "task_content": self.task_content,
            "observation": self.observation,
        }
